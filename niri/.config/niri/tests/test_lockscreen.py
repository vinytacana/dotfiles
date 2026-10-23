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


if __name__ == '__main__':
    unittest.main()
