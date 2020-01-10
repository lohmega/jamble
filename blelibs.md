




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

