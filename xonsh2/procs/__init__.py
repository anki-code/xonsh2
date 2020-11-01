# amalgamate exclude
import os as _os

if _os.getenv("XONSH_DEBUG", ""):
    pass
else:
    import sys as _sys

    try:
        from xonsh2.procs import __amalgam__

        readers = __amalgam__
        _sys.modules["xonsh2.procs.readers"] = __amalgam__
        pipelines = __amalgam__
        _sys.modules["xonsh2.procs.pipelines"] = __amalgam__
        posix = __amalgam__
        _sys.modules["xonsh2.procs.posix"] = __amalgam__
        proxies = __amalgam__
        _sys.modules["xonsh2.procs.proxies"] = __amalgam__
        specs = __amalgam__
        _sys.modules["xonsh2.procs.specs"] = __amalgam__
        del __amalgam__
    except ImportError:
        pass
    del _sys
del _os
# amalgamate end
