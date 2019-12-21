
import logging
import asyncio
import sys
import argparse
import logging

from uuid import UUID

# not needed in python >= 3.6? as default dict keeps order
from collections import OrderedDict
from bblogger import BlueBerryLoggerDeserializer, SENSORS, UUIDS

from bleak import BleakClient, discover
from bleak import _logger as bleak_logger
from bleak import __version__ as bleak_version



logging.basicConfig(stream=sys.stderr, level=logging.ERROR,
        format='%(levelname)s: %(message)s')
_logger = logging.getLogger(__name__)

bleak_logger.setLevel(logging.ERROR)
log = logging.getLogger(__name__)


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


PW_STATUS_INIT       = 0x00 
PW_STATUS_UNVERIFIED = 0x01
PW_STATUS_VERIFIED   = 0x02 
PW_STATUS_DISABLED   = 0x03

def pw_status_to_str(rc):
    rctranslate = {
        0x00 : 'init', #'the unit has not been configured yet',
        0x01 : 'unverified', #'the correct password has not been entered yet',
        0x02 : 'verified', #'the correct password has been entered',
        0x03 : 'disabled', #'no password is needed',
    }
    return rctranslate[rc]
 

class BlueBerryLogger(BleakClient):

    async def write_u32(self, cuuid, val):
        val = int(val)
        data = val.to_bytes(size, byteorder='little', signed=False)
        await self.write_gatt_char(cuuid, data, response=True)

    async def read_u32(self, cuuid):
        ba = await self.read_gatt_char(cuuid)
        assert(len(ba) == 4)
        return int.from_bytes(ba, byteorder='little', signed=False)

    async def cmd(self, txdata, rxsize=None):
        ''' first byte in txdata is the cmd id '''
        txuuid = UUIDS.C_CMD_TX
        rxuuid = UUIDS.C_CMD_RX 

        txdata = bytearray(txdata)
        rxdata = bytearray()
        if not rxsize:
            return await self.write_gatt_char(txuuid, txdata, response=True)

        event = asyncio.Event()
        def response_handler(sender, data):
            # sender is str. should be uudi!?
            if sender !=  str(rxuuid):
                print_dbg('unexpected notify response from', 
                        sender, 'expected', rxuuid)
                return
            rxdata.extend(data)
            print_dbg('cmd RXD:', sender, data)
            event.set()


        await self.start_notify(rxuuid, response_handler)
        await self.write_gatt_char(txuuid, txdata, response=True)
        await event.wait()
        await self.stop_notify(rxuuid)
        await asyncio.sleep(2)
        print_dbg('cmd RXD:', rxdata)

        assert(len(rxdata) == rxsize)

        if rxsize and rxdata[0] != (txdata[0] | 0x80):
            raise RuntimeError('Unexpected cmd id in respone')

        return rxdata

    async def pw_status(self):
        ''' password status '''
        rsp = await self.cmd([0x07], 2)
        rc = rsp[1]
        return rc

    async def connect_and_unlock(self, args):
        x = await self.is_connected()
         
        rc = await self.pw_status()
        if rc != PW_STATUS_UNVERIFIED:
            return # no password needed

        if 'password' not in args:
            die('Password needed for this device')

        await self.pw_write(args.password)


    async def pw_write(self, s):
        ''' if pw_status is "init", set new password, 
        if pw_status="unverified", unlock device
        '''
        emsg = 'Password must be 8 chars and ascii only'
        data = bytearray([0x06]) ## 0x06 = command code 
        try:
            pwdata = bytearray(s.encode('ascii'))
        except UnicodeDecodeError:
            raise TypeError(emsg)
        if len(pwdata) != 8:
            raise TypeError(emsg)
        data.extend(pwdata)
        await self.cmd(data)

    
    async def pw_status(self):
        ''' password status '''
        rsp = await self.cmd([0x07], 2)
        return rsp[1]

async def do_scan(loop, args):
    devices = await discover()
    for d in devices:
        if not 'BlueBerry' in d.name:
            print_dbg('ignoring:', d)
            continue
       
        print(d.address, '  ', d.rssi, 'dBm', '  ', d.name)
        continue

        #TODO check advertised service UUID:s
        # is_blueberry = False
        # client = BleakClient(d.address, loop=loop)
        # services = await client.get_services()
        # for service in services:
            # print(service.uuid, "=", UUIDS.S_LOG)
            # continue
            # if service.uuid in [UUIDS.S_LOG]:
                # is_blueberry = True
                # break



async def do_blink(loop, args):
    async with BlueBerryLogger(args.address, loop=loop) as bbl:
        x = await bbl.is_connected()
        await bbl.cmd([0x01])


async def do_config_read(loop, args):

    def to_onoff(x):
        return 'on' if x else 'off'

    conf = OrderedDict()
    async with BlueBerryLogger(args.address, loop=loop) as bbl:
        x = await bbl.is_connected()

        val = await bbl.read_u32(UUIDS.C_CFG_LOG_ENABLE)
        conf['logging'] = to_onoff(val)

        conf['interval'] = await bbl.read_u32(UUIDS.C_CFG_INTERVAL)

        val = await bbl.pw_status()
        conf['pwstatus'] = '{} ({})'.format(val, pw_status_to_str(val))

        enbits = await bbl.read_u32(UUIDS.C_CFG_SENSOR_ENABLE)
        for name, s in SENSORS.items():
            conf[s.apiName] = to_onoff(s.enmask & enbits)

    for k, v in conf.items(): 
        print('  ', k.ljust(10), ':', v)

async def do_config_write(loop, args):
    logging = None
    interval = None
    setMask = 0
    clrMask = 0

    # sanity check all params before write
    argsd = vars(args)
    for k, v in argsd.items():
        if v is None:
            continue

        if k in SENSORS:
            enmask = SENSORS[k].enmask 
            if v:
                setMask |= enmask
            else:
                clrMask |= enmask
        else:
            print_dbg('Ignoring unknown conifg field "{}"'.format(k))
        
    async with BlueBerryLogger(args.address, loop=loop) as bbl:
        await bbl.connect_and_unlock(args)
        if logging is not None:
            await bbl.write_u32(UUIDS.C_CFG_LOG_ENABLE, logging)

        if interval is not None:
            await bbl.write_u32(UUIDS.C_CFG_INTERVAL, interval)

        cuuid = UUIDS.C_CFG_SENSOR_ENABLE
        if setMask or clrMask:
            enMaskOld = await bbl.read_u32(cuuid)
            enMaskNew = (enMaskOld & ~clrMask) | setMask
            print_dbg(self, 
                    'enabled sensors old=0x{:04X}, new=0x{:04X}'.format(enMaskOld, enMaskNew))
            await bbl.write_u32(cuuid, enMaskNew)


async def do_config_password(loop, args):
    pass

async def do_fetch(loop, args):

    if args.rtd:    
        uid = UUIDS.C_SENSORS_RTD
    else:
        uid = UUIDS.C_SENSORS_LOG
    if args.file is None:
        ofile = sys.stdout
    else:
        ofile = open(args.file, 'w')
        #TODO open file, check exists etc

    bbld = BlueBerryLoggerDeserializer(ofmt=args.fmt, ofile=ofile)
    nentries = args.num

    event = asyncio.Event()
    def response_handler(sender, data):
        if sender !=  str(uid):
            print_dbg('unexpected notify response from', 
                    sender, 'expected', uid)
            return

        done = bbld.putb(data)
        if not done and nentries is not None:
            done = bbld.msgCount >= nentries
        if done:
            print_dbg('End of log. Fetched', bbld.msgCount, 'entries')
            event.set()

    async with BleakClient(args.address, loop=loop) as client:
        x = await client.is_connected()
        if args.rtd:    
            enabled = await bbl.read_u32(UUIDS.C_CFG_LOG_ENABLE)
            if not enabled:
                die('logging must be enabled for real-time data (rtd)')

        await client.start_notify(uid, response_handler)
        await event.wait()
        await client.stop_notify(uid)




def parse_args():
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

    parser.add_argument('--version',
            action='store_true',
            help='show version info and exit')

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
    sp.set_defaults(_actionfunc=do_scan)
    sps.append(sp)

    # ---- CONFIG READ ------------------------------------------------------
    sp = subparsers.add_parser('config-read', 
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
            description='configure device')
    sp.set_defaults(_actionfunc=do_config_write)
    cfa = sp.add_argument_group('Config fields', 
            description='show config if none provided')
    #gsensors = sp.add_mutually_exclusive_group()

    sensor_names = list(SENSORS.keys())
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
        sp.add_argument('--debug',
               action='store_true',
               default=False, 
               help='Extra debug output')

        sp.format_help()

    args = parser.parse_args()


    if args.help:
        for sp in sps:
           print(sp.format_help())
           print(sp.format_usage())

        parser.exit()

    if 'verbose' not in args:
        args.verbose = 0

    if 'debug' not in args:
        args.debug = False

    return args

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


def main():
    args = parse_args()

    level = args.verbose
    if level <= 0:
       #level = logging.NOTSET
       level = logging.WARNING
    else:
        level = logging.DEBUG
    logging.getLogger().setLevel(level)
    _logger.setLevel(level)

    print_dbg(args)

    if args.version: 
        print_versions()
        exit(0)

    if args.debug:
        #import os
        #os.environ["PYTHONASYNCIODEBUG"] = str(1)
        print('----- VERSIONS ----')
        print_versions()

    if '_actionfunc' in args:
        loop = asyncio.get_event_loop()
        loop.run_until_complete(args._actionfunc(loop, args))


if __name__ == '__main__':
    main()

