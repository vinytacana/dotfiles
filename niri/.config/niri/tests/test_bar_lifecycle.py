"""Bar transactions tested with fake systemctl; never stop a real session."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
import rice_bar as bar
import waybar_presets as presets


class Transactions(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name); binaries = self.base/'bin'; binaries.mkdir()
        ctl = binaries/'systemctl'
        ctl.write_text('''#!/usr/bin/python3
import os,sys,time
from pathlib import Path
if 'restart' in sys.argv:
    fd=os.open(os.environ['BAR_TEST_LOG'],os.O_WRONLY|os.O_APPEND|os.O_CREAT,0o600)
    os.write(fd,('start '+str(os.getpid())+'\\n').encode())
    time.sleep(.12)
    os.write(fd,('end '+str(os.getpid())+'\\n').encode());os.close(fd)
    flag=Path(os.environ['BAR_TEST_FAIL'])
    if os.environ.get('BAR_FAIL')=='1' and not flag.exists():flag.touch();sys.exit(1)
sys.exit(0)
'''); ctl.chmod(0o700)
        self.env = {**os.environ, 'XDG_CURRENT_DESKTOP': 'niri', 'XDG_STATE_HOME': str(self.base/'state'),
                    'XDG_RUNTIME_DIR': str(self.base/'runtime'), 'PATH': str(binaries)+':'+os.environ['PATH'],
                    'BAR_TEST_LOG': str(self.base/'calls'), 'BAR_TEST_FAIL': str(self.base/'failed')}
        self.flag = self.base/'state/niri-rice/dock-disabled'

    def invoke(self, *args, **env):
        return subprocess.run([sys.executable, '-B', str(ROOT/'scripts/dock-mode'), *args],
                              env={**self.env, **env}, text=True, capture_output=True, timeout=15)

    def test_concurrent_toggles_are_serialized_and_keep_parity(self):
        self.flag.parent.mkdir(parents=True); self.flag.touch()
        children = [subprocess.Popen([sys.executable, '-B', str(ROOT/'scripts/dock-mode'), 'toggle'],
                                    env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(3)]
        for child in children:
            _out, err = child.communicate(timeout=15); self.assertEqual(child.returncode, 0, err)
        self.assertFalse(self.flag.exists())  # off -> on -> off -> on
        active = 0
        for line in (self.base/'calls').read_text().splitlines():
            active += 1 if line.startswith('start') else -1
            self.assertIn(active, [0, 1])
        self.assertEqual(active, 0)

    def test_failed_dock_restart_restores_previous_preference(self):
        result = self.invoke('off', BAR_FAIL='1')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.flag.exists())
        self.assertEqual((self.base/'calls').read_text().count('start'), 2)

    def test_dock_never_mutates_state_outside_niri(self):
        result = self.invoke('off', XDG_CURRENT_DESKTOP='GNOME')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.flag.exists()); self.assertFalse((self.base/'calls').exists())


class Diagnostics(unittest.TestCase):
    def test_distinguishes_inactive_hidden_missing_and_disabled_output(self):
        service = {'ActiveState': 'active'}; outputs = {'HDMI-A-1': {'logical': {'width': 1920}}, 'eDP-1': {'logical': None}}
        layer = {'namespace': 'top', 'output': 'HDMI-A-1', 'layer': 'Top'}
        self.assertEqual(bar.classify(service, [layer], outputs, True), 'top-surface-present-dock-off')
        self.assertEqual(bar.classify(service, [], outputs, True), 'top-surface-missing')
        self.assertEqual(bar.classify(service, [{**layer, 'layer': 'Bottom'}], outputs, True), 'top-layer-changed-possible-hidden-mode')
        self.assertEqual(bar.classify(service, [layer], {'HDMI-A-1': {'logical': None}}, True), 'no-active-output')
        self.assertEqual(bar.classify({'ActiveState': 'failed'}, [], outputs, False), 'service-not-active')
        # Output comes back on another connector: no stale name may be accepted.
        self.assertEqual(bar.classify(service, [layer], {'eDP-1': {'logical': {'width': 1920}}}, False), 'top-surface-missing')

    def test_atomic_write_failure_preserves_working_config(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'waybar.json'; path.write_text('working')
            with patch.object(bar.os, 'replace', side_effect=OSError('test failure')):
                with self.assertRaises(OSError): bar.atomic_text(path, 'replacement')
            self.assertEqual(path.read_text(), 'working')
            self.assertEqual(list(Path(folder).iterdir()), [path])

    def test_top_and_dock_signal_policy_in_every_preset(self):
        for preset in presets.profiles():
            bars, _css = presets.render(preset)
            self.assertEqual(bars[0]['on-sigusr1'], 'show')
            self.assertEqual(bars[1]['on-sigusr1'], 'noop')
            self.assertNotIn('start_hidden', bars[0])
            self.assertNotIn('output', bars[0])

    def test_capture_is_opt_in_and_expires_without_spawning_commands(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(bar, 'DIAGNOSTICS', Path(folder)), patch.dict(os.environ, {'XDG_CURRENT_DESKTOP': 'niri'}), patch.object(bar.subprocess, 'check_output') as query:
            self.assertIsNone(bar.capture('test'))
            (Path(folder)/'enabled-until').write_text(str(time.time()-1))
            self.assertIsNone(bar.capture('test'))
            query.assert_not_called()


if __name__ == '__main__': unittest.main(verbosity=2)
