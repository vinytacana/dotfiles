"""Mocha OSD models, real GTK widgets and event/lifecycle regression tests.

No volume/layout changes, key injection, locking or authentication.
"""
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch, Mock
sys.dont_write_bytecode=True
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import rice_osd as osd


def settle(seconds=.04):
    until=time.monotonic()+seconds
    while time.monotonic()<until:
        while osd.GLib.MainContext.default().pending():osd.GLib.MainContext.default().iteration(False)
        time.sleep(.002)


class Models(unittest.TestCase):
    def test_volume_zero_is_not_mute_and_boost_is_not_clamped(self):
        self.assertFalse(osd.volume_model('Volume: 0.00')['muted'])
        self.assertEqual(osd.volume_model('Volume: 1.35')['percent'],135)
        self.assertTrue(osd.volume_model('Volume: 0.82 [MUTED]')['muted'])
    def test_invalid_volume_cannot_be_displayed(self):
        for text in ['Volume: nan','Volume: -1','Volume: inf']:
            with self.assertRaises(ValueError):osd.volume_model(text)
    def test_layout_order_and_variants_are_preserved(self):
        value=osd.layout_model(['Portuguese (Brazil)','English (US)'],1)
        self.assertEqual([v['code'] for v in value['items']],['PT','EN'])
        self.assertEqual(value['index'],1)
        self.assertEqual(osd.layout_model(['English (US, intl., with dead keys)'],0)['items'][0]['name'],'English (US, intl., with dead keys)')
    def test_unknown_layout_index_is_not_guessed(self):
        for names,index in [([],0),(['x'],2),(['x'],-1),(['x'],None)]:self.assertIsNone(osd.layout_model(names,index))
    def test_caps_leds_consensus_hotplug_and_conflict(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);self.assertIsNone(osd.caps_state(root))
            (root/'capabilities').mkdir()
            (root/'capabilities/key').write_text(format((1<<30)|(1<<44)|(1<<58),'x'))
            for name in ['input3','input47']:
                (root/(name+'::capslock')).mkdir();(root/(name+'::capslock/brightness')).write_text('0')
            self.assertIs(osd.caps_state(root),False)
            (root/'input3::capslock/brightness').write_text('1');self.assertIsNone(osd.caps_state(root))
            (root/'input47::capslock/brightness').write_text('1');self.assertIs(osd.caps_state(root),True)
            (root/'input47::capslock/brightness').unlink();self.assertIs(osd.caps_state(root),True)
    def test_caps_ignores_mouse_leds_without_alphabetic_keyboard_capabilities(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);leds=root/'leds';leds.mkdir()
            for name,keys,value in [('keyboard',(1<<30)|(1<<44)|(1<<58),1),('mouse',1<<58,0)]:
                device=root/name;(device/'capabilities').mkdir(parents=True)
                (device/'capabilities/key').write_text(format(keys,'x'))
                lamp=device/(name+'::capslock');lamp.mkdir();(lamp/'brightness').write_text(str(value))
                (leds/lamp.name).symlink_to(lamp)
            self.assertIs(osd.caps_state(leds),True)
            (leds/'keyboard::capslock').unlink();self.assertIsNone(osd.caps_state(leds))
    def test_strict_preferences_and_timeout_bounds(self):
        self.assertEqual(osd.preferences({'timeout_ms':1000})['volume_timeout_ms'],1000)
        self.assertEqual(osd.preferences({'timeout_ms':1700}),osd.DEFAULTS)
        self.assertEqual(osd.preferences({'timeout_ms':3000})['layout_timeout_ms'],400)
        for prefs in [{'volume':'yes'},{'timeout_ms':0},{'timeout_ms':True},{'unknown':True},
                      {'layout_timeout_ms':True},{'layout_timeout_ms':1700},{'caps_timeout_ms':0}]:
            with self.assertRaises(ValueError):osd.preferences(prefs)
    def test_indicator_budgets_are_independent_and_include_fade(self):
        prefs=osd.preferences()
        for kind,expected in [('volume',1350),('caps',900),('layout',400)]:
            model={'kind':kind}
            self.assertEqual(osd.hold_ms(model,prefs)+osd.transition_ms(model,prefs),expected)
            reduced={**prefs,'reduced_motion':True}
            self.assertEqual(osd.transition_ms(model,reduced),0)
            self.assertEqual(osd.hold_ms(model,reduced),expected)
    def test_session_must_be_known_unlocked_active_wayland_and_same_user(self):
        props={'User':(os.getuid(),'/u'),'Active':True,'Type':'wayland','LockedHint':False}
        self.assertTrue(osd.session_allowed(props))
        for key,value in [('LockedHint',True),('Active',False),('Type','tty'),('User',(-1,'/u'))]:
            self.assertFalse(osd.session_allowed({**props,key:value}))
        self.assertFalse(osd.session_allowed({}))


class Lifecycle(unittest.TestCase):
    def test_repeated_layout_events_replace_timeout_and_keep_latest_selection(self):
        app=osd.OSDApplication();app.alive=True;app.session_proxy=object();app.session_path='/session'
        props={'User':(os.getuid(),'/u'),'Active':True,'Type':'wayland','LockedHint':False}
        app.session_bus=SimpleNamespace(call_finish=lambda _:SimpleNamespace(unpack=lambda:(props,)))
        app.session_bus.call=lambda *args:args[-2](app.session_bus,None)
        app.window=Mock();app.window.revealer=Mock();app.prefs['layout_timeout_ms']=200
        with patch.object(osd,'locker_running',return_value=False),patch.object(app,'monitor',return_value=object()):
            names=['Portuguese (Brazil)','English (US)']
            app.present(osd.layout_model(names,0));settle(.04)
            app.present(osd.layout_model(names,1));settle(.04)
            app.present(osd.layout_model(names,0));settle(.14)
            app.window.hide.assert_not_called()
            self.assertEqual(app.model['index'],0)
            settle(.12)
            app.window.hide.assert_called_once()
            self.assertIsNone(app.model);self.assertEqual(app.sources.ids,{})
        app.sources.close()
    def test_control_center_shares_audio_watch_and_retains_fallback(self):
        from rice_control_center import ControlCenter
        panel=SimpleNamespace(subscriptions=[],queue_refresh=Mock(),
                              stop_audio_watch=Mock(),start_audio_watch=Mock())
        bus=Mock()
        with patch.object(osd.Gio,'bus_get_sync',return_value=bus), \
             patch.object(osd.Gio,'bus_watch_name_on_connection',return_value=73) as watch:
            ControlCenter.watch_events(panel)
            self.assertEqual(panel.osd_name_watch,73)
            panel.start_audio_watch.assert_not_called()
            appeared,vanished=watch.call_args.args[-2:]
            appeared();panel.stop_audio_watch.assert_called_once()
            vanished();panel.start_audio_watch.assert_called_once()
            audio=bus.signal_subscribe.call_args.args
            self.assertEqual(audio[:4],(osd.NAME,osd.NAME,'AudioChanged',osd.OBJECT))
            audio[-1]();panel.queue_refresh.assert_called_once()

    def test_replacing_timer_and_close_releases_all_sources(self):
        timers=osd.Sources();calls=[]
        timers.later('hide',5,lambda:calls.append('stale'))
        timers.later('hide',5,lambda:calls.append('latest'));settle()
        self.assertEqual(calls,['latest']);self.assertEqual(timers.ids,{})
        timers.later('x',10,lambda:calls.append('orphan'));timers.close();settle()
        self.assertEqual(calls,['latest']);self.assertEqual(timers.ids,{})
    def test_native_layout_events_initial_state_and_fast_final_selection(self):
        app=osd.OSDApplication()
        with patch.object(app,'present') as show:
            app.layout_event({'KeyboardLayoutsChanged':{'keyboard_layouts':{'names':['Portuguese (Brazil)','English (US)'],'current_idx':1}}})
            show.assert_not_called()
            for index in [0,1,0]:app.layout_event({'KeyboardLayoutSwitched':{'idx':index}})
            self.assertEqual(show.call_count,3);self.assertEqual(show.call_args.args[0]['index'],0)
            app.layout_event({'WindowFocusChanged':{'id':123}});self.assertEqual(show.call_count,3)
    def test_caps_only_emits_real_changes_and_suppresses_disagreement(self):
        app=osd.OSDApplication();app.alive=False
        with patch.object(osd,'caps_state',side_effect=[False,True,True,None,False,True]),patch.object(app,'present') as show:
            for _ in range(6):app.poll_caps()
            self.assertEqual([c.args[0]['enabled'] for c in show.call_args_list],[True,True])
    def test_audio_events_coalesce_and_do_not_change_volume(self):
        app=osd.OSDApplication();bus=Mock()
        with patch.object(app,'get_dbus_connection',return_value=bus),patch.object(app,'read_volume') as read:
            for _ in range(20):app.audio_event(b"Event 'change' on sink #1")
            self.assertEqual(list(app.sources.ids),['volume-refresh']);settle(.09)
            read.assert_called_once_with(True)
            app.audio_event(b"Event 'change' on source #2");self.assertEqual(app.sources.ids,{})
        app.sources.close()
    def test_coalesced_audio_reply_does_not_consume_final_state(self):
        app=osd.OSDApplication();app.alive=True;app.last_volume=osd.volume_model('Volume: 0.25')
        callbacks=[]
        child=Mock();child.get_successful.return_value=True
        child.communicate_utf8_finish.return_value=(True,'Volume: 0.75','')
        child.communicate_utf8_async.side_effect=lambda _,__,done,___:callbacks.append(done)
        with patch.object(osd.Gio.Subprocess,'new',return_value=child),patch.object(app,'present') as show:
            app.read_volume(True);app.read_volume(True)
            callbacks[0](child,None);show.assert_not_called()
            callbacks[1](child,None);show.assert_called_once_with(osd.volume_model('Volume: 0.75'))
        app.sources.close()
    def test_disabled_caps_stops_reading_and_scheduling(self):
        app=osd.OSDApplication();app.alive=True;app.prefs['caps']=False
        with patch.object(osd,'caps_state') as read:
            app.poll_caps();read.assert_not_called();self.assertEqual(app.sources.ids,{})
    def test_stale_lock_queries_cannot_present_old_states(self):
        app=osd.OSDApplication();app.alive=True;app.session_proxy=object();app.session_path='/session'
        callbacks=[];props={'User':(os.getuid(),'/u'),'Active':True,'Type':'wayland','LockedHint':False}
        app.session_bus=SimpleNamespace(call=lambda *args:callbacks.append(args[-2]),call_finish=lambda _:SimpleNamespace(unpack=lambda:(props,)))
        app.window=Mock();app.window.revealer=Mock()
        with patch.object(osd,'locker_running',return_value=False),patch.object(app,'monitor',return_value=object()):
            app.present(osd.volume_model('Volume: 0.25'));app.present(osd.volume_model('Volume: 0.75'))
            callbacks[0](app.session_bus,None);app.window.update.assert_not_called()
            callbacks[1](app.session_bus,None);self.assertEqual(app.window.update.call_args.args[0]['percent'],75)
            props['LockedHint']=True;app.present({'kind':'caps','enabled':True});callbacks[-1](app.session_bus,None)
            self.assertEqual(app.window.update.call_count,1);app.window.hide.assert_called()
        app.sources.close()
    def test_unknown_lock_or_disabled_indicator_never_requests_presentation(self):
        app=osd.OSDApplication();app.session_bus=Mock();app.window=Mock()
        app.present(osd.volume_model('Volume: 0.75'));app.session_bus.call.assert_not_called()
        app.session_proxy=object();app.prefs['volume']=False;app.present(osd.volume_model('Volume: 0.75'))
        app.session_bus.call.assert_not_called();app.sources.close()


class Presentation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not osd.Gtk.init_check()[0]:raise unittest.SkipTest('GTK display unavailable')
        osd.load_css()
    def test_css_and_all_seven_states_fit_without_clipping(self):
        with tempfile.TemporaryDirectory() as folder:
            osd.preview(Path(folder));paths=list(Path(folder).glob('*.png'));self.assertEqual(len(paths),7)
            for path in paths:
                from gi.repository import GdkPixbuf
                image=GdkPixbuf.Pixbuf.new_from_file(str(path))
                self.assertGreater(image.get_width(),200);self.assertLess(image.get_width(),650)
                self.assertLess(image.get_height(),200)
    def test_volume_has_stable_width_and_caps_class(self):
        widths=[]
        for raw in ['Volume: 0.25','Volume: 0.75','Volume: 0.75 [MUTED]','Volume: 1.35']:
            window=osd.Gtk.OffscreenWindow();window.set_name('mocha-osd');widget=osd.content(osd.volume_model(raw));window.add(widget);window.show_all();settle()
            widths.append(widget.get_allocated_width());window.destroy()
        self.assertEqual(len(set(widths)),1)
        widget=osd.content({'kind':'caps','enabled':True})
        self.assertTrue(widget.get_children()[0].get_style_context().has_class('caps-active'));widget.destroy()
    def test_language_cards_show_complete_native_names_and_codes(self):
        window=osd.Gtk.OffscreenWindow();window.set_name('mocha-osd')
        card=osd.content(osd.layout_model(['Portuguese (Brazil)','English (US)'],1))
        window.add(card);window.show_all();settle()
        try:
            self.assertGreaterEqual(card.get_allocated_width(),400)
            self.assertLessEqual(card.get_allocated_width(),600)
            for tile in card.get_children()[0].get_children():
                for label in tile.get_children():self.assertFalse(label.get_layout().is_ellipsized())
        finally:window.destroy()
    def test_passive_surface_cannot_take_keyboard_focus(self):
        if not osd.GtkLayerShell.is_supported():raise unittest.SkipTest('layer-shell unavailable')
        app=osd.Gtk.Application(application_id='org.niri.MochaOSD.Tests',flags=osd.Gio.ApplicationFlags.NON_UNIQUE);app.register(None)
        window=osd.OSDWindow(app)
        try:
            self.assertEqual(osd.GtkLayerShell.get_keyboard_mode(window),osd.GtkLayerShell.KeyboardMode.NONE)
            self.assertFalse(window.get_accept_focus());self.assertFalse(window.get_focus_on_map())
            self.assertEqual(osd.GtkLayerShell.get_exclusive_zone(window),-1)
        finally:window.destroy()


if __name__=='__main__':unittest.main(verbosity=2)
