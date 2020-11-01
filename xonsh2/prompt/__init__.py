# amalgamate exclude
import os as _os

if _os.getenv("XONSH_DEBUG", ""):
    pass
else:
    import sys as _sys

    try:
        from xonsh2.prompt import __amalgam__

        cwd = __amalgam__
        _sys.modules["xonsh2.prompt.cwd"] = __amalgam__
        env = __amalgam__
        _sys.modules["xonsh2.prompt.env"] = __amalgam__
        gitstatus = __amalgam__
        _sys.modules["xonsh2.prompt.gitstatus"] = __amalgam__
        job = __amalgam__
        _sys.modules["xonsh2.prompt.job"] = __amalgam__
        times = __amalgam__
        _sys.modules["xonsh2.prompt.times"] = __amalgam__
        vc = __amalgam__
        _sys.modules["xonsh2.prompt.vc"] = __amalgam__
        base = __amalgam__
        _sys.modules["xonsh2.prompt.base"] = __amalgam__
        del __amalgam__
    except ImportError:
        pass
    del _sys
del _os
# amalgamate end
