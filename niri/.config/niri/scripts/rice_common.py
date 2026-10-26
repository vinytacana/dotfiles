"""Shared desktop launching, favorites and runtime settings for Niri Rice."""
import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import time
import gi

gi.require_version('Gio', '2.0')
from gi.repository import Gio, GLib

ROOT = Path(__file__).resolve().parent.parent
STATE = Path(os.environ.get('XDG_STATE_HOME', Path.home() / '.local/state')) / 'niri-rice'
ALIASES = {'terminal': 'Alacritty.desktop', 'browser': 'org.mozilla.firefox.desktop',
           'code': 'com.microsoft.VSCode.desktop', 'files': 'org.gnome.Nautilus.desktop',
           'settings': 'niri-settings.desktop'}


def read_json(path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text())


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name + '.', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def favorites():
    result = read_json(STATE / 'favorites.json', read_json(ROOT / 'dock-defaults.json', []))
    if not isinstance(result, list) or any(not isinstance(x, str) for x in result):
        raise ValueError('favorites.json deve ser uma lista de arquivos .desktop')
    return list(dict.fromkeys(result))


def save_favorites(items):
    items = list(dict.fromkeys(items))
    if len(items) > 24:
        raise ValueError('A dock suporta até 24 favoritos nesta tela.')
    if any(desktop(item) is None for item in items):
        raise ValueError('Um aplicativo não está mais instalado. Atualize a lista.')
    write_json(STATE / 'favorites.json', items)


def appearance():
    return {'style': 'dark', 'opacity': 0.94, **read_json(STATE / 'appearance.json', {})}


def desktop(identity):
    try:
        return Gio.DesktopAppInfo.new(ALIASES.get(identity, identity))
    except (TypeError, GLib.Error):
        return None


def windows():
    # Failure is not equivalent to "app closed": never launch on a failed IPC read.
    result = subprocess.run(['niri', 'msg', '-j', 'windows'], capture_output=True, text=True, timeout=3, check=True)
    return json.loads(result.stdout)


def matches(identity, items):
    identity = ALIASES.get(identity, identity)
    app = desktop(identity)
    names = {identity.removesuffix('.desktop').casefold()}
    if app and app.get_startup_wm_class():
        names.add(app.get_startup_wm_class().casefold())
    known = {'niri-settings.desktop': ['org.niri.Rice'],
             'niri-gnome-settings.desktop': ['org.gnome.Settings']}
    names.update(x.casefold() for x in known.get(identity, []))
    names.update(x.casefold() for x in read_json(STATE / 'app-ids.json', {}).get(identity, []))
    return [w for w in items if (w.get('app_id') or '').casefold() in names]


def focus(identity):
    found = matches(identity, windows())
    if not found:
        return False
    def key(w):
        stamp = w.get('focus_timestamp') or {}
        return (stamp.get('secs', 0), stamp.get('nanos', 0), w['id'])
    chosen = max(found, key=key)
    subprocess.run(['niri', 'msg', 'action', 'focus-window', '--id', str(chosen['id'])], check=True, timeout=3)
    return True


def launch(identity, action=None):
    identity = ALIASES.get(identity, identity)
    app = desktop(identity)
    if not app:
        raise ValueError(f'Aplicativo não instalado: {identity}')
    context = Gio.AppLaunchContext()
    if identity == 'blueman-manager.desktop':
        # GTK3-only override. It never enters the session or GTK4 environment.
        context.setenv('GTK_THEME', 'Adwaita:dark' if appearance()['style'] == 'dark' else 'Adwaita')
    if action:
        if action not in app.list_actions():
            raise ValueError('Ação não declarada pelo aplicativo')
        app.launch_action(action, context)
    elif identity == 'Alacritty.desktop':
        command = 'alacritty --config-file ' + shlex.quote(str(Path.home() / '.config/alacritty/niri.toml'))
        Gio.AppInfo.create_from_commandline(command, 'Alacritty', Gio.AppInfoCreateFlags.NONE).launch([], context)
    else:
        app.launch([], context)


def reload_bar():
    from rice_bar import reload_bar as refresh
    refresh()


def run(command):
    # Inherit stderr so failures remain observable from Waybar's journal.
    return subprocess.Popen(command, start_new_session=True)


def icon_file(app):
    gi.require_version('Gtk', '3.0')
    from gi.repository import Gtk, Gdk
    theme = Gtk.IconTheme.get_default()
    icon = app.get_icon() if app else Gio.ThemedIcon.new('application-x-executable')
    info = theme.lookup_by_gicon(icon, 48, Gtk.IconLookupFlags.FORCE_SIZE)
    if not info:
        info = theme.lookup_icon('application-x-executable', 48, Gtk.IconLookupFlags.FORCE_SIZE)
    if info and info.is_symbolic():
        color=Gdk.RGBA()
        color.parse('#cdd6f4' if appearance()['style']=='dark' else '#4c4f69')
        pixbuf,_=info.load_symbolic(color,None,None,None)
        cache=Path(os.environ['XDG_RUNTIME_DIR'])/'niri-rice/icons'
        cache.mkdir(parents=True,exist_ok=True)
        import hashlib
        path=cache/(hashlib.sha256(icon.to_string().encode()).hexdigest()[:16]+'.png')
        pixbuf.savev(str(path),'png',[],[])
        return str(path)
    return info.get_filename() if info else None


def start_desktop(identity, action=None):
    """Separate app lifetime from Waybar and from this short-lived launcher."""
    command = ['systemd-run', '--user', '--quiet', '--collect',
               '--property=ExitType=cgroup', '--property=PartOf=graphical-session.target',
               '--', str(ROOT / 'scripts/dock-app'), identity, 'launch']
    if action:
        command.append(action)
    subprocess.run(command, check=True, timeout=5)


def open_or_focus(identity):
    """Focus the most recently used matching window, or activate its desktop file."""
    if not focus(identity):
        start_desktop(identity)


def desktop_for_window(window):
    """Resolve actual Niri app IDs through desktop metadata without guessing commands."""
    identity=window.get('app_id') or ''
    for candidate in [identity+'.desktop',identity]:
        app=desktop(candidate)
        if app:return app
    for app in Gio.AppInfo.get_all():
        if isinstance(app,Gio.DesktopAppInfo) and (app.get_startup_wm_class() or '').casefold()==identity.casefold():return app
    return None
