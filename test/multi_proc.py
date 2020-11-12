from subprocess import Popen, run, PIPE
from time import sleep
from glob import glob
import os
import sys
from pprint import pprint

from time import strftime
from tempfile import mkdtemp

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

g_use_installed_bblog = True

def bblog(subarg, flags=None, child=False, **kwargs):
    """ testing as subprocess as the cli is (or should be) the more stable interface
    """

    if g_use_installed_bblog:
        cmd = ["bblog"]
    else:
        # use local relative to this dir
        this_dir = os.path.dirname(os.path.realpath(__file__))
        bblog_dir = os.path.realpath(os.path.join(this_dir, "../bblogger"))
        sys.path.insert(0, bblog_dir)
        bblog_cli = os.path.join(bblog_dir, "cli.py")
        cmd = ["python3", bblog_cli]


    cmd.append(subarg)

    if flags:
        cmd.append(flags)

    for k, v in kwargs.items():
        cmd.append("--{}".format(k))
        cmd.append("{}".format(str(v)))
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
    global g_use_installed_bblog
    g_use_installed_bblog = False

    devices = bblog_devices()
    if not devices:
        print_err("No devices found")
        return
    print(devices)

    addresses = devices.keys()
    bblog_foreach(addresses, "device-info")
main()
