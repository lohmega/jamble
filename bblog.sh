#!/bin/sh
#
# wrapper to run cli.py in this dir and not the installed one, without
# modifications to pythons `sys.path` in source.  for development and
# debug/test. (something about virtualenv...)
#
# note: could also run as module `python3 -m bblogger.cli` but that only works
# in with correct PWD.


# `realpath` and `readlink -f` not on MacOS :(
_realpath()
{
    python3 -c "import os; print(os.path.realpath('$1'))"
}

# Absolute path to this script
SCRIPT=$(_realpath "$0")
# Absolute path this script is in
SCRIPTPATH=$(dirname "$SCRIPT")

PYTHONPATH="$SCRIPTPATH:$PYTHONPATH" 

# test with your dirty branch of "bleak" (Bluetooth LE lib)
# example `BLEAK=../myforks/bleak sh bblog.sh scan -vvvv`
if [ -n "$BLEAK" ]; then
    BLEAK=$(_realpath "$BLEAK")
    #echo "BLEAK $BLEAK"
    PYTHONPATH="$BLEAK/bleak:$PYTHONPATH" 
fi

# you can verify import paths with the following command
# PYTHONPATH="$PYTHONPATH" python3 -v $BBLOG -h 2>&1 | grep bblogger

echo "PYTHONPATH: $PYTHONPATH" 1>&2

BBLOG="$SCRIPTPATH/bblogger/cli.py"
PYTHONPATH="$PYTHONPATH" python3 $BBLOG "$@"


