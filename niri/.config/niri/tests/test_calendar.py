"""GTK calendar interactions; real layer-shell widgets, no system/session changes."""
import datetime
from pathlib import Path
import runpy
import sys
import time
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
namespace = runpy.run_path(str(ROOT/'scripts/rice-ui'), run_name='rice_calendar_tests')
CalendarWindow = namespace['CalendarWindow']
Gtk, Gdk, Gio, GLib = (namespace[name] for name in ['Gtk','Gdk','Gio','GLib'])


def settle():
    until = time.monotonic() + 0.12
    while time.monotonic() < until:
        while Gtk.events_pending() and time.monotonic() < until:
            Gtk.main_iteration_do(False)
        time.sleep(0.005)


class CalendarTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not Gtk.init_check()[0] or not namespace['GtkLayerShell'].is_supported():
            raise unittest.SkipTest('É necessária uma sessão gráfica com layer-shell.')
        cls.app = Gtk.Application(application_id='org.niri.Rice.CalendarTests', flags=Gio.ApplicationFlags.NON_UNIQUE)
        cls.app.register(None)
        cls.app.safe = lambda callback: callback()
        provider = Gtk.CssProvider()
        provider.load_from_path(str(ROOT/'rice-ui.css'))
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def setUp(self):
        self.window = CalendarWindow(self.app)
        self.addCleanup(self.window.destroy)

    def show(self):
        self.window.show_all()
        settle()

    def key(self, value):
        event = Gdk.Event.new(Gdk.EventType.KEY_PRESS)
        event.window = self.window.get_window()
        event.keyval = value
        event.state = Gdk.ModifierType(0)
        self.window.emit('key-press-event', event)
        settle()

    def test_grid_has_six_monday_first_weeks_and_portuguese_dates(self):
        self.window.select(datetime.date(2026, 10, 23))
        days = list(self.window.cells)
        self.assertEqual(len(days), 42)
        self.assertEqual(days[0], datetime.date(2026, 9, 28))
        self.assertEqual(days[0].weekday(), 0)
        self.assertEqual(days[-1], datetime.date(2026, 11, 8))
        self.assertIn('sexta-feira, 23 de outubro de 2026', self.window.date_text(datetime.date(2026,10,23)))
        self.assertTrue(self.window.cells[days[0]].get_style_context().has_class('outside-month'))

    def test_selected_day_and_today_remain_distinct(self):
        today = self.window.current_day
        other = today + datetime.timedelta(days=1)
        self.window.select(other)
        self.assertTrue(self.window.cells[today].get_style_context().has_class('today'))
        self.assertFalse(self.window.cells[today].get_style_context().has_class('selected'))
        self.assertTrue(self.window.cells[other].get_style_context().has_class('selected'))
        self.assertEqual(sum(cell.get_can_focus() for cell in self.window.cells.values()),1)
        self.window.cells[today].clicked()
        self.assertEqual(self.window.selected,today)

    def test_month_buttons_clamp_days_and_cross_years(self):
        self.window.select(datetime.date(2024,1,31))
        self.window.next_button.clicked()
        self.assertEqual(self.window.selected,datetime.date(2024,2,29))
        self.window.select(datetime.date(2026,12,31))
        self.window.next_button.clicked()
        self.assertEqual(self.window.selected,datetime.date(2027,1,31))
        self.window.previous_button.clicked()
        self.assertEqual(self.window.selected,datetime.date(2026,12,31))

    def test_keyboard_moves_selection_and_returns_home(self):
        self.show()
        self.window.select(datetime.date(2026,10,31))
        self.key(Gdk.KEY_Right)
        self.assertEqual(self.window.selected,datetime.date(2026,11,1))
        self.key(Gdk.KEY_Up)
        self.assertEqual(self.window.selected,datetime.date(2026,10,25))
        self.key(Gdk.KEY_Page_Up)
        self.assertEqual(self.window.selected,datetime.date(2026,9,25))
        self.key(Gdk.KEY_Page_Down)
        self.assertEqual(self.window.selected,datetime.date(2026,10,25))
        self.key(Gdk.KEY_Home)
        self.assertEqual(self.window.selected,datetime.date.today())
        self.assertEqual(self.window.get_focus(),self.window.cells[self.window.selected])

    def test_midnight_updates_today_without_overriding_other_selection(self):
        today = self.window.current_day
        tomorrow = today + datetime.timedelta(days=1)
        self.window.refresh_day(tomorrow)
        self.assertEqual(self.window.selected,tomorrow)
        self.assertTrue(self.window.cells[tomorrow].get_style_context().has_class('today'))
        other = tomorrow + datetime.timedelta(days=3)
        self.window.select(other)
        self.window.refresh_day(tomorrow + datetime.timedelta(days=1))
        self.assertEqual(self.window.selected,other)
        self.assertIn(self.window.date_text(self.window.current_day),self.window.date_title.get_text())
        self.assertGreater(self.window.midnight_source,0)

    def test_escape_and_outside_click_destroy_and_cancel_timer(self):
        self.show()
        self.key(Gdk.KEY_Escape)
        self.assertFalse(self.window.alive)
        self.assertEqual(self.window.midnight_source,0)
        self.window = CalendarWindow(self.app)
        self.addCleanup(self.window.destroy)
        self.show()
        event = Gdk.Event.new(Gdk.EventType.BUTTON_PRESS)
        event.window = self.window.get_window()
        event.button = 1
        self.window.get_child().emit('button-press-event',event)
        self.assertFalse(self.window.alive)
        self.assertEqual(self.window.midnight_source,0)

    def test_calendar_launcher_uses_existing_desktop_and_closes(self):
        calls=[]
        with patch.dict(CalendarWindow.open_calendar.__globals__,open_or_focus=lambda identity:calls.append(identity)):
            self.window.open_button.clicked()
        self.assertEqual(calls,['org.gnome.Calendar.desktop'])
        self.assertFalse(self.window.alive)

    def test_mapped_grid_geometry_hover_and_narrow_card(self):
        self.show()
        sizes=[]
        for month in [2,3,8,10]:
            self.window.select(datetime.date(2026,month,15))
            settle()
            sizes.append((self.window.panel.get_allocated_width(),self.window.panel.get_allocated_height()))
            cells=list(self.window.cells.values())
            for row in range(6):
                positions=[cell.translate_coordinates(self.window.grid,0,0) for cell in cells[row*7:row*7+7]]
                self.assertEqual(len({y for x,y in positions}),1)
                self.assertEqual(sorted(x for x,y in positions),[x for x,y in positions])
        self.assertEqual(len(set(sizes)),1)
        for width in [296,320,360,420]:
            self.window.panel.set_size_request(width,-1)
            settle()
            self.assertLessEqual(self.window.panel.get_allocated_width(),width)
        date = next(d for d in self.window.cells if d.month==self.window.month and d!=self.window.selected and d!=self.window.current_day)
        cell=self.window.cells[date]
        cell.set_state_flags(Gtk.StateFlags.PRELIGHT,False)
        settle()
        self.assertTrue(cell.get_state_flags() & Gtk.StateFlags.PRELIGHT)

    def test_long_portuguese_dates_do_not_set_card_natural_width(self):
        # Fixed dates reproduce the 309px Monday header regardless of when this
        # test is run. Changing the expected width would conceal the defect.
        self.show()
        for today in [datetime.date(2026,10,26), datetime.date(2026,9,30)]:
            self.window.current_day=today
            for width in [296,320,360,420]:
                self.window.panel.set_size_request(width,-1)
                sizes=[]
                for year,month in [(2026,2),(2026,3),(2026,8),(2026,9),(2026,12),(2027,1)]:
                    self.window.select(datetime.date(year,month,15))
                    settle()
                    panel=self.window.panel
                    sizes.append((panel.get_allocated_width(),panel.get_allocated_height()))
                    self.assertEqual(panel.get_allocated_width(),width)
                    self.assertFalse(self.window.month_title.get_layout().is_ellipsized())
                    self.assertFalse(self.window.date_title.get_layout().is_ellipsized())
                    self.assertEqual(self.window.date_title.get_tooltip_text(),self.window.date_text(today))
                    for cell in self.window.cells.values():
                        x,y=cell.translate_coordinates(panel,0,0)
                        self.assertGreaterEqual(x,0)
                        self.assertLessEqual(x+cell.get_allocated_width(),width)
                        self.assertGreaterEqual(cell.get_allocated_width(),34)
                        self.assertGreaterEqual(cell.get_allocated_height(),32)
                        self.assertFalse(cell.get_child().get_layout().is_ellipsized())
                self.assertEqual(len(set(sizes)),1)


if __name__ == '__main__':
    unittest.main(verbosity=2)
