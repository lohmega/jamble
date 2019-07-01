
from platform import system as _platform_system

if _platform_system() == 'Linux':
    from bluetoothle.ble_linux import *
elif _platform_system() == 'Darwin':
    pass
elif _platform_system() == 'Windows':
    pass
