import asyncio
import logging
import time
from sys import platform
from os.path import join as path_join
from os.path import getsize, realpath
from shutil import rmtree
from tempfile import mkdtemp
from binascii import crc32
from uuid import UUID
from random import randint

# Nordic libraries
from nordicsemi.dfu.package import Package

from nordicsemi.dfu.dfu_transport import (
    OP_CODE,
    RES_CODE,
    OBJ_TYPE,
    operation_txd_pack,
    operation_rxd_unpack,
    OperationResponseTimeoutError,
    OperationResCodeError,
    ValidationException,
    NordicSemiException,
)

from bleak import BleakClient, discover
from bleak.exc import BleakError

logger = logging.getLogger(__name__)


class _UUIDWithStrCmp(UUID):
    """ Same as UUID but compares to string (not case sensitive) """

    def __cmp__(self, other):

        if not isinstance(other, UUID):

            if isinstance(other, int):
                return self.int - other

            if isinstance(other, float):
                return self.int - int(other)

            try:
                other = UUID(other)
            except Exception as e:
                logger.debug("{} != {}".format(self, other))
                return -1

        return self.int - other.int

    def __eq__(self, other):
        return self.__cmp__(other) == 0

    def __ne__(self, other):
        return self.__cmp__(other) != 0

    def __gt__(self, other):
        return self.__cmp__(other) > 0

    def __lt__(self, other):
        return self.__cmp__(other) < 0

    def __ge__(self, other):
        return self.__cmp__(other) >= 0

    def __le__(self, other):
        return self.__cmp__(other) <= 0


def _dfu_uuid(n):
    """ NRF DFU UUID """
    base = "8EC9{:04x}-F315-4F60-9FB8-838830DAEA50"
    return _UUIDWithStrCmp(base.format(n))


def _std_uuid(n):
    """ Bluetooth LE "standard" uuid """
    base = "0000{:04x}-0000-1000-8000-00805F9B34FB"
    return _UUIDWithStrCmp(base.format(n))


class BLE_UUID:
    """
    """

    # fmt: off
    S_GENERIC_SERVICE            = _std_uuid(0x1800)
    S_GENERIC_ATTRIBUTE          = _std_uuid(0x1801)
    S_NORDIC_SEMICONDUCTOR_ASA   = _std_uuid(0xFE59)
    S_GENERIC_ATTRIBUTE_PROFILE  = _std_uuid(0x1801)
    # Buttonless characteristics. Buttonless DFU without bonds 	
    C_DFU_BUTTONLESS_UNBONDED    = _dfu_uuid(0x0003)
    # Secure Buttonless DFU characteristic with bond sharing from SDK 14 or newer.
    C_DFU_BUTTONLESS_BONDED      = _dfu_uuid(0x0004)
    # service changed characteristic
    C_SERVICE_CHANGED            = _std_uuid(0x2A05)
    # Commands with OP_CODE. aka CP_UUID 
    C_DFU_CONTROL_POINT          = _dfu_uuid(0x0001)
    # aka DP_UUID 
    C_DFU_PACKET_DATA            = _dfu_uuid(0x0002)
    # fmt: on


class BleAddress:
    """
    NRF "unbounded buttonless" DFU increments the BLE app address with one.
    i.e. if the address when in application is `00:00:00:00:00:00`
    the address when entered bootloader (DFU) is `00:00:00:00:00:01`
    """

    def __init__(self, x, n=0):
        if isinstance(x, BleAddress):
            self._int = x._int
        elif isinstance(x, int):
            self._int = x
        else:
            s = x
            s = s.replace(":", "")
            s = s.replace("-", "")
            ba = bytes.fromhex(s)
            if len(ba) != 6:
                raise ValueError("Invalid BLE address string")

            self._int = int.from_bytes(ba, byteorder="big")

        if n:
            # python int underflow works as unsigned int underflow in C
            self._int = (self._int + n) & 0xFFFFFFFFFFFF

    def __str__(self):
        # return ba.hex(":") # only works in python >= 3.8
        ba = int.to_bytes(self._int, length=6, byteorder="big")
        return ":".join("{:02x}".format(x) for x in ba)

    def __cmp__(self, other):
        if not isinstance(other, BleAddress):
            try:
                other = BleAddress(other)
            except Exception as e:
                logger.warning("Bad BleAddress compare {} != {}".format(self, other))
                return -1

        return self._int - other._int

    def __eq__(self, other):
        return self.__cmp__(other) == 0

    def __ne__(self, other):
        return self.__cmp__(other) != 0

    def __gt__(self, other):
        return self.__cmp__(other) > 0

    def __lt__(self, other):
        return self.__cmp__(other) < 0

    def __ge__(self, other):
        return self.__cmp__(other) >= 0

    def __le__(self, other):
        return self.__cmp__(other) <= 0

    def dfu_addr(self):
        return BleAddress(self._int, n=1)

    def app_addr(self):
        return BleAddress(self._int, n=-1)


def app_addr_to_dfu_addr(app_addr):

    app_addr = BleAddress(app_addr)
    dfu_addr = app_addr.dfu_addr()
    return dfu_addr


class _ATimeoutEvent(asyncio.Event):
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


class _ATimeoutQueue(asyncio.Queue):
    """ 
    Same as asyncio.Queue but get has a timeout option like queue.Queue 
    but raises asyncio.TimeoutError and not queue.Empty Exception.
    """

    async def get(self, timeout=None):
        """ on timeout raises asyncio.TimeoutError not queue.Empty """
        if timeout is None:
            return await super().get()
        else:
            return await asyncio.wait_for(super().get(), timeout)


class DfuImage:
    """ Paths to a binary(firmware) file with init_packet """

    def __init__(self, unpacked_zip, firmware):
        self.init_packet = path_join(unpacked_zip, firmware.dat_file)
        self.bin_file = path_join(unpacked_zip, firmware.bin_file)


class DfuImagePkg:
    # TODO this class not needed!? either add this to class Manifest
    # or extend it like `ManifestWithPaths(Manifest)`
    """ Class to abstract the DFU zip Package structure and only expose
    init_packet and binary file paths. """

    def __init__(self, zip_file_path):
        """
        @param zip_file_path: Path to the zip file with the firmware to upgrade
        """
        zip_file_path = realpath(zip_file_path)
        print(zip_file_path)

        self.temp_dir = mkdtemp(prefix="nrf_dfu_")
        self.unpacked_zip = path_join(self.temp_dir, "unpacked_zip")
        self.manifest = Package.unpack_package(zip_file_path, self.unpacked_zip)

        self.images = {}

        if self.manifest.softdevice_bootloader:
            k = "softdevice_bootloader"
            self.images[k] = DfuImage(
                self.unpacked_zip, self.manifest.softdevice_bootloader
            )

        if self.manifest.softdevice:
            k = "softdevice"
            self.images[k] = DfuImage(self.unpacked_zip, self.manifest.softdevice)

        if self.manifest.bootloader:
            k = "bootloader"
            self.images[k] = DfuImage(self.unpacked_zip, self.manifest.bootloader)

        if self.manifest.application:
            k = "application"
            self.images[k] = DfuImage(self.unpacked_zip, self.manifest.application)

    def __del__(self):
        """
        Destructor removes the temporary directory for the unpacked zip
        :return:
        """
        logger.debug("Removing {}".format(self.temp_dir))
        rmtree(self.temp_dir)

    def get_total_size(self):
        total_size = 0
        for name, image in self.images.items():
            total_size += getsize(image.bin_file)
        return total_size


class DfuDevice:
    """
    class represents a device already in DFU
    """

    def __init__(self, *args, **kwargs):
        self.address = kwargs.get("address")
        if self.address is None:
            raise ValueError("invalid address")

        timeout = kwargs.get("timeout", 10)
        self._bleclnt = BleakClient(self.address, timeout=timeout)

        # TODO what packet_size? 20 seems small --> slow
        # packet size ATT_MTU_DEFAULT - 3
        # ATT_MTU_DEFAULT = driver.GATT_MTU_SIZE_DEFAULT
        # #define GATT_MTU_SIZE_DEFAULT 23
        self.packet_size = 20

        self._cp_notif_evt = asyncio.Event()
        self._cp_notif_data = []

        self.prn = 0  # TODO prn not yet supported
        self.RETRIES_NUMBER = 3

    async def connect(self):
        logger.debug("Connecting {}...".format(self.address))
        await self._bleclnt.connect()
        await self._bleclnt.start_notify(
            BLE_UUID.C_DFU_CONTROL_POINT, self._on_cp_notif
        )

    async def disconnect(self):
        logger.debug("Disconnecting {} ...".format(self.address))
        await self._bleclnt.disconnect()

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.disconnect()

    def _on_cp_notif(self, sender, data):
        cpuuid = BLE_UUID.C_DFU_CONTROL_POINT
        self._cp_notif_data.append(data)
        self._cp_notif_evt.set()

    async def cp_cmd(self, opcode, **kwargs):
        return await asyncio.wait_for(self.__cp_cmd(opcode, **kwargs), timeout=20)

    async def __cp_cmd(self, opcode, **kwargs):
        """ 
        control point (cp) characteristic command - handles request, 
        parses response and check success.
        returns payload (if any).

        assumes payload fits in a single transfer/packet.

        note: enable and disable control point notifications for every command/operation do not work.
        unclear why - have not investigated it.
        
        """
        cpuuid = BLE_UUID.C_DFU_CONTROL_POINT
        txdata = operation_txd_pack(opcode, **kwargs)
        if not isinstance(txdata, bytearray):
            # bytes object not supported in txdbus
            txdata = bytearray(txdata)

        if len(self._cp_notif_data):
            logger.warning("Unread control point notifications")
            self._cp_notif_data = []

        self._cp_notif_evt.clear()
        logger.debug("cmd {} TXD:{}".format(opcode, txdata))
        await self._bleclnt.write_gatt_char(cpuuid, txdata, response=True)

        try:
            await asyncio.wait_for(self._cp_notif_evt.wait(), timeout=10)
        except asyncio.TimeoutError:
            raise OperationResponseTimeoutError("CP Operation {}".format(opcode))

        rxdata = self._cp_notif_data.pop(0)  # pop first element
        logger.debug("cmd {} RXD:{}".format(opcode, rxdata))
        return operation_rxd_unpack(opcode, rxdata)

    async def _validate_crc(self, crc, offset):
        response = await self.cp_cmd(OP_CODE.CRC_GET)
        if crc != response["crc"]:
            raise ValidationException(
                "Failed CRC validation.\n"
                + "Expected: {} Received: {}.".format(crc, response["crc"])
            )
        if offset != response["offset"]:
            raise ValidationException(
                "Failed offset validation.\n"
                + "Expected: {} Received: {}.".format(offset, response["offset"])
            )

    async def __stream_data(self, data, crc=0, offset=0):
        """ write to package data characteristic (aka DP_UUID or data_point) in
        chunks and verify success"""
        logger.debug(
            "BLE: Streaming Data: len:{0} offset:{1} crc:0x{2:08X}".format(
                len(data), offset, crc
            )
        )

        current_pnr = 0
        for i in range(0, len(data), self.packet_size):
            packet = data[i : i + self.packet_size]
            await self._bleclnt.write_gatt_char(
                BLE_UUID.C_DFU_PACKET_DATA, packet, response=True
            )
            crc = crc32(packet, crc) & 0xFFFFFFFF
            offset += len(packet)
            current_pnr += 1
            if self.prn == current_pnr:
                current_pnr = 0
                # TODO read CRC from CONTROL_POINT notifications

        await self._validate_crc(crc, offset)

        return crc

    async def send_init_packet(self, init_packet):
        async def try_to_recover():
            if response["offset"] == 0 or response["offset"] > len(init_packet):
                # There is no init packet or present init packet is too long.
                return False

            expected_crc = crc32(init_packet[: response["offset"]]) & 0xFFFFFFFF

            if expected_crc != response["crc"]:
                # Present init packet is invalid.
                return False

            if len(init_packet) > response["offset"]:
                # Send missing part.
                try:
                    await self.__stream_data(
                        data=init_packet[response["offset"] :],
                        crc=expected_crc,
                        offset=response["offset"],
                    )
                except ValidationException:
                    return False

            await self.cp_cmd(OP_CODE.OBJ_EXECUTE)
            return True

        response = await self.cp_cmd(OP_CODE.OBJ_SELECT, obj_type=OBJ_TYPE.COMMAND)
        if len(init_packet) > response["max_size"]:
            raise Exception("Init command is too long")

        if await try_to_recover():
            return

        for r in range(self.RETRIES_NUMBER):
            try:
                # was: self.__create_command(len(init_packet))
                await self.cp_cmd(
                    OP_CODE.OBJ_CREATE,
                    obj_type=OBJ_TYPE.COMMAND,
                    size=len(init_packet),
                )
                await self.__stream_data(data=init_packet)
                # was: self.__execute()
                await self.cp_cmd(OP_CODE.OBJ_EXECUTE)
            except ValidationException:
                logger.debug("attempt failed")
            break
        else:
            raise NordicSemiException("Failed to send init packet")

    async def send_firmware(self, firmware):
        async def try_to_recover():
            if response["offset"] == 0:
                # Nothing to recover
                return

            expected_crc = crc32(firmware[: response["offset"]]) & 0xFFFFFFFF
            remainder = response["offset"] % response["max_size"]

            if expected_crc != response["crc"]:
                # Invalid CRC. Remove corrupted data.
                response["offset"] -= (
                    remainder if remainder != 0 else response["max_size"]
                )
                response["crc"] = crc32(firmware[: response["offset"]]) & 0xFFFFFFFF
                return

            if (remainder != 0) and (response["offset"] != len(firmware)):
                # Send rest of the page.
                try:
                    to_send = firmware[
                        response["offset"] : response["offset"]
                        + response["max_size"]
                        - remainder
                    ]
                    response["crc"] = await self.__stream_data(
                        data=to_send, crc=response["crc"], offset=response["offset"]
                    )
                    response["offset"] += len(to_send)
                except ValidationException:
                    # Remove corrupted data.
                    response["offset"] -= remainder
                    response["crc"] = crc32(firmware[: response["offset"]]) & 0xFFFFFFFF
                    return

            await self.cp_cmd(OP_CODE.OBJ_EXECUTE)
            logger.info("progress at {}".format(response["offset"]))

        response = await self.cp_cmd(OP_CODE.OBJ_SELECT, obj_type=OBJ_TYPE.DATA)
        await try_to_recover()

        for i in range(response["offset"], len(firmware), response["max_size"]):
            data = firmware[i : i + response["max_size"]]
            for r in range(self.RETRIES_NUMBER):
                try:
                    await self.cp_cmd(
                        OP_CODE.OBJ_CREATE, obj_type=OBJ_TYPE.DATA, size=len(data)
                    )
                    response["crc"] = await self.__stream_data(
                        data=data, crc=response["crc"], offset=i
                    )
                    await self.cp_cmd(OP_CODE.OBJ_EXECUTE)
                except ValidationException:
                    pass
                break
            else:
                raise NordicSemiException("Failed to send firmware")
            logger.info("progress at {}".format(len(data)))

    async def send_image_package(self, imgpkg):
        """
        @imgpkg a DfuImagePkg instance
        """
        for name, image in imgpkg.images.items():
            start_time = time.time()

            logger.info("Sending init packet for {} ...".format(name))
            with open(image.init_packet, "rb") as f:
                data = f.read()
                await self.send_init_packet(data)

            logger.info("Sending firmware bin file for {}...".format(name))
            with open(image.bin_file, "rb") as f:
                data = f.read()
                await self.send_firmware(data)

            end_time = time.time()
            delta_time = end_time - start_time
            logger.info("Image sent for {} in {}s".format(name, delta_time))

    async def _ping(self):
        """ Not needed in BLE transport """
        tx_id = randint(0, 255)
        try:
            rx_id = self.cp_cmd(OP_CODE.PING, ping_id=tx_id)
        except OperationResCodeError as e:
            logger.debug("ignoring ping response error {}".format(e))
            # Returning an error code is seen as good enough. The bootloader is up and running
            return True
        logger.debug("ping tx_id:{} rx_id:{}".format(tx_id, rx_id))

        expected_rx_id = (tx_id + 1) % 256
        return bool(rx_id == expected_rx_id)


async def scan_dfu_devices(app_address=None, timeout=10):
    """ Scan (discover) devices already in bootloader """
    devices = []
    candidates = await discover(timeout=timeout)
    for d in candidates:
        match = None
        if "uuids" in d.metadata:
            advertised = d.metadata["uuids"]  # service uuids
            # logger.debug(str(BLE_UUID.S_NORDIC_SEMICONDUCTOR_ASA) + " in " + str(advertised))
            if BLE_UUID.S_NORDIC_SEMICONDUCTOR_ASA in advertised:
                match = "nordic semi asa"
            elif BLE_UUID.C_DFU_BUTTONLESS_BONDED in advertised:
                match = "DFU bonded"
            elif BLE_UUID.C_DFU_BUTTONLESS_UNBONDED in advertised:
                match = "DFU unbonded"

        if match:
            logger.info(
                "dfu device: {}  rssi:{} dBm  name:{} ({})".format(
                    d.address, d.rssi, d.name, match
                )
            )
            devices.append(d)
        else:
            logger.debug("ignoring device={}".format(d))

    return devices


if platform == "darwin":
    from plistlib import load as plist_load

    async def __get_addr_from_CoreBluetoothCache():
        """ returns dict {MacOS_device_UUID : BLE_MAC_address } """

        path = "/Library/Preferences/com.apple.Bluetooth.plist"
        try:
            with open(path, "rb") as f:
                plist = plist_load(f)
        except FileNotFoundError:
            logger.warning("{} do not exist".format(path))
            return {}

        if "CoreBluetoothCache" not in plist:
            logger.debug("No CoreBluetoothCache in {}".format(path))
            return {}

        cbcache = plist["CoreBluetoothCache"]

        if cbcache is None:
            return {}

        uuid_to_addr = {}

        for devuuid, devinfo in cbcache.items():
            if "DeviceAddress" not in devinfo:
                continue

            addr = devinfo["DeviceAddress"]
            # addr = addr.replace('-', ':')
            uuid_to_addr[UUID(devuuid)] = BleAddress(addr)

        return uuid_to_addr

    async def __find_unbounded_dfu_osid(app_osid):
        """ find MacOS BLE device UUID (called `osid` here to avoid confusing
        with MAC address and BLE service/characteristic uuid:s which are
        unrelated) for a device in unbounded DFU mode. i.e. the BLE MAC address
        changed to +1.

        @param app_osid the MacOS Device UUID when device is in application (not bootlaoder)
        """
        app_osid = UUID(app_osid)
        # first find the app MAC addr
        osid_to_addr = await __get_addr_from_CoreBluetoothCache()
        if app_osid not in osid_to_addr:
            raise RuntimeError("Could not find application MAC address in plist")

        app_addr = osid_to_addr[app_osid]
        dfu_addr = app_addr_to_dfu_addr(app_addr)

        # create reverse lookup dict
        addr_to_osid = {v: k for k, v in osid_to_addr.items()}
        # might alreay have it cached
        if dfu_addr in addr_to_osid:
            return addr_to_osid[dfu_addr]

        candidates = []
        all_devices = await discover(timeout=10)
        for dev_info in all_devices:
            advertised = dev_info.metadata.get("uuids")  # service uuids
            if advertised and BLE_UUID.S_NORDIC_SEMICONDUCTOR_ASA in advertised:
                candidates.append(dev_info)
            else:
                logger.debug("ignoring device {}".format(dev_info))
        # currently Bleak only support advertiesed service uuids, not characteristic uuids.
        for dev_info in candidates:
            # send a ping to candidate. this should make MacOS to write the MAC address to plist
            try:
                async with DfuDevice(address=dev_info.address) as dev:
                    success = dev._ping()
                    logger.debug(
                        "DFU ping to {} - {}".format(
                            dev_info.address, "success" if success else "failed"
                        )
                    )

            except Exception as e:
                logger.debug("Ignoring {}".format(e))

        # might take some time before plist is updated?
        for attempt in range(3):
            osid_to_addr = await __get_addr_from_CoreBluetoothCache()
            addr_to_osid = {v: k for k, v in osid_to_addr.items()}
            if dfu_addr in addr_to_osid:
                return addr_to_osid[dfu_addr]
            logger.debug("Failed attempt to find MacOS unbounded DFU device UUID")
            asyncio.sleep(1)

        raise RuntimeError("Failed to find MacOS unbounded DFU device UUID")


async def app_to_dfu_address(app_addr):
    
    if platform == "darwin":
        logger.warning("DFU on MacOS is experimental")
        dfu_addr = __find_unbounded_dfu_osid(app_osid=app_addr)
    else:
        app_addr = BleAddress(app_addr)
        dfu_addr = app_addr.dfu_addr()

    return dfu_addr

async def device_firmware_upgrade(dfu_addr, package):

    async with DfuDevice(address=str(dfu_addr)) as dev:
        imgpkg = DfuImagePkg(package)
        await dev.send_image_package(imgpkg)

