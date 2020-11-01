"""Constructor for xonsh completer objects."""
import collections

from xonsh2.completers.pip import complete_pip
from xonsh2.completers.man import complete_from_man
from xonsh2.completers.bash import complete_from_bash
from xonsh2.completers.base import complete_base
from xonsh2.completers.path import complete_path
from xonsh2.completers.dirs import complete_cd, complete_rmdir
from xonsh2.completers.python import (
    complete_python,
    complete_import,
    complete_python_mode,
)
from xonsh2.completers.commands import complete_skipper
from xonsh2.completers.completer import complete_completer
from xonsh2.completers.xompletions import complete_xonfig, complete_xontrib


def default_completers():
    """Creates a copy of the default completers."""
    return collections.OrderedDict(
        [
            ("python_mode", complete_python_mode),
            ("base", complete_base),
            ("completer", complete_completer),
            ("skip", complete_skipper),
            ("pip", complete_pip),
            ("cd", complete_cd),
            ("rmdir", complete_rmdir),
            ("xonfig", complete_xonfig),
            ("xontrib2", complete_xontrib),
            ("bash", complete_from_bash),
            ("man", complete_from_man),
            ("import", complete_import),
            ("python", complete_python),
            ("path", complete_path),
        ]
    )
