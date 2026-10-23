"""V4 panels built on the V3 application's singleton and shared GTK widgets."""
import json,subprocess
import gi
gi.require_version('Gtk','3.0');gi.require_version('Gdk','3.0')
from gi.repository import Gtk,Gdk,GLib
from rice_widgets import Popup,label,button,async_update,app_image
from rice_common import ROOT,desktop,start_desktop,windows,run
import rice_controls as controls

from rice_control_center import ControlCenter

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
