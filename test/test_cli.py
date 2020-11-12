
from subprocess import Popen, run, PIPE, CalledProcessError
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


BBLOG_CMD = ["bblog"]

def use_repo_sources(enable):
    global BBLOG_CMD
    if enable
        # use local relative to this dir
        this_dir = os.path.dirname(os.path.realpath(__file__))
        bblog_dir = os.path.realpath(os.path.join(this_dir, "../bblogger"))
        sys.path.insert(0, bblog_dir)
        bblog_cli = os.path.join(bblog_dir, "cli.py")
        BBLOG_CMD = ["python3", bblog_cli]
    else:
        BBLOG_CMD = ["bblog"]

def bblog(subarg, flags=None, **kwargs):

    cmd = list(BBLOG_CMD) # copy
    cmd.append(subarg)

    if flags:
        cmd.append(flags)

    for k, v in kwargs.items():
        cmd.append("--{}".format(k))
        cmd.append("{}".format(str(v)))

    r = run(cmd, stdout=PIPE, stderr=PIPE, universal_newlines=True)
    if r.returncode != 0:
        print_err("FAILED", r)
        return 1
    else:
        print_inf("OK", r.args)
        return 0


def test_cli(address):
    """ test different commands and settings. As problems
    often are in lower level BLE API:s this test might expose them"""
    err = 0
    formats = ("txt", "csv", "json")
    for fmt in formats:
        err += bblog("scan", address=address, fmt=fmt)
        err += bblog("device-info", address=address, fmt=fmt)
        err += bblog("config-read", address=address, fmt=fmt)
    kwargs = {} 
    kwargs["timeout"] = 5
    kwargs["logging"] = True
    kwargs["interval"] = 1
    
    err += bblog("config-write", address=address, **kwargs)

    kwargs = {} 
    kwargs["rtd"] = 1
    kwargs["num"] = 3
    for fmt in formats:
        err += bblog("fetch", address=address, fmt=fmt, **kwargs)

    logger.info("Testing fetch rtd csv")
    kwargs["fmt"] = "csv"
    logger.info("args: %s" % str(kwargs))
    await do_fetch(**kwargs)

    logger.info("Testing fetch stored (but must sleep some sec first)")
    kwargs = {} 
    kwargs["num"] = 3
    sleep(3)
    err += bblog("fetch", address=address, **kwargs)
   

def main():
    use_repo_sources(True)
    addr = sys.argv[1]
    test_cli(addr)
