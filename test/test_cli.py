
from subprocess import Popen, run, PIPE, CalledProcessError
from time import sleep
from glob import glob
import os
import sys
from pprint import pprint

import csv
import json

from time import strftime
from tempfile import mkdtemp

import utils

def print_fail(*args, **kwargs):
    print("FAILED:", *args, file=sys.stderr, **kwargs)

def print_ok(*args, **kwargs):
    print("OK:", *args, file=sys.stdout, **kwargs)


def bblog(subarg, flags=None, **kwargs):
    cmd = utils.mk_bblog_cmd(subarg, flags, **kwargs)

    r = run(cmd, stdout=PIPE, stderr=PIPE, universal_newlines=True)
    if r.returncode != 0:
        print_fail(subarg, "rc =", r.returncode)
        utils.dump_run_res(r)
        return 1
    fmt = kwargs.get("fmt")
   
    try:
        if fmt == "json":
            for line in r.stdout.split("\n"):
                json.loads(line)
        elif fmt == "csv":
            csv.reader(r.stdout)
    except Exception as e:
        print_fail(e)
        utils.dump_run_res(r)
        return 1

    print_ok(r.args)
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
    kwargs["logging"] = 1
    kwargs["interval"] = 1
    err += bblog("config-write", address=address, **kwargs)

    kwargs = {}
    kwargs["rtd"] = 1
    kwargs["num"] = 3
    for fmt in formats:
        err += bblog("fetch", address=address, fmt=fmt, **kwargs)

    kwargs = {}
    kwargs["num"] = 3
    sleep(3)
    err += bblog("fetch", address=address, **kwargs)


def main():
    #utils.use_repo_sources(True)
    addr = sys.argv[1]
    test_cli(addr)


main()
