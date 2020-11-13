import sys
import os

BBLOG_CMD = ["bblog"]

def use_repo_sources(yes):
    global BBLOG_CMD
    if yes:
        # use local relative to this dir
        this_dir = os.path.dirname(os.path.realpath(__file__))
        bblog_dir = os.path.realpath(os.path.join(this_dir, "../bblogger"))
        sys.path.insert(0, bblog_dir)
        bblog_cli = os.path.join(bblog_dir, "cli.py")
        BBLOG_CMD = ["python3", bblog_cli]
    else:
        BBLOG_CMD = ["bblog"]

def mk_bblog_cmd(subarg, flags=None, **kwargs):
    global BBLOG_CMD
    cmd = list(BBLOG_CMD) # copy
    cmd.append(subarg)

    if flags:
        cmd.append(flags)
    cmd.append("-vvv")

    for k, v in kwargs.items():
        cmd.append("--{}".format(k))
        cmd.append("{}".format(str(v)))

    return cmd



def dump_run_res(r):
    def pline(*args, **kwargs):
        print(*args, file=sys.stdout, **kwargs)

    ind1 = " "
    ind2 = "   "
    pline(ind1, "---- COMMAND: ----")
    for x in r.args:
        pline(ind2, x)

    pline(ind1, "---- STDERR: ----")
    for x in r.stderr.split("\n"):
        pline(ind2, x)

    pline(ind1, "---- STDOUT: ----")
    for x in r.stdout.split("\n"):
        pline(ind2, x)

