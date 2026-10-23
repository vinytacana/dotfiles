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
        if selected == 'dynamic-island-lite':
            top['mpris#track'].update({'title-len':16, 'artist-len':10, 'dynamic-len':32})
        css += '\n'+(PRESETS/'common.css').read_text()+'\n'+(PRESETS/(selected+'.css')).read_text()
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
