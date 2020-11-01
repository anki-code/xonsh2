"""Additional core utilities that are implemented in xonsh2. The current list
includes:

* cat
* echo
* pwd
* tee
* tty
* yes

In many cases, these may have a lower performance overhead than the
posix command line utility with the same name. This is because these
tools avoid the need for a full subprocess call. Additionally, these
tools are cross-platform.
"""
from xonsh2.xoreutils.cat import cat
from xonsh2.xoreutils.echo import echo
from xonsh2.xoreutils.pwd import pwd
from xonsh2.xoreutils.tee import tee
from xonsh2.xoreutils.tty import tty
from xonsh2.xoreutils.yes import yes

__all__ = ()

aliases["cat"] = cat
aliases["echo"] = echo
aliases["pwd"] = pwd
aliases["tee"] = tee
aliases["tty"] = tty
aliases["yes"] = yes
