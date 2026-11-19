"""Target interface and discovery.

A target is a subcommand of `catppuccinize`. It subclasses Target and uses only
catppuccinizer.core. Built-in targets live in catppuccinizer/targets/<name>
(module attribute TARGET); other packages can add targets with an entry point:

    [project.entry-points."catppuccinizer.targets"]
    grub = "my_package.grub:TARGET"
"""
from importlib import import_module
from importlib.metadata import entry_points

BUILTIN = ["plymouth", "image", "limine", "ksplash", "lut"]


class Target:
    name = ""                  # subcommand
    help = ""                  # one line for `catppuccinize --help`
    description = None         # long help (defaults to the module docstring)
    default_out = "themes"     # output folder, relative to the current directory
    default_accent = ("all",)  # accents when -a is not given

    def add_arguments(self, parser):
        """Add target-specific options (common ones: -f -a -m --preview -o)."""

    def check(self, args):
        """Validate options before running (raise SystemExit on error)."""

    def sources(self):
        """Ready-made sources a front-end can offer for the first positional argument
        (the GUI's catalogue): [{"value", "label", "note"}], or None for none."""
        return None

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
