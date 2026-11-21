"""Limine target: Catppuccin colours (and optionally a recoloured wallpaper) for
the Limine boot menu.

Writes a snippet (limine-theme.conf) and the wallpaper into the output folder.
--install copies the wallpaper to the ESP; --apply (which installs first)
inserts the snippet into limine.conf between marker comments (a backup is made,
conflicting global options are commented out). --restore undoes both.

limine.conf is edited byte for byte: apply only adds the block and comments out
options, restore removes exactly that, and the result is checked before it is
written (check_insert): the rest of the file stays as it was.

An existing wallpaper is kept (the menu background becomes see-through over
it), unless --wallpaper replaces it or --recolor-wallpaper recolours it.
"""
import os
import re
import shutil
from pathlib import Path

from ..core import recolor
from ..core.mapping import colour_report
from ..core.naming import output_name, planned
from ..core.options import Option, step
from ..core.palette import FLAVOR_TITLES, PALETTES
from ..core.sources import item, section, wallpaper_sections
from ..core.system import place, read_text
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

    def build(self, a):
        return build(a)

    def install(self, a, built, system):
        if not built["wallpapers"]:
            print("  nothing to copy: no new wallpaper (the current one, if any, is kept)")
        for f in built["wallpapers"]:
            system.copy_file(f, place(built["esp"] / WALL_DIR, f.name, "wallpaper name"))

    def apply(self, a, built, system):
        conf = built["conf"]
        system.write_text(conf, insert_theme(read(conf), built["lines"],
                                             bool(built["wallpapers"])), backup=True)
        enrollment_note()

    def restore(self, a, system):
        esp = a.esp or default_esp()
        conf = a.conf or find_conf(esp)
        text = read(conf)
        stripped = strip_theme(text)
        if stripped == text:
            print(f"  {conf}: no catppuccinizer theme in it, left as it is")
        else:
            system.write_text(conf, stripped, backup=True)
        walls = esp / WALL_DIR
        ours = sorted(walls.glob("catppuccin-*-wallpaper*"))
        for f in ours:
            system.remove(f)
        if walls.is_dir() and not set(walls.iterdir()) - set(ours):     # nothing else in it
            system.remove(walls)
        enrollment_note()

    def colours(self, a):
        return colours(a)

    def sources(self):
        return [section("Set in limine.conf", current_wallpapers), *wallpaper_sections()]

    def outputs(self, a):
        return outputs(a)


OPTIONS = [
    Option("--wallpaper", type=Path, metavar="IMAGE", accept="image", source=True,
           help="image to recolour and use as the Limine wallpaper"),
    Option("--recolor-wallpaper", switch=True,
           help="recolour the wallpaper(s) already set in limine.conf"),
    *recolor.method_options(),
    Option("--style", choices=["stretched", "centered", "tiled"],
           help="wallpaper_style (default: the current one, or stretched)"),
    step("install", sudo="run", help=f"copy the wallpaper to <ESP>/{WALL_DIR}/ (sudo)"),
    step("apply", sudo="run",
         help="install, then write the theme into limine.conf (sudo; a backup is made)",
         explain="Here: the theme block goes before the first menu entry and the global "
                 "options it replaces are commented out; the rest of limine.conf is checked "
                 "to stay byte for byte the same, otherwise nothing is written."),
    step("restore", sudo="run",
         help="remove the theme from limine.conf and its wallpapers from the ESP (sudo)",
         explain="Here: exactly the block is removed and the options it had commented out "
                 "come back, so changes made since (new kernel entries) are kept."),
    Option("--conf", type=Path, accept="file", stage="apply",
           help="limine.conf to edit (default: searched on the ESP)"),
    Option("--esp", type=Path, accept="dir", stage="apply",
           help="ESP mount point (default: ESP_PATH of /etc/default/limine, or /boot)"),
]


def check_args(a):
    if (a.install or a.apply) and (len(a.flavor) > 1 or len(a.accent) > 1):
        raise SystemExit("--install / --apply need a single flavour and a single accent")
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
        raise SystemExit(f"Cannot read {esp}: run with sudo (--dry-run too: it changes nothing, but it reads limine.conf)")
    for rel in ("limine.conf", "EFI/limine/limine.conf", "EFI/BOOT/limine.conf",
                "boot/limine/limine.conf", "limine/limine.conf"):
        if (esp / rel).is_file():
            return esp / rel
    raise SystemExit(f"limine.conf not found under {esp} (use --conf)")


# our block, and the blank line insert_theme puts after it
BLOCK = re.compile(rf"^{re.escape(BEGIN)}[^\n]*\n(?:.*?\n)??{re.escape(END)}\n\n?", re.M | re.S)


def markers(text):
    return (len(re.findall(rf"^{re.escape(BEGIN)}", text, re.M)),
            len(re.findall(rf"^{re.escape(END)}$", text, re.M)))


def strip_theme(text):
    """Remove our block and re-enable the options we had commented out: exactly what
    insert_theme added, so the rest of the file comes back byte for byte."""
    text, n = BLOCK.subn("", text)
    if markers(text) != (0, 0):
        raise SystemExit(f"limine.conf: a '{BEGIN}' line without its '{END}' line (or the "
                         "reverse); fix it by hand, nothing was written")
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
    """'boot():/path#hash' (or any 'xxx():/path') -> file on the mounted ESP (never
    out of it: '../' is refused)."""
    path = re.sub(r"^[a-z_]+\([^)]*\):", "", ref).split("#", 1)[0]
    f = esp / path.lstrip("/")
    if not f.resolve().is_relative_to(esp.resolve()):
        raise SystemExit(f"limine.conf: wallpaper {ref} is not on the ESP ({esp})")
    return f


def insert_theme(text, lines, replace_wallpaper=False):
    """limine.conf with our block (lines) before the first menu entry (at the top
    when there is none) and the conflicting global options commented out; the
    rest of the file is kept byte for byte (line endings included)."""
    base = strip_theme(text)
    disable = KEYS + (WALL_KEYS if replace_wallpaper else [])
    block = "".join(line + "\n" for line in lines) + "\n"
    out, in_globals = [], True
    for line in base.splitlines(keepends=True):
        if in_globals and line.lstrip().startswith("/"):        # first menu entry
            out.append(block)
            in_globals = False
        key = line.split(":", 1)[0].strip().lower()
        if in_globals and key in disable and not line.lstrip().startswith("#"):
            line = DISABLED + line
        out.append(line)
    if in_globals:
        out.insert(0, block)
    new = "".join(out)
    check_insert(base, new, block)
    return new


def check_insert(base, new, block):
    """Read the new limine.conf back before it is written: one block, exactly ours,
    and the rest of the file unchanged byte for byte (once our commented-out
    options are enabled again)."""
    found = BLOCK.search(new)
    if (markers(new) != (1, 1) or not found or found.group(0) != block
            or strip_theme(new) != base):
        raise SystemExit("limine.conf: the new file would change more than the "
                         "catppuccinizer block; nothing was written")


def read(conf):
    try:
        return read_text(conf)              # as it is: byte for byte when written back
    except PermissionError:
        raise SystemExit(f"Cannot read {conf}: run with sudo (--dry-run too: it changes nothing, but it reads limine.conf)")


def enrollment_note():
    tool = Path("/etc/limine-entry-tool.conf")
    if tool.exists() and re.search(r"^ENABLE_ENROLL_LIMINE_CONFIG=yes", tool.read_text(), re.M):
        print("  config enrollment is on: run 'sudo limine-enroll-config' now")


def wallpapers(a, esp, read_conf):
    """(limine.conf, its current wallpapers, their style, the images to recolour);
    limine.conf is only read when read_conf."""
    conf, current, style = None, [], a.style
    if read_conf:
        conf = a.conf or find_conf(esp)
        text = strip_theme(read(conf))
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


def current_wallpapers():
    """The wallpapers limine.conf sets (without the catppuccinizer theme: the one it
    replaced, which is the one to recolour)."""
    esp = default_esp()
    if esp.is_dir() and not os.access(esp, os.R_OK | os.X_OK):
        raise SystemExit(f"{esp} can only be read by root: to recolour the wallpaper set in "
                         "limine.conf, use “recolour the wallpaper(s) already set” "
                         "(--recolor-wallpaper) and run with sudo")
    conf = find_conf(esp)
    for ref in global_values(strip_theme(read(conf)), "wallpaper"):
        f = resolve_on_esp(ref, esp)
        yield item(f, f.name, f"{ref} in {conf}" + ("" if f.is_file() else ", not found"),
                   current=True, thumb=f if f.is_file() else None)


def colours(a):
    """--colours: the menu (fixed roles, nothing to remap) and each wallpaper."""
    sources = wallpapers(a, a.esp or default_esp(), a.recolor_wallpaper)[3]
    return [colour_report("menu", "fixed", note="Catppuccin roles, the accent comes from -a"),
            *(recolor.colour_report(src, *recolor.plan(src, a, verbose=False)) for src in sources)]


def wallpaper_stem(flv, k, n, acc, suffix):
    return output_name(flv, "wallpaper" + (f"-{k + 1}" if n > 1 else ""), acc, suffix)


def outputs(a):
    """Per flavour and accent: the folder, its wallpapers and limine-theme.conf; the
    before/after images with --preview."""
    sources = wallpapers(a, a.esp or default_esp(), a.recolor_wallpaper)[3]
    plans = [recolor.plan(src, a, verbose=False) for src in sources]
    out = []
    for flv in a.flavor:
        for acc in a.accent:
            dst = a.out / output_name(flv, "limine", acc, a.suffix)
            out.append(planned(dst, folder=True))
            for k, (src, (method, grp)) in enumerate(zip(sources, plans)):
                wacc = None if recolor.accent_ignored_reason(method, grp) else acc
                stem = wallpaper_stem(flv, k, len(sources), wacc, a.suffix)
                out.append(planned(dst / (stem + recolor.output_suffix(method, src, opaque=True))))
                if a.preview:
                    out.append(planned(a.out / "previews" / f"{stem}.png"))
            out.append(planned(dst / "limine-theme.conf"))
    return out


def build(a):
    """The snippet and wallpapers of each flavour and accent; for the system steps,
    those of the last one (they need a single flavour and accent)."""
    esp = a.esp or default_esp()
    conf, current, style, sources = wallpapers(a, esp, a.apply or a.recolor_wallpaper)
    built = None
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
                stem = wallpaper_stem(flv, k, len(sources), wacc, a.suffix)
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
            if not a.apply:
                print(f"  paste {dst / 'limine-theme.conf'} at the top of limine.conf"
                      + (f", copy {', '.join(f.name for f in wall_files)} to <ESP>/{WALL_DIR}/"
                         if wall_files else "")
                      + ", or rerun with --apply (sudo)")
            built = {"esp": esp, "conf": conf, "lines": lines, "wallpapers": wall_files}
    return built


TARGET = LimineTarget()
