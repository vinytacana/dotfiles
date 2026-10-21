"""V4 panels built on the V3 application's singleton and shared GTK widgets."""
import json,subprocess
import gi
gi.require_version('Gtk','3.0');gi.require_version('Gdk','3.0')
from gi.repository import Gtk,Gdk,GLib
from rice_widgets import Popup,label,button,async_update,app_image
from rice_common import ROOT,desktop,start_desktop,windows,run
import rice_controls as controls

class ControlCenter(Popup):
    def __init__(self,app):
        super().__init__(app,'Central de controle',440,True)
        self.values={};self.loading=True;self.pending={}
        self.panel.get_style_context().add_class('control-center-card');self.panel.set_spacing(8)
        heading=Gtk.Box(spacing=12)
        heading.pack_start(label('Central de controle','page-title'),True,True,0)
        heading.pack_end(button('×',self.destroy),False,False,0)
        self.panel.pack_start(heading,False,False,0)
        scroll=Gtk.ScrolledWindow();scroll.set_policy(Gtk.PolicyType.NEVER,Gtk.PolicyType.AUTOMATIC)
        scroll.set_max_content_height(680);scroll.set_propagate_natural_height(True)
        self.body=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=6);scroll.add(self.body)
        self.panel.pack_start(scroll,True,True,0)
        self.wifi=button('Wi-Fi · consultando',lambda:self.toggle('wifi'),'network-wireless-symbolic')
        self.bt=button('Bluetooth · consultando',lambda:self.toggle('bluetooth'),'bluetooth-symbolic')
        for widget,cmd in [(self.wifi,'nm-connection-editor'),(self.bt,'blueman-manager')]:
            row=Gtk.Box(spacing=8);row.pack_start(widget,True,True,0)
            row.pack_end(button('Gerenciar',lambda c=cmd:run([str(ROOT/'scripts/gtk3-app'),c])),False,False,0)
            self.body.pack_start(row,False,False,0)
        self.sliders={};self.mutes={}
        for key,title,target,icon in [('volume','Saída de áudio','@DEFAULT_AUDIO_SINK@','audio-volume-high-symbolic'),('mic','Microfone','@DEFAULT_AUDIO_SOURCE@','audio-input-microphone-symbolic')]:
            row=Gtk.Box(spacing=8);row.pack_start(label(title,'section-title'),True,True,0)
            mute=button('Silenciar',lambda t=target:self.perform(lambda:controls.command(['wpctl','set-mute',t,'toggle'])),icon)
            row.pack_end(mute,False,False,0);self.mutes[key]=mute;self.body.pack_start(row,False,False,0)
            slider=Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL,0,100,1);slider.set_digits(0);slider.set_sensitive(False);mute.set_sensitive(False)
            slider.connect('value-changed',lambda w,k=key,t=target:self.schedule(k,lambda:controls.command(['wpctl','set-volume',t,f'{round(w.get_value())}%'])))
            self.sliders[key]=slider;self.body.pack_start(slider,False,False,0)
        self.output=Gtk.ComboBoxText();self.output.connect('changed',self.change_output)
        for cell in self.output.get_cells():cell.set_property('ellipsize',3);cell.set_property('width-chars',34)
        self.body.pack_start(self.output,False,False,0)
        self.body.pack_start(button('Áudio avançado',lambda:run(['pavucontrol'])),False,False,0)
        self.brightness_text=label('Brilho','section-title');self.body.pack_start(self.brightness_text,False,False,0)
        self.brightness=Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL,1,100,1);self.brightness.set_digits(0)
        self.brightness.connect('value-changed',lambda w:self.schedule('brightness',lambda:self.set_brightness(round(w.get_value()))))
        self.body.pack_start(self.brightness,False,False,0)
        self.power=label('Energia · consultando','status-card');self.body.pack_start(self.power,False,False,0)
        self.profiles=Gtk.ComboBoxText();self.profiles.connect('changed',self.change_profile)
        self.body.pack_start(self.profiles,False,False,0)
        self.dnd=button('Não perturbe',lambda:self.perform(lambda:controls.command([str(ROOT/'scripts/notifications'),'dnd'])))
        self.body.pack_start(self.dnd,False,False,0)
        row=Gtk.Box(spacing=8)
        row.pack_start(button('Notificações',lambda:self.open_command([str(ROOT/'scripts/notifications'),'open'])),True,True,0)
        row.pack_start(button('Configurações',lambda:self.open_command([str(ROOT/'scripts/settings-hub'),'settings'])),True,True,0)
        self.body.pack_start(row,False,False,0)
        row=Gtk.Box(spacing=8)
        row.pack_start(button('Bloquear',lambda:self.open_command([str(ROOT/'scripts/lock')])),True,True,0)
        row.pack_start(button('Suspender…',self.suspend),True,True,0)
        row.pack_start(button('GNOME',lambda:self.open_command([str(ROOT/'scripts/settings-window')])),True,True,0)
        self.body.pack_start(row,False,False,0)
        self.message=label('','muted');self.body.pack_start(self.message,False,False,0)
        self.body.pack_start(button('Atualizar estado',self.refresh,'view-refresh-symbolic'),False,False,0)
        children=self.body.get_children()
        for child in children:self.body.remove(child)
        for group in [children[:2],children[2:8],children[8:12]]:
            card=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=6);card.get_style_context().add_class('control-section')
            for child in group:card.pack_start(child,False,False,0)
            self.body.pack_start(card,False,False,0)
        for child in children[12:]:self.body.pack_start(child,False,False,0)
        for widget in [self.wifi,self.bt,self.output,self.brightness,self.profiles]:widget.set_sensitive(False)
        self.refresh()
    def open_command(self,args):self.destroy();run(args)
    def perform(self,work):
        def execute():
            try:work();return None
            except Exception as exc:return str(exc)
        def done(error):
            if self.alive:
                self.message.set_text(error or 'Atualizado');self.refresh()
        async_update(execute,done)
    def schedule(self,key,work):
        if self.loading:return
        if key in self.pending:GLib.source_remove(self.pending.pop(key))
        def apply():
            self.pending.pop(key,None)
            if self.alive:self.perform(work)
            return False
        self.pending[key]=GLib.timeout_add(180,apply)
    def toggle(self,key):
        state=self.values.get(key)
        if state is None:return
        args=['nmcli','radio','wifi','off' if state[0] else 'on'] if key=='wifi' else ['bluetoothctl','power','off' if state[0] else 'on']
        self.perform(lambda:controls.command(args))
    def set_brightness(self,value):
        current=controls.brightness()
        if current:controls.command(['brightnessctl','--device',current[0],'set',str(value)+'%'])
    def change_output(self,widget):
        if not self.loading and widget.get_active_id():self.perform(lambda:controls.command(['pactl','set-default-sink',widget.get_active_id()]))
    def change_profile(self,widget):
        if not self.loading and widget.get_active_id():self.perform(lambda:controls.set_profile(self.values['profiles'],widget.get_active_id()))
    def suspend(self):
        dialog=Gtk.MessageDialog(transient_for=self,modal=True,message_type=Gtk.MessageType.QUESTION,buttons=Gtk.ButtonsType.YES_NO,text='Suspender o computador agora?')
        response=dialog.run();dialog.destroy()
        if response==Gtk.ResponseType.YES:self.open_command(['systemctl','suspend'])
    def refresh(self):
        def read():
            values={}
            for key,fn in [('wifi',controls.wifi),('bluetooth',controls.bluetooth),('volume',lambda:controls.volume('@DEFAULT_AUDIO_SINK@')),('mic',lambda:controls.volume('@DEFAULT_AUDIO_SOURCE@')),('outputs',controls.outputs),('brightness',controls.brightness),('battery',controls.battery),('profiles',controls.power_proxy),('notifications',lambda:json.loads(controls.command([str(ROOT/'scripts/notifications')])) )]:
                try:values[key]=fn()
                except Exception:values[key]=None
            return values
        def show(values):
            if not self.alive or not values:return
            self.loading=True;self.values=values
            for key,widget,name in [('wifi',self.wifi,'Wi-Fi'),('bluetooth',self.bt,'Bluetooth')]:
                value=values[key];widget.set_sensitive(value is not None)
                widget.set_label(name+' · '+((value[1][:30] if key=='wifi' and value[0] else ('Ligado' if value[0] else 'Desligado')) if value else 'Indisponível'))
                widget.set_tooltip_text(value[1] if value else 'Adaptador indisponível')
            for key in ['volume','mic']:
                value=values[key];self.sliders[key].set_sensitive(value is not None);self.mutes[key].set_sensitive(value is not None)
                if value:self.sliders[key].set_value(value[0]);self.mutes[key].set_label('Reativar' if value[1] else 'Silenciar')
            self.output.remove_all();output=values['outputs'];self.output.set_sensitive(output is not None)
            if output:
                for identity,name in output[0]:self.output.append(identity,name)
                self.output.set_active_id(output[1])
            bright=values['brightness'];self.brightness.set_sensitive(bright is not None)
            self.brightness_text.set_text('Brilho · tela interna' if bright else 'Brilho indisponível · tela interna desligada ou sem suporte')
            if bright:self.brightness.set_value(bright[1])
            self.power.set_text('Energia · '+(values['battery'] or 'Indisponível'))
            self.profiles.remove_all();proxy=values['profiles'];self.profiles.set_sensitive(proxy is not None)
            if proxy:
                for item in proxy.get_cached_property('Profiles').unpack():self.profiles.append(item['Profile'],{'balanced':'Equilibrado','power-saver':'Economia','performance':'Desempenho'}.get(item['Profile'],item['Profile']))
                self.profiles.set_active_id(proxy.get_cached_property('ActiveProfile').unpack())
            else:self.profiles.append('none','Perfil energético indisponível');self.profiles.set_active(0)
            self.dnd.set_label('Não perturbe · '+('Ligado' if (values['notifications'] or {}).get('dnd') else 'Desligado'))
            self.loading=False
        async_update(read,show)

class WindowSwitcher(Popup):
    def __init__(self,app,reverse=False):
        # Snapshot before the overlay takes keyboard focus. No background polling.
        self.items=sorted(windows(),key=lambda w:((w.get('focus_timestamp') or {}).get('secs',0),(w.get('focus_timestamp') or {}).get('nanos',0)),reverse=True)
        super().__init__(app,'Alternador de janelas',760)
        from rice_common import desktop_for_window
        self.panel.pack_start(label('Janelas abertas','page-title'),False,False,0)
        self.panel.pack_start(label('Tab / setas: navegar · Enter: focar · Esc: fechar','muted'),False,False,0)
        self.list=Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        self.list.connect('row-activated',lambda _,row:self.choose(row.window_id))
        scroll=Gtk.ScrolledWindow();scroll.set_policy(Gtk.PolicyType.NEVER,Gtk.PolicyType.AUTOMATIC)
        scroll.set_min_content_height(min(480,max(90,len(self.items)*80)))
        scroll.set_max_content_height(560);scroll.set_propagate_natural_height(True);scroll.add(self.list)
        self.panel.pack_start(scroll,True,True,0)
        try:spaces={w['id']:w.get('name') or str(w['idx']) for w in json.loads(controls.command(['niri','msg','-j','workspaces']))}
        except Exception:spaces={}
        for window in self.items:
            row=Gtk.ListBoxRow();row.window_id=window['id'];row.get_style_context().add_class('search-result')
            box=Gtk.Box(spacing=14);appinfo=desktop_for_window(window)
            box.pack_start(app_image(appinfo,40) if appinfo else Gtk.Image.new_from_icon_name('application-x-executable',Gtk.IconSize.DIALOG),False,False,0)
            text=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=4)
            title=label(window.get('title') or 'Janela sem título');title.set_ellipsize(3);title.set_max_width_chars(65)
            text.pack_start(title,False,False,0)
            text.pack_start(label((appinfo.get_display_name() if appinfo else window.get('app_id','Aplicativo'))+' · workspace '+spaces.get(window.get('workspace_id'),'?'),'muted'),False,False,0)
            box.pack_start(text,True,True,0);row.add(box);self.list.add(row)
        if not self.items:self.panel.pack_start(label('Nenhuma janela aberta'),False,False,0)
        self.list.show_all()
        self.index=(len(self.items)-1 if reverse else min(1,len(self.items)-1))
        if self.items:self.select(self.index)
        self.connect('key-press-event',self.navigate)
    def select(self,index):
        if not self.items:return
        self.index=index%len(self.items)
        row=self.list.get_row_at_index(self.index);self.list.select_row(row);row.grab_focus()
    def cycle(self,delta=1):self.select(self.index+delta)
    def navigate(self,_,event):
        if event.keyval in (Gdk.KEY_Tab,Gdk.KEY_ISO_Left_Tab,Gdk.KEY_Right,Gdk.KEY_Down):
            self.cycle(-1 if event.keyval==Gdk.KEY_ISO_Left_Tab or event.state&Gdk.ModifierType.SHIFT_MASK else 1);return True
        if event.keyval in (Gdk.KEY_Left,Gdk.KEY_Up):self.cycle(-1);return True
        if event.keyval in (Gdk.KEY_Return,Gdk.KEY_KP_Enter):
            row=self.list.get_selected_row()
            if row:self.choose(row.window_id)
            return True
        return False
    def choose(self,identity):
        self.destroy()
        self.app.safe(lambda:controls.command(['niri','msg','action','focus-window','--id',str(identity)]))

class ClipboardPanel(Popup):
    def __init__(self,app):
        from rice_common import STATE
        try:self.previous=next((w['id'] for w in windows() if w.get('is_focused')),None)
        except Exception:self.previous=None
        super().__init__(app,'Histórico de cópia',720)
        self.panel.pack_start(label('Área de transferência','page-title'),False,False,0)
        self.panel.pack_start(label('Somente texto · até 40 itens / 30 min · dados voláteis\nFiltros não garantem exclusão de toda senha. Pausar também limpa o histórico.','muted'),False,False,0)
        row=Gtk.Box(spacing=8)
        paused=(STATE/'clipboard-disabled').exists()
        self.pause=button('Retomar captura' if paused else 'Pausar e limpar',lambda:self.control('resume' if (STATE/'clipboard-disabled').exists() else 'pause'))
        row.pack_start(self.pause,True,True,0);row.pack_start(button('Limpar histórico',lambda:self.control('clear')),True,True,0)
        self.panel.pack_start(row,False,False,0)
        self.search=Gtk.SearchEntry(placeholder_text='Pesquisar no histórico…');self.search.connect('search-changed',lambda *_:self.refresh())
        self.panel.pack_start(self.search,False,False,0)
        self.list=Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE);self.list.connect('row-activated',lambda _,row:self.choose(row.payload))
        scroll=Gtk.ScrolledWindow();scroll.set_policy(Gtk.PolicyType.NEVER,Gtk.PolicyType.AUTOMATIC);scroll.set_min_content_height(300);scroll.set_max_content_height(500);scroll.add(self.list)
        self.panel.pack_start(scroll,True,True,0)
        self.note=label('Enter ou clique para copiar. × exclui somente o item.','muted');self.panel.pack_start(self.note,False,False,0)
        self.search.connect('activate',lambda *_:self.choose(self.list.get_selected_row().payload) if self.list.get_selected_row() else None)
        self.refresh();self.search.grab_focus()
        self.connect('key-press-event',self.keys)
    def keys(self,_,event):
        if event.keyval in (Gdk.KEY_Down,Gdk.KEY_Up):
            rows=self.list.get_children()
            if rows:
                selected=self.list.get_selected_row();index=rows.index(selected) if selected else -1
                row=rows[(index+(1 if event.keyval==Gdk.KEY_Down else -1))%len(rows)]
                self.list.select_row(row);row.grab_focus()
            return True
        return False
    def refresh(self):
        import datetime
        from rice_clipboard import entries
        for row in self.list.get_children():self.list.remove(row)
        for digest,text,stamp in entries(self.search.get_text()):
            row=Gtk.ListBoxRow();row.payload=text;row.get_style_context().add_class('search-result')
            box=Gtk.Box(spacing=10)
            preview=label(text.splitlines()[0][:80]+'  ·  '+datetime.datetime.fromtimestamp(stamp).strftime('%H:%M'));preview.set_ellipsize(3);preview.set_max_width_chars(68)
            box.pack_start(preview,True,True,0);box.pack_end(button('×',lambda d=digest:self.remove(d)),False,False,0)
            row.add(box);self.list.add(row)
        self.list.show_all()
        if self.list.get_children():self.list.select_row(self.list.get_row_at_index(0))
    def remove(self,digest):
        from rice_clipboard import delete
        delete(digest);self.refresh()
    def control(self,action):
        def done(_):
            if self.alive:
                from rice_common import STATE
                self.pause.set_label('Retomar captura' if (STATE/'clipboard-disabled').exists() else 'Pausar e limpar');self.refresh()
        async_update(lambda:controls.command([str(ROOT/'scripts/clipboard-control'),action]),done)
    def choose(self,text):
        controls.copy_text(text)
        previous=self.previous;self.destroy()
        if previous:self.app.safe(lambda:controls.command(['niri','msg','action','focus-window','--id',str(previous)]))
