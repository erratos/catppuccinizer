"""Declarative targets: a TOML file describes a target that recolours a theme folder
(core.folder) and installs it by copying it and setting variables of configuration
files; load() turns it into a Target. The format, what it can say and the trust
rules: docs/architecture.md, "Declarative targets (TOML)".

Built-in files (catppuccinizer/targets/*.toml) may use sudo and system files; the
user's (core.paths.config_dir()/targets/*.toml) run with the user's rights only.
"""
import os
import re
import shutil
import stat
import tomllib
from pathlib import Path

from . import folder, naming, recolor
from .formats import SYNTAXES
from .mapping import note_accent_ignored
from .online import Ocs
from .options import PREVIEW_ANIMATION, Option, previewing, step
from .palette import FLAVOR_TITLES
from .parts import check_parts, note_unused, single
from .paths import state_file, user_home
from .settings import given, integer, pattern, plain_text, remember, setting, settings_state
from .sources import item, link, section, theme_folders, tidy
from .system import (UNSAFE_VALUE, VARIABLE, config_text, copy_folder, get_variable, place,
                     set_variable, unquote)
from .target import Target

# the programs apply may run: bootloader and cache refreshers (adding one is a change
# to catppuccinizer, reviewed like code)
COMMANDS = ("grub-mkconfig", "grub2-mkconfig", "update-grub", "fc-cache",
            "gtk-update-icon-cache", "kbuildsycoca6")
NAME = re.compile(r"[a-z][a-z0-9-]*")
FIELDS = ("name", "installed")               # what {…} may name in apply's values and commands

STR, BOOL, INT, STRS, TABLE, TABLES, COMMAND_LIST = "a string", "true or false", "a number", \
    "a list of strings", "a table", "a list of tables", "a list of commands (lists of strings)"
SCHEMA = {                 # key: (type, required)
    "": {"name": (STR, True), "help": (STR, True), "description": (STR, False),
         "default_out": (STR, False), "ignore": (STRS, False), "source": (TABLE, True),
         "parts": (TABLES, True), "install": (TABLE, False), "apply": (TABLE, False),
         "restore": (TABLE, False), "configure": (TABLE, False)},
    "source": {"marker": (STR, True), "search": (STRS, False), "default": (STR, False),
               "label": (STR, False), "help": (STR, False), "links": (TABLES, False),
               "online": (TABLES, False)},
    "links": {"name": (STR, True), "url": (STR, True), "note": (STR, False)},
    "online": {"store": (STR, True), "category": (INT, True), "title": (STR, False),
               "note": (STR, False)},
    "parts": {"name": (STR, True), "kind": (STR, True), "files": (STRS, False),
              "syntax": (STR, False), "label": (STR, False)},
    "install": {"to": (STR, True), "sudo": (BOOL, False), "help": (STR, False)},
    "apply": {"help": (STR, False), "explain": (STR, False), "set": (TABLES, False),
              "run": (COMMAND_LIST, False)},
    "set": {"file": (STR, True), "key": (STR, True), "value": (STR, True)},
    "restore": {"help": (STR, False)},
    "configure": {"settings": (TABLES, True), "help": (STR, False), "explain": (STR, False),
                  "sudo": (BOOL, False), "run": (COMMAND_LIST, False), "tips": (STRS, False)},
    "settings": {"name": (STR, True), "file": (STR, True), "key": (STR, True), "help": (STR, True),
                 "label": (STR, False), "choices": (STRS, False), "min": (INT, False),
                 "max": (INT, False), "pattern": (STR, False), "what": (STR, False)},
}


def _is(value, kind):
    if kind == STR:
        return isinstance(value, str)
    if kind == BOOL:
        return isinstance(value, bool)
    if kind == INT:
        return isinstance(value, int) and not isinstance(value, bool)
    if kind == STRS:
        return isinstance(value, list) and all(isinstance(v, str) for v in value)
    if kind == TABLE:
        return isinstance(value, dict)
    if kind == TABLES:
        return isinstance(value, list) and all(isinstance(v, dict) for v in value)
    return (isinstance(value, list) and all(isinstance(c, list) and c and all(isinstance(v, str) for v in c)
                                            for c in value))


def check_table(table, schema, where):
    """Fail on an unknown or missing key, or a value of the wrong type."""
    for key in table:
        if key not in SCHEMA[schema]:
            raise SystemExit(f"{where}: unknown key '{key}' (allowed: {', '.join(SCHEMA[schema])})")
    for key, (kind, required) in SCHEMA[schema].items():
        if key not in table:
            if required:
                raise SystemExit(f"{where}: '{key}' is missing")
        elif not _is(table[key], kind):
            raise SystemExit(f"{where}: '{key}' must be {kind}")


def fields_of(text, where):
    """Check that {…} in text only name FIELDS."""
    for name in re.findall(r"\{([^}]*)\}", text):
        if name not in FIELDS:
            raise SystemExit(f"{where}: unknown {{{name}}} (use {', '.join('{' + f + '}' for f in FIELDS)})")
    if re.sub(r"\{[^}]*\}", "", text).count("{") or re.sub(r"\{[^}]*\}", "", text).count("}"):
        raise SystemExit(f"{where}: unbalanced braces in {text!r}")
    return text


def fill(text, name, installed):
    return text.replace("{name}", name).replace("{installed}", str(installed))


def system_path(text, builtin, where):
    """An absolute path of the file (~ is the user's home); a user's file may only
    name paths in their home."""
    p = Path(user_home() / text[2:] if text.startswith("~/") else text)
    if not p.is_absolute():
        raise SystemExit(f"{where}: {text} is not an absolute path")
    if ".." in p.parts:
        raise SystemExit(f"{where}: {text}: no '..' in paths")
    # resolved: a link in the home that leads out of it (~/x -> /etc) does not count as home
    if not builtin and not p.resolve().is_relative_to(user_home().resolve()):
        raise SystemExit(f"{where}: {text} is not in your home ({user_home()}): a TOML target "
                         "of yours runs with your rights only")
    return p


def check_trust(path):
    """A user's TOML file must be theirs (or root's) and writable by its owner only,
    like the folder it is in."""
    uids = {0, os.getuid(), *([int(os.environ["SUDO_UID"])] if "SUDO_UID" in os.environ else [])}
    for p in (path, path.parent):
        st = os.stat(p)
        if st.st_uid not in uids:
            raise SystemExit(f"{p} belongs to another user")
        if st.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
            raise SystemExit(f"{p} can be changed by other users (chmod go-w)")


def load(path, builtin=False):
    """The Target a TOML file describes (SystemExit with the reason when it is not valid)."""
    path = Path(path)
    if not builtin:
        check_trust(path)
    try:
        with open(path, "rb") as f:
            spec = tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise SystemExit(f"{path}: {e}")
    check_table(spec, "", path)
    return TomlTarget(spec, path, builtin)


class TomlTarget(Target):
    def __init__(self, spec, path, builtin):
        where = str(path)
        self.path, self.builtin = path, builtin
        if not builtin:
            # under sudo its commands and files would be root's: a file dropped in the
            # user's folder must not become a root action
            self.root_refused = (f"{path} is a TOML target of yours: it runs with your rights "
                                 "only, not as root (run it without sudo)")
        if not NAME.fullmatch(spec["name"]):
            raise SystemExit(f"{where}: name must be lowercase letters, digits and '-'")
        self.name, self.help = spec["name"], spec["help"]
        self.description = spec.get("description")
        self.default_out = spec.get("default_out", "themes")
        self.ignore = tuple(spec.get("ignore", ()))

        src = spec["source"]
        check_table(src, "source", f"{where} [source]")
        self.marker, self.default = src["marker"], src.get("default")
        self.search = [system_path(d, True, f"{where} [source]") for d in src.get("search", [])]
        self.source_label = src.get("label", "Theme")
        self.source_help = src.get("help", "theme name (see --list) or theme folder")
        self.links = []
        for k, ln in enumerate(src.get("links", [])):
            w = f"{where} [[source.links]] #{k + 1}"
            check_table(ln, "links", w)
            try:
                self.links.append(link(ln["name"], ln["url"], ln.get("note", "")))
            except ValueError as e:
                raise SystemExit(f"{w}: {e}") from None
        self.online = []
        for k, on in enumerate(src.get("online", [])):
            w = f"{where} [[source.online]] #{k + 1}"
            check_table(on, "online", w)
            try:
                o = Ocs(on["store"], on["category"], on.get("title"), on.get("note", ""),
                        marker=self.marker)
            except ValueError as e:
                raise SystemExit(f"{w}: {e}") from None
            if o.name in (x.name for x in self.online):
                raise SystemExit(f"{w}: {on['store']} category {on['category']} is already given")
            self.online.append(o)

        self.parts = []
        for k, p in enumerate(spec["parts"]):
            w = f"{where} [[parts]] #{k + 1}"
            check_table(p, "parts", w)
            if not naming.SAFE.fullmatch(p["name"]) or p["name"] in (q.name for q in self.parts):
                raise SystemExit(f"{w}: name must be unique, lowercase letters, digits and '-'")
            if p["kind"] not in folder.KINDS:
                raise SystemExit(f"{w}: kind must be one of {', '.join(folder.KINDS)}")
            if "syntax" in p and (p["kind"] != "text" or p["syntax"] not in SYNTAXES):
                raise SystemExit(f"{w}: syntax goes with a text part: one of {', '.join(SYNTAXES)}")
            self.parts.append(folder.Part(p["name"], p["kind"], tuple(p.get("files", ["*"])),
                                          p.get("label"), p.get("syntax")))

        self.install_to = self.sudo = None
        self.step_help, self.sets, self.commands = {}, [], []
        if "install" in spec:
            ins = spec["install"]
            check_table(ins, "install", f"{where} [install]")
            self.sudo = ins.get("sudo", False)
            if self.sudo and not builtin:
                raise SystemExit(f"{where} [install]: sudo = true is only for the TOML targets "
                                 "of catppuccinizer (a TOML target of yours runs with your rights)")
            self.install_to = system_path(ins["to"], builtin, f"{where} [install]")
            self.step_help["install"] = ins.get("help", f"copy the result to {self.install_to}")
        if "apply" in spec:
            app = spec["apply"]
            w = f"{where} [apply]"
            check_table(app, "apply", w)
            if self.install_to is None:
                raise SystemExit(f"{w}: apply selects the installed result: it needs [install]")
            for k, st in enumerate(app.get("set", [])):
                check_table(st, "set", f"{w} set #{k + 1}")
                self.sets.append((system_path(st["file"], builtin, f"{w} set #{k + 1}"), st["key"],
                                  fields_of(st["value"], f"{w} set #{k + 1}")))
            for cmd in app.get("run", []):
                if cmd[0] not in COMMANDS:
                    raise SystemExit(f"{w}: {cmd[0]} is not a command apply may run "
                                     f"({', '.join(COMMANDS)})")
                self.commands.append([fields_of(c, w) for c in cmd])
            self.step_help["apply"] = app.get("help", "install, then select it")
            self.apply_explain = app.get("explain")
        if "restore" in spec:
            check_table(spec["restore"], "restore", f"{where} [restore]")
            if self.install_to is None:
                raise SystemExit(f"{where} [restore]: restore undoes install: it needs [install]")
        if self.install_to is not None:
            self.step_help["restore"] = spec.get("restore", {}).get(
                "help", "select the previous one again and remove the installed ones"
                if self.sets else "remove the installed ones")
        self.settings, self.configure_sudo, self.configure_run = [], False, []
        if "configure" in spec:
            self.load_settings(spec["configure"], f"{where} [configure]", builtin)
        names = [p.name for p in self.parts]
        texts = [p.label or p.name for p in self.parts if p.kind == "text"]
        self.accent_also = f"the colours of {', '.join(texts)}" if texts else None
        self.part_names = names

    def load_settings(self, conf, where, builtin):
        """[configure]: settings of KEY="value" files ([[configure.settings]]), the
        commands to run after a change, the tips."""
        check_table(conf, "configure", where)
        self.configure_sudo = conf.get("sudo", False)
        if self.configure_sudo and not builtin:
            raise SystemExit(f"{where}: sudo = true is only for the TOML targets of catppuccinizer")
        for cmd in conf.get("run", []):
            if cmd[0] not in COMMANDS or any("{" in c for c in cmd):
                raise SystemExit(f"{where}: {cmd[0]} is not a command configure may run "
                                 f"({', '.join(COMMANDS)}, without {{…}})")
            self.configure_run.append(cmd)
        self.tips = list(conf.get("tips", []))
        for k, st in enumerate(conf["settings"]):
            w = f"{where} [[configure.settings]] #{k + 1}"
            check_table(st, "settings", w)
            if not NAME.fullmatch(st["name"]) or st["name"] in (o.flags[-1][2:] for o, *_ in self.settings):
                raise SystemExit(f"{w}: name must be unique, lowercase letters, digits and '-'")
            kinds = [k for k in ("choices", "min", "pattern") if k in st]
            if len(kinds) > 1 or ("min" in st) != ("max" in st) or ("what" in st and "pattern" not in st):
                raise SystemExit(f"{w}: a setting is checked by choices, by min and max, or by a "
                                 "pattern (with what, its description), or is plain text")
            try:
                if "pattern" in st:
                    re.compile(st["pattern"])
                check = (None if "choices" in st else integer(st["min"], st["max"]) if "min" in st
                         else pattern(st["pattern"], st.get("what", f"text matching {st['pattern']}"))
                         if "pattern" in st else plain_text(200, forbid='"$`\\'))
                o = setting(f"--{st['name']}", help=st["help"], label=st.get("label"), check=check,
                            choices=st.get("choices"), metavar=None if "choices" in st else "VALUE",
                            sudo="run" if self.configure_sudo else None)
            except (re.error, ValueError) as e:
                raise SystemExit(f"{w}: {e}") from None
            if not VARIABLE.fullmatch(st["key"]):
                raise SystemExit(f"{w}: key must be a variable name (letters, digits, _)")
            self.settings.append((o, system_path(st["file"], builtin, w), st["key"]))
        self.step_help["configure"] = conf.get("help", "write the settings given")
        self.configure_explain = conf.get("explain")

    # ------------------------------------------------------------ declared
    @property
    def doc(self):
        return self.description or self.help

    @property
    def steps(self):
        return [s for s in ("install", "apply", "restore", "configure") if s in self.step_help]

    @property
    def has_locations(self):
        return bool(self.search)

    def state(self):
        return state_file(self.name, system=bool(self.sudo))

    def options(self):
        kinds = {p.kind for p in self.parts}
        explain = {"apply": getattr(self, "apply_explain", None),
                   "configure": getattr(self, "configure_explain", None)}
        def sudo(s):
            return self.configure_sudo if s == "configure" else self.sudo
        steps = [step(s, sudo="run" if sudo(s) else None,
                      help=self.step_help[s] + (" (sudo)" if sudo(s) else ""),
                      **({"explain": explain[s]} if explain.get(s) else {}))
                 for s in self.steps]
        settings = [o for o, _, _ in self.settings]
        configure = [o for o in steps if o.dest == "configure"]          # after its settings
        steps = [o for o in steps if o.dest != "configure"]
        # optional on the command line: --list and --restore go without it
        return [Option("theme", label=self.source_label, nargs="?", default=self.default,
                       metavar="THEME", accept="dir", help=self.source_help),
                *(recolor.method_options(keys_always="animation" in kinds)
                  if kinds & {"image", "animation"} else []),
                *([PREVIEW_ANIMATION] if "animation" in kinds else []),
                *steps, *settings, *configure]

    # ------------------------------------------------------------ settings
    def settings_now(self, a=None):
        return {o.dest: (unquote(v) if (v := get_variable(config_text(f), key)) is not None else None)
                for o, f, key in self.settings}

    def configure(self, a, system):
        values = given(a, [o for o, _, _ in self.settings])
        changed = False
        for f in dict.fromkeys(f for _, f, _ in self.settings):
            mine = [(o, key) for o, g, key in self.settings if g == f and o.dest in values]
            if not mine:
                continue
            text = config_text(f)
            ids = {f"{f}|{key}": values[o.dest] for o, key in mine}
            for (o, key), v in zip(mine, ids.values()):
                if v != "default" and UNSAFE_VALUE.search(v):
                    raise SystemExit(f"{o.flags[-1]}: the value {v!r} cannot be written safely "
                                     "(no \", $, `, \\ or line break)")
            current = {f"{f}|{key}": get_variable(text, key) for _, key in mine}
            writes = remember(system, settings_state(self.name, system=bool(self.configure_sudo)),
                              {i: v if v == "default" else f'"{v}"' for i, v in ids.items()}, current)
            new = text
            for i, raw in writes.items():
                new = set_variable(new, i.rpartition("|")[2], raw, raw=True)
            if new != text:
                system.write_text(f, new, backup=True)
                changed = True
        if not changed:
            print("  nothing to change")
            return
        for cmd in self.configure_run:
            if system.run(cmd):
                raise SystemExit(f"{cmd[0]} failed")

    def check(self, a):
        check_parts(a, self.part_names)
        if (getattr(a, "install", False) or getattr(a, "apply", False)) and (
                len(a.flavor) > 1 or not single(a, self.part_names)):
            raise SystemExit("--install / --apply need a single flavour and a single accent "
                             "(-f FLAVOR -a ACCENT)")

    # ------------------------------------------------------------- sources
    def resolve(self, arg):
        """The theme folder of a folder, of its marker file, or of a name in search."""
        if arg is None:
            raise SystemExit(f"Give a {self.source_label.lower()} (see --list, or give a folder)")
        p = Path(arg).expanduser()
        if p.is_file() and p.match(self.marker):
            p = p.parent
        if p.is_dir() and any(p.glob(self.marker)):
            return p.resolve()
        if "/" not in arg:
            for base in self.search:
                d = base / arg
                if d.is_dir() and any(d.glob(self.marker)):
                    return d
        if p.is_dir():
            raise SystemExit(f"{arg} is not a {self.source_label.lower()}: no {self.marker} in it")
        raise SystemExit(f"No {self.source_label.lower()} '{arg}' (see --list, or give a folder)")

    def locations(self):
        """A section per search folder; those only root can read, in one section that
        says so."""
        found, hidden = [], []
        for base in self.search:
            try:                             # not is_dir(): it says False for "cannot know"
                if not stat.S_ISDIR(base.stat().st_mode):
                    continue
                if not os.access(base, os.R_OK | os.X_OK):
                    raise PermissionError
            except (FileNotFoundError, NotADirectoryError):
                continue
            except PermissionError:          # base, or a folder above it (/boot), is root's
                hidden.append(base)
                continue
            found.append(section(f"Installed ({tidy(base)})", lambda base=base: (
                item(d, d.name, thumb=d) for d in theme_folders(base, self.marker))))
        if hidden:
            def unreadable():
                raise SystemExit("only root can read it: run with sudo to see these themes, "
                                 "or give a theme folder")
            found.append(section(f"Installed ({', '.join(map(tidy, hidden))})", unreadable))
        return found

    def analyse(self, a):
        return folder.analyse(self.resolve(a.theme), self.parts, a)

    def colours(self, a):
        return folder.colours(self.analyse(a))

    def outputs(self, a):
        src = self.resolve(a.theme)
        _, sets = folder.results(a, folder.analyse(src, self.parts, a, verbose=False), self.parts)
        out = []
        for flv in a.flavor:
            for _, aname in sets:
                name = naming.output_name(flv, naming.slug(src.name), aname, a.suffix)
                if previewing(a):
                    ext = ".webp" if getattr(a, "preview_animation", False) else ".png"
                    out.append(naming.planned(a.out / "previews" / f"{name}{ext}"))
                else:
                    out.append(naming.planned(a.out / name, folder=True))
        return out

    # --------------------------------------------------------------- steps
    def build(self, a):
        src = self.resolve(a.theme)
        slug = naming.slug(src.name)
        print(f"{src.name} ({src})")
        fold = folder.analyse(src, self.parts, a)
        using, sets = folder.results(a, fold, self.parts)
        if not using:
            note_accent_ignored(a)
        note_unused(a, using)
        if previewing(a):
            flv, (accents, aname) = a.flavor[0], sets[0]
            moving = getattr(a, "preview_animation", False)
            dst = a.out / "previews" / f"{naming.output_name(flv, slug, aname, a.suffix)}.{'webp' if moving else 'png'}"
            if moving:
                folder.preview_moving(fold, flv, accents, dst)
            else:
                folder.preview_still(fold, flv, accents, a, dst)
            print(f"  preview: {dst}  (Catppuccin {FLAVOR_TITLES[flv]}{' ' + aname if aname else ''})")
            return None
        built, done = [], {}
        for flv in a.flavor:
            for accents, aname in sets:
                dst = a.out / naming.output_name(flv, slug, aname, a.suffix)
                if dst.exists():
                    shutil.rmtree(dst)
                copy_folder(src, dst, ignore=self.ignore)
                folder.write(fold, flv, accents, a, lambda f, dst=dst: dst / f.relative_to(src), done)
                built.append(dst)
                print(f"  -> {dst}  (Catppuccin {FLAVOR_TITLES[flv]}{' ' + aname if aname else ''})")
        return built or None

    def install(self, a, built, system):
        system.install_tree(built[0], self.install_to, self.state(), "theme name")

    def current(self):
        """{"<file>|<key>": raw value or None} of the variables apply sets."""
        out = {}
        for f, key, _ in self.sets:
            text = config_text(f)
            out[f"{f}|{key}"] = get_variable(text, key)
        return out

    def ours(self, current, names):
        """The installed result the variables point to now, or None."""
        return next((n for n in names if all(
            v is not None and unquote(v) == fill(value, n, place(self.install_to, n))
            for (f, key, value), v in zip(self.sets, current.values()))), None)

    def apply(self, a, built, system):
        name = built[0].name
        installed = place(self.install_to, name, "theme name")
        current = self.current()
        data = system.load_state(self.state())
        # "" is no installed name: current is kept unless it points to one of ours
        system.keep_previous(self.state(), current, self.ours(current, data.get("installed", [])) or "")
        self.write_sets(system, {f"{f}|{key}": (fill(value, name, installed), False)
                                 for f, key, value in self.sets})
        self.run_commands(system, name, installed)

    def restore(self, a, system):
        data, installed = system.restore_state(self.state(), "theme name")
        if self.sets:
            previous = data.get("previous")
            current = self.current()
            if previous is not None:
                self.write_sets(system, {k: (v, True) for k, v in previous.items()})
                self.run_commands(system)
            elif self.ours(current, installed):
                raise SystemExit("The setting in use before is not known: set it back by hand, "
                                 "then rerun --restore")
        system.uninstall(self.state(), self.install_to, installed)

    def write_sets(self, system, values):
        """values: {"<file>|<key>": (value or None, raw)}, one write per file."""
        for f in dict.fromkeys(f for f, _, _ in self.sets):
            text = config_text(f)
            new = text
            for (g, key, _) in self.sets:
                if g == f and f"{f}|{key}" in values:
                    value, raw = values[f"{f}|{key}"]
                    new = set_variable(new, key, value, raw=raw)
            if new != text:
                system.write_text(f, new, backup=True)

    def run_commands(self, system, name=None, installed=None):
        for cmd in self.commands:
            if name is None and any("{" in c for c in cmd):
                continue                      # restore: a command about the result goes with it
            if system.run([fill(c, name or "", installed or "") for c in cmd]):
                raise SystemExit(f"{cmd[0]} failed")


def files(base):
    """The TOML files of a folder, by name."""
    return sorted(Path(base).glob("*.toml")) if Path(base).is_dir() else []
