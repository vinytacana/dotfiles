"""Shared on-demand GTK widgets; no compositor, timer or service is started on import."""
import threading
import gi
gi.require_version('Gtk','3.0');gi.require_version('GtkLayerShell','0.1')
from gi.repository import Gtk,Gdk,GLib,GtkLayerShell

def label(text, style=None):
    widget=Gtk.Label(label=text,xalign=0);widget.set_line_wrap(True)
    if style:widget.get_style_context().add_class(style)
    return widget

def button(text,callback,icon=None):
    widget=Gtk.Button(label=text)
    if icon:
        widget.set_image(Gtk.Image.new_from_icon_name(icon,Gtk.IconSize.BUTTON));widget.set_always_show_image(True)
    widget.connect('clicked',lambda *_:callback())
    return widget

def async_update(work,done):
    def task():
        try:value=work()
        except Exception:value='Indisponível'
        GLib.idle_add(lambda:(done(value),False)[1])
    threading.Thread(target=task,daemon=True).start()

def app_image(app,size=28):
    image=Gtk.Image.new_from_gicon(app.get_icon(),Gtk.IconSize.DIALOG)
    image.set_pixel_size(size);return image

class Popup(Gtk.ApplicationWindow):
    """Transparent, input-only outside area gives reliable dismissal on Wayland."""
    def __init__(self,app,title,width=620,right=False):
        super().__init__(application=app,title=title)
        self.app=app;self.alive=True
        self.set_name('rice-overlay');self.set_decorated(False)
        visual=self.get_screen().get_rgba_visual()
        if visual:self.set_visual(visual)
        GtkLayerShell.init_for_window(self)
        GtkLayerShell.set_namespace(self,'niri-rice-popup')
        GtkLayerShell.set_layer(self,GtkLayerShell.Layer.OVERLAY)
        GtkLayerShell.set_keyboard_mode(self,GtkLayerShell.KeyboardMode.EXCLUSIVE)
        GtkLayerShell.set_exclusive_zone(self,0)
        for edge in [GtkLayerShell.Edge.TOP,GtkLayerShell.Edge.BOTTOM,GtkLayerShell.Edge.LEFT,GtkLayerShell.Edge.RIGHT]:GtkLayerShell.set_anchor(self,edge,True)
        # GDK exposes connector names on Wayland, so follow Niri's focused output.
        try:
            import json,subprocess
            focused=json.loads(subprocess.check_output(['niri','msg','-j','focused-output'],text=True,timeout=2))
            screen=Gdk.Screen.get_default();display=Gdk.Display.get_default()
            for index in range(display.get_n_monitors()):
                if screen.get_monitor_plug_name(index)==focused['name']:GtkLayerShell.set_monitor(self,display.get_monitor(index));break
        except Exception:pass
        outside=Gtk.EventBox();outside.set_visible_window(False)
        self.add(outside)
        self.panel=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=12)
        self.panel.get_style_context().add_class('popup-card')
        self.panel.set_size_request(width,-1)
        self.panel.set_halign(Gtk.Align.END if right else Gtk.Align.CENTER)
        self.panel.set_valign(Gtk.Align.START if right else Gtk.Align.CENTER)
        self.panel.set_margin_top(50 if right else 24);self.panel.set_margin_bottom(24)
        self.panel.set_margin_end(14 if right else 24);self.panel.set_margin_start(24)
        outside.add(self.panel)
        def outside_click(_,event):
            source=Gtk.get_event_widget(event)
            while source:
                if source==self.panel:return False
                source=source.get_parent()
            self.destroy();return True
        outside.connect('button-press-event',outside_click)
        self.connect('key-press-event',self.escape)
        self.connect('destroy',lambda *_:setattr(self,'alive',False))
    def escape(self,_,event):
        if event.keyval==Gdk.KEY_Escape:self.destroy();return True
        return False
