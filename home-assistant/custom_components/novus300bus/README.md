This is a custom component for home assistant.
It allows read the temperatures from the Paul Novus 300 air ventilation.
To connect the air ventilation it uses a serial RS-485 USB Adapter.

* To use it copy the folder novus300 and all sub folders and files into your home assistant config sub folder "custom_components".
* Extend your home assistant seonsors.yaml with:

```
- platform: novus300
  serial_port: /dev/ttyUSB0
  # optional:
  # baudrate: 9600
  # name: ...
```

Todo:

* Cleanup code - move read function into global part
* Remove hardcoded sensors and read them as config
* Add bypass state as sensor
* Add filter time as sensor
