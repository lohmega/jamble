import csv
import json
import sys

class OutputWriterBase:
    def __init__(self, outfile, header=None, **kwargs):
        self._header = header
        self._outfile = outfile
        if header:
            self.write_row(header)

    def close(self):
        pass


class OutputWriterTxt(OutputWriterBase):
    def __init__(self, outfile, header=None, colwidths=[], **kwargs):
        self._colwidths = colwidths
        super().__init__(outfile, header)

    def _column_pad(self, i, s):
        s = str(s)
        if i < len(self._colwidths):
            n = self._colwidths[i]
        else:
            n = 1

        return s.ljust(n) 

    def write_row(self, vals):
        a = [self._column_pad(i, v) for i, v in enumerate(vals)]
        print(*a, sep=" ", file=self._outfile)

    def write_kv(self, d):
        klen = max(len(str(k)) for k in d) + 1
        for k, v in d.items():
            ks = "{}:".format(k).ljust(klen)
            vs = str(v)
            print("   ", ks, vs, file=self._outfile)


class OutputWriterJson(OutputWriterBase):
    def __init__(self, outfile, header=None, **kwargs):
        super().__init__(outfile, header)

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
        super().__init__(outfile, header)

    def write_row(self, vals):
        self._csvw.writerow(vals)

    def write_kv(self, d):
        self.write_row(d.keys())
        self.write_row(d.values())

class OutputWriterDummy(OutputWriterBase):
    def __init__(self, outfile, header=None, **kwargs):
        super().__init__(outfile, header)

    def write_row(self, vals):
        pass

    def write_kv(self, d):
        pass

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


