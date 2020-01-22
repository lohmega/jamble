#!/usr/bin/env python3
#
# Set default conn_interval.
# TODO assumes hci0 used (single bluetooth interface)
#
# Background
# ==========
#
# BlueBerry will Make a "Connection Parameter Update Request" with the following
# values:
#    conn_min_interval = 80 (100 ms)
#    conn_max_interval = 160 (200 ms)
# If these values are not accepted (i.e. out of range) the device will
# eventually be disconnected.  However, on Debian stretch, buster and bluz <=
# 5.50 (presumably also on Ubuntu) default values are:
#    conn_min_interval = 24 (30 ms)
#    conn_max_interval = 40 (50 ms)
# 
# Note: Raw values are converted to milliseconds by multipy with 1.25, this is 
# part of the Bluetooth specifigation.
# 
# Setting default conn_max_interval 
# =================================
#
# A possible alternative, but untested, method is the 
# bluetooth management socket API described here:
# https://git.kernel.org/pub/scm/bluetooth/bluez.git/tree/doc/mgmt-api.txt
#
# It might also be possible that this is a undocumneted setting in 
# /etc/bluetooth/main.conf
# 
# Paramters accessible in debugfs as root. Example
#     echo 80 | sudo dd of=/sys/kernel/debug/bluetooth/hci0/conn_max_interval
# but these changes are reverted after reboot. 
# Could have a launch script but as most kernels do not allow scripts
# to be "owened by root" (i.e. started by user without sudo but with root access)
# so this will not work.
#
# Easiest to tell systemd to do this at startup.

from os import path, mkdir, geteuid
from platform import system
import logging

logger = logging.getLogger(__name__)

_BT_SERVICE_DIR='/etc/systemd/system/bluetooth.service.d' 
_BT_SERVICE_FILE='/etc/systemd/system/bluetooth.service.d/10-set-conn_interval.conf'

def _raw2ms(x):
    ''' convert raw values of min/max conn interval to milliseconds '''
    return x * 1.25

def __bt_debugfs_path(hci, prop):
    btd = '/sys/kernel/debug/bluetooth/'
    path_ = path.join(btd, hci, prop)
    # check exists always in case of write
    if not path.exists(path_):
        raise RuntimeError('No such path %s' % path_)
    return path_

def __bt_debugfs_set(hci, prop, val):
    path_ = __bt_debugfs_path(hci, prop)
    with open(path_, 'w') as f:
        f.write(str(int(val)))

def __bt_debugfs_get(hci, prop):
    path_ = __bt_debugfs_path(hci, prop)
    with open(path_) as f:
        val = f.readline()
    return int(val.strip())

def is_configured():
    # need sudo to reead debugfs but. this seems like a better method
    return path.exists(_BT_SERVICE_FILE)

def verify_configured():
    if is_configured():
        return

    logger.warning(('System not configured! '
        '(Bluetooth conn_max_interval to low) '
        'Please run the follwing command as root to remove this warning: '
        '\'python3 {} --create-service'.format(path.realpath(__file__))))

def _create_service(hci='hci0', vmax=160):

    assert (geteuid() == 0)
    assert path.exists('/etc/systemd/system')
    assert path.exists('/sys/kernel/debug/bluetooth/{}'.format(hci))

    if not path.exists(_BT_SERVICE_DIR):
        mkdir(_BT_SERVICE_DIR)

    vmax_ms = vmax * 1.25 

    logger.debug('Setting default conn_max_interval to %d (%f ms)' % (vmax, _raw2ms(vmax)))
    vmaxpath = __bt_debugfs_path(hci, 'conn_max_interval')
    # service content
    lines = [
        '# Setting default conn_max_interval',
        '# to avoid disconnect of some BLE devices that require it',
        '[Service]',
        'ExecStartPre=/bin/bash -c \'echo {} > {}\''.format(vmax, vmaxpath)
    ]

    logger.debug('---- BEGIN %s ----' % _BT_SERVICE_FILE)
    for line in lines:
        logger.debug(line)
    logger.debug('---- END ----')
    with open(_BT_SERVICE_FILE, 'w') as f:
        f.write('\n'.join(lines))
   
    if 1:
        # update it now and let the service to it next time after reboot/reload
        with open(vmaxpath, 'w') as f:
            f.write(str(int(vmax)))
    else:
        # alternative reload dameons to run the newly created startup service
        import subprocess
        logger.info('Reloading bluetooth daemon')
        p = subprocess.Popen(['systemctl', 'daemon-reload'], stdout=subprocess.PIPE)
        out, err = p.communicate()
        if p.returncode:
            raise RuntimeError('systemctl error %s' % err)


def __main():

    if system() != 'Linux':
        raise RuntimeError('Linux only')

    if geteuid() != 0:
        raise RuntimeError('Need root for this. try sudo')

    import argparse
    parser = argparse.ArgumentParser()

    parser.add_argument('--max', type=int,
            default=None, 
            help='')
    
    parser.add_argument('--min', type=int,
            default=None, 
            help='')

    parser.add_argument('--status', 
            default=False, 
            action='store_true',
            help='')

    parser.add_argument('--create-service', 
            default=False, 
            action='store_true',
            help='Creates a systemd service that set conn_max_interval')

    parser.add_argument('-v', '--verb', 
            default=False, 
            action='store_true',
            help='')

    parser.add_argument('--hci', 
            type=str,
            default='hci0',
            help='')

    args = parser.parse_args()
    if args.verb:
        level = logging.DEBUG
    else:
        level = logging.INFO

    handler = logging.StreamHandler()
    handler.setLevel(level)
    logger.setLevel(level)
    formatter = logging.Formatter('%(levelname)s: %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    if args.status:
        v = __bt_debugfs_get(args.hci, 'conn_min_interval')
        print('conn_min_interval: %d (%.2f ms)' % (v, _raw2ms(v)))

        v = __bt_debugfs_get(args.hci, 'conn_max_interval')
        print('conn_max_interval: %d (%.2f ms)' % (v, _raw2ms(v)))

        print('configured: %s' %  str(is_configured()))
        exit(0)

    if args.create_service:
        _create_service(hci=args.hci)
        exit(0)

    if not args.min is None:
       __bt_debugfs_set(args.hci, 'conn_min_interval', args.min)

    if not args.max is None:
       __bt_debugfs_set(args.hci, 'conn_max_interval', args.max)

if __name__ == '__main__':
    __main()
