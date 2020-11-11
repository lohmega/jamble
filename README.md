jamble
======
Command line tool for interacting with the Lohmega BlueBerry logger over Bluetooth LE 

Tested on GNU/Linux, MacOS and Windows.

Install
=======
```
python3 -m pip install git+https://git@github.com/lohmega/jamble.git
```
or 
```
# clone this repo
git clone https://github.com/lohmega/jamble.git
cd jamble
make install
```


Usage examples
==============

```
# scan and list BlueBerry devices
bblog scan

# enable logging
bblog config-write --logging=on --address <address_or_MacOSid>

# fetch 3 seconds of real time sensor data
bblog fetch --rtd -n3 --address <address_or_MacOSid>
```

Firmware update
===============

Find latest firmware versions at http://fw.lohmega.com/.
Flash/install firmware zip with command `bblog dfu -address F2:1F:2B:52:48:9E --package bb_v10_logger_dfu_x_x_x.zip`
To see installed firmware, run `bblog device-info --address <address_or_MacOSid>`.


Debug
=====

Try pass the verbose level 4 argument `-vvvv` to enable lots of debug info

GNU/Linux:

`btmon` - bluetooth monitor (replaces hcidump that is no longer maintained)
will show more details on error than Bluez DBUS API.

`journalctl | grep bluetooth`

Experimental settings in
`/sys/kernel/debug/bluetooth/hci*/`

`hciconfig -a` - show configurations and interface info

`sudo hcitool -i hci0 lescan` - scan BLE devices


MacOS:

Bluetooth monitor on MacOS "PacketLogger.app":
- Create Apple developer account.
- Download xcode (mabye not required)
- Download "Additional Tools" (contains PacketLogger) from
 https://developer.apple.com/download/more/?=for%20Xcode

