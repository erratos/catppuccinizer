"""Command line: catppuccinize TARGET [options]. Targets are discovered (see core.target)."""
import argparse
import os
import sys
from pathlib import Path

from . import __version__
from .core.palette import ACCENTS, FLAVORS, TARGETS, expand
from .core.target import discover


def common_parser():
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("-f", "--flavor", nargs="+", default=["mocha"], metavar="FLAVOR",
                        help="one or more flavors, or 'all' (default: mocha)")
    common.add_argument("-a", "--accent", nargs="+", metavar="ACCENT",
                        help="accent(s) for colours mapped to 'accent', or 'all'")
    common.add_argument("-m", "--map", nargs="+", action="extend", default=[], metavar="NAME=TARGET",
                        help="override the colour mapping: white=mauve, ui.white=text, '#ffad03=peach'")
    common.add_argument("--preview", action="store_true",
                        help="only render before/after images into <out>/previews/")
    common.add_argument("-o", "--out", type=Path, help="output folder")
    return common


def build_parser(targets=None):
    """(parser, {target name: its subparser}); the GUI builds its forms from the subparsers."""
    targets = discover() if targets is None else targets
    p = argparse.ArgumentParser(prog="catppuccinize",
                                description="Recolour boot themes, wallpapers and more with Catppuccin.")
    p.add_argument("--version", action="version", version=f"catppuccinizer {__version__}")
    sub = p.add_subparsers(dest="target_name", required=True, metavar="TARGET")
    epilog = (f"flavors: {', '.join(FLAVORS)}\naccents: {', '.join(ACCENTS)}\n"
              f"targets: {', '.join(TARGETS)}")
    common = common_parser()
    subparsers = {}
    for name, t in targets.items():
        doc = t.description or sys.modules[type(t).__module__].__doc__
        sp = sub.add_parser(name, parents=[common], help=t.help, description=doc, epilog=epilog,
                            formatter_class=argparse.RawDescriptionHelpFormatter)
        t.add_arguments(sp)
        sp.set_defaults(target=t)
        subparsers[name] = sp
    if "gui" not in targets:
        g = sub.add_parser("gui", help="open the graphical interface in your browser",
                           description="Choose a target, its source and options in a web page "
                                       "served on this computer only (127.0.0.1).")
        g.add_argument("--port", type=int, default=0, help="port (default: a free one)")
        g.add_argument("--no-browser", action="store_true", help="only print the address")
        g.set_defaults(target=None)
    return p, subparsers


def parse(argv=None, parser=None):
    """Parsed and resolved arguments (flavours, accents, output folder), checked by the target."""
    p = parser or build_parser()[0]
    a = p.parse_args(argv)
    t = a.target
    if t is None:                     # gui
        return a
    a.accent_given = bool(a.accent)   # -a asked for: say so when it has no effect
    a.flavor = expand(a.flavor, FLAVORS, "flavor")
    a.accent = expand(a.accent or list(t.default_accent), ACCENTS, "accent")
    a.out = a.out or Path.cwd() / t.default_out
    t.check(a)
    return a


def main(argv=None):
    sys.dont_write_bytecode = True       # no root-owned __pycache__ after a sudo run
    try:
        a = parse(argv)
        if a.target is None:
            from .gui import serve
            return serve(port=a.port, browser=not a.no_browser)
        a.target.run(a)
    except KeyboardInterrupt:
        raise SystemExit("\ninterrupted")
    except OSError as e:
        # missing, unreadable or unwritable files are the user's to fix: a message,
        # not a traceback (CATPPUCCINIZER_DEBUG=1 shows it)
        if os.environ.get("CATPPUCCINIZER_DEBUG"):
            raise
        raise SystemExit(f"error: {e.strerror}: {e.filename}" if e.filename and e.strerror
                         else f"error: {e}")
