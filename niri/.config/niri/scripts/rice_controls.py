"""Control backends using supported NetworkManager, WirePlumber and system interfaces."""
import json,os,subprocess
from pathlib import Path
from gi.repository import Gio,GLib

def command(args,input=None):
    try:
        result=subprocess.run(args,input=input,text=True,capture_output=True,timeout=5,env={**os.environ,'LC_ALL':'C'})
    except (OSError,subprocess.TimeoutExpired):raise RuntimeError(f'{args[0]} indisponível') from None
    if result.returncode:raise RuntimeError(f'{args[0]}: operação não concluída (verifique dispositivo e permissões)')
    return result.stdout.strip()

def wifi():
    if 'wifi' not in command(['nmcli','-t','-f','TYPE','device']).splitlines():raise RuntimeError('Adaptador Wi-Fi indisponível')
    enabled=command(['nmcli','radio','wifi'])=='enabled'
    if not enabled:return False,'Wi-Fi desativado'
    ssid=next((s.split(':',1)[1].replace('\\:',':') for s in command(['nmcli','-t','-f','ACTIVE,SSID','dev','wifi','list','--rescan','no']).splitlines() if s.startswith('yes:')),'Sem conexão Wi-Fi')
    return enabled,ssid

def bluetooth():
    info=command(['bluetoothctl','show'])
    powered='Powered: yes' in info
    devices=command(['bluetoothctl','devices','Connected'])
    return powered,'\n'.join(s.split(' ',2)[-1] for s in devices.splitlines()) or 'Sem dispositivos conectados'

def volume(target):
    data=command(['wpctl','get-volume',target]).split()
    return round(float(data[1])*100),'[MUTED]' in data

def outputs():
    sinks=json.loads(command(['pactl','-f','json','list','sinks']))
    default=command(['pactl','get-default-sink'])
    def description(sink):
        props=sink.get('properties',{})
        for value in [sink.get('description'),props.get('device.description'),props.get('device.product.name'),sink['name']]:
            if value and value!='(null)':return value
    return [(s['name'],description(s)) for s in sinks],default

def brightness():
    outputs=json.loads(command(['niri','msg','-j','outputs']))
    if not any(name.startswith(('eDP','LVDS','DSI')) and output.get('logical') for name,output in outputs.items()):return None
    devices=list(Path('/sys/class/backlight').glob('*'))
    if not devices:return None
    device=devices[0];maximum=int((device/'max_brightness').read_text())
    return device.name,round(int((device/'brightness').read_text())*100/maximum)

def battery():
    for device in Path('/sys/class/power_supply').glob('*'):
        if (device/'capacity').exists():return (device/'capacity').read_text().strip()+'% · '+{'Charging':'Carregando','Discharging':'Em uso','Full':'Carregada','Not charging':'Conectada'}.get((device/'status').read_text().strip(),(device/'status').read_text().strip())
    return 'Sem bateria'

def power_proxy():
    for bus,path in [('org.freedesktop.UPower.PowerProfiles','/org/freedesktop/UPower/PowerProfiles'),('net.hadess.PowerProfiles','/net/hadess/PowerProfiles')]:
        try:
            proxy=Gio.DBusProxy.new_for_bus_sync(Gio.BusType.SYSTEM,Gio.DBusProxyFlags.DO_NOT_AUTO_START,None,bus,path,bus,None)
            if proxy.get_cached_property('ActiveProfile') is not None:return proxy
        except GLib.Error:pass
    return None

def set_profile(proxy,value):
    proxy.call_sync('org.freedesktop.DBus.Properties.Set',GLib.Variant('(ssv)',(proxy.get_interface_name(),'ActiveProfile',GLib.Variant('s',value))),Gio.DBusCallFlags.NONE,3000,None)


def copy_text(text):
    # wl-copy forks a clipboard owner; inherited capture pipes would stay open.
    subprocess.run(['wl-copy','--type','text/plain;charset=utf-8'],input=text,text=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,check=True,timeout=3)
