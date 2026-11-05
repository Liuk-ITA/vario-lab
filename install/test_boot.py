import sys,types,tempfile,unittest,json,io
from pathlib import Path
from unittest.mock import patch
from contextlib import redirect_stdout
import boot_control as boot

class NVS:
    values={'boot_option':1};writes=[]
    def __init__(self,name):assert name=='uiflow'
    def get_u8(self,key):
        if key not in self.values:raise OSError(2)
        return self.values[key]
    def set_u8(self,key,value):self.values[key]=value;self.writes.append((key,value))
    def commit(self):pass

class BootTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.base=Path(self.temp.name);self.old=boot.BASE;boot.BASE=str(self.base)
        NVS.values={'boot_option':1};NVS.writes=[]
        self.mods=patch.dict(sys.modules,{'esp32':types.SimpleNamespace(NVS=NVS)});self.mods.start()
        (self.base/'stick_vario_app.py').write_text('SV_APP_STARTED=True')
    def tearDown(self):self.mods.stop();boot.BASE=self.old;self.temp.cleanup()
    def test_enable_restore_and_reenable(self):
        original='print("old user main")\n';(self.base/'main.py').write_text(original)
        (self.base/'boot.py').write_text('UNCHANGED')
        self.assertFalse(boot.sv_boot()['main_owned'])
        info=boot.sv_boot('enable');self.assertEqual(info['boot_option'],0);self.assertTrue(info['main_owned'])
        self.assertEqual((self.base/'stick_vario_main_before_autorun.py').read_text(),original)
        boot.sv_boot('mode',2);self.assertEqual(NVS.values['boot_option'],2)
        info=boot.sv_boot('restore');self.assertFalse(info['main_owned']);self.assertEqual(info['boot_option'],1)
        self.assertEqual((self.base/'main.py').read_text(),original);self.assertEqual((self.base/'boot.py').read_text(),'UNCHANGED')
        self.assertTrue(boot.sv_boot('enable')['main_owned'])
        self.assertEqual(set(k for k,v in NVS.writes),{'boot_option'})
    def test_no_main_restore_and_invalid_mode(self):
        boot.sv_boot('enable');boot.sv_boot('restore');self.assertFalse((self.base/'main.py').exists())
        for value in (-1,3,True,'0'):
            with self.assertRaises(ValueError):boot.sv_boot('mode',value)
        (self.base/'stick_vario_app.py').unlink()
        with self.assertRaises(ValueError):boot.sv_boot('enable')
    def test_pending_ota_and_interrupted_enable(self):
        (self.base/'main.py').write_text('original')
        (self.base/'main_ota_temp.py').write_text('pending')
        with self.assertRaisesRegex(ValueError,'pendente'):boot.sv_boot('enable')
        self.assertEqual((self.base/'main.py').read_text(),'original')
        (self.base/'main_ota_temp.py').unlink()
        boot.sv_boot('enable')
        # Model power loss after backup/state commit, before launcher promotion.
        (self.base/'main.py').write_text('original')
        self.assertTrue(boot.sv_boot('enable')['main_owned'])
    def test_refuse_foreign_main_or_corrupt_backup(self):
        (self.base/'main.py').write_text('original')
        boot.sv_boot('enable');(self.base/'stick_vario_main_before_autorun.py').write_text('corrupt')
        with self.assertRaisesRegex(ValueError,'Backup'):boot.sv_boot('restore')
        (self.base/'main.py').write_text('other project')
        with self.assertRaisesRegex(ValueError,'non e'):boot.sv_boot('restore')
        with self.assertRaises(ValueError):boot.sv_boot('enable')
    def run_launcher(self,pressed=False,fail=False):
        if fail:(self.base/'stick_vario_app.py').write_text("raise RuntimeError('sensor missing')")
        clock=[0]
        def ticks():clock[0]+=10;return clock[0]
        class Reset(Exception):pass
        def reset():raise Reset()
        fake_time=types.SimpleNamespace(ticks_ms=ticks,ticks_add=lambda a,b:a+b,ticks_diff=lambda a,b:a-b,sleep_ms=lambda ms:None)
        fake_m5=types.SimpleNamespace(begin=lambda:None,update=lambda:None,BtnB=types.SimpleNamespace(isPressed=lambda:pressed))
        ctx={'__name__':'__main__'}
        with patch.dict(sys.modules,{'time':fake_time,'M5':fake_m5,'machine':types.SimpleNamespace(reset=reset)}),redirect_stdout(io.StringIO()):
            try:exec(boot.LAUNCHER.replace('/flash',str(self.base).replace('\\','/')),ctx)
            except Reset:ctx['RESET']=True
        return ctx
    def test_launcher_normal_recovery_and_error(self):
        self.assertTrue(self.run_launcher()['SV_APP_STARTED'])
        NVS.values['boot_option']=0
        recovered=self.run_launcher(True);self.assertTrue(recovered['RESET']);self.assertNotIn('SV_APP_STARTED',recovered);self.assertEqual(NVS.values['boot_option'],1)
        NVS.values['boot_option']=0
        self.assertNotIn('SV_APP_STARTED',self.run_launcher(fail=True));self.assertEqual(NVS.values['boot_option'],1)

if __name__=='__main__':unittest.main()
