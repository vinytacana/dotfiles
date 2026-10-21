"""Bounded text-only history in the private runtime tmpfs; never logs payloads."""
import hashlib,json,os,sqlite3,time
from pathlib import Path
from contextlib import contextmanager
from rice_common import ROOT,STATE,read_json

def config():
    result=read_json(ROOT/'clipboard-defaults.json',{})
    result.update(read_json(STATE/'clipboard.json',{}))
    result['max_entries']=max(1,min(100,int(result['max_entries'])))
    result['max_bytes']=max(128,min(65536,int(result['max_bytes'])))
    result['ttl_seconds']=max(60,min(3600,int(result['ttl_seconds'])))
    return result

def directory():
    path=Path(os.environ['XDG_RUNTIME_DIR'])/'niri-rice/clipboard'
    path.mkdir(parents=True,exist_ok=True,mode=0o700);path.chmod(0o700)
    return path

@contextmanager
def connect():
    path=directory()/'history.sqlite3'
    # umask before sqlite creates the database and any journal file.
    old=os.umask(0o077)
    try:db=sqlite3.connect(path,timeout=2)
    finally:os.umask(old)
    path.chmod(0o600);db.execute('PRAGMA secure_delete=ON')
    db.execute('CREATE TABLE IF NOT EXISTS items (digest TEXT PRIMARY KEY, text TEXT NOT NULL, copied REAL NOT NULL)')
    try:
        with db:yield db
    finally:db.close()

def prune(db):
    prefs=config();db.execute('DELETE FROM items WHERE copied < ?',(time.time()-prefs['ttl_seconds'],))
    db.execute('DELETE FROM items WHERE digest NOT IN (SELECT digest FROM items ORDER BY copied DESC LIMIT ?)',(prefs['max_entries'],))

def store(data,types,app_id,clipboard_state='data'):
    prefs=config()
    if (STATE/'clipboard-disabled').exists() or clipboard_state in {'sensitive','nil','clear'}:return False
    if any(x.casefold() in app_id.casefold() for x in prefs['excluded_apps']):return False
    if any(x.casefold() in t.casefold() for x in prefs['excluded_mime'] for t in types):return False
    if len(data)>prefs['max_bytes'] or b'\0' in data:return False
    try:text=data.decode('utf-8')
    except UnicodeDecodeError:return False
    if not text.strip():return False
    with connect() as db:
        db.execute('INSERT INTO items VALUES (?,?,?) ON CONFLICT(digest) DO UPDATE SET copied=excluded.copied',(hashlib.sha256(data).hexdigest(),text,time.time()))
        prune(db)
    return True

def entries(search=''):
    with connect() as db:
        prune(db)
        items=db.execute('SELECT digest,text,copied FROM items ORDER BY copied DESC').fetchall()
    return [item for item in items if search.casefold() in item[1].casefold()]

def delete(digest=None):
    with connect() as db:
        if digest:db.execute('DELETE FROM items WHERE digest=?',(digest,))
        else:db.execute('DELETE FROM items')
    if digest is None:
        with connect() as db:db.execute('VACUUM')
