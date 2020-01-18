#!/usr/bin/env python3
# command line tool for interacting with Lohmea BlueBerry logger over Bluetooth LE 
#
import logging
import asyncio
import sys
import argparse
import traceback

import bblogger as bbl
from bleak import __version__ as bleak_version



logger = logging.getLogger(__name__)

async def do_scan(**kwargs):
    await bbl.scan(outfile=sys.stdout, timeout=kwargs.get('timeout'))

async def do_blink(**kwargs):
    n = kwargs.get('num', 0)
    async with bbl.BlueBerryClient(**kwargs) as bbc:
        await bbc.blink(n)

async def do_config_read(**kwargs):
    def to_onoff(x):
        return 'on' if x else 'off'

    async with bbl.BlueBerryClient(**kwargs) as bbc:
        conf = await bbc.config_read()

    for key, val in conf.items(): 
        if key == 'pwstatus':
            v = '{} ({})'.format(val, bbl.pw_status_to_str(val))
        elif key == 'interval':
            v = str(val)
        else:
            v = to_onoff(val)

        print('  ', key.ljust(10), ':', v)

async def do_config_write(**kwargs):
    async with bbl.BlueBerryClient(**kwargs) as bbc:
        await bbc.config_write(**kwargs)

async def do_set_password(**kwargs):
    password = kwargs.get('password')
    if password is None:
        raise ValueError('No password provided')

    async with bbl.BlueBerryClient(**kwargs) as bbc:
        await bbc.set_password(password)

async def do_fetch(**kwargs):
    ofile = kwargs.get('file') 
    if  ofile is None:
        fp = sys.stdout
    else:
        #TODO open file, check exists etc
        fp = open(ofile, 'w')

    async with bbl.BlueBerryClient(**kwargs) as bbc:
        await bbc.fetch(ofile=fp, **kwargs)


async def do_test(**kwargs):
    ''' test different commands and settings. As problems
    often are in lower level BLE API:s this test might expose them'''

    if kwargs.get('address') is None:
        raise ValueError('No address')

    logger.info('Testing scan')
    kwargs['timeout'] = 5
    logger.info('args: %s' % str(kwargs))
    await do_scan(**kwargs)

    logger.info('Testing config-read')
    await do_config_read(**kwargs)
        
    logger.info('Testing config-write')
    kwargs['logging'] = True
    kwargs['interval'] = 1
    logger.info('args: %s' % str(kwargs))
    await do_config_write(**kwargs)

    logger.info('Testing fetch rtd txt')
    kwargs['rtd'] = True
    kwargs['num'] = 3
    kwargs['fmt'] = 'txt'
    logger.info('args: %s' % str(kwargs))
    await do_fetch(**kwargs)
    
    logger.info('Testing fetch rtd csv')
    kwargs['fmt'] = 'csv'
    logger.info('args: %s' % str(kwargs))
    await do_fetch(**kwargs)

    logger.info('Testing fetch stored (but must sleep some sec first)')
    kwargs['rtd'] = False
    kwargs['num'] = None
    logger.info('args: %s' % str(kwargs))
    await asyncio.sleep(3)
    await do_fetch(**kwargs)



def parse_args():

    def type_password(s):
        if s is None:
            return None
        msg = 'Password must be 8 chars and ascii only'
        try:
            ba = bytearray(s.encode('ascii'))
        except UnicodeDecodeError:
            raise argparse.ArgumentTypeError(msg)
        if len(ba) != 8:
            raise argparse.ArgumentTypeError(msg)
        return ba

    def type_uint(s):
        ''' parse to unsigned (positive) int '''
        i = int(s)
        if i < 0:
            raise argparse.ArgumentTypeError('%s is an not a positive int value' % s)
        return i

    common = argparse.ArgumentParser(add_help=False)                                 
    common.add_argument('--verbose', '-v', default=0, action='count',
            help='Verbose output')

    
    common.add_argument('--timeout', 
        type=type_uint, 
        default=5,
        help='Timeout in seconds. useful for batch jobs')

    # --- common that do not apply for scan -------------------------------
    common.add_argument('--password', '--pw',
            type=type_password,
            default=None, 
            help='Password to unlock (or lock) device')
    common.add_argument('--address', '-a', 
            metavar='ADDR', 
            help='Bluetooth LE device address (or device UUID on MacOS)')

    parser = argparse.ArgumentParser(description='',
            add_help=False)
    subparsers = parser.add_subparsers()
    sps = []

    parser.add_argument('--help', '-h', 
            action='store_true',
            help='Show this help message and exit')

    parser.add_argument('--version',
            action='store_true',
            help='Show version info and exit')

    # ---- SCAN --------------------------------------------------------------
    sp = subparsers.add_parser('scan', 
            parents = [common],
            description='Show list of BlueBerry logger devices')
    sp.set_defaults(_actionfunc=do_scan)
    sps.append(sp)


    # ---- BLINK -------------------------------------------------------------
    sp = subparsers.add_parser('blink', 
            parents = [common],
            description='Blink LED on device for physical identification')
    sp.set_defaults(_actionfunc=do_blink)

    sp.add_argument('--num', '-n', metavar='N', type=type_uint, 
            default=1,
            help='Number of blinks')
    sps.append(sp)


    # ---- CONFIG READ ------------------------------------------------------
    sp = subparsers.add_parser('config-read', 
            parents = [common],
            description='configure device')
    sp.set_defaults(_actionfunc=do_config_read)
    sps.append(sp)


    # ---- CONFIG WRITE ------------------------------------------------------
    BOOL_CHOICES = { 'on':True, 'off':False}
    def onoffbool(s):
        if s not in BOOL_CHOICES:
            msg = 'Valid options are {}'.format(BOOL_CHOICES.keys())
            raise argparse.ArgumentTypeError(msg)
        return BOOL_CHOICES[s]

    sp = subparsers.add_parser('config-write', 
            parents = [common],
            description='configure device')
    sp.set_defaults(_actionfunc=do_config_write)
    cfa = sp.add_argument_group('Config fields', 
            description='')
    #gsensors = sp.add_mutually_exclusive_group()

    sensor_names = list(bbl.SENSORS.keys())
    for s in sensor_names:
        cfa.add_argument('--{}'.format(s), 
                #'-{}'.format(s.symbol), 
                metavar='ONOFF', 
                type=onoffbool,
                help='sensor on|off')

    # cfa.add_argument('--all', 
            # metavar='ONOFF', 
            # type=onoffbool,
            # help='All sensors on|off. Can be combined with indvidual sensors \
            # on|off for easier configuration')

    cfa.add_argument('--logging', 
            type=onoffbool,
            metavar='ONOFF', 
            help='Logging (sensor measurements) on|off')

    cfa.add_argument('--interval', type=type_uint, 
            help='Global log interval in seconds')
    sps.append(sp)

    # ---- CONFIG-PASSWORD ---------------------------------------------------
    sp = subparsers.add_parser('set-password', #'config-pw',
            parents = [common],
            #aliases=['config-pw'],
            description='Enable password protection on device. \
            can only be used after device power cycle.')
    sp.set_defaults(_actionfunc=do_set_password)
    sps.append(sp)

    # ---- FETCH -------------------------------------------------------------
    sp = subparsers.add_parser('fetch', # parents=[parser],
            parents = [common],
            description='Fetch sensor data')
    sp.set_defaults(_actionfunc=do_fetch)
    sp.add_argument('--file', help='Data output file')
    sp.add_argument('--rtd', 
            action='store_true',
        help='Fetch realtime sensor data instead of logged. Will always show \
            all sensors regardless of config')

    sp.add_argument('--fmt', default='txt', choices=['csv', 'json', 'txt'], #'pb'
            help='Data output format')

    sp.add_argument('--num', '-n', metavar='N', type=type_uint, 
            help='Max number of data points or log entries to fetch')
    sps.append(sp)

    sp = subparsers.add_parser('test', 
            parents = [common],
            description='Test different actions. takes a some time to complete')
    sp.set_defaults(_actionfunc=do_test)
    sps.append(sp)

    args = parser.parse_args()

    if args.help:
        for sp in sps:
           print(sp.format_help())
           print() # extra linebreak

        parser.exit()

    if 'verbose' not in args:
        args.verbose = 0

    return vars(args)

def print_versions():
    import platform

    print('bleak:', bleak_version)
    print('os:', platform.platform())
    print('python:', platform.python_version())

    if platform.system() == 'Linux':
        import subprocess
        try:
            s = subprocess.check_output(['bluetoothctl', '--version'])
            s = s.decode('ascii').strip()
        except (FileNotFoundError, subprocess.CalledProcessError) as e:
            s = '??'
        print('bluez:', s)

def set_verbose(verbose_level):
    loggers = [logging.getLogger('bblogger'), logger]

    if verbose_level <= 0:
        level = logging.WARNING
    elif verbose_level == 2:
        level = logging.INFO
    elif verbose_level >= 3:
        level = logging.DEBUG

    if verbose_level >= 4:
        bleak_logger = logging.getLogger('bleak')
        loggers.append(bleak_logger)

    handler = logging.StreamHandler(sys.stderr)
    handler.setLevel(level)
    
    formatter = logging.Formatter('%(levelname)s:%(name)s:%(lineno)d: %(message)s')
    handler.setFormatter(formatter)

    for l in loggers:
        l.setLevel(level) #logging.DEBUG)
        l.addHandler(handler)

    if verbose_level >= 3:
        print_versions()

def main():
    args = parse_args()

    verbose_level = args['verbose']
    set_verbose(verbose_level)
    logger.debug('args={}'.format(args))

    if args.get('version'): 
        print_versions()
        exit(0)

    actionfunc = args.get('_actionfunc')
    if not actionfunc:
        return
    loop = asyncio.get_event_loop()
    loop.run_until_complete(actionfunc(loop=loop, **args))

    # try:
        # loop = asyncio.get_event_loop()
        # #aw = asyncio.wait_for(args._actionfunc(loop, args), args.timeout)
        # #loop.run_until_complete(aw)
        # loop.run_until_complete(actionfunc(loop=loop, **args))
    # except Exception as e:
        # print(e)
        # if verbose_level:
            # print(traceback.format_exc())
        # exit(1)



if __name__ == '__main__':
    main()
