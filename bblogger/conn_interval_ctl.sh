#!/bin/sh
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

echoerr() 
{ 
    echo "$@" 1>&2; 
}


CONN_MIN_INTERVAL="/sys/kernel/debug/bluetooth/hci0/conn_min_interval"
CONN_MAX_INTERVAL="/sys/kernel/debug/bluetooth/hci0/conn_max_interval"


configure_service()
{
    echo "Setting default conn_max_interval to 160 (200 ms)"
    # service content
    local S=""
    S="${S}# Setting default conn_max_interval to 160 (200 ms) to avoid \n"
    S="${S}# disconnect of some BLE devices that require it\n"
    S="${S}[Service]\n"
    S="${S}ExecStartPre=/bin/bash -c " # no newline here
    S="${S}'echo 160 > /sys/kernel/debug/bluetooth/hci0/conn_max_interval'\n"

    local BT_SERVICE_D="/etc/systemd/system/bluetooth.service.d" 
    mkdir -p $BT_SERVICE_D

    local BT_SERVICE_FILE="$BT_SERVICE_D/10-set-conn_interval.conf"
    echo "Creating $BT_SERVICE_FILE"
    echo "$S" > "$BT_SERVICE_FILE"

    echo "Reloading bluetooth daemon"
    systemctl daemon-reload
    if [ "$?" -ne 0 ]; then
        echoerr "systemctl exit with non-zero exit status"
    else
        echo "done"
    fi
}

assert_root()
{
    if [ $(id -u) -ne 0 ] ; then 
        echoerr "Please run as root!"
        exit 1
    fi
}

assert_root

case "$1" in
  "configure")
    configure_service
    ;;
  "get-min")
    cat $CONN_MIN_INTERVAL
    ;;
  "get-max")
    cat $CONN_MAX_INTERVAL
    ;;
  "set-max")
    echo 160 > $CONN_MAX_INTERVAL
    ;;
  *)
    echoerr "unknown arg"
    exit 1
    ;;
esac
