"""Command line: catppuccinize TARGET [options]. Targets are discovered (see core.target)."""
import argparse
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
    common.add_argument("-m", "--map", nargs="+", default=[], metavar="NAME=TARGET",
                        help="override the colour mapping: white=mauve, ui.white=text, '#ffad03=peach'")
    common.add_argument("--preview", action="store_true",
                        help="only render before/after images into <out>/previews/")
    common.add_argument("-o", "--out", type=Path, help="output folder")
    return common


def main(argv=None):
    sys.dont_write_bytecode = True       # no root-owned __pycache__ after a sudo run
    p = argparse.ArgumentParser(prog="catppuccinize",
                                description="Recolour boot themes, wallpapers and more with Catppuccin.")
    p.add_argument("--version", action="version", version=f"catppuccinizer {__version__}")
    sub = p.add_subparsers(dest="target_name", required=True, metavar="TARGET")
    epilog = (f"flavors: {', '.join(FLAVORS)}\naccents: {', '.join(ACCENTS)}\n"
              f"targets: {', '.join(TARGETS)}")
    common = common_parser()
    for name, t in discover().items():
        doc = t.description or sys.modules[type(t).__module__].__doc__
        sp = sub.add_parser(name, parents=[common], help=t.help, description=doc, epilog=epilog,
                            formatter_class=argparse.RawDescriptionHelpFormatter)
        t.add_arguments(sp)
        sp.set_defaults(target=t)

    a = p.parse_args(argv)
    t = a.target
    a.flavor = expand(a.flavor, FLAVORS, "flavor")
    a.accent = expand(a.accent or list(t.default_accent), ACCENTS, "accent")
    a.out = a.out or Path.cwd() / t.default_out
    t.check(a)
    t.run(a)
