"""Command pipeline tools."""
import os
import re
import io
import sys
import time
import signal
import builtins
import threading
import subprocess

import xonsh2.lazyasd as xl
import xonsh2.tools as xt
import xonsh2.platform as xp
import xonsh2.jobs as xj

from xonsh2.procs.readers import NonBlockingFDReader, ConsoleParallelReader, safe_fdclose


@xl.lazyobject
def STDOUT_CAPTURE_KINDS():
    return frozenset(["stdout", "object"])


@xl.lazyobject
def RE_HIDDEN_BYTES():
    return re.compile(b"(\001.*?\002)")


@xl.lazyobject
def RE_VT100_ESCAPE():
    return re.compile(b"(\x9B|\x1B\\[)[0-?]*[ -\\/]*[@-~]")


@xl.lazyobject
def RE_HIDE_ESCAPE():
    return re.compile(
        b"(" + RE_HIDDEN_BYTES.pattern + b"|" + RE_VT100_ESCAPE.pattern + b")"
    )


@xl.lazyobject
def SIGNAL_MESSAGES():
    sm = {
        signal.SIGABRT: "Aborted",
        signal.SIGFPE: "Floating point exception",
        signal.SIGILL: "Illegal instructions",
        signal.SIGTERM: "Terminated",
        signal.SIGSEGV: "Segmentation fault",
    }
    if xp.ON_POSIX:
        sm.update(
            {
                signal.SIGQUIT: "Quit",
                signal.SIGHUP: "Hangup",
                signal.SIGKILL: "Killed",
                signal.SIGTSTP: "Stopped",
            }
        )
    return sm


def safe_readlines(handle, hint=-1):
    """Attempts to read lines without throwing an error."""
    try:
        lines = handle.readlines(hint)
    except OSError:
        lines = []
    return lines


def safe_readable(handle):
    """Attempts to find if the handle is readable without throwing an error."""
    try:
        status = handle.readable()
    except (OSError, ValueError):
        status = False
    return status


def update_fg_process_group(pipeline_group, background):
    if background:
        return False
    if not xp.ON_POSIX:
        return False
    env = builtins.__xonsh__.env
    if not env.get("XONSH_INTERACTIVE"):
        return False
    return xj.give_terminal_to(pipeline_group)


class CommandPipeline:
    """Represents a subprocess-mode command pipeline."""

    attrnames = (
        "stdin",
        "stdout",
        "stderr",
        "pid",
        "returncode",
        "args",
        "alias",
        "stdin_redirect",
        "stdout_redirect",
        "stderr_redirect",
        "timestamps",
        "executed_cmd",
        "input",
        "output",
        "errors",
    )

    nonblocking = (io.BytesIO, NonBlockingFDReader, ConsoleParallelReader)

    def __init__(self, specs):
        """
        Parameters
        ----------
        specs : list of SubprocSpec
            Process specifications

        Attributes
        ----------
        spec : SubprocSpec
            The last specification in specs
        proc : Popen-like
            The process in procs
        ended : bool
            Boolean for if the command has stopped executing.
        input : str
            A string of the standard input.
        output : str
            A string of the standard output.
        errors : str
            A string of the standard error.
        lines : list of str
            The output lines
        starttime : floats or None
            Pipeline start timestamp.
        """
        self.starttime = None
        self.ended = False
        self.procs = []
        self.specs = specs
        self.spec = specs[-1]
        self.captured = specs[-1].captured
        self.input = self._output = self.errors = self.endtime = None
        self._closed_handle_cache = {}
        self.lines = []
        self._stderr_prefix = self._stderr_postfix = None
        self.term_pgid = None

        background = self.spec.background
        pipeline_group = None
        for spec in specs:
            if self.starttime is None:
                self.starttime = time.time()
            try:
                proc = spec.run(pipeline_group=pipeline_group)
            except Exception:
                xt.print_exception()
                self._return_terminal()
                self.proc = None
                return
            if (
                proc.pid
                and pipeline_group is None
                and not spec.is_proxy
                and self.captured != "object"
            ):
                pipeline_group = proc.pid
                if update_fg_process_group(pipeline_group, background):
                    self.term_pgid = pipeline_group
            self.procs.append(proc)
        self.proc = self.procs[-1]

    def __repr__(self):
        s = self.__class__.__name__ + "(\n  "
        s += ",\n  ".join(a + "=" + repr(getattr(self, a)) for a in self.attrnames)
        s += "\n)"
        return s

    def __str__(self):
       self.end()
       return self.output

    @property
    def str(self):
        return str(self)

    def __bool__(self):
        return self.returncode == 0

    def __len__(self):
        return len(self.procs)

    def __iter__(self):
        """Iterates through stdout and returns the lines, converting to
        strings and universal newlines if needed.
        """
        if self.ended:
            yield from iter(self.lines)
        else:
            yield from self.tee_stdout()

    def iterraw(self):
        """Iterates through the last stdout, and returns the lines
        exactly as found.
        """
        # get appropriate handles
        spec = self.spec
        proc = self.proc
        if proc is None:
            return
        timeout = builtins.__xonsh__.env.get("XONSH_PROC_FREQUENCY")
        # get the correct stdout
        stdout = proc.stdout
        if (
            stdout is None or spec.stdout is None or not safe_readable(stdout)
        ) and spec.captured_stdout is not None:
            stdout = spec.captured_stdout
        if hasattr(stdout, "buffer"):
            stdout = stdout.buffer
        if stdout is not None and not isinstance(stdout, self.nonblocking):
            stdout = NonBlockingFDReader(stdout.fileno(), timeout=timeout)
        if (
            not stdout
            or self.captured == "stdout"
            or not safe_readable(stdout)
            or not spec.threadable
        ):
            # we get here if the process is not threadable or the
            # class is the real Popen
            PrevProcCloser(pipeline=self)
            task = xj.wait_for_active_job()
            if task is None or task["status"] != "stopped":
                proc.wait()
                self._endtime()
                if self.captured == "object":
                    self.end(tee_output=False)
                elif self.captured == "hiddenobject" and stdout:
                    b = stdout.read()
                    lines = b.splitlines()
                    yield from lines
                    self.end(tee_output=False)
                elif self.captured == "stdout":
                    b = stdout.read()
                    s = self._decode_uninew(b, universal_newlines=True)
                    self.lines = s.splitlines()
            return
        # get the correct stderr
        stderr = proc.stderr
        if (
            stderr is None or spec.stderr is None or not safe_readable(stderr)
        ) and spec.captured_stderr is not None:
            stderr = spec.captured_stderr
        if hasattr(stderr, "buffer"):
            stderr = stderr.buffer
        if stderr is not None and not isinstance(stderr, self.nonblocking):
            stderr = NonBlockingFDReader(stderr.fileno(), timeout=timeout)
        # read from process while it is running
        check_prev_done = len(self.procs) == 1
        prev_end_time = None
        i = j = cnt = 1
        while proc.poll() is None:
            if getattr(proc, "suspended", False):
                return
            elif getattr(proc, "in_alt_mode", False):
                time.sleep(0.1)  # probably not leaving any time soon
                continue
            elif not check_prev_done:
                # In the case of pipelines with more than one command
                # we should give the commands a little time
                # to start up fully. This is particularly true for
                # GNU Parallel, which has a long startup time.
                pass
            elif self._prev_procs_done():
                self._close_prev_procs()
                proc.prevs_are_closed = True
                break
            stdout_lines = safe_readlines(stdout, 1024)
            i = len(stdout_lines)
            if i != 0:
                yield from stdout_lines
            stderr_lines = safe_readlines(stderr, 1024)
            j = len(stderr_lines)
            if j != 0:
                self.stream_stderr(stderr_lines)
            if not check_prev_done:
                # if we are piping...
                if stdout_lines or stderr_lines:
                    # see if we have some output.
                    check_prev_done = True
                elif prev_end_time is None:
                    # or see if we already know that the next-to-last
                    # proc in the pipeline has ended.
                    if self._prev_procs_done():
                        # if it has, record the time
                        prev_end_time = time.time()
                elif time.time() - prev_end_time >= 0.1:
                    # if we still don't have any output, even though the
                    # next-to-last proc has finished, wait a bit to make
                    # sure we have fully started up, etc.
                    check_prev_done = True
            # this is for CPU usage
            if i + j == 0:
                cnt = min(cnt + 1, 1000)
            else:
                cnt = 1
            time.sleep(timeout * cnt)
        # read from process now that it is over
        yield from safe_readlines(stdout)
        self.stream_stderr(safe_readlines(stderr))
        proc.wait()
        self._endtime()
        yield from safe_readlines(stdout)
        self.stream_stderr(safe_readlines(stderr))
        if self.captured == "object":
            self.end(tee_output=False)

    def itercheck(self):
        """Iterates through the command lines and throws an error if the
        returncode is non-zero.
        """
        yield from self
        if self.returncode:
            # I included self, as providing access to stderr and other details
            # useful when instance isn't assigned to a variable in the shell.
            raise xt.XonshCalledProcessError(
                self.returncode, self.executed_cmd, self.stdout, self.stderr, self
            )

    def tee_stdout(self):
        """Writes the process stdout to the output variable, line-by-line, and
        yields each line. This may optionally accept lines (in bytes) to iterate
        over, in which case it does not call iterraw().
        """
        env = builtins.__xonsh__.env
        enc = env.get("XONSH_ENCODING")
        err = env.get("XONSH_ENCODING_ERRORS")
        lines = self.lines
        stream = self.captured not in STDOUT_CAPTURE_KINDS
        if stream and not self.spec.stdout:
            stream = False
        stdout_has_buffer = hasattr(sys.stdout, "buffer")
        nl = b"\n"
        cr = b"\r"
        crnl = b"\r\n"
        for line in self.iterraw():
            # write to stdout line ASAP, if needed
            if stream:
                if stdout_has_buffer:
                    sys.stdout.buffer.write(line)
                else:
                    sys.stdout.write(line.decode(encoding=enc, errors=err))
                sys.stdout.flush()
            # do some munging of the line before we return it
            if line.endswith(crnl):
                line = line[:-2]
            elif line.endswith(cr) or line.endswith(nl):
                line = line[:-1]
            line = RE_HIDE_ESCAPE.sub(b"", line)
            line = line.decode(encoding=enc, errors=err)
            # tee it up!
            lines.append(line)
            yield line

    def stream_stderr(self, lines):
        """Streams lines to sys.stderr and the errors attribute."""
        if not lines:
            return
        env = builtins.__xonsh__.env
        enc = env.get("XONSH_ENCODING")
        err = env.get("XONSH_ENCODING_ERRORS")
        b = b"".join(lines)
        if self.stderr_prefix:
            b = self.stderr_prefix + b
        if self.stderr_postfix:
            b += self.stderr_postfix
        stderr_has_buffer = hasattr(sys.stderr, "buffer")
        # write bytes to std stream
        if stderr_has_buffer:
            sys.stderr.buffer.write(b)
        else:
            sys.stderr.write(b.decode(encoding=enc, errors=err))
        sys.stderr.flush()
        # do some munging of the line before we save it to the attr
        b = b.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
        b = RE_HIDE_ESCAPE.sub(b"", b)
        env = builtins.__xonsh__.env
        s = b.decode(
            encoding=env.get("XONSH_ENCODING"), errors=env.get("XONSH_ENCODING_ERRORS")
        )
        # set the errors
        if self.errors is None:
            self.errors = s
        else:
            self.errors += s

    def _decode_uninew(self, b, universal_newlines=None):
        """Decode bytes into a str and apply universal newlines as needed."""
        if not b:
            return ""
        if isinstance(b, bytes):
            env = builtins.__xonsh__.env
            s = b.decode(
                encoding=env.get("XONSH_ENCODING"),
                errors=env.get("XONSH_ENCODING_ERRORS"),
            )
        else:
            s = b
        if universal_newlines or self.spec.universal_newlines:
            s = s.replace("\r\n", "\n").replace("\r", "\n")
        return s

    #
    # Ending methods
    #

    def end(self, tee_output=True):
        """
        End the pipeline, return the controlling terminal if needed.

        Main things done in self._end().
        """
        if self.ended:
            return
        self._end(tee_output=tee_output)
        self._return_terminal()
        return self

    def _end(self, tee_output):
        """Waits for the command to complete and then runs any closing and
        cleanup procedures that need to be run.
        """
        if tee_output:
            for _ in self.tee_stdout():
                pass
        self._endtime()
        # since we are driven by getting output, input may not be available
        # until the command has completed.
        self._set_input()
        self._close_prev_procs()
        self._close_proc()
        self._check_signal()
        self._apply_to_history()
        self.ended = True
        self._raise_subproc_error()

    def _return_terminal(self):
        if xp.ON_WINDOWS or not xp.ON_POSIX:
            return
        pgid = os.getpgid(0)
        if self.term_pgid is None or pgid == self.term_pgid:
            return
        if xj.give_terminal_to(pgid):  # if gave term succeed
            self.term_pgid = pgid
            if builtins.__xonsh__.shell is not None:
                # restoring sanity could probably be called whenever we return
                # control to the shell. But it only seems to matter after a
                # ^Z event. This *has* to be called after we give the terminal
                # back to the shell.
                builtins.__xonsh__.shell.shell.restore_tty_sanity()

    def resume(self, job, tee_output=True):
        self.ended = False
        if xj.give_terminal_to(job["pgrp"]):
            self.term_pgid = job["pgrp"]
        xj._continue(job)
        self.end(tee_output=tee_output)

    def _endtime(self):
        """Sets the closing timestamp if it hasn't been already."""
        if self.endtime is None:
            self.endtime = time.time()

    def _safe_close(self, handle):
        safe_fdclose(handle, cache=self._closed_handle_cache)

    def _prev_procs_done(self):
        """Boolean for if all previous processes have completed. If there
        is only a single process in the pipeline, this returns False.
        """
        any_running = False
        for s, p in zip(self.specs[:-1], self.procs[:-1]):
            if p.poll() is None:
                any_running = True
                continue
            self._safe_close(s.stdin)
            self._safe_close(s.stdout)
            self._safe_close(s.stderr)
            if p is None:
                continue
            self._safe_close(p.stdin)
            self._safe_close(p.stdout)
            self._safe_close(p.stderr)
        return False if any_running else (len(self) > 1)

    def _close_prev_procs(self):
        """Closes all but the last proc's stdout."""
        for s, p in zip(self.specs[:-1], self.procs[:-1]):
            self._safe_close(s.stdin)
            self._safe_close(s.stdout)
            self._safe_close(s.stderr)
            if p is None:
                continue
            self._safe_close(p.stdin)
            self._safe_close(p.stdout)
            self._safe_close(p.stderr)

    def _close_proc(self):
        """Closes last proc's stdout."""
        s = self.spec
        p = self.proc
        self._safe_close(s.stdin)
        self._safe_close(s.stdout)
        self._safe_close(s.stderr)
        self._safe_close(s.captured_stdout)
        self._safe_close(s.captured_stderr)
        if p is None:
            return
        self._safe_close(p.stdin)
        self._safe_close(p.stdout)
        self._safe_close(p.stderr)

    def _set_input(self):
        """Sets the input variable."""
        if self.proc is None:
            return
        stdin = self.proc.stdin
        if (
            stdin is None
            or isinstance(stdin, int)
            or stdin.closed
            or not stdin.seekable()
            or not safe_readable(stdin)
        ):
            input = b""
        else:
            stdin.seek(0)
            input = stdin.read()
        self.input = self._decode_uninew(input)

    def _check_signal(self):
        """Checks if a signal was received and issues a message."""
        proc_signal = getattr(self.proc, "signal", None)
        if proc_signal is None:
            return
        sig, core = proc_signal
        sig_str = SIGNAL_MESSAGES.get(sig)
        if sig_str:
            if core:
                sig_str += " (core dumped)"
            print(sig_str, file=sys.stderr)
            if self.errors is not None:
                self.errors += sig_str + "\n"

    def _apply_to_history(self):
        """Applies the results to the current history object."""
        hist = builtins.__xonsh__.history
        if hist is not None:
            hist.last_cmd_rtn = 1 if self.proc is None else self.proc.returncode

    def _raise_subproc_error(self):
        """Raises a subprocess error, if we are supposed to."""
        spec = self.spec
        rtn = self.returncode
        if (
            rtn is not None
            and rtn != 0
            and builtins.__xonsh__.env.get("RAISE_SUBPROC_ERROR")
        ):
            try:
                raise subprocess.CalledProcessError(rtn, spec.args, output=self.output)
            finally:
                # this is need to get a working terminal in interactive mode
                self._return_terminal()

    #
    # Properties
    #

    @property
    def stdin(self):
        """Process stdin."""
        return self.proc.stdin

    @property
    def stdout(self):
        """Process stdout."""
        return self.proc.stdout

    @property
    def stderr(self):
        """Process stderr."""
        return self.proc.stderr

    @property
    def inp(self):
        """Creates normalized input string from args."""
        return " ".join(self.args)

    @property
    def output(self):
        """Non-blocking, lazy access to output"""
        if self.ended:
            if self._output is None:
                self._output = "\n".join(self.lines)
            return self._output
        else:
            return "\n".join(self.lines)

    @property
    def out(self):
        """Output value as a str."""
        self.end()
        return self.output

    @property
    def err(self):
        """Error messages as a string."""
        self.end()
        return self.errors

    @property
    def pid(self):
        """Process identifier."""
        return self.proc.pid

    @property
    def returncode(self):
        """Process return code, waits until command is completed."""
        self.end()
        if self.proc is None:
            return 1
        return self.proc.returncode

    @property
    def args(self):
        """Arguments to the process."""
        return self.spec.args

    @property
    def rtn(self):
        """Alias to return code."""
        return self.returncode

    @property
    def alias(self):
        """Alias the process used."""
        return self.spec.alias

    @property
    def stdin_redirect(self):
        """Redirection used for stdin."""
        stdin = self.spec.stdin
        name = getattr(stdin, "name", "<stdin>")
        mode = getattr(stdin, "mode", "r")
        return [name, mode]

    @property
    def stdout_redirect(self):
        """Redirection used for stdout."""
        stdout = self.spec.stdout
        name = getattr(stdout, "name", "<stdout>")
        mode = getattr(stdout, "mode", "a")
        return [name, mode]

    @property
    def stderr_redirect(self):
        """Redirection used for stderr."""
        stderr = self.spec.stderr
        name = getattr(stderr, "name", "<stderr>")
        mode = getattr(stderr, "mode", "r")
        return [name, mode]

    @property
    def timestamps(self):
        """The start and end time stamps."""
        return [self.starttime, self.endtime]

    @property
    def executed_cmd(self):
        """The resolve and executed command."""
        return self.spec.cmd

    @property
    def stderr_prefix(self):
        """Prefix to print in front of stderr, as bytes."""
        p = self._stderr_prefix
        if p is None:
            env = builtins.__xonsh__.env
            t = env.get("XONSH_STDERR_PREFIX")
            s = xt.format_std_prepost(t, env=env)
            p = s.encode(
                encoding=env.get("XONSH_ENCODING"),
                errors=env.get("XONSH_ENCODING_ERRORS"),
            )
            self._stderr_prefix = p
        return p

    @property
    def stderr_postfix(self):
        """Postfix to print after stderr, as bytes."""
        p = self._stderr_postfix
        if p is None:
            env = builtins.__xonsh__.env
            t = env.get("XONSH_STDERR_POSTFIX")
            s = xt.format_std_prepost(t, env=env)
            p = s.encode(
                encoding=env.get("XONSH_ENCODING"),
                errors=env.get("XONSH_ENCODING_ERRORS"),
            )
            self._stderr_postfix = p
        return p

    """
    String functions
    """
    def capitalize(self, *a, **kw):
        return str(self).capitalize(*a, **kw)

    def lines_capitalize(self, *a, **kw):
        return [l.capitalize(*a, **kw) for l in self]

    def casefold(self, *a, **kw):
        return str(self).casefold(*a, **kw)

    def lines_casefold(self, *a, **kw):
        return [l.casefold(*a, **kw) for l in self]

    def center(self, *a, **kw):
        return str(self).center(*a, **kw)

    def lines_center(self, *a, **kw):
        return [l.center(*a, **kw) for l in self]

    def str_count(self, *a, **kw):
        return str(self).count(*a, **kw)

    def lines_count(self, *a, **kw):
        return [l.count(*a, **kw) for l in self]

    def encode(self, *a, **kw):
        return str(self).encode(*a, **kw)

    def lines_encode(self, *a, **kw):
        return [l.encode(*a, **kw) for l in self]

    def endswith(self, *a, **kw):
        return str(self).endswith(*a, **kw)

    def lines_endswith(self, *a, **kw):
        return [l.endswith(*a, **kw) for l in self]

    def expandtabs(self, *a, **kw):
        return str(self).expandtabs(*a, **kw)

    def lines_expandtabs(self, *a, **kw):
        return [l.expandtabs(*a, **kw) for l in self]

    def find(self, *a, **kw):
        return str(self).find(*a, **kw)

    def lines_find(self, *a, **kw):
        return [l.find(*a, **kw) for l in self]

    def format(self, *a, **kw):
        return str(self).format(*a, **kw)

    def lines_format(self, *a, **kw):
        return [l.format(*a, **kw) for l in self]

    def format_map(self, *a, **kw):
        return str(self).format_map(*a, **kw)

    def lines_format_map(self, *a, **kw):
        return [l.format_map(*a, **kw) for l in self]

    def str_index(self, *a, **kw):
        return str(self).index(*a, **kw)

    def lines_index(self, *a, **kw):
        return [l.index(*a, **kw) for l in self]

    def isalnum(self, *a, **kw):
        return str(self).isalnum(*a, **kw)

    def lines_isalnum(self, *a, **kw):
        return [l.isalnum(*a, **kw) for l in self]

    def isalpha(self, *a, **kw):
        return str(self).isalpha(*a, **kw)

    def lines_isalpha(self, *a, **kw):
        return [l.isalpha(*a, **kw) for l in self]

    def isascii(self, *a, **kw):
        return str(self).isascii(*a, **kw)

    def lines_isascii(self, *a, **kw):
        return [l.isascii(*a, **kw) for l in self]

    def isdecimal(self, *a, **kw):
        return str(self).isdecimal(*a, **kw)

    def lines_isdecimal(self, *a, **kw):
        return [l.isdecimal(*a, **kw) for l in self]

    def isdigit(self, *a, **kw):
        return str(self).isdigit(*a, **kw)

    def lines_isdigit(self, *a, **kw):
        return [l.isdigit(*a, **kw) for l in self]

    def isidentifier(self, *a, **kw):
        return str(self).isidentifier(*a, **kw)

    def lines_isidentifier(self, *a, **kw):
        return [l.isidentifier(*a, **kw) for l in self]

    def islower(self, *a, **kw):
        return str(self).islower(*a, **kw)

    def lines_islower(self, *a, **kw):
        return [l.islower(*a, **kw) for l in self]

    def isnumeric(self, *a, **kw):
        return str(self).isnumeric(*a, **kw)

    def lines_isnumeric(self, *a, **kw):
        return [l.isnumeric(*a, **kw) for l in self]

    def isprintable(self, *a, **kw):
        return str(self).isprintable(*a, **kw)

    def lines_isprintable(self, *a, **kw):
        return [l.isprintable(*a, **kw) for l in self]

    def isspace(self, *a, **kw):
        return str(self).isspace(*a, **kw)

    def lines_isspace(self, *a, **kw):
        return [l.isspace(*a, **kw) for l in self]

    def istitle(self, *a, **kw):
        return str(self).istitle(*a, **kw)

    def lines_istitle(self, *a, **kw):
        return [l.istitle(*a, **kw) for l in self]

    def isupper(self, *a, **kw):
        return str(self).isupper(*a, **kw)

    def lines_isupper(self, *a, **kw):
        return [l.isupper(*a, **kw) for l in self]

    def join(self, *a, **kw):
        return str(self).join(*a, **kw)

    def lines_join(self, *a, **kw):
        return [l.join(*a, **kw) for l in self]

    def ljust(self, *a, **kw):
        return str(self).ljust(*a, **kw)

    def lines_ljust(self, *a, **kw):
        return [l.ljust(*a, **kw) for l in self]

    def lower(self, *a, **kw):
        return str(self).lower(*a, **kw)

    def lines_lower(self, *a, **kw):
        return [l.lower(*a, **kw) for l in self]

    def lstrip(self, *a, **kw):
        return str(self).lstrip(*a, **kw)

    def lines_lstrip(self, *a, **kw):
        return [l.lstrip(*a, **kw) for l in self]

    def maketrans(self, *a, **kw):
        return str(self).maketrans(*a, **kw)

    def lines_maketrans(self, *a, **kw):
        return [l.maketrans(*a, **kw) for l in self]

    def partition(self, *a, **kw):
        return str(self).partition(*a, **kw)

    def lines_partition(self, *a, **kw):
        return [l.partition(*a, **kw) for l in self]

    def replace(self, *a, **kw):
        return str(self).replace(*a, **kw)

    def lines_replace(self, *a, **kw):
        return [l.replace(*a, **kw) for l in self]

    def rfind(self, *a, **kw):
        return str(self).rfind(*a, **kw)

    def lines_rfind(self, *a, **kw):
        return [l.rfind(*a, **kw) for l in self]

    def rindex(self, *a, **kw):
        return str(self).rindex(*a, **kw)

    def lines_rindex(self, *a, **kw):
        return [l.rindex(*a, **kw) for l in self]

    def rjust(self, *a, **kw):
        return str(self).rjust(*a, **kw)

    def lines_rjust(self, *a, **kw):
        return [l.rjust(*a, **kw) for l in self]

    def rpartition(self, *a, **kw):
        return str(self).rpartition(*a, **kw)

    def lines_rpartition(self, *a, **kw):
        return [l.rpartition(*a, **kw) for l in self]

    def rsplit(self, *a, **kw):
        return str(self).rsplit(*a, **kw)

    def lines_rsplit(self, *a, **kw):
        return [l.rsplit(*a, **kw) for l in self]

    def rstrip(self, *a, **kw):
        return str(self).rstrip(*a, **kw)

    def lines_rstrip(self, *a, **kw):
        return [l.rstrip(*a, **kw) for l in self]

    def split(self, *a, **kw):
        return str(self).split(*a, **kw)

    def lines_split(self, *a, **kw):
        return [l.split(*a, **kw) for l in self]

    def splitlines(self, *a, **kw):
        return str(self).splitlines(*a, **kw)

    def lines_splitlines(self, *a, **kw):
        return [l.splitlines(*a, **kw) for l in self]

    def startswith(self, *a, **kw):
        return str(self).startswith(*a, **kw)

    def lines_startswith(self, *a, **kw):
        return [l.startswith(*a, **kw) for l in self]

    def strip(self, *a, **kw):
        return str(self).strip(*a, **kw)

    def lines_strip(self, *a, **kw):
        return [l.strip(*a, **kw) for l in self]

    def swapcase(self, *a, **kw):
        return str(self).swapcase(*a, **kw)

    def lines_swapcase(self, *a, **kw):
        return [l.swapcase(*a, **kw) for l in self]

    def title(self, *a, **kw):
        return str(self).title(*a, **kw)

    def lines_title(self, *a, **kw):
        return [l.title(*a, **kw) for l in self]

    def translate(self, *a, **kw):
        return str(self).translate(*a, **kw)

    def lines_translate(self, *a, **kw):
        return [l.translate(*a, **kw) for l in self]

    def upper(self, *a, **kw):
        return str(self).upper(*a, **kw)

    def lines_upper(self, *a, **kw):
        return [l.upper(*a, **kw) for l in self]

    def zfill(self, *a, **kw):
        return str(self).zfill(*a, **kw)

    def lines_zfill(self, *a, **kw):
        return [l.zfill(*a, **kw) for l in self]




class HiddenCommandPipeline(CommandPipeline):
    def __repr__(self):
        return ""


def pause_call_resume(p, f, *args, **kwargs):
    """For a process p, this will call a function f with the remaining args and
    and kwargs. If the process cannot accept signals, the function will be called.

    Parameters
    ----------
    p : Popen object or similar
    f : callable
    args : remaining arguments
    kwargs : keyword arguments
    """
    can_send_signal = (
        hasattr(p, "send_signal")
        and xp.ON_POSIX
        and not xp.ON_MSYS
        and not xp.ON_CYGWIN
    )
    if can_send_signal:
        try:
            p.send_signal(signal.SIGSTOP)
        except PermissionError:
            pass
    try:
        f(*args, **kwargs)
    except Exception:
        pass
    if can_send_signal:
        p.send_signal(signal.SIGCONT)


class PrevProcCloser(threading.Thread):
    """Previous process closer thread for pipelines whose last command
    is itself unthreadable. This makes sure that the pipeline is
    driven forward and does not deadlock.
    """

    def __init__(self, pipeline):
        """
        Parameters
        ----------
        pipeline : CommandPipeline
            The pipeline whose prev procs we should close.
        """
        self.pipeline = pipeline
        super().__init__()
        self.daemon = True
        self.start()

    def run(self):
        """Runs the closing algorithm."""
        pipeline = self.pipeline
        check_prev_done = len(pipeline.procs) == 1
        if check_prev_done:
            return
        proc = pipeline.proc
        prev_end_time = None
        timeout = builtins.__xonsh__.env.get("XONSH_PROC_FREQUENCY")
        sleeptime = min(timeout * 1000, 0.1)
        while proc.poll() is None:
            if not check_prev_done:
                # In the case of pipelines with more than one command
                # we should give the commands a little time
                # to start up fully. This is particularly true for
                # GNU Parallel, which has a long startup time.
                pass
            elif pipeline._prev_procs_done():
                pipeline._close_prev_procs()
                proc.prevs_are_closed = True
                break
            if not check_prev_done:
                # if we are piping...
                if prev_end_time is None:
                    # or see if we already know that the next-to-last
                    # proc in the pipeline has ended.
                    if pipeline._prev_procs_done():
                        # if it has, record the time
                        prev_end_time = time.time()
                elif time.time() - prev_end_time >= 0.1:
                    # if we still don't have any output, even though the
                    # next-to-last proc has finished, wait a bit to make
                    # sure we have fully started up, etc.
                    check_prev_done = True
            # this is for CPU usage
            time.sleep(sleeptime)
