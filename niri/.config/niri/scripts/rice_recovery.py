"""Bounded, event-driven Waybar recovery. Never changes monitors or lockers."""
import fcntl
import json
import os
from pathlib import Path
import subprocess
import time

import rice_bar as bar
from rice_common import STATE, read_json, write_json

EVENTS = ('lid-close', 'lid-open', 'after-resume', 'unlocked', 'check')


def outputs_signature(outputs):
    return json.dumps({name: {'logical': item.get('logical'), 'current_mode': item.get('current_mode')}
                       for name, item in outputs.items()}, sort_keys=True)


def lid_state():
    for path in Path('/proc/acpi/button/lid').glob('*/state'):
        try: return path.read_text().strip().split()[-1]
        except OSError: pass
    return 'unavailable'


def record(result):
    try:
        bar.DIAGNOSTICS.mkdir(parents=True, exist_ok=True, mode=0o700)
        bar.DIAGNOSTICS.chmod(0o700)
        write_json(bar.DIAGNOSTICS/f'recovery-{time.time_ns()}.json', result)
        for path in sorted(bar.DIAGNOSTICS.glob('recovery-*.json'))[:-24]: path.unlink(missing_ok=True)
    except OSError: pass


class Backend:
    @staticmethod
    def query(args):
        return subprocess.check_output(args, text=True, stderr=subprocess.DEVNULL, timeout=2).strip()

    def sample(self):
        values = self.query(['systemctl', '--user', 'show', bar.UNIT, '-p', 'ActiveState', '-p', 'SubState',
                             '-p', 'MainPID', '-p', 'Result', '-p', 'NRestarts'])
        service = dict(line.split('=', 1) for line in values.splitlines() if '=' in line)
        raw = json.loads(self.query(['niri', 'msg', '-j', 'outputs']))
        outputs = {name: {'logical': item.get('logical'), 'current_mode': item.get('current_mode')}
                   for name, item in raw.items()}
        layers = json.loads(self.query(['niri', 'msg', '-j', 'layers']))
        pid = int(service.get('MainPID', '0'))
        try:
            proc = Path('/proc')/str(pid)
            alive = pid > 0 and (proc/'comm').read_text().strip() == 'waybar'
            alive = alive and (proc/'stat').read_text().rsplit(')', 1)[1].split()[0] != 'Z'
        except OSError: alive = False
        return {'service': service, 'pid_alive': alive, 'outputs': outputs, 'layers': layers,
                'dock_disabled': (STATE/'dock-disabled').exists()}

    def lock_state(self):
        """Niri sets logind LockedHint for ext-session-lock; unknown means defer."""
        try:
            for proc in Path('/proc').iterdir():
                if not proc.name.isdigit(): continue
                try:
                    if proc.stat().st_uid != os.getuid(): continue
                    if (proc/'comm').read_text().strip() in {'gtklock', 'swaylock'}:
                        if (proc/'stat').read_text().rsplit(')', 1)[1].split()[0] != 'Z': return 'locked'
                except FileNotFoundError: continue
            pid = int(self.query(['systemctl', '--user', 'show', 'niri.service', '-p', 'MainPID', '--value']))
            entries = (Path('/proc')/str(pid)/'environ').read_bytes().split(b'\0')
            session = next(item.split(b'=', 1)[1].decode() for item in entries if item.startswith(b'XDG_SESSION_ID='))
            if os.environ.get('XDG_SESSION_ID', session) != session: return 'unknown'
            data = self.query(['loginctl', 'show-session', session, '-p', 'User', '-p', 'Type', '-p', 'Active', '-p', 'LockedHint'])
            props = dict(line.split('=', 1) for line in data.splitlines() if '=' in line)
            if props.get('User') != str(os.getuid()) or props.get('Type') != 'wayland' or props.get('Active') != 'yes':
                return 'unknown'
            return {'yes': 'locked', 'no': 'unlocked'}.get(props.get('LockedHint'), 'unknown')
        except (OSError, ValueError, StopIteration, subprocess.SubprocessError): return 'unknown'

    def show_supported(self):
        try:
            path = Path(os.environ['XDG_RUNTIME_DIR'])/'niri-rice/waybar.json'
            top = next(item for item in json.loads(path.read_text()) if item.get('name') == 'top')
            return top.get('on-sigusr1') == 'show'
        except (OSError, ValueError, StopIteration): return False

    def signal(self, name):
        subprocess.run(['systemctl', '--user', 'kill', '--kill-whom=main', '--signal='+name, bar.UNIT], check=True, timeout=3)

    def restart(self): bar.restart('event-recovery')


class Recovery:
    def __init__(self, backend=None, clock=time.monotonic, sleep=time.sleep):
        self.backend = backend or Backend(); self.clock = clock; self.sleep = sleep

    @staticmethod
    def diagnosis(sample):
        if not sample['pid_alive']: return 'process-not-ready-systemd-responsibility'
        return bar.classify(sample['service'], sample['layers'], sample['outputs'], sample['dock_disabled'])

    def stable(self, marker):
        deadline = self.clock()+5; previous = None; matches = 0
        while self.clock() < deadline:
            sample = self.backend.sample(); signature = outputs_signature(sample['outputs'])
            latest = read_json(marker, {}).get('monotonic', 0)
            matches = matches+1 if signature == previous else 0
            if matches >= 2 and self.clock()-latest >= .6: return sample
            previous = signature; self.sleep(.35)
        return None

    def run(self, event, runtime, dry_run=False):
        start = self.clock(); actions = []
        result = {'time': time.time(), 'event': event, 'actions': actions, 'lid': lid_state(),
                  'dock_disabled': (STATE/'dock-disabled').exists(), 'dry_run': dry_run}
        def finish(status):
            result.update(result=status, elapsed_s=self.clock()-start)
            result['latest_event'] = read_json(runtime/'recovery-event.json', {})
            return result
        sample = self.stable(runtime/'recovery-event.json')
        if sample is None: return finish('outputs-unstable')
        result['before'] = sample; state = self.diagnosis(sample)
        if state.startswith('top-surface-present'):
            (runtime/'recovery-deferred').unlink(missing_ok=True)
            return finish('healthy-noop')
        if state not in {'top-surface-missing', 'top-layer-changed-possible-hidden-mode'}: return finish(state)
        # Same lock as dock/preset transactions. Re-read after waiting for them.
        with bar.update_lock():
            checked = self.backend.sample()
            if outputs_signature(checked['outputs']) != outputs_signature(sample['outputs']): return finish('outputs-changed')
            if self.diagnosis(checked) not in {'top-surface-missing', 'top-layer-changed-possible-hidden-mode'}:
                return finish('state-changed-noop')
            state = self.diagnosis(checked)
            lock = self.backend.lock_state(); result['lock_state'] = lock
            if lock != 'unlocked':
                bar.atomic_text(runtime/'recovery-deferred', event)
                return finish('deferred-'+lock)
            recent = read_json(runtime/'recovery-last.json', {})
            if recent.get('socket') == os.getenv('NIRI_SOCKET') and self.clock()-recent.get('monotonic', -1000) < 30:
                return finish('cooldown-noop')
            if dry_run: return finish('would-recover')
            write_json(runtime/'recovery-last.json', {'socket': os.getenv('NIRI_SOCKET'), 'monotonic': self.clock()})
            bar.capture('before-recovery-'+event, force=True)
            if state == 'top-layer-changed-possible-hidden-mode' and self.backend.show_supported():
                plan = [('show', lambda: self.backend.signal('SIGUSR1')),
                        ('reload', lambda: self.backend.signal('SIGUSR2')), ('restart', self.backend.restart)]
            else: plan = [('reload', lambda: self.backend.signal('SIGUSR2')), ('restart', self.backend.restart)]
            for name, action in plan:
                # Never interfere with an authentication started during settling.
                if self.backend.lock_state() != 'unlocked': return finish('deferred-during-recovery')
                latest = self.backend.sample()
                if outputs_signature(latest['outputs']) != outputs_signature(sample['outputs']): return finish('outputs-changed')
                if not latest['pid_alive'] or latest['service']['ActiveState'] != 'active': return finish('systemd-responsibility')
                if name != 'restart' and latest['service']['MainPID'] != checked['service']['MainPID']: return finish('pid-changed')
                actions.append(name)
                try: action()
                except (OSError, subprocess.SubprocessError): return finish(name+'-failed')
                for _ in range(4):
                    self.sleep(.3); latest = self.backend.sample(); result['after'] = latest
                    if outputs_signature(latest['outputs']) != outputs_signature(sample['outputs']): return finish('outputs-changed')
                    if self.diagnosis(latest).startswith('top-surface-present'):
                        (runtime/'recovery-deferred').unlink(missing_ok=True)
                        return finish('recovered-'+name)
            return finish('recovery-failed')


def recover(event='check', dry_run=False, engine=None, runtime=None):
    if event not in EVENTS: raise ValueError('Evento desconhecido')
    if not bar.in_niri(): return {'event': event, 'result': 'outside-niri', 'actions': []}
    runtime = runtime or Path(os.environ['XDG_RUNTIME_DIR'])/'niri-rice'
    runtime.mkdir(parents=True, exist_ok=True, mode=0o700)
    write_json(runtime/'recovery-event.json', {'event': event, 'monotonic': time.monotonic()})
    with (runtime/'recovery.lock').open('a') as guard:
        os.fchmod(guard.fileno(), 0o600)
        try: fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            result = {'time': time.time(), 'event': event, 'result': 'coalesced', 'actions': []}
            record(result)
            return result
        try: result = (engine or Recovery()).run(event, runtime, dry_run)
        except (OSError, ValueError, KeyError, subprocess.SubprocessError):
            result = {'time': time.time(), 'event': event, 'result': 'query-or-action-failed', 'actions': []}
        try: result['preset'] = read_json(STATE/'waybar-preset.json', {'preset': 'mocha-pill'}).get('preset')
        except (OSError, ValueError): result['preset'] = 'unavailable'
        record(result)
        return result
