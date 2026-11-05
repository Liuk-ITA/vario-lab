import hashlib,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from mirror_release import mirror

class MirrorTests(unittest.TestCase):
    def test_copy_release_with_integrity(self):
        app=b'import M5\n';doc={'schema':1,'kind':'micropython-app','board':'M5StickS3','version':'test','app':{'url':'stick_vario_ram.py','sha256':hashlib.sha256(app).hexdigest(),'bytes':len(app)}}
        release={'tag_name':'v1','html_url':'https://github.com/o/r/releases/tag/v1','assets':[{'name':'stick-vario.release.json','browser_download_url':'https://example.test/manifest'},{'name':'stick_vario_ram.py','browser_download_url':'https://example.test/app'}]}
        def fetch(url,limit):return json.dumps(release).encode() if 'api.github.com' in url else json.dumps(doc).encode() if url.endswith('manifest') else app
        with tempfile.TemporaryDirectory() as d,patch('mirror_release.download',fetch):
            mirror('o/r','v1',d);self.assertEqual((Path(d)/'stick_vario_ram.py').read_bytes(),app)
            self.assertEqual(json.loads((Path(d)/'stick-vario.release.json').read_text())['origin']['tag'],'v1')
            doc['app']['sha256']='0'*64
            with self.assertRaisesRegex(ValueError,'SHA'):mirror('o/r','v1',d)
            doc['app']['url']='../../boot.py'
            with self.assertRaisesRegex(ValueError,'artifact'):mirror('o/r','v1',d)

if __name__=='__main__':unittest.main()
