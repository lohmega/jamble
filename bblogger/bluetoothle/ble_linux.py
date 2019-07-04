
# Bluetooth Low Energy interface for Linux
# using bluez dbus API
#
# Kudos and derived from:
#  - https://github.com/adafruit/Adafruit_Python_BluefruitLE/ 
#    License: MIT Copyright (c) 2015 Adafruit Industries
#
#  - https://github.com/hadess/bluez/blob/master/test/bluezutils.py
#    License: GNU GPL V2
# 

from uuid import UUID
from collections.abc import Iterable

import dbus.mainloop.glib
from future.utils import raise_
from gi.repository import GObject
import time
import threading
import sys
import queue
import subprocess

from bluetoothle.typeconvert import toCType, fromCType
from bluetoothle.typeconvert import DEFAULT_BYTEORDER
from bluetoothle.common import print_dbg, print_wrn, print_err

import platform

## DBus interfaces (if)
_IF_ADAPTER             = 'org.bluez.Adapter1'
_IF_DEVICE              = 'org.bluez.Device1'
_IF_GATT_SERVICE        = 'org.bluez.GattService1'
_IF_GATT_CHARACTERISTIC = 'org.bluez.GattCharacteristic1'
_IF_GATT_DESCRIPTOR     = 'org.bluez.GattDescriptor1'
_IF_PROPERTIES          = 'org.freedesktop.DBus.Properties'

TIMEOUT_SEC = 8

_gp = None 


def _py2dbus(data):
    '''
        convert python data types to dbus data types
    '''
    if isinstance(data, str):
        data = dbus.String(data)
    elif isinstance(data, bool):
        # python bools are also ints, order is important !
        data = dbus.Boolean(data)
    elif isinstance(data, int):
        data = dbus.Int64(data)
    elif isinstance(data, float):
        data = dbus.Double(data)
    elif isinstance(data, list):
        data = dbus.Array([_py2dbus(value) for value in data], signature='v')
    elif isinstance(data, dict):
        data = dbus.Dictionary(data, signature='sv')
        for key in data.keys():
            data[key] = _py2dbus(data[key])
    return data


def _dbus2py(data):
    '''
        convert dbus data types to python native data types
    '''
    if isinstance(data, dbus.String):
        data = str(data)
    elif isinstance(data, dbus.Boolean):
        data = bool(data)
    elif isinstance(data, dbus.Int64):
        data = int(data)
    elif isinstance(data, dbus.Double):
        data = float(data)
    elif isinstance(data, dbus.ObjectPath):
        data = str(data)
    elif isinstance(data, dbus.Array):
        data = [_dbus2py(value) for value in data]
    elif isinstance(data, dbus.Dictionary):
        d = dict()
        for k in data.keys():
            d[_dbus2py(k)] = _dbus2py(data[k])
        data = d
    return data

def versions():
    def bluez_version():
        try:
            s = subprocess.check_output(['bluetoothctl', '--version'])
            s = s.decode('ascii').strip()
        except (FileNotFoundError, subprocess.CalledProcessError) as e:
            s = '<?>'
        return s

    vd = {
        'dbus': dbus.__version__,
        'bluez': bluez_version(),
        'os': platform.platform(),
        'python': platform.python_version()
    }

    return vd
#
# def _getDBusIfObjects(interface, parentpath='/org/bluez'):
    # '''Return a list of all bluez DBus objects that implement the requested
    # interface name and are under the specified path.  The default is to
    # search devices under the root of all bluez objects.
    # '''
    # # Iterate through all the objects in bluez's DBus hierarchy and return
    # # any that implement the requested interface under the specified path.
    # parentpath = parentpath.lower()

    # bus = dbus.SystemBus()
    # manager = dbus.Interface(bus.get_object('org.bluez', '/'),
                # 'org.freedesktop.DBus.ObjectManager')
    # objects = []
# managedObjects = ranager.GetManagedObjects()
    # for opath, ifaces in managedObjects.items():
        # if not interface in ifaces.keys():
            # continue
        # if not opath.lower().startswith(parentpath):
            # contine
        # obj = bus.get_object('org.bluez', opath)
        # objects.append(obj)

    # return objects

class Address(object):
    def __init__(self, s):
        '''
        excpected format example: 4A:17:B9:62:46:ED
        '''
        s = s.replace(':',' ')
        self._bytes = bytearray.fromhex(s)

        if len(self._bytes) != 6:
            raise TypeError('Invalid BLE address')

    def __cmp__(self, other):
        # if isinstance(other, str):
            # other = Address(other)
        #retur 
        return self._bytes.__cmp(other)
        # if self._bytes < other._bytes:
            # return 

    def __str__(self):
        return ':'.join(['{:02X}'.format(b) for b in list(self._bytes)])

    def __repr__(self):
        return str(self)

class Adapter(object):
    '''Bluez BLE network adapter.'''

    def __init__(self, identifier=None):
        '''
        '''
        global _gp
        _gp.verify() 

        if identifier is None:
            objs = _gp.getDBusIfObjects(_IF_ADAPTER)
            if not objs:
                raise RuntimeError('No adapters found')
            dbusobj = objs[0]
        # TODO elif isinstance(identifier, str):
        # find that adapter fromm paths
        elif isinstance(identifier, dbus.proxies.ProxyObject):
            dbusobj = identifier
        else:
            raise TypeError('Unknown adapter identifier')

        self._evtStartDiscovery = threading.Event()
        self._evtStartDiscovery.set()
        self._evtStopDiscovery = threading.Event()
        self._evtStopDiscovery.set()

        self._ifAdpt = dbus.Interface(dbusobj, _IF_ADAPTER)
        self._ifProp = dbus.Interface(dbusobj, _IF_PROPERTIES)
        self._ifProp.connect_to_signal('PropertiesChanged', self._onPropertiesChanged)


    def scan(self, devfilter=None, cached=True, timeout=TIMEOUT_SEC):
        '''
        return BLE devices. some might be cached by OS and no longer present. i.e.
        not always a clean device scan.

        :param devfilter: device filter. useful examples:
            # find specific myuuid advertiesed uuid(s)
            lambda dev: myuuid in dev.advertised

            # match address (not supported on MacOS)
            lambda dev: dev.addr == ble.Address()

            # print devices (once) when discovered 
            lambda dev: not print(dev)

            # match any uuids in iterable uuidsOfInterest.
            lambda dev: any(x in uuidsOfInterest for x in dev.advertised)

            # Match all uuids in iterable uuidsRequired:
            lamda dev: all(x in uuidsRequired for x in dev.advertised)

        :param cached: include cached devices if true. might be faster!?
        :param timeout: timeout in seconds. actual timeout might be more.
        '''
        if not cached:
            self._removeDisconnectedDevices()

        alldevices = {}
        devices = {}
        if not self._ispowered():
            print_dbg('power on adapter')
            self._power_on()

        attempts = 0
        maxAttempts = 6
        tstart = time.time()

        try:
            self._startDiscovery()
            
            # for some reason, devices to not appear at first try. perhaps related
            # to scan/discovery procedure?
            while True:
                for obj in _gp.getDBusIfObjects(_IF_DEVICE):
                    device = Device(obj) 
                    devaddr = device.addr 

                    if devaddr in alldevices:
                        continue
                    alldevices[devaddr] = True

                    if devfilter is not None and devfilter(device):
                        devices[devaddr] = device

                if timeout: 
                    if (time.time() - tstart) >= timeout:
                        break

                attempts += 1
                if attempts >= maxAttempts:
                    break

                # assumtion here that if one (present) device detected, other
                # devices should also be in the list.
                if len(devices):
                    break

                time.sleep(0.1)
        finally:
            # Make sure scanning is stopped before exiting.
            self._stopDiscovery()

        ttot = time.time() - tstart
        print_dbg(len(devices), 'devices found in', ttot, 'sec and', attempts, 'attempts')
        return list(devices.values())

    def _removeDisconnectedDevices(self):
        '''Clear any internally cached BLE device data.  Necessary in some cases
        to prevent issues with stale device data getting cached by the OS.
        '''
        #FIXME: this will remove devices regardless of adapter. correct?

        # def onRemoveDeviceError(self, e):
            # print(e)
        devices = [Device(o) for o in _gp.getDBusIfObjects(_IF_DEVICE)]
        for device in devices:
            if device.isConnected:
                continue
            print_dbg('Removing disconnected device', device)
            self._ifAdpt.RemoveDevice(device._ifDev.object_path)
            

    def _onPropertiesChanged(self, iface, changed, invalidated):
        # Handle property changes for the adapter.  Note this call happens in
        # a separate thread so be careful to make thread safe changes to state!
        # Skip any change events not for this adapter interface.
        if iface != _IF_ADAPTER:
            return
        # If scanning starts then fire the scan started event.
        if 'Discovering' in changed:
            discovering = changed['Discovering']
            if discovering == 1:
                self._evtStartDiscovery.set()
            elif discovering == 0:
                self._evtStopDiscovery.set()
            else:
                pass


    def _startDiscovery(self, timeout=10):
        ''' discovery i.e. scan '''
        print_dbg('scan/discovery start')
        assert(self._evtStartDiscovery.is_set()) # no pending
        assert(self._evtStopDiscovery.is_set()) # no pending

        self._evtStartDiscovery.clear()
        self._ifAdpt.StartDiscovery()
        if not self._evtStartDiscovery.wait(timeout):
            raise RuntimeError('Timeout waiting on start scan/discovery!')

    def _stopDiscovery(self, timeout=10):
        ''' discovery i.e. scan '''
        print_dbg('scan/discovery stop')
        assert(self._evtStartDiscovery.is_set()) # no pending
        assert(self._evtStopDiscovery.is_set()) # no pending

        self._evtStopDiscovery.clear()
        self._ifAdpt.StopDiscovery()
        if not self._evtStopDiscovery.wait(timeout):
            raise RuntimeError('Timeout waiting on stop scan/discovery!')

    @property
    def name(self):
        '''Return the name of this BLE network adapter.'''
        return self._ifProp.Get(_IF_ADAPTER, 'Name')

    def _isDiscovering(self):
        return self._ifProp.Get(_IF_ADAPTER, 'Discovering')

    def _power_on(self):
        '''Power on this BLE adapter.'''
        return self._ifProp.Set(_IF_ADAPTER, 'Powered', True)

    def _power_off(self):
        '''Power off this BLE adapter.'''
        return self._ifProp.Set(_IF_ADAPTER, 'Powered', False)

    def _ispowered(self):
        '''Return True if the BLE adapter is powered up, otherwise return False.
        '''
        return self._ifProp.Get(_IF_ADAPTER, 'Powered')



class _GattCharacteristicNotifications(object):
    '''
    waiting on multiple queues should be possible, see:
    https://stackoverflow.com/a/2162188/1565079
    but will ad complexity...
    '''

    def __init__(self, charac):
        self._charac = charac
        self._queue = queue.Queue() # Queue is thread safe 
        #self._enabled = False
        self._partial = None

        self._evtEnable = threading.Event()
        self._evtEnable.set()

        self._evtDisable = threading.Event()
        self._evtDisable.set()

        self._ifChar = self._charac._ifChar
        self._ifProp = self._charac._ifProp

        self._ifProp.connect_to_signal('PropertiesChanged',
            self._onPropertiesChanged, byte_arrays=True)
        
    def __repr__(self):
        return '{} Notifications '.format(repr(self._charac))

    def __enter__(self):
        self.enable()
        return self

    def __exit__(self, exctype, excval, traceback):
        self.disable()
        return False
        
    def _get(self, timeout=None):
        # queue raises Empty on timeout, as this is probably due to BLE
        # communication timeout, reraise it as TimeoutError()
        
        #return self._queue.get(block=True, timeout=timeout)
        try:
            return self._queue.get(block=True, timeout=timeout)
        except queue.Empty: 
            #return None
            raise TimeoutError('Read notfications timeout')

    def _getSize(self, size, timeout=None):
        assert(size >= 0)
        if self._partial:
            ba = self._partial
            self._partial = None
        else:
            ba = bytearray()
            
        while len(ba) < size:
            data = self._get(timeout=timeout) # TODO update timeout
            ba.extend(data)
                
        if len(ba) > size:
            self._partial = ba[size:] # size to end
            ba = ba[0:size]

        return ba

    def read(self, len_=None, ctype=None, byteorder=None, timeout=TIMEOUT_SEC):
        '''
        :param len: number of bytes or number of ctype(s)
        return bytearray by default.
        on timeout, returns None or array of length less then length specified
        by len (if provided)

        '''
        assert(self._isEnabled())
        
        if byteorder is not None:
            raise NotImplementedError('TODO: Notifications read byteorder')

        if ctype is not None:
            if len_ is None:
                len_ = 1
            if ctype == 'ascii':  # TODO support nul terminated ascii string
                pass
            #if ctype is in 
            # size = len_ * sizeOfCtype(ctype)
            raise NotImplementedError('TODO: Notifications read type')

        elif len_ is not None:
            size = len_
            return self._getSize(size, timeout)

        else:
            return self._get(timeout)

    def _clear(self):
        count = 0
        while not self._queue.empty():
            self._queue.get(block=False)
            count += 1
        return count
        
    def _isEmpty(self):
        return self._queue.empty()

    def _onPropertiesChanged(self, iface, changed, invalidated):
        # TODO this should proably be moved to parent class
        # Check that this change is for a GATT characteristic and it has a
        # new value.
        if iface != _IF_GATT_CHARACTERISTIC:
            return

        if 'Notifying' in changed:
            notifying = int(changed['Notifying'])
            if notifying == 0:
                self._evtDisable.set()
            elif notifying == 1:
                self._evtEnable.set()
            else:
                raise RuntimeError( 'Unexpected "Notifying" property value \
                        "{}"'.format(connected))

        if 'Value' in changed:
            value = changed['Value']
            if value is None:
                print_err(self, 'PropertiesChanged cb None Value')
                return
            self._queue.put(value)

    def _isEnabled(self):
        v = int(self._ifProp.Get(_IF_GATT_CHARACTERISTIC, 'Notifying'))
        assert(v in (0, 1))
        return bool(v)

    # def _onStartStopSuccess(self): # FIXME no param?
        # self._tevt.set()

    # def _onStartStopError(self, e):
        # emsg = ' '.join([repr(self), 'StartNotify or StopNotify', 
            # e.get_dbus_name(), e.get_dbus_message()])
        # self._cbErr = RuntimeError(emsg) # raise in caller thread
        # self._tevt.set()

    def enable(self):
        assert(self._evtEnable.is_set()) # no pending enable
        assert(self._evtDisable.is_set()) # no pending disable
        assert(self._charac._device.isConnected)

        if self._isEnabled():
            print_dbg(self, 'Already enabled')
            return self
        self._clear()

        self._evtEnable.clear()
        self._ifChar.StartNotify()
        if not self._evtEnable.wait(TIMEOUT_SEC):
            raise TimeoutError('enable/StartNotify')
        
        print_dbg(self, 'Enabled')
        return self # with x.enable() as y

    def disable(self):
        assert(self._evtEnable.is_set()) # no pending enable
        assert(self._evtDisable.is_set()) # no pending disable
        # if not self._isEnabled():
            # print_dbg(self, 'already disabled')
            # return

        self._evtDisable.clear()
        self._ifChar.StopNotify()
        if not self._evtDisable.wait(TIMEOUT_SEC):
            raise TimeoutError('disable/StopNotify')

        print_dbg(self, 'Disabled')
        


class GattCharacteristic(object):

    def __init__(self, device, dbusobj):
        '''Create an instance of the GATT characteristic from the provided bluez
        DBus object.
        '''
        self._device = device
        self._ifChar = dbus.Interface(dbusobj, _IF_GATT_CHARACTERISTIC)
        self._ifProp = dbus.Interface(dbusobj, _IF_PROPERTIES)

        self._notifyq = None
        self._notifications = _GattCharacteristicNotifications(charac=self)

    def __repr__(self):
        return 'Characteristic {}'.format(self.uuid)

    @property
    def notifications(self):
        return self._notifications 

    def _properties(self):
        props = self._ifProp.GetAll(_IF_GATT_CHARACTERISTIC)
        return _dbus2py(props)

    @property
    def uuid(self):
        '''Return the UUID of this GATT characteristic.'''
        return UUID(str(self._ifProp.Get(_IF_GATT_CHARACTERISTIC, 'UUID')))

    def read(self, ctype=None, byteorder=None, offset=0):
        '''
        '''
        #return self._ifChar.ReadValue()
        ba = self._ifChar.ReadValue(
                {'offset': dbus.UInt16(offset, variant_level=1)},
                #reply_handler=self._onReadSuccess,
                #error_handler=self._onReadError,
                byte_arrays=True,
                dbus_interface=_IF_GATT_CHARACTERISTIC)
        if ctype is None:
            return ba
        else:
            if byteorder is None:
                byteorder = self._device.byteorder
            return fromCType(ba, ctype, byteorder)


    def write(self, data, ctype=None, byteorder=None, offset=0):
        # TODO handle bytes, not iterable. add param on data format?
        # if isinstance(data, Iterable):
            # bytedata = [dbus.Byte(b) for b in data]
        # else: # works for int. FIXME
            # bytedata = [dbus.Byte(data)]
        if ctype is None:
            ba = data
        else:
            if byteorder is None:
                byteorder = self._device.byteorder
            if isinstance(data, Iterable):
                ba = bytearray()
                for val in data:
                    ba.extend(toCType(val, ctype, byteorder))
            else:
                ba = toCType(data, ctype, byteorder)

            # bytedata = [dbus.Byte(b) for b in data]
        # TODO:
        # "type": string
            # Possible values:
            # "command": Write without response
            # "request": Write with response
            # "reliable": Reliable Write

        self._ifChar.WriteValue(ba,
            {'offset': dbus.UInt16(offset, variant_level=1)},
            dbus_interface=_IF_GATT_CHARACTERISTIC)
    # TODO
    # def descriptors(self):
        # '''Return list of GATT descriptors that have been discovered for this
        # characteristic.
        # '''
        # paths = self._ifProp.Get(_IF_GATT_CHARACTERISTIC, 'Descriptors')
        # return list(map(BluezGattDescriptor,
                   # _gp._get_objects_by_path(paths)))

class GattService(object):
    def __init__(self, uuid, device):
        self.uuid = uuid
        self._device = device
        self._characteristics = {}

    def characteristic(self, uuid, timeout=TIMEOUT_SEC):
        if not isinstance(uuid, UUID):
           raise TypeError('Not a UUID object') 

        tstart = time.time()
        while uuid not in self._characteristics:
            self._device._discover()
            tdelta = time.time() - tstart
            if tdelta >= timeout:
                break
            time.sleep(1)

        return self._characteristics[uuid]

class Device(object):
    '''Bluez BLE device.'''

    def __init__(self, dbusobj):
        '''Create an instance of the bluetooth device from the provided bluez
        DBus object.
        '''
        self._evtConnect = threading.Event()
        self._evtConnect.set()
        self._evtDisconnect = threading.Event()
        self._evtDisconnect.set()

        self._ifDev = dbus.Interface(dbusobj, _IF_DEVICE )
        self._ifProp = dbus.Interface(dbusobj, _IF_PROPERTIES)
        self._ifProp.connect_to_signal('PropertiesChanged', self._onPropertiesChanged)
        self._services  = {}
        self._byteorder = DEFAULT_BYTEORDER

    @property
    def byteorder(self):
        return self._byteorder

    @byteorder.setter
    def byteorder(self, byteorder):
        self._byteorder = byteorder

    def __str__(self):
        return '<Device {} {}>'.format(self.addr, self.name)
        
    def __repr__(self):
        return str(self)
    
    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exctype, excval, traceback):
        self.disconnect()
        return False

    def _property(self, name):
        return self._ifProp.Get(_IF_DEVICE, name)

    def _properties(self):
        props = self._ifProp.GetAll(_IF_DEVICE)
        return _dbus2py(props)

    def service(self, uuid, timeout=TIMEOUT_SEC):
        if not isinstance(uuid, UUID):
           raise TypeError('Not a UUID object') 

        if uuid not in self._services:
            tstart = time.time()
            while uuid not in self._services:
                self._discover()
                tdelta = time.time() - tstart
                if tdelta >= timeout:
                    #raise TimeoutError('get Serivce Timeout')
                    #return None
                    break
                time.sleep(1)
        return self._services[uuid]

    def _onPropertiesChanged(self, iface, changed, invalidated):
        # Handle property changes for the device.  Note this call happens in
        # a separate thread so be careful to make thread safe changes to state!
        # Skip any change events not for this adapter interface.
        if iface != _IF_DEVICE:
            return
        # If connected then fire the connected event.
        if 'Connected' in changed: 
            connected = int(changed['Connected'])
            if connected == 1:
                self._evtConnect.set()
            elif connected == 0:
                self._evtDisconnect.set()
            else:
                raise RuntimeError('Unexpected "Connected" property value \
                        "{}"'.format(connected))
        else:
            pass
    
    def connect(self, timeout=TIMEOUT_SEC):
        '''Connect to the device.  If not connected within the specified timeout
        then an exception is thrown.
        '''
        print_dbg(self, 'connecting...')

        if self.isConnected:
            print_dbg(self, 'already conected')
            return self # use with
        
        assert(self._evtConnect.is_set()) # no pending connect
        assert(self._evtDisconnect.is_set()) # no pending disconnect

        self._evtConnect.clear()
       
        dbuserr = None
        if 0:
            def onSuccess():
                self._evtConnect.set()

            def onError(e):
                dbuserr = e #('Connect', e.get_dbus_name(), e.get_dbus_message())
                self._evtConnect.set()

            self._ifDev.Connect(
                    reply_handler=onSuccess,
                    error_handler=onError)

        else:
            try:
                self._ifDev.Connect()
            except dbus.exceptions.DBusException as e:
                ename = e.get_dbus_name() 
                emsg = e.get_dbus_message()
                estr = '{}:{}'.format(ename, emsg) 
                                             
                if ename == 'org.bluez.Error.AlreadyConnected':
                    return self
                elif ename == 'org.bluez.Error.Failed' \
                        and emsg == 'Operation already in progress':
                    pass
                elif ename == 'org.bluez.Error.InProgress':
                    # could occur if other process started a connection
                    raise RuntimeError(estr)
                else:
                    raise RuntimeError(estr)

        if not self._evtConnect.wait(timeout):
            raise TimeoutError('Device connect timeout!')

        if dbuserr is not None:
            estr = '{}:{}'.format(dbuserr.get_dbus_name(), dbuserr.get_dbus_message()) 
            raise RuntimeError(estr) # raise in caller thread

        # while not self.isConnected:
            # print_dbg('Wait on connect')
            # time.sleep(0.5)

        print_dbg(self, 'Connected')
        return self

    def disconnect(self, timeout=TIMEOUT_SEC):
        '''Disconnect from the device.  If not disconnected within the specified
        timeout then an exception is thrown.
        '''
        if not self.isConnected:
            return 

        assert(self._evtDisconnect.is_set()) # no pending disconnect
        assert(self._evtConnect.is_set()) # no pending connect

        self._evtDisconnect.clear()
        self._ifDev.Disconnect()
        if not self._evtDisconnect.wait(timeout):
            raise TimeoutError('Timeout waiting to disconnect from device!')
        print_dbg(self, 'Disconnected')


    def _discover(self, uuid=None):
        assert(self.isConnected)
        # global _gp
        bus = _gp._bus
        manager = _gp._manager
        # bus = dbus.SystemBus()
        # manager = dbus.Interface(bus.get_object('org.bluez', '/'),
                                     # 'org.freedesktop.DBus.ObjectManager')

        objects = manager.GetManagedObjects()

        print_dbg('Discovering services for ', self)
        cpaths0 = []
        for cpath, interfaces in objects.items():
            if _IF_GATT_CHARACTERISTIC not in interfaces.keys():
                continue
            #print_dbg('    characteristic path: ', cpath)
            cpaths0.append(cpath)

        for spath, interfaces in objects.items():
            if _IF_GATT_SERVICE not in interfaces.keys():
                continue

            #vprint('spath ', spath)
            #UUID(str(self._ifProp.Get(_SERVICE_INTERFACE, 'UUID')))
            sobj = bus.get_object('org.bluez', spath)
            sprops = sobj.GetAll(_IF_GATT_SERVICE, 
                                    dbus_interface=_IF_PROPERTIES)
            suuid = UUID(sprops['UUID'])
            if suuid not in self._services:
                self._services[suuid] = GattService(suuid, self)

            #cpaths = [d for d in cpaths0 if d.startswith(spath + '/')]
            for cpath in cpaths0:
                if not cpath.startswith(spath + '/'):
                    #vprint('ignoring path ', cpath)
                    continue

                cobj = bus.get_object('org.bluez', cpath)
                cprops = cobj.GetAll(_IF_GATT_CHARACTERISTIC, 
                        dbus_interface=_IF_PROPERTIES)

                cuuid = UUID(cprops['UUID'])
                if cuuid not in self._services[suuid]._characteristics:
                    self._services[suuid]._characteristics[cuuid] = GattCharacteristic(self, cobj)

    def _getProperty(self, name):
        # Get property but wrap it in a try/except to catch if the property
        # doesn't exist
        try:
            return self._ifProp.Get(_IF_DEVICE, name)
        except dbus.exceptions.DBusException as ex:
            # Ignore error if device has no UUIDs property (i.e. might not be
            # a BLE device).
            if ex.get_dbus_name() != 'org.freedesktop.DBus.Error.InvalidArgs':
                raise ex
            return None
        

    @property
    def advertised(self):
        '''Return a list of UUIDs for services that are advertised by this
        device.
        '''
        uuids = self._getProperty('UUIDs')
        return [] if uuids is None else [UUID(str(x)) for x in uuids]

    @property
    def addr(self):
        return self._ifProp.Get(_IF_DEVICE, 'Address')

    @property
    def name(self):
        '''Return the name of this device or None if no such property'''
        return self._getProperty('Name')

    @property
    def isConnected(self):
        '''Return True if the device is connected '''
        return self._ifProp.Get(_IF_DEVICE, 'Connected')

    @property
    def isResolved(self):
        ''' is GATT services resolved '''
        return self._ifProp.Get(_IF_DEVICE, 'ServicesResolved')

    @property
    def rssi(self):
        '''Return the RSSI signal strength in decibels.'''
        return self._getProperty('RSSI')

    @property
    def _adapter(self):
        '''Return the adapter name like 'hci0' '''
        path = self._ifProp.Get(_IF_DEVICE, 'Adapter')
        return str(path).lstrip('/org/bluez/')


import signal
import atexit

class _GlobalProvider(object):
    def __init__(self):
        self._mainloop = GObject.MainLoop()
        
        # Ensure GLib's threading is initialized to support python threads, and
        # make a default mainloop that all DBus objects will inherit.  
        # These commands MUST execute before any other DBus commands!
        GObject.threads_init()
        dbus.mainloop.glib.threads_init()
        # Set the default main loop, this also MUST happen before other DBus calls.
        self._dbusloop = dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)

        # daemon=True Do not let the worker thread block exit.
        # daemon=False the worker thread will block exit, excplicity end int
        self._thread = threading.Thread(target=self._mainloop.run, daemon=True)

        # TODO check if already registred?
        # also needed ? this thread will die anyways as daemon=True
        atexit.register(self._atexit)
        signal.signal(signal.SIGINT, self._sigintexit)

    # def run(self):
        # try:
            # self._mainloop.run()
        # except queue.Empty:
            # pass

    def init(self):
        print_dbg('worker thread starting')
        self._thread.start()
        while not self._mainloop.is_running():
            print_dbg('Waiting on worker mainloop to start')
            time.sleep(0.1)

        self._bus = dbus.SystemBus()
        self._manager = dbus.Interface(self._bus.get_object('org.bluez', '/'),
                                     'org.freedesktop.DBus.ObjectManager')
    def verify(self):
        #no need to check self._thread.isAlive():
        if not self._mainloop.is_running():
            self.init()

    def exit(self, cause=''):
        # stop mainloop and let the thread die
        if self._mainloop.is_running():
            self._mainloop.quit()
            print_dbg('Stopping worker mainloop', cause)
            while self._mainloop.is_running():
                print_dbg('Waiting on worker mainloop to stop')
                time.sleep(0.1)

    def _atexit(self):
        # Note: not called when the program is killed by a signal, when a
        # Python fatal internal error is detected, or on os._exit() 
        self.exit('(atexit)')

    def _sigintexit(self, signum, frame):
        sys.exit(0) # this will call atexit
        #self.exit('(sigint)')

    def __del__(self):
        self.exit('(destructor)')


    def getDBusIfObjects(self, interface, parentpath='/org/bluez'):
        '''Return a list of all bluez DBus objects that implement the requested
        interface name and are under the specified path.  The default is to
        search devices under the root of all bluez objects.
        '''
        parentpath = parentpath.lower()
        bus = self._bus
        manager = self._manager
                  
        objects = []
        managedObjects = manager.GetManagedObjects()
        for opath, ifaces in managedObjects.items():
            if not interface in ifaces.keys():
                continue
            if not opath.lower().startswith(parentpath):
                continue
            obj = bus.get_object('org.bluez', opath)
            objects.append(obj)

        return objects

_gp = _GlobalProvider()

def adapters():
    ''' return all BLE adapters '''
    #_gp.verify() 
    return [Adapter(o) for o in _gp.getDBusIfObjects(_IF_ADAPTER)]

     



