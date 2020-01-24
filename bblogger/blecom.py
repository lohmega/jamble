import asyncio
import logging
from collections import OrderedDict
from platform import system

from bleak import BleakClient, discover
from bleak.exc import BleakError

if system() == 'Linux':
    from bblogger.conn_params import verify_configured
    verify_configured()

from bblogger.deserialize import BlueBerryDeserializer, SENSORS

logger = logging.getLogger(__name__)

# temporary fix as uuid not (yet) suported in bleak MacOS backend, only str works
# from uuid import UUID
UUID = lambda x: str(x)


class ATimeoutEvent(asyncio.Event):
    ''' 
    Same as asyncio.Event but wait has a timeout option like threading.Event 
    '''

    async def wait(self, timeout=None):
        ''' return True on success, False on timeout '''
        if timeout is None:
            await super().wait()
            return True

        try:
            await asyncio.wait_for(super().wait(), timeout)
        except asyncio.TimeoutError:
            return False

        return True

# Command response codes.
CMD_RESP_CODES = {
    0x00 : 'SUCCESS',
    0x01 : 'ERROR', 
    0x02 : 'ERROR_PASSCODE_FORMAT',
    0x03 : 'ERROR_COMPASS_NO_MOTION',
    0x04 : 'ERROR_COMPASS_LARGE_MAGNET',
    0x05 : 'ERROR_ACCESS_DENIED',  # Password protected (no check if cmd is valid)
    0x06 : 'ERROR_UNKNOWN_CMD',
    0x80 : 'COMPLETE' ,
    0x81 : 'ERROR_CALIBRATION',
    0x82 : 'PROGRESS'
}
    
class PW_STATUS():
    INIT       = 0x00 
    UNVERIFIED = 0x01
    VERIFIED   = 0x02 
    DISABLED   = 0x03

PW_STATUS_TRANSLATE = {
    0x00 : 'init', #'the unit has not been configured yet',
    0x01 : 'unverified', #'the correct password has not been entered yet',
    0x02 : 'verified', #'the correct password has been entered',
    0x03 : 'disabled', #'no password is needed',
}

def pw_status_to_str(rc):
    return PW_STATUS_TRANSLATE[rc]

def _bbuuid(n):
    base='c9f6{:04x}-9f9b-fba4-5847-7fd701bf59f2'
    return UUID(base.format(n))

# GATT Services and Characteristics UUIDS
class UUIDS():
    # Log service
    S_LOG = _bbuuid(0x002)
    # Real time data characteristic
    C_SENSORS_RTD = _bbuuid(0x0022)
    # Stored log characteristic
    C_SENSORS_LOG = _bbuuid(0x0021)
    # Command TX characteristic
    C_CMD_TX = _bbuuid(0x001a)
    # Command RX characteristic (as notification)
    C_CMD_RX = _bbuuid(0x0023)
    # uint32. log on/off
    C_CFG_LOG_ENABLE = _bbuuid(0x00)
    # uint32 bitfield 
    C_CFG_SENSOR_ENABLE = _bbuuid(0x01)
    # uint32 log interval in seconds
    C_CFG_INTERVAL = _bbuuid(0x02)



class BlueBerryClient():
    '''
    BlueBerry logger Bluetooth LE Client
    '''

    def __init__(self, *args, **kwargs):
        address = kwargs.get('address')
        if address is None:
            raise ValueError('invalid address')
        self._password = kwargs.get('password')

        timeout = kwargs.get("timeout", 5.0)
        self._bc = BleakClient(address, timeout=timeout)
        self._evt_cmd = ATimeoutEvent()
        self._evt_fetch = ATimeoutEvent()

        # not in all backend (yet). will work without it but might hang forver
        try:
            self._bc.set_disconnected_callback(self._on_disconnect)
        except NotImplementedError:
            logger.warning('set_disconnected_callback not supported')

    async def __aenter__(self):
        await self._bc.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self._bc.disconnect()

    def _on_disconnect(self, client, _x=None):
        # _x only in bleak > 0.6 
        logger.warning('Device {} unexpected disconnect'.format(self._bc.address))
        if not client is self._bc:
            logger.warning('Unexpected disconnect callback from {} (self:{})'.format(client.address, self._bc.address))
            return
        # abort if someone is waiting on notifications and device disconnect
        if not self._evt_cmd.is_set():
            self._evt_cmd.set()

        if not self._evt_fetch.is_set():
            self._evt_fetch.set()

    async def connect(self, address, **kwargs):
        # called on enter
        await self._bc.connect(**kwargs)
        # TODO unlock only needed for same operations do it when needed
        await self._unlock(self._password)
        return True

    async def _unlock(self, password):
        '''
        unlock device if it requires a password
        '''
        rc = await self._pw_status()
        if rc == PW_STATUS.UNVERIFIED: 
            if password is None:
                await self._bc.disconnect()
                raise ValueError('Password needed for this device')
            await self._pw_write(password)
        else:
            pass # password not needed for this device
        return rc


    async def _write_u32(self, cuuid, val):
        val = int(val)
        data = val.to_bytes(4, byteorder='little', signed=False)
        data = bytearray(data) # fixes bug(!?) in txdbus ver 1.1.1 
        await self._bc.write_gatt_char(cuuid, data, response=True)

    async def _read_u32(self, cuuid):
        ba = await self._bc.read_gatt_char(cuuid)
        assert(len(ba) == 4)
        return int.from_bytes(ba, byteorder='little', signed=False)

    async def _cmd(self, txdata, rxsize=None):
        ''' first byte in txdata is the cmd id '''
        txuuid = UUIDS.C_CMD_TX
        rxuuid = UUIDS.C_CMD_RX 

        txdata = bytearray(txdata)
        rxdata = bytearray()
        if not rxsize:
            return await self._bc.write_gatt_char(txuuid, txdata, response=True)

        self._evt_cmd.clear()

        def response_handler(sender, data):
            # sender is str. should be uuid!?
            if str(sender).lower() !=  str(rxuuid).lower():
                logger.warning('unexpected notify response \
                        from {} expected {}'.format(sender, rxuuid))
                return
            rxdata.extend(data)
            logger.debug('cmd RXD:{}'.format(data))
            self._evt_cmd.set()

        await self._bc.start_notify(rxuuid, response_handler)
        await self._bc.write_gatt_char(txuuid, txdata, response=True)
        
        if not await self._evt_cmd.wait(6): 
            logger.error('notification timeout')

        # hide missleading error on unexpected disconnect
        if await self._bc.is_connected(): 
            await self._bc.stop_notify(rxuuid)

        await asyncio.sleep(2) # TODO remove!?

        assert(len(rxdata) == rxsize)

        if rxsize and rxdata[0] != (txdata[0] | 0x80):
            raise RuntimeError('Unexpected cmd id in respone {}'.format(rxdata))

        return rxdata

    async def _pw_write(self, s):
        ''' password write.
        if pw_status is "init", set new password, 
        if pw_status="unverified", unlock device.

        Password must be 8 chars and ascii only
        '''
        data = bytearray([0x06]) # 0x06 = command code 
        assert(len(s) == 8)
        data.extend(s)
        await self._cmd(data)

    
    async def _pw_status(self):
        ''' get password status '''
        rsp = await self._cmd([0x07], 2)
        return rsp[1]

    async def set_password(self, password):
        if password is None:
            raise ValueError('No new password provided')

        rc = await self._pw_status()
        if rc == PW_STATUS.INIT:
            await self._pw_write(password)
            logger.debug('Password protection enabled')
        else:
            raise RuntimeError('Device not in init mode. Please power cycle device')
        # TODO verify success 


    async def blink(self, n=1):
        ''' blink LED on device '''
        assert(n > 0)
        while n:
            await self._cmd([0x01])
            n = n - 1
            if n > 0:
                await asyncio.sleep(1)

    async def config_read(self):

        conf = OrderedDict()

        val = await self._read_u32(UUIDS.C_CFG_LOG_ENABLE)
        conf['logging'] = bool(val)

        val = await self._read_u32(UUIDS.C_CFG_INTERVAL)
        conf['interval'] = val

        val = await self._pw_status()
        conf['pwstatus'] = val #'{} ({})'.format(val, pw_status_to_str(val))

        enbits = await self._read_u32(UUIDS.C_CFG_SENSOR_ENABLE)

        for name, s in SENSORS.items():
            conf[s.apiName] = bool(s.enmask & enbits)

        return conf

    async def config_write(self, **kwargs):
        setMask = 0
        clrMask = 0

        # sanity check all params before write
        for k, v in kwargs.items():
            if v is None:
                continue

            if k in SENSORS:
                enmask = SENSORS[k].enmask 
                if v:
                    setMask |= enmask
                else:
                    clrMask |= enmask
            else:
                logger.debug('Ignoring unknown conifg field "{}"'.format(k))

        logging = kwargs.get('logging')
        if logging is not None:
            await self._write_u32(UUIDS.C_CFG_LOG_ENABLE, logging)

        interval = kwargs.get('interval')
        if interval is not None:
            await self._write_u32(UUIDS.C_CFG_INTERVAL, interval)

        cuuid = UUIDS.C_CFG_SENSOR_ENABLE
        if setMask or clrMask:
            enMaskOld = await self._read_u32(cuuid)
            enMaskNew = (enMaskOld & ~clrMask) | setMask
            await self._write_u32(cuuid, enMaskNew)

            logger.debug('enabled sensors \
                    old=0x{:04X}, new=0x{:04X}'.format(enMaskOld, enMaskNew))



    async def fetch(self, ofile=None, rtd=False, fmt='txt', num=None, **kwargs):

        if rtd:
            uuid_ = UUIDS.C_SENSORS_RTD
        else:
            uuid_ = UUIDS.C_SENSORS_LOG

        bbd = BlueBerryDeserializer(ofmt=fmt, ofile=ofile)
        nentries = num

        self._evt_fetch.clear()
        def response_handler(sender, data):
            if str(sender).lower() !=  str(uuid_).lower():
                logger.warning('unexpected notify response \
                        from {} expected {}'.format(sender, uuid_))
                return

            done = bbd.putb(data)
            if not done and nentries is not None:
                done = bbd.nentries >= nentries
            if done:
                logger.debug('End of log. Fetched {} entries'.format(bbd.nentries))
                self._evt_fetch.set()


        if rtd:    
            enabled = await self._read_u32(UUIDS.C_CFG_LOG_ENABLE)
            if not enabled:
                raise RuntimeError('logging must be enabled for real-time data (rtd)')

        await self._bc.start_notify(uuid_, response_handler)

        timeout = None #kwargs.get('timeout', 100)
        if not await self._evt_fetch.wait(timeout): 
            logger.error('Notification timeout after %d sec' % timeout)

        # hide missleading error on unexpected disconnect
        if await self._bc.is_connected(): 
            await self._bc.stop_notify(uuid_)

        logger.debug('Fetched %d entries' % bbd.nentries)
        return bbd._data


async def scan(timeout=None, outfile=None, **kwargs):
    devices = []
    candidates = await discover(timeout=timeout)
    for d in candidates:
        match = False
        if 'uuids' in d.metadata:
            advertised = d.metadata['uuids']
            suuid = str(UUIDS.S_LOG)
            if suuid.lower() in advertised or suuid.upper() in advertised:
                match = True
        elif 'BlueBerry' in d.name:
            # Advertised UUIDs sometimes slow to retrive 
            logger.warning('no mathcing service uuid but matching name {}'.format(d))
            match = True
        else:
            logger.debug('ignoring device={}'.format(d))

        if match:
            logger.debug('details={}, metadata={}'.format(d.details, d.metadata))
            if outfile:
                print(d.address, '  ', d.rssi, 'dBm', '  ', d.name, file=outfile)
            devices.append(d)

    return devices

