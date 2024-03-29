import asyncio
import logging
from collections import OrderedDict
from platform import system
from types import SimpleNamespace

from bleak import BleakClient, BleakScanner
from bleak.exc import BleakError

if system() == "Linux":
    from bblogger.conn_params import verify_configured
    verify_configured()

from bblogger.defs import SENSORS, CMD_OPCODE, CMD_RESP, UUIDS, PASSCODE_STATUS, enum2str
from bblogger.deserialize import BlueBerryDeserializer
from bblogger.outputwriter import mk_OutputWriter

logger = logging.getLogger(__name__)


class ATimeoutEvent(asyncio.Event):
    """ 
    Same as asyncio.Event but wait has a timeout option like threading.Event 
    """

    async def wait(self, timeout=None):
        """ return True on success, False on timeout """
        if timeout is None:
            await super().wait()
            return True

        try:
            await asyncio.wait_for(super().wait(), timeout)
        except asyncio.TimeoutError:
            return False

        return True

class BlueBerryClient():
    """
    BlueBerry logger Bluetooth LE Client
    """

    def __init__(self, *args, **kwargs):
        address = kwargs.get("address")
        if address is None:
            raise ValueError("invalid address")
        self._password = kwargs.get("password")

        timeout = kwargs.get("timeout", 5.0)
        self._bc = BleakClient(address, timeout=timeout)
        self._evt_cmd = ATimeoutEvent()
        self._evt_fetch = ATimeoutEvent()

        self._err_fetch = None

        try:
            self._bc.set_disconnected_callback(self._on_disconnect)
        # not in all backend (yet). will work without it but might hang forever
        except NotImplementedError:
            logger.warning("set_disconnected_callback not supported")
        # "fix" for bug in bleak MacOS backend version 0.7.x?
        except AttributeError:
            logger.warning("set_disconnected_callback not set")

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self._bc.disconnect()

    def _on_disconnect(self, client, _x=None):
        # _x only in bleak > 0.6
        if not client is self._bc:
            logger.warning(
                "Unexpected disconnect callback from {} (self:{})".format(
                    client.address, self._bc.address
                )
            )
            return
        # abort if someone is waiting on notifications and device disconnect
        if not self._evt_cmd.is_set():
            self._evt_cmd.set()

        if not self._evt_fetch.is_set():
            self._evt_fetch.set()

    async def connect(self):
        # called on enter
        await self._bc.connect()
        # TODO unlock only needed for same operations do it when needed
        await self._unlock(self._password)
        return True

    async def _unlock(self, password):
        """
        unlock or "init" device. 
        note: might set password if provided and BB device 
        passcode state is INIT (directly after power on).
        passcode status can not be INIT for some operations like fetch (read log).

        """

        rc = await self._pw_status()
        logger.debug("Unlock/init: password/passcode state {}".format(rc))

        if rc == PASSCODE_STATUS.INIT:
            if password:
                await self._pw_write(password)
                logger.debug("Password protection enabled")
            else:
                # writing to log enable characteristic will change state to
                # DISABLED as a side effect. also logging is disabled after
                # power on
                #val = await self._read_u32(UUIDS.C_CFG_LOG_ENABLE)
                await self._write_u32(UUIDS.C_CFG_LOG_ENABLE, 0)
                logger.debug("Password protection disabled")

        elif rc == PASSCODE_STATUS.UNVERIFIED:
            if password is None:
                await self._bc.disconnect()
                raise ValueError("Password needed for this device")
            await self._pw_write(password)
        else:
            # password not needed for this device
            pass


    async def _write_u32(self, cuuid, val):
        val = int(val)
        data = val.to_bytes(4, byteorder="little", signed=False)
        data = bytearray(data)  # fixes bug(!?) in txdbus ver 1.1.1
        await self._bc.write_gatt_char(cuuid, data, response=True)

    async def _read_u32(self, cuuid):
        ba = await self._bc.read_gatt_char(cuuid)
        assert len(ba) == 4
        return int.from_bytes(ba, byteorder="little", signed=False)

    async def _read_str(self, cuuid):
        """ read string """
        ba = await self._bc.read_gatt_char(cuuid)
        return ba.decode("utf-8") # or ascii

    async def _cmd(self, txdata, rxsize=None):
        """ first byte in txdata is the cmd id """
        txuuid = UUIDS.C_CMD_TX
        rxuuid = UUIDS.C_CMD_RX
        # bytes object not supported in txdbus
        txdata = bytearray(txdata)
        rxdata = bytearray()
        if not rxsize:
            return await self._bc.write_gatt_char(txuuid, txdata, response=True)

        self._evt_cmd.clear()

        def response_handler(sender, data):
            rxdata.extend(data)
            logger.debug("cmd RXD:{}".format(data))
            self._evt_cmd.set()

        await self._bc.start_notify(rxuuid, response_handler)
        await self._bc.write_gatt_char(txuuid, txdata, response=True)

        if not await self._evt_cmd.wait(6):
            logger.error("notification timeout")

        # hide misleading error on unexpected disconnect
        if self._bc.is_connected:
            await self._bc.stop_notify(rxuuid)
        else:
            logger.warning("Unexpected disconnect")

        await asyncio.sleep(2)  # TODO remove!?

        assert len(rxdata) == rxsize

        if rxsize and rxdata[0] != (txdata[0] | 0x80):
            raise RuntimeError("Unexpected cmd id in response {}".format(rxdata))

        return rxdata

    async def _pw_write(self, s):
        """ password write.
        if pw_status is "init", set new password, 
        if pw_status="unverified", unlock device.

        Password must be 8 chars and ascii only
        """
        data = bytearray([CMD_OPCODE.SET_PASSCODE])
        assert len(s) == 8
        data.extend(s)
        await self._cmd(data)

    async def _pw_status(self):
        """ get password status """
        rsp = await self._cmd([CMD_OPCODE.GET_PASSCODE_STATE], 2)
        return rsp[1]

    async def set_password(self, password):
        if password is None:
            raise ValueError("No new password provided")

        rc = await self._pw_status()
        if rc == PASSCODE_STATUS.INIT:
            await self._pw_write(password)
            logger.debug("Password protection enabled")
        else:
            raise RuntimeError("Device not in init mode. Please power cycle device")
        # TODO verify success

    async def blink(self, n=1):
        """ blink LED on device """
        assert n > 0
        while n:
            await self._cmd([CMD_OPCODE.BLINK_LED])
            n = n - 1
            if n > 0:
                await asyncio.sleep(1)

    async def config_read(self, outfile=None, fmt=None, **kwargs):

        conf = OrderedDict()

        val = await self._read_u32(UUIDS.C_CFG_LOG_ENABLE)
        conf["logging"] = bool(val)

        val = await self._read_u32(UUIDS.C_CFG_INTERVAL)
        conf["interval"] = val

        val = await self._pw_status()
        val = "{} ({})".format(val, enum2str(PASSCODE_STATUS, val))
        conf["pwstatus"] = val

        enbits = await self._read_u32(UUIDS.C_CFG_SENSOR_ENABLE)

        for name, s in SENSORS.items():
            conf[s.apiname] = bool(s.enmask & enbits)

        out = mk_OutputWriter(outfile=outfile, fmt=fmt)
        out.write_kv(conf)

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
                logger.debug("Ignoring unknown config field '{}'".format(k))

        logging = kwargs.get("logging")
        if logging is not None:
            await self._write_u32(UUIDS.C_CFG_LOG_ENABLE, logging)

        interval = kwargs.get("interval")
        if interval is not None:
            await self._write_u32(UUIDS.C_CFG_INTERVAL, interval)

        cuuid = UUIDS.C_CFG_SENSOR_ENABLE
        if setMask or clrMask:
            enMaskOld = await self._read_u32(cuuid)
            enMaskNew = (enMaskOld & ~clrMask) | setMask
            await self._write_u32(cuuid, enMaskNew)

            logger.debug(
                "enabled sensors \
                    old=0x{:04X}, new=0x{:04X}".format(
                    enMaskOld, enMaskNew
                )
            )

    async def enter_dfu(self):
        await self._cmd([CMD_OPCODE.ENTER_DFU])

    async def device_info(self, outfile=None, fmt="txt", debug=False, **kwargs):
        if debug:
            services = await self._bc.get_services()
            for s in services:
                logger.debug("Characteristic for service: %s" % str(s))
                for c in s.characteristics:
                    logger.debug("  %s" % str(c))
        d = {}
        d["manufacturer"] = await self._read_str(UUIDS.C_MANUFACTURER)
        d["software_rev"] = await self._read_str(UUIDS.C_SOFTWARE_REV)
        d["serial_number"] = await self._read_str(UUIDS.C_SERIAL_NUMBER)

        out = mk_OutputWriter(outfile=outfile, fmt=fmt)
        out.write_kv(d)

        return d

    async def fetch(self, outfile=None, fmt="txt", rtd=False, num=None, **kwargs):
        RTD_RATE_HZ_TO_VAL = {
             1:   0,
             25:  6,
             50:  7,
            100:  8,
            200:  9,
            400: 10
        }
        uuid_ = UUIDS.C_SENSORS_LOG
        if not rtd:
            pass
        elif rtd in RTD_RATE_HZ_TO_VAL:
            #if rtd == 1:
            uuid_ = UUIDS.C_SENSORS_RTD

            rtd_rate = RTD_RATE_HZ_TO_VAL[rtd]
            await self._write_u32(UUIDS.C_CFG_RT_IMU, rtd_rate)
        else:
            raise ValueError("Invalid rtd")

        bbd = BlueBerryDeserializer(outfile=outfile, fmt=fmt)
        nentries = num

        self._evt_fetch.clear()
        self._err_fetch = None
        def response_handler(sender, data):
            # store exception and raise it later.
            # can not raise it from this conext as asyncio will only
            # print to stderr and continue execution.
            # there is probably a bettwr way of doning this.
            try:
                done = bbd.putb(data)
            except Exception as e:
                self._err_fetch = e
                done = True

            if nentries and bbd.nentries >= nentries:
                done = True

            if done:
                self._evt_fetch.set()

        await self._bc.start_notify(uuid_, response_handler)

        timeout = None  # kwargs.get('timeout', 100)
        if not await self._evt_fetch.wait(timeout):
            logger.error("Notification timeout after %d sec" % timeout)

        # hide missleading error on unexpected disconnect
        if self._bc.is_connected:
            await self._bc.stop_notify(uuid_)
        else:
            logger.warning("Unexpected disconnect")

        logger.debug("Fetched %d entries" % bbd.nentries)

        if self._err_fetch:
            logger.debug("err %s" % str(self._err_fetch))
            raise self._err_fetch

_scan = SimpleNamespace(output=None, devices={})

def _is_match(dev, advertisement_data):

    service_uuids = advertisement_data.service_uuids

    suuid = str(UUIDS.S_LOG)

    if suuid.lower() in service_uuids:
         return True

    if suuid.upper() in service_uuids:
        return True

    if "BlueBerry" in dev.name:
        logger.warning("no matching service uuid but matching name {}".format(dev))
        return True

    return False

def _scanner_callback(dev, advertisement_data):
    global _scan

    if not _is_match(dev, advertisement_data):
        logger.debug("ignoring device={}".format(dev))
        return

    if dev.address in _scan.devices:
        # already printed
        return
    _scan.devices[dev.address] = dev

    logger.debug("details={}, metadata={}".format(dev.details, dev.metadata))
    row = (dev.address, str(dev.rssi), dev.name)

    _scan.output.write_row(row)


async def scan(outfile=None, fmt=None, timeout=None, **kwargs):
    global _scan

    _scan.output = mk_OutputWriter(
        outfile = outfile,
        fmt = fmt,
        header=["ADDR", "RSSI", "NAME"],
        colwidths=[20, 10, 4]
    )

    scanner = BleakScanner(_scanner_callback)

    await scanner.start()

    try:
        if timeout:
            await asyncio.sleep(timeout)
        else:
            while True:
                await asyncio.sleep(1)

    except KeyboardInterrupt:
        pass

    await scanner.stop()

