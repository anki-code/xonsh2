# -*- coding: utf-8 -*-
"""The prompt_toolkit based xonsh shell."""
import os
import re
import sys
import builtins
from types import MethodType

from xonsh2.events import events
from xonsh2.base_shell import BaseShell
from xonsh2.ptk_shell.formatter import PTKPromptFormatter
from xonsh2.shell import transform_command
from xonsh2.tools import print_exception, carriage_return
from xonsh2.platform import HAS_PYGMENTS, ON_WINDOWS, ON_POSIX
from xonsh2.style_tools import partial_color_tokenize, _TokenType, DEFAULT_STYLE_DICT
from xonsh2.lazyimps import pygments, pyghooks, winutils
from xonsh2.pygments_cache import get_all_styles
from xonsh2.ptk_shell.history import PromptToolkitHistory, _cust_history_matches
from xonsh2.ptk_shell.completer import PromptToolkitCompleter
from xonsh2.ptk_shell.key_bindings import load_xonsh_bindings

from prompt_toolkit import ANSI
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.lexers import PygmentsLexer
from prompt_toolkit.enums import EditingMode
from prompt_toolkit.key_binding.bindings.emacs import (
    load_emacs_shift_selection_bindings,
)
from prompt_toolkit.key_binding.key_bindings import merge_key_bindings
from prompt_toolkit.history import ThreadedHistory
from prompt_toolkit.shortcuts import print_formatted_text as ptk_print
from prompt_toolkit.shortcuts import CompleteStyle
from prompt_toolkit.shortcuts.prompt import PromptSession
from prompt_toolkit.formatted_text import PygmentsTokens, to_formatted_text
from prompt_toolkit.styles import merge_styles, Style
from prompt_toolkit.styles.pygments import (
    style_from_pygments_cls,
    style_from_pygments_dict,
)


ANSI_OSC_PATTERN = re.compile("\x1b].*?\007")
Token = _TokenType()

events.transmogrify("on_ptk_create", "LoadEvent")
events.doc(
    "on_ptk_create",
    """
on_ptk_create(prompter: PromptSession, history: PromptToolkitHistory, completer: PromptToolkitCompleter, bindings: KeyBindings) ->

Fired after prompt toolkit has been initialized
""",
)


def tokenize_ansi(tokens):
    """Checks a list of (token, str) tuples for ANSI escape sequences and
    extends the token list with the new formatted entries.
    During processing tokens are converted to ``prompt_toolkit.FormattedText``.
    Returns a list of similar (token, str) tuples.
    """
    formatted_tokens = to_formatted_text(tokens)
    ansi_tokens = []
    for style, text in formatted_tokens:
        if "\x1b" in text:
            formatted_ansi = to_formatted_text(ANSI(text))
            ansi_text = ""
            prev_style = ""
            for ansi_style, ansi_text_part in formatted_ansi:
                if prev_style == ansi_style:
                    ansi_text += ansi_text_part
                else:
                    ansi_tokens.append((prev_style or style, ansi_text))
                    prev_style = ansi_style
                    ansi_text = ansi_text_part
            ansi_tokens.append((prev_style or style, ansi_text))
        else:
            ansi_tokens.append((style, text))
    return ansi_tokens


def remove_ansi_osc(prompt):
    """Removes the ANSI OSC escape codes - ``prompt_toolkit`` does not support them.
    Some terminal emulators - like iTerm2 - uses them for various things.

    See: https://www.iterm2.com/documentation-escape-codes.html
    """

    osc_tokens = ANSI_OSC_PATTERN.findall(prompt)
    prompt = ANSI_OSC_PATTERN.sub("", prompt)

    return prompt, osc_tokens


class PromptToolkitShell(BaseShell):
    """The xonsh shell for prompt_toolkit v2 and later."""

    completion_displays_to_styles = {
        "multi": CompleteStyle.MULTI_COLUMN,
        "single": CompleteStyle.COLUMN,
        "readline": CompleteStyle.READLINE_LIKE,
        "none": None,
    }

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if ON_WINDOWS:
            winutils.enable_virtual_terminal_processing()
        self._first_prompt = True
        self.history = ThreadedHistory(PromptToolkitHistory())
        self.prompter = PromptSession(history=self.history)
        self.prompt_formatter = PTKPromptFormatter(self.prompter)
        self.pt_completer = PromptToolkitCompleter(self.completer, self.ctx, self)
        self.key_bindings = load_xonsh_bindings()

        # Store original `_history_matches` in case we need to restore it
        self._history_matches_orig = self.prompter.default_buffer._history_matches
        # This assumes that PromptToolkitShell is a singleton
        events.on_ptk_create.fire(
            prompter=self.prompter,
            history=self.history,
            completer=self.pt_completer,
            bindings=self.key_bindings,
        )
        # Goes at the end, since _MergedKeyBindings objects do not have
        # an add() function, which is necessary for on_ptk_create events
        self.key_bindings = merge_key_bindings(
            [self.key_bindings, load_emacs_shift_selection_bindings()]
        )

    def singleline(
        self, auto_suggest=None, enable_history_search=True, multiline=True, **kwargs
    ):
        """Reads a single line of input from the shell. The store_in_history
        kwarg flags whether the input should be stored in PTK's in-memory
        history.
        """
        events.on_pre_prompt_format.fire()
        env = builtins.__xonsh__.env
        mouse_support = env.get("MOUSE_SUPPORT")
        auto_suggest = auto_suggest if env.get("AUTO_SUGGEST") else None
        refresh_interval = env.get("PROMPT_REFRESH_INTERVAL")
        refresh_interval = refresh_interval if refresh_interval > 0 else None
        complete_in_thread = env.get("COMPLETION_IN_THREAD")
        completions_display = env.get("COMPLETIONS_DISPLAY")
        complete_style = self.completion_displays_to_styles[completions_display]

        complete_while_typing = env.get("UPDATE_COMPLETIONS_ON_KEYPRESS")
        if complete_while_typing:
            # PTK requires history search to be none when completing while typing
            enable_history_search = False
        if HAS_PYGMENTS:
            self.styler.style_name = env.get("XONSH_COLOR_STYLE")
        completer = None if completions_display == "none" else self.pt_completer

        events.on_timingprobe.fire(name="on_pre_prompt_tokenize")
        get_bottom_toolbar_tokens = self.bottom_toolbar_tokens
        if env.get("UPDATE_PROMPT_ON_KEYPRESS"):
            get_prompt_tokens = self.prompt_tokens
            get_rprompt_tokens = self.rprompt_tokens
        else:
            get_prompt_tokens = self.prompt_tokens()
            get_rprompt_tokens = self.rprompt_tokens()
            if get_bottom_toolbar_tokens:
                get_bottom_toolbar_tokens = get_bottom_toolbar_tokens()
        events.on_timingprobe.fire(name="on_post_prompt_tokenize")

        if env.get("VI_MODE"):
            editing_mode = EditingMode.VI
        else:
            editing_mode = EditingMode.EMACS

        if env.get("XONSH_HISTORY_MATCH_ANYWHERE"):
            self.prompter.default_buffer._history_matches = MethodType(
                _cust_history_matches, self.prompter.default_buffer
            )
        elif (
            self.prompter.default_buffer._history_matches
            is not self._history_matches_orig
        ):
            self.prompter.default_buffer._history_matches = self._history_matches_orig

        prompt_args = {
            "mouse_support": mouse_support,
            "auto_suggest": auto_suggest,
            "message": get_prompt_tokens,
            "rprompt": get_rprompt_tokens,
            "bottom_toolbar": get_bottom_toolbar_tokens,
            "completer": completer,
            "multiline": multiline,
            "editing_mode": editing_mode,
            "prompt_continuation": self.continuation_tokens,
            "enable_history_search": enable_history_search,
            "reserve_space_for_menu": 0,
            "key_bindings": self.key_bindings,
            "complete_style": complete_style,
            "complete_while_typing": complete_while_typing,
            "include_default_pygments_style": False,
            "refresh_interval": refresh_interval,
            "complete_in_thread": complete_in_thread,
        }

        if env.get("COLOR_INPUT"):
            events.on_timingprobe.fire(name="on_pre_prompt_style")
            if HAS_PYGMENTS:
                prompt_args["lexer"] = PygmentsLexer(pyghooks.XonshLexer)
                style = style_from_pygments_cls(pyghooks.xonsh_style_proxy(self.styler))
            else:
                style = style_from_pygments_dict(DEFAULT_STYLE_DICT)
            prompt_args["style"] = style
            events.on_timingprobe.fire(name="on_post_prompt_style")

            style_overrides_env = env.get("PTK_STYLE_OVERRIDES")
            if style_overrides_env:
                try:
                    style_overrides = Style.from_dict(style_overrides_env)
                    prompt_args["style"] = merge_styles([style, style_overrides])
                except (AttributeError, TypeError, ValueError):
                    print_exception()

        if env["ENABLE_ASYNC_PROMPT"]:
            # once the prompt is done, update it in background as each future is completed
            prompt_args["pre_run"] = self.prompt_formatter.start_update

        events.on_pre_prompt.fire()
        line = self.prompter.prompt(**prompt_args)
        events.on_post_prompt.fire()
        return line

    def _push(self, line):
        """Pushes a line onto the buffer and compiles the code in a way that
        enables multiline input.
        """
        code = None
        self.buffer.append(line)
        if self.need_more_lines:
            return None, code
        src = "".join(self.buffer)
        src = transform_command(src)
        try:
            code = self.execer.compile(src, mode="single", glbs=self.ctx, locs=None)
            self.reset_buffer()
        except Exception:  # pylint: disable=broad-except
            self.reset_buffer()
            print_exception()
            return src, None
        return src, code

    def cmdloop(self, intro=None):
        """Enters a loop that reads and execute input from user."""
        if intro:
            print(intro)
        auto_suggest = AutoSuggestFromHistory()
        self.push = self._push
        while not builtins.__xonsh__.exit:
            try:
                line = self.singleline(auto_suggest=auto_suggest)
                if not line:
                    self.emptyline()
                else:
                    line = self.precmd(line)
                    self.default(line)
            except (KeyboardInterrupt, SystemExit):
                self.reset_buffer()
            except EOFError:
                if builtins.__xonsh__.env.get("IGNOREEOF"):
                    print('Use "exit" to leave the shell.', file=sys.stderr)
                else:
                    break

    def _get_prompt_tokens(self, env_name: str, prompt_name: str, **kwargs):
        env = builtins.__xonsh__.env  # type:ignore
        p = env.get(env_name)

        if not p and "default" in kwargs:
            return kwargs.pop("default")

        try:
            p = self.prompt_formatter(
                template=p, threaded=env["ENABLE_ASYNC_PROMPT"], prompt_name=prompt_name
            )
        except Exception:  # pylint: disable=broad-except
            print_exception()

        p, osc_tokens = remove_ansi_osc(p)

        if kwargs.get("handle_osc_tokens"):
            # handle OSC tokens
            for osc in osc_tokens:
                if osc[2:4] == "0;":
                    env["TITLE"] = osc[4:-1]
                else:
                    print(osc, file=sys.__stdout__, flush=True)

        toks = partial_color_tokenize(p)

        return tokenize_ansi(PygmentsTokens(toks))

    def prompt_tokens(self):
        """Returns a list of (token, str) tuples for the current prompt."""
        if self._first_prompt:
            carriage_return()
            self._first_prompt = False

        tokens = self._get_prompt_tokens("PROMPT", "message", handle_osc_tokens=True)
        self.settitle()
        return tokens

    def rprompt_tokens(self):
        """Returns a list of (token, str) tuples for the current right
        prompt.
        """
        return self._get_prompt_tokens("RIGHT_PROMPT", "rprompt", default=[])

    def _bottom_toolbar_tokens(self):
        """Returns a list of (token, str) tuples for the current bottom
        toolbar.
        """
        return self._get_prompt_tokens("BOTTOM_TOOLBAR", "bottom_toolbar", default=None)

    @property
    def bottom_toolbar_tokens(self):
        """Returns self._bottom_toolbar_tokens if it would yield a result"""
        if builtins.__xonsh__.env.get("BOTTOM_TOOLBAR"):
            return self._bottom_toolbar_tokens

    def continuation_tokens(self, width, line_number, is_soft_wrap=False):
        """Displays dots in multiline prompt"""
        if is_soft_wrap:
            return ""
        width = width - 1
        dots = builtins.__xonsh__.env.get("MULTILINE_PROMPT")
        dots = dots() if callable(dots) else dots
        if not dots:
            return ""
        basetoks = self.format_color(dots)
        baselen = sum(len(t[1]) for t in basetoks)
        if baselen == 0:
            return [(Token, " " * (width + 1))]
        toks = basetoks * (width // baselen)
        n = width % baselen
        count = 0
        for tok in basetoks:
            slen = len(tok[1])
            newcount = slen + count
            if slen == 0:
                continue
            elif newcount <= n:
                toks.append(tok)
            else:
                toks.append((tok[0], tok[1][: n - count]))
            count = newcount
            if n <= count:
                break
        toks.append((Token, " "))  # final space
        return PygmentsTokens(toks)

    def format_color(self, string, hide=False, force_string=False, **kwargs):
        """Formats a color string using Pygments. This, therefore, returns
        a list of (Token, str) tuples. If force_string is set to true, though,
        this will return a color formatted string.
        """
        tokens = partial_color_tokenize(string)
        if force_string and HAS_PYGMENTS:
            env = builtins.__xonsh__.env
            self.styler.style_name = env.get("XONSH_COLOR_STYLE")
            proxy_style = pyghooks.xonsh_style_proxy(self.styler)
            formatter = pyghooks.XonshTerminal256Formatter(style=proxy_style)
            s = pygments.format(tokens, formatter)
            return s
        elif force_string:
            print("To force colorization of string, install Pygments")
            return tokens
        else:
            return tokens

    def print_color(self, string, end="\n", **kwargs):
        """Prints a color string using prompt-toolkit color management."""
        if isinstance(string, str):
            tokens = partial_color_tokenize(string)
        else:
            # assume this is a list of (Token, str) tuples and just print
            tokens = string
        tokens = PygmentsTokens(tokens)
        if HAS_PYGMENTS:
            env = builtins.__xonsh__.env
            self.styler.style_name = env.get("XONSH_COLOR_STYLE")
            proxy_style = style_from_pygments_cls(
                pyghooks.xonsh_style_proxy(self.styler)
            )
        else:
            proxy_style = style_from_pygments_dict(DEFAULT_STYLE_DICT)
        ptk_print(
            tokens, style=proxy_style, end=end, include_default_pygments_style=False
        )

    def color_style_names(self):
        """Returns an iterable of all available style names."""
        if not HAS_PYGMENTS:
            return ["For other xonsh styles, please install pygments"]
        return get_all_styles()

    def color_style(self):
        """Returns the current color map."""
        if not HAS_PYGMENTS:
            return DEFAULT_STYLE_DICT
        env = builtins.__xonsh__.env
        self.styler.style_name = env.get("XONSH_COLOR_STYLE")
        return self.styler.styles

    def restore_tty_sanity(self):
        """An interface for resetting the TTY stdin mode. This is highly
        dependent on the shell backend. Also it is mostly optional since
        it only affects ^Z backgrounding behaviour.
        """
        # PTK does not seem to need any specialization here. However,
        # if it does for some reason in the future...
        # The following writes an ANSI escape sequence that sends the cursor
        # to the end of the line. This has the effect of restoring ECHO mode.
        # See http://unix.stackexchange.com/a/108014/129048 for more details.
        # This line can also be replaced by os.system("stty sane"), as per
        # http://stackoverflow.com/questions/19777129/interactive-python-interpreter-run-in-background#comment29421919_19778355
        # However, it is important to note that not termios-based solution
        # seems to work. My guess is that this is because termios restoration
        # needs to be performed by the subprocess itself. This fix is important
        # when subprocesses don't properly restore the terminal attributes,
        # like Python in interactive mode. Also note that the sequences "\033M"
        # and "\033E" seem to work too, but these are technically VT100 codes.
        # I used the more primitive ANSI sequence to maximize compatibility.
        # -scopatz 2017-01-28
        #   if not ON_POSIX:
        #       return
        #   sys.stdout.write('\033[9999999C\n')
        if not ON_POSIX:
            return
        stty, _ = builtins.__xonsh__.commands_cache.lazyget("stty", (None, None))
        if stty is None:
            return
        os.system(stty + " sane")
