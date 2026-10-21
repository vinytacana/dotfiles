"""Offline regression checks for privacy boundaries, safe parsing and bounded indexing."""
import os,sys,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
sys.dont_write_bytecode=True
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import rice_clipboard as clipboard
import rice_search as search
from rice_common import write_json

class V4Tests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.base=Path(self.temp.name)
        (self.base/'runtime').mkdir()
        self.env=patch.dict(os.environ,{'XDG_RUNTIME_DIR':str(self.base/'runtime'),'XDG_CACHE_HOME':str(self.base/'cache')});self.env.start()
        self.state=self.base/'state';self.patches=[patch.object(clipboard,'STATE',self.state),patch.object(search,'STATE',self.state)]
        for p in self.patches:p.start()
    def tearDown(self):
        for p in self.patches:p.stop()
        self.env.stop();self.temp.cleanup()
    def test_arithmetic_rejects_code_and_excessive_work(self):
        self.assertEqual(search.calculate('2*(3+4)'),'14')
        self.assertEqual(search.calculate('1,5+2'),'3.5')
        for text in ["__import__('os').system('id')",'9**999999','(1).__class__','[x for x in []]','1/0']:
            with self.assertRaises((ValueError,ArithmeticError,SyntaxError,OverflowError)):search.calculate(text)
    def test_sensitive_offers_and_apps_are_rejected(self):
        self.assertFalse(clipboard.store(b'fake-password',['text/plain','x-kde-passwordManagerHint'],'Alacritty'))
        self.assertFalse(clipboard.store(b'fake-password',['text/plain'],'org.keepassxc.KeePassXC'))
        self.assertFalse(clipboard.store(b'fake-password',['text/plain'],'Alacritty','sensitive'))
        self.assertFalse(clipboard.store(b'a'*16385,['text/plain'],'Alacritty'))
        self.assertFalse(clipboard.store(b'\x00binary',['image/png'],'Alacritty'))
        self.assertEqual(clipboard.entries(),[])
    def test_clipboard_bounds_expiry_permissions_and_deletion(self):
        for _ in range(2):self.assertTrue(clipboard.store(b'test duplicate',['text/plain'],'Alacritty'))
        self.assertEqual(len(clipboard.entries()),1)
        for number in range(50):clipboard.store(f'test {number}'.encode(),['text/plain'],'Alacritty')
        self.assertEqual(len(clipboard.entries()),40)
        self.assertEqual((clipboard.directory()/'history.sqlite3').stat().st_mode&0o777,0o600)
        self.assertEqual(clipboard.directory().stat().st_mode&0o777,0o700)
        with clipboard.connect() as db:db.execute('UPDATE items SET copied=?',(time.time()-3601,))
        self.assertEqual(clipboard.entries(),[])
        clipboard.store(b'delete me',['text/plain'],'Alacritty');clipboard.delete();self.assertEqual(clipboard.entries(),[])
    def test_pause_blocks_storage(self):
        self.state.mkdir();(self.state/'clipboard-disabled').touch()
        self.assertFalse(clipboard.store(b'test',['text/plain'],'Alacritty'))
    def test_index_excludes_secrets_caches_and_symlinks(self):
        root=self.base/'files';root.mkdir();project=root/'test project';project.mkdir();(project/'.git').mkdir()
        filename=root/"file ' ; $(inert).txt";filename.write_text('test')
        (root/'.env').write_text('fake-secret')
        for name in ['node_modules','.aws','pgdata']:
            (root/name).mkdir();(root/name/'hidden.txt').write_text('excluded')
        (root/'link.txt').symlink_to(filename)
        write_json(self.state/'launcher.json',{'file_roots':[str(root)],'project_roots':[str(root)],'max_files':100,'max_depth':4,'exclude_dirs':[]})
        search.build_index()
        self.assertEqual(search.search('$(inert)','file')[0][0],str(filename))
        self.assertEqual(len(search.search('hidden','file')),0)
        self.assertEqual(search.search('.env','file'),[])
        self.assertEqual(search.search('link','file'),[])
        self.assertEqual(search.search('test project','project')[0][0],str(project))
        filename.unlink();search.build_index();self.assertEqual(search.search('$(inert)','file'),[])
    def test_notification_retention_uses_count_only(self):
        import runpy,subprocess
        calls=[]
        def client(args,**kwargs):
            calls.append(args[-1]);return '101' if args[-1]=='--count' else ''
        script=Path(__file__).resolve().parents[1]/'scripts/notification-prune'
        with patch.dict(os.environ,{'XDG_CURRENT_DESKTOP':'niri'}),patch.object(subprocess,'check_output',side_effect=client):runpy.run_path(str(script),run_name='retention_test')
        self.assertIn('--close-all',calls)
        self.assertNotIn('--subscribe',calls)
    def test_rollback_simulates_and_refuses_later_edits(self):
        import json,hashlib,subprocess,tarfile
        repo=self.base/'repo';repo.mkdir();source=repo/'config';source.write_text('installed')
        archive=self.base/'v3.tar.gz'
        with tarfile.open(archive,'w:gz') as saved:saved.add(source,arcname='config')
        def record(text):return {'sha256':hashlib.sha256(text.encode()).hexdigest(),'mode':0o644}
        receipt={'repository':str(repo),'archive_sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'files':{'config':{'before':record('before'),'installed':record('installed')}},'new_links':{},'services':[]}
        (self.base/'receipt.json').write_text(json.dumps(receipt))
        script=Path(__file__).resolve().parents[1]/'scripts/rice-rollback'
        result=subprocess.run([sys.executable,str(script),str(self.base)],capture_output=True,text=True)
        self.assertEqual(result.returncode,0);self.assertIn('SIMULATION ONLY',result.stdout);self.assertEqual(source.read_text(),'installed')
        source.write_text('later edit')
        result=subprocess.run([sys.executable,str(script),str(self.base)],capture_output=True,text=True)
        self.assertNotEqual(result.returncode,0);self.assertIn('Later changes',result.stderr);self.assertEqual(source.read_text(),'later edit')
if __name__=='__main__':unittest.main(verbosity=2)
