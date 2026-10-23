"""On-demand power panel. Only the explicit confirmation button dispatches power actions."""
import os

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
gi.require_version('GtkLayerShell', '0.1')
from gi.repository import Gdk, Gtk, GtkLayerShell
from rice_common import ROOT, run
from rice_widgets import Popup

# Fixed argv lists: no shell, sudo, session killing or user-supplied commands.
ACTIONS = (
    ('lock', 'Lock', 'system-lock-screen-symbolic'),
    ('logout', 'Logout', 'system-log-out-symbolic'),
    ('shutdown', 'Shutdown', 'system-shutdown-symbolic'),
    ('suspend', 'Suspend', 'weather-clear-night-symbolic'),
    ('reboot', 'Reboot', 'system-reboot-symbolic'),
)
CONFIRMATIONS = {
    'logout': ('Encerrar a sessão do Niri?', 'Salve seu trabalho antes de sair.', 'Encerrar sessão'),
    'shutdown': ('Desligar o computador?', 'Salve seu trabalho antes de desligar.', 'Desligar'),
    'suspend': ('Suspender o computador?', 'Sua sessão será bloqueada antes de suspender.', 'Suspender'),
    'reboot': ('Reiniciar o computador?', 'Salve seu trabalho antes de reiniciar.', 'Reiniciar'),
}


def power_command(action):
    commands = {
        'lock': [str(ROOT/'scripts/lock')],
        # The in-panel confirmation replaces Niri's additional quit prompt.
        'logout': ['niri', 'msg', 'action', 'quit', '--skip-confirmation'],
        'shutdown': ['systemctl', 'poweroff'],
        'suspend': ['systemctl', 'suspend'],
        'reboot': ['systemctl', 'reboot'],
    }
    return commands[action]


class PowerMenu(Popup):
    def __init__(self, app, executor=run):
        super().__init__(app, 'Menu de energia', 836)
        self.executor = executor
        self.selected = 0
        self.pending_action = None
        self.dispatched = False
        self.set_name('rice-power-overlay')
        GtkLayerShell.set_namespace(self, 'niri-power')
        # Ignora a área reservada da Waybar para centralizar na tela inteira.
        GtkLayerShell.set_exclusive_zone(self, -1)
        self.panel.get_style_context().add_class('power-menu-card')
        self.panel.set_spacing(0)
        self.stack = Gtk.Stack()
        self.stack.set_homogeneous(False)
        self.stack.set_transition_type(Gtk.StackTransitionType.NONE)
        self.panel.pack_start(self.stack, False, False, 0)
        self.items = []
        row = Gtk.Box(spacing=24, homogeneous=True)
        row.set_halign(Gtk.Align.CENTER)
        for index, (action, title, icon) in enumerate(ACTIONS):
            item = Gtk.Button()
            item.set_size_request(148, 132)
            item.set_tooltip_text({'lock': 'Bloquear a sessão', 'logout': 'Encerrar a sessão…',
                                   'shutdown': 'Desligar…', 'suspend': 'Suspender…',
                                   'reboot': 'Reiniciar…'}[action])
            item.get_accessible().set_name(title)
            item.get_style_context().add_class('power-item')
            content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
            content.set_halign(Gtk.Align.CENTER)
            content.set_valign(Gtk.Align.CENTER)
            image = Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.DIALOG)
            image.set_pixel_size(38)
            content.pack_start(image, False, False, 0)
            content.pack_start(Gtk.Label(label=title), False, False, 0)
            item.add(content)
            item.connect('clicked', lambda _, a=action: self.choose(a))
            item.connect('enter-notify-event', lambda _, event, i=index: self.hover(i))
            item.connect('focus-in-event', lambda _, event, i=index: self.select(i, focus=False))
            row.pack_start(item, False, False, 0)
            self.items.append(item)
        self.stack.add_named(row, 'actions')
        self.confirm_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        self.confirm_card.set_halign(Gtk.Align.CENTER)
        self.confirm_card.set_size_request(460, -1)
        self.confirm_card.get_style_context().add_class('power-confirm-card')
        self.confirm_title = Gtk.Label()
        self.confirm_title.get_style_context().add_class('power-confirm-title')
        self.confirm_card.pack_start(self.confirm_title, False, False, 0)
        self.confirm_message = Gtk.Label()
        self.confirm_message.set_line_wrap(True)
        self.confirm_message.set_max_width_chars(46)
        self.confirm_message.set_justify(Gtk.Justification.CENTER)
        self.confirm_message.get_style_context().add_class('muted')
        self.confirm_card.pack_start(self.confirm_message, False, False, 0)
        self.error = Gtk.Label()
        self.error.set_line_wrap(True)
        self.error.get_style_context().add_class('power-error')
        self.confirm_card.pack_start(self.error, False, False, 0)
        buttons = Gtk.Box(spacing=12, homogeneous=True)
        self.cancel_button = Gtk.Button(label='Cancelar')
        self.cancel_button.connect('clicked', lambda _: self.cancel())
        self.confirm_button = Gtk.Button()
        self.confirm_button.get_style_context().add_class('power-confirm-button')
        self.confirm_button.connect('clicked', lambda _: self.confirm())
        buttons.pack_start(self.cancel_button, True, True, 0)
        buttons.pack_start(self.confirm_button, True, True, 0)
        self.confirm_card.pack_start(buttons, False, False, 0)
        self.stack.add_named(self.confirm_card, 'confirm')
        self.stack.set_visible_child_name('actions')
        self.connect('map', lambda _: self.select(0))
        self.select(0, focus=False)

    def select(self, index, focus=True):
        self.selected = index % len(self.items)
        for number, item in enumerate(self.items):
            context = item.get_style_context()
            if number == self.selected:
                context.add_class('selected')
            else:
                context.remove_class('selected')
        if focus:
            self.items[self.selected].grab_focus()
        return False

    def hover(self, index):
        if self.pending_action is None:
            self.select(index)
        return False

    def choose(self, action):
        if self.dispatched or not self.alive or self.pending_action is not None:
            return
        if action == 'lock':
            self.dispatch(action)
            return
        title, message, confirm = CONFIRMATIONS[action]
        self.pending_action = action
        self.confirm_title.set_text(title)
        self.confirm_message.set_text(message)
        self.confirm_button.set_label(confirm)
        context = self.confirm_button.get_style_context()
        if action == 'suspend':
            context.remove_class('destructive')
        else:
            context.add_class('destructive')
        self.error.set_text('')
        self.stack.set_visible_child_name('confirm')
        # Enter repetido sobre o item nunca confirma uma ação de energia.
        self.cancel_button.grab_focus()

    def cancel(self):
        self.pending_action = None
        self.error.set_text('')
        self.stack.set_visible_child_name('actions')
        self.select(self.selected)

    def confirm(self):
        if self.pending_action is not None and not self.dispatched:
            self.dispatch(self.pending_action)

    def dispatch(self, action):
        if 'niri' not in os.environ.get('XDG_CURRENT_DESKTOP', '').split(':'):
            self.error.set_text('Este menu está disponível apenas na sessão Niri.')
            return
        try:
            self.executor(power_command(action))
        except OSError as error:
            self.error.set_text('Não foi possível executar a ação: '+str(error))
            return
        self.dispatched = True
        self.destroy()

    def escape(self, _, event):
        if event.keyval == Gdk.KEY_Escape:
            if self.pending_action is not None:
                self.cancel()
            else:
                self.destroy()
            return True
        backwards = event.keyval in (Gdk.KEY_Left, Gdk.KEY_ISO_Left_Tab) or bool(event.state & Gdk.ModifierType.SHIFT_MASK)
        if event.keyval in (Gdk.KEY_Left, Gdk.KEY_Right, Gdk.KEY_Tab, Gdk.KEY_ISO_Left_Tab):
            if self.pending_action is None:
                self.select(self.selected + (-1 if backwards else 1))
            else:
                target = self.confirm_button if self.get_focus() == self.cancel_button else self.cancel_button
                target.grab_focus()
            return True
        if event.keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter, Gdk.KEY_space):
            if self.pending_action is None:
                self.choose(ACTIONS[self.selected][0])
            elif self.get_focus() == self.confirm_button:
                self.confirm()
            else:
                self.cancel()
            return True
        return False
