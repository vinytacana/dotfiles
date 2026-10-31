"""Media label exclusivity and real MPRIS fixtures on a PRIVATE session bus.

No real Spotify, audio, user notifications or desktop focus are changed.
"""
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
media = runpy.run_path(str(ROOT/'scripts/media-idle'))
MediaState, Observer = media['MediaState'], media['Observer']
from gi.repository import Gio, GLib
A = 'org.mpris.MediaPlayer2.spotify_test'
B = 'org.mpris.MediaPlayer2.firefox_test'
META = {'xesam:title': 'On The Square <&> 日本語', 'xesam:artist': ['Artista'], 'xesam:album': 'Álbum'}


class StateTests(unittest.TestCase):
    def state(self, status='Playing', metadata=META):
        state = MediaState(); epoch = state.select(True, [A])
        state.update(epoch, ':1.20', {'PlaybackStatus': status, 'Metadata': metadata, 'CanControl': True})
        return state

    def test_no_player_is_idle_but_unavailable_service_is_not(self):
        state = MediaState(); state.select(True, [])
        self.assertIn('idle', state.output()['class']); self.assertIn('Nada tocando', state.output()['text'])
        state.select(False, [A]); self.assertIn('unavailable', state.output()['class'])
        self.assertIsNone(state.target()['name'])

    def test_player_without_metadata_is_transitional_not_idle(self):
        state = self.state('Stopped', {})
        self.assertNotIn('idle', state.output()['class']); self.assertIn('Sincronizando', state.output()['text'])

    def test_late_metadata_replaces_transition_in_same_label(self):
        state = self.state('Stopped', {}); state.update(state.epoch, ':1.20', {'Metadata': META})
        self.assertIn('On The Square', state.output()['text']); self.assertNotIn('Nada tocando', state.output()['text'])

    def test_playing_and_paused_keep_metadata_and_full_tooltip(self):
        for status in ['Playing', 'Paused']:
            state = self.state(status); output = state.output()
            self.assertIn(status.lower(), output['class']); self.assertIn('On The Square', output['text'])
            self.assertIn('Álbum', output['tooltip']); self.assertIn('Artista', output['tooltip'])
            self.assertIn('&lt;&amp;&gt;', output['text']); self.assertNotIn('<&>', output['tooltip'])

    def test_metadata_before_status_is_not_absence(self):
        state = self.state(None)
        self.assertIn('On The Square', state.output()['text']); self.assertNotIn('idle', state.output()['class'])

    def test_stopped_with_valid_metadata_does_not_claim_no_player(self):
        state = self.state('Stopped'); self.assertIn('On The Square', state.output()['text'])
        self.assertIn('Parado', state.output()['tooltip'])

    def test_incomplete_or_invalid_metadata_has_safe_fallback(self):
        for value in [None, {}, {'xesam:title': 99}, {'xesam:artist': 'invalid'}, {'xesam:artist': [None, 'Artista']}]:
            state = self.state('Playing', value)
            self.assertNotIn('idle', state.output()['class']); self.assertIn('Mídia em reprodução', state.output()['text'])

    def test_disappearance_clears_old_metadata(self):
        state = self.state(); state.select(True, [])
        self.assertIn('idle', state.output()['class']); self.assertNotIn('On The Square', state.output()['text'])
        self.assertIsNone(state.target()['owner'])

    def test_selection_follows_playerctld_order_not_playing_heuristic(self):
        state = self.state('Paused'); state.select(True, [B, A])
        self.assertEqual(state.name, B); self.assertNotIn('On The Square', state.output()['text'])

    def test_out_of_order_old_player_reply_and_signal_are_ignored(self):
        state = self.state(); old = state.epoch; state.select(True, [B])
        self.assertFalse(state.update(old, ':1.20', {'Metadata': META}))
        self.assertNotIn('On The Square', state.output()['text'])

    def test_invalidated_metadata_and_owner_restart_do_not_keep_old_track(self):
        state = self.state(); state.update(state.epoch, ':1.20', {}, ['Metadata'])
        self.assertNotIn('On The Square', state.output()['text'])
        state.update(state.epoch, ':1.21', {'PlaybackStatus': 'Paused'})
        self.assertFalse(state.target()['control']); self.assertNotIn('On The Square', state.output()['text'])

    def test_remote_sync_and_track_change_during_startup(self):
        state = self.state('Stopped', {})
        for status, title in [('Stopped', 'Track A'), ('Paused', 'Track B'), ('Playing', 'Remote track')]:
            state.update(state.epoch, ':1.20', {'Metadata': {**META, 'xesam:title': title}, 'PlaybackStatus': status})
            self.assertIn(title, state.output()['text']); self.assertNotIn('idle', state.output()['class'])

    def test_rapid_pause_play_and_multiple_updates_keep_final_state(self):
        state = self.state()
        for n in range(60):
            state.update(state.epoch, ':1.20', {'PlaybackStatus': 'Playing' if n % 2 else 'Paused', 'Metadata': {**META, 'xesam:title': str(n)}})
        self.assertIn('59', state.output()['text']); self.assertIn('playing', state.output()['class'])

    def test_no_two_text_modules_can_render_contradictory_states(self):
        import waybar_presets
        for preset in waybar_presets.profiles():
            top = waybar_presets.render(preset)[0][0]
            if preset == 'original': continue
            modules = top['group/media']['modules']
            self.assertEqual([name for name in modules if name.startswith('custom/')], ['custom/media-idle'])
            self.assertNotIn('mpris#track', top)
            for name in modules[1:]:
                self.assertNotIn('{title}', top[name]['format'])
                self.assertNotIn('{artist}', top[name]['format'])
                self.assertGreaterEqual(top[name]['interval'], 1)

    def test_transport_refuses_replaced_or_gone_unique_owner(self):
        selected = runpy.run_path(str(ROOT/'scripts/media-player'))['selected']
        class Bus:
            def call_sync(self, *args): return GLib.Variant('(s)', (':1.21',))
        self.assertIsNone(selected(Bus(), {'name': A, 'owner': ':1.20'}))
        self.assertEqual(selected(Bus(), {'name': A, 'owner': ':1.21'}), ':1.21')
        self.assertIsNone(selected(Bus(), {'name': 'unsafe', 'owner': ':1.21'}))

    def test_only_idle_can_launch_spotify_not_a_known_player_transition(self):
        main = runpy.run_path(str(ROOT/'scripts/media-player'))['main']
        with tempfile.TemporaryDirectory() as folder:
            runtime = Path(folder)/'niri-rice'; runtime.mkdir()
            for name, should_launch in [(None, True), (B, False)]:
                (runtime/'media-target.json').write_text(json.dumps({'name': name, 'owner': None}))
                with patch.dict(os.environ, XDG_RUNTIME_DIR=folder), patch.object(sys, 'argv', ['media-player']), \
                     patch.object(Gio, 'bus_get_sync', return_value=object()), \
                     patch.dict(main.__globals__, selected=lambda *_: None, spotify=lambda: calls.append('spotify')):
                    calls = []; main()
                self.assertEqual(bool(calls), should_launch)

    def test_burst_is_coalesced_and_close_cancels_pending_source(self):
        observer = object.__new__(Observer)
        observer.alive = True; observer.pending = 0; observer.previous = None; observer.previous_target = None
        observer.state = self.state(); outputs = []; observer.publish = outputs.append; observer.write_target = None
        for _ in range(40): observer.schedule()
        pending = observer.pending; self.assertNotEqual(pending, 0)
        context = GLib.MainContext.default()
        while context.pending(): context.iteration(False)
        self.assertEqual(len(outputs), 1); self.assertEqual(observer.pending, 0)
        observer.schedule(); source = observer.pending; observer.alive = False; GLib.source_remove(source); observer.pending = 0
        self.assertIsNone(context.find_source_by_id(source))

    def test_late_async_proxy_reply_cannot_replace_new_selection(self):
        class Order:
            names = [A]
            def get_name_owner(self): return ':1.1'
            def get_cached_property(self, name): return GLib.Variant('as', self.names)
            def connect(self, *args): return 1
            def disconnect(self, *args): pass
        order = Order()
        with patch.object(Gio.DBusProxy, 'new_for_bus_sync', return_value=order), \
             patch.object(Gio.DBusProxy, 'new_for_bus') as create:
            observer = Observer(lambda _: None)
            try:
                old = observer.state.epoch; old_request = observer.request
                order.names = [B]; observer.select()
                self.assertTrue(old_request.is_cancelled())
                with patch.object(Gio.DBusProxy, 'new_for_bus_finish', return_value=object()):
                    observer.ready(None, None, old)
                self.assertIsNone(observer.proxy)
                self.assertEqual(observer.state.name, B)
                self.assertEqual(create.call_count, 2)
            finally: observer.close()
            self.assertFalse(observer.alive); self.assertEqual(observer.pending, 0)

    def test_private_bus_integration(self):
        result = subprocess.run(['dbus-run-session', '--', sys.executable, '-B', str(Path(__file__).resolve()), '--private-integration'],
                                capture_output=True, text=True, timeout=40)
        self.assertEqual(result.returncode, 0, result.stdout+'\n'+result.stderr)
        self.assertIn('PRIVATE MPRIS OK', result.stdout)


def integration():
    """Real D-Bus, real playerctld and fixture methods; never the user's bus."""
    assert 'DBUS_SESSION_BUS_ADDRESS' in os.environ
    context = GLib.MainContext.default(); processes = []
    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    def wait(predicate, seconds=4):
        deadline = time.monotonic()+seconds
        while time.monotonic() < deadline:
            while context.pending(): context.iteration(False)
            if predicate(): return
            time.sleep(.01)
        raise AssertionError('Timed out waiting for fixture state')
    def own(name):
        try:
            return bus.call_sync('org.freedesktop.DBus', '/org/freedesktop/DBus', 'org.freedesktop.DBus',
                'GetNameOwner', GLib.Variant('(s)', (name,)), GLib.VariantType.new('(s)'), Gio.DBusCallFlags.NONE, 500, None).unpack()[0]
        except GLib.Error: return None
    def launch(args):
        child = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL); processes.append(child); return child
    def method(name, status, title):
        bus.call_sync(name, media['PATH'], 'org.niri.Rice.MprisFixture', 'SetState',
            GLib.Variant('(ssss)', (status, title, 'Artista <&>', 'Álbum')), None, Gio.DBusCallFlags.NONE, 1000, None)
    with tempfile.TemporaryDirectory() as folder:
        base = Path(folder); runtime = base/'niri-rice'; runtime.mkdir(mode=0o700)
        proxy = launch(['playerctld']); wait(lambda: own(media['NAME']))
        outputs = []
        def target(value):
            p = runtime/'media-target.json'; p.write_text(json.dumps(value)); p.chmod(0o600)
        observer = Observer(outputs.append, target)
        try:
            wait(lambda: outputs and 'idle' in outputs[-1]['class'])
            first = launch([sys.executable, '-B', str(ROOT/'tests/mpris_fixture.py'), str(base/'first.json'), '--name', 'spotify_test', '--initial-status', 'Stopped', '--empty'])
            wait(lambda: observer.state.name == A and observer.state.owner)
            assert 'idle' not in observer.state.output()['class']
            method(A, 'Stopped', 'On The Square fixture'); wait(lambda: 'On The Square' in outputs[-1]['text'])
            for status in ['Paused', 'Playing', 'Paused', 'Playing']:
                method(A, status, 'Remote Connect fixture'); wait(lambda: status.lower() in outputs[-1]['class'])
            env = {**os.environ, 'XDG_RUNTIME_DIR': str(base)}
            for action in ['previous', 'play-pause', 'next']:
                subprocess.run([sys.executable, '-B', str(ROOT/'scripts/media-player'), action], env=env, check=True, capture_output=True, timeout=4)
            calls = json.loads((base/'first.json').read_text())['calls']
            assert all(name in calls for name in ['Previous', 'PlayPause', 'Next']), calls
            second = launch([sys.executable, '-B', str(ROOT/'tests/mpris_fixture.py'), str(base/'second.json'), '--name', 'firefox_test'])
            wait(lambda: observer.state.name == B and observer.state.owner)
            method(B, 'Playing', 'Browser fixture'); wait(lambda: 'Browser fixture' in outputs[-1]['text'])
            # Explicit target remains the rendered player, even if another is paused.
            subprocess.run([sys.executable, '-B', str(ROOT/'scripts/media-player'), 'next'], env=env, check=True, capture_output=True, timeout=4)
            assert 'Next' in json.loads((base/'second.json').read_text())['calls']
            second.terminate(); second.wait(timeout=3)
            wait(lambda: observer.state.name == A and observer.state.owner)
            method(A, 'Paused', 'Track after browser exit'); wait(lambda: 'Track after browser exit' in outputs[-1]['text'])
            proxy.terminate(); proxy.wait(timeout=3); wait(lambda: not observer.state.service)
            proxy = launch(['playerctld']); wait(lambda: observer.state.service and observer.state.name == A and observer.state.owner)
            first.terminate(); first.wait(timeout=3); wait(lambda: outputs and 'idle' in outputs[-1]['class'])
            assert observer.state.target()['owner'] is None
            assert all(not ('idle' in row['class'] and 'track' in row['class']) for row in outputs)
            assert (runtime/'media-target.json').stat().st_mode & 0o777 == 0o600
            print('PRIVATE MPRIS OK:', len(outputs), 'coherent snapshots; controls/reselection/reconnect/exit')
        finally:
            observer.close()
            assert observer.pending == 0 and observer.request is None and observer.proxy is None
            for child in processes:
                if child.poll() is None: child.terminate()
                child.wait(timeout=3)


if __name__ == '__main__':
    if '--private-integration' in sys.argv: integration()
    else: unittest.main()
