#!/usr/bin/env python3
# -*- coding: utf-8 -*-

HOST = "localhost" # <-- Set your Tinkerforge (Brick Daemon) Host Name or IP
PORT = 4223
UID = "Jyq" # Change XYZ to the UID of your Air Quality Bricklet
UID_ANALOG_OUT = 'Hob' # Change XYZ to the UID of your Analog Out Bricklet
READ_INTERVAL_MS = 10
WRITE_INTERVAL_SEC = 60
OH_HOST = 'localhost' # <-- Set your OH Host Name or IP
BASE_URL = 'http://{oh_host}:8080/rest'.format(oh_host=OH_HOST)
AIR_PRESSURE_BASE = 1013.25

from tinkerforge.ip_connection import IPConnection
from tinkerforge.bricklet_air_quality import BrickletAirQuality
from tinkerforge.bricklet_industrial_analog_out_v2 import BrickletIndustrialAnalogOutV2
from openhab import openHAB
import asyncio
import requests
import time

ipcon = IPConnection() # Create IP connection
iao = BrickletIndustrialAnalogOutV2(UID_ANALOG_OUT, ipcon) # Create device object

# Air Level Write Values
# last_volt_set = -1

# Air Read Values
last_write = 0
count_read = avg_iaq_index = 0
avg_temperature = avg_humidity = avg_air_pressure = last_avg_air_pressure = 0.0

# Callback function for all values callback
def cb_all_values(iaq_index, iaq_index_accuracy, temperature, humidity, air_pressure):
    global last_write, count_read, avg_iaq_index, avg_temperature, avg_humidity, avg_air_pressure, last_avg_air_pressure #, last_volt_set
    avg_iaq_index = ((count_read * avg_iaq_index) + iaq_index) / (count_read + 1)
    avg_temperature = ((count_read * avg_temperature) + (temperature/100.0)) / (count_read + 1)
    avg_humidity = ((count_read * avg_humidity) + (humidity/100.0)) / (count_read + 1)
    avg_air_pressure = ((count_read * avg_air_pressure) + (air_pressure/100.0) - AIR_PRESSURE_BASE) / (count_read + 1)
    count_read += 1

    if last_write + WRITE_INTERVAL_SEC < time.time():
        last_write = time.time()
        # 3.7. asyncio.run
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(writeOpenHab('outgoingAirTemperature', round(avg_temperature, 2)))
        loop.run_until_complete(writeOpenHab('outgoingAirHumidity', round(avg_humidity, 2)))
        if last_avg_air_pressure == 0.0 or abs(last_avg_air_pressure-avg_air_pressure) < 10.0:
            last_avg_air_pressure = avg_air_pressure
            loop.run_until_complete(writeOpenHab('outgoingAirPressure', round(avg_air_pressure, 3)))
        loop.run_until_complete(writeOpenHab('outgoingAirIndex', avg_iaq_index))
        avg_temperature = avg_humidity = avg_air_pressure = 0.0
        count_read = avg_iaq_index = 0

        loop.run_until_complete(writeOpenHab('airLevelPercent', round(iao.get_voltage() / 100, 2)))

    if round(time.time(), 0) % 10:
        setVolt = int(float(requests.get('{base_url}/items/{item}/state'.format(base_url=BASE_URL, item='airLevelPercent')).text))
        # if last_volt_set != setVolt:
        if iao.get_voltage() != setVolt * 100:
            # Set output voltage to nn V
            iao.set_voltage(setVolt * 100)
            iao.set_enabled(True)
            # last_volt_set = setVolt

async def writeOpenHab(item, data):
    requests.put('{base_url}/items/{item}/state'.format(base_url=BASE_URL, item=item), data=str(data))


if __name__ == "__main__":
    aq = BrickletAirQuality(UID, ipcon) # Create device object

    ipcon.connect(HOST, PORT) # Connect to brickd
    # Don't use device before ipcon is connected

    # Register all values callback to function cb_all_values
    aq.register_callback(aq.CALLBACK_ALL_VALUES, cb_all_values)

    # Set period for all values callback to 1s (1000ms)
    aq.set_all_values_callback_configuration(READ_INTERVAL_MS, False)

    input("Press key to exit\n") # Use input() in Python 3
    ipcon.disconnect()
