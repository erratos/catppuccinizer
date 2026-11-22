"""Target interface and discovery.

A target is a subcommand of `catppuccinize`. It subclasses Target and uses only
catppuccinizer.core. It writes its result with build(); the steps that touch the
system (install, apply, test, restore) are separate, optional methods, each with
its option (core.options.step), run in that order by the command line. Built-in targets live in catppuccinizer/targets/<name>
(module attribute TARGET), or are TOML files there (core.declarative); other packages
can add targets with an entry point:

    [project.entry-points."catppuccinizer.targets"]
    sddm = "my_package.sddm:TARGET"

and the user with TOML files in ~/.config/catppuccinizer/targets/ (core.paths.config_dir).
"""
import sys
from importlib import import_module
from importlib.metadata import entry_points
from pathlib import Path

from . import options as opts
from .paths import config_dir

BUILTIN = ["plymouth", "image", "limine", "ksplash", "lut"]
BUILTIN_DIR = Path(__file__).resolve().parent.parent / "targets"     # + its *.toml files


class Target:
    name = ""                  # subcommand
    help = ""                  # one line for `catppuccinize --help`
    description = None         # long help (defaults to the module docstring)
    default_out = "themes"     # output folder, relative to the current directory
    default_accent = ("all",)  # accents when -a is not given: one result per accent, for
                               # what uses one (the system steps need -a ACCENT)
    accent_also = None         # what uses the accent whatever --method is (limine: "the menu
                               # colours"); None: a LUT method leaves the accent unused
    unused_common = ()         # common options that mean nothing here (lut: "accent", "map",
                               # "preview"): left out of the command line and the GUI
    links = ()                 # other sources: web pages to download sources from, as
                               # core.sources.link() (the GUI's "Other sources", --list)
    online = ()                # other sources the GUI browses itself, core.online
                               # OnlineSource objects (--list prints their page)
    tips = ()                  # system settings: tips (text), shown with the settings
    root_refused = None        # why it may not run as root (a user's TOML target), or None

    def options(self):
        """The target's own options, as core.options.Option (scope "target"), plus
        core.recolor.method_options() when it recolours images with the methods.
        The common ones (-f -a -m --preview -o -s, --list, --colours, --names) are
        added by all_options()."""
        return []

    def all_options(self):
        """Every option of the subcommand, in order: common, the target's, --list,
        --colours, --names, --json, --dry-run (when it has system steps)."""
        listing = [*([opts.COLOURS] if self.has_colours else []),
                   *([opts.NAMES] if self.has_outputs else [])]
        common = [o for o in opts.COMMON if o.dest not in self.unused_common]
        return [*common, *self.options(), *([opts.LIST] if self.has_locations or self.other_sources else []),
                *listing, *([opts.JSON] if listing else []),
                *([opts.DRY_RUN] if self.steps else [])]

    @property
    def steps(self):
        """The system steps the target defines, in order (core.options.STEPS)."""
        return [s for s in opts.STEPS if getattr(type(self), s) is not getattr(Target, s)]

    @property
    def other_sources(self):
        """Every other source as a link: the online sources' pages, then the links."""
        return [*(s.link() for s in self.online), *self.links]

    @property
    def has_locations(self):
        """Whether the target defines locations() (--list, the GUI's system locations)."""
        return type(self).locations is not Target.locations

    @property
    def has_outputs(self):
        """Whether the target defines outputs() (--names, the GUI's output preview)."""
        return type(self).outputs is not Target.outputs

    @property
    def has_settings(self):
        """Whether the target has system settings (core.settings: --configure)."""
        return "configure" in self.steps

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

    def locations(self):
        """System locations: what this computer has for the source argument (installed
        themes, wallpaper folders), for the GUI and --list, as sections of items
        made with core.sources.section() and item()."""
        raise NotImplementedError

    def colours(self, args):
        """`--colours`: the source colours -m can remap, analysed but nothing
        written, as a list of core.mapping.colour_report() entries. Targets
        without source colours (lut) leave it out: the option is not offered."""
        raise NotImplementedError

    def outputs(self, args):
        """`--names`: what build() would write with these options (files and folders,
        including those inside a written folder), as core.naming.planned() entries,
        in the order build() writes them. It analyses what it must (whether the
        accent is used), like colours(), but writes nothing."""
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

    def configure(self, args, system):
        """Write the system settings given (core.settings), without building."""

    def settings_now(self, args=None):
        """The current value of each system setting, {dest: text or None when not
        set}, read from the system (core.settings); writes nothing. args: the
        command line's, when it names where to read (Limine's --esp), else None."""
        raise NotImplementedError


def user_targets_dir():
    """Where the user's TOML targets are."""
    return config_dir() / "targets"


def discover():
    """{name: Target instance}: the built-in targets (Python, then TOML), the entry
    points, then the user's TOML targets. A name already taken, or a user's TOML file
    that is not valid, is skipped with a note (on stderr)."""
    from . import declarative               # it subclasses Target
    targets = {}
    for name in BUILTIN:
        t = import_module(f"catppuccinizer.targets.{name}").TARGET
        targets[t.name] = t
    for f in declarative.files(BUILTIN_DIR):
        t = declarative.load(f, builtin=True)
        targets[t.name] = t
    for ep in entry_points(group="catppuccinizer.targets"):
        if ep.name in targets:
            continue
        t = ep.load()
        targets[ep.name] = t() if isinstance(t, type) else t
    for f in declarative.files(user_targets_dir()):
        try:
            t = declarative.load(f)
        except (SystemExit, OSError) as e:
            print(f"note: {f} skipped: {e}", file=sys.stderr)
            continue
        if t.name in targets:
            print(f"note: {f} skipped: a target named '{t.name}' exists already", file=sys.stderr)
            continue
        targets[t.name] = t
    return targets
