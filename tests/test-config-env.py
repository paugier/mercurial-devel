# Test the config layer generated by environment variables


import os

from mercurial import (
    encoding,
    extensions,
    rcutil,
    ui as uimod,
    util,
)

from mercurial.utils import procutil

testtmp = encoding.environ[b'TESTTMP']


# prepare hgrc files
def join(name):
    return os.path.join(testtmp, name)


with open(join(b'sysrc'), 'wb') as f:
    f.write(b'[ui]\neditor=e0\n[pager]\npager=p0\n')

with open(join(b'userrc'), 'wb') as f:
    f.write(b'[ui]\neditor=e1')


# replace rcpath functions so they point to the files above
def systemrcpath():
    return [join(b'sysrc')]


def userrcpath():
    return [join(b'userrc')]


extensions.wrapfunction(rcutil, 'default_rc_resources', lambda orig: [])

rcutil.systemrcpath = systemrcpath
rcutil.userrcpath = userrcpath


# utility to print configs
def printconfigs(env):
    encoding.environ = env
    rcutil._rccomponents = None  # reset cache
    ui = uimod.ui.load()
    for section, name, value in ui.walkconfig():
        source = ui.configsource(section, name)
        procutil.stdout.write(
            b'%s.%s=%s # %s\n' % (section, name, value, util.pconvert(source))
        )
    procutil.stdout.write(b'\n')


# environment variable overrides
printconfigs({})
printconfigs({b'EDITOR': b'e2', b'PAGER': b'p2'})
