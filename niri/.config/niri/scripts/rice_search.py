"""Bounded filename/project index and arithmetic parser. No file content is read."""
import ast,json,math,operator,os,re,sqlite3,time
from pathlib import Path
from contextlib import contextmanager
from rice_common import STATE,read_json,write_json
EXCLUDED={'.git','.hg','.svn','.cache','.ssh','.aws','.gnupg','.kube','.config','.local','node_modules','venv','.venv','env','.env','__pycache__','target','build','dist','site-packages','anaconda3','miniconda3','snap','pgdata','pg_wal','postgresql','databases','database','backups','backup','rice-backups','run','.secrets','secrets','credentials','.idea','.vscode'}
PRIVATE=re.compile(r'(^\.env($|\.)|credential|secret|password|token|^id_(rsa|ed25519)|\.(pem|key|kdbx|sqlite3?|db|dump|sql|p12|pfx|pgpass)$)',re.I)
MARKERS={'.git','pom.xml','package.json','pyproject.toml','Cargo.toml','go.mod','CMakeLists.txt','default.nix'}

def cache():
    root=Path(os.environ.get('XDG_CACHE_HOME',Path.home()/'.cache'))/'niri-rice'
    root.mkdir(parents=True,exist_ok=True,mode=0o700);root.chmod(0o700)
    return root

def config():
    return read_json(STATE/'launcher.json',{'file_roots':[],'project_roots':[],'favorite_projects':[],'exclude_dirs':[],'max_files':50000,'max_depth':7})

def suggested_roots():
    """One bounded directory discovery, performed only on initial index setup."""
    home=Path.home();file_roots=[];project_roots=[];budget=2500
    import subprocess
    for kind in ['DOCUMENTS','DOWNLOAD']:
        try:
            p=Path(subprocess.check_output(['xdg-user-dir',kind],text=True,timeout=2).strip())
            if p.is_dir() and p!=home:file_roots.append(str(p))
        except Exception:pass
    for base in sorted(home.iterdir()):
        if not base.is_dir() or base.is_symlink() or base.name.startswith('.') or base.name.lower() in EXCLUDED or 'backup' in base.name.casefold():continue
        stack=[(base,0)];found=False
        while stack and budget>0:
            path,depth=stack.pop();budget-=1
            try:
                names=set(os.listdir(path))
                if MARKERS&names:found=True;break
                if depth<3:
                    for item in os.scandir(path):
                        if item.is_dir(follow_symlinks=False) and item.name.lower() not in EXCLUDED and not item.name.startswith('.'):stack.append((Path(item.path),depth+1))
            except OSError:continue
        if found:project_roots.append(str(base))
        if budget<=0:break
    return list(dict.fromkeys(file_roots)),project_roots[:6]

def initialize():
    if not (STATE/'launcher.json').exists():
        files,projects=suggested_roots()
        write_json(STATE/'launcher.json',{**config(),'file_roots':files,'project_roots':projects})
    return config()

@contextmanager
def database():
    old=os.umask(0o077)
    try:db=sqlite3.connect(cache()/'search.sqlite3',timeout=2)
    finally:os.umask(old)
    db.execute('CREATE TABLE IF NOT EXISTS entries (path TEXT PRIMARY KEY, name TEXT, kind TEXT, mtime REAL, generation REAL)')
    db.execute('CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY,value TEXT)')
    try:
        with db:yield db
    finally:db.close()

def build_index():
    prefs=initialize();limit=max(1,min(100000,int(prefs.get('max_files',50000))));maxdepth=max(1,min(12,int(prefs.get('max_depth',7))))
    excluded=EXCLUDED|set(prefs.get('exclude_dirs',[]));generation=time.time();count=0;dirs=0;seen=set()
    with database() as db:
        for kind,key in [('file','file_roots'),('project','project_roots')]:
            for root in prefs.get(key,[])[:8]:
                root=Path(root).expanduser()
                # Never scan a whole filesystem/home implicitly or follow links.
                if root in [Path('/'),Path.home()] or not root.is_dir() or root.is_symlink():continue
                stack=[(root,0)]
                while stack and count<limit and dirs<15000:
                    path,depth=stack.pop();dirs+=1
                    try:items=list(os.scandir(path))
                    except OSError:continue
                    names={item.name for item in items}
                    if kind=='project' and MARKERS&names:
                        db.execute('INSERT INTO entries VALUES (?,?,?,?,?) ON CONFLICT(path) DO UPDATE SET name=excluded.name,kind=excluded.kind,mtime=excluded.mtime,generation=excluded.generation',(str(path),path.name,'project',path.stat().st_mtime,generation));count+=1
                    for item in items:
                        if item.name.lower() in excluded or item.name.startswith('.') or PRIVATE.search(item.name) or item.is_symlink():continue
                        try:
                            if item.is_dir(follow_symlinks=False) and depth<maxdepth:stack.append((Path(item.path),depth+1))
                            elif kind=='file' and item.is_file(follow_symlinks=False) and os.access(item.path,os.R_OK) and item.path not in seen and count<limit:
                                seen.add(item.path);db.execute('INSERT INTO entries VALUES (?,?,?,?,?) ON CONFLICT(path) DO UPDATE SET name=excluded.name,mtime=excluded.mtime,generation=excluded.generation',(item.path,item.name,'file',item.stat().st_mtime,generation));count+=1
                        except OSError:continue
        db.execute('DELETE FROM entries WHERE generation!=?',(generation,))
        db.execute('INSERT OR REPLACE INTO metadata VALUES (?,?)',('updated',str(time.time())))
    return count

def search(query,kind=None,limit=12):
    if not (cache()/'search.sqlite3').exists():return []
    # Escape LIKE wildcards and keep every query as bound data.
    escaped=query.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')
    with database() as db:
        result=db.execute("SELECT path,name,kind FROM entries WHERE name LIKE ? ESCAPE '\\' AND (? IS NULL OR kind=?) ORDER BY name COLLATE NOCASE LIMIT ?",('%'+escaped+'%',kind,kind,limit)).fetchall()
    return [item for item in result if Path(item[0]).exists() and os.access(item[0],os.R_OK)]

def calculate(expression):
    if len(expression)>128:raise ValueError('Expressão longa demais')
    tree=ast.parse(expression.replace(',','.'),mode='eval')
    if len(list(ast.walk(tree)))>40:raise ValueError('Expressão complexa demais')
    binary={ast.Add:operator.add,ast.Sub:operator.sub,ast.Mult:operator.mul,ast.Div:operator.truediv,ast.FloorDiv:operator.floordiv,ast.Mod:operator.mod,ast.Pow:operator.pow}
    def visit(node):
        if isinstance(node,ast.Constant) and type(node.value) in (int,float):result=node.value
        elif isinstance(node,ast.UnaryOp) and isinstance(node.op,(ast.UAdd,ast.USub)):result=visit(node.operand)*(1 if isinstance(node.op,ast.UAdd) else -1)
        elif isinstance(node,ast.BinOp) and type(node.op) in binary:
            left,right=visit(node.left),visit(node.right)
            if isinstance(node.op,ast.Pow) and (abs(right)>10 or abs(left)>1e6):raise ValueError('Potência fora do limite')
            result=binary[type(node.op)](left,right)
        else:raise ValueError('Use somente números e operações aritméticas')
        if type(result) not in (int,float) or not math.isfinite(result) or abs(result)>1e100:raise ValueError('Resultado fora do limite')
        return result
    value=visit(tree.body)
    return format(value,'.12g') if isinstance(value,float) else str(value)


def project_paths(paths,query=''):
    """Fetch pinned/recent projects directly, even outside the first result page."""
    paths=list(dict.fromkeys(paths))[:40]
    if not paths or not (cache()/'search.sqlite3').exists():return []
    with database() as db:
        rows=db.execute('SELECT path,name,kind FROM entries WHERE kind=? AND path IN ('+','.join('?' for _ in paths)+')',['project',*paths]).fetchall()
    return [row for row in rows if query.casefold() in row[1].casefold() and Path(row[0]).is_dir()]
