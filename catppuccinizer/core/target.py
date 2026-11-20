"""Target interface and discovery.

A target is a subcommand of `catppuccinize`. It subclasses Target and uses only
catppuccinizer.core. It writes its result with build(); the steps that touch the
system (install, apply, test, restore) are separate, optional methods, each with
its option (core.options.step), run in that order by the command line. Built-in targets live in catppuccinizer/targets/<name>
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
        The common ones (-f -a -m --preview -o -s, --list, --colours) are added by
        all_options()."""
        return []

    def all_options(self):
        """Every option of the subcommand, in order: common, the target's, --list,
        --colours, --dry-run (when it has system steps)."""
        return [*opts.COMMON, *self.options(), *([opts.LIST] if self.has_sources else []),
                *(opts.COLOURS if self.has_colours else []),
                *([opts.DRY_RUN] if self.steps else [])]

    @property
    def steps(self):
        """The system steps the target defines, in order (core.options.STEPS)."""
        return [s for s in opts.STEPS if getattr(type(self), s) is not getattr(Target, s)]

    @property
    def has_sources(self):
        """Whether the target defines sources() (--list, the GUI's catalogue)."""
        return type(self).sources is not Target.sources

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
        """Ready-made sources for the source argument (the GUI's catalogue, --list):
        sections of items, made with core.sources.section() and item()."""
        raise NotImplementedError

    def colours(self, args):
        """`--colours`: the source colours -m can remap, analysed but nothing
        written, as a list of core.mapping.colour_report() entries. Targets
        without source colours (lut) leave it out: the option is not offered."""
        raise NotImplementedError

    # ------------------------------------------------------------- steps
    def build(self, args):
        """preview / build: write the result into args.out (only before/after images
        with --preview). Returns what the system steps work on (the built folders…),
        or None when there is nothing for them (--list, --preview…)."""
        raise NotImplementedError

    # The system steps get what build() returned and a core.system.System, through
    # which every change outside the output folder goes (printed, or only listed
    # with --dry-run). Each one needs its option, made with core.options.step().

    def install(self, args, built, system):
        """Copy the result where the system looks for it, without selecting it."""

    def apply(self, args, built, system):
        """Select / configure it (after install)."""

    def test(self, args, built, system):
        """Show it without rebooting or logging out."""

    def restore(self, args, system):
        """Undo apply and install (without building anything)."""


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
