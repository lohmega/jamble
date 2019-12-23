
import logging
from sys import stderr, stdout
import csv
from uuid import UUID

import bb_log_entry_pb2

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

logging.basicConfig(stream=stderr, level=logging.ERROR,
        format='%(levelname)s: %(message)s')
_logger = logging.getLogger(__name__)

#wrap logger to behave like print. i.e. automatic conversion to string
def print_wrn(*args):
    _logger.warning(' '.join(str(a) for a in args))

def print_err(*args):
    _logger.error(' '.join(str(a) for a in args))

def print_dbg(*args):
    _logger.debug(' '.join(str(a) for a in args))

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
                
class BlueBerryLoggerDeserializer(object):
    '''
    reads a stream of protobuf data with the format 
    <len><protobuf message of size len><len>,...
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



