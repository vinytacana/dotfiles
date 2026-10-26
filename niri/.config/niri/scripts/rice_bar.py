"""Serialized bar updates and bounded, opt-in incident snapshots. No daemon."""
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

from rice_common import STATE, write_json

UNIT = 'niri-rice-bar.service'
DIAGNOSTICS = STATE/'waybar-diagnostics'


def in_niri():
    return 'niri' in os.environ.get('XDG_CURRENT_DESKTOP', '').split(':')


@contextmanager
def update_lock():
    if not in_niri():
        raise RuntimeError('A atualização da barra é exclusiva da sessão Niri.')
    runtime = Path(os.environ['XDG_RUNTIME_DIR'])/'niri-rice'
    runtime.mkdir(mode=0o700, parents=True, exist_ok=True)
    # The service's generator must not acquire this lock: systemctl waits for it.
    with (runtime/'bar-update.lock').open('a') as stream:
        os.fchmod(stream.fileno(), 0o600)
        fcntl.flock(stream, fcntl.LOCK_EX)
        yield


def atomic_text(path, content):
    fd, temporary = tempfile.mkstemp(prefix=path.name+'.', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            stream.write(content)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)


def classify(service, layers, outputs, dock_disabled):
    active = [name for name, output in outputs.items() if output.get('logical')]
    top = [item for item in layers if item.get('namespace') == 'top']
    if service.get('ActiveState') != 'active': return 'service-not-active'
    if not active: return 'no-active-output'
    if any(not any(item.get('output') == name for item in top) for name in active):
        return 'top-surface-missing'
    if any(item.get('layer') != 'Top' for item in top if item.get('output') in active):
        return 'top-layer-changed-possible-hidden-mode'
    return 'top-surface-present-dock-off' if dock_disabled else 'top-surface-present-dock-on'


def capture(reason, force=False):
    """Best effort only; failure never blocks bar startup or recovery."""
    try:
        until = DIAGNOSTICS/'enabled-until'
        if not in_niri() or (not force and (not until.exists() or float(until.read_text()) <= time.time())):
            return None
        DIAGNOSTICS.mkdir(parents=True, exist_ok=True, mode=0o700)
        DIAGNOSTICS.chmod(0o700)
        def query(args):
            return subprocess.check_output(args, text=True, stderr=subprocess.DEVNULL, timeout=2).strip()
        errors = []
        def optional(name, read, default):
            try: return read()
            except (OSError, ValueError, subprocess.SubprocessError):
                errors.append(name+' unavailable')
                return default
        fields = ['Id', 'ActiveState', 'SubState', 'MainPID', 'NRestarts', 'Result',
                  'ExecMainCode', 'ExecMainStatus', 'ExecMainStartTimestamp', 'ExecMainExitTimestamp']
        service = optional('service', lambda: dict(line.split('=', 1) for line in query(['systemctl', '--user', 'show', UNIT,
                           *sum([['-p', key] for key in fields], [])]).splitlines() if '=' in line), {})
        layers = optional('layers', lambda: json.loads(query(['niri', 'msg', '-j', 'layers'])), [])
        raw_outputs = optional('outputs', lambda: json.loads(query(['niri', 'msg', '-j', 'outputs'])), {})
        outputs = {name: {'logical': output.get('logical'), 'current_mode': output.get('current_mode')}
                   for name, output in raw_outputs.items()}
        runtime = Path(os.environ['XDG_RUNTIME_DIR'])/'niri-rice'
        bars = optional('runtime config', lambda: json.loads((runtime/'waybar.json').read_text()), [])
        processes = []
        for path in Path('/proc').iterdir():
            if not path.name.isdigit(): continue
            try:
                if (path/'comm').read_text().strip() != 'waybar' or path.stat().st_uid != os.getuid(): continue
                status = (path/'stat').read_text().rsplit(')', 1)[1].split()
                processes.append({'pid': int(path.name), 'state': status[0], 'ppid': int(status[1])})
            except OSError: pass
        disabled = (STATE/'dock-disabled').exists()
        snapshot = {'time': time.time(), 'reason': reason, 'service': service, 'processes': processes,
                    'layers': layers, 'outputs': outputs, 'dock_disabled': disabled,
                    'classification': 'incomplete-snapshot' if errors else classify(service, layers, outputs, disabled),
                    'errors': errors,
                    'bars': [{key: bar.get(key) for key in ['name', 'output', 'mode', 'start_hidden', 'on-sigusr1', 'on-sigusr2']} for bar in bars],
                    'runtime_hashes': {name: optional(name, lambda name=name: hashlib.sha256((runtime/name).read_bytes()).hexdigest(), None) for name in ['waybar.json', 'waybar.css']},
                    'exit': {key: os.getenv(key) for key in ['SERVICE_RESULT', 'EXIT_CODE', 'EXIT_STATUS']}}
        destination = DIAGNOSTICS/f'snapshot-{time.time_ns()}.json'
        write_json(destination, snapshot)
        for old in sorted(DIAGNOSTICS.glob('snapshot-*.json'))[:-24]: old.unlink()
        print(f'waybar-diagnose: {snapshot["classification"]} ({reason})', file=sys.stderr, flush=True)
        return destination
    except (OSError, ValueError, KeyError, subprocess.SubprocessError):
        return None


def restart(reason):
    # Caller holds update_lock across preference read/write and this restart.
    subprocess.run(['systemctl', '--user', 'restart', UNIT], check=True, timeout=10)
    subprocess.run(['systemctl', '--user', 'is-active', '--quiet', UNIT], check=True, timeout=3)


def reload_bar(reason='refresh'):
    with update_lock():
        capture('before-'+reason)
        restart(reason)
