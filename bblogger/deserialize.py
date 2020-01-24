import logging
import csv
import json
from platform import system

from sys import stderr, stdout

# not needed in python >= 3.6? as default dict keeps order
from collections import OrderedDict

try:
    from google.protobuf.json_format import MessageToDict
except ImportError:
    # not in debian stretch dpkg/apt version of the pb lib
    from google.protobuf.json_format import MessageToJson

    def MessageToDict(pb):
        # super inefficient - yes!
        tmpjs = MessageToJson(pb)
        return json.loads(tmpjs)


from bblogger import bb_log_entry_pb2

logger = logging.getLogger(__name__)

TXT_COL_WIDTH = 10


class _DataField:
    def __init__(
        self,
        enmask,
        pbname,
        symbol="",
        unit="",
        tounit=None,
        alias=None,
        subfields=None,
        txtfmt="4.3f",
    ):
        self.enmask = enmask
        self.pbname = pbname
        self.symbol = symbol
        self.unit = unit
        self.tounit = tounit
        self.alias = alias
        self.txtfmt = "{{0: {}}}".format(txtfmt)
        if subfields:
            self._colname = ["{}_{}".format(self.symbol, x) for x in subfields]
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
    _DataField(0x0001, "pressure", "p", "hPa", lambda x: x / 100.0),
    _DataField(0x0002, "rh", "rh", "%", lambda x: x / 10.0, "humid"),  # humidity
    _DataField(0x0004, "temperature", "t", "C", lambda x: x / 1000.0, "temp"),
    _DataField(
        0x0008,
        "compass",
        "m",
        "uT",
        lambda x: x * 4915.0 / 32768.0,
        subfields=("x", "y", "z"),
    ),
    _DataField(
        0x0010,
        "accelerometer",
        "a",
        "m/s^2",
        lambda x: x * 2.0 * 9.81 / 32768.0,
        "accel",
        subfields=("x", "y", "z"),
    ),
    _DataField(
        0x0020,
        "gyro",
        "g",
        "dps",
        lambda x: x * 250.0 / 32768.0,
        subfields=("x", "y", "z"),
    ),
    _DataField(0x0040, "lux", "L", "lux", lambda x: x / 1000.0),  #  illuminance
    _DataField(0x0100, "uvi", "UVi", "", lambda x: x / 1000.0),
    _DataField(0x0200, "battery_mv", "bat", "V", lambda x: x / 1000.0, "batvolt"),
    # texhnically not sensors, but use same class.
    _DataField(None, "timestamp", "TS", "s", lambda x: float(x), txtfmt="7.0f"),
    _DataField(None, "gpio0_mv", "gp0", "mV", lambda x: x * 1.0),
    _DataField(None, "gpio1_mv", "gp1", "mV", lambda x: x * 1.0),
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
# FIELDS = _dfList


class BlueBerryDeserializer:
    """
    reads a stream of protobuf data with the format 
    <len><protobuf message of size len><len>,...

    yes- should probably be changed to one class for
    each format that inherit common code. TODO
    """

    def __init__(self, ofile=stdout, ofmt="txt", raw=False):
        self._pb = bb_log_entry_pb2.bb_log_entry()  # protobuf message
        self._bytes = bytearray()
        self._entries = []
        self._ofile = ofile
        self._raw = raw
        self._prevKeySet = None
        self._msgCount = 0
        self._data = []

        self._fmt = ofmt

        if ofmt is None:
            self._append_fmt = None
        if ofmt == "txt":
            self._append_fmt = self._append_txt
        elif ofmt == "csv":
            self._csvw = csv.writer(ofile)
            self._append_fmt = self._append_csv
        elif ofmt == "json":
            self._append_fmt = self._append_json
        else:
            raise ValueError("Unknown fmt format")

    @property
    def nentries(self):
        return self._msgCount

    def _MessageToOrderedDict(self, pb, columnize=False):
        """ 
        mimic name from protobuf lib.
        assumption: all values can be converted to float or list of floats.
        if the protobuf format change, the built in MessageToDict() function
        can be used. requres python > 3.6 (?) where the default dict heaviour 
        rememebers insertion order.
        """
        od = OrderedDict()
        for descr in pb.DESCRIPTOR.fields:
            df = _dfByPbName[descr.name]
            val = getattr(pb, descr.name)
            if descr.label == descr.LABEL_REPEATED:
                # HasField() do not work on repeated, use len instead. hack
                if not len(val):
                    continue

                if columnize:
                    for i in range(0, len(val)):
                        name = df.colNames[i]
                        od[name] = val[i]
                else:
                    name = df.colNames[0]
                    od[name] = list(val)  # [x for x in val]
            else:
                if not pb.HasField(descr.name):
                    continue
                name = df.colNames[0]
                od[name] = val
        return od

    def _append_txt(self, keys, vals, add_header):
        """
        pretty columnized text for terminal output.
        will not look pretty if raw values are used
        """
        if add_header:
            if add_header > 1:
                print("", file=self._ofile)  # extra delimiter

            units = []
            names = []
            for k in keys:
                name = k.ljust(TXT_COL_WIDTH)
                names.append(name)

                df = _dfByColName[k]
                unit = "({})".format(df.unit).ljust(TXT_COL_WIDTH)
                units.append(unit)

            print(*names, sep="", file=self._ofile)
            print(*units, sep="", file=self._ofile)

        svals = [None] * len(keys)
        for i, k in enumerate(keys):
            df = _dfByColName[k]
            s = df.txtfmt.format(vals[i])
            svals[i] = s.ljust(TXT_COL_WIDTH)

        print(*svals, sep="", file=self._ofile)

    def _append_csv(self, keys, vals, add_header):
        if add_header:
            self._csvw.writerow(keys)
        self._csvw.writerow(vals)

    def _append_json(self, keys, vals, add_header):
        # TODO json start and end "{}" is missing
        if add_header:
            json.dump(keys, fp=self._ofile)
        json.dump(vals, fp=self._ofile)

    def _append(self, odmsg):
        keys = odmsg.keys()

        keySet = set(keys)
        if self._prevKeySet != keySet:
            if self._prevKeySet is not None:
                add_header = 1
            else:
                add_header = 2
            self._prevKeySet = keySet
        else:
            add_header = 0

        if self._raw:
            vals = odmsg.values()
        else:
            vals = [_dfByColName[k].tounit(v) for k, v in odmsg.items()]

        assert len(keys) == len(vals)

        self._data.append(vals)

        if self._append_fmt:
            self._append_fmt(keys, vals, add_header)

    def _is_last_msg(self, odm):
        """ end of log "EOF" is a empty messagge with only the required
        timestamp field """
        if len(odm) == 1:
            if "TS" not in odm:
                logger.warning("unexpected last msg keys {}".format(odm.keys()))
            return True
        else:
            return False

    def putb(self, chunk):
        """ put chunk of bytes to be deserialize into protobuf messages"""
        self._bytes.extend(chunk)

        while True:
            if not self._bytes:
                return False

            msgSize = self._bytes[0]
            if len(self._bytes) - 1 < msgSize:  # exclued "header"
                return False

            self._pb.Clear()
            msg = self._pb.FromString(self._bytes[1 : msgSize + 1])
            odmsg = self._MessageToOrderedDict(msg, columnize=True)
            if self._is_last_msg(odmsg):
                return True

            self._append(odmsg)

            self._bytes = self._bytes[msgSize + 1 :]  # pop
            self._msgCount += 1

