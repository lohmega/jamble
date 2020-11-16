import csv
import json
import sys

class OutputWriterBase:
    def __init__(self, outfile, header=None, units={}, **kwargs):
        self._outfile = outfile
        self._header = header
        self._units = units
        if header:
            self.write_row(header)

        self._prev_keyset = None

    def close(self):
        pass

    def write_row(self, vals):
        pass

    def write_kv(self, d):
        pass

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


    def write_sensordata(self, keys, vals):
        if self._did_keys_change(keys):
            self.write_row(keys)
        self.write_row(vals)

    def get_unit(self, k):
        if not k in self._units:
            return " "
        else:
            return self._units[k]

class OutputWriterTxt(OutputWriterBase):
    def __init__(self, outfile, header=None, colwidth=None, colwidths=[], formats={}, **kwargs):
        if colwidth and colwidths:
                raise ValueError("colwitdh or colwidths!?")

        self._colwidth = colwidth
        self._colwidths = colwidths
        self._formats = formats

        super().__init__(outfile, header, **kwargs)

    def _col_pad(self, i, s):
        """ colum space padding """
        s = str(s)
        if self._colwidth:
            n = self._colwidth
        elif i < len(self._colwidths):
            n = self._colwidths[i]
        else:
            n = 1

        return s.ljust(n)

    def write_row(self, vals):
        a = [self._col_pad(i, v) for i, v in enumerate(vals)]
        print(*a, sep=" ", file=self._outfile)

    def write_kv(self, d):
        klen = max(len(str(k)) for k in d) + 1
        for k, v in d.items():
            ks = "{}:".format(k).ljust(klen)
            vs = str(v)
            print("   ", ks, vs, file=self._outfile)


    def write_sensordata(self, keys, vals):
        """
        pretty columnized text for terminal output.
        """

        if self._did_keys_change(keys):
            self.write_row(keys)

            units = ["({})".format(self.get_unit(k)) for k in keys]
            self.write_row(units)

        assert(len(keys) == len(vals))
        svals = [None] * len(keys)
        for i, k in enumerate(keys):
            if k in self._formats:
                s = self._formats[k].format(vals[i])
            else:
                s = str(vals[i])
            svals[i] = s

        self.write_row(svals)


class OutputWriterJson(OutputWriterBase):
    def __init__(self, outfile, header=None, **kwargs):
        super().__init__(outfile, header, **kwargs)

    def _write_obj(self, obj):
        json.dump(obj, fp=self._outfile)
        print("\n", end="", file=self._outfile)

    def write_row(self, vals):
        self._write_obj(vals)

    def write_kv(self, d):
        self._write_obj(d)


class OutputWriterCsv(OutputWriterBase):
    def __init__(self, outfile, header=None, **kwargs):
        self._csvw = csv.writer(outfile)
        super().__init__(outfile, header, **kwargs)

    def write_row(self, vals):
        self._csvw.writerow(vals)

    def write_kv(self, d):
        self.write_row(d.keys())
        self.write_row(d.values())

class OutputWriterDummy(OutputWriterBase):
    def __init__(self, outfile, header=None, **kwargs):
        super().__init__(outfile, header)


def mk_OutputWriter(outfile=None, fmt=None, **kwargs):
    if outfile is None:
        return OutputWriterDummy(outfile, **kwargs)

    if fmt == "txt":
        return OutputWriterTxt(outfile, **kwargs)

    elif fmt == "csv":
        return OutputWriterCsv(outfile, **kwargs)

    elif fmt == "json":
        return OutputWriterJson(outfile, **kwargs)

    else:
        raise ValueError("Unknown fmt format")


