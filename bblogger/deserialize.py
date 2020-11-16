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


class _PacketBuffer:
    """
    FIFO buffer preserving BLE packets to handle packets out of order (bug in dbus/bluez!?)
    'pkt' - bluteooth package (chunk of bytes)
    """

    def __init__(self):
        self._q = deque(maxlen=128)

    def write(self, data):
        if len(self._q) >= self._q.maxlen:
            raise RuntimeError("buf to small")

        self._q.append(data)


    def peek(self, size, pkt_order=None):
        """ returns a bytearray of len size or less """

        res = bytearray()
        if not size:
            return res

        if pkt_order is None:
            pkt_order = range(0, len(self._q))

        for i in pkt_order:
            remains = size - len(res)
            if remains <= 0:
                break

            try:
                pkt = self._q[i]
            except IndexError:
                break

            # remains could be out of range (no error raised)
            chunk = pkt[0 : remains]
            res.extend(chunk)

        return res


    def getc(self):
        """ read a single char/byte """

        try:
            c = self._q[0][0]
        except IndexError:
            raise EOFError()

        self._q[0] = self._q[0][1:] # pop left

        return int(c)


    def seek_fwd(self, size, pkt_order=None):
        """ Move "read cursor" forward N bytes """ 
        if not size:
            return

        if pkt_order is None:
            pkt_order = range(0, len(self._q))

        remains = size
        to_del = []
        for i in pkt_order:

            try:
                pkt = self._q[i]
            except IndexError:
                break

            if remains < len(pkt):
                self._q[i] = pkt[remains:]
                remains = 0
                break

            to_del.append(i)
            remains -= len(pkt)

            if remains <= 0:
                break

        if remains > 0:
            raise EOFError()

        # reverse sort to preserve index while deleting
        for i in sorted(to_del, reverse=True):
            del self._q[i]


class BlueBerryDeserializer:
    """
    reads a stream of protobuf data with the format 
    <len><protobuf message of size len><len>,...
   
    abbrevations and definitions used:
    'msg' - bytes or pb object for a complete message
    'pkg' - bluteooth package (chunk of bytes)
    """

    def __init__(self, ofile=stdout, ofmt="txt", raw=False, msg_hist_len=32):
        self._pb = bb_log_entry_pb2.bb_log_entry()  # protobuf message
        self._ofile = ofile
        self._raw = raw
        self._prev_keyset = None
        self._msg_hist = deque(maxlen=msg_hist_len)
        self._msg_count = 0

        self._pkt_buf = _PacketBuffer()
        self._msg_size = None
        self._fail_count = 0

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

        failed_msg_bytes = ','.join([ba.hex() for ba in self._pkt_buf._q]),
        print(
              "{:04d}".format(self._msg_count),
              "{:04d}".format(self._msg_size), 
              "({})".format(failed_msg_bytes),
              "'Failed pakets'",
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

    def _is_end_of_log_msg(self, odm):
        """ end of log "EOF" is a empty messagge with only the required
        timestamp field """
        if len(odm) == 1:
            if "TS" not in odm:
                logger.warning("unexpected last msg keys {}".format(odm.keys()))
            return True
        else:
            return False

    def parse_msg_bytes(self, msg_bytes):
        self._pb.Clear()
        # ignore E1101: Instance of 'bb_log_entry' has no 'FromString' member (no-member)
        pb_msg = self._pb.FromString(msg_bytes) # pylint: disable=E1101
        odmsg = self._MessageToOrderedDict(pb_msg, columnize=True)
        done = self._is_end_of_log_msg(odmsg)
        if done:
           logger.debug("End of log msg received")
        else:
            self._append(odmsg)

        return done

    def parse_pkt_buf(self, pkt_order=None):
        if self._msg_size is None:
            self._msg_size = self._pkt_buf.getc() # raises EOFError if no data

            if self._msg_size == 0:
                raise RuntimeError("msg_size is zero. Where to start?")

        msg_bytes = self._pkt_buf.peek(self._msg_size, pkt_order)
        if len(msg_bytes) < self._msg_size:
            raise EOFError("Need more data")

        done = self.parse_msg_bytes(msg_bytes)

        entry = (self._msg_count, self._msg_size, msg_bytes, "")
        self._msg_hist.append(entry)
        self._msg_count += 1

        # reset
        self._pkt_buf.seek_fwd(self._msg_size, pkt_order)
        self._msg_size = None

        return done # might have more msg in pkt_buf

    def putb(self, chunk):
        if not isinstance(chunk, bytearray):
            chunk = bytearray(chunk)

        self._pkt_buf.write(chunk)
        if self._fail_count:
            try:
                pkt_order=[0, 2, 1, 3, 4] # 0 is oldest
                self.parse_pkt_buf(pkt_order=pkt_order)
                self._fail_count = 0
                logger.debug("Successfully recovered")
            except (DecodeError, EOFError) as e:
                logger.error("Failed to parse msg nr {}. '{}'".format(self._msg_count, e))
                self._dump_msg_hist()
                raise e

        done = False
        while not done:
            try:
                done = self.parse_pkt_buf()
            except EOFError:
                return False  # Need more data

            except DecodeError as e:
                logger.warning("Failed to parse msg nr {}. '{}'. Trying to recover...".format(self._msg_count, e))
                self._fail_count += 1
                return False  # try recover on next call

        return done

