"""Preset rendering shared by the session, selector and validation (no daemon).

MPRIS uses Waybar's 1s refresh guard: interval=0 caused a metadata feedback
storm with multiple native modules and playerctld on the installed 0.15.0.
"""
import json
from rice_common import ROOT, STATE, read_json

PRESETS = ROOT/'waybar-presets'
PREFERENCE = STATE/'waybar-preset.json'


def profiles():
    return json.loads((PRESETS/'presets.json').read_text())


def current():
    selected = read_json(PREFERENCE, {'preset': 'mocha-pill'})['preset']
    if selected not in profiles():
        raise ValueError('Preset desconhecido: '+str(selected)+'. Use waybar-preset set mocha-pill.')
    return selected


def render(selected=None):
    selected = selected or current()
    choices = profiles()
    if selected not in choices:
        raise ValueError('Preset desconhecido: '+selected)
    bars = json.loads((ROOT/'waybar.jsonc').read_text())
    css = (ROOT/'waybar.css').read_text()
    top = next(bar for bar in bars if bar['name'] == 'top')
    if selected == 'original':
        top.clear(); top.update(json.loads((PRESETS/'original-top.json').read_text()))
    else:
        settings = choices[selected]
        top.update({'height': settings['height'], 'margin-top': settings['top'],
                    'margin-left': settings['margin'], 'margin-right': settings['margin'],
                    'fixed-center': True, 'expand-left': False, 'expand-right': False})
        top['mpris#track']['max-length'] = settings['track_chars']
        # Same character width on both ends keeps transport controls stationary.
        top['mpris#track']['min-length'] = settings['track_chars']
        css += '\n'+(PRESETS/'common.css').read_text()+'\n'+(PRESETS/(selected+'.css')).read_text()
    # Upgrade only entry points in the archived preset; keep its layout intact.
    if selected == 'original':
        top['modules-right'] = [name.replace('custom/settings', 'custom/control') for name in top['modules-right']]
        top.pop('custom/settings', None)
        baseline = json.loads((ROOT/'waybar.jsonc').read_text())[0]
        top['custom/control'] = baseline['custom/control']
        for name in ['network','bluetooth','battery']:
            top[name]['on-click'] = baseline[name]['on-click']
    uri = json.dumps((ROOT/'icons/control-center.svg').as_uri())
    css += f"\nwindow#waybar.top #custom-control {{ background-image: url({uri}); background-size: 20px 20px; background-repeat: no-repeat; background-position: center; min-width: 22px; }}\n"
    css += '#custom-control.open, window#waybar.top #custom-control.open { background-color: #45475a; box-shadow: inset 0 -2px #cba6f7; }\n'
    return bars, css


def validate(selected):
    import gi
    gi.require_version('Gtk', '3.0')
    from gi.repository import Gtk
    bars, css = render(selected)
    assert [bar['name'] for bar in bars] == ['top','dock']
    assert bars[0]['modules-center'] == ['clock']
    assert bars[0]['clock']['on-click'].endswith('settings-hub calendar')
    errors = []
    provider = Gtk.CssProvider()
    provider.connect('parsing-error',lambda _, section, error:errors.append(str(error)))
    provider.load_from_data(css.encode())
    if errors:
        raise ValueError(selected+': '+'; '.join(errors))


def validate_all():
    for identity in profiles():validate(identity)
