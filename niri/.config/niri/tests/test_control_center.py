"""Quick-control interactions with simulated hardware; never disconnect the session."""
import copy
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
import rice_control_center as center
import rice_controls as controls
from gi.repository import Gtk, Gdk, Gio, GLib


def settle(predicate=lambda: False, seconds=.3):
    until = time.monotonic() + seconds
    while time.monotonic() < until:
        while Gtk.events_pending() and time.monotonic() < until: Gtk.main_iteration_do(False)
        if predicate(): return
        time.sleep(.005)


class Power:
    def get_cached_property(self, name):
        return (GLib.Variant('s', 'balanced') if name == 'ActiveProfile' else
                GLib.Variant('aa{sv}', [{'Profile': GLib.Variant('s', item)} for item in ['balanced', 'power-saver']]))


def snapshot():
    return {'wifi': (True, 'Rede: casa \\ teste'), 'bluetooth': (True, 'Mouse'),
            'volume': (24, False), 'mic': (36, True), 'outputs': ([('sink1', 'Alto-falantes'), ('sink2', 'Fones')], 'sink1'),
            'inputs': ([('mic1', 'Microfone')], 'mic1'), 'brightness': ('test_backlight', 73),
            'battery': {'percent': 82, 'status': 'Carregando', 'external': True},
            'profiles': Power(), 'notifications': {'alt': 'empty', 'dnd': False}}


class Backends(unittest.TestCase):
    def test_network_deduplication_preserves_connected_access_point(self):
        class Bus:
            def call_sync(self, _name, _path, _interface, method, *_args):
                if method == 'ListConnections': return GLib.Variant('(ao)', (['/saved'],))
                return GLib.Variant('(a{sa{sv}})', ({'802-11-wireless': {'ssid': GLib.Variant('ay', b'Rede:1')},
                                                   'connection': {'uuid': GLib.Variant('s', 'saved')}},))
        with patch.object(controls, 'command', return_value='*:Rede\\:1:65:WPA2\n:Rede\\:1:90:WPA2'), patch.object(Gio, 'bus_get_sync', return_value=Bus()):
            items = controls.networks()
        self.assertEqual(len(items), 1)
        self.assertTrue(items[0]['active'])
        self.assertEqual(items[0]['signal'], 90)
        self.assertEqual(items[0]['uuid'], 'saved')

    def test_nmcli_escaped_fields_and_saved_network_argument_safety(self):
        self.assertEqual(controls.terse_rows(r'yes:Rede\: casa\\teste'), [['yes', 'Rede: casa\\teste']])
        with patch.object(controls, 'command') as call:
            controls.connect_network({'uuid': 'uuid-safe'})
            self.assertEqual(call.call_args.args[0], ['nmcli', '--wait', '12', 'connection', 'up', 'uuid', 'uuid-safe'])
            with self.assertRaises(RuntimeError): controls.connect_network({'ssid': '$(inert); senha não solicitada'})
            self.assertEqual(call.call_count, 1)

    def test_bluetooth_uses_exact_device_and_sources_exclude_monitors(self):
        with patch.object(controls, 'command') as call:
            controls.connect_bluetooth({'address': 'AA:BB:CC:DD:EE:FF', 'connected': True})
            self.assertEqual(call.call_args.args[0], ['bluetoothctl', 'disconnect', 'AA:BB:CC:DD:EE:FF'])
        with patch.object(controls, 'command', side_effect=['[{"name":"sink.monitor"},{"name":"mic","description":"Entrada"}]', 'mic']):
            self.assertEqual(controls.inputs(), ([('mic', 'Entrada')], 'mic'))


class QuickControls(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not Gtk.init_check()[0] or not center.GtkLayerShell.is_supported():
            raise unittest.SkipTest('É necessária uma sessão gráfica com layer-shell.')
        cls.app = Gtk.Application(application_id='org.niri.Rice.ControlTests', flags=Gio.ApplicationFlags.NON_UNIQUE)
        cls.app.register(None)
        cls.app.control_visible = Gio.SimpleAction.new_stateful('control-visible', None, GLib.Variant('b', False))
        provider = Gtk.CssProvider(); provider.load_from_path(str(ROOT/'rice-ui.css'))
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), provider, 600)

    def setUp(self):
        self.values = snapshot(); self.calls = []
        for target, replacement in [('control_snapshot', lambda: copy.copy(self.values)), ('networks', lambda: []),
                                    ('paired_devices', lambda: []), ('command', lambda args, **_: self.calls.append(args))]:
            mock = patch.object(controls, target, replacement); mock.start(); self.addCleanup(mock.stop)
        watch = patch.object(center.ControlCenter, 'watch_events'); watch.start(); self.addCleanup(watch.stop)
        self.window = center.ControlCenter(self.app)
        self.addCleanup(self.window.destroy)
        self.window.show_all(); settle(lambda: not self.window.loading)

    def key(self, key):
        event = Gdk.Event.new(Gdk.EventType.KEY_PRESS); event.keyval = key
        self.window.emit('key-press-event', event); settle()

    def test_main_geometry_mute_status_and_supported_profiles(self):
        self.assertEqual(self.window.panel.get_allocated_width(), 392)
        self.assertLess(self.window.panel.get_allocated_height(), 610)
        self.assertTrue(self.window.mutes['mic'].get_style_context().has_class('muted'))
        self.assertIn('silenciado', self.window.mic_status.get_text())
        self.assertEqual(len(self.window.profile_list.get_children()), 2)
        self.assertEqual(self.window.output_name.get_text(), 'Alto-falantes')
        self.assertTrue(self.app.control_visible.get_state().unpack())
        with patch.object(controls, 'set_profile') as change:
            self.window.profile_list.get_children()[1].clicked()
            settle(lambda: not self.window.operating)
            self.assertEqual(change.call_args.args[1], 'power-saver')

    def test_contextual_navigation_escape_and_outside_close(self):
        self.window.show_page('battery'); settle()
        self.assertEqual(self.window.page, 'battery'); self.assertTrue(self.window.back.get_visible())
        self.assertTrue(self.window.back.get_child().get_visible())
        self.key(Gdk.KEY_Escape); self.assertEqual(self.window.page, 'main')
        self.key(Gdk.KEY_Escape); self.assertFalse(self.window.alive)
        self.assertFalse(self.app.control_visible.get_state().unpack())

    def test_first_opening_directly_in_each_context_selects_matching_content(self):
        self.window.destroy()
        for page in ['wifi', 'bluetooth', 'battery', 'audio']:
            self.window = center.ControlCenter(self.app, page)
            self.addCleanup(self.window.destroy)
            self.window.show_all(); settle(lambda: not self.window.loading)
            self.assertEqual(self.window.stack.get_visible_child_name(), page)
            self.assertEqual(self.window.title.get_text(), center.PAGES[page])
            self.assertTrue(self.window.back.get_visible())
            self.window.destroy()

    def test_unavailable_hardware_and_notification_backend_are_disabled(self):
        self.window.display({key: None for key in self.values})
        for widget in [self.window.tiles['wifi']['button'], self.window.tiles['bluetooth']['button'],
                       self.window.sliders['brightness'], self.window.sliders['volume'], self.window.mutes['mic'], self.window.dnd]:
            self.assertFalse(widget.get_sensitive())
        self.assertEqual(self.window.percentages['brightness'].get_text(), 'Indisponível')
        self.assertIn('Sem bateria', self.window.battery_title.get_text())

    def test_radio_toggles_and_mutes_have_exact_targets(self):
        for widget, expected in [
            (self.window.tiles['wifi']['button'], ['nmcli', 'radio', 'wifi', 'off']),
            (self.window.tiles['bluetooth']['button'], ['bluetoothctl', 'power', 'off']),
            (self.window.mutes['volume'], ['wpctl', 'set-mute', '@DEFAULT_AUDIO_SINK@', 'toggle']),
            (self.window.mutes['mic'], ['wpctl', 'set-mute', '@DEFAULT_AUDIO_SOURCE@', 'toggle'])]:
            widget.clicked(); settle(lambda: not self.window.operating)
            self.assertIn(expected, self.calls)
        self.values['wifi'] = (False, 'Desligado'); self.window.display(self.values)
        self.window.toggle('wifi'); settle(lambda: not self.window.operating)
        self.assertIn(['nmcli', 'radio', 'wifi', 'on'], self.calls)

    def test_slider_debounce_device_selection_and_cancel_on_close(self):
        self.window.sliders['volume'].set_value(30); self.window.sliders['volume'].set_value(44)
        settle(lambda: ['wpctl', 'set-volume', '@DEFAULT_AUDIO_SINK@', '44%'] in self.calls, .8)
        self.assertIn(['wpctl', 'set-volume', '@DEFAULT_AUDIO_SINK@', '44%'], self.calls)
        self.assertNotIn(['wpctl', 'set-volume', '@DEFAULT_AUDIO_SINK@', '30%'], self.calls)
        settle(lambda: not self.window.operating)
        self.window.combos['outputs'].set_active_id('sink2'); settle(lambda: not self.window.operating)
        self.assertIn(['pactl', 'set-default-sink', 'sink2'], self.calls)
        before = len(self.calls); self.window.sliders['brightness'].set_value(51)
        self.window.destroy(); settle(seconds=.3)
        self.assertEqual(len(self.calls), before); self.assertEqual(self.window.pending, {})

    def test_failed_operation_is_visible_and_controls_recover(self):
        def fail(): raise RuntimeError('Operação recusada pelo serviço')
        self.window.perform(fail); settle(lambda: not self.window.operating)
        self.assertTrue(self.window.stack.get_sensitive())
        self.assertIn('recusada', self.window.message.get_text())

    def test_wifi_and_bluetooth_detail_rows_are_real_actions(self):
        with patch.object(controls, 'networks', return_value=[{'ssid': 'Rede salva', 'active': False, 'signal': 90, 'security': 'WPA2', 'uuid': 'saved'}]), patch.object(controls, 'connect_network') as connect:
            self.window.show_page('wifi'); settle(lambda: bool(self.window.details['wifi'][1].get_children()))
            self.window.details['wifi'][1].get_children()[0].clicked(); settle(lambda: not self.window.operating)
            self.assertEqual(connect.call_args.args[0]['uuid'], 'saved')
        with patch.object(controls, 'paired_devices', return_value=[{'address': 'AA:BB:CC:DD:EE:FF', 'name': 'Fone de teste', 'connected': False}]), patch.object(controls, 'connect_bluetooth') as connect:
            self.window.show_page('bluetooth'); settle(lambda: bool(self.window.details['bluetooth'][1].get_children()))
            self.window.details['bluetooth'][1].get_children()[0].clicked(); settle(lambda: not self.window.operating)
            self.assertEqual(connect.call_args.args[0]['name'], 'Fone de teste')

    def test_outside_click_cleans_up_and_late_refresh_is_harmless(self):
        self.window.queue_refresh()
        event = Gdk.Event.new(Gdk.EventType.BUTTON_PRESS); event.window = self.window.get_window(); event.button = 1
        self.window.get_child().emit('button-press-event', event)
        self.assertFalse(self.window.alive); self.assertEqual(self.window.pending, {})
        self.window.refresh(); settle()
        self.assertFalse(self.app.control_visible.get_state().unpack())

    def test_wrapped_detail_content_fits_without_clipping_advanced_action(self):
        items = [{'ssid': 'Rede de teste ' + str(i), 'active': False, 'signal': 80,
                  'security': 'WPA2', 'uuid': None} for i in range(8)]
        with patch.object(controls, 'networks', return_value=items):
            self.window.show_page('wifi')
            settle(lambda: len(self.window.details['wifi'][1].get_children()) == 8)
            settle()
            page = self.window.stack.get_visible_child()
            width = self.window.scroll.get_allocated_width()
            required = page.get_preferred_height_for_width(width).natural_height
            self.assertGreaterEqual(self.window.scroll.get_allocated_height(), required)
            self.assertLess(self.window.panel.get_allocated_height(), 900)


if __name__ == '__main__': unittest.main(verbosity=2)
