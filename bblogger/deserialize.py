import logging
import csv
import json
from platform import system

from sys import stderr, stdout

# not needed in python >= 3.6? as default dict keeps order
from collections import OrderedDict, deque

try:
    from google.protobuf.json_format import MessageToDict
except ImportError:
    # not in debian stretch dpkg/apt version of the pb lib
    from google.protobuf.json_format import MessageToJson

    def MessageToDict(pb):
        # super inefficient - yes!
        tmpjs = MessageToJson(pb)
        return json.loads(tmpjs)
from google.protobuf.message import DecodeError

from bblogger import bb_log_entry_pb2
from bblogger.defs import BlueBerryLogEntryFields

logger = logging.getLogger(__name__)

TXT_COL_WIDTH = 10


_COLNAME_TO_FLD = {}
_PBNAME_TO_FLD = {}

for x in BlueBerryLogEntryFields:
    fld = x.value
    _PBNAME_TO_FLD[fld.pbname] = fld

    for colname in fld.colnames:
        _COLNAME_TO_FLD[colname] = fld



class BlueBerryDeserializer:
    """
    reads a stream of protobuf data with the format 
    <len><protobuf message of size len><len>,...

    yes- should probably be changed to one class for
    each format that inherit common code. TODO
    """

    def __init__(self, ofile=stdout, ofmt="txt", raw=False, msg_hist_len=32):
        self._pb = bb_log_entry_pb2.bb_log_entry()  # protobuf message
        self._bbuf = bytearray()
        self._ofile = ofile
        self._raw = raw
        self._prev_keyset = None
        self._msg_hist = deque(maxlen=msg_hist_len)
        self._msg_count = 0

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
        return self._msg_count

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
            fld = _PBNAME_TO_FLD[descr.name]
            val = getattr(pb, descr.name)
            if descr.label == descr.LABEL_REPEATED:
                # HasField() do not work on repeated, use len instead. hack
                if not len(val):
                    continue

                if columnize:
                    for i in range(0, len(val)):
                        name = fld.colnames[i]
                        od[name] = val[i]
                else:
                    name = fld.colnames[0]
                    od[name] = list(val)  # [x for x in val]
            else:
                if not pb.HasField(descr.name):
                    continue
                name = fld.colnames[0]
                od[name] = val
        return od

    def _dump_msg_hist(self, max_len=4):
        print("==== MSG HISTORY DUMP (count, size, bytes, err) ====", file=stderr)

        for entry in self._msg_hist:
            msg_count, msg_size, msg_bytes, err_str = entry
            print("{:04d}".format(msg_count),
                  "{:04d}".format(msg_size),
                    msg_bytes.hex(),
                    "'{}'".format(err_str),
                    sep=",",
                    file=stderr)

        print("==== END: MSG HISTORY ====", file=stderr)


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

                fld = _COLNAME_TO_FLD[k]
                unit = "({})".format(fld.unit).ljust(TXT_COL_WIDTH)
                units.append(unit)

            print(*names, sep="", file=self._ofile)
            print(*units, sep="", file=self._ofile)

        svals = [None] * len(keys)
        for i, k in enumerate(keys):
            fld = _COLNAME_TO_FLD[k]
            s = fld.txtfmt.format(vals[i])
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

    def _did_keys_change(self, keys):
        """ 
        compare keys/field names from previous message and check if changed.
        side effect: new keys stored
        """

        keyset = set(keys)
        if self._prev_keyset != keyset:
            if self._prev_keyset is not None:
                add_header = 1
            else:
                add_header = 2
            self._prev_keyset = keyset
        else:
            add_header = 0

        return add_header

    def _append(self, odmsg):
        keys = odmsg.keys()

        add_header = self._did_keys_change(keys)

        if self._raw:
            vals = odmsg.values()
        else:
            vals = [_COLNAME_TO_FLD[k].tounit(v) for k, v in odmsg.items()]

        assert len(keys) == len(vals)

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
        self._bbuf.extend(chunk)

        while True:
            if not self._bbuf:
                return False

            msg_size = self._bbuf[0]
            if len(self._bbuf) - 1 < msg_size:  # exclued "header"
                return False

            self._pb.Clear()
            msg_bytes = self._bbuf[1 : msg_size + 1]
            err = None
            try:
                pb_msg = self._pb.FromString(msg_bytes)
            except DecodeError as e:
                logger.error("Failed to parse msg nr {}. '{}'".format(self._msg_count, e))
                pb_msg = None
                err = e

            if 1:
                err_str = str(err) if err else ""
                entry = (self._msg_count, msg_size, msg_bytes, err_str)
                self._msg_hist.append(entry)

            if pb_msg:
                odmsg = self._MessageToOrderedDict(pb_msg, columnize=True)
                if self._is_last_msg(odmsg):
                    return True
                self._append(odmsg)

            if err:
                self._dump_msg_hist()
                raise err

            self._bbuf = self._bbuf[msg_size + 1 :]  # pop
            self._msg_count += 1



