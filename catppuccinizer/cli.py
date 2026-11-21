"""Command line: catppuccinize TARGET [options]. Targets are discovered (see core.target)."""
import argparse
import contextlib
import json
import os
import sys
from pathlib import Path

from . import __version__
from .core import options
from .core.mapping import format_colour_report
from .core.naming import dedupe, format_planned
from .core.palette import ACCENTS, FLAVORS, TARGETS, expand
from .core.paths import cache_dir, config_dir, give_back
from .core.system import System
from .core.target import discover


def build_parser(targets=None):
    """The parser of `catppuccinize`: one subcommand per target, built from its
    options (core.options), plus `gui`."""
    targets = discover() if targets is None else targets
    p = argparse.ArgumentParser(prog="catppuccinize",
                                description="Recolour boot themes, wallpapers and more with Catppuccin.")
    p.add_argument("--version", action="version", version=f"catppuccinizer {__version__}")
    sub = p.add_subparsers(dest="target_name", required=True, metavar="TARGET")
    epilog = (f"flavors: {', '.join(FLAVORS)}\naccents: {', '.join(ACCENTS)}\n"
              f"targets: {', '.join(TARGETS)}")
    for name, t in targets.items():
        sp = sub.add_parser(name, help=t.help, description=t.doc, epilog=epilog,
                            formatter_class=argparse.RawDescriptionHelpFormatter)
        options.add_to(sp, t.all_options())
        sp.set_defaults(target=t)
    if "gui" not in targets:
        g = sub.add_parser("gui", help="open the graphical interface in your browser",
                           description="Choose a target, its source and options in a web page "
                                       "served on this computer only (127.0.0.1).")
        g.add_argument("--port", type=int, default=0, help="port (default: a free one)")
        g.add_argument("--no-browser", action="store_true", help="only print the address")
        g.set_defaults(target=None)
    return p


def parse(argv=None, parser=None):
    """Parsed and resolved arguments (flavours, accents, output folder), checked by the target."""
    p = parser or build_parser()
    a = p.parse_args(argv)
    t = a.target
    if t is None:                     # gui
        return a
    for o in options.COMMON:          # those the target leaves out (unused_common): their default
        if not hasattr(a, o.dest):
            setattr(a, o.dest, False if o.switch else o.default)
    a.accent_given = bool(a.accent)   # -a asked for: say so when it has no effect
    a.flavor = expand(a.flavor, FLAVORS, "flavor")
    a.accent = expand(a.accent or list(t.default_accent), ACCENTS, "accent")
    a.out = a.out or Path.cwd() / t.default_out
    if getattr(a, "json", False) and not (getattr(a, "colours", False) or getattr(a, "names", False)):
        raise SystemExit("--json only goes with --colours or --names")
    if getattr(a, "colours", False) and getattr(a, "names", False):
        raise SystemExit("use either --colours or --names")
    asked = [s for s in t.steps if getattr(a, s)]
    if getattr(a, "dry_run", False) and not asked:
        raise SystemExit("--dry-run goes with " + " / ".join(f"--{s}" for s in t.steps))
    if "restore" in asked and len(asked) > 1:
        raise SystemExit("--restore goes alone (it undoes --install / --apply)")
    options.check(a, t.all_options())
    t.check(a)
    return a


def run(t, a):
    """build, then the system steps asked for, in order: --apply implies --install;
    --restore runs alone, without building."""
    system = System(dry_run=getattr(a, "dry_run", False))
    dry = " (dry run: nothing is changed)" if system.dry_run else ""
    if getattr(a, "restore", False):
        print(f"restore{dry}")
        return t.restore(a, system)
    built = t.build(a)
    # under sudo, what build wrote (output, configs, downloads) belongs to the invoking user
    give_back(a.out, config_dir(t.name), cache_dir())
    if built is None or a.preview:
        return
    asked = [s for s in t.steps if getattr(a, s) or (s == "install" and getattr(a, "apply", False))]
    for s in asked:
        print(f"{s}{dry}")
        getattr(t, s)(a, built, system)


def main(argv=None):
    sys.dont_write_bytecode = True       # no root-owned __pycache__ after a sudo run
    try:
        a = parse(argv)
        if a.target is None:
            from .gui import serve
            return serve(port=a.port, browser=not a.no_browser)
        if getattr(a, "colours", False):
            with contextlib.redirect_stdout(sys.stderr):    # notes, fetching: not the list
                items = a.target.colours(a)
            print(json.dumps(items, indent=2) if a.json else format_colour_report(items))
            return
        if getattr(a, "names", False):
            with contextlib.redirect_stdout(sys.stderr):
                items = dedupe(a.target.outputs(a))
            print(json.dumps(items, indent=2) if a.json else format_planned(items))
            return
        run(a.target, a)
    except KeyboardInterrupt:
        raise SystemExit("\ninterrupted")
    except OSError as e:
        # missing, unreadable or unwritable files are the user's to fix: a message,
        # not a traceback (CATPPUCCINIZER_DEBUG=1 shows it)
        if os.environ.get("CATPPUCCINIZER_DEBUG"):
            raise
        raise SystemExit(f"error: {e.strerror}: {e.filename}" if e.filename and e.strerror
                         else f"error: {e}")
