
def main():
    bblDevs = devices()
    if not bblDevs:
        print('No BlueBerry devices found')
        exit(0) # not an error

    with bblDevs[0].connect() as bbl:
        bbl._cLogEnable.write(0xffff, ctype='uint32')
        bbl._cSensEnable.write(0xffff, ctype='uint32')
        print('Fetching log entries')
        #bbl.fetch(rtd=False, nentries=5)
        bbl.fetch()
