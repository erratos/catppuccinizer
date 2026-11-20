"""Target interface and discovery.

A target is a subcommand of `catppuccinize`. It subclasses Target and uses only
catppuccinizer.core. Built-in targets live in catppuccinizer/targets/<name>
(module attribute TARGET); other packages can add targets with an entry point:

    [project.entry-points."catppuccinizer.targets"]
    grub = "my_package.grub:TARGET"
"""
import sys
from importlib import import_module
from importlib.metadata import entry_points

from . import options as opts

BUILTIN = ["plymouth", "image", "limine", "ksplash", "lut"]


class Target:
    name = ""                  # subcommand
    help = ""                  # one line for `catppuccinize --help`
    description = None         # long help (defaults to the module docstring)
    default_out = "themes"     # output folder, relative to the current directory
    default_accent = ("all",)  # accents when -a is not given
    accent_also = None         # what uses the accent whatever --method is (limine: "the menu
                               # colours"); None: a LUT method leaves the accent unused

    def options(self):
        """The target's own options, as core.options.Option (scope "target"), plus
        core.recolor.method_options() when it recolours images with the methods.
        The common ones (-f -a -m --preview -o -s, --colours) are added by
        all_options()."""
        return []

    def all_options(self):
        """Every option of the subcommand, in order: common, the target's, --colours."""
        return [*opts.COMMON, *self.options(), *(opts.COLOURS if self.has_colours else [])]

    @property
    def has_colours(self):
        """Whether the target defines colours() (--colours, the GUI's remap list)."""
        return type(self).colours is not Target.colours

    @property
    def doc(self):
        """Long help: description, or the docstring of the target's module."""
        return self.description or sys.modules[type(self).__module__].__doc__

    def check(self, args):
        """Validate options before running (raise SystemExit on error)."""

    def sources(self):
        """Ready-made sources a front-end can offer for the first positional argument
        (the GUI's catalogue): [{"value", "label", "note"}], or None for none."""
        return None

    def colours(self, args):
        """`--colours`: the source colours -m can remap, analysed but nothing
        written, as a list of core.mapping.colour_report() entries. Targets
        without source colours (lut) leave it out: the option is not offered."""
        raise NotImplementedError

    def run(self, args):
        raise NotImplementedError


def discover():
    """{name: Target instance}, built-in first, then entry points."""
    targets = {}
    for name in BUILTIN:
        t = import_module(f"catppuccinizer.targets.{name}").TARGET
        targets[t.name] = t
    for ep in entry_points(group="catppuccinizer.targets"):
        if ep.name in targets:
            continue
        t = ep.load()
        targets[ep.name] = t() if isinstance(t, type) else t
    return targets
