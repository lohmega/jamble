# jamble
command line tool for interacting with Lohmea BlueBerry logger over Bluetooth LE 

Should work on Linux, MacOS and windows but Windows untested and there is a bug
in bleak ver <= 0.5.1 for MacOS. Fixes is in the develop branch and hopefull
included in next release.

install
-------
not yet any installer try the follwing 
```
python3 -m pip install bleak protobuf
# git and clone this repo
git clone https://github.com/lohmega/jamble.git
cd jamble/bblogger
python3 main.py scan

```


Usage example

```
# scan and list BlueBerry devices
python3 main.py scan

# enable logging
python3 main.py config-write --logging=on --address=<address_or_MacOSid>

# fetch 3 seconds of real time sensor data
python3 main.py fetch --rtd -n3 --address=<address_or_MacOSid>
```

debug
-----

Try pass the verbose level 4 argument `-vvvv` to enable lots of debug info
