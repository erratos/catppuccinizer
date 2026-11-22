"""System settings: how the result is shown, set in the system's own configuration
files (a boot menu's timeout and resolution, Plymouth's delay…), apart from the
theme: the GUI's "System settings" section, the command line's --configure.

A target declares each setting as an option made with setting() (stage
"configure", left at None when not given) and the step that writes them,
options.step("configure"); it implements configure(args, system), which writes
the settings given, and settings_now(), their current values ({dest: text or
None when not set}, read from the system, writing nothing). --configure runs
alone, without building; without any setting it prints the current values and
the target's tips (Target.tips).

The value DEFAULT ("default") undoes a setting: what the file had before comes
back. Where catppuccinizer writes its own block (limine.conf) or its own file
(a systemd drop-in), removing it is enough; where it changes a line of the
system's file (/etc/default/grub, plymouthd.conf, ksplashrc), the value it
replaced is remembered first (remember()), in the target's settings state file
(settings_state()).
"""
import argparse
import re

from .options import Option
from .paths import state_file

DEFAULT = "default"
CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def setting(flag, help, check=None, choices=None, label=None, metavar=None, explain=None,
            sudo=None):
    """The option of a setting: a value checked by check (a function of the text:
    the value to write, or ValueError) or one of choices, or DEFAULT."""
    if (check is None) == (choices is None):
        raise ValueError(f"{flag}: a setting is checked by a function or by its choices")
    if choices is not None:
        return Option(flag, help=help, label=label, choices=[*choices, DEFAULT], default=None,
                      metavar=metavar, explain=explain, stage="configure", sudo=sudo, kind="choice")

    def kind(text):
        text = str(text).strip()
        try:
            return DEFAULT if text == DEFAULT else check(text)
        except ValueError as e:              # argparse prints the message itself
            raise argparse.ArgumentTypeError(f"{text!r}: expected {e}, or {DEFAULT}") from None
    return Option(flag, help=help, label=label, type=kind, default=None, metavar=metavar,
                  explain=explain, stage="configure", sudo=sudo, kind="text")


def setting_options(options):
    """The settings among options (not the --configure step itself)."""
    return [o for o in options if o.stage == "configure" and o.dest != "configure"]


def given(args, options):
    """{dest: value} of the settings given on the command line."""
    return {o.dest: getattr(args, o.dest) for o in setting_options(options)
            if getattr(args, o.dest, None) is not None}


# -------------------------------------------------------------- value checks
def integer(low, high, words=()):
    """A check: a whole number from low to high, or one of words ("no")."""
    def number(text):
        if text in words:
            return text
        if not re.fullmatch(r"-?\d{1,6}", text) or not low <= int(text) <= high:
            also = "".join(f" or {w}" for w in words)
            raise ValueError(f"a whole number from {low} to {high}{also}")
        return str(int(text))
    return number


def decimal(low, high):
    """A check: a number from low to high (0.5)."""
    def seconds(text):
        if not re.fullmatch(r"\d{1,4}(\.\d{1,3})?", text) or not low <= float(text) <= high:
            raise ValueError(f"a number from {low} to {high}")
        return text
    return seconds


def pattern(regex, what):
    """A check: text matching regex (whole), described as what in the error."""
    def matching(text):
        if not re.fullmatch(regex, text):
            raise ValueError(what)
        return text
    return matching


def plain_text(limit=80, forbid=""):
    """A check: one line of at most limit characters, none of forbid."""
    def text(value):
        if not value or len(value) > limit or CONTROL.search(value) or any(c in value for c in forbid):
            extra = f", without {' '.join(forbid)}" if forbid else ""
            raise ValueError(f"one line of 1 to {limit} characters{extra}")
        return value
    return text


# ------------------------------------------------------------ previous values
def settings_state(target, system=True):
    """The state file of a target's settings (apart from its theme's: restore removes
    that one)."""
    return state_file(f"{target}-settings", system=system)


def remember(system, state, changes, current):
    """What to write for changes ({id: value or DEFAULT}) given the current values
    ({id: value or None}), the replaced values kept in the state file: {id: value,
    or None to remove the line}. A first change of id remembers its current value;
    DEFAULT writes the remembered one back (and forgets it), or nothing when
    nothing was remembered (it is as it was)."""
    data = system.load_state(state)
    before = data.get("previous", {})
    writes = {}
    for key, value in changes.items():
        if value == DEFAULT:
            if key in before:
                writes[key] = before.pop(key)
            else:
                print(f"  {key}: as it was, nothing to undo")
            continue
        if key not in before:
            before[key] = current.get(key)
        if value != current.get(key):
            writes[key] = value
    system.save_state(state, {**data, "previous": before} if before else
                      {k: v for k, v in data.items() if k != "previous"})
    return writes


# ------------------------------------------------------------------- report
def format_settings(options, now, tips=()):
    """The text of --configure without a setting: each setting and its current value,
    then the tips."""
    lines = ["Current settings (change one with --configure --NAME VALUE, undo it with "
             f"--NAME {DEFAULT})"]
    for o in setting_options(options):
        value = now.get(o.dest)
        lines.append(f"  {o.flags[-1]:<22} {value if value is not None else '(not set)'}")
        lines.append(f"      {o.help}")
    if tips:
        lines += ["", "Tips"] + [f"  - {t}" for t in tips]
    return "\n".join(lines)
