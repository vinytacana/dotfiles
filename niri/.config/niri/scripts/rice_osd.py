"""Mocha OSD: one passive presenter, Niri/Pulse events, read-only LED fallback.

No input devices, key events, screenshots, authentication or shell commands.
Caps LEDs have no change notification in input-leds; use 2 small reads/s, not
an evdev listener requiring privileges. Disagreement means unknown, never guess.
"""
import json
import math
import os
from pathlib import Path
import socket
import struct
import subprocess
import sys

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('GtkLayerShell', '0.1')
from gi.repository import Gtk, Gdk, Gio, GLib, GtkLayerShell
from rice_common import ROOT, STATE, read_json, write_json

NAME = 'org.niri.MochaOSD'
OBJECT = '/org/niri/MochaOSD'
UNIT = 'niri-rice-osd.service'
PREFERENCES = STATE/'mocha-osd/preferences.json'
DEFAULTS = {'volume': True, 'layout': True, 'caps': True, 'timeout_ms': 1700,
            'compact': False, 'reduced_motion': False}
INTERFACE = '''<node><interface name="org.niri.MochaOSD">
<method name="Show"><arg type="s" direction="in"/></method>
<method name="Configure"><arg type="s" direction="in"/><arg type="s" direction="out"/></method>
<method name="Status"><arg type="s" direction="out"/></method>
<signal name="AudioChanged"/>
</interface></node>'''


def preferences(value=None):
    if value is None:
        try: value = read_json(PREFERENCES, {})
        except (OSError, ValueError): value = {}
    result = DEFAULTS.copy()
    if not isinstance(value, dict): raise ValueError('Preferências inválidas')
    for key, item in value.items():
        if key not in DEFAULTS: raise ValueError('Preferência desconhecida')
        if key == 'timeout_ms':
            if type(item) is not int or not 700 <= item <= 5000: raise ValueError('Tempo deve ser 700–5000 ms')
        elif type(item) is not bool: raise ValueError('Preferência deve ser booleana')
        result[key] = item
    return result


def query(args):
    return subprocess.check_output(args, text=True, stderr=subprocess.DEVNULL,
                                   env={**os.environ, 'LC_ALL': 'C'}, timeout=2).strip()


def niri(request):
    """One short IPC request. No CLI child for each layout/monitor query."""
    with socket.socket(socket.AF_UNIX) as sock:
        sock.settimeout(.5); sock.connect(os.environ['NIRI_SOCKET'])
        sock.sendall((json.dumps(request)+'\n').encode())
        with sock.makefile('rb') as stream: reply = json.loads(stream.readline(1024*1024))
    if 'Ok' not in reply: raise RuntimeError('Niri IPC indisponível')
    return reply['Ok']


def volume_model(text):
    fields = text.split()
    value = float(fields[1])
    if not math.isfinite(value) or value < 0: raise ValueError('Volume inválido')
    muted = '[MUTED]' in fields
    return {'kind': 'volume', 'percent': round(value*100), 'muted': muted,
            'icon': 'audio-volume-muted-symbolic' if muted else
                    'audio-volume-low-symbolic' if value <= .33 else
                    'audio-volume-medium-symbolic' if value <= .66 else 'audio-volume-high-symbolic'}


def layout_model(names, index):
    if not names or type(index) is not int or not 0 <= index < len(names): return None
    items = []
    for name in names:
        if name == 'English (US)': code, title = 'EN', 'English (US)'
        elif name == 'Portuguese (Brazil)': code, title = 'PT', 'Português (Brasil)'
        else: code, title = '⌨', name  # Preserve unknown layouts/variants verbatim.
        items.append({'code': code, 'name': title})
    return {'kind': 'layout', 'items': items, 'index': index}


def caps_state(folder=Path('/sys/class/leds')):
    values = []
    for path in folder.glob('*::capslock/brightness'):
        try:
            # Some composite mice expose a permanently-off Caps LED. Identify
            # alphabetic keyboards by their supported keys, never by a device
            # name, a captured key event, or an assumed internal/USB connector.
            words=(path.resolve().parent.parent/'capabilities/key').read_text().split()
            bits=sum(int(word,16) << (index*struct.calcsize('L')*8)
                     for index,word in enumerate(reversed(words)))
            if not all(bits & (1 << key) for key in [30,44,58]): continue  # KEY_A, KEY_Z, KEY_CAPSLOCK
            values.append(int(path.read_text().strip()) > 0)
        except (OSError, ValueError): continue
    return values[0] if values and len(set(values)) == 1 else None


def session_allowed(props):
    user = props.get('User', (-1, ''))
    return (props.get('LockedHint') is False and props.get('Active') is True
            and props.get('Type') == 'wayland' and user[0] == os.getuid())


def locker_running():
    for proc in Path('/proc').iterdir():
        if not proc.name.isdigit(): continue
        try:
            if proc.stat().st_uid == os.getuid() and (proc/'comm').read_text().strip() in {'gtklock','swaylock'}:
                if (proc/'stat').read_text().rsplit(')',1)[1].split()[0] != 'Z': return True
        except FileNotFoundError: continue
        except OSError: return True  # Unknown: do not show.
    return False


class Sources:
    """Own every GLib source; replacement and close cannot leave old callbacks."""
    def __init__(self): self.ids = {}
    def cancel(self, key):
        identity = self.ids.pop(key, 0)
        if identity and GLib.MainContext.default().find_source_by_id(identity): GLib.source_remove(identity)
    def later(self, key, delay, callback):
        self.cancel(key)
        def invoke():
            self.ids.pop(key, None); callback(); return False
        self.ids[key] = GLib.timeout_add(delay, invoke)
    def close(self):
        for key in list(self.ids): self.cancel(key)


def content(model, compact=False):
    card = Gtk.Box(spacing=14)
    card.get_style_context().add_class('mocha-osd-card')
    if compact: card.get_style_context().add_class('compact')
    kind = model['kind']
    if kind == 'layout':
        grid = Gtk.Grid(column_spacing=12, row_spacing=12, column_homogeneous=True)
        card.pack_start(grid, False, False, 0)
        for index, item in enumerate(model['items']):
            tile = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
            tile.set_size_request(166 if compact else 186, -1)
            tile.get_style_context().add_class('layout-option')
            if index == model['index']: tile.get_style_context().add_class('selected')
            for key, style in [('code','layout-code'),('name','layout-name')]:
                label = Gtk.Label(label=item[key]); label.set_single_line_mode(True)
                if key == 'name':
                    label.set_width_chars(16); label.set_max_width_chars(24); label.set_ellipsize(3)
                label.get_style_context().add_class(style); tile.pack_start(label, False, False, 0)
            grid.attach(tile,index%3,index//3,1,1)
        return card
    icon = Gtk.Image.new_from_icon_name(model.get('icon', 'caps-lock-symbolic'), Gtk.IconSize.DIALOG)
    icon.set_pixel_size(24 if compact else 28); card.pack_start(icon, False, False, 0)
    if kind == 'volume':
        progress = Gtk.ProgressBar(); progress.set_size_request(174 if compact else 200, -1)
        progress.set_valign(Gtk.Align.CENTER)
        progress.set_fraction(0 if model['muted'] else min(model['percent']/100,1))
        if model['muted']: progress.get_style_context().add_class('muted')
        if model['percent'] > 100: progress.get_style_context().add_class('boosted')
        card.pack_start(progress, False, False, 0)
        text = 'Mudo' if model['muted'] else str(model['percent'])+'%'
        label = Gtk.Label(label=text); label.set_width_chars(6)
        label.get_style_context().add_class('percentage')
    else:
        label = Gtk.Label(label='Caps Lock '+('ativado' if model['enabled'] else 'desativado'))
        for widget in [icon,label]: widget.get_style_context().add_class('caps-active' if model['enabled'] else 'muted')
    card.pack_start(label, False, False, 0)
    return card


def load_css():
    provider = Gtk.CssProvider(); provider.load_from_path(str(ROOT/'mocha-osd.css'))
    Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)


class OSDWindow(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title='Mocha OSD')
        self.set_name('mocha-osd'); self.set_decorated(False); self.set_accept_focus(False); self.set_focus_on_map(False)
        visual = self.get_screen().get_rgba_visual()
        if visual: self.set_visual(visual)
        GtkLayerShell.init_for_window(self); GtkLayerShell.set_namespace(self, 'mocha-osd')
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.OVERLAY)
        GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.NONE)
        GtkLayerShell.set_exclusive_zone(self, -1)
        self.revealer = Gtk.Revealer(); self.revealer.set_transition_type(Gtk.RevealerTransitionType.CROSSFADE)
        self.revealer.set_transition_duration(180)
        # Room for shadow; no full-screen input surface, zero exclusive area.
        self.revealer.set_margin_top(16); self.revealer.set_margin_bottom(16)
        self.revealer.set_margin_start(16); self.revealer.set_margin_end(16)
        self.add(self.revealer)
        self.connect('map', self.pass_through)

    def pass_through(self, *_):
        import cairo
        if self.get_window(): self.get_window().input_shape_combine_region(cairo.Region(), 0, 0)

    def update(self, model, prefs, monitor):
        old = self.revealer.get_child()
        if old: self.revealer.remove(old); old.destroy()
        self.revealer.add(content(model, prefs['compact']))
        self.revealer.set_transition_duration(0 if prefs['reduced_motion'] else 180)
        GtkLayerShell.set_monitor(self, monitor)
        for edge in [GtkLayerShell.Edge.LEFT, GtkLayerShell.Edge.RIGHT, GtkLayerShell.Edge.TOP]:
            GtkLayerShell.set_anchor(self, edge, False)
        bottom = model['kind'] != 'layout'
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.BOTTOM, bottom)
        height = monitor.get_geometry().height
        GtkLayerShell.set_margin(self, GtkLayerShell.Edge.BOTTOM, min(130, max(80,height//8)) if bottom else 0)
        self.show_all(); self.revealer.set_reveal_child(True); self.pass_through()


class OSDApplication(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=NAME)
        self.sources = Sources(); self.alive = False; self.revision = 0
        try:self.prefs = preferences()
        except ValueError:
            print('Mocha OSD: preferências inválidas; usando padrões sem sobrescrever o arquivo.',file=sys.stderr)
            self.prefs = DEFAULTS.copy()
        self.names = []; self.index = None
        self.last_volume = None; self.last_caps = None; self.model = None
        self.niri_socket = None; self.audio_process = None; self.buffers = {}
        self.session_proxy = None; self.session_bus = None; self.session_path = None
        self.audio_generation = 0; self.registrations = []; self.watchers = []
        self.connect('activate', self.activate_osd); self.connect('shutdown', self.cleanup)

    def activate_osd(self, *_):
        if self.alive: return
        if 'niri' not in os.environ.get('XDG_CURRENT_DESKTOP','').split(':') or not os.getenv('NIRI_SOCKET'):
            self.quit(); return
        try:niri('Version')
        except (OSError,ValueError,KeyError,RuntimeError):self.quit();return
        self.alive = True; self.hold(); load_css(); self.window = OSDWindow(self)
        display = Gdk.Display.get_default()
        self.watchers.append((display, display.connect('monitor-removed', lambda *_: self.suppress())))
        self.watchers.append((display, display.connect('monitor-added', lambda *_: self.suppress())))
        interface = Gio.DBusNodeInfo.new_for_xml(INTERFACE).interfaces[0]
        self.registrations.append(self.get_dbus_connection().register_object(OBJECT, interface, self.dbus_call, None, None))
        self.connect_session(); self.connect_niri(); self.connect_audio(); self.poll_caps()

    def connect_session(self):
        try:
            # User-manager services don't belong to logind 'self'. Resolve Niri's
            # exact session, as in rice_recovery; never assume session 2 or tty.
            pid = int(query(['systemctl','--user','show','niri.service','-p','MainPID','--value']))
            entries = (Path('/proc')/str(pid)/'environ').read_bytes().split(b'\0')
            sid = next(v.split(b'=',1)[1].decode() for v in entries if v.startswith(b'XDG_SESSION_ID='))
            self.session_bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
            self.session_path = self.session_bus.call_sync('org.freedesktop.login1','/org/freedesktop/login1',
                'org.freedesktop.login1.Manager','GetSession',GLib.Variant('(s)',(sid,)),None,Gio.DBusCallFlags.NONE,1000,None).unpack()[0]
            self.session_proxy = Gio.DBusProxy.new_sync(self.session_bus,Gio.DBusProxyFlags.DO_NOT_AUTO_START,None,
                'org.freedesktop.login1',self.session_path,'org.freedesktop.login1.Session',None)
            self.watchers.append((self.session_proxy,self.session_proxy.connect('g-properties-changed', self.session_changed)))
        except (OSError,ValueError,StopIteration,subprocess.SubprocessError,GLib.Error):
            self.session_proxy = None
            self.sources.later('session-retry',5000,self.connect_session)

    def session_changed(self, *_):
        # Hide even for unrelated session-property changes; never risk a stale OSD.
        self.suppress(); self.last_caps = caps_state()

    def suppress(self):
        self.revision += 1; self.sources.cancel('hide'); self.sources.cancel('unmap')
        self.model = None
        if hasattr(self,'window'): self.window.hide(); self.window.revealer.set_reveal_child(False)

    def monitor(self):
        focused = niri('FocusedOutput').get('FocusedOutput') or {}
        display = Gdk.Display.get_default(); screen = Gdk.Screen.get_default()
        for index in range(display.get_n_monitors()):
            if screen.get_monitor_plug_name(index) == focused.get('name'): return display.get_monitor(index)
        outputs = niri('Outputs')['Outputs']
        for index in range(display.get_n_monitors()):
            if (outputs.get(screen.get_monitor_plug_name(index)) or {}).get('logical'): return display.get_monitor(index)
        raise RuntimeError('Nenhum monitor ativo')

    def present(self, model):
        self.revision += 1; revision = self.revision
        if not model or not self.prefs[model['kind']] or self.session_proxy is None:
            self.suppress(); return
        # Fresh asynchronous logind read before each presentation; known-unlocked
        # only. ext-session-lock additionally prevents these surfaces over a lock.
        def ready(bus, result, *_):
            if not self.alive or revision != self.revision: return
            try:
                props = bus.call_finish(result).unpack()[0]
                if not session_allowed(props) or locker_running(): self.suppress(); return
                monitor = self.monitor()
            except (GLib.Error,OSError,ValueError,KeyError,RuntimeError): self.suppress(); return
            self.model = model; self.sources.cancel('unmap'); self.window.update(model, self.prefs, monitor)
            self.sources.later('hide', self.prefs['timeout_ms'], self.fade_out)
        self.session_bus.call('org.freedesktop.login1', self.session_path,'org.freedesktop.DBus.Properties',
            'GetAll',GLib.Variant('(s)',('org.freedesktop.login1.Session',)),None,Gio.DBusCallFlags.NONE,700,None,ready,None)

    def fade_out(self):
        self.window.revealer.set_reveal_child(False)
        self.sources.later('unmap',0 if self.prefs['reduced_motion'] else 190,self.suppress)

    def layout_event(self, event):
        if 'KeyboardLayoutsChanged' in event:
            value = event['KeyboardLayoutsChanged']['keyboard_layouts']
            previous = (self.names,self.index); self.names=value['names']; self.index=value['current_idx']
            if previous[0] and previous != (self.names,self.index): self.present(layout_model(self.names,self.index))
        elif 'KeyboardLayoutSwitched' in event:
            index = event['KeyboardLayoutSwitched']['idx']
            if index != self.index:
                self.index=index; self.present(layout_model(self.names,index))

    def watch_fd(self, key, descriptor, on_line, on_close):
        self.buffers[key] = b''
        os.set_blocking(descriptor,False)
        def read(_fd, condition):
            try:
                chunk = os.read(descriptor,65536)
                if not chunk: raise EOFError()
                self.buffers[key] += chunk
                if len(self.buffers[key]) > 4*1024*1024: raise EOFError()
                while b'\n' in self.buffers[key]:
                    line,self.buffers[key] = self.buffers[key].split(b'\n',1)
                    on_line(line)
            except BlockingIOError: pass
            except (OSError,ValueError,KeyError,EOFError):
                self.sources.ids.pop(key,None); self.buffers.pop(key,None); on_close(); return False
            return self.alive
        self.sources.ids[key] = GLib.io_add_watch(descriptor,GLib.IOCondition.IN|GLib.IOCondition.HUP|GLib.IOCondition.ERR,read)

    def connect_niri(self):
        try:
            self.niri_socket = socket.socket(socket.AF_UNIX); self.niri_socket.settimeout(1)
            self.niri_socket.connect(os.environ['NIRI_SOCKET']); self.niri_socket.sendall(b'"EventStream"\n')
            self.watch_fd('niri',self.niri_socket.fileno(),lambda line:self.layout_event(json.loads(line)),self.niri_closed)
        except (OSError,KeyError): self.niri_closed()

    def niri_closed(self):
        self.suppress(); self.names=[];self.index=None
        if self.niri_socket:self.niri_socket.close();self.niri_socket=None
        if self.alive:self.sources.later('niri-retry',3000,self.connect_niri)

    def connect_audio(self):
        try:
            self.audio_process = subprocess.Popen(['pactl','subscribe'],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
                                                  env={**os.environ,'LC_ALL':'C'})
            self.watch_fd('audio',self.audio_process.stdout.fileno(),self.audio_event,self.audio_closed)
            self.read_volume(False)
        except OSError:self.audio_closed()

    def audio_event(self, line):
        # Sources also notify the control center, but never produce a sink OSD.
        if any(part in line for part in [b'on sink #',b'on source #',b'on server #']):
            self.get_dbus_connection().emit_signal(None,OBJECT,NAME,'AudioChanged',None)
        if any(part in line for part in [b'on sink #',b'on server #']):
            self.sources.later('volume-refresh',65,lambda:self.read_volume(True))

    def read_volume(self, show):
        # Async child coalescing: one wpctl at a time, latest event wins.
        self.audio_generation += 1
        if getattr(self,'volume_reading',False): self.volume_dirty = show; return
        self.volume_reading=True; self.volume_dirty=None
        process = Gio.Subprocess.new(['wpctl','get-volume','@DEFAULT_AUDIO_SINK@'],
                                    Gio.SubprocessFlags.STDOUT_PIPE|Gio.SubprocessFlags.STDERR_SILENCE)
        self.volume_query = process
        self.sources.later('volume-timeout',2200,process.force_exit)
        def done(child,result,*_):
            self.sources.cancel('volume-timeout')
            self.volume_reading=False; self.volume_query=None
            if not self.alive:return
            try:
                ok,stdout,_ = child.communicate_utf8_finish(result)
                model = volume_model(stdout) if ok and child.get_successful() else None
            except (GLib.Error,ValueError,IndexError): model=None
            pending = self.volume_dirty
            if model:
                changed = self.last_volume is not None and model != self.last_volume
                if pending is None:self.last_volume=model
                if show and changed and pending is None:self.present(model)
            else:self.last_volume=None;self.suppress()
            if pending is not None:self.read_volume(pending)
        process.communicate_utf8_async(None,None,done,None)

    def audio_closed(self):
        self.last_volume=None
        process=self.audio_process;self.audio_process=None
        if process:
            if process.poll() is None:process.terminate()
            try:process.wait(timeout=1)
            except subprocess.TimeoutExpired:process.kill();process.wait(timeout=1)
            process.stdout.close()
        if self.alive:self.sources.later('audio-retry',3000,self.connect_audio)

    def poll_caps(self):
        if not self.prefs['caps']:
            self.last_caps=None;return
        current = caps_state()
        if self.prefs['caps'] and current is not None and self.last_caps is not None and current != self.last_caps:
            self.present({'kind':'caps','enabled':current})
        self.last_caps=current
        if self.alive:self.sources.later('caps',500,self.poll_caps)

    def dbus_call(self,_bus,_sender,_path,_iface,method,params,invocation):
        try:
            if method=='Show':
                kind=params.unpack()[0]
                if kind=='volume':
                    value=volume_model(query(['wpctl','get-volume','@DEFAULT_AUDIO_SINK@']));self.present(value)
                elif kind=='layout':self.present(layout_model(self.names,self.index))
                elif kind=='caps':
                    value=caps_state()
                    if value is not None:self.present({'kind':'caps','enabled':value})
                else:raise ValueError('Indicador desconhecido')
                invocation.return_value(None)
            elif method=='Configure':
                self.prefs=preferences(json.loads(params.unpack()[0]));write_json(PREFERENCES,self.prefs);self.suppress()
                self.sources.cancel('caps');self.last_caps=None;self.poll_caps()
                invocation.return_value(GLib.Variant('(s)',(json.dumps(self.prefs),)))
            else:
                value={'preferences':self.prefs,'layout':layout_model(self.names,self.index),
                       'caps':caps_state(),'volume':self.last_volume,'visible':self.window.get_visible(),
                       'session_known':self.session_proxy is not None,
                       'niri_connected':self.niri_socket is not None,'audio_watching':self.audio_process is not None,
                       'kind':self.model['kind'] if self.model else None,'pid':os.getpid()}
                invocation.return_value(GLib.Variant('(s)',(json.dumps(value),)))
        except (OSError,ValueError,IndexError,subprocess.SubprocessError):invocation.return_dbus_error(NAME+'.Invalid','Estado indisponível ou preferência inválida')

    def cleanup(self,*_):
        self.alive=False;self.sources.close();self.revision+=1
        if getattr(self,'volume_query',None):self.volume_query.force_exit()
        if self.niri_socket:self.niri_socket.close();self.niri_socket=None
        self.audio_closed()
        for obj,identity in self.watchers:obj.disconnect(identity)
        self.watchers.clear()
        if self.get_dbus_connection():
            for identity in self.registrations:self.get_dbus_connection().unregister_object(identity)
        self.registrations.clear()
        if hasattr(self,'window'):self.window.destroy()


def client(method, value=None):
    bus=Gio.bus_get_sync(Gio.BusType.SESSION,None)
    return bus.call_sync(NAME,OBJECT,NAME,method,GLib.Variant('(s)',(value,)) if value is not None else None,
                         None,Gio.DBusCallFlags.NO_AUTO_START,2500,None)


def preview(folder):
    """Offscreen GTK renders, not authentication or real hardware events."""
    Gtk.init([]);load_css();folder.mkdir(parents=True,exist_ok=True,mode=0o700)
    states={'volume-25':volume_model('Volume: 0.25'),'volume-75':volume_model('Volume: 0.75'),
            'volume-muted':volume_model('Volume: 0.75 [MUTED]'),
            'layout-en':layout_model(['Portuguese (Brazil)','English (US)'],1),
            'layout-pt':layout_model(['Portuguese (Brazil)','English (US)'],0),
            'caps-on':{'kind':'caps','enabled':True},'caps-off':{'kind':'caps','enabled':False}}
    for name,model in states.items():
        window=Gtk.OffscreenWindow();window.set_name('mocha-osd')
        box=Gtk.Box();box.set_border_width(20);box.add(content(model));window.add(box);window.show_all()
        while Gtk.events_pending():Gtk.main_iteration_do(False)
        window.get_pixbuf().savev(str(folder/(name+'.png')),'png',[],[]);window.destroy()
