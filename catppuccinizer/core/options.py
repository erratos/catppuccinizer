"""Options, declared once: the command line (argparse) and the GUI are built from them.

An Option holds what argparse needs (flags, type, choices, default, nargs…) and
what a front-end needs to show it:

- help: one line; explain: a longer text; image: an illustration (path in the
  repository, e.g. "assets/options-method.jpg");
- scope: "common" (every target, declared here), "method" / "method:<name>"
  (the recolouring methods, declared in core.recolor and core.lutgen) or
  "target" (declared by the target);
- stage: the stage it belongs to (STAGES): "analyse" lists or detects and writes
  no output, "preview" / "build" write into the output folder, "install",
  "apply", "test" and "restore" touch the system. The option that runs a system
  step is made with step() (dest = stage = the step's name);
- sudo: None or "run" (the command must run as root);
- when: when the option matters, {key: allowed values}. A key is another
  option's dest ({"method": ["lutgen"]}) or "analysis.<fact>", a fact from the
  analysis of the sources (see analysis()); a fact not known yet (nothing
  analysed) does not hide the option, and an option taking several values
  matches when one of them is allowed. Options of scope "method:<name>" get
  {"method": [<name>]} by default;
- source: what the target works on (positional arguments by default), shown
  first by the GUI; accept: what a path is ("image", "images" = image files or
  folders, "dir", "file");
- range: (low, high), checked after parsing ("--keep-lum must be between 0 and 1");
- gui: False keeps it out of the GUI forms (--colours lists, it does not run).
"""
import argparse
from pathlib import Path

from .naming import suffix_type

STAGES = ("analyse", "preview", "build", "install", "apply", "test", "restore")
SYSTEM_STAGES = ("install", "apply", "test", "restore")
STEPS = SYSTEM_STAGES                  # Target methods, each with its option (step())
SCOPES = ("common", "method", "target")          # + "method:<name>"
SUDO = (None, "run")
ACCEPT = (None, "image", "images", "dir", "file")
KINDS = ("bool", "optional", "choice", "multichoice", "int", "float", "path", "text",
         "flavor", "accent", "map", "colour")


class Option:
    """One option or positional argument. Flags as for argparse.add_argument:
    Option("-f", "--flavor", ...) or Option("images", nargs="+", ...)."""

    def __init__(self, *flags, **kw):
        self._given = kw                       # for replace()
        self._init(*flags, **kw)

    def _init(self, *flags, help, dest=None, type=None, choices=None, default=None,
              nargs=None, metavar=None, const=None, switch=False, extend=False,
              required=None, kind=None, range=None, accept=None, source=None, group=None,
              explain=None, image=None, scope="target", stage="build", sudo=None,
              when=None, gui=True):
        if not flags:
            raise ValueError("an option needs at least one flag or a name")
        self.flags = tuple(flags)
        self.positional = not flags[0].startswith("-")
        long = next((f for f in flags if f.startswith("--")), flags[-1])
        self.dest = dest or (flags[0] if self.positional else long.lstrip("-").replace("-", "_"))
        self.help, self.explain, self.image = help, explain, image
        self.type, self.choices, self.default = type, choices, default
        self.nargs, self.const, self.switch, self.extend = nargs, const, switch, extend
        self.range = tuple(range) if range else None
        self.metavar = metavar or (f"{self.range[0]}..{self.range[1]}" if self.range else None)
        self.required = required
        self.accept, self.group, self.scope, self.stage, self.sudo = accept, group, scope, stage, sudo
        self.source = self.positional if source is None else source
        self.gui = gui
        if when is None and scope.startswith("method:"):
            when = {"method": [scope.partition(":")[2]]}
        self.when = {k: list(v) if isinstance(v, (list, tuple)) else [v]
                     for k, v in (when or {}).items()} or None
        self.kind = kind or self._kind()

    def __repr__(self):
        return f"Option({', '.join(map(repr, self.flags))})"

    def replace(self, **changes):
        """A copy with some fields changed (lut: --method with only the LUT methods)."""
        return Option(*self.flags, **{**self._given, **changes})

    def _kind(self):
        if self.switch:
            return "bool"
        if self.nargs == "?" and not self.positional and self.const is not None:
            return "optional"                  # --test [SECONDS]: a switch with an optional value
        if self.choices:
            return "multichoice" if self.multiple else "choice"
        if self.type in (int, float):
            return self.type.__name__
        if self.type is Path or self.accept or self.positional:
            return "path"
        return "text"

    @property
    def multiple(self):
        return self.nargs in ("+", "*")

    @property
    def is_required(self):
        if self.positional:
            return self.nargs not in ("?", "*")
        return bool(self.required)

    def shown(self, values, analysis=None):
        """Whether the option matters for these option values {dest: value} (defaults
        included) and analysis facts (see when)."""
        return condition_met(self.when, values, analysis)

    # ------------------------------------------------------------ argparse
    def argparse_kwargs(self):
        kw = {"help": self.help.replace("%", "%%")}
        if self.switch:
            kw["action"] = "store_true"
        else:
            if self.extend:
                kw["action"] = "extend"
            for name in ("type", "choices", "nargs", "metavar", "const", "default"):
                if getattr(self, name) is not None:
                    kw[name] = getattr(self, name)
        if not self.positional:
            kw["dest"] = self.dest
            if self.required is not None:
                kw["required"] = self.required
        return kw

    # ----------------------------------------------------------------- GUI
    def schema(self):
        """What the GUI needs, as JSON."""
        return {
            "dest": self.dest, "flags": [] if self.positional else list(self.flags),
            "kind": self.kind, "positional": self.positional, "nargs": self.nargs,
            "multiple": self.multiple, "required": self.is_required,
            "choices": _plain(list(self.choices)) if self.choices else None,
            "default": _plain(False if self.switch else self.default), "const": _plain(self.const),
            "metavar": self.metavar, "help": self.help, "explain": self.explain,
            "image": self.image, "range": list(self.range) if self.range else None,
            "group": self.group, "when": self.when, "scope": self.scope, "stage": self.stage,
            "sudo": self.sudo, "accept": self.accept,
            "role": ("source" if self.source else "step" if is_step(self)
                     else "common" if self.scope == "common" else "option"),
        }


def _plain(v):
    if isinstance(v, Path):
        return str(v)
    if isinstance(v, (list, tuple)):
        return [_plain(x) for x in v]
    return v if v is None or isinstance(v, (str, int, float, bool)) else str(v)


def condition_met(when, values, analysis=None):
    """`when` ({key: allowed values}) against option values and analysis facts."""
    for key, allowed in (when or {}).items():
        if key.startswith("analysis."):
            value = (analysis or {}).get(key.partition(".")[2])
            if value is None:                  # not analysed yet: shown
                continue
        else:
            value = values.get(key)
        if isinstance(value, (list, tuple)):   # several values (--format hald cube): any
            if not any(v in allowed for v in value):
                return False
        elif value not in allowed:
            return False
    return True


def analysis(report):
    """Facts `when` can use, from a `--colours` report (core.mapping.colour_report
    entries): remappable = some colour can be changed with -m."""
    return {"remappable": any(e["remap"] and e["colours"] for e in report)}


# ----------------------------------------------------------------- parsers
def add_to(parser, options):
    """Add the options to an argparse parser (argument groups by `group`)."""
    groups, seen = {}, set()
    for o in options:
        if o.dest in seen:
            raise ValueError(f"option {o.dest} declared twice")
        seen.add(o.dest)
        where = parser
        if o.group:
            where = groups.get(o.group) or groups.setdefault(o.group, parser.add_argument_group(o.group))
        where.add_argument(*o.flags, **o.argparse_kwargs())
    return parser


def check(args, options):
    """Checks argparse cannot do: ranges."""
    for o in options:
        v = getattr(args, o.dest, None)
        if o.range and v is not None and not o.range[0] <= v <= o.range[1]:
            raise SystemExit(f"{o.flags[-1]} must be between {o.range[0]} and {o.range[1]}")


def defaults(options, **values):
    """A namespace with the defaults of the options (and the given values), as
    parsing an empty command line would give: for scripts using the core directly."""
    a = add_to(argparse.ArgumentParser(add_help=False),
               [o for o in options if not o.positional]).parse_args([])
    for k, v in values.items():
        setattr(a, k, v)
    return a


def step(name, help, sudo=None, **kw):
    """The option that runs a system step of a target (--install, --apply, --test,
    --restore): its dest and stage are the step's name. kw: e.g. --test [SECONDS]."""
    if name not in STEPS:
        raise ValueError(f"unknown step {name}")
    kw = {"switch": True, **kw} if "nargs" not in kw else kw
    return Option(f"--{name}", help=help, stage=name, sudo=sudo, **kw)


def is_step(o):
    return o.dest in STEPS and o.stage == o.dest


# ---------------------------------------------------------- common options
COMMON = [
    Option("-f", "--flavor", nargs="+", default=["mocha"], metavar="FLAVOR", kind="flavor",
           scope="common", image="assets/options-flavors.jpg",
           help="one or more flavors, or 'all' (default: mocha)"),
    Option("-a", "--accent", nargs="+", metavar="ACCENT", kind="accent", scope="common",
           help="accent(s) for colours mapped to 'accent', or 'all'"),
    Option("-m", "--map", nargs="+", extend=True, default=[], metavar="NAME=TARGET", kind="map",
           scope="common", when={"analysis.remappable": [True]},
           help="override the colour mapping: white=mauve, ui.white=text, '#ffad03=peach'"),
    Option("--preview", switch=True, scope="common", stage="preview",
           help="only render before/after images into <out>/previews/"),
    Option("-o", "--out", type=Path, accept="dir", scope="common", help="output folder"),
    Option("-s", "--suffix", default="", type=suffix_type, metavar="SUFFIX", scope="common",
           help="extra word at the end of the output names (lowercase letters, digits and '-')"),
]

# added to the targets that have system steps
DRY_RUN = Option("--dry-run", switch=True, scope="common", stage="install",
                 help="with --install, --apply, --test or --restore: build as usual, then "
                      "only list the files the steps would copy, change or remove and the "
                      "commands they would run (reading the system may still need sudo)")

# added to the targets that define colours() (core.target.Target.colours)
COLOURS = [
    Option("--colours", switch=True, scope="common", stage="analyse", gui=False,
           help="only list the colours -m can remap (name, source colour, current target, "
                "share) and exit; nothing is written"),
    Option("--json", switch=True, scope="common", stage="analyse", gui=False,
           when={"colours": [True]}, help="with --colours: print JSON"),
]
