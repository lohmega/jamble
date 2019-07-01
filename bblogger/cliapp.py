import bblogger
import sys
import argparse
import logging
import pprint

BOOL_CHOICES_DICT = { 'on':True, 'off':False}
BOOL_CHOICES = BOOL_CHOICES_DICT.keys()

SENSOR_NAMES = list(bblogger._sensors.keys())
CONFIG_FIELDS = list(SENSOR_NAMES) # "new"
CONFIG_FIELDS.extend(['logging', 'interval'])

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

def die(*args, **kwargs):
    print('ERROR:', *args, file=sys.stderr, **kwargs)
    exit(1)

def getBlueBerryDevice(args, cached=True):

    if args.address is None:
        return die('No address')

    if args.address == '0': # i.e. use first detected
        devs = bblogger.devices(cached=cached)

    else:
        addr = args.address # crash later if invalid format
        devs = bblogger.devices(addr=addr, 
                cached=cached)#, timeout=args.timeout)

    if len(devs) == 0:
        return die('No devices found')

    elif len(devs) > 1:
        return die('More then one berry found. Which one of the following to \
                use?', devs)

    else:
        dev = devs[0]
        print('Using:', dev.addr, dev.name) 
        return dev

def doBlink(args):
    with getBlueBerryDevice(args) as dev:
        for n in range(0, args.num):
            print(dev.addr, dev.name, 'blinking..')
            dev.blinkLED()

def doScan(args):
    devs = bblogger.devices(cached=True)
    for dev in devs:
        print(dev.addr, dev.name)


def doConfigWrite(args):
    toBool = lambda s: BOOL_CHOICES_DICT[s]
    d = vars(args)
    confd = {}
    for k, v in d.items():
        if k not in CONFIG_FIELDS:
            continue
        if v is None:
            continue
        confd[k] = v

    # if args.all is not None:
        # default = args.all
        # provided = d.keys()
        # for k in SENSOR_NAMES:
            # if k in provided:
                # continue
            # confd[k] = default

    print_dbg(confd)
    with getBlueBerryDevice(args) as dev:
        dev.config_write(**confd)

def doConfigRead(args):
    
    def toOnOff(_v):
        assert(_v is not None)
        return 'on' if _v else 'off'

    with getBlueBerryDevice(args) as dev:
        conf = dev.config_read()

    printkv = lambda _k, _v: print('  ', _k.ljust(12), ':', _v)
    k = 'logging'
    printkv(k, toOnOff(conf.pop(k)))

    k = 'interval'
    printkv(k, conf.pop(k))

    k = 'pwstatus'
    printkv(k, conf.pop(k))

    # "on|off" values
    for k in sorted(conf.keys()):
        v = toOnOff(conf[k])
        printkv(k, v)

def doFetch(args):
    
    if args.file is None:
        ofile = sys.stdout
    else:
        ofile = open(args.file, 'w')
        #raise NotImplementedError('TODO open file, check exists etc') # TODO


    with getBlueBerryDevice(args) as dev:
        dev.fetch(rtd=args.rtd, 
                nentries=args.num,
                ofmt=args.fmt,
                ofile=ofile)

    if ofile not in (sys.stdout, sys.stderr): # or use not ofile.isatty():
        ofile.close()


def verbosity(level):
    if level <= 0:
       #level = logging.NOTSET
       level = logging.WARNING
    else:
        level = logging.DEBUG
    logging.getLogger().setLevel(level)
    _logger.setLevel(level)


def main():
    parser = argparse.ArgumentParser(description='',
            add_help=False)
    subparsers = parser.add_subparsers()
    sps = []

    parser.add_argument('--help', '-h', 
            ##action=_HelpAction, 
            action='store_true',
            #default=argparse.SUPPRESS,
            default=False,
            help='show this help message and exit')

    # ---- BLINK -------------------------------------------------------------

    sp = subparsers.add_parser('blink', 
            description='Blink LED on device for physical identification')
    sp.set_defaults(_actionFunc=doBlink)

    sp.add_argument('--num', '-n', metavar='N', type=int, 
            default=1,
            help='Number of blinks')
    sps.append(sp)

    # ---- SCAN --------------------------------------------------------------

    sp = subparsers.add_parser('scan', 
            description='Show list of BlueBerry logger devices')
    sp.set_defaults(_actionFunc=doScan)
    sps.append(sp)

    # ---- CONFIG WRITE ------------------------------------------------------

    def onOffBool(s):
        if s not in BOOL_CHOICES_DICT:
            msg = 'Valid options are {}'.format(BOOL_CHOICES_DICT.keys())
            raise argparse.ArgumentTypeError(msg)
        return BOOL_CHOICES_DICT[s]

    sp = subparsers.add_parser('conf-write', 
            description='Write or modify device configuration ')
    sp.set_defaults(_actionFunc=doConfigWrite)
    #gsensors = sp.add_mutually_exclusive_group()
    for s in SENSOR_NAMES:
        sp.add_argument('--{}'.format(s), 
                #'-{}'.format(s.symbol), 
                metavar='ONOFF', 
                type=onOffBool,
                #choices=BOOL_CHOICES,
                help='sensor on|off')

    # sp.add_argument('--all', 
            # metavar='ONOFF', 
            # type=onOffBool,
            # help='All sensors on|off. Can be combined with indvidual sensors \
            # on|off for easier configuration')


    sp.add_argument('--logging', 
            type=onOffBool,
            metavar='ONOFF', 
            #choices=BOOL_CHOICES,
            help='Logging (global) on|off (sensor data stored)')

    sp.add_argument('--interval', type=int, 
            help='Global log interval in seconds')
    
    # TODO 
    # sp.add_argument('--new-password', 
            # help='Set (or change) password. Printable ASCII only')
    sps.append(sp)

    # ---- CONFIG READ -------------------------------------------------------

    sp = subparsers.add_parser('conf-read', 
            description='Read device configuration')
    sp.set_defaults(_actionFunc=doConfigRead)
    sps.append(sp)

    # ---- FETCH -------------------------------------------------------------

    sp = subparsers.add_parser('fetch', # parents=[parser],
            description='Fetch sensor data')
    sp.set_defaults(_actionFunc=doFetch)
    sp.add_argument('--file', help='Data output file')
    sp.add_argument('--rtd', 
            action='store_true',
        help='Fetch realtime sensor data instead of logged. Will always show \
            all sensors regardless of config')

    sp.add_argument('--fmt', default='txt', choices=['csv', 'txt'], #'pb', 'json', 
            help='Data output format')

    sp.add_argument('--num', '-n', metavar='N', type=int, 
            help='Max number of data points or log entries to fetch')
    sps.append(sp)


    for sp in sps:
        # TODO
        # sp.add_argument('--password', '--pw',
                # default=None, help='Needed if device is password protected')
        sp.add_argument('--address', '-a', 
                metavar='ADDR', 
                help='BLE device address. if set to "0", the first BlueBerry device \
                will be used, this feature should be used with care, but can be \
                useful when it is known that only one Berry is present within \
                range')
        sp.add_argument('--verbose', '-v', default=0, action='count',
                help='Verbose output')
        # sp.add_argument('--timeout', 
                # type=int, 
                # help='Timeout in seconds. useful for batch jobs')
        sp.format_help()

    args = parser.parse_args()


    if args.help:
        for sp in sps:
           print(sp.format_help())
           print(sp.format_usage())

        parser.exit()

    verbosity(args.verbose)
    print_dbg(args)

    print_dbg('----- VERSIONS ----\n',
            pprint.pformat(bblogger.versions()))

    args._actionFunc(args)


if __name__ == '__main__':
    main()
