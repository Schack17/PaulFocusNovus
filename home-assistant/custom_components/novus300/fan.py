"""Support for Novus300 fan."""
from homeassistant.components.fan import (
    ENTITY_ID_FORMAT,
    SUPPORT_OSCILLATE,
    SUPPORT_SET_SPEED,
    FanEntity,
)
from homeassistant.const import STATE_OFF, UNIT_PERCENTAGE, TEMP_CELSIUS

from tinkerforge.ip_connection import IPConnection as ipc
from tinkerforge.bricklet_industrial_analog_out_v2 import BrickletIndustrialAnalogOutV2

import re

host = '%tinkerforge-hat-ip%'
port = 4223
uid_analog_out = '%tinkerforge-id%'
default_speed = '60.0'
speed_list = [STATE_OFF, '10', '20', '30', '40', '50', '60', '70', '80', '90', '100']

def setup_platform(hass, config, add_entities, discovery_info=None):
    """Set up Novus 300 fan platform."""
    _ipcon = ipc() # IPConnection() Create IP connection
    device = BrickletIndustrialAnalogOutV2(uid_analog_out, _ipcon) # Create device object
    _ipcon.connect(host, port) # Connect to brickd
    add_entities([Novus300FanDevice(device)])

class Novus300FanDevice(FanEntity):
    """Novus300 fan devices."""

    def __init__(self, iao):
        """Init Novus300 fan device."""
        self._iao = iao
        self.entity_id = "fan.novus300"
        self.friendly_name = "Lüftung"

    @property
    def state(self):
        speed = float(self.speed)
        return speed if speed > 0 else STATE_OFF

    def set_speed(self, speed: str) -> None:
        """Set the speed of the fan."""
        speed = 0.0 if speed is None or speed == STATE_OFF else float(speed)
        if(speed < 0):
            speed = 0
        if(speed > 100):
            speed = 100
        self._iao.set_voltage(speed * 100)
        self._iao.set_enabled(True)

    def turn_on(self, speed: str = default_speed, **kwargs) -> None:
        """Turn on the fan."""
        if speed is None or speed == STATE_OFF:
            speed = default_speed
        self.set_speed(speed)

    def turn_off(self, **kwargs) -> None:
        """Turn the entity off."""
        self.set_speed(STATE_OFF)

    @property
    def is_on(self) -> bool:
        """Return true if the entity is on."""
        return self.state is not None or self.state != STATE_OFF # round(self._iao.get_voltage() / 100.0, 1) > 0.5

    @property
    def speed(self) -> str:
        """Return the current speed."""
        return str(round(self._iao.get_voltage() / 100.0, 1))

    @property
    def speed_list(self) -> list:
        """Get the list of available speeds."""
        return speed_list

    @property
    def supported_features(self) -> int:
        """Flag supported features."""
        return SUPPORT_SET_SPEED

    def oscillate(self, oscillating) -> None:
        """Oscillate the fan."""
        pass

    @property
    def oscillating(self):
        """Return current oscillating status."""
        return None
