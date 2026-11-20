"""Limine target: Catppuccin colours (and optionally a recoloured wallpaper) for
the Limine boot menu.

Without --apply, writes a snippet (limine-theme.conf) and the wallpaper into the
output folder. With --apply, inserts the snippet into limine.conf between marker
comments (a backup is made, conflicting global options are commented out) and
copies the wallpaper to the ESP. --remove undoes it.

An existing wallpaper is kept (the menu background becomes see-through over
it), unless --wallpaper replaces it or --recolor-wallpaper recolours it.
"""
import os
import re
import shutil
from datetime import datetime
from pathlib import Path

from ..core import recolor
from ..core.mapping import colour_report
from ..core.naming import output_name
from ..core.options import Option
from ..core.palette import FLAVOR_TITLES, PALETTES
from ..core.paths import give_back
from ..core.target import Target

BEGIN = "# >>> catppuccinizer"
END = "# <<< catppuccinizer"
DISABLED = "# (catppuccinizer) "
WALL_DIR = "catppuccin"
WALL_KEYS = ["wallpaper", "wallpaper_style"]
KEYS = ["backdrop", "term_palette", "term_palette_bright",
        "term_background", "term_foreground", "term_background_bright", "term_foreground_bright",
        "interface_branding_colour", "interface_branding_color", "interface_help_colour",
        "interface_help_color", "interface_help_colour_bright", "interface_help_color_bright"]


class LimineTarget(Target):
    name = "limine"
    help = "Catppuccin colours + wallpaper for the Limine boot menu"
    default_accent = ("mauve",)
    accent_also = "the menu colours"

    def options(self):
        return OPTIONS

    def check(self, a):
        check_args(a)

    def run(self, a):
        run(a)

    def colours(self, a):
        return colours(a)


OPTIONS = [
    Option("--wallpaper", type=Path, metavar="IMAGE", accept="image", source=True,
           help="image to recolour and use as the Limine wallpaper"),
    Option("--recolor-wallpaper", switch=True,
           help="recolour the wallpaper(s) already set in limine.conf"),
    *recolor.method_options(),
    Option("--style", choices=["stretched", "centered", "tiled"],
           help="wallpaper_style (default: the current one, or stretched)"),
    Option("--apply", switch=True, stage="apply", sudo="run",
           help="write the theme into limine.conf (run with sudo; a backup is made)"),
    Option("--remove", switch=True, stage="restore", sudo="run",
           help="remove the theme from limine.conf"),
    Option("--conf", type=Path, accept="file", stage="apply",
           help="limine.conf to edit (default: searched on the ESP)"),
    Option("--esp", type=Path, accept="dir", stage="apply",
           help="ESP mount point (default: ESP_PATH of /etc/default/limine, or /boot)"),
]


def check_args(a):
    if a.apply and (len(a.flavor) > 1 or len(a.accent) > 1):
        raise SystemExit("--apply needs a single flavour and a single accent")
    if a.wallpaper and a.recolor_wallpaper:
        raise SystemExit("use either --wallpaper or --recolor-wallpaper")
    if a.wallpaper and not a.wallpaper.is_file():
        raise SystemExit(f"Not found: {a.wallpaper}")


def theme_lines(flavor, accent, wallpapers=(), style=None, over_wallpaper=False):
    p = PALETTES[flavor]
    normal = ";".join(p[c] for c in ("surface1", "red", "green", "yellow", "blue", "pink",
                                     "teal", "subtext1"))
    bright = ";".join(p[c] for c in ("surface2", "red", "green", "yellow", "blue", "pink",
                                     "teal", "subtext0"))
    lines = [f"{BEGIN}: Catppuccin {FLAVOR_TITLES[flavor]} ({accent})"]
    lines += [f"wallpaper: {w}" for w in wallpapers]
    if wallpapers:
        lines.append(f"wallpaper_style: {style or 'stretched'}")
    see_through = bool(wallpapers) or over_wallpaper
    lines += [
        f"backdrop: {p['base']}",
        f"term_palette: {normal}",
        f"term_palette_bright: {bright}",
        # TTRRGGBB, TT = transparency: slightly see-through over a wallpaper
        f"term_background: {'33' if see_through else '00'}{p['base']}",
        f"term_foreground: {p['text']}",
        f"term_background_bright: {p['surface0']}",
        f"term_foreground_bright: {p['text']}",
        f"interface_branding_colour: {p[accent]}",
        f"interface_help_colour: {p['subtext0']}",
        f"interface_help_colour_bright: {p[accent]}",
        END,
    ]
    return lines


# --------------------------------------------------------------- limine.conf
def default_esp():
    try:
        m = re.search(r'^ESP_PATH="?([^"\n]+)"?', Path("/etc/default/limine").read_text(), re.M)
        if m:
            return Path(m.group(1))
    except OSError:
        pass
    return Path("/boot")


def find_conf(esp):
    if esp.is_dir() and not os.access(esp, os.R_OK | os.X_OK):
        raise SystemExit(f"Cannot read {esp}: run with sudo.")
    for rel in ("limine.conf", "EFI/limine/limine.conf", "EFI/BOOT/limine.conf",
                "boot/limine/limine.conf", "limine/limine.conf"):
        if (esp / rel).is_file():
            return esp / rel
    raise SystemExit(f"limine.conf not found under {esp} (use --conf)")


def strip_theme(text):
    """Remove our block and re-enable the options we had commented out."""
    text = re.sub(rf"^{re.escape(BEGIN)}.*?^{re.escape(END)}\n(\n(?=\s*/))?", "", text,
                  flags=re.M | re.S)
    return re.sub(rf"^{re.escape(DISABLED)}", "", text, flags=re.M)


def global_values(text, key):
    """Active values of a global option (before the first menu entry)."""
    vals = []
    for line in text.splitlines():
        if line.lstrip().startswith("/"):
            break
        k, _, v = line.partition(":")
        if k.strip().lower() == key and not line.lstrip().startswith("#"):
            vals.append(v.strip())
    return vals


def resolve_on_esp(ref, esp):
    """'boot():/path#hash' (or any 'xxx():/path') -> file on the mounted ESP."""
    path = re.sub(r"^[a-z_]+\([^)]*\):", "", ref).split("#", 1)[0]
    return esp / path.lstrip("/")


def insert_theme(text, lines, replace_wallpaper=False):
    text = strip_theme(text)
    disable = KEYS + (WALL_KEYS if replace_wallpaper else [])
    out, in_globals, inserted = [], True, False
    for line in text.splitlines():
        if in_globals and line.lstrip().startswith("/"):        # first menu entry
            out += lines + [""]
            in_globals, inserted = False, True
        key = line.split(":", 1)[0].strip().lower()
        if in_globals and key in disable and not line.lstrip().startswith("#"):
            line = DISABLED + line
        out.append(line)
    if not inserted:
        out += [""] + lines
    return "\n".join(out) + "\n"


def apply(conf, esp, lines, wallpaper_files=()):
    try:
        text = conf.read_text()
        backup = conf.with_name(conf.name + datetime.now().strftime(".%Y%m%d-%H%M%S-%f.bak"))
        shutil.copy2(conf, backup)
        for wf in wallpaper_files:
            (esp / WALL_DIR).mkdir(exist_ok=True)
            shutil.copy(wf, esp / WALL_DIR / wf.name)
        conf.write_text(insert_theme(text, lines, bool(wallpaper_files)) if lines
                        else strip_theme(text))
        if not lines:                            # --remove: drop our wallpapers too
            for f in (esp / WALL_DIR).glob("catppuccin-*-wallpaper*"):
                f.unlink()
            if (esp / WALL_DIR).is_dir() and not any((esp / WALL_DIR).iterdir()):
                (esp / WALL_DIR).rmdir()
    except PermissionError as e:
        raise SystemExit(f"{e}\nRun with sudo to edit {conf}.")
    print(f"  backup: {backup}")
    print(f"  updated: {conf}")
    if Path("/etc/limine-entry-tool.conf").exists() and re.search(
            r"^ENABLE_ENROLL_LIMINE_CONFIG=yes", Path("/etc/limine-entry-tool.conf").read_text(), re.M):
        print("  config enrollment is on: run 'sudo limine-enroll-config' now")


def wallpapers(a, esp, read_conf):
    """(limine.conf, its current wallpapers, their style, the images to recolour);
    limine.conf is only read when read_conf."""
    conf, current, style = None, [], a.style
    if read_conf:
        conf = a.conf or find_conf(esp)
        try:
            text = strip_theme(conf.read_text())
        except PermissionError:
            raise SystemExit(f"Cannot read {conf}: run with sudo.")
        current = global_values(text, "wallpaper")
        style = style or next(iter(global_values(text, "wallpaper_style")), None)
        if current:
            print(f"Current Limine wallpaper: {', '.join(current)}")
    sources = [a.wallpaper] if a.wallpaper else []
    if a.recolor_wallpaper:
        if not current:
            raise SystemExit("limine.conf has no wallpaper to recolour (use --wallpaper IMAGE)")
        sources = [resolve_on_esp(w, esp) for w in current]
        for src in sources:
            if not src.is_file():
                raise SystemExit(f"Wallpaper not found on the ESP: {src} (use --esp or --wallpaper)")
    return conf, current, style, sources


def colours(a):
    """--colours: the menu (fixed roles, nothing to remap) and each wallpaper."""
    sources = wallpapers(a, a.esp or default_esp(), a.recolor_wallpaper)[3]
    return [colour_report("menu", "fixed", note="Catppuccin roles, the accent comes from -a"),
            *(recolor.colour_report(src, *recolor.plan(src, a, verbose=False)) for src in sources)]


def run(a):
    esp = a.esp or default_esp()
    if a.remove:
        conf = a.conf or find_conf(esp)
        print(f"Removing the Catppuccin theme from {conf}")
        return apply(conf, esp, None)

    conf, current, style, sources = wallpapers(a, esp, a.apply or a.recolor_wallpaper)
    plans = [recolor.plan(src, a) for src in sources]          # analysed once per image
    done = {}       # (image, flavour, accent or None) -> files already written for it
    for flv in a.flavor:
        for acc in a.accent:
            name = output_name(flv, "limine", acc, a.suffix)
            dst = a.out / name
            dst.mkdir(parents=True, exist_ok=True)
            wall_files = []
            for k, (src, (method, grp)) in enumerate(zip(sources, plans)):
                # a wallpaper that ignores the accent is the same for every accent:
                # rendered once per flavour, named without the accent, copied
                wacc = None if recolor.accent_ignored_reason(method, grp) else acc
                stem = output_name(flv, "wallpaper" + (f"-{k + 1}" if len(sources) > 1 else ""),
                                   wacc, a.suffix)
                key = (k, flv, wacc)
                if key in done:
                    for f in done[key]:
                        if f.parent != dst:
                            shutil.copyfile(f, dst / f.name)
                    wall_files.append(dst / done[key][0].name)
                    continue
                im = recolor.render(src, method, grp, flv, wacc, a)
                files = [recolor.save_image(im.convert("RGB"), dst / stem, method, src)]
                if a.preview:
                    (a.out / "previews").mkdir(parents=True, exist_ok=True)
                    recolor.side_by_side(src, im, a.out / "previews" / f"{stem}.png")
                done[key] = files
                wall_files.append(files[0])
            wall_refs = [f"boot():/{WALL_DIR}/{f.name}" for f in wall_files]
            lines = theme_lines(flv, acc, wall_refs, style,
                                over_wallpaper=bool(current) and not wall_files)
            (dst / "limine-theme.conf").write_text("\n".join(lines) + "\n")
            print(f"Catppuccin {FLAVOR_TITLES[flv]} ({acc}) -> {dst}")
            if a.apply:
                apply(conf, esp, lines, wall_files)
            else:
                print(f"  paste {dst / 'limine-theme.conf'} at the top of limine.conf"
                      + (f", copy {', '.join(f.name for f in wall_files)} to <ESP>/{WALL_DIR}/"
                         if wall_files else "")
                      + ", or rerun with --apply (sudo)")
    give_back(a.out)      # files written under sudo belong to the invoking user


TARGET = LimineTarget()
