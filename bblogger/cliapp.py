
import logging
import asyncio
import sys
import argparse


# not needed in python >= 3.6? as default dict keeps order
from collections import OrderedDict
from bblogger import BlueBerryLoggerDeserializer, \
        SENSORS, UUIDS, PW_STATUS, pw_status_to_str

from bleak import BleakClient, discover
from bleak import _logger as bleak_logger
from bleak import __version__ as bleak_version


from bleak.exc import BleakError

# logging.basicConfig(stream=sys.stderr, level=logging.ERROR,
#        format='%(levelname)s: %(message)s')
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

class BlueBerryLogger(BleakClient):

    async def write_u32(self, cuuid, val):
        val = int(val)
        data = val.to_bytes(4, byteorder='little', signed=False)
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
            # sender is str. should be uuid!?
            if sender !=  str(rxuuid):
                print_wrn('unexpected notify response from', 
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

        assert(len(rxdata) == rxsize)

        if rxsize and rxdata[0] != (txdata[0] | 0x80):
            raise RuntimeError('Unexpected cmd id in respone')

        return rxdata

    async def pw_write(self, s):
        ''' if pw_status is "init", set new password, 
        if pw_status="unverified", unlock device.

        Password must be 8 chars and ascii only
        '''
        data = bytearray([0x06]) # 0x06 = command code 
        assert(len(s) == 8)
        data.extend(s)
        await self.cmd(data)

    
    async def pw_status(self):
        ''' password status '''
        rsp = await self.cmd([0x07], 2)
        return rsp[1]


async def bbl_connect(loop, args, unlock=False):

    bbl = BlueBerryLogger(args.address, loop=loop)

    try:
        await bbl.connect()
        await bbl.is_connected() # needed?
    except BleakError as e:
        # provide a better error message then dual thread backtrace...
        die('Failed to connect. Device exitst?', e)

    if unlock:
        rc = await bbl.pw_status()
        if rc == PW_STATUS.UNVERIFIED: 
            if 'password' not in args:
                await bbl.disconnect()
                die('Password needed for this device and operation')
            await bbl.pw_write(args.password)
        else:
            pass # password not needed for this device

    return bbl

async def do_scan(loop, args):
    devices = await discover()
    for d in devices:
        match = False
        if 'uuids' in d.metadata:
            advertised = d.metadata['uuids']
            suuid = str(UUIDS.S_LOG)
            if suuid.lower() in advertised or suuid.upper() in advertised:
                match = True
            
        elif 'BlueBerry' in d.name:
            print_wrn('no mathcing service uuid but matching name:', d)
            match = True
        else:
            print_dbg('ignoring:', d)

        if match:
            print_dbg('details:', d.details, 'metadata:', d.metadata) 
            print(d.address, '  ', d.rssi, 'dBm', '  ', d.name)


async def do_blink(loop, args):
    assert(args.num > 0)
    bbl = await bbl_connect(loop, args)
    n = args.num
    while n:
        await bbl.cmd([0x01])
        n = n - 1
        if n > 0:
            await asyncio.sleep(1)

    await bbl.disconnect()

async def do_config_read(loop, args):

    def to_onoff(x):
        return 'on' if x else 'off'

    conf = OrderedDict()
    bbl = await bbl_connect(loop, args)

    val = await bbl.read_u32(UUIDS.C_CFG_LOG_ENABLE)
    conf['logging'] = to_onoff(val)

    val = await bbl.read_u32(UUIDS.C_CFG_INTERVAL)
    conf['interval'] = val

    val = await bbl.pw_status()
    conf['pwstatus'] = '{} ({})'.format(val, pw_status_to_str(val))

    enbits = await bbl.read_u32(UUIDS.C_CFG_SENSOR_ENABLE)
    await bbl.disconnect()

    for name, s in SENSORS.items():
        conf[s.apiName] = to_onoff(s.enmask & enbits)

    for k, v in conf.items(): 
        print('  ', k.ljust(10), ':', v)

async def do_config_write(loop, args):
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
        

    bbl = await bbl_connect(loop, args, unlock=True)
    if args.logging is not None:
        await bbl.write_u32(UUIDS.C_CFG_LOG_ENABLE, args.logging)

    if args.interval is not None:
        await bbl.write_u32(UUIDS.C_CFG_INTERVAL, args.interval)

    cuuid = UUIDS.C_CFG_SENSOR_ENABLE
    if setMask or clrMask:
        enMaskOld = await bbl.read_u32(cuuid)
        enMaskNew = (enMaskOld & ~clrMask) | setMask
        print_dbg('enabled sensors', 
                'old=0x{:04X}, new=0x{:04X}'.format(enMaskOld, enMaskNew))
        await bbl.write_u32(cuuid, enMaskNew)

    await bbl.disconnect()


async def do_set_password(loop, args):
    bbl = await bbl_connect(loop, args)
    rc = await bbl.pw_status()
    if rc == PW_STATUS.INIT:
        bbl.pw_write(args.password)
        print_dbg('Password protection enabled')
    else:
        await bbl.disconnect()
        die('Device not in init mode. Please power cycle device')

    await bbl.disconnect()
    
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
        if str(sender).upper() !=  str(uid).upper():
            print_wrn('unexpected notify response from', 
                    sender, 'expected', uid)
            return

        done = bbld.putb(data)
        if not done and nentries is not None:
            done = bbld.msgCount >= nentries
        if done:
            print_dbg('End of log. Fetched', bbld.msgCount, 'entries')
            event.set()

    bbl = await bbl_connect(loop, args, unlock=True)

    if args.rtd:    
        enabled = await bbl.read_u32(UUIDS.C_CFG_LOG_ENABLE)
        if not enabled:
            await bbl.disconnect()
            die('logging must be enabled for real-time data (rtd)')

    await bbl.start_notify(uid, response_handler)
    await event.wait()
    await bbl.stop_notify(uid)

    await bbl.disconnect()


def parse_args():
    def p_password(s):
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

    common = argparse.ArgumentParser(add_help=False)                                 
    common.add_argument('--verbose', '-v', default=0, action='count',
            help='Verbose output')

    if 0: # TODO
        common.add_argument('--timeout', 
            type=int, 
            help='Timeout in seconds. useful for batch jobs')

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

    # --- more common args for below commands -------------------------------
    common.add_argument('--password', '--pw',
            type=p_password,
            default=None, help='Password to unlock (or lock) device')
    common.add_argument('--address', '-a', 
            metavar='ADDR', 
            help='Bluetooth LE device address (or device UUID on MacOS)')

    # ---- BLINK -------------------------------------------------------------
    sp = subparsers.add_parser('blink', 
            parents = [common],
            description='Blink LED on device for physical identification')
    sp.set_defaults(_actionfunc=do_blink)

    sp.add_argument('--num', '-n', metavar='N', type=int, 
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
    sp = subparsers.add_parser('set-password', #'config-pw',
            parents = [common],
            aliases=['config-pw'],
            description='set (new) disable password. \
            requires device power cycle. empty password to disable')
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

    sp.add_argument('--fmt', default='txt', choices=['csv', 'txt'], #'pb', 'json', 
            help='Data output format')

    sp.add_argument('--num', '-n', metavar='N', type=int, 
            help='Max number of data points or log entries to fetch')
    sps.append(sp)


    args = parser.parse_args()

    if args.help:
        for sp in sps:
           print(sp.format_help())
           print() # extra linebreak

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

def set_verbose(verbose_level):
    loggers = [logging.getLogger('bblogger'), _logger]

    if verbose_level <= 0:
        level = logging.WARNING
    elif verbose_level == 2:
        level = logging.INFO
    elif verbose_level >= 3:
        level = logging.DEBUG

    if verbose_level >= 4:
        bleak_logger = logging.getLogger('bleak')
        bleak_logger.setLevel(logging.DEBUG)
        loggers.append(bleak_logger)

    # create logger
    #_logger.setLevel(logging.DEBUG)

    handler = logging.StreamHandler(sys.stderr)
    handler.setLevel(level)
    
    #formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(name)s: %(message)s')
    formatter = logging.Formatter('%(levelname)s:%(name)s:%(lineno)d: %(message)s')
    handler.setFormatter(formatter)

    for l in loggers:
        l.addHandler(handler)
        l.setLevel(logging.DEBUG)

    if verbose_level >= 3:
        print_versions()

def main():
    args = parse_args()

    set_verbose(args.verbose)
    print_dbg(args)

    if args.version: 
        print_versions()
        exit(0)

    if '_actionfunc' in args:
        loop = asyncio.get_event_loop()
        #aw = asyncio.wait_for(args._actionfunc(loop, args), args.timeout)
        #loop.run_until_complete(aw)
        loop.run_until_complete(args._actionfunc(loop, args))


if __name__ == '__main__':
    main()

