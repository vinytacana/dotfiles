"""Orbit/Mocha: palette roles, geometry and reversible atomic generation.

No real service restart, notification action, hardware change or lock.
"""
import hashlib
import json
import os
from pathlib import Path
import runpy
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import rice_theme as theme
import waybar_presets as presets


class ThemeModels(unittest.TestCase):
    def test_mocha_styles_remain_exact_and_orbit_roles_have_no_neon(self):
        for component,path in theme.COMPONENTS.items():
            self.assertEqual(theme.css(component,'mocha'),(ROOT/path).read_text())
            orbit=theme.css(component,'orbit').lower()
            for old in theme.SOURCE_ROLES:self.assertNotIn(old,orbit)
        colors=theme.palette('orbit')
        self.assertEqual(colors['primary'],'#49C6F6')
        self.assertEqual(colors['warning'],'#EBAF79')

    def test_text_and_selected_controls_have_readable_contrast(self):
        def luminance(color):
            values=[v/255 for v in theme.rgb(color)]
            values=[v/12.92 if v<=.04045 else ((v+.055)/1.055)**2.4 for v in values]
            return sum(v*w for v,w in zip(values,[.2126,.7152,.0722]))
        colors=theme.palette('orbit')
        for fg,bg in [('text-primary','background-main'),('text-secondary','surface'),
                      ('text-muted','surface'),('text-primary','primary-strong'),
                      ('background-deep','primary')]:
            dark,light=sorted([luminance(colors[fg]),luminance(colors[bg])])
            self.assertGreaterEqual((light+.05)/(dark+.05),4.5,(fg,bg))

    def test_palette_conversion_does_not_touch_brands_or_geometry(self):
        value='button { padding: 12px; background: rgba(30,30,46,0.94); color: #b4befe; } /* #1db954 */'
        result=theme.colorize(value,'orbit')
        self.assertIn('padding: 12px',result);self.assertIn('#1db954',result)
        self.assertIn('rgba(5,8,23,0.94)',result)
        self.assertIn('#49C6F6',result)

    def test_all_presets_preserve_calendar_dock_and_mpris_guard(self):
        for preset in presets.profiles():
            mocha,_=presets.render(preset,theme='mocha');orbit,css=presets.render(preset,theme='orbit')
            self.assertEqual(mocha[1],orbit[1])
            self.assertEqual(mocha[0]['clock'],orbit[0]['clock'])
            self.assertEqual(orbit[0]['modules-center'],['clock'])
            self.assertEqual(orbit[0]['on-sigusr1'],'show')
            for key,value in orbit[0].items():
                if key.startswith('mpris#'):self.assertGreaterEqual(value['interval'],1)
            self.assertIn('#49C6F6',css)

    def test_atomic_generation_persists_and_rolls_back_on_refresh_error(self):
        with tempfile.TemporaryDirectory() as folder:
            base=Path(folder);state=base/'state';generated=state/'theme';preference=state/'visual-theme.json'
            with patch.object(theme,'STATE',state),patch.object(theme,'GENERATED',generated),patch.object(theme,'PREFERENCE',preference),patch.object(theme,'validate_bundle'):
                theme.apply('mocha',live=False)
                before={p.name:p.read_bytes() for p in generated.iterdir()}
                with patch.dict(os.environ,XDG_CURRENT_DESKTOP='niri'),patch.object(theme,'refresh_clients',side_effect=RuntimeError('simulated client failure')):
                    with self.assertRaises(RuntimeError):theme.apply('orbit')
                self.assertEqual({p.name:p.read_bytes() for p in generated.iterdir()},before)
                self.assertEqual(theme.current(),'mocha')
                for _ in range(2):theme.apply('orbit',live=False);self.assertEqual(theme.current(),'orbit');theme.apply('mocha',live=False)
                self.assertEqual({p.name:p.read_bytes() for p in generated.iterdir()},before)
                self.assertFalse(any(p.name.endswith('.tmp') for p in state.rglob('*')))

    def test_alacritty_profile_keeps_global_settings_and_only_imports_colors(self):
        import tomllib
        profile=tomllib.loads((ROOT.parents[2]/'alacritty/.config/alacritty/niri.toml').read_text())
        self.assertIn('~/.config/alacritty/alacritty.toml',profile['general']['import'])
        for name in theme.palettes():
            data=tomllib.loads(theme.alacritty_colors(name))
            self.assertEqual(set(data),{'colors'})


class ThemeGTK(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import gi
        gi.require_version('Gtk','3.0')
        from gi.repository import Gtk,Gdk,Gio
        if not Gtk.init_check()[0]:raise unittest.SkipTest('GTK display unavailable')
        cls.Gtk,cls.Gdk=Gtk,Gdk
        cls.app=Gtk.Application(application_id='org.niri.Rice.ThemeTests',flags=Gio.ApplicationFlags.NON_UNIQUE);cls.app.register(None);cls.app.safe=lambda work:work()

    def test_both_palettes_parse_gtk3_and_all_presets(self):
        for name in theme.palettes():
            for component in ['ui','osd','gtklock']:
                provider=self.Gtk.CssProvider();provider.load_from_data(theme.css(component,name).encode())
            for preset in presets.profiles():
                provider=self.Gtk.CssProvider();provider.load_from_data(presets.render(preset,theme=name)[1].encode())

    def test_orbit_calendar_keeps_narrow_width_and_full_date(self):
        import datetime,time
        namespace=runpy.run_path(str(ROOT/'scripts/rice-ui'),run_name='theme_calendar')
        provider=self.Gtk.CssProvider();provider.load_from_data(theme.css('ui','orbit').encode())
        self.Gtk.StyleContext.add_provider_for_screen(self.Gdk.Screen.get_default(),provider,700)
        window=namespace['CalendarWindow'](self.app)
        try:
            window.show_all()
            def settle():
                end=time.monotonic()+.15
                while time.monotonic()<end:
                    while self.Gtk.events_pending():self.Gtk.main_iteration_do(False)
                    time.sleep(.002)
            settle();window.current_day=datetime.date(2026,10,26)
            for width in [296,320,360,420]:
                window.panel.set_size_request(width,-1);window.select(datetime.date(2026,12,15));settle()
                self.assertEqual(window.panel.get_allocated_width(),width)
                self.assertFalse(window.date_title.get_layout().is_ellipsized())
        finally:
            window.destroy();self.Gtk.StyleContext.remove_provider_for_screen(self.Gdk.Screen.get_default(),provider)


if __name__=='__main__':unittest.main(verbosity=2)
