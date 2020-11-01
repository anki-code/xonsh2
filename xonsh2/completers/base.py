"""Base completer for xonsh2."""
import collections.abc as cabc

from xonsh2.completers.path import complete_path
from xonsh2.completers.python import complete_python
from xonsh2.completers.commands import complete_command


def complete_base(prefix, line, start, end, ctx):
    """If the line is empty, complete based on valid commands, python names,
    and paths.  If we are completing the first argument, complete based on
    valid commands and python names.
    """
    if line.strip() and prefix != line:
        # don't do unnecessary completions
        return set()

    # get and unpack python completions
    python_comps = complete_python(prefix, line, start, end, ctx)
    if isinstance(python_comps, cabc.Sequence):
        python_comps, python_comps_len = python_comps
    else:
        python_comps_len = None
    # add command completions
    out = python_comps | complete_command(prefix, line, start, end, ctx)
    # add paths, if needed
    if line.strip() == "":
        paths = complete_path(prefix, line, start, end, ctx, False)
        return (out | paths[0]), paths[1]
    elif prefix == line:
        if python_comps_len is None:
            return out
        else:
            return out, python_comps_len
    return set()
