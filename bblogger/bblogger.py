
from uuid import UUID
from time import sleep
import sys
import bluetoothle as ble
import bb_log_entry_pb2
from pprint import pprint
import argparse
import logging
import csv
import pprint
# not needed in python >= 3.6? as default dict keeps order
from collections import OrderedDict

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

logging.basicConfig(stream=sys.stderr, level=logging.ERROR,
        format='%(levelname)s: %(message)s')
_logger = logging.getLogger(__name__)

#wrap logger to behave like print. i.e. automatic conversion to string
def print_wrn(*args):
    _logger.warning(' '.join(str(a) for a in args))

def print_err(*args):
    _logger.error(' '.join(str(a) for a in args))

def print_dbg(*args):
    _logger.debug(' '.join(str(a) for a in args))


def _bbuuid(n):
    base='c9f6{:04x}-9f9b-fba4-5847-7fd701bf59f2'
    return UUID(base.format(n))

UUID_LOG_SERVICE = _bbuuid(0x002)
TXT_COL_WIDTH = 10

class _DataField(object):
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

                
class BlueBerryLoggerDeserializer(object):
    '''
    reads a stream of protobuf data with the format 
    <len><protobuf message of size len><len>,...
    '''
    def __init__(self, ofile=sys.stdout, ofmt='txt', raw=False):
        self._pb = bb_log_entry_pb2.bb_log_entry() # protobuf message
        self._bytes = bytearray()
        self._entries = []
        self._ofile = ofile
        self._raw = raw
        self._prevKeySet = None
        self._msgCount = 0
        
        if ofmt == 'txt':
            self._outFmt = self._outFmtTxt
        elif ofmt == 'csv':
            self._csvw = csv.writer(ofile)
            self._outFmt = self._outFmtCsv
        else:
            raise ValueError('Unknown fmt format')

    @property
    def msgCount(self):
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

    def _outFmtCsv(self, odmsg):
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


    def _outFmtTxt(self, odmsg):
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
                print_wrn('unexpected last msg keys:', odm.keys())
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

            self._outFmt(odmsg)
            self._bytes = self._bytes[msgSize + 1:] # pop
            self._msgCount += 1


class CmdTxData(bytearray):
    def __init__(self, cmdid, data=None):
        #super.__init__()
        self.data = data
        self.cmdid = cmdid

    @property
    def cmdid(self):
        return self[0]

    @cmdid.setter
    def cmdid(self, cmdid):
        self[0] = cmdid

    @property
    def data(self):
        return self[1:]

    @data.setter
    def data(self, data):
        ''' :param data: data is cleared if None'''
        # this could be more efficient, but no need
        del self[1:] # 
        if data is None:
            return
        if isinstance(data, int):
            data = [data]
        self.extend(data)


_CMD_RESP_CODES = {
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
    
class CmdRxData(bytearray):

    @property
    def cmdid(self):
        return self[0] & ~0x80

    @property
    def statuscode(self):
        ''' only present for some commands ''' 

    @property
    def statusstr(self):
        ''' only present for some commands ''' 
        scode = self[1]
        if scode == 0x00:
            return 'SUCCESS'

        elif scode == 0x01:
            rc = self[2]
            if rc in _CMD_RESP_CODES:
                return _CMD_RESP_CODES[rc]
            return 'UNKNOWN_RC_0x{:02X}'.format(rc)
        else:
            return 'UNKNOWN_STATUS_0x{:02X}'.format(scode)

PW_STATUS_INIT       = 0x00 
PW_STATUS_UNVERIFIED = 0x01
PW_STATUS_VERIFIED   = 0x02 
PW_STATUS_DISABLED   = 0x03

class BlueBerryLogger(object):

    def __init__(self, bleDev, addr=None):
        self._bleDev = bleDev
        
    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exctype, excval, traceback):
        self._bleDev.disconnect()
        return False

    def connect(self):
        # TODO better error handling when using a disconnected device
        self._bleDev.connect()
        s = self._bleDev.service(UUID_LOG_SERVICE)

        self._cmdtx = s.characteristic(_bbuuid(0x001a))
        self._cmdrx = s.characteristic(_bbuuid(0x0023))
        self._cRtData = s.characteristic(_bbuuid(0x0022))
        self._cLogData = s.characteristic(_bbuuid(0x0021))

        self._cLogEnable = s.characteristic(_bbuuid(0x00))
        self._cSensEnable = s.characteristic(_bbuuid(0x01))
        self._cInterval = s.characteristic(_bbuuid(0x02))

        self._service = s
        print_dbg('logEP', pprint.pformat(self._cLogData._properties()))


    def disconnect(self):
        self._bleDev.disconnect()

    @property
    def _logging(self):
        return bool(self._cLogEnable.read(ctype='uint32'))

    @_logging.setter
    def _logging(self, enable):
        self._cLogEnable.write(enable, ctype='uint32')

    @property
    def _sensorflags(self):
        return self._cSensEnable.read(ctype='uint32')
        
    @_sensorflags.setter
    def _sensorflags(self, flags):
        self._cSensEnable.write(flags, ctype='uint32')

    @property
    def _interval(self):
        return self._cInterval.read(ctype='uint32')

    @_interval.setter
    def _interval(self, sec):
        self._cInterval.write(sec, ctype='uint32')

    @property
    def address(self): 
        return self._bleDev.address

    @property
    def name(self): 
        return self._bleDev.name
    
    def _docmdtxrx(self, txdata, rxsize):
        with self._cmdrx.notifications as reply:
            self._cmdtx.write(txdata, ctype='uint8')
            rxdata = reply.read(rxsize, timeout=5)

        if rxsize and rxdata[0] != (txdata[0] | 0x80):
            raise RuntimeError('Unexpected cmd id in respone')

        return rxdata

    def blinkLED(self):
        self._cmdtx.write(0x01, ctype='uint8')
        sleep(2) # blocking call

    def config_write(self, **kwargs):
        logging = None
        interval = None
        setMask = 0
        clrMask = 0

        # sanity check all params before write
        for k, v in kwargs.items():
            if k == 'logging':
                logging = bool(v)
            elif k == 'interval':
                interval = int(v)

            elif k in _sensors:
                if v:
                    setMask |= _sensors[k].enmask
                else:
                    clrMask |= _sensors[k].enmask
            else:
                raise ValueError('Unknown conifg field "{}"'.format(k))
            
        if logging is not None:
            self._logging = logging

        if interval is not None:
            self._interval = interval

        if setMask or clrMask:
            enMaskOld = self._cSensEnable.read(ctype='uint32')
            enMaskNew = (enMaskOld & ~clrMask) | setMask
            print_dbg(self, 
                    'enabled sensors old=0x{:04X}, new=0x{:04X}'.format(enMaskOld, enMaskNew))
            self._cSensEnable.write(enMaskNew, ctype='uint32')

    def config_read(self):
        conf = {}
        enbits = self._cSensEnable.read(ctype='uint32')
        
        for s in _dfList:
            if not s.isSensor():
                continue
            conf[s.apiName] = True if (s.enmask & enbits) else False
                
        conf['logging'] = self._logging
        conf['interval'] = self._interval
        n, s = self.pw_status() 
        conf['pwstatus'] = s

        return conf 


    def fetch(self, rtd=False, nentries=None, ofile=sys.stdout, ofmt='txt'):
        '''
        :param rtd: fetch realtime sensor data if true, else fetch sensor data
              stord on device.

        '''

        # realtime data not readable if logging is off/disabled
        if rtd:
            if not self._logging:
                print_err('can not read realtime data while logging disabled.')
                return
            c = self._cLogData
        else:
            c = self._cRtData

        bbld = BlueBerryLoggerDeserializer(ofmt=ofmt, ofile=ofile)

        with c.notifications as pbdata:
            while True:
                chunk = pbdata.read(timeout=10)
                haveEOF = bbld.putb(chunk)
                if haveEOF:
                    print_dbg('End of log. Fetched', bbld.msgCount, 'entries')
                    break
                elif nentries is not None:
                    if bbld.msgCount >= nentries:
                        break

    def pw_set(self, s):
        ''' if pw_status is "init", set new password, 
        if pw_status="unverified", unlock device
        '''
        emsg = 'Password must be 8 chars and ascii only'
        try:
            data = bytearray(s.encode('ascii'))
        except UnicodeDecodeError:
            raise TypeError(emsg)
        if len(data) != 8:
            raise TypeError(emsg)
        data.insert(0, 0x06) ## 0x06 = command code 
        self._cmdtx.write(data)
        #rsp = self._docmdtxrx(data, 0)


    def pw_unlock(self, pw):
        self.pw_set(pw)

    def pw_required(self):
        ''' is password requried for this device''' 
        rc, s = self.pw_status()
        return bool(rc == PW_STATUS_UNVERIFIED)
    
    def pw_status(self):
        ''' password status '''
        rsp = self._docmdtxrx([0x07], 2)
        rctranslate = {
            0x00 : 'init', #'the unit has not been configured yet',
            0x01 : 'unverified', #'the correct password has not been entered yet',
            0x02 : 'verified', #'the correct password has been entered',
            0x03 : 'disabled', #'no password is needed',
        }
        rc = rsp[1]
        return rc, rctranslate[rc]

def versions():
    return ble.versions()

def devices(address=None, cached=False, output=None):
    adapter = ble.Adapter()
    if address is not None:
        #address = ble.Address(address)
        def devicefilter(dev):
            #print(dev.address, address, dev.address == address)
            return dev.address == address
    else:
        def devicefilter(dev):
            print_dbg('----- DEVICE ----\n',
                    pprint.pformat(dev._properties(), indent=4))
            return UUID_LOG_SERVICE in dev.advertised

    devs = adapter.scan(devicefilter, cached=cached)
    return [BlueBerryLogger(dev) for dev in devs]

