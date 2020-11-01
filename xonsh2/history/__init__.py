# amalgamate exclude
import os as _os

if _os.getenv("XONSH_DEBUG", ""):
    pass
else:
    import sys as _sys

    try:
        from xonsh2.history import __amalgam__

        base = __amalgam__
        _sys.modules["xonsh2.history.base"] = __amalgam__
        dummy = __amalgam__
        _sys.modules["xonsh2.history.dummy"] = __amalgam__
        json = __amalgam__
        _sys.modules["xonsh2.history.json"] = __amalgam__
        sqlite = __amalgam__
        _sys.modules["xonsh2.history.sqlite"] = __amalgam__
        main = __amalgam__
        _sys.modules["xonsh2.history.main"] = __amalgam__
        del __amalgam__
    except ImportError:
        pass
    del _sys
del _os
# amalgamate end
