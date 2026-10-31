"""Bounded fake MPRIS player for manual integration tests; never plays audio.

Usage: python3 mpris_fixture.py /tmp/private-directory/state.json
It exits after 90 seconds or SIGTERM. The real players are not paused/modified.
"""
import argparse
import json
from pathlib import Path
import signal
import sys
sys.dont_write_bytecode=True
from gi.repository import Gio,GLib,GLibUnix

XML='''<node>
<interface name="org.mpris.MediaPlayer2">
<method name="Raise"/><method name="Quit"/>
<property name="CanQuit" type="b" access="read"/><property name="CanRaise" type="b" access="read"/>
<property name="HasTrackList" type="b" access="read"/><property name="Identity" type="s" access="read"/>
<property name="DesktopEntry" type="s" access="read"/>
<property name="SupportedUriSchemes" type="as" access="read"/><property name="SupportedMimeTypes" type="as" access="read"/>
</interface>
<interface name="org.mpris.MediaPlayer2.Player">
<method name="Play"/><method name="Pause"/><method name="PlayPause"/>
<method name="Next"/><method name="Previous"/><method name="Stop"/>
<property name="PlaybackStatus" type="s" access="read"/>
<property name="LoopStatus" type="s" access="readwrite"/><property name="Rate" type="d" access="readwrite"/>
<property name="Shuffle" type="b" access="readwrite"/><property name="Volume" type="d" access="readwrite"/>
<property name="Metadata" type="a{sv}" access="read"/><property name="Position" type="x" access="read"/>
<property name="MinimumRate" type="d" access="read"/><property name="MaximumRate" type="d" access="read"/>
<property name="CanGoNext" type="b" access="read"/><property name="CanGoPrevious" type="b" access="read"/>
<property name="CanPlay" type="b" access="read"/><property name="CanPause" type="b" access="read"/>
<property name="CanSeek" type="b" access="read"/><property name="CanControl" type="b" access="read"/>
</interface>
<interface name="org.niri.Rice.MprisFixture">
<method name="SetMetadata"><arg type="s" direction="in"/><arg type="s" direction="in"/><arg type="s" direction="in"/></method>
<method name="SetState"><arg type="s" direction="in"/><arg type="s" direction="in"/><arg type="s" direction="in"/><arg type="s" direction="in"/></method>
<method name="InvalidateMetadata"/>
</interface></node>'''


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('state',type=Path)
    parser.add_argument('--name',default='rice_test',choices=['rice_test','rice_test2','spotify_test','firefox_test'])
    parser.add_argument('--initial-status',default='Playing',choices=['Playing','Paused','Stopped'])
    parser.add_argument('--empty',action='store_true',help='Start without track metadata')
    parser.add_argument('--duration',type=int,default=90)
    args=parser.parse_args()
    state=args.state;state.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    loop=GLib.MainLoop();bus=Gio.bus_get_sync(Gio.BusType.SESSION,None)
    calls=[];status=args.initial_status
    root={'CanQuit':GLib.Variant('b',True),'CanRaise':GLib.Variant('b',False),'HasTrackList':GLib.Variant('b',False),
          'Identity':GLib.Variant('s','Rice test fixture'),'DesktopEntry':GLib.Variant('s',args.name),
          'SupportedUriSchemes':GLib.Variant('as',[]),'SupportedMimeTypes':GLib.Variant('as',[])}
    player={'Metadata':GLib.Variant('a{sv}',{'mpris:trackid':GLib.Variant('o','/org/niri/test/track'),
            'xesam:title':GLib.Variant('s',('Título de teste muito longo <&> 日本語 · '*20)+'$(inert)'),
            'xesam:artist':GLib.Variant('as',['Artista de teste '+('Longo '*20)]),'xesam:album':GLib.Variant('s','Álbum <&> teste'),
            'mpris:length':GLib.Variant('x',90000000)}),
            'LoopStatus':GLib.Variant('s','None'),'Rate':GLib.Variant('d',1),'Shuffle':GLib.Variant('b',False),
            'Volume':GLib.Variant('d',1),'Position':GLib.Variant('x',0),'MinimumRate':GLib.Variant('d',1),
            'MaximumRate':GLib.Variant('d',1),'CanGoNext':GLib.Variant('b',True),'CanGoPrevious':GLib.Variant('b',True),
            'CanPlay':GLib.Variant('b',True),'CanPause':GLib.Variant('b',True),'CanSeek':GLib.Variant('b',False),'CanControl':GLib.Variant('b',True)}
    if args.empty:player['Metadata']=GLib.Variant('a{sv}',{})
    def save():
        state.write_text(json.dumps({'calls':calls,'status':status}));state.chmod(0o600)
    def get_property(connection,sender,path,interface,name):
        if name=='PlaybackStatus':return GLib.Variant('s',status)
        return (root if interface=='org.mpris.MediaPlayer2' else player)[name]
    def method(connection,sender,path,interface,name,parameters,invocation):
        nonlocal status
        calls.append(name)
        changes={}
        if name in ['SetMetadata','SetState']:
            if name=='SetState':status,title,artist,album=parameters.unpack()
            else:title,artist,album=parameters.unpack()
            values=player['Metadata'].unpack()
            values={key:GLib.Variant('o' if key=='mpris:trackid' else ('x' if key=='mpris:length' else ('as' if key=='xesam:artist' else 's')),value) for key,value in values.items()}
            values.update({'xesam:title':GLib.Variant('s',title),'xesam:artist':GLib.Variant('as',[artist]),'xesam:album':GLib.Variant('s',album)})
            player['Metadata']=GLib.Variant('a{sv}',values)
            changes['Metadata']=player['Metadata']
        if name=='PlayPause':status='Paused' if status=='Playing' else 'Playing'
        if name in ['Play','Pause','Stop']:status={'Play':'Playing','Pause':'Paused','Stop':'Stopped'}[name]
        changes['PlaybackStatus']=GLib.Variant('s',status)
        save()
        invocation.return_value(None)
        bus.emit_signal(None,path,'org.freedesktop.DBus.Properties','PropertiesChanged',
                        GLib.Variant('(sa{sv}as)',('org.mpris.MediaPlayer2.Player',
                            {} if name=='InvalidateMetadata' else changes,
                            ['Metadata'] if name=='InvalidateMetadata' else [])))
        if name=='Quit':loop.quit()
    info=Gio.DBusNodeInfo.new_for_xml(XML)
    for interface in info.interfaces:bus.register_object('/org/mpris/MediaPlayer2',interface,method,get_property,None)
    owner=Gio.bus_own_name_on_connection(bus,'org.mpris.MediaPlayer2.'+args.name,Gio.BusNameOwnerFlags.NONE,lambda *_:save(),None)
    def stop():loop.quit();return False
    GLib.timeout_add_seconds(min(600,max(10,args.duration)),stop)
    GLibUnix.signal_add(GLib.PRIORITY_DEFAULT,signal.SIGTERM,stop)
    try:loop.run()
    finally:Gio.bus_unown_name(owner)


if __name__=='__main__':main()
