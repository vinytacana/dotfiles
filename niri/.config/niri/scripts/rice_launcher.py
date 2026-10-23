"""Spotlight-style UI; Fuzzel remains available through the original shortcut."""
import json,subprocess,time
from pathlib import Path
import gi
gi.require_version('Gtk','3.0');gi.require_version('Gdk','3.0')
from gi.repository import Gtk,Gdk,Gio,GLib
from rice_widgets import Popup,label,button,app_image
from rice_common import ROOT,STATE,desktop,start_desktop,favorites,read_json,write_json,run
import rice_search as search

class Spotlight(Popup):
    def __init__(self,app):
        super().__init__(app,'Spotlight do Niri',800)
        self.pending=None;self.index_pending=None;self.indexing=False
        self.connect('destroy',self.cleanup)
        self.apps=sorted([a for a in Gio.AppInfo.get_all() if a.get_id() and a.should_show() and isinstance(a,Gio.DesktopAppInfo)],key=lambda a:a.get_display_name().casefold())
        top=Gtk.Box(spacing=8)
        self.entry=Gtk.SearchEntry(placeholder_text='Pesquisar aplicativos, arquivos e projetos…')
        top.pack_start(self.entry,True,True,0);top.pack_end(button('×',self.destroy),False,False,0);self.panel.pack_start(top,False,False,0)
        self.panel.pack_start(label('Aplicativos · / arquivos · @ projetos · > ações · = contas','muted'),False,False,0)
        self.list=Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE);self.list.connect('row-activated',lambda _,row:self.activate(row))
        self.scroll=Gtk.ScrolledWindow();self.scroll.set_policy(Gtk.PolicyType.NEVER,Gtk.PolicyType.AUTOMATIC);self.scroll.set_min_content_height(350);self.scroll.set_max_content_height(520);self.scroll.add(self.list)
        self.panel.pack_start(self.scroll,True,True,0)
        footer=Gtk.Box(spacing=8);footer.pack_start(button('Atualizar índice',self.index,'view-refresh-symbolic'),False,False,0)
        footer.pack_start(button('Pastas pesquisadas',self.preferences,'folder-symbolic'),False,False,0)
        footer.pack_end(button('Fuzzel',lambda:(self.destroy(),run(['fuzzel','--config',str(ROOT/'fuzzel.ini')]))),False,False,0)
        self.panel.pack_start(footer,False,False,0)
        self.message=label('Pesquisa por nome. O índice não lê o conteúdo dos arquivos.','muted');self.panel.pack_start(self.message,False,False,0)
        self.preferences_box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=8);self.preferences_box.set_no_show_all(True)
        self.panel.pack_start(self.preferences_box,False,False,0)
        self.entry.connect('search-changed',lambda *_:self.debounce())
        self.entry.connect('activate',lambda *_:self.activate(self.list.get_selected_row()))
        self.connect('key-press-event',self.keys)
        self.results();self.entry.grab_focus()
        if not (STATE/'launcher.json').exists():self.index()
    def debounce(self):
        if not self.alive:return
        if self.pending:GLib.source_remove(self.pending)
        def ready():
            self.pending=None
            return self.results()
        self.pending=GLib.timeout_add(120,ready)
    def cleanup(self,*_):
        # A settings/calendar window can keep this GTK application alive.
        # Cancel popup work, while an independently running index may finish.
        for name in ['pending','index_pending']:
            source=getattr(self,name)
            if source and GLib.MainContext.default().find_source_by_id(source):
                GLib.source_remove(source)
            setattr(self,name,None)
        self.indexing=False
    def row(self,title,subtitle,callback,app=None,icon='system-run-symbolic',extra=None):
        row=Gtk.ListBoxRow();row.callback=callback;row.get_style_context().add_class('search-result')
        box=Gtk.Box(spacing=12)
        box.pack_start(app_image(app,32) if app else Gtk.Image.new_from_icon_name(icon,Gtk.IconSize.DND),False,False,0)
        text=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=3)
        main=label(title);main.set_ellipsize(3);main.set_max_width_chars(58);text.pack_start(main,False,False,0)
        sub=label(subtitle,'muted');sub.set_ellipsize(3);sub.set_max_width_chars(70);text.pack_start(sub,False,False,0)
        box.pack_start(text,True,True,0)
        if extra:
            for title,action in extra:box.pack_end(button(title,lambda a=action:self.safe(a)),False,False,0)
        row.add(box);self.list.add(row)
    def safe(self,work):
        try:work()
        except Exception:self.message.set_text('Não foi possível executar a ação. Verifique se o aplicativo ou caminho ainda está disponível.')
    def activate(self,row):
        if row:self.safe(row.callback)
    def remember(self,identity):
        recent=read_json(STATE/'launcher-recent.json',[])
        write_json(STATE/'launcher-recent.json',[identity]+[x for x in recent if x!=identity][:19])
    def open_app(self,identity):
        start_desktop(identity);self.remember(identity);self.destroy()
    def open_path(self,kind,path):
        subprocess.run(['systemd-run','--user','--quiet','--collect','--property=ExitType=cgroup','--property=PartOf=graphical-session.target','--',str(ROOT/'scripts/rice-open'),kind,path],check=True,timeout=4)
        self.remember(path);self.destroy()
    def quick(self,name):
        if name in ['reiniciar','desligar']:
            dialog=Gtk.MessageDialog(transient_for=self,modal=True,message_type=Gtk.MessageType.QUESTION,buttons=Gtk.ButtonsType.YES_NO,text=('Reiniciar' if name=='reiniciar' else 'Desligar')+' o computador agora?')
            response=dialog.run();dialog.destroy()
            if response==Gtk.ResponseType.YES:run(['systemctl','reboot' if name=='reiniciar' else 'poweroff']);self.destroy()
            return
        commands={'terminal':lambda:start_desktop('Alacritty.desktop'),'arquivos':lambda:start_desktop('org.gnome.Nautilus.desktop'),'configurações':lambda:run([str(ROOT/'scripts/settings-hub'),'settings']),'controle':lambda:run([str(ROOT/'scripts/settings-hub'),'control']),'bloquear':lambda:run([str(ROOT/'scripts/lock')]),'wallpaper':lambda:run([str(ROOT/'scripts/wallpaper-manager'),'choose']),'clipboard':lambda:run([str(ROOT/'scripts/settings-hub'),'clipboard']),'notificações':lambda:run([str(ROOT/'scripts/notifications'),'open'])}
        action=commands.get(name)
        if action:self.destroy();action()
    def project_star(self,path):
        prefs=search.config();items=prefs.get('favorite_projects',[])
        if path in items:items.remove(path)
        else:items.append(path)
        prefs['favorite_projects']=items;write_json(STATE/'launcher.json',prefs);self.results()
    def results(self):
        if not self.alive:return False
        for row in self.list.get_children():self.list.remove(row)
        text=self.entry.get_text().strip();prefix=text[:1];query=text[1:].strip() if prefix in ['>','=','/','@'] else text
        if prefix=='>':
            for name in ['terminal','arquivos','configurações','controle','bloquear','wallpaper','clipboard','notificações','reiniciar','desligar']:
                if query.casefold() in name:self.row(name,'Ação rápida'+(' · pede confirmação' if name in ['reiniciar','desligar'] else ''),lambda n=name:self.quick(n))
        elif prefix=='=':
            try:
                result=search.calculate(query)
                self.row(result,'Enter copia o resultado',lambda r=result:self.copy_result(r),icon='accessories-calculator-symbolic')
            except (ValueError,SyntaxError,ArithmeticError,OverflowError):self.row('Conta inválida','Use números, parênteses e + − * / % **',lambda:None,icon='accessories-calculator-symbolic')
        else:
            recent=read_json(STATE/'launcher-recent.json',[]);fav=favorites()
            if prefix not in ['/','@']:
                apps=[a for a in self.apps if all(term in (a.get_display_name()+' '+a.get_id()).casefold() for term in query.casefold().split())]
                apps.sort(key=lambda a:(0 if a.get_id() in recent else 1, recent.index(a.get_id()) if a.get_id() in recent else fav.index(a.get_id()) if a.get_id() in fav else 100))
                for app in apps[:8]:self.row(app.get_display_name(),'Aplicativo',lambda i=app.get_id():self.open_app(i),app=app)
            kind='project' if prefix=='@' else 'file' if prefix=='/' else None
            paths=search.search(query,kind,16) if query or prefix in ['/','@'] else search.search('','project',5)
            favorites_projects=search.config().get('favorite_projects',[])
            if prefix!='/':
                preferred=search.project_paths(favorites_projects+recent,query)
                paths=list({item[0]:item for item in preferred+paths}.values())
            paths.sort(key=lambda item:(item[0] not in favorites_projects,item[0] not in recent))
            for path,name,kind in paths[:12]:
                if kind=='project':
                    extra=[('★' if path in favorites_projects else '☆',lambda p=path:self.project_star(p)),('Terminal',lambda p=path:self.open_path('terminal',p)),('Pasta',lambda p=path:self.open_path('folder',p))]
                    self.row(name,'Projeto · '+path,lambda p=path:self.open_path('editor',p),icon='folder-development-symbolic',extra=extra)
                else:self.row(name,path,lambda p=path:self.open_path('file',p),icon='text-x-generic-symbolic',extra=[('Pasta',lambda p=path:self.open_path('folder',p))])
        self.list.show_all()
        if self.list.get_children():self.list.select_row(self.list.get_row_at_index(0))
        else:self.message.set_text('Nenhum resultado. Verifique as pastas configuradas e atualize o índice.')
        return False
    def copy_result(self,value):
        from rice_controls import copy_text
        copy_text(value);self.destroy()
    def keys(self,_,event):
        if event.keyval in (Gdk.KEY_Up,Gdk.KEY_Down):
            rows=self.list.get_children()
            if rows:
                selected=self.list.get_selected_row();index=rows.index(selected) if selected else -1
                row=rows[(index+(1 if event.keyval==Gdk.KEY_Down else -1))%len(rows)];self.list.select_row(row)
                adjustment=self.scroll.get_vadjustment();y=row.get_allocation().y
                if y<adjustment.get_value():adjustment.set_value(y)
                elif y+row.get_allocated_height()>adjustment.get_value()+adjustment.get_page_size():adjustment.set_value(y+row.get_allocated_height()-adjustment.get_page_size())
            return True
        return False
    def index(self):
        if not self.alive or self.indexing:return
        self.indexing=True;self.message.set_text('Atualizando índice em segundo plano…')
        subprocess.run(['systemctl','--user','start','--no-block','niri-rice-index.service'],check=True,timeout=3)
        def ready():
            if not self.alive:self.index_pending=None;return False
            state=subprocess.run(['systemctl','--user','is-active','--quiet','niri-rice-index.service']).returncode
            if state==0:return True
            self.index_pending=None
            result=subprocess.check_output(['systemctl','--user','show','-p','Result','--value','niri-rice-index.service'],text=True,timeout=2).strip()
            self.indexing=False;self.message.set_text('Índice atualizado. Pesquisa somente por nomes.' if result=='success' else 'Falha ao atualizar o índice. Verifique as pastas e o serviço niri-rice-index.');self.results();return False
        self.index_pending=GLib.timeout_add(800,ready)
    def preferences(self):
        visible=self.preferences_box.get_visible()
        if visible:self.preferences_box.hide();return
        for child in self.preferences_box.get_children():self.preferences_box.remove(child)
        prefs=search.config()
        for key,title in [('file_roots','Arquivos'),('project_roots','Projetos')]:
            row=Gtk.Box(spacing=8);row.pack_start(label(title,'section-title'),True,True,0)
            row.pack_end(button('+ Pasta',lambda k=key:self.add_root(k)),False,False,0);self.preferences_box.pack_start(row,False,False,0)
            for path in prefs.get(key,[]):
                row=Gtk.Box(spacing=8);text=label(path,'muted');text.set_ellipsize(3);text.set_max_width_chars(60)
                row.pack_start(text,True,True,0);row.pack_end(button('×',lambda k=key,p=path:self.remove_root(k,p)),False,False,0);self.preferences_box.pack_start(row,False,False,0)
        self.preferences_box.set_no_show_all(False);self.preferences_box.show_all();self.preferences_box.set_no_show_all(True)
    def remove_root(self,key,path):
        prefs=search.config();prefs[key].remove(path);write_json(STATE/'launcher.json',prefs)
        self.preferences_box.hide();self.preferences();self.index()
    def add_root(self,key):
        chooser=Gtk.FileChooserNative.new('Adicionar pasta pesquisável',self,Gtk.FileChooserAction.SELECT_FOLDER,'Adicionar','Cancelar')
        def selected(dialog,response):
            if response==Gtk.ResponseType.ACCEPT:
                path=Path(dialog.get_filename()).resolve()
                if path in [Path.home(),Path('/')]:self.message.set_text('Escolha uma subpasta; HOME e raiz inteira são excluídos.');dialog.destroy();self.show_all();self.present();return
                prefs=search.config()
                if len(prefs.get(key,[]))>=8:self.message.set_text('Use até oito pastas por categoria.');dialog.destroy();self.show_all();self.present();return
                prefs[key]=list(dict.fromkeys(prefs.get(key,[])+[str(path)]));write_json(STATE/'launcher.json',prefs)
                self.preferences_box.hide();self.preferences();self.index()
            dialog.destroy()
            if self.alive:self.show_all();self.present()
        chooser.connect('response',selected);self.hide();chooser.show()
