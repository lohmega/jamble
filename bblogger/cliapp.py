import bblogger
import sys
import argparse
import logging
import pprint
from time import sleep

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
    print('E:', *args, file=sys.stderr, **kwargs)
    exit(1)

def get_device(args, cached=True):

    if args.address is None:
        return die('No address')

    if args.address == '0': # i.e. use first detected
        devs = bblogger.devices(cached=cached)

    else:
        addr = args.address # crash later if invalid format
        devs = bblogger.devices(address=addr, 
                cached=cached)#, timeout=args.timeout)

    if len(devs) == 0:
        return die('No devices found')

    elif len(devs) > 1:
        return die('More then one berry found. Which one of the following to \
                use?', devs)

    dev = devs[0]
    print('Using:', dev.address, dev.name) 
    return dev

def unlock_device(dev, password):
    ''' assume device to be connected '''
    if dev.pw_required():
        if password is None:
            return die('Password required for device', dev.address)
        dev.pw_unlock(password)

def do_scan(args):
    devs = bblogger.devices(cached=args.cached)
    for dev in devs:
        print(dev.address, dev.name)

def do_blink(args):
    #password not needed for blink
    try:
        with get_device(args) as dev:
            for n in range(0, args.num):
                print(dev.address, dev.name, 'blinking..')
                dev.blinkLED()
    except TimeoutError as e:
        die(e)

def do_config_write(args):
    toBool = lambda s: BOOL_CHOICES_DICT[s]
    argsd = vars(args)
    confd = {}
    for k, v in argsd.items():
        if k not in CONFIG_FIELDS:
            continue
        if v is None:
            continue
        confd[k] = v

    print_dbg(confd)
    try:
        with get_device(args) as dev:
            unlock_device(dev, args.password)
            dev.config_write(**confd)
    except TimeoutError as e:
        die(e)

def do_config_read(args):
    
    def toOnOff(_v):
        assert(_v is not None)
        return 'on' if _v else 'off'
    # password not needed for read
    try:
        with get_device(args) as dev:
            conf = dev.config_read()
    except TimeoutError as e:
        die(e)

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

def have_config_field(args):
    argsd = vars(args)
    for k, v in argsd.items():
        if v is None:
            continue
        if k in CONFIG_FIELDS:
            return True
    return False

def do_config(args):
    if have_config_field(args):
        do_config_write(args)
    else:
        do_config_read(args)

def do_config_password(args):
    # TODO verify oasswird format first
    addr = args.address

    if addr is None or addr == '0':
        return die('Address is required when setting password') 
            
    if args.password is None or len(args.password) == 0:
        disable = True
    else:
        disable = False
    
    done = False
    while True:
        devs = bblogger.devices(address=addr, cached=False)

        if len(devs) == 0:
            print('No device with matching addr found. Insert battery!? Retrying...')
            sleep(1)
            continue

        assert(len(devs) == 1)
        dev = devs[0]
        try:
            dev.connect()
            rc, s = dev.pw_status()
            if disable:
                if rc in (bblogger.PW_STATUS_INIT, bblogger.PW_STATUS_DISABLED):
                    print('Password protection is disabled')
                else:
                    print('Please power cycle device and password protection will be disabled')
                done = True
            else:
                if rc == bblogger.PW_STATUS_INIT:
                    dev.pw_set(args.password)
                    print('Password protection enabled')
                    done = True
                else:
                    print('Device not in init mode. Please power cycle device')

            dev.disconnect()

        except TimeoutError as e:
            print('Failed to connect or write, retrying...')

        except KeyboardInterrupt:
            die('Aborted')

        if done:
            break
        else:
            sleep(1)

                    


            


def do_fetch(args):
    
    if args.file is None:
        ofile = sys.stdout
    else:
        ofile = open(args.file, 'w')
        #raise NotImplementedError('TODO open file, check exists etc') # TODO
    errmsg = None
    try:
        with get_device(args) as dev:
            unlock_device(dev, args.password)
            dev.fetch(rtd=args.rtd, 
                    nentries=args.num,
                    ofmt=args.fmt,
                    ofile=ofile)
    except TimeoutError as e:
        errmsg = str(e)

    finally:
        if ofile not in (sys.stdout, sys.stderr): # or use not ofile.isatty():
            ofile.close()

    if errmsg is not None:
        die(errmsg)


def set_verbosity(level):
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
            #default=False,
            help='show this help message and exit')

    # ---- BLINK -------------------------------------------------------------
    sp = subparsers.add_parser('blink', 
            description='Blink LED on device for physical identification')
    sp.set_defaults(_actionfunc=do_blink)

    sp.add_argument('--num', '-n', metavar='N', type=int, 
            default=1,
            help='Number of blinks')
    sps.append(sp)

    # ---- SCAN --------------------------------------------------------------
    sp = subparsers.add_parser('scan', 
            description='Show list of BlueBerry logger devices')

    sp.add_argument('--cached', '-c',
           action='store_true',
           default=False, 
           help='Show system cached BLE devices. faster but possible incorrect')
    sp.set_defaults(_actionfunc=do_scan)
    sps.append(sp)

    # ---- CONFIG READ ------------------------------------------------------
    sp = subparsers.add_parser('config-read', 
            description='configure device')
    sp.set_defaults(_actionfunc=do_config_read)
    sps.append(sp)


    # ---- CONFIG WRITE ------------------------------------------------------
    def onoffbool(s):
        if s not in BOOL_CHOICES_DICT:
            msg = 'Valid options are {}'.format(BOOL_CHOICES_DICT.keys())
            raise argparse.ArgumentTypeError(msg)
        return BOOL_CHOICES_DICT[s]

    sp = subparsers.add_parser('config-write', 
            description='configure device')
    sp.set_defaults(_actionfunc=do_config_write)
    cfa = sp.add_argument_group('Config fields', 
            description='show config if none provided')
    #gsensors = sp.add_mutually_exclusive_group()
    for s in SENSOR_NAMES:
        cfa.add_argument('--{}'.format(s), 
                #'-{}'.format(s.symbol), 
                metavar='ONOFF', 
                type=onoffbool,
                #choices=BOOL_CHOICES,
                help='sensor on|off')

    # cfa.add_argument('--all', 
            # metavar='ONOFF', 
            # type=onoffbool,
            # help='All sensors on|off. Can be combined with indvidual sensors \
            # on|off for easier configuration')

    cfa.add_argument('--logging', 
            type=onoffbool,
            metavar='ONOFF', 
            #choices=BOOL_CHOICES,
            help='Logging (global) on|off (sensor data stored)')

    cfa.add_argument('--interval', type=int, 
            help='Global log interval in seconds')
    sps.append(sp)

    # ---- CONFIG-PASSWORD ---------------------------------------------------
    sp = subparsers.add_parser('config-password', #'config-pw',
            aliases=['config-pw'],
            description='set (new) disable password. \
            requires device power cycle. empty password to disable')
    sp.set_defaults(_actionfunc=do_config_password)
    sps.append(sp)

    # ---- FETCH -------------------------------------------------------------
    sp = subparsers.add_parser('fetch', # parents=[parser],
            description='Fetch sensor data')
    sp.set_defaults(_actionfunc=do_fetch)
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

    # same flags added for all positionals above
    for sp in sps:
        # TODO
        sp.add_argument('--password', '--pw',
                default=None, help='Needed if device is password protected')
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

    if 'verbose' not in args:
        args.verbose = 0
    set_verbosity(args.verbose)

    print_dbg(args)

    print_dbg('----- VERSIONS ----\n',
            pprint.pformat(bblogger.versions()))

    if '_actionfunc' in args:
        args._actionfunc(args)


if __name__ == '__main__':
    main()
