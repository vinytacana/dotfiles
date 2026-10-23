"""GTK flow checks with a fake executor; never executes a real power/lock command."""
import os
from pathlib import Path
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import time

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
from rice_power import ACTIONS, PowerMenu, power_command
from gi.repository import Gtk, Gdk, Gio, GLib, GtkLayerShell


class PowerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not Gtk.init_check()[0] or not GtkLayerShell.is_supported():
            raise unittest.SkipTest('É necessária uma sessão gráfica com layer-shell.')
        cls.app = Gtk.Application(application_id='org.niri.Rice.PowerTests', flags=Gio.ApplicationFlags.NON_UNIQUE)
        cls.app.register(None)

    def setUp(self):
        self.environment = patch.dict(os.environ, XDG_CURRENT_DESKTOP='niri')
        self.environment.start(); self.addCleanup(self.environment.stop)
        self.calls = []
        self.menu = PowerMenu(self.app, executor=lambda command: self.calls.append(command))
        self.addCleanup(self.menu.destroy)

    def key(self, key, shift=False):
        return self.menu.escape(None, SimpleNamespace(keyval=key, state=Gdk.ModifierType.SHIFT_MASK if shift else 0))

    def test_lock_dispatches_only_the_central_command(self):
        self.menu.items[0].clicked()
        self.assertEqual(self.calls, [[str(Path(__file__).resolve().parents[1]/'scripts/lock')]])
        self.assertFalse(self.menu.alive)

    def test_power_actions_require_explicit_confirmation(self):
        for index, action in enumerate(['logout', 'shutdown', 'suspend', 'reboot'], 1):
            with self.subTest(action=action):
                self.menu.choose(action)
                self.assertEqual(self.calls, [])
                self.assertEqual(self.menu.pending_action, action)
                self.assertEqual(self.menu.get_focus(), self.menu.cancel_button)
                self.menu.cancel_button.clicked()
                self.assertIsNone(self.menu.pending_action)
        self.assertEqual(self.calls, [])

    def test_confirmation_maps_to_logind_and_niri(self):
        self.menu.choose('reboot')
        self.menu.confirm_button.clicked()
        self.assertEqual(self.calls, [['systemctl', 'reboot']])
        self.assertEqual(power_command('logout'), ['niri', 'msg', 'action', 'quit', '--skip-confirmation'])
        self.assertEqual(power_command('shutdown'), ['systemctl', 'poweroff'])
        self.assertEqual(power_command('suspend'), ['systemctl', 'suspend'])

    def test_repeated_enter_does_not_confirm_power(self):
        self.menu.select(2)
        self.key(Gdk.KEY_Return)
        self.assertEqual(self.menu.pending_action, 'shutdown')
        self.key(Gdk.KEY_Return)
        self.assertEqual(self.calls, [])
        self.assertIsNone(self.menu.pending_action)

    def test_keyboard_and_hover_keep_one_selection(self):
        self.key(Gdk.KEY_Left); self.assertEqual(self.menu.selected, 4)
        self.key(Gdk.KEY_Right); self.assertEqual(self.menu.selected, 0)
        self.key(Gdk.KEY_Tab); self.assertEqual(self.menu.selected, 1)
        self.key(Gdk.KEY_ISO_Left_Tab); self.assertEqual(self.menu.selected, 0)
        self.menu.hover(3); self.assertEqual(self.menu.selected, 3)
        self.assertEqual(sum(item.get_style_context().has_class('selected') for item in self.menu.items), 1)

    def test_escape_cancels_confirmation_then_closes(self):
        self.menu.choose('suspend')
        self.key(Gdk.KEY_Escape)
        self.assertTrue(self.menu.alive)
        self.assertIsNone(self.menu.pending_action)
        self.key(Gdk.KEY_Escape)
        self.assertFalse(self.menu.alive)
        self.assertEqual(self.calls, [])

    def test_confirmation_requires_focus_on_confirm(self):
        self.menu.choose('logout')
        self.key(Gdk.KEY_Right)
        self.assertEqual(self.menu.get_focus(), self.menu.confirm_button)
        self.key(Gdk.KEY_Return)
        self.assertEqual(self.calls, [power_command('logout')])
        self.menu.confirm()
        self.assertEqual(len(self.calls), 1)

    def test_no_action_dispatch_in_gnome(self):
        with patch.dict(os.environ, XDG_CURRENT_DESKTOP='GNOME'):
            self.menu.choose('shutdown'); self.menu.confirm_button.clicked()
        self.assertEqual(self.calls, [])
        self.assertTrue(self.menu.alive)
        self.assertIn('Niri', self.menu.error.get_text())

    def test_mapped_panel_geometry_and_gtk_event_handlers(self):
        def settle():
            context = GLib.MainContext.default()
            end = time.monotonic() + 0.15
            while time.monotonic() < end:
                while context.pending(): context.iteration(False)
                time.sleep(0.005)
        def emit_key(key):
            event = Gdk.Event.new(Gdk.EventType.KEY_PRESS)
            event.window = self.menu.get_window()
            event.keyval = key
            event.state = Gdk.ModifierType(0)
            self.menu.emit('key-press-event', event)
        self.menu.show_all(); settle()
        first = self.menu.items[0]
        last = self.menu.items[-1]
        left, _ = first.translate_coordinates(self.menu, 0, 0)
        right, _ = last.translate_coordinates(self.menu, 0, 0)
        center = (left + right + last.get_allocated_width()) / 2
        self.assertLessEqual(abs(center - self.menu.get_allocated_width()/2), 0.5)
        _, top = first.translate_coordinates(self.menu, 0, 0)
        self.assertLessEqual(abs(top + first.get_allocated_height()/2 - self.menu.get_allocated_height()/2), 0.5)
        # A posição real do ponteiro pode selecionar um item durante o mapeamento.
        self.menu.select(0)
        emit_key(Gdk.KEY_Right)
        self.assertEqual(self.menu.selected, 1)
        crossing = Gdk.Event.new(Gdk.EventType.ENTER_NOTIFY)
        crossing.window = self.menu.items[3].get_window()
        self.menu.items[3].emit('enter-notify-event', crossing)
        self.assertEqual(self.menu.selected, 3)
        self.menu.items[3].clicked()
        emit_key(Gdk.KEY_Return)  # Cancel selected by default.
        self.assertIsNone(self.menu.pending_action)
        self.assertEqual(self.calls, [])
        # Background event goes through the same outside-click callback as a pointer.
        event = Gdk.Event.new(Gdk.EventType.BUTTON_PRESS)
        event.window = self.menu.get_window()
        event.button = 1
        self.menu.get_child().emit('button-press-event', event)
        self.assertFalse(self.menu.alive)
        self.assertEqual(self.calls, [])


if __name__ == '__main__':
    unittest.main(verbosity=2)
