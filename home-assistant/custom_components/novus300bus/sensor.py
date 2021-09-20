"""Support for reading data from a serial port."""
# region Imports
import codecs
import logging
from datetime import timedelta
from enum import Enum

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant.components.binary_sensor import (DEVICE_CLASS_PLUG,
                                                    BinarySensorEntity)
from homeassistant.components.sensor import PLATFORM_SCHEMA, SensorEntity
from homeassistant.const import (CONF_NAME, DEVICE_CLASS_TEMPERATURE,
                                 TEMP_CELSIUS)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
from homeassistant.util import Throttle
from serial import EIGHTBITS, PARITY_MARK, STOPBITS_ONE, Serial

# endregion Imports

# region Constants
_LOGGER = logging.getLogger(__name__)

CONF_SERIAL_PORT = "serial_port"
CONF_BAUDRATE = "baudrate"

DEFAULT_NAME = "Innentemperatur (Abluft)"
DEFAULT_BAUDRATE = 9600

MIN_TIME_BETWEEN_UPDATES = timedelta(seconds=60)

SENSOR_HEAT_RECOVERY = 'heat_recovery'
SENSOR_DEFROSTER = 'defroster'
SENSOR_INDOOR = 'indoor'
SENSOR_INDOOR_IN = 'indoor_in'
SENSOR_OUTDOOR = 'outdoor'
SENSOR_HOUSE_AIR_OUT = 'house_air_out'

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_SERIAL_PORT): cv.string,
        vol.Optional(CONF_BAUDRATE, default=DEFAULT_BAUDRATE): cv.positive_int,
        vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
    }
)
# endregion Constants


class Command(Enum):
    # Date and time
    STATUS = 0x0
    BROADCAST_REQUEST = 0x80
    BROADCAST_ANSWER = 0x81
    # = 0x82
    # = 0x83
    ALIVE = 0x84
    GET_SET = 0x85
    ASK = 0x86
    OTHER = 0x87


class SubCommand(Enum):
    SET_LANGUAGE = 0x06
    SET_FAN_SPEED = 0x08
    TIME_LEFT_TO_FILTER_REPLACEMENT = 0x09
    # 26 9 - 1
    BYPASS = 0x1A
    OPERATING_HOURS = 0x26
    TEMPERATURES = 0x44
    # 0x90 144 9 - 1
    # 0x1D 29  9 - 1
    # 0x55 85 10 - 2


async def async_setup_platform(hass: HomeAssistant, config: ConfigType, async_add_entities: AddEntitiesCallback, discovery_info: DiscoveryInfoType = None):  # | None
    """Set up the Serial sensor platform."""
    name = config.get(CONF_NAME) or DEFAULT_NAME
    port = config.get(CONF_SERIAL_PORT)
    baudrate = config.get(CONF_BAUDRATE) or DEFAULT_BAUDRATE

    sensors: dict[str, NovusSensorInterface] = {
        SENSOR_HEAT_RECOVERY: NovusBinarySensor(hass, SENSOR_HEAT_RECOVERY, "Wärme Rück Gewinnung"),
        SENSOR_DEFROSTER: NovusSensor(hass, SENSOR_DEFROSTER, "Defroster"),
        SENSOR_INDOOR: NovusTempSensor(hass, SENSOR_INDOOR, "Innentemperatur (Abluft)", "mdi:home-thermometer"),
        SENSOR_INDOOR_IN: NovusTempSensor(hass, SENSOR_INDOOR_IN, "Zuluft Temperatur Räume", "mdi:air-purifier"),
        SENSOR_OUTDOOR: NovusTempSensor(hass, SENSOR_OUTDOOR, "Außentemperatur Lüftung", "mdi:home-import-outline"),
        SENSOR_HOUSE_AIR_OUT: NovusTempSensor(
            hass, SENSOR_HOUSE_AIR_OUT, "Abluft Temperatur Haus")
    }

    async def serial_read(device, rate, **kwargs):
        """Read the data from the port."""
        reader = Serial(device, baudrate=rate, **kwargs)
        count = 0
        lastdata = None
        result = None
        while result != True:
            line = ''
            try:
                line = reader.readline()
                count += 1
                if not line or len(line) <= 0:
                    continue
                if lastdata:
                    line = lastdata + line
                    lastdata = None
                if len(line) < 6:
                    lastdata = line
                    continue
                elif line and getDataLength(line) > len(line)-6 and (getCommandId(line) != 87 or len(line) == 32):
                    lastdata = line
                    continue
                data = []
                if line and len(line) > 0:
                    for x in line:
                        data.append(x)
                    result = consumePackage(data)
                    if result == False:
                        lastdata = line
            except ValueError:
                _LOGGER.error("ValueError: %s", line)
                pass
        reader.close()

    def consumePackage(data, recursion=0):
        if recursion > 10:
            return None
        if expectedDataLength(data) + 6 > len(data):
            return False
        valid = False
        lastdata = []
        while not valid and len(data) >= 6 and lastdata != data:
            lastdata = data
            valid = validate(data)
            if not valid and len(data) >= 6:
                if len(data) >= 20 and data[0] == 0x00 and data[1] == 0x00 and data[2] == 0x00 and data[3] == 0x03:
                    consumePackage(data[0:6+14], recursion=recursion+1)
                    data = data[6+14:]
                elif data[2] in [item.value for item in Command] and data[2] != Command.STATUS.value:
                    consumePackage(
                        data[0:6+expectedDataLength(data)], recursion=recursion+1)
                    data = data[6+expectedDataLength(data):]
                else:
                    # try:
                    while not isCommand(data[2]):
                        data = data[1:]
                        if len(data) < 2:
                            break
                    if data[2] != Command.OTHER.value:
                        if isCommand(data[2]):
                            consumePackage(
                                data[0:6+expectedDataLength(data)], recursion=recursion+1)
                        data = data[6+expectedDataLength(data):]
                    # except:
                    #    break
                    #    pass

        return process_command(data)

    def process_command(raw_data):
        if len(raw_data) < 9:
            return None
        cmd = raw_data[2]
        sub_cmd = raw_data[6]
        length = raw_data[3]
        data = raw_data[6:]

        if cmd == Command.GET_SET.value and sub_cmd == SubCommand.TEMPERATURES.value and len(raw_data) == 25:
            set_temp_value(SENSOR_INDOOR_IN, extractTemp(raw_data[9:13]))
            set_temp_value(SENSOR_OUTDOOR, extractTemp(raw_data[13:17]), False)
            set_temp_value(SENSOR_INDOOR, extractTemp(raw_data[17:21]))
            set_temp_value(SENSOR_HOUSE_AIR_OUT, extractTemp(raw_data[21:25]))
            return True

        if length == 32 or len(data):
            _LOGGER.warning("Time left to filter replacement? %s - %s - %s",
                            sub_cmd, asHex(raw_data), raw_data)

            # and len(raw_data) > 11:
        if cmd == Command.GET_SET.value and sub_cmd == SubCommand.BYPASS.value:
            try:
                heat_recovery = not extractBypass(data)
                if heat_recovery != get_sensor_value(SENSOR_HEAT_RECOVERY):
                    set_sensor_value(SENSOR_HEAT_RECOVERY, heat_recovery)
                    _LOGGER.warning("bypass state change: open? %s - %s - %s",
                                    not heat_recovery, asHex(raw_data), raw_data)
                defroster = extractDefroster(data)
                if defroster != get_sensor_value(SENSOR_DEFROSTER):
                    set_sensor_value(SENSOR_DEFROSTER, defroster)
            except:
                pass
        elif cmd == Command.GET_SET.value and sub_cmd == SubCommand.TIME_LEFT_TO_FILTER_REPLACEMENT.value:
            if len(data) > 25:
                _LOGGER.warning(
                    "Time left to filter replacement: %s - %s", asHex(data[23:27]), data[23:27])
        elif cmd == Command.GET_SET.value:
            _LOGGER.warning(
                "sub_cmd: %s %s - len(raw_data): %s, len(data): %s - data: %s", asHex(sub_cmd), sub_cmd, len(raw_data), len(data), asHex(raw_data))

        # elif len(data) == 12 and (' '.join('{:02x}'.format(x) for x in data)).startswith('01 00 85 06'):
        #     value = str(data[-1])
        #     print(value)
        #     setAirLevel(value)
        return None

    def get_sensor_value(name):
        if not name in sensors:
            return None
        return sensors[name].state

    def set_sensor_value(name, value):
        if not name in sensors:
            return
        sensors[name].setState(value)

    def set_temp_value(name, temp, tempOverNull=True):
        _LOGGER.warning('set_temp_value name: %s - temp: %s', name, temp)
        if not tempOverNull and temp <= 0:
            return
        elif tempOverNull and temp >= 100:
            return
        elif not name in sensors:
            return
        elif temp == get_sensor_value(name):
            return
        _LOGGER.warning('set_sensor_value name: %s - temp: %s',
                        name, round(temp, 1))
        set_sensor_value(name, round(temp, 1))

    async_add_entities(sensors.values(), True)

    if port is None:
        return
    await serial_read(port, baudrate, timeout=0, stopbits=STOPBITS_ONE, parity=PARITY_MARK, bytesize=EIGHTBITS, rtscts=False, dsrdtr=False)


# region Helper Functions


def getDataLength(reading):
    try:
        return ord(reading[3])
    except:
        pass
    return 0


def validate(data):
    return validateCrc(data) and expectedDataLength(data) == len(data[6:])


def expectedDataLength(data):
    if data[3] >= 0x80:
        return int(hex(data[3] - 0x80), 16)
    return int(hex(data[3]), 16)


def validateCrc(data):
    refCrc = data[4:6]
    crc = novus_crc(data[0:4] + data[6:])
    return refCrc == crc


def novus_crc(data):
    crc = crc16_ccitt(0, data)
    try:
        return [int(formatLeadingZero(hex(crc)[-2:]), 16), int(formatLeadingZero(hex(crc)[2:][:-2]), 16)]
    except:
        pass
    return []


def formatLeadingZero(str):
    return '0' + str if len(str) < 2 else str


def crc16_ccitt(crc, data):
    msb = crc >> 8
    lsb = crc & 255
    for c in data:
        x = c ^ msb
        x ^= (x >> 4)
        msb = (lsb ^ (x >> 3) ^ (x << 4)) & 255
        lsb = (x ^ (x << 5)) & 255
    return (msb << 8) + lsb


def isCommand(cmd):
    return cmd == Command.STATUS.value or (cmd >= Command.BROADCAST_REQUEST.value and cmd <= Command.OTHER.value)


def extractTemp(b):
    # Exmaple Data: [130, 0, 246, 0] --> 24.6 °C
    temp = b[2] / 10.0
    # TODO: b[3] == 255 < 0.0 or > 25.6!
    if b[3] > 128:  # Temp Values < 0.0 °C
        #     # 256 --> -25.6 - Exmaple Data: [130, 0, 246, 255] --> -25,6+24,6= -1.0 °C
        temp -= (256 - b[3]) * 25.6
    else:
        temp += b[3] * 25.6
    # Org:    temp = (b[3] << 8 | b[2]) / 10.0
    _LOGGER.debug(
        "Valid temp %s - raw data: '%s'",
        temp,
        b,
    )
    return temp


#  01 00  85  03 04   65  1a 00  1d
#  [1, 0, 133, 3, 4, 101, 26, 0, 29]
# Extract Bypass state           ^
# e.g. 29 / 1d --> 1d = 1 = True
# e.g. 13 / 0d --> 0d = 0 = False
def extractBypass(data):
    try:
        return int(format(data[2], '02x')[0]) == 1
    except:
        pass
    return False


def extractDefroster(data):
    try:
        return format(data[2], '02x')[1]
    except:
        pass
    return 'unknown'


def getCommandId(reading):
    try:
        return int(codecs.encode(reading[2], 'hex'))
    except:
        pass
    return 0


def asHex(data):
    try:
        return ''.join('{:02x}'.format(x) for x in data)
    except:
        pass
    return ''
# endregion Helper Functions


class NovusSensorInterface:
    def setState(self, newState):
        pass

    def state(self):
        pass


class NovusBinarySensor(BinarySensorEntity, NovusSensorInterface):
    """Representation of a Binary sensor."""

    def __init__(self, hass, id, friendly_name):
        """Initialize the Serial sensor."""
        self._hass = hass
        self._attr_unique_id = self._attr_name = "novus300_" + id
        self._name = friendly_name
        self._attr_icon = 'mdi:compare-horizontal'
        self._is_on = None
        self._attr_device_class = DEVICE_CLASS_PLUG

    @property
    def name(self):
        """Return the name of the sensor."""
        return self._name

    @property
    def is_on(self):
        """Return the state of the sensor."""
        return self._is_on

    def setState(self, newState):
        self._is_on = newState


class NovusSensor(SensorEntity, NovusSensorInterface):
    def __init__(self, hass, id, friendly_name):
        self._hass = hass
        self._attr_unique_id = self._attr_name = "novus300_" + id
        self._name = friendly_name
        self._state = None
        # self._attr_icon = icon
        # self._attr_device_class = DEVICE_CLASS_TEMPERATURE
        # self._attr_unit_of_measurement = TEMP_CELSIUS

    @property
    def name(self):
        """Return the name of the sensor."""
        return self._name

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._state

    def setState(self, newState):
        self._state = newState


class NovusTempSensor(NovusSensor):
    """Representation of a Serial sensor."""

    def __init__(self, hass, id, friendly_name, icon='hass:thermometer'):
        """Initialize the Serial sensor."""
        self._hass = hass
        self._attr_unique_id = self._attr_name = "novus300_temp_" + id
        self._name = friendly_name
        self._attr_icon = icon
        self._state = None
        # self._attr_should_poll = True  # self._port is not None
        self._attr_device_class = DEVICE_CLASS_TEMPERATURE
        self._attr_unit_of_measurement = TEMP_CELSIUS
