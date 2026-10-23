"""Control backends using supported NetworkManager, WirePlumber and system interfaces."""
import json,os,subprocess
from pathlib import Path
from gi.repository import Gio,GLib

def command(args,input=None,timeout=5):
    try:
        result=subprocess.run(args,input=input,text=True,capture_output=True,timeout=timeout,env={**os.environ,'LC_ALL':'C'})
    except (OSError,subprocess.TimeoutExpired):raise RuntimeError(f'{args[0]} indisponível') from None
    if result.returncode:raise RuntimeError(f'{args[0]}: operação não concluída (verifique dispositivo e permissões)')
    return result.stdout.strip()

def wifi():
    if 'wifi' not in command(['nmcli','-t','-f','TYPE','device']).splitlines():raise RuntimeError('Adaptador Wi-Fi indisponível')
    enabled=command(['nmcli','radio','wifi'])=='enabled'
    if not enabled:return False,'Wi-Fi desativado'
    ssid=next((row[1] for row in terse_rows(command(['nmcli','-t','-f','ACTIVE,SSID','dev','wifi','list','--rescan','no'])) if len(row)==2 and row[0]=='yes'),'Sem conexão Wi-Fi')
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


def terse_rows(text):
    """Split nmcli's escaped colon fields without damaging SSIDs or names."""
    rows=[]
    for line in text.splitlines():
        fields=[];value='';escaped=False
        for char in line:
            if escaped:value+=char;escaped=False
            elif char=='\\':escaped=True
            elif char==':':fields.append(value);value=''
            else:value+=char
        fields.append(value);rows.append(fields)
    return rows


def networks():
    rows=terse_rows(command(['nmcli','-t','-f','IN-USE,SSID,SIGNAL,SECURITY','device','wifi','list','--rescan','no']))
    saved={}
    # Read only public settings. GetSecrets is deliberately never called.
    bus=Gio.bus_get_sync(Gio.BusType.SYSTEM,None)
    def call(path,interface,method):
        return bus.call_sync('org.freedesktop.NetworkManager',path,interface,method,None,None,Gio.DBusCallFlags.NONE,2500,None).unpack()[0]
    for path in call('/org/freedesktop/NetworkManager/Settings','org.freedesktop.NetworkManager.Settings','ListConnections'):
        settings=call(path,'org.freedesktop.NetworkManager.Settings.Connection','GetSettings')
        wireless=settings.get('802-11-wireless')
        if wireless:
            ssid=bytes(wireless.get('ssid',[])).decode('utf-8',errors='replace')
            saved[ssid]=settings['connection']['uuid']
    found={}
    for fields in rows:
        if len(fields)!=4:continue
        active,ssid,signal,security=fields
        if not ssid:continue
        item={'ssid':ssid,'active':active=='*','signal':int(signal or 0),'security':security,'uuid':saved.get(ssid)}
        previous=found.get(ssid)
        if previous:
            connected=previous['active'] or item['active']
            if previous['signal']>item['signal']:item=previous
            item['active']=connected
        found[ssid]=item
    return sorted(found.values(),key=lambda item:(not item['active'],-item['signal'],item['ssid'].casefold()))


def connect_network(item):
    if not item.get('uuid'):
        raise RuntimeError('Configure esta rede em Conexões avançadas; nenhuma senha é solicitada ou armazenada pelo painel.')
    command(['nmcli','--wait','12','connection','up','uuid',item['uuid']],timeout=15)


def paired_devices():
    result=[]
    for line in command(['bluetoothctl','devices','Paired']).splitlines():
        fields=line.split(' ',2)
        if len(fields)!=3:continue
        _,address,name=fields
        info=command(['bluetoothctl','info',address])
        result.append({'address':address,'name':name,'connected':'Connected: yes' in info})
    return result


def connect_bluetooth(item):
    command(['bluetoothctl','disconnect' if item['connected'] else 'connect',item['address']],timeout=15)


def inputs():
    sources=json.loads(command(['pactl','-f','json','list','sources']))
    default=command(['pactl','get-default-source'])
    return [(s['name'],s.get('description') or s['name']) for s in sources if not s['name'].endswith('.monitor')],default


def battery_details():
    devices=list(Path('/sys/class/power_supply').glob('*'))
    online=any((p/'online').exists() and (p/'online').read_text().strip()=='1' for p in devices)
    for device in devices:
        if not (device/'capacity').exists():continue
        status=(device/'status').read_text().strip()
        return {'percent':int((device/'capacity').read_text()),'status':{'Charging':'Carregando','Discharging':'Em uso','Full':'Carregada','Not charging':'Conectada'}.get(status,status),'external':online}
    return None


def control_snapshot():
    readers={'wifi':wifi,'bluetooth':bluetooth,'volume':lambda:volume('@DEFAULT_AUDIO_SINK@'),
             'mic':lambda:volume('@DEFAULT_AUDIO_SOURCE@'),'outputs':outputs,'inputs':inputs,
             'brightness':brightness,'battery':battery_details,'profiles':power_proxy,
             'notifications':lambda:json.loads(command([str(Path(__file__).resolve().parents[1]/'scripts/notifications')]))}
    values={}
    for key,reader in readers.items():
        try:values[key]=reader()
        except Exception:values[key]=None
    return values
