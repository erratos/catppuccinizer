"""Plymouth target: recolour a Plymouth theme: the one in use by default, any
installed theme by name, or any theme folder (script, two-step, fade-throbber,
..., such as the 80 animations of adi1090x/plymouth-themes, which the GUI downloads).

Colours are detected per group of images (each numbered sequence, plus "ui"
for single images) at each run; -m changes them. Themes built on adi1090x's script
template also get a "-status" variant (progress bar + latest systemd services).

--install copies the result (its -status variant if any) to
/usr/share/plymouth/themes, --apply (which installs first) makes it the default
theme and rebuilds the initramfs, --test shows it without rebooting, --restore
makes the previous default theme active again and removes the installed ones.
--preview renders one image per theme (each group before and after),
--preview-animation its main animation as an animated WebP: no sudo, nothing
installed.
"""
import configparser
import re
import shutil
import subprocess
from collections import defaultdict
from pathlib import Path

from PIL import Image

from ...core.detect import DEFAULT_SEPARATION, UI_GROUP, detect_group, detect_params
from ...core.mapping import (apply_maps, background_of, colour_report, note_accent_ignored,
                             print_colours, uses_accent)
from ...core.palette import ACCENTS, FLAVOR_TITLES, PALETTES, color_args, rgb
from ...core.naming import output_name, planned, slug
from ...core.options import PREVIEW_ANIMATION, Option, previewing, step
from ...core.parts import accent_sets, check_parts, note_unused
from ...core.paths import state_file
from ...core.settings import DEFAULT, decimal, given, integer, remember, setting, settings_state
from ...core.sources import item, section, theme_folders
from ...core.recolor import (SEPARATION, SHEET_GAP, SHEET_GAP_COLOUR, draw_legend, keys_plan,
                             preview_animation, recolor_image, run_jobs, separation_image)
from ...core.naming import check_name
from ...core.online import GithubRelease, Ocs
from ...core.system import System, config_text, get_ini, set_ini, source_file, which
from ...core.target import Target

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE / "scripts"

INSTALL_DIR = "/usr/share/plymouth/themes"
DAEMON_CONF = Path("/etc/plymouth/plymouthd.conf")              # [Daemon] Key=Value
DAEMON_DEFAULTS = Path("/usr/share/plymouth/plymouthd.defaults")  # what is not set there
HOLD_DROPIN = Path("/etc/systemd/system/plymouth-quit.service.d/catppuccinizer.conf")


class PlymouthTarget(Target):
    name = "plymouth"
    help = "recolour Plymouth themes (installed ones, or theme folders)"
    tips = [
        "The splash only shows with 'splash' (and usually 'quiet') on the kernel command "
        "line: KERNEL_CMDLINE in /etc/default/limine, GRUB_CMDLINE_LINUX_DEFAULT in "
        "/etc/default/grub (then grub-mkconfig).",
        "Plymouth must be in the initramfs: the plymouth hook in /etc/mkinitcpio.conf "
        "(Arch), or dracut's plymouth module; the delay and scale settings are copied into "
        "it, so --configure rebuilds it.",
        "A splash that never shows on a fast machine: --show-delay 0 shows it at once, "
        "--hold 3 keeps it 3 seconds longer (the boot waits for it).",
        "Blurry or tiny on a HiDPI screen: --scale 2 (or 1).",
    ]
    online = [
        GithubRelease("adi1090x/plymouth-themes", "adi1090x: Plymouth themes", marker="*.plymouth",
                      note="80 animated themes (GPL-3.0), previewed in its README (animated "
                           "GIFs of a few MB each: no thumbnails here)"),
        Ocs("gnome-look", 108, "Gnome-look: Plymouth themes", marker="*.plymouth",
            note="themes with screenshots, each with its own licence"),
    ]

    def options(self):
        return OPTIONS

    def check(self, a):
        check_args(a)

    def build(self, a):
        return build(a)

    def install(self, a, built, system):
        system.install_tree(built, INSTALL_DIR, state_file("plymouth", system=True), "theme name")

    def apply(self, a, built, system):
        # what restore makes active again
        system.keep_previous(state_file("plymouth", system=True), default_theme() or None)
        if system.run(["plymouth-set-default-theme", "-R",                 # -R: initramfs
                       check_name(built.name, "theme name")]):
            raise SystemExit("plymouth-set-default-theme failed")

    def test(self, a, built, system):
        if not a.install and not a.apply:           # the theme must be in INSTALL_DIR
            self.install(a, built, system)
        system.run(["bash", SCRIPTS / "preview.sh", check_name(built.name, "theme name"), a.test])

    def restore(self, a, system):
        path = state_file("plymouth", system=True)
        state, installed = system.restore_state(path, "theme name")
        previous = state.get("previous") and check_name(state["previous"], f"theme name in {path}")
        if default_theme() in installed:
            if not previous:
                raise SystemExit("The theme in use before is not known: choose one with "
                                 "sudo plymouth-set-default-theme -R NAME, then rerun --restore")
            if system.run(["plymouth-set-default-theme", "-R", previous]):
                raise SystemExit("plymouth-set-default-theme failed")
        system.uninstall(path, INSTALL_DIR, installed)

    def colours(self, a):
        return colours(a)

    def outputs(self, a):
        return outputs(a)

    def locations(self):
        return [section(f"Installed themes ({INSTALL_DIR})", installed_themes)]

    def configure(self, a, system):
        configure(a, system)

    def settings_now(self, a=None):
        return settings_now()


OPTIONS = [
    Option("themes", label="Themes", nargs="*", default=[], metavar="THEME", accept="dir",
           empty="the theme in use is recoloured",
           help="installed theme name or theme folder (default: the theme in use)"),
    Option("--no-status", label="No -status variant", switch=True, help="skip the -status variants"),
    SEPARATION.replace(when={}),
    PREVIEW_ANIMATION,
    step("install", sudo="run",
         help=f"copy the result (its -status variant if any) to {INSTALL_DIR} (sudo)"),
    step("apply", sudo="run",
         help="install, then make it the default theme and rebuild the initramfs (sudo)",
         explain="Here: plymouth-set-default-theme -R makes it the default theme and "
                 "rebuilds the initramfs, which takes a little while."),
    step("test", sudo="run", nargs="?", const=10, type=int, metavar="SECONDS",
         help="show the result for SECONDS without rebooting (default: 10; sudo)",
         explain="Here: installs it if needed, shows it for SECONDS with the names of your "
                 "running services as status messages, then puts the default theme back. "
                 "If the screen does not switch, run it from a text console (Ctrl+Alt+F3)."),
    step("restore", sudo="run",
         help="make the previous default theme active again, remove the installed ones (sudo)"),
]
# the display settings (core.settings): [Daemon] of plymouthd.conf, and a systemd drop-in
DAEMON_KEYS = {"show_delay": "ShowDelay", "device_timeout": "DeviceTimeout", "scale": "DeviceScale"}
SETTINGS_OPTIONS = [
    setting("--show-delay", check=decimal(0, 60), metavar="SECONDS",
            help="seconds of boot before the splash shows: a shorter boot shows none "
                 "(ShowDelay; not set: plymouthd.defaults, often 0)"),
    setting("--device-timeout", check=decimal(1, 60), metavar="SECONDS",
            help="seconds to wait for the graphics driver before the text splash "
                 "(DeviceTimeout; not set: plymouthd.defaults, often 8)"),
    setting("--scale", label="HiDPI scale", choices=["1", "2"],
            help="draw the splash at 1x or 2x (DeviceScale; not set: chosen from the screen)"),
    setting("--hold", label="Hold the splash", check=integer(1, 30), metavar="SECONDS",
            help="keep the splash SECONDS longer at the end of the boot, which waits for it "
                 "(a systemd drop-in for plymouth-quit.service; not set: none)"),
]
OPTIONS += [
    *SETTINGS_OPTIONS,
    step("configure", sudo="run", help="write the display settings given (sudo)",
         explain=f"Here: the delay, timeout and scale go into [Daemon] of {DAEMON_CONF} (the "
                 "value replaced is remembered), then the initramfs is rebuilt "
                 "(plymouth-set-default-theme -R), as it holds a copy; --hold writes "
                 f"{HOLD_DROPIN} and reloads systemd."),
]


def settings_now():
    """The settings as plymouthd.conf has them (else plymouthd.defaults, said so), and
    the hold of our drop-in."""
    conf, defaults = config_text(DAEMON_CONF), config_text(DAEMON_DEFAULTS)
    now = {}
    for dest, key in DAEMON_KEYS.items():
        value = get_ini(conf, "Daemon", key)
        fallback = get_ini(defaults, "Daemon", key)
        now[dest] = value if value is not None else f"{fallback} (plymouthd.defaults)" if fallback else None
    m = re.search(r"^ExecStartPre=\S*sleep (\d+)", config_text(HOLD_DROPIN), re.M)
    now["hold"] = m.group(1) if m else None
    return now


def configure(a, system):
    values = given(a, SETTINGS_OPTIONS)
    changes = {DAEMON_KEYS[d]: v for d, v in values.items() if d in DAEMON_KEYS}
    if changes:
        text = config_text(DAEMON_CONF)
        current = {k: get_ini(text, "Daemon", k) for k in changes}
        new = text
        for key, value in remember(system, settings_state("plymouth"), changes, current).items():
            new = set_ini(new, "Daemon", key, value)
        if new != text:
            system.write_text(DAEMON_CONF, new, backup=True)
            theme = default_theme()
            if not theme:
                raise SystemExit("The default theme is not known: rebuild the initramfs with "
                                 "sudo plymouth-set-default-theme -R THEME")
            if system.run(["plymouth-set-default-theme", "-R", check_name(theme, "theme name")]):
                raise SystemExit("plymouth-set-default-theme failed")
        else:
            print(f"  {DAEMON_CONF}: nothing to change")
    if "hold" in values:
        if values["hold"] == DEFAULT:
            if not HOLD_DROPIN.exists():
                print("  hold: as it was, nothing to undo")
                return
            system.remove(HOLD_DROPIN)
            if HOLD_DROPIN.parent.is_dir() and not any(HOLD_DROPIN.parent.iterdir()):
                system.remove(HOLD_DROPIN.parent)
        else:
            sleep = which("sleep") or "/usr/bin/sleep"
            system.write_text(HOLD_DROPIN, "# written by catppuccinizer (plymouth --configure --hold): "
                                           "the splash stays longer\n"
                                           f"[Service]\nExecStartPre={sleep} {values['hold']}\n")
        system.run(["systemctl", "daemon-reload"])


def check_args(a):
    if not a.restore:       # no theme given: the one in use must be known (and not ours)
        themes_of(a)
    if a.preview_animation:
        for arg in themes_of(a):
            if not main_animation(Theme(find_theme(arg))):
                raise SystemExit(f"--preview-animation: {arg} has no animation (no numbered "
                                 "images), --preview shows it")
    if (a.install or a.apply or a.test) and (len(themes_of(a)) > 1 or len(a.flavor) > 1
                                             or len(a.accent) > 1):
        raise SystemExit("--install / --apply / --test need a single theme, flavour and accent "
                         "(THEME -f FLAVOR -a ACCENT)")


# --------------------------------------------------------------- theme model
class Theme:
    """A source theme: its .plymouth, module, script and image groups."""

    def __init__(self, folder):
        self.dir = folder
        # only the theme's own files: a link out of the folder is not followed
        files = sorted(f for f in folder.glob("*.plymouth") if source_file(f, folder))
        own = folder / f"{folder.name}.plymouth"
        if own in files:
            files = [own]
        if not files:
            raise SystemExit(f"No .plymouth file in {folder}")
        self.conf_file = files[0]
        self.conf_text = self.conf_file.read_text()
        cp = configparser.ConfigParser(interpolation=None, strict=False)
        cp.optionxform = str
        cp.read_string(self.conf_text)
        self.cp = cp
        main = cp["Plymouth Theme"] if cp.has_section("Plymouth Theme") else {}
        self.module = main.get("ModuleName", "script")
        self.title = main.get("Name", folder.name)
        if " " not in self.title and "_" in self.title:      # hexa_retro -> Hexa Retro
            self.title = self.title.replace("_", " ").title()
        self.name = folder.name
        self.slug = slug(folder.name)

        self.script = None
        if self.module == "script":
            sf = cp.get("script", "ScriptFile", fallback=f"{folder.name}.script")
            cand = folder / Path(sf).name
            self.script = cand if source_file(cand, folder) else next(
                (f for f in folder.glob("*.script") if source_file(f, folder)), None)

        # images: theme folder, or the ImageDir of the module if it lives elsewhere
        self.image_dir = folder
        if not list(folder.glob("*.png")):
            idir = cp.get(self.module, "ImageDir", fallback="")
            if idir and Path(idir).is_dir():
                self.image_dir = Path(idir)
        self.groups = group_images(sorted(p for p in self.image_dir.glob("*.png")
                                          if source_file(p, self.image_dir)))

    @property
    def adi_template(self):
        """True for scripts built on adi1090x's template (needed for -status)."""
        if not self.script:
            return False
        s = self.script.read_text()
        return "flyingman_image" in s and "refresh_callback" in s


def group_images(paths):
    """Numbered sequences (animation-1.png ...) get their own group; single
    images are gathered into the 'ui' group."""
    seq = defaultdict(list)
    for p in paths:
        m = re.fullmatch(r"(.*?)[-_]?(\d+)", p.stem)
        seq[m.group(1) if m and m.group(1) else p.stem].append(p)
    groups, ui = {}, []
    for prefix, items in seq.items():
        if len(items) > 1:
            groups[prefix] = sorted(items, key=lambda p: int(re.search(r"(\d+)$", p.stem).group(1)))
        else:
            ui += items
    if ui:
        groups[UI_GROUP] = ui
    # biggest animation first
    return dict(sorted(groups.items(), key=lambda kv: (kv[0] == UI_GROUP, -len(kv[1]))))


def detect(theme, separation=DEFAULT_SEPARATION):
    params = detect_params(separation)
    groups = {g: detect_group(paths, g == UI_GROUP, params) for g, paths in theme.groups.items()}
    cfg = {"bar_gap": 20, "bar_width": 0.5, "groups": groups}
    anim = next((g for g in groups.values() if g is not groups.get(UI_GROUP)), None)
    if anim:
        x0, _, x1, y1 = anim["_bbox"]
        w, h = anim["_size"]
        cfg["bar_gap"] = int(20 - (h - 1 - y1))
        cfg["bar_width"] = round(float(0.6 * (x1 - x0 + 1) / w), 2)
    return cfg


def print_mapping(theme, cfg):
    print(f"{theme.title} [{theme.module}]")
    for g, grp in cfg["groups"].items():
        n = len(theme.groups.get(g, []))
        bg = "transparent" if grp["transparent"] else f"background {grp['background']}"
        print(f"  {g} ({n} image{'s' if n > 1 else ''}, {bg})")
        print_colours(grp["colors"])


# --------------------------------------------------------------- theme files

def patch_script(text, flavor):
    """Flavour base for the whole window + flavour `text` colour for white text."""
    b = color_args(flavor, "base")
    text, n = re.subn(r"Window\.SetBackground(Top|Bottom)Color\s*\([^)]*\)",
                      lambda m: f"Window.SetBackground{m.group(1)}Color({b})", text)
    if not n:
        bg = (f"// Catppuccin {FLAVOR_TITLES[flavor]} background\n"
              f"Window.SetBackgroundTopColor({b});\n"
              f"Window.SetBackgroundBottomColor({b});\n\n")
        if "// Screen size" in text:
            text = text.replace("// Screen size", bg + "// Screen size", 1)
        else:
            text = bg + text
    white = r",\s*1(?:\.0*)?\s*,\s*1(?:\.0*)?\s*,\s*1(?:\.0*)?\s*([,)])"
    return re.sub(white, lambda m: f", {color_args(flavor, 'text')}{m.group(1)}", text)


def plymouth_colour(flavor, name, old):
    """0xRRGGBB / 0xAARRGGBB value keeping the original alpha byte, if any."""
    hx = PALETTES[flavor][name]
    v = old.strip().lower().removeprefix("0x")
    return "0x" + (v[:2] + hx if len(v) == 8 else hx)


def colour_key_target(key, bar):
    k = key.lower()
    if "progressbarforeground" in k:
        return bar
    if "progressbarbackground" in k:
        return "surface0"
    if "background" in k:
        return "base"
    return "text"


def patch_plymouth(theme, new_name, desc, flavor, bar):
    text = theme.conf_text
    text = re.sub(r"^Name(\[[^]]*\])?=.*\n?", "", text, flags=re.M)
    text = re.sub(r"^Description(\[[^]]*\])?=.*\n?", "", text, flags=re.M)
    text = re.sub(r"^(\[Plymouth Theme\]\s*\n)",
                  f"\\1Name={new_name}\nDescription={desc}\n", text, count=1, flags=re.M)
    comment = f"Catppuccin {FLAVOR_TITLES[flavor]} recolour of {theme.title}"
    old = re.search(r"^Comment=(.*)$", text, flags=re.M)
    if old:
        text = text.replace(old.group(0), f"Comment={comment} ({old.group(1).strip()})", 1)
    else:
        text = re.sub(r"^(Description=.*\n)", f"\\1Comment={comment}\n", text, count=1, flags=re.M)
    text = re.sub(r"^(\s*ImageDir\s*=).*$", rf"\g<1>{INSTALL_DIR}/{new_name}", text, flags=re.M)
    text = re.sub(r"^(\s*ScriptFile\s*=).*$", rf"\g<1>{INSTALL_DIR}/{new_name}/{new_name}.script",
                  text, flags=re.M)
    if theme.module == "two-step":
        text = re.sub(r"^(\s*(\w*Color)\s*=\s*)(0x[0-9a-fA-F]{6,8})\s*$",
                      lambda m: m.group(1) + plymouth_colour(
                          flavor, colour_key_target(m.group(2), bar), m.group(3)),
                      text, flags=re.M)
        if not re.search(r"^\s*BackgroundStartColor", text, flags=re.M):
            base = plymouth_colour(flavor, "base", "0x000000")
            text = re.sub(r"^(\[two-step\]\s*\n)",
                          f"\\1BackgroundStartColor={base}\nBackgroundEndColor={base}\n",
                          text, count=1, flags=re.M)
    return text


def write_theme(theme, new_name, flavor, acc, bar, dst_dir):
    if dst_dir.exists():
        shutil.rmtree(dst_dir)
    dst_dir.mkdir(parents=True)
    skip = {theme.conf_file.name, theme.script.name if theme.script else None}
    for f in theme.dir.iterdir():                # fonts, licences, ...
        if f.suffix != ".png" and f.name not in skip and (real := source_file(f, theme.dir)):
            shutil.copyfile(real, dst_dir / f.name)     # a link inside the theme: its file
        elif f.is_symlink() and f.suffix != ".png":
            print(f"note: skipped {f}: a link out of {theme.dir}")
    desc = f"{theme.title} - Catppuccin {FLAVOR_TITLES[flavor]}" + (f" {acc}" if acc else "")
    (dst_dir / f"{new_name}.plymouth").write_text(patch_plymouth(theme, new_name, desc, flavor, bar))
    if theme.script:
        (dst_dir / f"{new_name}.script").write_text(patch_script(theme.script.read_text(), flavor))


def write_status_variant(base_dir, flavor, bar, bar_width, bar_gap):
    """"-status" variant: same frames + progress bar + latest services."""
    base = base_dir.name
    name = base + "-status"
    dst = base_dir.parent / name
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(base_dir, dst)
    (dst / f"{base}.script").rename(dst / f"{name}.script")
    conf = (dst / f"{base}.plymouth").read_text().replace(base, name)
    conf = re.sub(r"^Description=(.*)$", r"Description=\1 (progress + status)", conf, flags=re.M)
    (dst / f"{name}.plymouth").write_text(conf)
    (dst / f"{base}.plymouth").unlink()

    extras = ((HERE / "extras.script").read_text()
              .replace("@SUBTEXT@", color_args(flavor, "subtext0"))
              .replace("@OVERLAY@", color_args(flavor, "overlay1"))
              .replace("@BARFRAC@", str(bar_width))
              .replace("@BARGAP@", str(bar_gap)))
    with open(dst / f"{name}.script", "a") as f:
        f.write(extras)
    for fname, col in (("bar-track.png", "surface0"), ("bar-fill.png", bar)):
        Image.new("RGB", (1, 1), tuple(int(v) for v in rgb(flavor, col))).save(dst / fname)


# ------------------------------------------------------------------- preview
def preview_sheet(theme, plan, cfg, out):
    """One row per image group: original (over its background) | recoloured (over base)
    | separation (each source colour in its own plain colour, see recolor)."""
    rows = []
    for g, (src_bg, keys, targets, base) in plan.items():
        paths = theme.groups[g]
        if g == UI_GROUP:   # the largest UI image is the most telling
            path = max(paths, key=lambda p: Image.open(p).size[0] * Image.open(p).size[1]
                       if Image.open(p).size[0] < 4000 else 0)
        else:
            path = paths[len(paths) // 2]
        im = Image.open(path).convert("RGBA")
        before = Image.new("RGBA", im.size, tuple(int(v) for v in src_bg) + (255,))
        before.alpha_composite(im)
        after = Image.new("RGBA", im.size, tuple(int(v) for v in base) + (255,))
        after.alpha_composite(recolor_image(path, src_bg, keys, targets, base).convert("RGBA"))
        scale = min(240 / im.height, 560 / im.width, 8)
        size = (max(1, round(im.width * scale)), max(1, round(im.height * scale)))
        sep, legend = separation_image(path, cfg["groups"][g])
        rows.append([before.convert("RGB").resize(size), after.convert("RGB").resize(size),
                     draw_legend(sep.resize(size), legend)])
    col = max(r[0].width for r in rows) + SHEET_GAP
    sheet = Image.new("RGB", (3 * col - SHEET_GAP, sum(r[0].height + SHEET_GAP for r in rows)),
                      SHEET_GAP_COLOUR)
    y = 0
    for row in rows:
        for i, panel in enumerate(row):
            sheet.paste(panel, (i * col, y))
        y += row[0].height + SHEET_GAP
    sheet.save(out)


def main_animation(theme):
    """The longest numbered sequence of images (None: only single images)."""
    return next((g for g in theme.groups if g != UI_GROUP), None)


def frame_ms(theme):
    """How long Plymouth shows each image of the main animation: it refreshes 50 times
    a second, and adi1090x's scripts move on every N refreshes (progress / N)."""
    m = theme.script and re.search(r"Math\.Int\(\s*progress\s*/\s*(\d+)\s*\)",
                                   theme.script.read_text())
    return 20 * max(1, int(m.group(1))) if m else 20


def animation_preview(theme, plan, out):
    """--preview-animation: the main animation, before (over its background) | after
    (over base), as an animated WebP."""
    g = main_animation(theme)
    src_bg, keys, targets, base = plan[g]
    def pairs():
        for path in theme.groups[g]:
            im = Image.open(path).convert("RGBA")
            before = Image.new("RGBA", im.size, tuple(int(v) for v in src_bg) + (255,))
            before.alpha_composite(im)
            after = Image.new("RGBA", im.size, tuple(int(v) for v in base) + (255,))
            after.alpha_composite(recolor_image(path, src_bg, keys, targets, base).convert("RGBA"))
            yield before.convert("RGB"), after.convert("RGB")
    preview_animation(pairs(), len(theme.groups[g]), out, frame_ms(theme))


def installed_themes():
    """The installed themes that have images to recolour, the default one marked."""
    active = default_theme()
    for d in theme_folders(INSTALL_DIR, "*.plymouth"):
        try:
            theme = Theme(d)
        except (SystemExit, OSError, configparser.Error):
            continue
        if theme.groups:                         # text, details: nothing to recolour
            yield item(d, theme.title, " · ".join(x for x in (d.name if theme.title != d.name else "",
                                                              theme.module) if x),
                       current=d.name == active, thumb=d)


def find_theme(arg):
    """Folder of a theme given as a folder, or as the name of an installed theme
    (/usr/share/plymouth/themes/<name>)."""
    p = Path(arg).expanduser()
    if p.is_dir():
        return p.resolve()
    d = Path(INSTALL_DIR) / arg
    if "/" not in arg and d.is_dir() and any(d.glob("*.plymouth")):
        return d
    raise SystemExit(f"Theme not found: {arg} (give a theme folder, or an installed theme "
                     "name: see --list)")


def themes_of(a):
    """The themes given, or the theme in use; when that one is a catppuccinizer
    result, the theme it replaced (recolouring a recolour makes no sense)."""
    if a.themes:
        return a.themes
    name, note = default_theme(), ""
    if not name:
        raise SystemExit("No theme given, and the theme in use is not known: give one "
                         "(an installed theme name, a folder; see --list)")
    state = System.load_state(state_file("plymouth", system=True))
    if name in state.get("installed", []) or name.startswith("catppuccin-"):
        if not state.get("previous"):
            raise SystemExit(f"The theme in use, {name}, is a catppuccinizer result: give the "
                             "theme to recolour (see --list)")
        name, note = check_name(state["previous"], "theme name"), f" (before {name})"
    if not hasattr(a, "_announced"):
        print(f"Theme in use: {name}{note}")
        a._announced = True
    return [name]


def default_theme():
    """The default Plymouth theme ("" when unknown)."""
    try:
        exe = which("plymouth-set-default-theme")
        return subprocess.run([exe], capture_output=True, text=True,
                              check=False).stdout.strip() if exe else ""
    except OSError:
        return ""


def colours(a):
    """--colours: each image group of each theme, under the names -m accepts
    ("group.name" when a theme has several groups)."""
    out = []
    for arg in themes_of(a):
        theme = Theme(find_theme(arg))
        cfg = detect(theme, a.separation)
        apply_maps(cfg, a.map)
        several = len(cfg["groups"]) > 1
        for g, grp in cfg["groups"].items():
            n = len(theme.groups.get(g, []))
            note = f"{n} image{'s' if n != 1 else ''}"
            out.append(colour_report(theme.name, "keys", grp["colors"], group=g,
                                     background=background_of(grp), note=note, prefix=several,
                                     part=g))
        using, _ = results(theme, cfg, a)
        if has_bar(theme, a):
            out.append(colour_report(theme.name, "fixed", group="bar", part="bar",
                                     accent="bar" in using,
                                     note="progress bar: the accent (-a bar=ACCENT for its own), "
                                          "or the main colour when nothing uses the accent"))
    return out


def has_bar(theme, a):
    """Whether the result has a progress bar: the -status variant, or the two-step
    module's own bar."""
    return (not a.no_status and theme.adi_template) or theme.module == "two-step"


def results(theme, cfg, a):
    """(parts that use the accent, core.parts.accent_sets): the image groups that
    have a colour mapped to accent (main animation first), then the progress bar
    when it follows an accent."""
    groups = [g for g, grp in cfg["groups"].items()
              if g in theme.groups and uses_accent(grp["colors"])]
    bar = has_bar(theme, a) and (groups or "bar" in a.part_accents)
    check_parts(a, [*theme.groups, *(["bar"] if has_bar(theme, a) else [])])
    using = [*groups, *(["bar"] if bar else [])]
    return using, accent_sets(a, using)


def outputs(a):
    """Per theme, flavour and accent (when a colour goes to it): the theme folder and
    its -status variant, or the before/after image with --preview."""
    out = []
    for arg in themes_of(a):
        theme = Theme(find_theme(arg))
        if not theme.groups:
            continue
        cfg = detect(theme, a.separation)
        apply_maps(cfg, a.map)
        _, sets = results(theme, cfg, a)
        status = not a.no_status and theme.adi_template
        for flv in a.flavor:
            for _, aname in sets:
                name = output_name(flv, theme.slug, aname, a.suffix)
                if previewing(a):
                    ext = ".webp" if a.preview_animation else ".png"
                    out.append(planned(a.out / "previews" / f"{name}{ext}"))
                    continue
                out.append(planned(a.out / name, folder=True))
                if status:
                    out.append(planned(a.out / f"{name}-status", folder=True))
    return out


def build(a):
    """The themes; for the system steps, the folder to install (the -status variant
    if any) of the first one (they need a single theme)."""
    jobs, status, copies = [], [], []
    for arg in themes_of(a):
        theme = Theme(find_theme(arg))
        if not theme.groups:
            print(f"{theme.title}: no PNG images, nothing to recolour")
            continue
        cfg = detect(theme, a.separation)
        apply_maps(cfg, a.map)
        print_mapping(theme, cfg)

        using, sets = results(theme, cfg, a)
        if not using:
            note_accent_ignored(a)
        note_unused(a, using)
        main_colours = [c["target"] for grp in cfg["groups"].values()
                        for c in sorted(grp["colors"].values(), key=lambda c: -c.get("share", 0))
                        if c["target"] in ACCENTS]
        with_status = not a.no_status and theme.adi_template
        done = {}      # (flavour, group, accent or None) -> folder whose images can be copied
        if not a.no_status and not theme.adi_template and not previewing(a):
            print("  (no -status variant: only for adi1090x-style script themes)")
        for flv in a.flavor:
            for accents, aname in sets:
                out_name = output_name(flv, theme.slug, aname, a.suffix)
                # bar colour: its accent, else the most common colour target
                bar = accents.get("bar") or (main_colours[0] if main_colours else "blue")
                plan = {g: keys_plan(grp, flv, accents.get(g))
                        for g, grp in cfg["groups"].items() if g in theme.groups}
                if previewing(a):
                    (a.out / "previews").mkdir(parents=True, exist_ok=True)
                    if a.preview_animation:
                        out = a.out / "previews" / f"{out_name}.webp"
                        print(f"  recolouring {len(theme.groups[main_animation(theme)])} "
                              "images of the main animation…", flush=True)
                        animation_preview(theme, plan, out)
                    else:
                        out = a.out / "previews" / f"{out_name}.png"
                        preview_sheet(theme, plan, cfg, out)
                    print(f"  preview: {out}")
                    continue
                write_theme(theme, out_name, flv, aname, bar, a.out / out_name)
                for g in plan:
                    # a group without "accent" is the same for every accent: recoloured
                    # once, then copied into the other accents' themes
                    gkey = (flv, g, accents.get(g))
                    if gkey in done:
                        copies += [(done[gkey] / p.name, a.out / out_name / p.name)
                                   for p in theme.groups[g]]
                        continue
                    done[gkey] = a.out / out_name
                    jobs += [(p, a.out / out_name / p.name, "keys", cfg["groups"][g], flv,
                              accents.get(g), a) for p in theme.groups[g]]
                status.append(((a.out / out_name, flv, bar, cfg["bar_width"], cfg["bar_gap"]),
                               with_status))

    if not jobs:
        return None
    print(f"{len(status)} theme(s), {len(jobs)} images", flush=True)
    run_jobs(jobs, parallel=True)
    for src, dst in copies:
        shutil.copyfile(src, dst)
    for args, with_st in status:
        if with_st:
            write_status_variant(*args)
        print(f"  -> {args[0]}" + (f"  (+ {args[0].name}-status)" if with_st else ""))

    folder, with_st = status[0][0][0], status[0][1]
    return folder.parent / f"{folder.name}-status" if with_st else folder


TARGET = PlymouthTarget()
