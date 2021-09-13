This is a custom component for home assistant.
It allows to control the fan speed of a Paul Novus 300 air ventilation.
To connect the air ventilation it uses a Tinkerforge 0-10 V output modul.

* To use it copy the folder novus300 and all sub folders and files into your home assistant config sub folder "custom_components".
* Edit the fan.py and add your tinkerforge brickd ip address in "host" and the 0-10V-Modul id in "uid_analog_out".
* Extend your home assistant configuration.yaml with:
```
fan:
  - platform: novus300
```
* Optional: Extend your customize.yaml with:
```
fan.novus300:
  unit_of_measurement: "%"
  friendly_name: Lüftung
```
