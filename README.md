# jamble
command line tool for interacting with Lohmea BlueBerry logger over Bluetooth LE 

install
-------
not yet any installer. On Linux and MacOS something like the following should work 
```
python3 -m pip install bleak protobuf
# assuming `~/bin` is on PATH
cd ~/bin
git clone https://github.com/lohmega/jamble.git
chmod +x jamble/bblogger/main.py
ln -s bblogger jamble/bblogger/main.py

```
or just run `python3 main.py` to try it out.


Usage example

```
# scan an list BlueBerry devices
python3 main.py scan

# enable logging
python3 main.py config-write --logging=on --address=<address_or_MacOSid>

# fetch 3 seconds of real time sensor data
python3 main.py fetch --rtd -n3 --address=<address_or_MacOSid>
```
