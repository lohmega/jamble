
from sys import stderr

import logging
logging.basicConfig(stream=stderr, level=logging.DEBUG,
        format='%(levelname)s: %(message)s')
_logger = logging.getLogger(__name__)
_logger.setLevel(logging.ERROR)
#_logger.setLevel(logging.DEBUG)


def verbosity(level):
    if level <= 0:
       #level = logging.NOTSET
       level = logging.ERROR
    elif level == 1:
        level = logging.ERROR
    elif level == 2:
        level = logging.WARNING
    else:
        level = logging.DEBUG
    _logger.setLevel(level)


def print_wrn(*args):
    _logger.warning(' '.join(str(a) for a in args))

def print_err(*args):
    _logger.error(' '.join(str(a) for a in args))

def print_dbg(*args):
    _logger.debug(' '.join(str(a) for a in args))

def objdump(obj):
    ''' debug '''
    for attr in dir(obj):
        print("obj.%s = %r" % (attr, getattr(obj, attr)))

def hexdump(bdata):
    print(','.join(['0x{:02x}'.format(b) for b in bdata]))

# names must not conflict with those listed here: 
# https://docs.python.org/3/library/codecs.html#standard-encodings
_INT_TYPES = {
    'int8':   (1, True),
    'int16':  (2, True),
    'int24':  (3, True), # works, why not
    'int32':  (4, True),
    'int64':  (8, True),
    #'int128': (16, True),
    'uint8':  (1, False),
    'uint16': (2, False),
    'uint24': (3, False), # works, why not
    'uint32': (4, False),
    'uint64': (8, False),
}
# little-endian '<', big-endian '>'
# IEEE-754 floats
# format name : (size, littlefmt, bigfmt)
_FLOAT_TYPES = {
    # 'float16'
    'float32': (4, '<f', '>f'),
    'float':   (4, '<f', '>f'),
    'float64': (4, '<d', '>d'),
    'double':  (4, '<d', '>d'),
}


_STRING_TYPES = {
    'ascii' : 1,
    'utf-8' : 1
}

def toCType(val, ctype, byteorder):
    ''' python to ctype 
    floats implicitly converted to int types '''
    if ctype is None:
        return val

    elif ctype in _INT_TYPES:
        # if isinstance(val, float) and val.is_integer():
        val = int(val) 
        size, signed = _INT_TYPES[ctype]
        return val.to_bytes(size, byteorder, signed=signed)

    elif ctype in _FLOAT_TYPES:
        val = float(val)
        size, littlefmt, bigfmt = _FLOAT_TYPES[ctype]

        if len(ba) != size:
            emsg = 'Convert bytes to float of size {} failed. Got {} \
            bytes'.format(size, len(ba))
            raise TypeError(emsg)

        if byteorder not in ['little', 'big']:
            raise ValueError('byteorder must be little or big')

        fmt = littlefmt if byteorder == 'little' else bigfmt
        return struct.pack(fmt, val)
    else:
        #if not isinstance(val, str):
        # val = str(val)
        val.encode(ctype)

def fromCType(ba, ctype, byteorder, strict=True):
    ''' convert bytearray to python value '''
    if ctype is None:
        return ba

    elif ctype in _INT_TYPES:
        # if isinstance(x, float) and x.is_integer():
            # x = int(x)
        size, signed = _INT_TYPES[ctype]

        if len(ba) != size and strict:
            raise TypeError('Convert bytes to int of size {} failed. \
                    Got {} bytes'.format(size, len(ba)))

        return int.from_bytes(ba, byteorder, signed=signed)

    elif ctype in _FLOAT_TYPES:
        size, littlefmt, bigfmt = _FLOAT_TYPES[ctype]

        if len(ba) != size:
            raise TypeError('Convert bytes to float of size {} failed. \
                    Got {} bytes'.format(size, len(ba)))

        if byteorder not in ['little', 'big']:
            raise ValueError('byteorder must be little or big')

        fmt = littlefmt if byteorder == 'little' else bigfmt
        return struct.unpack(fmt, ba)[0]

    else:
        return ba.decode(ctype)


