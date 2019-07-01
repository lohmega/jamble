Bluetoot LE client
==================


State of Bluetooth LE libs 2019 Q2
----------------------------------

- (python/C++) https://bitbucket.org/OscarAcena/pygattlib
  no commits since 2016.
  
  There is a fork with "some fixes" under pybluez project:
  https://github.com/pybluez/pygattlib.
  maintained?  broken installer for python3.
  as dbus interface in python seems like risky
  buiseness (can be buggy, according to official docs) this lib might be the
  winner in "best design choises" - future will tell.

- (python) https://github.com/adafruit/Adafruit_Python_BluefruitLE/
  support Linux/bluez and MacOS/CoreBluetooth.
  broken for Linux as dbus API changed. no longer maintained.
  
- (Go) https://github.com/go-ble/ble 
  used by apache mynewt-newtmgr but no longer maintained.
  maintained fork exists here https://github.com/go-ble/ble however, not (yet)
  stable according to README, perahps due to experimental changes

- (javascript/nodejs) https://github.com/noble/noble
  maintainer(s) died 2018? lots of pending pullrequests with critiqal fixes. 
  might work with nodejs ver 8, broken installer for ver 10)

- (C) bluez - standard stack on linux put ported to osx, ios etc. unclear if ports
  are stable. older version of Bluez (hcitool & gatttool) < 5.17 !? do not
  support write to attibutes.

- (C) https://github.com/armansito/bluez-gatt-dbus-client
  fork of bluez repo with misleading name. no longer maintained

- (C) https://github.com/labapart/gattlib

- (pyhon) https://github.com/getsenic/gatt-python
  linux only
  requires BlueZ >= 5.38

- (python) https://github.com/ukBaz/python-bluezero
  untested

- (python) https://github.com/hbldh/bleak 
  windows and linux, but do not work with python dpkg packages available in
  Debian stretch.  uses twisted dbus module for linux (not dbus module in
  standard lib). not sure if this is good or bad.  "Be warned: Bleak is
  still in an early state of implementation." according tor readme.

- (python) https://github.com/IanHarvey/bluepy/
  nice API IMO. linux only should be easily portable according to author.
  do not seem to support notifications as of 2019-05-16 !?
  https://github.com/rlangoy/bluepy_examples_nRF51822_mbed/

- (python) https://github.com/pybluez/pybluez
  crossplattform and mature but "project is not under active development"
  the BLE/GATT interface used is a fork of
  https://bitbucket.org/OscarAcena/pygattlib see above



Linux tools examples
====================

Useful debug tools (Linux)
--------------------------
- hcitool and gatttool
- btmon - bluetooth monitor (replaces hcidump that is no longer maintained!?)

useful commands
```
hciconfig hci0 up|down
btmgmt le on
```

hcitool and gatttool
--------------------

```
sudo hcitool lescan
sudo gatttool -b EC:26:CD:58:DC:B0 -t random -I
[EC:26:CD:58:DC:B0][LE]> connect

# get handles from characteristics (use the larger handle value)
[EC:26:CD:58:DC:B0][LE]> characteristics 
handle: 0x0002, char properties: 0x0a, char value handle: 0x0003, uuid: 00002a00-0000-1000-8000-00805f9b34fb
handle: 0x0004, char properties: 0x02, char value handle: 0x0005, uuid: 00002a01-0000-1000-8000-00805f9b34fb
handle: 0x0006, char properties: 0x02, char value handle: 0x0007, uuid: 00002a04-0000-1000-8000-00805f9b34fb
handle: 0x0008, char properties: 0x02, char value handle: 0x0009, uuid: 00002aa6-0000-1000-8000-00805f9b34fb
handle: 0x000b, char properties: 0x20, char value handle: 0x000c, uuid: 00002a05-0000-1000-8000-00805f9b34fb
handle: 0x000f, char properties: 0x0e, char value handle: 0x0010, uuid: c9f60000-9f9b-fba4-5847-7fd701bf59f2
handle: 0x0011, char properties: 0x0e, char value handle: 0x0012, uuid: c9f60001-9f9b-fba4-5847-7fd701bf59f2
handle: 0x0013, char properties: 0x0e, char value handle: 0x0014, uuid: c9f60002-9f9b-fba4-5847-7fd701bf59f2
handle: 0x0015, char properties: 0x0c, char value handle: 0x0016, uuid: c9f6001a-9f9b-fba4-5847-7fd701bf59f2

[EC:26:CD:58:DC:B0][LE]> char-write-cmd 0x0023 010

[EC:26:CD:58:DC:B0][LE]> char-write-cmd 0x001a 01

```
