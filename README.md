# jamble
Command line tool for interacting with the Lohmega BlueBerry logger over Bluetooth LE 

Should work on Linux, MacOS and Windows but not tested Windows.

install
-------
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


CLI tool Usage example
----------------------

```
# scan and list BlueBerry devices
bblog scan

# enable logging
bblog config-write --logging=on --address=<address_or_MacOSid>

# fetch 3 seconds of real time sensor data
bblog fetch --rtd -n3 --address=<address_or_MacOSid>
```

debug
-----

Try pass the verbose level 4 argument `-vvvv` to enable lots of debug info

### GNU/Linux:


btmon - bluetooth monitor (replaces hcidump that is no longer maintained)
will show more details on error than Bluez DBUS API.

`journalctl | grep bluetooth`

Experimental settings in
`/sys/kernel/debug/bluetooth/hci*/`

`hciconfig -a` - show configurations and interface info

### MacOS

Bluetooth monitor on MacOS "PacketLogger.app":
- Create Apple developer account.
- Download xcode (mabye not required)
- Download "Additional Tools" (contains PacketLogger) from
 https://developer.apple.com/download/more/?=for%20Xcode

Also see:
https://stackoverflow.com/questions/5863088/bluetooth-sniffer-preferably-mac-osx
