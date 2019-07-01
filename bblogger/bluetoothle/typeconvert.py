from struct import pack, unpack

# Bluetooth LE do not specify eniandess (byteorder), but little seems to be
# most commonly used according to random sources on the internets, even though
# network order is usualy big endian.
DEFAULT_BYTEORDER='little' 


# names must not conflict with those listed here: 
# https://docs.python.org/3/library/codecs.html#standard-encodings
_INT_TYPES = {
    'int8':   (1, True),
    'int16':  (2, True),
    #'int24':  (3, True), 
    'int32':  (4, True),
    'int64':  (8, True),
    #'int128': (16, True),
    'uint8':  (1, False),
    'uint16': (2, False),
    #'uint24': (3, False), 
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
# Only to verify sane parameter
# could be replaced with:
#    codecs.lookup(<name>) that raises a LookupError if bad codec name
# from codecs import lookup as _codecs_lookup
# _STRING_TYPES = {
    # 'ascii' : 1,
    # 'utf-8' : 1
# }

def toCType(val, ctype, byteorder):
    ''' python to ctype 
    if ctype is "*int*", floats implicitly converted to int types 
    '''
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

        return pack(fmt, val)
    else:
        #if not isinstance(val, str):
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
        
        return unpack(fmt, ba)[0]

    else:
        return ba.decode(ctype)


