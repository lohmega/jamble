
import asyncio
import logging
from sys import stderr, stdout
import csv
import json

# not needed in python >= 3.6? as default dict keeps order
from collections import OrderedDict

from bleak import BleakClient, discover
from bleak.exc import BleakError
import bb_log_entry_pb2

# temporary fix as uuid not (yet) suported in bleak MacOS backend, only str works
# from uuid import UUID
UUID = lambda x: str(x)


try:
    from google.protobuf.json_format import MessageToDict
except ImportError:
    # not in debian stretch dpkg/apt version of the pb lib
    from google.protobuf.json_format import MessageToJson
    import json
    def MessageToDict(pb):
        # super inefficient - yes!
        tmpjs = MessageToJson(pb)
        return json.loads(tmpjs)

logger = logging.getLogger(__name__)

# Command line interface stdout 
CLI_OUTPUT = False


# Command response codes.
CMD_RESP_CODES = {
    0x00 : 'SUCCESS',
    0x01 : 'ERROR', 
    0x02 : 'ERROR_PASSCODE_FORMAT',
    0x03 : 'ERROR_COMPASS_NO_MOTION',
    0x04 : 'ERROR_COMPASS_LARGE_MAGNET',
    0x05 : 'ERROR_ACCESS_DENIED',  # Password protected (no check if cmd is valid)
    0x06 : 'ERROR_UNKNOWN_CMD',
    0x80 : 'COMPLETE' ,
    0x81 : 'ERROR_CALIBRATION',
    0x82 : 'PROGRESS'
}
    
class PW_STATUS():
    INIT       = 0x00 
    UNVERIFIED = 0x01
    VERIFIED   = 0x02 
    DISABLED   = 0x03

PW_STATUS_TRANSLATE = {
    0x00 : 'init', #'the unit has not been configured yet',
    0x01 : 'unverified', #'the correct password has not been entered yet',
    0x02 : 'verified', #'the correct password has been entered',
    0x03 : 'disabled', #'no password is needed',
}

def pw_status_to_str(rc):
    return PW_STATUS_TRANSLATE[rc]

def _bbuuid(n):
    base='c9f6{:04x}-9f9b-fba4-5847-7fd701bf59f2'
    return UUID(base.format(n))

# GATT Services and Characteristics UUIDS
class UUIDS():
    # Log service
    S_LOG = _bbuuid(0x002)
    # Real time data characteristic
    C_SENSORS_RTD = _bbuuid(0x0022)
    # Stored log characteristic
    C_SENSORS_LOG = _bbuuid(0x0021)
    # Command TX characteristic
    C_CMD_TX = _bbuuid(0x001a)
    # Command RX characteristic (as notification)
    C_CMD_RX = _bbuuid(0x0023)
    # uint32. log on/off
    C_CFG_LOG_ENABLE = _bbuuid(0x00)
    # uint32 bitfield 
    C_CFG_SENSOR_ENABLE = _bbuuid(0x01)
    # uint32 log interval in seconds
    C_CFG_INTERVAL = _bbuuid(0x02)



TXT_COL_WIDTH = 10

class _DataField():
    def __init__(self, enmask, pbname, symbol='', unit='',
            tounit=None, alias=None,  subfields=None, txtfmt='4.3f'):
        self.enmask = enmask
        self.pbname = pbname
        self.symbol = symbol
        self.unit = unit
        self.tounit = tounit
        self.alias = alias
        self.txtfmt = '{{0: {}}}'.format(txtfmt)
        if subfields:
            self._colname = ['{}_{}'.format(self.symbol, x) for x in subfields]
        else:
            self._colname = [self.symbol]
    
    def isSensor(self):
        return self.enmask is not None

    @property
    def cliName(self):
        return self.apiName
        
    @property
    def apiName(self):
        if self.alias:
            return self.alias
        else:
            return self.pbname
    @property
    def colNames(self):
        return self._colname
        
# Names used in iOS app csv output:
#     Unix time stamp,
#     Acceleration x (m/s²),
#     Acceleration y (m/s²),
#     Acceleration z (m/s²),
#     Magnetic field x (µT),
#     Magnetic field y (µT),
#     Magnetic field z (µT),
#     Rotation rate x (°/s),
#     Rotation rate y (°/s),
#     Rotation rate z (°/s),
#     Illuminance (lux),
#     Pressure (hPa),
#     Rel. humidity (%),
#     Temperature (C),
#     UV index,
#     Battery voltage (V)
_dfList = [
    _DataField(0x0001, 'pressure',     'p',   'hPa',   lambda x: x/100.0),
    _DataField(0x0002, 'rh',           'rh',  '%',     lambda x: x/10.0, 'humid'), # humidity
    _DataField(0x0004, 'temperature',  't',   'C',     lambda x: x/1000.0, 'temp'),
    _DataField(0x0008, 'compass',      'm',   'uT',    lambda x: x*4915.0/32768.0, subfields=('x','y','z')),
    _DataField(0x0010, 'accelerometer','a',   'm/s^2', lambda x: x*2.0*9.81/32768.0, 'accel', subfields=('x','y','z')),
    _DataField(0x0020, 'gyro',         'g',   'dps',   lambda x: x*250.0/32768.0, subfields=('x','y','z')),
    _DataField(0x0040, 'lux',          'L',   'lux',   lambda x: x/1000.0),#  illuminance
    _DataField(0x0100, 'uvi',          'UVi', '',      lambda x: x/1000.0),
    _DataField(0x0200, 'battery_mv',   'bat', 'V',     lambda x: x/1000.0, 'batvolt'),
    # texhnically not sensors, but use same class.
    _DataField(None, 'timestamp', 'TS', 's', lambda x: float(x), txtfmt='7.0f'),
    _DataField(None, 'gpio0_mv', 'gp0', 'mV', lambda x: x*1.0),
    _DataField(None, 'gpio1_mv', 'gp1', 'mV', lambda x: x*1.0)
]

_sensors = {}
_dfByPbName = {}
_dfByColName = {}
for df in _dfList:
    if df.isSensor():
        _sensors[df.apiName] = df
    _dfByPbName[df.pbname] = df
    for colName in df.colNames:
        _dfByColName[colName] = df

SENSORS = _sensors
                
class BlueBerryDeserializer(object):
    '''
    reads a stream of protobuf data with the format 
    <len><protobuf message of size len><len>,...

    yes- should probably be changed to one class for
    each format that inherit common code. TODO
    '''
    def __init__(self, ofile=stdout, ofmt='txt', raw=False):
        self._pb = bb_log_entry_pb2.bb_log_entry() # protobuf message
        self._bytes = bytearray()
        self._entries = []
        self._ofile = ofile
        self._raw = raw
        self._prevKeySet = None
        self._msgCount = 0
        
        if ofmt == 'txt':
            self._write = self._write_txt
        elif ofmt == 'csv':
            self._csvw = csv.writer(ofile)
            self._write = self._write_csv
        elif ofmt == 'json':
            self._write = self._write_csv
            self._csvw = csv.writer(ofile)
        else:
            raise ValueError('Unknown fmt format')

    @property
    def nentries(self):
        return self._msgCount

    def _MessageToOrderedDict(self, pb, columnize=False):
        ''' 
        mimic name from prtobuf lib.
        assumption: all values can be converted to float or list of floats.
        if the protobuf format change, the built in MessageToDict() function
        can be used. requres python > 3.6 (?) where the default dict heaviour 
        rememebers insertion order.
        '''
        od = OrderedDict()
        for descr in pb.DESCRIPTOR.fields:
            df = _dfByPbName[descr.name]
            val = getattr(pb, descr.name)
            if descr.label == descr.LABEL_REPEATED:
                # HasField() do not work on repeated, use len instead. hack
                if not len(val): 
                    continue

                if columnize:
                    for i in range(0,len(val)):
                        name = df.colNames[i]
                        od[name] = val[i]
                else:
                    name = df.colNames[0]
                    od[name] = list(val) #[x for x in val]
            else:
                if not pb.HasField(descr.name):
                    continue
                name = df.colNames[0]
                od[name] = val
        return od

    def _write_csv(self, odmsg):
        keys = odmsg.keys()
        keySet = set(keys)
        if self._prevKeySet != keySet:
            self._prevKeySet = keySet
            # units = []
            # names = []
            # for colname in keys:
                # name = colname.ljust(TXT_COL_WIDTH)
                # names.append(name)

                # df = _dfByColName[colname]
                # unit = '({})'.format(df.unit).ljust(TXT_COL_WIDTH)
                # units.append(unit)
            self._csvw.writerow(keys)
        if self._raw: 
            vals = odmsg.values()
        else:
            vals = [_dfByColName[k].tounit(v) for k, v in odmsg.items()]
        self._csvw.writerow(vals)

    def _write_json(self, odmsg):
        keys = odmsg.keys()
        keySet = set(keys)
        if self._prevKeySet != keySet:
            self._prevKeySet = keySet
            json.dump(keys, fp=self._ofile)
        if self._raw: 
            vals = odmsg.values()
        else:
            vals = [_dfByColName[k].tounit(v) for k, v in odmsg.items()]
        json.dump(vals, fp=self._ofile)

    def _write_txt(self, odmsg):
        '''
        pretty columnized text for terminal output
        '''

        keys = odmsg.keys()
        keySet = set(keys)
        if self._prevKeySet != keySet:
            if self._prevKeySet is not None:
                print('', file=self._ofile) # extra delimiter
            self._prevKeySet = keySet

            units = []
            names = []
            for colname in keys:
                name = colname.ljust(TXT_COL_WIDTH)
                names.append(name)

                df = _dfByColName[colname]
                unit = '({})'.format(df.unit).ljust(TXT_COL_WIDTH)
                units.append(unit)

            print(*names, sep='', file=self._ofile)
            print(*units, sep='', file=self._ofile)

        vals = []
        for colname, value in odmsg.items():
            df = _dfByColName[colname]
            v = value if self._raw else df.tounit(value)
            s = df.txtfmt.format(v)
            vals.append(s.ljust(TXT_COL_WIDTH))

        print(*vals, sep='', file=self._ofile)

    def _isLastMsg(self, odm):
        ''' end of log "EOF" is a empty messagge with only the required
        timestamp field '''
        if len(odm) == 1:
            if 'TS' not in odm: 
                logger.warning('unexpected last msg keys {}'.format(odm.keys()))
            return True
        else:
            return False


    def putb(self, chunk): 
        ''' put chunk of bytes to be deserialize into protobuf messages'''
        self._bytes.extend(chunk)

        while True:
            if not self._bytes:
                return False 

            msgSize = self._bytes[0] 
            if len(self._bytes) -1 < msgSize : # exclued "header"
                return False

            self._pb.Clear() 
            msg = self._pb.FromString(self._bytes[1:msgSize + 1])
            odmsg = self._MessageToOrderedDict(msg, columnize=True)
            if self._isLastMsg(odmsg):
                return True

            self._write(odmsg)
            self._bytes = self._bytes[msgSize + 1:] # pop
            self._msgCount += 1


class BlueBerryClient(BleakClient):

    async def write_u32(self, cuuid, val):
        val = int(val)
        data = val.to_bytes(4, byteorder='little', signed=False)
        data = bytearray(data) # fixes bug(!?) in txdbus ver 1.1.1 
        await self.write_gatt_char(cuuid, data, response=True)

    async def read_u32(self, cuuid):
        ba = await self.read_gatt_char(cuuid)
        assert(len(ba) == 4)
        return int.from_bytes(ba, byteorder='little', signed=False)

    async def cmd(self, txdata, rxsize=None):
        ''' first byte in txdata is the cmd id '''
        txuuid = UUIDS.C_CMD_TX
        rxuuid = UUIDS.C_CMD_RX 

        txdata = bytearray(txdata)
        rxdata = bytearray()
        if not rxsize:
            return await self.write_gatt_char(txuuid, txdata, response=True)

        event = asyncio.Event()
        def response_handler(sender, data):
            # sender is str. should be uuid!?
            if sender !=  str(rxuuid):
                logger.warning('unexpected notify response \
                        from {} expected {}'.format(sender, rxuuid))
                return
            rxdata.extend(data)
            logger.debug('cmd RXD:{}'.format(data))
            event.set()

        await self.start_notify(rxuuid, response_handler)
        await self.write_gatt_char(txuuid, txdata, response=True)
        await event.wait()
        await self.stop_notify(rxuuid)
        await asyncio.sleep(2) # TODO remove!?

        assert(len(rxdata) == rxsize)

        if rxsize and rxdata[0] != (txdata[0] | 0x80):
            raise RuntimeError('Unexpected cmd id in respone {}'.format(rxdata))

        return rxdata

    async def pw_write(self, s):
        ''' if pw_status is "init", set new password, 
        if pw_status="unverified", unlock device.

        Password must be 8 chars and ascii only
        '''
        data = bytearray([0x06]) # 0x06 = command code 
        assert(len(s) == 8)
        data.extend(s)
        await self.cmd(data)

    
    async def pw_status(self):
        ''' password status '''
        rsp = await self.cmd([0x07], 2)
        return rsp[1]


async def _connect(address, **kwargs):

    bbc = BlueBerryClient(address, loop=kwargs.get('loop'))

    try:
        await bbc.connect()
        await bbc.is_connected() # needed?
    except BleakError as e:
        # provide a better error message then dual thread backtrace...
        raise RuntimeError('Failed to connect. Device exitst?', e)

    return bbc

async def _connect_unlock(address, password=None, **kwargs):
    '''
    connect and unlock device if it requires a password
    '''

    bbc = await _connect(address, **kwargs)

    rc = await bbc.pw_status()
    if rc == PW_STATUS.UNVERIFIED: 
        if password is None:
            await bbc.disconnect()
            raise ValueError('Password needed for this device and operation')
        await bbc.pw_write(password)
    else:
        pass # password not needed for this device

    return bbc

async def scan(timeout=None, **kwargs):
    devices = []
    candidates = await discover()
    for d in candidates:
        match = False
        if 'uuids' in d.metadata:
            advertised = d.metadata['uuids']
            suuid = str(UUIDS.S_LOG)
            if suuid.lower() in advertised or suuid.upper() in advertised:
                match = True
        elif 'BlueBerry' in d.name:
            logger.warning('no mathcing service uuid but matching name {}'.format(d))
            match = True
        else:
            logger.debug('ignoring device={}'.format(d))

        if match:
            logger.debug('details={}, metadata={}'.format(d.details, d.metadata))
            if CLI_OUTPUT:
                print(d.address, '  ', d.rssi, 'dBm', '  ', d.name)
            devices.append(d)

    return devices


async def blink(**kwargs):
    n = kwargs.get('num', 0)
    assert(n > 0)
    bbc = await _connect(**kwargs)
    while n:
        await bbc.cmd([0x01])
        n = n - 1
        if n > 0:
            await asyncio.sleep(1)

    await bbc.disconnect()

async def config_read(address, **kwargs):

    def to_onoff(x):
        return 'on' if x else 'off'

    conf = OrderedDict()
    bbc = await _connect(**kwargs)

    val = await bbc.read_u32(UUIDS.C_CFG_LOG_ENABLE)
    conf['logging'] = to_onoff(val)

    val = await bbc.read_u32(UUIDS.C_CFG_INTERVAL)
    conf['interval'] = val

    val = await bbc.pw_status()
    conf['pwstatus'] = '{} ({})'.format(val, pw_status_to_str(val))

    enbits = await bbc.read_u32(UUIDS.C_CFG_SENSOR_ENABLE)
    await bbc.disconnect()

    for name, s in SENSORS.items():
        conf[s.apiName] = to_onoff(s.enmask & enbits)

    if CLI_OUTPUT:
        for k, v in conf.items(): 
            print('  ', k.ljust(10), ':', v)

    return conf

async def config_write(address, **kwargs):
    setMask = 0
    clrMask = 0

    # sanity check all params before write
    for k, v in kwargs.items():
        if v is None:
            continue

        if k in SENSORS:
            enmask = SENSORS[k].enmask 
            if v:
                setMask |= enmask
            else:
                clrMask |= enmask
        else:
            logger.debug('Ignoring unknown conifg field "{}"'.format(k))
        

    bbc = await _connect_unlock(address, **kwargs)

    logging = kwargs.get('logging')
    if logging is not None:
        await bbc.write_u32(UUIDS.C_CFG_LOG_ENABLE, logging)

    interval = kwargs.get('interval')
    if interval is not None:
        await bbc.write_u32(UUIDS.C_CFG_INTERVAL, interval)

    cuuid = UUIDS.C_CFG_SENSOR_ENABLE
    if setMask or clrMask:
        enMaskOld = await bbc.read_u32(cuuid)
        enMaskNew = (enMaskOld & ~clrMask) | setMask
        await bbc.write_u32(cuuid, enMaskNew)

        logger.debug('enabled sensors \
                old=0x{:04X}, new=0x{:04X}'.format(enMaskOld, enMaskNew))

    await bbc.disconnect()


async def set_password(address, password, **kwargs):
    if password is None:
        raise ValueError('No new password provided')

    bbc = await _connect(address, **kwargs)

    rc = await bbc.pw_status()
    if rc == PW_STATUS.INIT:
        await bbc.pw_write(password)
        logger.debug('Password protection enabled')
    else:
        await bbc.disconnect()
        raise RuntimeError('Device not in init mode. Please power cycle device')

    await bbc.disconnect()
    
async def fetch(address, ofile=None, rtd=False, fmt='txt', num=None, **kwargs):

    if rtd:
        uid = UUIDS.C_SENSORS_RTD
    else:
        uid = UUIDS.C_SENSORS_LOG

    if ofile is None:
        ofile = stdout
    else:
        ofile = open(ofile, 'w')
        #TODO open file, check exists etc

    bbc = await _connect_unlock(address, **kwargs)

    bbd = BlueBerryDeserializer(ofmt=fmt, ofile=ofile)
    nentries = num
    event = asyncio.Event()
    def response_handler(sender, data):
        if str(sender).upper() !=  str(uid).upper():
            logger.warning('unexpected notify response \
                    from {} expected {}'.format(sender, uid))
            return

        done = bbd.putb(data)
        if not done and nentries is not None:
            done = bbd.nentries >= nentries
        if done:
            logger.debug('End of log. Fetched {} entries'.format(bbd.nentries))
            event.set()


    if rtd:    
        enabled = await bbc.read_u32(UUIDS.C_CFG_LOG_ENABLE)
        if not enabled:
            await bbc.disconnect()
            raise RuntimeError('logging must be enabled for real-time data (rtd)')

    await bbc.start_notify(uid, response_handler)
    await event.wait()
    await bbc.stop_notify(uid)

    await bbc.disconnect()

