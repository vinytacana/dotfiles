#!/usr/bin/python3
"""Regressões de fallback/cache. Nunca inicia um bloqueador nem lê senhas."""
import importlib.machinery
import importlib.util
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
ROOT = Path(__file__).resolve().parent.parent
loader = importlib.machinery.SourceFileLoader('rice_lockscreen', str(ROOT/'scripts/lockscreen'))
spec = importlib.util.spec_from_loader(loader.name, loader)
lockscreen = importlib.util.module_from_spec(spec)
loader.exec_module(lockscreen)


class ExecAttempt(BaseException):
    pass


class Dispatch(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        for mocked in [patch.object(lockscreen, 'STATE', Path(self.tmp.name)),
                       patch.object(lockscreen, 'cached_background', return_value=None),
                       patch.object(lockscreen.shutil, 'which', return_value='/usr/bin/gtklock'),
                       patch.object(lockscreen, 'layout', return_value=Path(self.tmp.name)/'layout.ui'),
                       patch.dict(os.environ, XDG_CURRENT_DESKTOP='niri', GTK_THEME='unrelated')]:
            mocked.start(); self.addCleanup(mocked.stop)

    def test_default_uses_swaylock_readiness(self):
        with patch.object(os, 'execvp', side_effect=ExecAttempt) as execute:
            with self.assertRaises(ExecAttempt): lockscreen.lock()
        self.assertEqual(execute.call_args.args[1][:2], ['swaylock', '-f'])

    def test_corrupt_preference_still_locks(self):
        (lockscreen.STATE/'backend').write_text('invalid')
        with patch.object(os, 'execvp', side_effect=ExecAttempt) as execute:
            with self.assertRaises(ExecAttempt): lockscreen.lock()
        self.assertEqual(execute.call_args.args[0], 'swaylock')

    def test_candidate_does_not_change_preference(self):
        with patch.object(os, 'execvpe', side_effect=ExecAttempt) as execute:
            with self.assertRaises(ExecAttempt): lockscreen.lock(True)
        args = execute.call_args.args
        self.assertIn('--daemonize', args[1])
        self.assertEqual(args[2]['LC_ALL'], 'pt_BR.UTF-8')
        self.assertNotIn('GTK_THEME', args[2])
        self.assertFalse((lockscreen.STATE/'backend').exists())
        self.assertEqual(os.environ['GTK_THEME'], 'unrelated')

    def test_missing_binary_falls_back_before_start(self):
        (lockscreen.STATE/'backend').write_text('gtklock')
        with patch.object(lockscreen.shutil, 'which', return_value=None), \
                patch.object(os, 'execvp', side_effect=ExecAttempt) as execute:
            with self.assertRaises(ExecAttempt): lockscreen.lock()
        self.assertEqual(execute.call_args.args[0], 'swaylock')

    def test_never_starts_second_locker_after_gtklock(self):
        with patch.object(os, 'execvpe', side_effect=OSError('test')), \
                patch.object(os, 'execvp') as fallback:
            with self.assertRaises(OSError): lockscreen.lock(True)
        fallback.assert_not_called()

    def test_cached_image_is_passed_to_swaylock(self):
        with patch.object(lockscreen, 'cached_background', return_value=Path('/tmp/cache.png')), \
                patch.object(os, 'execvp', side_effect=ExecAttempt) as execute:
            with self.assertRaises(ExecAttempt): lockscreen.lock()
        self.assertIn('--image', execute.call_args.args[1])


class Wallpaper(unittest.TestCase):
    def test_wallpaper_change_restore_cache_and_permissions(self):
        # HOME isolado + systemctl simulado: a sessão real não muda de wallpaper.
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            state = home/'.local/state/niri-rice'
            (home/'.config/niri').mkdir(parents=True)
            (home/'bin').mkdir()
            systemctl = home/'bin/systemctl'
            systemctl.write_text('#!/bin/sh\nexit 0\n'); systemctl.chmod(0o700)
            original = home/'.config/niri/wallpaper.png'
            selected = home/"nova parede ' ç; $x.png"
            for path, color in [(original, '#1e1e2e'), (selected, '#b4befe')]:
                subprocess.run(['magick', '-size', '64x64', 'xc:'+color, str(path)], check=True)
            original_bytes = original.read_bytes()
            env = {'HOME': str(home), 'XDG_STATE_HOME': str(home/'.local/state'),
                   'PATH': str(home/'bin')+':'+os.environ['PATH']}
            with patch.dict(os.environ, env), patch.object(lockscreen, 'STATE', state/'lockscreen'):
                manager = str(ROOT/'scripts/wallpaper-manager')
                subprocess.run([manager, 'set', str(selected)], check=True, capture_output=True)
                lockscreen.background()
                image = lockscreen.cached_background()
                self.assertIsNotNone(image)
                first = image.read_bytes()
                generated_at = image.stat().st_mtime_ns
                lockscreen.background()
                self.assertEqual(image.stat().st_mtime_ns, generated_at)
                dimensions = subprocess.check_output(['magick', 'identify', '-format', '%wx%h', str(image)], text=True)
                self.assertEqual(dimensions, '1920x1080')
                self.assertEqual(image.stat().st_mode & 0o777, 0o600)
                subprocess.run([manager, 'restore'], check=True, capture_output=True)
                self.assertIsNone(lockscreen.cached_background())
                lockscreen.background()
                self.assertNotEqual(first, image.read_bytes())
                metadata = json.loads((lockscreen.STATE/'background.json').read_text())
                self.assertEqual(metadata['source']['path'], str(original))
                self.assertEqual(original.read_bytes(), original_bytes)


class Presentation(unittest.TestCase):
    """Real GTK widgets in an OffscreenWindow; never lock or invoke PAM.

    Wake/hide calls model GTKLock 4's native presentation callbacks only.
    Physical input routing, first-keystroke delivery and authentication remain
    manual checks in GTKLock itself, not claims made by these simulations.
    """
    @classmethod
    def setUpClass(cls):
        import gi
        gi.require_version('Gtk', '3.0')
        from gi.repository import Gtk, Gdk, GLib
        if not Gtk.init_check()[0]:
            raise unittest.SkipTest('É necessária uma sessão GTK para renderizar a prévia.')
        cls.Gtk, cls.Gdk, cls.GLib = Gtk, Gdk, GLib

    def setUp(self):
        Gtk, provider, self.builder = lockscreen.validate_gtk()
        Gtk.StyleContext.add_provider_for_screen(self.Gdk.Screen.get_default(), provider,
                                                Gtk.STYLE_PROVIDER_PRIORITY_USER)
        self.window = Gtk.OffscreenWindow()
        self.window.set_default_size(1920, 1080)
        self.window.get_style_context().add_class('focused')
        self.window.get_style_context().add_class('hidden')
        self.window.add(self.builder.get_object('window-box'))
        self.revealer = self.builder.get_object('body-revealer')
        self.entry = self.builder.get_object('input-field')
        self.window.show_all()
        self.settle(.05)
        self.addCleanup(self.window.destroy)

    def settle(self, duration):
        until = time.monotonic() + duration
        while time.monotonic() < until:
            while self.Gtk.events_pending() and time.monotonic() < until:
                self.Gtk.main_iteration_do(False)
            time.sleep(.003)

    def show_form(self):
        self.window.get_style_context().remove_class('hidden')
        self.revealer.set_reveal_child(True)
        self.entry.grab_focus_without_selecting()

    def hide_form(self):
        self.window.get_style_context().add_class('hidden')
        self.revealer.set_reveal_child(False)

    def test_initial_state_and_native_animation_keep_entry_centered(self):
        self.assertFalse(self.revealer.get_reveal_child())
        self.assertFalse(self.revealer.get_child_revealed())
        self.assertEqual(self.revealer.get_transition_type(), self.Gtk.RevealerTransitionType.SLIDE_UP)
        self.assertEqual(self.revealer.get_transition_duration(), 300)
        self.show_form()
        for _ in range(14):
            self.settle(.03)
            if self.entry.get_allocated_width() > 1:
                x, _ = self.entry.translate_coordinates(self.window, 0, 0)
                self.assertAlmostEqual(x + self.entry.get_allocated_width()/2, 960, delta=.5)
        self.assertTrue(self.revealer.get_child_revealed())
        self.assertEqual(self.window.get_focus(), self.entry)
        self.assertFalse(self.entry.get_visibility())
        self.assertTrue(self.entry.get_property('caps-lock-warning'))

    def test_fifteen_second_return_retains_fictitious_partial_input(self):
        import configparser
        config = configparser.ConfigParser(interpolation=None)
        config.read(ROOT/'gtklock/config.ini')
        self.assertTrue(config.getboolean('main', 'start-hidden'))
        self.assertTrue(config.getboolean('main', 'idle-hide'))
        timeout = config.getint('main', 'idle-timeout')
        self.assertEqual(timeout, 15)
        self.show_form(); self.settle(.4)
        self.entry.set_text('texto-ficticio')
        fired = []
        def expire():
            fired.append(True); self.hide_form(); return False
        source = self.GLib.timeout_add_seconds(timeout, expire)
        def remove_timer():
            if self.GLib.MainContext.default().find_source_by_id(source):
                self.GLib.source_remove(source)
        self.addCleanup(remove_timer)
        deadline = time.monotonic() + timeout + 2
        while not fired and time.monotonic() < deadline:
            self.settle(.05)
        self.assertTrue(fired)
        self.settle(.4)
        self.assertFalse(self.revealer.get_child_revealed())
        self.assertEqual(self.entry.get_text(), 'texto-ficticio')
        self.show_form(); self.settle(.4)
        self.assertEqual(self.entry.get_text(), 'texto-ficticio')
        self.assertEqual(self.window.get_focus(), self.entry)
        self.entry.set_text('')

    def test_feedback_and_authentication_signals_remain_native(self):
        import xml.etree.ElementTree as ET
        self.show_form(); self.settle(.4)
        self.builder.get_object('warning-label').set_text('Caps Lock ativado')
        self.builder.get_object('error-label').set_text('Senha incorreta · demonstração')
        self.settle(.05)
        x, _ = self.entry.translate_coordinates(self.window, 0, 0)
        self.assertAlmostEqual(x + self.entry.get_allocated_width()/2, 960, delta=.5)
        self.assertTrue(self.builder.get_object('warning-label').get_mapped())
        self.assertTrue(self.builder.get_object('error-label').get_mapped())
        tree = ET.parse(ROOT/'gtklock/layout.ui')
        handlers = {signal.get('name'): signal.get('handler') for signal in tree.findall(".//object[@id='input-field']/signal")}
        self.assertEqual(handlers, {'icon-release': 'window_pw_toggle_vis', 'activate': 'window_pw_check'})
        self.assertEqual(tree.find(".//object[@id='unlock-button']/signal").get('handler'), 'window_pw_check')

    def test_preview_state_without_destination_cannot_lock(self):
        # The parser must reject this before reaching the locker dispatcher.
        result = subprocess.run([sys.executable, str(ROOT/'scripts/lockscreen'),
                                 '--preview-state', 'rest'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn('exige --preview', result.stderr)


if __name__ == '__main__':
    unittest.main()
