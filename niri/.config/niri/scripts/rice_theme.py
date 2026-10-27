"""Orbit/Mocha palettes and bounded, atomic theme application. No resident process.

The existing Mocha styles are preserved as templates. Only reviewed CSS color
literals are mapped; semantic exceptions (selection vs accent) live in the
small Orbit stylesheets. Geometry, commands and image URLs are never rewritten.
"""
import configparser
import fcntl
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import tomllib

from rice_common import ROOT, STATE, read_json
from rice_bar import atomic_text, update_lock, restart

PREFERENCE = STATE/'visual-theme.json'
GENERATED = STATE/'theme'
COMPONENTS = {'ui':'rice-ui.css', 'osd':'mocha-osd.css',
              'swaync':'swaync.css', 'gtklock':'gtklock/style.css'}
# Background, surface, text, accent and status roles audited in the Mocha CSS.
SOURCE_ROLES = {
    '#11111b':'background-deep', '#000000':'background-deep',
    '#1e1e2e':'background-main', '#181825':'background-elevated',
    '#313244':'surface', '#45475a':'surface-hover', '#585b70':'border-subtle',
    '#cdd6f4':'text-primary', '#bac2de':'text-secondary', '#a6adc8':'text-secondary',
    '#9399b2':'text-muted', '#6c7086':'text-muted',
    '#b4befe':'primary', '#89b4fa':'primary-strong', '#cba6f7':'secondary-accent',
    '#f5c2e7':'tertiary-accent', '#f5e0dc':'tertiary-accent',
    '#a6e3a1':'success', '#94e2d5':'success', '#f9e2af':'warning',
    '#fab387':'warning', '#f38ba8':'danger',
}


def palettes():
    return json.loads((ROOT/'themes/palettes.json').read_text())


def current():
    name = read_json(PREFERENCE, {'theme':'mocha'}).get('theme')
    if name not in palettes(): raise ValueError('Tema visual desconhecido')
    return name


def palette(name=None):
    return palettes()[name or current()]['colors']


def rgb(color):
    return tuple(int(color[index:index+2],16) for index in [1,3,5])


def colorize(text, name=None):
    """CSS/Pango literals only. Brands (e.g. the Spotify icon) stay unchanged."""
    name = name or current()
    if name == 'mocha': return text
    colors = palette(name)
    def hex_color(match):
        value=match.group();role=SOURCE_ROLES.get(value[:7].lower())
        return colors[role]+value[7:] if role else value
    text=re.sub(r'#[0-9a-fA-F]{6}(?:[0-9a-fA-F]{2})?\b',hex_color,text)
    def rgba_color(match):
        parts=match.group(2).split(',')
        try: old='#'+''.join(f'{int(x.strip()):02x}' for x in parts[:3])
        except ValueError:return match.group()
        role=SOURCE_ROLES.get(old)
        if not role:return match.group()
        values=[str(x) for x in rgb(colors[role])]+parts[3:]
        return match.group(1)+'('+','.join(values)+')'
    return re.sub(r'\b(rgba?)\(([^()]+)\)',rgba_color,text)


def css(component, name=None, source=None):
    name=name or current()
    base=source if source is not None else (ROOT/COMPONENTS[component]).read_text()
    if name=='mocha':return base
    tokens='\n'.join('@define-color orbit_'+key.replace('-','_')+' '+value+';' for key,value in palette(name).items())
    # GTK4's SwayNC default stylesheet consumes this RGB custom property.
    base=colorize(base,name)
    if component=='swaync':base=base.replace('--noti-bg: 24,24,37','--noti-bg: '+','.join(map(str,rgb(palette(name)['background-elevated']))))
    override=ROOT/'themes'/('orbit-'+component+'.css')
    return tokens+'\n'+base+'\n'+(override.read_text() if override.is_file() else '')


def active_css(component):
    path=GENERATED/(component+'.css')
    return path if path.is_file() else ROOT/COMPONENTS[component]


def niri_colors(name):
    colors=palette(name)
    # Mocha's exact original colors and Niri's default urgency color.
    active=colors['secondary-accent'] if name=='mocha' else colors['primary']
    inactive='#45475a' if name=='mocha' else colors['border-subtle']
    urgent='#9b0000' if name=='mocha' else colors['danger']
    return f'layout {{\n    focus-ring {{ active-color "{active}"; inactive-color "{inactive}"; urgent-color "{urgent}"; }}\n    background-color "{colors["background-main"]}"\n}}\n'


def alacritty_colors(name):
    c=palette(name)
    if name=='mocha':return '[colors.primary]\nbackground = "#1e1e2e"\nforeground = "#cdd6f4"\n'
    sections={'primary':{'background':c['background-main'],'foreground':c['text-primary']},
              'cursor':{'cursor':c['primary'],'text':c['background-deep']},
              'vi_mode_cursor':{'cursor':c['secondary-accent'],'text':c['background-deep']},
              'selection':{'background':c['primary-strong'],'text':c['text-primary']},
              'search.matches':{'background':c['surface-hover'],'foreground':c['text-primary']},
              'search.focused_match':{'background':c['primary'],'foreground':c['background-deep']},
              'hints.start':{'background':c['secondary-accent'],'foreground':c['background-deep']},
              'hints.end':{'background':c['surface-hover'],'foreground':c['text-primary']},
              'footer_bar':{'background':c['surface'],'foreground':c['text-primary']}}
    ansi={'black':c['background-elevated'],'red':c['danger'],'green':c['success'],
          'yellow':c['warning'],'blue':c['primary-strong'],'magenta':c['secondary-accent'],
          'cyan':c['primary'],'white':c['text-secondary']}
    for group in ['normal','bright','dim']:sections[group]=dict(ansi)
    sections['bright']['blue']=c['primary'];sections['bright']['magenta']=c['tertiary-accent'];sections['bright']['white']=c['text-primary']
    text='\n'.join('[colors.'+key+']\n'+'\n'.join(f'{k} = "{v}"' for k,v in value.items())+'\n' for key,value in sections.items())
    for index,color in [(16,c['warning']),(17,c['tertiary-accent'])]:text+=f'\n[[colors.indexed_colors]]\nindex = {index}\ncolor = "{color}"\n'
    return text


def fuzzel_config(name):
    base=(ROOT/'fuzzel.ini').read_text()
    if name=='mocha':return base
    parser=configparser.ConfigParser(interpolation=None);parser.read_string(base);c=palette(name)
    for key,role in {'background':'background-main','text':'text-primary','match':'primary',
                     'selection':'primary-strong','selection-text':'text-primary',
                     'selection-match':'text-primary','border':'primary'}.items():
        parser['colors'][key]=c[role][1:]+('f2' if key=='background' else 'ff')
    import io
    out=io.StringIO();parser.write(out);return out.getvalue()


def bundle(name):
    if name not in palettes():raise ValueError('Tema visual desconhecido')
    result={key+'.css':css(key,name) for key in COMPONENTS}
    result.update({'niri.kdl':niri_colors(name),'alacritty.toml':alacritty_colors(name),'fuzzel.ini':fuzzel_config(name)})
    return result


def validate_bundle(files):
    tomllib.loads(files['alacritty.toml'])
    # Separate GTK major versions. Parsing only; no surfaces or services started.
    with tempfile.TemporaryDirectory(prefix='rice-theme-check-') as temporary:
        base=Path(temporary)
        for name,data in files.items():(base/name).write_text(data)
        for major,names in [('3.0',['ui.css','osd.css','gtklock.css']),('4.0',['swaync.css'])]:
            code="import gi,sys;gi.require_version('Gtk',sys.argv[1]);from gi.repository import Gtk;errors=[]\nfor file in sys.argv[2:]:\n p=Gtk.CssProvider();p.connect('parsing-error',lambda _,section,error:errors.append(str(error)));p.load_from_path(file)\nprint('\\n'.join(errors));sys.exit(bool(errors))"
            subprocess.run(['/usr/bin/python3','-B','-c',code,major,*[str(base/name) for name in names]],check=True,timeout=10)
        subprocess.run(['niri','validate','-c',str(base/'niri.kdl')],check=True,timeout=5,stdout=subprocess.DEVNULL)


def _action(bus,name,path,interface,method,args=None):
    from gi.repository import Gio,GLib
    try:
        return bus.call_sync(name,path,interface,method,args,None,Gio.DBusCallFlags.NO_AUTO_START,2000,None)
    except GLib.Error as error:
        if Gio.DBusError.get_remote_error(error) in ['org.freedesktop.DBus.Error.ServiceUnknown','org.freedesktop.DBus.Error.NameHasNoOwner']:return None
        raise


def refresh_clients():
    from gi.repository import Gio,GLib
    bus=Gio.bus_get_sync(Gio.BusType.SESSION,None)
    _action(bus,'org.niri.Rice','/org/niri/Rice','org.gtk.Actions','Activate',GLib.Variant('(sava{sv})',('reload-theme',[],{})))
    _action(bus,'org.niri.MochaOSD','/org/niri/MochaOSD','org.niri.MochaOSD','ReloadTheme')
    # First migration needs one SwayNC restart only if no history would be lost.
    pid=int(subprocess.check_output(['systemctl','--user','show','niri-rice-notifications.service','-p','MainPID','--value'],text=True))
    if pid:
        args=(Path('/proc')/str(pid)/'cmdline').read_bytes().split(b'\0')
        if str(GENERATED/'swaync.css').encode() not in args:
            count=int(subprocess.check_output(['swaync-client','--skip-wait','--count'],text=True))
            if count:raise RuntimeError('SwayNC mantém histórico existente: recarregue o serviço após dispensar as notificações, ou no próximo login.')
            subprocess.run(['systemctl','--user','restart','niri-rice-notifications.service'],check=True,timeout=10)
        else:subprocess.run(['swaync-client','--skip-wait','--reload-css'],check=True,timeout=5)


def apply(name, live=True):
    if live and 'niri' not in os.environ.get('XDG_CURRENT_DESKTOP','').split(':'):raise RuntimeError('Tema visual exclusivo da sessão Niri')
    files=bundle(name);validate_bundle(files)
    STATE.mkdir(parents=True,exist_ok=True)
    GENERATED.mkdir(parents=True,exist_ok=True,mode=0o700)
    with (STATE/'visual-theme.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        paths=[GENERATED/key for key in files]+[PREFERENCE]
        before={path:path.read_bytes() if path.exists() else None for path in paths}
        bar_attempted=False
        try:
            for key,data in files.items():
                path=GENERATED/key
                if not path.exists() or path.read_text()!=data:atomic_text(path,data)
            atomic_text(PREFERENCE,json.dumps({'theme':name},indent=2)+'\n')
            if live:
                refresh_clients()
                with update_lock():
                    bar_attempted=True
                    restart('visual-theme-'+name)
        except Exception as failure:
            for path,data in before.items():
                if data is None:path.unlink(missing_ok=True)
                else:atomic_text(path,data.decode())
            if live:
                errors=[]
                try:refresh_clients()
                except Exception as error:errors.append(str(error))
                if bar_attempted:
                    try:
                        with update_lock():restart('visual-theme-rollback')
                    except Exception as error:errors.append(str(error))
                if errors:raise RuntimeError('Arquivos anteriores restaurados; falha ao recarregar componentes: '+'; '.join(errors)) from failure
            raise
    return name
