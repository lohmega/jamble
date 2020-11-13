from subprocess import Popen, run, PIPE
from time import sleep
from glob import glob
import os
import sys
from pprint import pprint

from time import strftime
from tempfile import mkdtemp

import utils

def print_wrn(*args, **kwargs):
    print("WRN:", *args, file=sys.stderr, **kwargs)

def print_err(*args, **kwargs):
    print("ERR:", *args, file=sys.stderr, **kwargs)

def print_dbg(*args, **kwargs):
    print("DBG:", *args, file=sys.stderr, **kwargs)

def print_inf(*args, **kwargs):
    print("INF:", *args, file=sys.stdout, **kwargs)

def rm(glob_expr):
    """ same as shell `rm /foo/bar/*.txt` """
    for f in glob(glob_expr):
        os.remove(f)

def bblog(subarg, flags=None, child=False, **kwargs):

    cmd = utils.mk_bblog_cmd(subarg, flags, **kwargs)
    if child:
        return Popen(cmd)
    else:
        r = run(cmd, stdout=PIPE, universal_newlines=True, check=True)

        return r.stdout


def bblog_devices(from_file = "bb_addresses.txt"):
    """ return dict {<BLE address or macOS id> : <other info>}.
    from file if exists
    """
    if os.path.exists(from_file):
        print_inf("Getting device list from file", from_file)
        with open(from_file) as f:
            lines = f.readlines()
    else:
        print_inf("Getting device list from scan result")
        res = bblog("scan", timeout=10)
        print(res)
        lines = res.split("\n")

    devices = {}
    for line in lines:
        toks = line.split()
        if len(toks) > 0:
            addr = toks[0]
            devices[addr] = toks[1:]

    return devices

def bblog_foreach(addresses, subarg, **kwargs):

    #tss = strftime("%Y%m%dT%H%M%S%z")
    #mkdtemp(suffix=None, prefix=None, dir=None)¶
    opath = lambda s: "/tmp/bblog_output_{}.txt".format(s)
    rm(opath("*"))

    for arg in ("address", "outfile"):
        if kwargs.pop(arg, None):
            print_wrn("ignoring arg:", arg)

    outfiles = {}
    ps = {}
    for addr in addresses:
        outfile = opath(addr.replace(":", ""))
        outfiles[addr] = outfile
        p = bblog(subarg, child=True, address=addr, outfile=outfile, **kwargs)
        ps[p.pid] = p

    while True:
        pid, status = os.wait()

        if pid in ps:
            p = ps.pop(pid)
            if status != 0:
                print_err("pid", pid, "exit non-zero", status)
            #out, err = p.communicate()
            print_inf("Waiting for ", len(ps), "processes...")
        if not ps:
            break

    for of in outfiles:
        pass
    # eta = n_samples/rtd_hz + 2)
    # print("Waiting ", eta, "s to complete fetch...")
    # eta = n_samples/rtd_hz + 2)
    # sleep(eta)
    # print("n_samples=", n_samples, "rtd_hz=",rtd_hz)



def main():
    utils.use_repo_sources(True)

    devices = bblog_devices()
    if not devices:
        print_err("No devices found")
        return
    print(devices)

    addresses = devices.keys()
    bblog_foreach(addresses, "device-info")
main()
