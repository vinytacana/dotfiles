"""Preset invariants and transactional selection; service calls use a fake systemctl."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import contextlib
import io
import runpy
from types import SimpleNamespace
from unittest.mock import patch
sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import waybar_presets as presets


class Presets(unittest.TestCase):
    def test_disabled_dock_does_not_load_favorites_or_icons(self):
        import rice_common
        with tempfile.TemporaryDirectory() as folder:
            base=Path(folder);state=base/'state';state.mkdir();(state/'dock-disabled').touch()
            with patch.dict(os.environ,{'XDG_RUNTIME_DIR':str(base)}),patch.object(rice_common,'STATE',state),patch.object(rice_common,'favorites',side_effect=AssertionError('disabled dock must not read favorites')),patch.object(rice_common,'icon_file',side_effect=AssertionError('disabled dock must not decode icons')),patch.object(subprocess,'run',side_effect=AssertionError('disabled dock must not start icon helpers')),patch.object(os,'execv'):
                runpy.run_path(str(ROOT/'scripts/waybar-session'),run_name='bar_generator_test')
            rendered=json.loads((base/'niri-rice/waybar.json').read_text())
            self.assertEqual([bar['name'] for bar in rendered],['top'])

    def test_dock_decodes_icons_in_one_collected_helper_before_exec(self):
        import rice_common
        import subprocess
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as folder:
            base=Path(folder);state=base/'state';state.mkdir()
            identities=['niri-settings.desktop','org.gnome.Nautilus.desktop']
            def decode(args,**options):
                self.assertEqual(args[-1],'--icons')
                self.assertEqual(json.loads(options['input']),identities)
                self.assertTrue(options['check']);self.assertEqual(options['timeout'],15)
                return SimpleNamespace(stdout=json.dumps({identity:str(base/(str(i)+'.png')) for i,identity in enumerate(identities)}))
            with patch.dict(os.environ,{'XDG_RUNTIME_DIR':str(base)}),patch.object(rice_common,'STATE',state), \
                 patch.object(rice_common,'favorites',return_value=identities),patch.object(rice_common,'desktop',return_value=object()), \
                 patch.object(rice_common,'icon_file',side_effect=AssertionError('decoder must not run in the exec parent')), \
                 patch.object(subprocess,'run',side_effect=decode) as helper,patch.object(os,'execv') as execute:
                runpy.run_path(str(ROOT/'scripts/waybar-session'),run_name='bar_generator_test')
            helper.assert_called_once();execute.assert_called_once()
            self.assertIn('0.png',(base/'niri-rice/waybar.css').read_text())
            rendered=json.loads((base/'niri-rice/waybar.json').read_text())
            self.assertEqual([bar['name'] for bar in rendered],['top','dock'])

    def test_media_has_exactly_one_track_or_idle_label(self):
        for identity in presets.profiles():
            if identity=='original':continue
            top=presets.render(identity)[0][0]
            self.assertEqual(top['group/media']['modules'],['custom/media-idle','custom/media-previous','custom/media-play','custom/media-next'])
            self.assertNotIn('mpris#track',top)
            self.assertNotIn('interval',top['custom/media-idle'])
            self.assertFalse(top['custom/media-idle']['exec-on-event'])
            self.assertEqual(len([n for n in top if n.startswith('mpris#')]),0)
            for name in ['previous','play','next']:
                module=top['custom/media-'+name]
                self.assertTrue(module['hide-empty-text'])
                self.assertEqual(module['signal'],12)
                self.assertNotIn('interval',module)
                self.assertIn('media-player ',module['on-click'])

    def test_idle_player_reuses_desktop_focus_and_launch(self):
        spotify=runpy.run_path(str(ROOT/'scripts/media-player'))['spotify']
        with patch.dict(spotify.__globals__,{'desktop':lambda identity:identity=='com.spotify.Client.desktop','open_or_focus':lambda identity:chosen.append(identity)}):
            chosen=[]
            spotify()
            self.assertEqual(chosen,['com.spotify.Client.desktop'])
        with patch.dict(spotify.__globals__,{'desktop':lambda identity:identity=='spotify.desktop','open_or_focus':lambda identity:chosen.append(identity)}):
            chosen=[]
            spotify()
            self.assertEqual(chosen,['spotify.desktop'])

    def test_calendar_and_dock_preserved_in_every_preset(self):
        baseline=json.loads((ROOT/'waybar.jsonc').read_text())
        for identity in presets.profiles():
            bars,css=presets.render(identity)
            self.assertEqual([bar['name'] for bar in bars],['top','dock'])
            self.assertEqual(bars[0]['modules-center'],['clock'])
            self.assertEqual(bars[0]['clock'],baseline[0]['clock'])
            self.assertEqual(bars[1],{**baseline[1], 'on-sigusr1': 'noop'})
            self.assertEqual(bars[0]['custom/power']['on-click'],baseline[0]['custom/power']['on-click'])
            self.assertIn('window#waybar.dock',css)
            if identity!='original':
                self.assertTrue(bars[0]['fixed-center'])
                self.assertLessEqual(bars[0]['custom/media-idle']['max-length'],32)
                self.assertLessEqual(bars[0]['niri/window']['max-length'],18)
                self.assertTrue(all(bars[0][name]['interval']>=1 for name in bars[0] if name.startswith('mpris#')))

    def test_default_and_unknown_presets(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(presets,'PREFERENCE',Path(temporary)/'selected.json'):
            self.assertEqual(presets.current(),'mocha-pill')
        for identity in ['../outside','', 'not-a-preset']:
            if identity:
                with self.assertRaises(ValueError):presets.render(identity)

    def test_original_is_exact_saved_top_configuration(self):
        bars,_=presets.render('original')
        expected=json.loads((presets.PRESETS/'original-top.json').read_text())
        expected['modules-right']=[n.replace('custom/settings','custom/control') for n in expected['modules-right']]
        expected.pop('custom/settings')
        expected['custom/control']=bars[0]['custom/control']
        expected['custom/notifications']=bars[0]['custom/notifications']
        expected['on-sigusr1']='show'
        for name in ['network','bluetooth','battery']:expected[name]['on-click']=bars[0][name]['on-click']
        expected['network']['format-wifi']=json.loads((ROOT/'waybar.jsonc').read_text())[0]['network']['format-wifi']
        expected['network']['max-length']=json.loads((ROOT/'waybar.jsonc').read_text())[0]['network']['max-length']
        self.assertEqual(bars[0],expected)

    def test_all_css_parses_in_gtk3(self):
        presets.validate_all()

    def test_notification_stream_has_no_polling_and_covers_native_states(self):
        for identity in presets.profiles():
            module=presets.render(identity)[0][0]['custom/notifications']
            self.assertIn('swaync-client --skip-wait --subscribe-waybar',module['exec'])
            self.assertNotIn('interval',module)
            self.assertFalse(module['exec-on-event'])
            states={('dnd-' if dnd else '')+('inhibited-' if inhibited else '')+('notification' if count else 'none') for dnd in [False,True] for inhibited in [False,True] for count in [0,1]}
            self.assertEqual(set(module['format-icons']),states)
            self.assertIn('{text}',module['tooltip-format'])

    def test_notification_adapter_keeps_control_center_status_contract(self):
        for count,paused,expected in [(0,False,'empty'),(3,False,'pending'),(3,True,'paused')]:
            def read(args,**kwargs):return str(paused).lower() if '--get-dnd' in args else str(count)
            output=io.StringIO()
            with patch.object(sys,'argv',['notifications']),patch.object(subprocess,'run',return_value=SimpleNamespace(returncode=0)),patch.object(subprocess,'check_output',side_effect=read),contextlib.redirect_stdout(output):
                runpy.run_path(str(ROOT/'scripts/notifications'),run_name='notification_schema_test')
            data=json.loads(output.getvalue())
            self.assertEqual(data['alt'],expected)
            self.assertEqual(data['count'],count)

    def test_selection_persists_and_restart_failure_rolls_back(self):
        with tempfile.TemporaryDirectory() as temporary:
            base=Path(temporary);binpath=base/'bin';binpath.mkdir()
            script=binpath/'systemctl'
            script.write_text("#!/usr/bin/python3\nimport os,sys\nfrom pathlib import Path\nflag=Path(os.environ['FAKE_SYSTEMCTL_FLAG'])\nif 'restart' in sys.argv and os.environ.get('FAKE_FAIL')=='1' and not flag.exists():\n flag.touch();sys.exit(1)\nsys.exit(0)\n")
            script.chmod(0o700)
            env={**os.environ,'XDG_CURRENT_DESKTOP':'niri','XDG_STATE_HOME':str(base/'state'),
                 'XDG_RUNTIME_DIR':str(base/'runtime'),
                 'PATH':str(binpath)+':'+os.environ['PATH'],'FAKE_SYSTEMCTL_FLAG':str(base/'failed')}
            command=[sys.executable,str(ROOT/'scripts/waybar-preset')]
            subprocess.run([*command,'set','floating-glass'],env=env,check=True,capture_output=True)
            selected=subprocess.check_output([*command,'current'],env=env,text=True).strip()
            self.assertEqual(selected,'floating-glass')
            preference=base/'state/niri-rice/waybar-preset.json'
            before=preference.read_bytes()
            self.assertEqual(preference.stat().st_mode&0o777,0o600)
            result=subprocess.run([*command,'set','mocha-pill'],env={**env,'FAKE_FAIL':'1'},capture_output=True)
            self.assertNotEqual(result.returncode,0)
            self.assertEqual(preference.read_bytes(),before)


if __name__=='__main__':unittest.main(verbosity=2)
