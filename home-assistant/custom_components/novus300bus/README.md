This is a custom component for home assistant.
It allows read the temperatures from the Paul Novus 300 air ventilation.
To connect the air ventilation it uses a serial RS-485 USB Adapter.

* To use it copy the folder novus300bus and all sub folders and files into your home assistant config sub folder "custom_components".
* Extend your home assistant sensors.yaml with:

```
- platform: novus300bus
  serial_port: /dev/ttyUSB0
  # optional:
  # baudrate: 9600
  # name: ...
```

Todo:

* Remove hardcoded sensors and read them as config
* Add filter time as sensor
* Add project to hacs
* Add dokumentation how to connect USB RS-485
