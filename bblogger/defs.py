from enum import Enum, IntEnum


# temporary fix as uuid not (yet) suported in bleak MacOS backend, only str works
# from uuid import UUID
UUID = lambda x: str(x)


class CMD_OPCODE(IntEnum):
    """ Command (request) codes (aka 'BB_LOG_CMD_...') """

    # fmt: off
    UPDATE_READ_PTR      =  0x00
    BLINK_LED            =  0x01
    ENTER_DFU            =  0x02
    CALIBRATE_GYRO       =  0x03
    CALIBRATE_COMPASS    =  0x04
    CALIBRATE_END        =  0x05
    SET_PASSCODE         =  0x06
    GET_PASSCODE_STATE   =  0x07
    SET_DISABLE_CAL_CORR =  0x08
    GET_DISABLE_CAL_CORR =  0x09
    CAL_CLEAR_TEMP_LUT   =  0x0A
    CAL_SET_TEMP_LUT_VAL =  0x0B
    CAL_SAVE_TEMP_LUT    =  0x0C
    UPDATE_GET_MEM       =  0x70
    # fmt: on


class CMD_RESP(IntEnum):
    """ Command response codes. (aka 'RESP_...')"""

    # fmt: off
    SUCCESS                     =  0x00
    ERROR                       =  0x01
    ERROR_PASSCODE_FORMAT       =  0x02
    ERROR_COMPASS_NO_MOTION     =  0x03
    ERROR_COMPASS_LARGE_MAGNET  =  0x04
    ERROR_ACCESS_DENIED         =  0x05
    ERROR_UNKNOWN_CMD           =  0x06
    COMPLETE                    =  0x80
    ERROR_CALIBRATION           =  0x81
    PROGRESS                    =  0x82
    # fmt: on


class PASSCODE_STATUS(IntEnum):
    """ Password status codes (aka 'BB_PASSCODE_...') """

    # fmt: off
    INIT       = 0x00 # the unit has not been configured yet
    UNVERIFIED = 0x01 # correct password has not been entered yet
    VERIFIED   = 0x02 # correct password has been entered
    DISABLED   = 0x03 # no password is needed
    # fmt: on


def _uuid_std(n):
    """ Bluetooth LE uuid as defined by specs """
    base = "0000{:04x}-0000-1000-8000-00805f9b34fb"
    return UUID(base.format(n))


def _uuid_bbl(n):
    base = "c9f6{:04x}-9f9b-fba4-5847-7fd701bf59f2"
    return UUID(base.format(n))


# GATT Services and Characteristics UUIDS
class UUIDS:
    # Log (Service)
    S_LOG = _uuid_bbl(0x002)
    # Real time data characteristic (protobuf)
    C_SENSORS_RTD = _uuid_bbl(0x0022)
    # Stored log characteristic (protobuf)
    C_SENSORS_LOG = _uuid_bbl(0x0021)
    # Command TX characteristic (opcode, [data])
    C_CMD_TX = _uuid_bbl(0x001A)
    # Command RX characteristic notification (rspcode, [data])
    C_CMD_RX = _uuid_bbl(0x0023)
    # log on/off (uint32)
    C_CFG_LOG_ENABLE = _uuid_bbl(0x00)
    # bitfield (uint32)
    C_CFG_SENSOR_ENABLE = _uuid_bbl(0x01)
    # log interval in seconds (uint32)
    C_CFG_INTERVAL = _uuid_bbl(0x02)
    # rt imu mode (off = 0, 25hz = 6, 50hz = 7, 100hz = 8, 200hz = 9, 400hz = 10) (uint32)
    C_CFG_RT_IMU = _uuid_bbl(0x03)
    #
    # Device Information (Service)
    S_DEVICE_INFORMATION = _uuid_std(0x180A)
    # Serial Number (String)
    C_SERIAL_NUMBER = _uuid_std(0x2A25)
    # Software Revision (String)
    C_SOFTWARE_REV = _uuid_std(0x2A28)
    # Manufacturer Name (String)
    C_MANUFACTURER = _uuid_std(0x2A29)
    #
    # Generic Attribute Profile (Service)
    S_GENERIC_ATTRIBUTE_PROFILE = _uuid_std(0x1801)
    # Service Changed ()
    C_SERVICE_CHANGED = _uuid_std(0x2A05)


class _BlueBerryLogEntryField:
    def __init__(
        self,
        enmask,
        pbname,
        symbol="",
        unit="",
        tounit=None,
        alias=None,
        subfields=None,
        txtfmt="4.3f",
    ):
        """
        Args: 
            enmask: enable bit mask
            pbname: protobuf descriptor field name 
            symbol: SI symbol or similar identifier
            tounit: func to convert from raw value
        """

        self.enmask = enmask
        self.pbname = pbname
        self.symbol = symbol
        self.unit = unit
        self.tounit = tounit
        self.txtfmt = "{{0: {}}}".format(txtfmt)
        self.apiname = alias if alias else pbname

        if subfields:
            self.colnames = ["{}_{}".format(self.symbol, x) for x in subfields]
        else:
            self.colnames = [self.symbol]

    def is_configurable(self):
        return self.enmask is not None


class BlueBerryLogEntryFields(Enum):
    """
    Log entry data field - i.e. a sensor value in most cases.
    Inherit from enum for easy iteration

    Names used in iOS app csv output:
        Unix time stamp,
        Acceleration x (m/s²),
        Acceleration y (m/s²),
        Acceleration z (m/s²),
        Magnetic field x (µT),
        Magnetic field y (µT),
        Magnetic field z (µT),
        Rotation rate x (°/s),
        Rotation rate y (°/s),
        Rotation rate z (°/s),
        Illuminance (lux),
        Pressure (hPa),
        Rel. humidity (%),
        Temperature (C),
        UV index,
        Battery voltage (V)
    """

    PRESSURE = _BlueBerryLogEntryField(
        enmask=0x0001,
        pbname="pressure",
        symbol="p",
        unit="hPa",
        tounit=lambda x: x / 100.0,
    )
    HUMIDITY = _BlueBerryLogEntryField(
        enmask=0x0002,
        pbname="rh",
        symbol="rh",
        unit="%",
        tounit=lambda x: x / 10.0,
        alias="humid",
    )
    TEMPERATURE = _BlueBerryLogEntryField(
        enmask=0x0004,
        pbname="temperature",
        symbol="t",
        unit="C",
        tounit=lambda x: x / 1000.0,
        alias="temp",
    )
    COMPASS = _BlueBerryLogEntryField(
        enmask=0x0008,
        pbname="compass",
        symbol="m",
        unit="uT",
        tounit=lambda x: x * 4915.0 / 32768.0,
        subfields=("x", "y", "z"),
    )
    ACCELEROMETER = _BlueBerryLogEntryField(
        enmask=0x0010,
        pbname="accelerometer",
        symbol="a",
        unit="m/s^2",
        tounit=lambda x: x * 2.0 * 9.81 / 32768.0,
        alias="accel",
        subfields=("x", "y", "z"),
    )
    GYRO = _BlueBerryLogEntryField(
        enmask=0x0020,
        pbname="gyro",
        symbol="g",
        unit="dps",
        tounit=lambda x: x * 250.0 / 32768.0,
        subfields=("x", "y", "z"),
    )
    LUX = _BlueBerryLogEntryField(
        enmask=0x0040,
        pbname="lux",
        symbol="L",
        unit="lux",
        tounit=lambda x: x / 1000.0,
        # alias="illuminance"
    )
    UVI = _BlueBerryLogEntryField(
        enmask=0x0100,
        pbname="uvi",
        symbol="UVi",
        unit="",  # FIXME
        tounit=lambda x: x / 1000.0,
    )
    BATVOLT = _BlueBerryLogEntryField(
        enmask=0x0200,
        pbname="battery_mv",
        symbol="bat",
        unit="V",
        tounit=lambda x: x / 1000.0,
        alias="batvolt",
    )
    TIME = _BlueBerryLogEntryField(
        enmask=None,
        pbname="timestamp",
        symbol="TS",
        unit="s",
        tounit=lambda x: float(x),
        txtfmt="7.0f",
    )
    _GPIO0ADC = _BlueBerryLogEntryField(
        enmask=None,
        pbname="gpio0_mv",
        symbol="gp0",
        unit="mV",
        tounit=lambda x: x * 1.0,
    )
    _GPIO1ADC = _BlueBerryLogEntryField(
        enmask=None,
        pbname="gpio1_mv",
        symbol="gp1",
        unit="mV",
        tounit=lambda x: x * 1.0,
    )

    _INT_GPIO0 = _BlueBerryLogEntryField(
        enmask=None,
        pbname="int_gpio0",
        symbol="int0",
        unit="",
        tounit=lambda x: x,
    )
    _INT_GPIO1 = _BlueBerryLogEntryField(
        enmask=None,
        pbname="int_gpio1",
        symbol="int1",
        unit="",
        tounit=lambda x: x,
    )
    _INT_ACC = _BlueBerryLogEntryField(
        enmask=None,
        pbname="int_acc",
        symbol="iacc1",
        unit="",
        tounit=lambda x: x,
    )

def enum2str(enumclass, val):
    """
    enumclass - a Enum class, either instance or class 
    """
    try:
        return enumclass(val).name
    except ValueError:
        return "{}.<unknown {}>".format(enumclass.__name__, val)


SENSORS = {
    x.value.apiname: x.value
    for x in BlueBerryLogEntryFields
    if x.value.is_configurable()
}
