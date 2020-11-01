__version__ = "xonsh2 fork from " + "0.9.24"


# amalgamate exclude jupyter_kernel parser_table parser_test_table pyghooks
# amalgamate exclude winutils wizard pytest_plugin fs macutils pygments_cache
# amalgamate exclude jupyter_shell
import os as _os

if _os.getenv("XONSH_DEBUG", ""):
    pass
else:
    import sys as _sys

    try:
        from xonsh2 import __amalgam__

        contexts = __amalgam__
        _sys.modules["xonsh2.contexts"] = __amalgam__
        lazyasd = __amalgam__
        _sys.modules["xonsh2.lazyasd"] = __amalgam__
        lazyjson = __amalgam__
        _sys.modules["xonsh2.lazyjson"] = __amalgam__
        platform = __amalgam__
        _sys.modules["xonsh2.platform"] = __amalgam__
        pretty = __amalgam__
        _sys.modules["xonsh2.pretty"] = __amalgam__
        codecache = __amalgam__
        _sys.modules["xonsh2.codecache"] = __amalgam__
        lazyimps = __amalgam__
        _sys.modules["xonsh2.lazyimps"] = __amalgam__
        parser = __amalgam__
        _sys.modules["xonsh2.parser"] = __amalgam__
        tokenize = __amalgam__
        _sys.modules["xonsh2.tokenize"] = __amalgam__
        tools = __amalgam__
        _sys.modules["xonsh2.tools"] = __amalgam__
        ast = __amalgam__
        _sys.modules["xonsh2.ast"] = __amalgam__
        color_tools = __amalgam__
        _sys.modules["xonsh2.color_tools"] = __amalgam__
        commands_cache = __amalgam__
        _sys.modules["xonsh2.commands_cache"] = __amalgam__
        completer = __amalgam__
        _sys.modules["xonsh2.completer"] = __amalgam__
        diff_history = __amalgam__
        _sys.modules["xonsh2.diff_history"] = __amalgam__
        events = __amalgam__
        _sys.modules["xonsh2.events"] = __amalgam__
        foreign_shells = __amalgam__
        _sys.modules["xonsh2.foreign_shells"] = __amalgam__
        jobs = __amalgam__
        _sys.modules["xonsh2.jobs"] = __amalgam__
        jsonutils = __amalgam__
        _sys.modules["xonsh2.jsonutils"] = __amalgam__
        lexer = __amalgam__
        _sys.modules["xonsh2.lexer"] = __amalgam__
        openpy = __amalgam__
        _sys.modules["xonsh2.openpy"] = __amalgam__
        xontribs = __amalgam__
        _sys.modules["xonsh2.xontribs"] = __amalgam__
        ansi_colors = __amalgam__
        _sys.modules["xonsh2.ansi_colors"] = __amalgam__
        dirstack = __amalgam__
        _sys.modules["xonsh2.dirstack"] = __amalgam__
        shell = __amalgam__
        _sys.modules["xonsh2.shell"] = __amalgam__
        style_tools = __amalgam__
        _sys.modules["xonsh2.style_tools"] = __amalgam__
        timings = __amalgam__
        _sys.modules["xonsh2.timings"] = __amalgam__
        xonfig = __amalgam__
        _sys.modules["xonsh2.xonfig"] = __amalgam__
        base_shell = __amalgam__
        _sys.modules["xonsh2.base_shell"] = __amalgam__
        environ = __amalgam__
        _sys.modules["xonsh2.environ"] = __amalgam__
        inspectors = __amalgam__
        _sys.modules["xonsh2.inspectors"] = __amalgam__
        aliases = __amalgam__
        _sys.modules["xonsh2.aliases"] = __amalgam__
        readline_shell = __amalgam__
        _sys.modules["xonsh2.readline_shell"] = __amalgam__
        tracer = __amalgam__
        _sys.modules["xonsh2.tracer"] = __amalgam__
        built_ins = __amalgam__
        _sys.modules["xonsh2.built_ins"] = __amalgam__
        dumb_shell = __amalgam__
        _sys.modules["xonsh2.dumb_shell"] = __amalgam__
        execer = __amalgam__
        _sys.modules["xonsh2.execer"] = __amalgam__
        imphooks = __amalgam__
        _sys.modules["xonsh2.imphooks"] = __amalgam__
        main = __amalgam__
        _sys.modules["xonsh2.main"] = __amalgam__
        del __amalgam__
    except ImportError:
        pass
    del _sys
del _os
# amalgamate end
