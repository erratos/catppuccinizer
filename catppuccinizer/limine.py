"""Limine target: Catppuccin colours (and optionally a recoloured wallpaper) for
the Limine boot menu.

Without --apply, writes a snippet (limine-theme.conf) and the wallpaper into the
output folder. With --apply, inserts the snippet into limine.conf between marker
comments (a backup is made, conflicting global options are commented out) and
copies the wallpaper to the ESP. --remove undoes it.
"""
import os
import re
import shutil
from datetime import datetime
from pathlib import Path

from . import ROOT
from . import image as img
from .palette import FLAVOR_TITLES, PALETTES

BEGIN = "# >>> catppuccinizer"
END = "# <<< catppuccinizer"
DISABLED = "# (catppuccinizer) "
WALL_DIR = "catppuccin"
KEYS = ["wallpaper", "wallpaper_style", "backdrop", "term_palette", "term_palette_bright",
        "term_background", "term_foreground", "term_background_bright", "term_foreground_bright",
        "interface_branding_colour", "interface_branding_color", "interface_help_colour",
        "interface_help_color", "interface_help_colour_bright", "interface_help_color_bright"]


def add_arguments(p):
    p.add_argument("--wallpaper", type=Path, metavar="IMAGE",
                   help="image to recolour and use as the Limine wallpaper")
    img.add_method_arguments(p)
    p.add_argument("--style", choices=["stretched", "centered", "tiled"], default="stretched",
                   help="wallpaper_style (default: stretched)")
    p.add_argument("--apply", action="store_true",
                   help="write the theme into limine.conf (run with sudo; a backup is made)")
    p.add_argument("--remove", action="store_true", help="remove the theme from limine.conf")
    p.add_argument("--conf", type=Path, help="limine.conf to edit (default: searched on the ESP)")
    p.add_argument("--esp", type=Path,
                   help="ESP mount point (default: ESP_PATH of /etc/default/limine, or /boot)")
    p.set_defaults(out_default=ROOT / "themes", default_accent=["mauve"])


def check_args(a):
    if a.apply and (len(a.flavor) > 1 or len(a.accent) > 1):
        raise SystemExit("--apply needs a single flavour and a single accent")


def theme_lines(flavor, accent, wallpaper_path=None, style="stretched"):
    p = PALETTES[flavor]
    normal = ";".join(p[c] for c in ("surface1", "red", "green", "yellow", "blue", "pink",
                                     "teal", "subtext1"))
    bright = ";".join(p[c] for c in ("surface2", "red", "green", "yellow", "blue", "pink",
                                     "teal", "subtext0"))
    lines = [f"{BEGIN}: Catppuccin {FLAVOR_TITLES[flavor]} ({accent})"]
    if wallpaper_path:
        lines += [f"wallpaper: {wallpaper_path}", f"wallpaper_style: {style}"]
    lines += [
        f"backdrop: {p['base']}",
        f"term_palette: {normal}",
        f"term_palette_bright: {bright}",
        # TTRRGGBB, TT = transparency: slightly see-through over a wallpaper
        f"term_background: {'33' if wallpaper_path else '00'}{p['base']}",
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


def insert_theme(text, lines):
    text = strip_theme(text)
    out, in_globals, inserted = [], True, False
    for line in text.splitlines():
        if in_globals and line.lstrip().startswith("/"):        # first menu entry
            out += lines + [""]
            in_globals, inserted = False, True
        key = line.split(":", 1)[0].strip().lower()
        if in_globals and key in KEYS and not line.lstrip().startswith("#"):
            line = DISABLED + line
        out.append(line)
    if not inserted:
        out += [""] + lines
    return "\n".join(out) + "\n"


def apply(conf, esp, lines, wallpaper_file):
    try:
        text = conf.read_text()
        backup = conf.with_name(conf.name + datetime.now().strftime(".%Y%m%d-%H%M%S-%f.bak"))
        shutil.copy2(conf, backup)
        if wallpaper_file:
            (esp / WALL_DIR).mkdir(exist_ok=True)
            shutil.copy(wallpaper_file, esp / WALL_DIR / wallpaper_file.name)
        conf.write_text(insert_theme(text, lines) if lines else strip_theme(text))
        if not lines:                            # --remove: drop our wallpapers too
            for f in (esp / WALL_DIR).glob("wallpaper-*"):
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


def run(a):
    esp = a.esp or default_esp()
    if a.remove:
        conf = a.conf or find_conf(esp)
        print(f"Removing the Catppuccin theme from {conf}")
        return apply(conf, esp, None, None)

    for flv in a.flavor:
        for acc in a.accent:
            name = f"limine-catppuccin-{flv}-{acc}"
            dst = a.out / name
            dst.mkdir(parents=True, exist_ok=True)
            wall_file = wall_ref = None
            if a.wallpaper:
                method, grp = img.plan_image(a.wallpaper, a)
                im = img.render(a.wallpaper, method, grp, flv, acc, a)
                if a.preview:
                    img.side_by_side(a.wallpaper, im, dst / "preview.png")
                wall_file = img.save(im.convert("RGB"), dst / f"wallpaper-{flv}-{acc}", method,
                                     a.wallpaper)
                wall_ref = f"boot():/{WALL_DIR}/{wall_file.name}"
            lines = theme_lines(flv, acc, wall_ref, a.style)
            (dst / "limine-theme.conf").write_text("\n".join(lines) + "\n")
            print(f"Catppuccin {FLAVOR_TITLES[flv]} ({acc}) -> {dst}")
            if a.apply:
                conf = a.conf or find_conf(esp)
                apply(conf, esp, lines, wall_file)
            else:
                print(f"  paste {dst / 'limine-theme.conf'} at the top of limine.conf"
                      + (f", copy {wall_file.name} to <ESP>/{WALL_DIR}/" if wall_file else "")
                      + ", or rerun with --apply (sudo)")
    if a.apply and os.geteuid() == 0 and a.out.is_relative_to(ROOT):
        # files written as root in the user's checkout: give them back
        uid, gid = ROOT.stat().st_uid, ROOT.stat().st_gid
        for p in [a.out, *a.out.rglob("*")]:
            os.chown(p, uid, gid)
