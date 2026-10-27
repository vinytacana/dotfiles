"""Event recovery state machine with simulated outputs, lock state and systemd."""
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
import rice_recovery as recovery


def sample(layer='Top', present=True, active=True, alive=True):
    return {'service': {'ActiveState': 'active' if alive else 'failed', 'MainPID': '42', 'SubState': 'running'},
            'pid_alive': alive, 'outputs': {'HDMI-A-1': {'logical': {'width': 1920} if active else None, 'current_mode': 0}},
            'layers': [{'namespace': 'top', 'output': 'HDMI-A-1', 'layer': layer}] if present else [],
            'dock_disabled': True}


class Fake:
    def __init__(self, value):
        self.value=value; self.lock='unlocked'; self.calls=[]; self.repair='reload'; self.samples=[]
    def sample(self):
        return copy.deepcopy(self.samples.pop(0) if self.samples else self.value)
    def lock_state(self): return self.lock
    def show_supported(self): return True
    def signal(self, name):
        action={'SIGUSR1':'show','SIGUSR2':'reload'}[name]; self.calls.append(action)
        if action==self.repair:self.value=sample()
    def restart(self):
        self.calls.append('restart')
        if self.repair=='restart':self.value=sample()


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.now=100.;self.fake=Fake(sample())
        for patcher in [patch.dict(os.environ,{'XDG_CURRENT_DESKTOP':'niri','XDG_RUNTIME_DIR':str(self.root),'NIRI_SOCKET':'test-socket'}),
                        patch.object(recovery.bar,'capture'),patch.object(recovery,'STATE',self.root),patch.object(recovery,'record')]:
            patcher.start();self.addCleanup(patcher.stop)
        (self.root/'dock-disabled').touch()
    def sleep(self,seconds):self.now+=seconds
    def run_event(self,event='check',dry=False):
        return recovery.Recovery(self.fake,lambda:self.now,self.sleep).run(event,self.root,dry)

    def test_native_events_are_idempotent_with_healthy_top_and_dock_off(self):
        for event in recovery.EVENTS:
            result=self.run_event(event);self.assertEqual(result['result'],'healthy-noop');self.assertEqual(result['actions'],[])
        self.assertEqual(self.fake.calls,[])

    def test_dead_process_is_left_to_systemd(self):
        self.fake.value=sample(alive=False)
        self.assertEqual(self.run_event()['result'],'process-not-ready-systemd-responsibility')
        self.assertEqual(self.fake.calls,[])

    def test_stable_missing_top_recovers_with_one_native_reload(self):
        self.fake.value=sample(present=False)
        result=self.run_event('after-resume')
        self.assertEqual(result['result'],'recovered-reload');self.assertEqual(self.fake.calls,['reload'])
        self.assertTrue(result['dock_disabled'])

    def test_demonstrated_hidden_mode_uses_show_before_reload(self):
        self.fake.value=sample(layer='Bottom');self.fake.repair='show'
        self.assertEqual(self.run_event()['result'],'recovered-show');self.assertEqual(self.fake.calls,['show'])

    def test_restart_is_last_resort_and_only_once(self):
        self.fake.value=sample(present=False);self.fake.repair='restart'
        self.assertEqual(self.run_event()['result'],'recovered-restart')
        self.assertEqual(self.fake.calls,['reload','restart'])

    def test_no_active_monitor_does_not_trigger_restart(self):
        self.fake.value=sample(active=False,present=False)
        self.assertEqual(self.run_event('lid-close')['result'],'no-active-output');self.assertFalse(self.fake.calls)

    def test_monitor_transition_waits_then_uses_only_current_connector(self):
        internal=sample(present=False);internal['outputs']={'eDP-1':{'logical':{'width':1920},'current_mode':0}}
        self.fake.samples=[internal,sample(present=False),internal]
        self.fake.value=sample()
        self.assertEqual(self.run_event('lid-open')['result'],'healthy-noop');self.assertFalse(self.fake.calls)

    def test_outputs_that_keep_changing_are_not_recovered(self):
        first=sample();second=sample();second['outputs']['HDMI-A-1']['logical']['width']=1280
        self.fake.samples=[first,second]*12
        self.assertEqual(self.run_event()['result'],'outputs-unstable');self.assertFalse(self.fake.calls)

    def test_locked_or_unknown_session_is_deferred_until_unlock(self):
        for state in ['locked','unknown']:
            self.fake.value=sample(present=False);self.fake.lock=state
            self.assertEqual(self.run_event('after-resume')['result'],'deferred-'+state)
            self.assertTrue((self.root/'recovery-deferred').exists());self.assertFalse(self.fake.calls)
        self.fake.lock='unlocked'
        self.assertEqual(self.run_event('unlocked')['result'],'recovered-reload')
        self.assertFalse((self.root/'recovery-deferred').exists())

    def test_cooldown_prevents_second_recovery(self):
        self.fake.value=sample(present=False);self.run_event()
        self.fake.value=sample(present=False)
        self.assertEqual(self.run_event()['result'],'cooldown-noop');self.assertEqual(self.fake.calls,['reload'])

    def test_dry_run_has_no_side_effects_on_bar_or_cooldown(self):
        self.fake.value=sample(present=False)
        self.assertEqual(self.run_event(dry=True)['result'],'would-recover')
        self.assertFalse(self.fake.calls);self.assertFalse((self.root/'recovery-last.json').exists())

    def test_unstable_or_unknown_lock_state_during_action_aborts(self):
        self.fake.value=sample(present=False)
        with patch.object(self.fake,'lock_state',side_effect=['unlocked','locked']):
            self.assertEqual(self.run_event()['result'],'deferred-during-recovery')
        self.assertFalse(self.fake.calls)

    def test_parallel_events_are_coalesced_without_second_runner(self):
        entered=threading.Event();release=threading.Event();results=[]
        class Engine:
            def run(inner,*args):entered.set();release.wait(3);return {'result':'healthy-noop','actions':[]}
        worker=threading.Thread(target=lambda:results.append(recovery.recover('lid-close',engine=Engine(),runtime=self.root)))
        worker.start();self.assertTrue(entered.wait(2))
        try:self.assertEqual(recovery.recover('lid-open',engine=Engine(),runtime=self.root)['result'],'coalesced')
        finally:release.set();worker.join(3)
        self.assertEqual(len(results),1)
        self.assertEqual(json.loads((self.root/'recovery-event.json').read_text())['event'],'lid-open')

    def test_runtime_fallback_never_writes_preset_or_dock_preference(self):
        (self.root/'waybar-preset.json').write_text('{"preset":"mocha-pill"}')
        (self.root/'dock-disabled').touch();self.fake.value=sample(present=False)
        self.run_event();self.assertEqual((self.root/'waybar-preset.json').read_text(),'{"preset":"mocha-pill"}')
        self.assertTrue((self.root/'dock-disabled').exists())

    def test_short_lived_unrelated_process_does_not_hide_logind_state(self):
        proc = self.root/'proc'; (proc/'42').mkdir(parents=True)
        (proc/'42/environ').write_bytes(b'XDG_SESSION_ID=9\0')
        class Vanished:
            name='123'
            def stat(self): raise FileNotFoundError('Process exited during enumeration')
        class ProcRoot:
            def iterdir(self): return iter([Vanished()])
            def __truediv__(self,name): return proc/name
        actual_path = recovery.Path
        def path(name): return ProcRoot() if name=='/proc' else actual_path(name)
        for hint, expected in [('no','unlocked'),('yes','locked')]:
            props=f'User={os.getuid()}\nType=wayland\nActive=yes\nLockedHint={hint}'
            with patch.object(recovery,'Path',side_effect=path), \
                 patch.dict(os.environ,{'XDG_SESSION_ID':'9'}), \
                 patch.object(recovery.Backend,'query',side_effect=['42',props]):
                self.assertEqual(recovery.Backend().lock_state(),expected)

    def test_logind_unavailable_remains_unknown(self):
        with patch.object(recovery.Backend,'query',side_effect=OSError('unavailable')):
            self.assertEqual(recovery.Backend().lock_state(),'unknown')


if __name__=='__main__':unittest.main(verbosity=2)
