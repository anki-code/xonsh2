# -*- coding: utf-8 -*-
"""Implements the xonsh parser."""
from xonsh2.lazyasd import lazyobject
from xonsh2.platform import PYTHON_VERSION_INFO


@lazyobject
def Parser():
    if PYTHON_VERSION_INFO > (3, 8):
        from xonsh2.parsers.v38 import Parser as p
    else:
        from xonsh2.parsers.v36 import Parser as p
    return p
