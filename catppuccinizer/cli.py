"""Command line: catppuccinize {plymouth,image,limine} ..."""
import argparse
from pathlib import Path

from . import image, ksplash, limine, plymouth
from .palette import ACCENTS, FLAVORS, TARGETS, expand

TARGETS_HELP = {
    "plymouth": (plymouth, "recolour Plymouth themes (folders or adi1090x names)"),
    "image": (image, "recolour wallpapers and other images"),
    "limine": (limine, "Catppuccin colours + wallpaper for the Limine boot menu"),
    "ksplash": (ksplash, "recolour a KDE Plasma splash screen"),
}


def main(argv=None):
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

    p = argparse.ArgumentParser(prog="catppuccinize",
                                description="Recolour boot themes and wallpapers with Catppuccin.")
    sub = p.add_subparsers(dest="target", required=True, metavar="TARGET")
    epilog = (f"flavors: {', '.join(FLAVORS)}\naccents: {', '.join(ACCENTS)}\n"
              f"targets: {', '.join(TARGETS)}")
    for name, (mod, help_) in TARGETS_HELP.items():
        sp = sub.add_parser(name, parents=[common], help=help_, description=mod.__doc__,
                            epilog=epilog, formatter_class=argparse.RawDescriptionHelpFormatter)
        mod.add_arguments(sp)
        sp.set_defaults(module=mod)

    a = p.parse_args(argv)
    a.flavor = expand(a.flavor, FLAVORS, "flavor")
    a.accent = expand(a.accent or getattr(a, "default_accent", ["all"]), ACCENTS, "accent")
    a.out = a.out or a.out_default
    if hasattr(a.module, "check_args"):
        a.module.check_args(a)
    a.module.run(a)
