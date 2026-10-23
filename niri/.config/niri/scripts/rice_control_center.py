"""On-demand quick controls: one card, contextual pages and scoped event listeners."""
import os
import subprocess

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('GtkLayerShell', '0.1')
from gi.repository import Gtk, Gdk, Gio, GLib, GtkLayerShell
from rice_widgets import Popup, button, async_update
from rice_common import ROOT, run
import rice_controls as controls

PROFILE_NAMES = {'balanced': 'Equilibrado', 'power-saver': 'Economia', 'performance': 'Desempenho'}
PAGES = {'main': 'Central de Controle', 'wifi': 'Wi-Fi', 'bluetooth': 'Bluetooth',
         'audio': 'Dispositivos de áudio', 'battery': 'Bateria e energia'}


def text(value='', style=None):
    widget = Gtk.Label(label=value, xalign=0)
    widget.set_single_line_mode(True)
    widget.set_ellipsize(3)
    if style:
        widget.get_style_context().add_class(style)
    return widget


def icon(name, size=18):
    widget = Gtk.Image.new_from_icon_name(name, Gtk.IconSize.BUTTON)
    widget.set_pixel_size(size)
    return widget


def icon_button(name, tooltip, callback):
    widget = Gtk.Button()
    image = icon(name); image.show(); widget.add(image)
    widget.set_tooltip_text(tooltip)
    widget.get_accessible().set_name(tooltip)
    widget.connect('clicked', lambda *_: callback())
    widget.get_style_context().add_class('cc-icon-button')
    return widget


class ControlCenter(Popup):
    def __init__(self, app, page='main'):
        super().__init__(app, 'Central de Controle', 392, True)
        self.values = {}; self.loading = True; self.pending = {}
        self.reading = False; self.read_again = False; self.operating = False
        self.sources = set(); self.subscriptions = []; self.audio_process = None
        self.detail_serial = 0
        self.set_name('control-overlay')
        GtkLayerShell.set_namespace(self, 'niri-control-center')
        GtkLayerShell.set_exclusive_zone(self, -1)
        from waybar_presets import current, profiles
        preset = profiles()[current()]
        monitor = GtkLayerShell.get_monitor(self) or Gdk.Display.get_default().get_monitor(0)
        bounds = monitor.get_geometry()
        top = preset.get('top', 6) + preset.get('height', 38) + 10
        self.panel.set_margin_top(top)
        self.panel.set_margin_start(12); self.panel.set_margin_end(preset.get('margin', 12))
        self.panel.set_margin_bottom(12)
        self.panel.set_size_request(min(392, bounds.width - 24), -1)
        self.panel.set_spacing(12)
        self.panel.get_style_context().add_class('control-center-card')
        heading = Gtk.Box(spacing=8)
        self.back = icon_button('go-previous-symbolic', 'Voltar · Esc', lambda: self.show_page('main'))
        self.back.set_no_show_all(True)
        heading.pack_start(self.back, False, False, 0)
        self.title = text('', 'cc-title'); heading.pack_start(self.title, True, True, 0)
        heading.pack_end(icon_button('view-refresh-symbolic', 'Atualizar estado', self.refresh), False, False, 0)
        self.panel.pack_start(heading, False, False, 0)
        self.scroll = scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.content_limit = max(100, bounds.height - top - 124)
        scroll.set_max_content_height(self.content_limit)
        scroll.set_propagate_natural_height(True)
        scroll.connect('size-allocate', lambda *_: self.queue_fit())
        self.stack = Gtk.Stack(); self.stack.set_homogeneous(False)
        self.stack.set_transition_type(Gtk.StackTransitionType.NONE)
        self.stack.set_transition_duration(120)
        scroll.add(self.stack); self.panel.pack_start(scroll, True, True, 0)
        self.main = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.stack.add_named(self.main, 'main')
        connectivity = Gtk.Box(spacing=10, homogeneous=True)
        self.tiles = {}
        for key, title, symbol in [('wifi', 'Wi-Fi', 'network-wireless-symbolic'), ('bluetooth', 'Bluetooth', 'bluetooth-symbolic')]:
            card, tile = self.connection_tile(key, title, symbol)
            self.tiles[key] = tile; connectivity.pack_start(card, True, True, 0)
        self.main.pack_start(connectivity, False, False, 0)
        quick = Gtk.Box(spacing=10, homogeneous=True)
        self.dnd, self.dnd_status = self.quick_tile('notifications-disabled-symbolic', 'Não perturbe', self.toggle_dnd)
        self.profile, self.profile_status = self.quick_tile('power-profile-balanced-symbolic', 'Perfil energético', lambda: self.show_page('battery'))
        quick.pack_start(self.dnd, True, True, 0); quick.pack_start(self.profile, True, True, 0)
        self.main.pack_start(quick, False, False, 0)
        audio = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=7)
        self.sliders = {}; self.percentages = {}; self.mutes = {}
        self.volume_row = self.slider_row('volume', 'Volume', 'audio-volume-high-symbolic', self.mute_output)
        audio.pack_start(self.volume_row, False, False, 0)
        self.output_name = text('Consultando saída…', 'cc-secondary')
        self.output_name.set_margin_start(38)
        audio.pack_start(self.output_name, False, False, 0)
        microw = Gtk.Box(spacing=8)
        self.mic = icon_button('microphone-sensitivity-muted-symbolic', 'Microfone', self.mute_mic)
        self.mutes['mic'] = self.mic
        microw.pack_start(self.mic, False, False, 0)
        self.mic_status = text('Microfone · consultando', 'cc-secondary')
        microw.pack_start(self.mic_status, True, True, 0)
        self.audio_button = icon_button('go-next-symbolic', 'Dispositivos e volume de entrada', lambda: self.show_page('audio'))
        microw.pack_end(self.audio_button, False, False, 0)
        audio.pack_start(microw, False, False, 0)
        self.main.pack_start(audio, False, False, 0)
        self.main.pack_start(Gtk.Separator(), False, False, 0)
        self.main.pack_start(self.slider_row('brightness', 'Brilho', 'display-brightness-symbolic'), False, False, 0)
        self.battery_button = Gtk.Button(); self.battery_button.get_style_context().add_class('cc-battery')
        battery = Gtk.Box(spacing=10); battery.pack_start(icon('battery-good-symbolic', 22), False, False, 0)
        battery_text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        self.battery_title = text('Bateria', 'cc-label'); self.battery_status = text('Consultando…', 'cc-secondary')
        battery_text.pack_start(self.battery_title, False, False, 0); battery_text.pack_start(self.battery_status, False, False, 0)
        battery.pack_start(battery_text, True, True, 0); battery.pack_end(icon('go-next-symbolic', 14), False, False, 0)
        self.battery_button.add(battery); self.battery_button.connect('clicked', lambda *_: self.show_page('battery'))
        self.main.pack_start(self.battery_button, False, False, 0)
        self.build_details()
        self.message = Gtk.Label(xalign=0); self.message.set_line_wrap(True)
        self.message.get_style_context().add_class('cc-error'); self.message.set_no_show_all(True)
        self.panel.pack_start(self.message, False, False, 0)
        footer = Gtk.Box(spacing=8)
        footer.pack_start(button('Configurações', lambda: self.open_command([str(ROOT/'scripts/settings-hub'), 'settings']), 'preferences-system-symbolic'), True, True, 0)
        footer.pack_end(icon_button('preferences-system-notifications-symbolic', 'Histórico de notificações', lambda: self.open_command([str(ROOT/'scripts/notifications'), 'open'])), False, False, 0)
        footer.get_style_context().add_class('cc-footer'); self.panel.pack_start(footer, False, False, 0)
        self.connect('destroy', self.cleanup)
        # Gtk.Stack can select only visible children, including a first opening
        # directly from the battery/network module rather than from the main page.
        self.stack.show_all()
        self.show_page(page, refresh=False)
        if hasattr(app, 'control_visible'): app.control_visible.set_state(GLib.Variant('b', True))
        self.connect('map', lambda *_: self.back.grab_focus() if self.page != 'main' else self.tiles['wifi']['button'].grab_focus())
        self.watch_events()
        self.refresh()

    def connection_tile(self, key, title, symbol):
        card = Gtk.Box(spacing=0); card.get_style_context().add_class('cc-connection')
        toggle = Gtk.Button(); toggle.set_sensitive(False)
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        content.pack_start(icon(symbol, 22), False, False, 0)
        content.pack_start(text(title, 'cc-label'), False, False, 0)
        status = text('Consultando…', 'cc-secondary'); status.set_max_width_chars(16)
        content.pack_start(status, False, False, 0); toggle.add(content)
        toggle.connect('clicked', lambda *_: self.toggle(key))
        toggle.get_accessible().set_name(title + ' · ligar ou desligar')
        more = icon_button('go-next-symbolic', 'Abrir ' + title, lambda: self.show_page(key))
        card.pack_start(toggle, True, True, 0); card.pack_end(more, False, False, 0)
        return card, {'button': toggle, 'status': status, 'card': card}

    def quick_tile(self, symbol, title, callback):
        widget = Gtk.Button(); widget.get_style_context().add_class('cc-quick')
        box = Gtk.Box(spacing=8); box.pack_start(icon(symbol), False, False, 0)
        titles = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        titles.pack_start(text(title, 'cc-label'), False, False, 0)
        status = text('Consultando…', 'cc-secondary'); titles.pack_start(status, False, False, 0)
        box.pack_start(titles, True, True, 0); widget.add(box)
        widget.connect('clicked', lambda *_: callback())
        return widget, status

    def slider_row(self, key, title, symbol, mute=None):
        section = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        heading = Gtk.Box(spacing=8)
        heading.pack_start(text(title, 'cc-label'), True, True, 0)
        percentage = text('—', 'cc-secondary'); self.percentages[key] = percentage
        heading.pack_end(percentage, False, False, 0); section.pack_start(heading, False, False, 0)
        row = Gtk.Box(spacing=8)
        image = icon_button(symbol, 'Silenciar ou reativar ' + title.lower(), mute) if mute else icon(symbol)
        if mute: self.mutes[key] = image
        else: image.set_size_request(30, -1)
        row.pack_start(image, False, False, 0)
        slider = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 1 if key == 'brightness' else 0, 100, 1)
        slider.set_draw_value(False); slider.set_sensitive(False)
        slider.get_accessible().set_name(title)
        slider.connect('value-changed', lambda w: self.schedule_value(key, round(w.get_value())))
        self.sliders[key] = slider; row.pack_start(slider, True, True, 0)
        section.pack_start(row, False, False, 0)
        return section

    def build_details(self):
        self.details = {}
        for name in ['wifi', 'bluetooth']:
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
            caption = Gtk.Label(xalign=0); caption.set_line_wrap(True)
            caption.get_style_context().add_class('cc-secondary'); box.pack_start(caption, False, False, 0)
            items = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            box.pack_start(items, False, False, 0)
            command = 'nm-connection-editor' if name == 'wifi' else 'blueman-manager'
            box.pack_start(button('Conexões avançadas' if name == 'wifi' else 'Gerenciar no Blueman', lambda c=command: self.open_command([str(ROOT/'scripts/gtk3-app'), c]), 'preferences-system-symbolic'), False, False, 0)
            self.details[name] = (caption, items)
            self.stack.add_named(box, name)
        audio = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.combos = {}
        for key, title in [('outputs', 'Saída de áudio'), ('inputs', 'Entrada de áudio')]:
            audio.pack_start(text(title, 'cc-label'), False, False, 0)
            combo = Gtk.ComboBoxText(); combo.set_sensitive(False)
            for cell in combo.get_cells(): cell.set_property('ellipsize', 3); cell.set_property('width-chars', 24)
            combo.connect('changed', lambda w, k=key: self.change_device(k, w.get_active_id()))
            self.combos[key] = combo; audio.pack_start(combo, False, False, 0)
        audio.pack_start(self.slider_row('mic', 'Volume de entrada', 'audio-input-microphone-symbolic'), False, False, 0)
        audio.pack_start(button('Áudio avançado', lambda: self.open_command(['pavucontrol']), 'preferences-system-symbolic'), False, False, 0)
        self.stack.add_named(audio, 'audio')
        battery = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.energy_summary = Gtk.Label(xalign=0); self.energy_summary.set_line_wrap(True)
        self.energy_summary.get_style_context().add_class('cc-energy-summary')
        battery.pack_start(self.energy_summary, False, False, 0)
        battery.pack_start(text('Perfil energético', 'cc-label'), False, False, 0)
        self.profile_list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        battery.pack_start(self.profile_list, False, False, 0)
        note = Gtk.Label(label='Os perfis são fornecidos pelo serviço de energia do sistema. As políticas de suspensão permanecem nas configurações existentes.', xalign=0)
        note.set_line_wrap(True); note.get_style_context().add_class('cc-secondary')
        battery.pack_start(note, False, False, 0); self.stack.add_named(battery, 'battery')

    def show_page(self, page, refresh=True):
        if page not in PAGES: page = 'main'
        self.page = page; self.title.set_text(PAGES[page]); self.back.set_visible(page != 'main')
        self.stack.set_visible_child_name(page)
        self.detail_serial += 1
        if refresh: self.refresh()
        if page != 'main': self.back.grab_focus()
        self.queue_fit()

    def queue_fit(self):
        if not self.alive or 'fit' in self.pending: return
        def fit():
            self.pending.pop('fit', None)
            if not self.alive: return False
            width = max(1, self.scroll.get_allocated_width())
            page = self.stack.get_visible_child()
            if page and width > 1:
                # ScrolledWindow's width-independent request can underestimate
                # wrapped labels. Measure the current page at its real width.
                height = min(self.content_limit, page.get_preferred_height_for_width(width).natural_height)
                if self.scroll.get_min_content_height() != height:
                    self.scroll.set_min_content_height(height)
            return False
        self.pending['fit'] = GLib.idle_add(fit)

    def escape(self, widget, event):
        if event.keyval == Gdk.KEY_Escape and self.page != 'main':
            self.show_page('main'); self.tiles['wifi']['button'].grab_focus(); return True
        return super().escape(widget, event)

    def open_command(self, args):
        self.destroy(); run(args)

    def report(self, message=''):
        self.message.set_text(message); self.message.set_visible(bool(message))

    def perform(self, work):
        if self.operating: return
        self.operating = True; self.stack.set_sensitive(False); self.report('Aplicando…')
        def execute():
            try: work(); return ''
            except Exception as exc: return str(exc)
        def done(error):
            if not self.alive: return
            self.operating = False; self.stack.set_sensitive(True); self.report(error)
            self.refresh()
        async_update(execute, done)

    def toggle(self, key):
        value = self.values.get(key)
        if value is None: return
        args = ['nmcli', 'radio', 'wifi', 'off' if value[0] else 'on'] if key == 'wifi' else ['bluetoothctl', 'power', 'off' if value[0] else 'on']
        self.perform(lambda: controls.command(args))

    def toggle_dnd(self):
        self.perform(lambda: controls.command([str(ROOT/'scripts/notifications'), 'dnd']))

    def mute_output(self): self.perform(lambda: controls.command(['wpctl', 'set-mute', '@DEFAULT_AUDIO_SINK@', 'toggle']))
    def mute_mic(self): self.perform(lambda: controls.command(['wpctl', 'set-mute', '@DEFAULT_AUDIO_SOURCE@', 'toggle']))

    def schedule_value(self, key, value):
        self.percentages[key].set_text(str(value) + '%')
        if self.loading: return
        if key in self.pending: GLib.source_remove(self.pending.pop(key))
        def apply():
            self.pending.pop(key, None)
            if not self.alive: return False
            if key == 'brightness':
                device = self.values.get('brightness')
                if device: self.perform(lambda: controls.command(['brightnessctl', '--device', device[0], 'set', str(value) + '%']))
            else:
                target = '@DEFAULT_AUDIO_SINK@' if key == 'volume' else '@DEFAULT_AUDIO_SOURCE@'
                self.perform(lambda: controls.command(['wpctl', 'set-volume', target, str(value) + '%']))
            return False
        self.pending[key] = GLib.timeout_add(180, apply)

    def change_device(self, key, identity):
        if not self.loading and identity:
            self.perform(lambda: controls.command(['pactl', 'set-default-sink' if key == 'outputs' else 'set-default-source', identity]))

    def refresh(self):
        if not self.alive: return
        if self.reading: self.read_again = True; return
        self.reading = True
        def done(values):
            self.reading = False
            if not self.alive: return
            if isinstance(values, dict): self.display(values)
            if self.read_again:
                self.read_again = False; self.queue_refresh()
        async_update(controls.control_snapshot, done)

    @staticmethod
    def state(widget, name, active):
        style = widget.get_style_context()
        (style.add_class if active else style.remove_class)(name)

    def display(self, values):
        self.loading = True; self.values = values
        for key, tile in self.tiles.items():
            value = values.get(key); tile['button'].set_sensitive(value is not None)
            status = value[1] if value and value[0] else ('Desligado' if value else 'Indisponível')
            tile['status'].set_text(status); tile['status'].set_tooltip_text(status)
            self.state(tile['card'], 'enabled', bool(value and value[0]))
        for key in ['volume', 'mic']:
            value = values.get(key); self.sliders[key].set_sensitive(value is not None)
            self.mutes[key].set_sensitive(value is not None)
            self.percentages[key].set_text(str(value[0]) + '%' if value else 'Indisponível')
            if value: self.sliders[key].set_value(min(100, value[0]))
            muted = bool(value and value[1]); self.state(self.mutes[key], 'muted', muted)
            image = 'audio-volume-muted-symbolic' if muted else 'audio-volume-high-symbolic'
            if key == 'mic': image = 'microphone-sensitivity-muted-symbolic' if muted else 'audio-input-microphone-symbolic'
            self.mutes[key].get_child().set_from_icon_name(image, Gtk.IconSize.BUTTON)
            self.mutes[key].set_tooltip_text(('Reativar' if muted else 'Silenciar') + (' microfone' if key == 'mic' else ' saída'))
            self.mutes[key].get_accessible().set_name(('Microfone' if key == 'mic' else 'Volume') + (' silenciado' if muted else ' ativo'))
        mic = values.get('mic')
        self.mic_status.set_text('Microfone ' + ('silenciado' if mic[1] else 'ativo') if mic else 'Microfone indisponível')
        self.state(self.mic_status, 'muted', bool(mic and mic[1]))
        for key, combo in self.combos.items():
            combo.remove_all(); value = values.get(key); combo.set_sensitive(bool(value and value[0]))
            if value:
                for identity, name in value[0]: combo.append(identity, name)
                combo.set_active_id(value[1])
        output = values.get('outputs')
        name = dict(output[0]).get(output[1], 'Saída de áudio') if output else 'Saída indisponível'
        self.output_name.set_text(name); self.output_name.set_tooltip_text(name)
        bright = values.get('brightness'); self.sliders['brightness'].set_sensitive(bright is not None)
        self.percentages['brightness'].set_text(str(bright[1]) + '%' if bright else 'Indisponível')
        if bright: self.sliders['brightness'].set_value(bright[1])
        self.sliders['brightness'].set_tooltip_text('Tela interna' if bright else 'Nenhuma tela interna com controle de brilho disponível')
        notifications = values.get('notifications')
        available = notifications is not None and notifications.get('alt') != 'unavailable'
        self.dnd.set_sensitive(available)
        paused = bool(available and notifications.get('dnd'))
        self.dnd_status.set_text(('Ativado' if paused else 'Desativado') if available else 'Indisponível')
        self.state(self.dnd, 'enabled', paused)
        proxy = values.get('profiles'); active = None
        for child in self.profile_list.get_children(): child.destroy()
        if proxy:
            active = proxy.get_cached_property('ActiveProfile').unpack()
            for item in proxy.get_cached_property('Profiles').unpack():
                identity = item['Profile']; caption = PROFILE_NAMES.get(identity, identity)
                choice = button(caption + ('  ✓' if identity == active else ''), lambda p=proxy, v=identity: self.perform(lambda: controls.set_profile(p, v)))
                self.state(choice, 'enabled', identity == active)
                self.profile_list.pack_start(choice, False, False, 0)
        else: self.profile_list.pack_start(text('Perfis indisponíveis', 'cc-secondary'), False, False, 0)
        self.profile_status.set_text(PROFILE_NAMES.get(active, active) or 'Indisponível')
        battery = values.get('battery')
        self.battery_title.set_text(str(battery['percent']) + '% · ' + battery['status'] if battery else 'Sem bateria disponível')
        status = 'Alimentação externa' if battery and battery['external'] else 'Usando a bateria'
        self.battery_status.set_text(status if battery else 'Energia e perfis')
        summary = self.battery_title.get_text() + '\n' + (status if battery else '')
        self.energy_summary.set_text(summary.strip())
        self.profile_list.show_all(); self.loading = False
        if self.page in self.details: self.load_detail(self.page)
        self.queue_fit()
        self.stack.queue_draw()

    def load_detail(self, page):
        self.detail_serial += 1
        caption, box = self.details[page]; serial = self.detail_serial
        caption.set_text('Consultando redes conhecidas…' if page == 'wifi' else 'Consultando dispositivos pareados…')
        for child in box.get_children(): child.destroy()
        def read():
            try: return (controls.networks() if page == 'wifi' else controls.paired_devices()), None
            except Exception as exc: return [], str(exc)
        def show(result):
            if not self.alive or serial != self.detail_serial or self.page != page: return
            items, error = result
            caption.set_text(error or ('Redes disponíveis em cache. Redes salvas podem ser conectadas aqui; configure novas credenciais em Conexões avançadas.' if page == 'wifi' else 'Dispositivos já pareados. Novos dispositivos podem ser adicionados no Blueman.'))
            for item in items:
                if page == 'wifi':
                    title = item['ssid']; sub = ('Conectada' if item['active'] else str(item['signal']) + '% de sinal')
                    callback = lambda value=item: self.perform(lambda: controls.connect_network(value))
                    if not item['uuid']: callback = lambda: self.open_command([str(ROOT/'scripts/gtk3-app'), 'nm-connection-editor'])
                    symbol = 'network-wireless-symbolic'; active = item['active']
                else:
                    title = item['name']; sub = 'Conectado · desconectar' if item['connected'] else 'Pareado · conectar'
                    callback = lambda value=item: self.perform(lambda: controls.connect_bluetooth(value))
                    symbol = 'bluetooth-symbolic'; active = item['connected']
                row = button('', callback); content = Gtk.Box(spacing=10)
                content.pack_start(icon(symbol), False, False, 0)
                lines = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
                name = text(title, 'cc-label'); name.set_max_width_chars(30); name.set_tooltip_text(title)
                lines.pack_start(name, False, False, 0); lines.pack_start(text(sub, 'cc-secondary'), False, False, 0)
                content.pack_start(lines, True, True, 0); row.remove(row.get_child()); row.add(content)
                row.set_sensitive(not (page == 'wifi' and active))
                row.get_style_context().add_class('cc-device'); self.state(row, 'enabled', active)
                box.pack_start(row, False, False, 0)
            if not items: box.pack_start(text('Nenhuma rede disponível' if page == 'wifi' else 'Nenhum dispositivo pareado', 'cc-secondary'), False, False, 0)
            box.show_all()
            self.queue_fit()
        async_update(read, show)

    def queue_refresh(self):
        if not self.alive or 'refresh' in self.pending: return
        def apply():
            self.pending.pop('refresh', None); self.refresh(); return False
        self.pending['refresh'] = GLib.timeout_add(300, apply)

    def watch_events(self):
        def changed(_bus, _sender, _path, _interface, signal, params, *_):
            if signal == 'PropertiesChanged':
                interface, properties, _invalid = params.unpack()
                relevant = {'State', 'WirelessEnabled', 'ActiveConnections', 'Powered', 'Connected', 'ActiveProfile', 'Percentage', 'Online', 'Status', 'WarningLevel', 'Energy', 'Brightness'}
                if not relevant.intersection(properties): return
            self.queue_refresh()
        for kind, sender in [(Gio.BusType.SYSTEM, 'org.freedesktop.NetworkManager'),
                             (Gio.BusType.SYSTEM, 'org.bluez'),
                             (Gio.BusType.SYSTEM, 'org.freedesktop.UPower'),
                             (Gio.BusType.SYSTEM, 'net.hadess.PowerProfiles'),
                             (Gio.BusType.SYSTEM, 'org.freedesktop.UPower.PowerProfiles'),
                             (Gio.BusType.SESSION, 'org.erikreider.swaync')]:
            try:
                bus = Gio.bus_get_sync(kind, None)
                identity = bus.signal_subscribe(sender, None, None, None, None, Gio.DBusSignalFlags.NONE, changed)
                self.subscriptions.append((bus, identity))
            except GLib.Error: pass
        try:
            self.audio_process = subprocess.Popen(['pactl', 'subscribe'], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env={**os.environ, 'LC_ALL': 'C'})
            def audio_event(_fd, condition):
                if condition & (GLib.IOCondition.HUP | GLib.IOCondition.ERR): return False
                line = self.audio_process.stdout.readline()
                if any(kind in line for kind in [b"on sink #", b"on source #", b"on server #"]): self.queue_refresh()
                return self.alive
            self.sources.add(GLib.io_add_watch(self.audio_process.stdout, GLib.IOCondition.IN | GLib.IOCondition.HUP | GLib.IOCondition.ERR, audio_event))
        except OSError: pass

    def cleanup(self, *_):
        for identity in self.pending.values(): GLib.source_remove(identity)
        self.pending.clear()
        for identity in self.sources:
            if GLib.MainContext.default().find_source_by_id(identity): GLib.source_remove(identity)
        self.sources.clear()
        for bus, identity in self.subscriptions: bus.signal_unsubscribe(identity)
        self.subscriptions.clear()
        if self.audio_process:
            if self.audio_process.poll() is None:
                self.audio_process.terminate()
                try: self.audio_process.wait(timeout=1)
                except subprocess.TimeoutExpired: self.audio_process.kill(); self.audio_process.wait()
            self.audio_process.stdout.close(); self.audio_process = None
        if hasattr(self.app, 'control_visible'): self.app.control_visible.set_state(GLib.Variant('b', False))
