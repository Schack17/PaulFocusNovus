"""Support for reading data from a serial port."""
import codecs
# import json
import logging
from datetime import timedelta
from enum import Enum

import homeassistant.helpers.config_validation as cv
import serial
import voluptuous as vol
from homeassistant.components.sensor import PLATFORM_SCHEMA
from homeassistant.const import CONF_NAME, EVENT_HOMEASSISTANT_STOP
from homeassistant.helpers.entity import Entity
from homeassistant.util import Throttle

_LOGGER = logging.getLogger(__name__)

CONF_SERIAL_PORT = "serial_port"
CONF_BAUDRATE = "baudrate"

DEFAULT_NAME = "Innentemperatur (Abluft)"
DEFAULT_BAUDRATE = 9600

MIN_TIME_BETWEEN_UPDATES = timedelta(seconds=60)

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_SERIAL_PORT): cv.string,
        vol.Optional(CONF_BAUDRATE, default=DEFAULT_BAUDRATE): cv.positive_int,
        vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
    }
)


class Command(Enum):
    STATUS = 0x0
    BROADCAST_REQUEST = 0x80
    BROADCAST_ANSWER = 0x81
    # = 0x82
    # = 0x83
    ALIVE = 0x84
    GET_SET = 0x85
    ASK = 0x86
    OTHER = 0x87


def async_setup_platform(hass, config, async_add_entities, discovery_info=None, entities=None):
    """Set up the Serial sensor platform."""
    name = config.get(CONF_NAME) or DEFAULT_NAME
    port = config.get(CONF_SERIAL_PORT)
    baudrate = config.get(CONF_BAUDRATE) or DEFAULT_BAUDRATE

    indoor_in = NovusTempSensor(hass, "indoor_in", "Zuluft Temperatur Räume")
    outdoor = NovusTempSensor(hass, "outdoor", "Außentemperatur Lüftung")
    house_air_out = NovusTempSensor(
        hass, "house_air_out", "Abluft Temperatur Haus")
    entities += [NovusTempSensor(hass, "indoor", name, port, baudrate,
                                 indoor_in, outdoor, house_air_out), indoor_in, outdoor, house_air_out]
    async_add_entities(entities, True)


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
    # # Org:    temp = (b[3] << 8 | b[2]) / 10.0
    _LOGGER.debug(
        "Valid temp %s - raw data: '%s'",
        temp,
        b,
    )
    return temp


def getCommandId(reading):
    try:
        return int(codecs.encode(reading[2], 'hex'))
    except:
        pass
    return 0


class NovusTempSensor(Entity):
    """Representation of a Serial sensor."""

    def __init__(self, hass, id, name, port=None, baudrate=None, indoor_in=None, outdoor=None, house_air_out=None):
        """Initialize the Serial sensor."""
        self._indoor_in = indoor_in
        self._outdoor = outdoor
        self._house_air_out = house_air_out
        self.entity_id = "sensor.novus300_temp_" + id
        self._hass = hass
        self._name = name
        self._port = port
        self._baudrate = baudrate
        self._serial_loop_task = None
        self._attributes = []
        self._state = self._tempIndoor = None

    async def serial_read(self, device, rate, **kwargs):
        """Read the data from the port."""
        _LOGGER.debug("serial_read start: %s", self.entity_id)
        reader = serial.Serial(device, baudrate=rate, **kwargs)
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
                    result = self.consumePackage(data)
                    if result == False:
                        lastdata = line
            except ValueError:
                _LOGGER.error("ValueError: %s", line)
                pass
        reader.close()
        _LOGGER.debug("serial_read end: %s", self.entity_id)

    def consumePackage(self, data, recursion=0):
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
                    self.consumePackage(data[0:6+14], recursion=recursion+1)
                    data = data[6+14:]
                elif data[2] in [item.value for item in Command] and data[2] != Command.STATUS.value:
                    self.consumePackage(
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
                            self.consumePackage(
                                data[0:6+expectedDataLength(data)], recursion=recursion+1)
                        data = data[6+expectedDataLength(data):]
                    # except:
                    #    break
                    #    pass

        if len(data) == 25 and data[2] == Command.GET_SET.value:
            temp = extractTemp(data[9:13])
            if temp > 0 and temp != self._indoor_in.state:
                self._indoor_in.setState(round(temp, 1))
            temp = extractTemp(data[13:17])
            if temp < 100 and temp != self._outdoor.state:
                self._outdoor.setState(round(temp, 1))
            temp = extractTemp(data[17:21])
            if temp > 0 and temp != self._tempIndoor:
                self._state = self._tempIndoor = round(temp, 1)
            temp = extractTemp(data[21:25])
            if temp > 0 and temp != self._house_air_out.state:
                self._house_air_out.setState(round(temp, 1))
            return True
        # elif len(data) == 12 and (' '.join('{:02x}'.format(x) for x in data)).startswith('01 00 85 06'):
        #     value = str(data[-1])
        #     print(value)
        #     setAirLevel(value)
        return None

    @property
    def unit_of_measurement(self):
        return "°C"

    @property
    def device_class(self):
        return "temperature"

    @property
    def name(self):
        """Return the name of the sensor."""
        return self._name

    @property
    def should_poll(self):
        """No polling needed."""
        return True  # self._port is not None

    @property
    def device_state_attributes(self):
        return self._attributes

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._state

    def setState(self, newState):
        self._state = newState

    @Throttle(MIN_TIME_BETWEEN_UPDATES)
    async def async_update(self):
        _LOGGER.debug("async_update req: %s", self.entity_id)
        if self._port is None:
            return
        _LOGGER.debug("async_update start: %s", self.entity_id)
        await self.serial_read(self._port, self._baudrate, timeout=0, stopbits=1  # serial.STOPBITS_ONE
                               , parity="M"  # serial.PARITY_MARK
                               , bytesize=8,  # serial.EIGHTBITS
                               rtscts=False,
                               dsrdtr=False)
        _LOGGER.debug("async_update end: %s", self.entity_id)