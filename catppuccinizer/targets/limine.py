"""Limine target: Catppuccin colours (and optionally a recoloured wallpaper) for
the Limine boot menu.

Writes a snippet (limine-theme.conf) and the wallpaper into the output folder.
--install copies the wallpaper to the ESP; --apply (which installs first)
inserts the snippet into limine.conf between marker comments (a backup is made,
conflicting global options are commented out). --restore undoes both.

limine.conf is edited byte for byte: apply only adds the block and comments out
options, restore removes exactly that, and the result is checked before it is
written (check_insert): the rest of the file stays as it was.

Without --wallpaper only the menu colours change (text, highlight, frame): the
wallpaper set in limine.conf is kept (the menu background becomes see-through
over it). --wallpaper IMAGE recolours IMAGE and uses it instead; --wallpaper
current recolours the wallpaper limine.conf sets (the system locations offer it).

--preview draws the boot menu as Limine lays it out (branding, help lines, the
entries of limine.conf, the countdown, the terminal frame over the wallpaper),
with the original wallpaper on its left: see menu_screen().
"""
import contextlib
import io
import os
import platform
import re
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path

from PIL import Image

from ..core import recolor
from ..core.mapping import colour_report
from ..core.naming import output_name, planned
from ..core.online import WALLHAVEN
from ..core.options import Option, previewing, step
from ..core.parts import accent_sets, check_parts, note_unused, single
from ..core.palette import FLAVOR_TITLES, PALETTES, hex2rgb
from ..core.sources import WALLPAPER_LINKS, item, section, wallpaper_sections
from ..core.system import place, read_text, which
from ..core.target import Target
from ..core.textscreen import TextScreen

BEGIN = "# >>> catppuccinizer"
END = "# <<< catppuccinizer"
DISABLED = "# (catppuccinizer) "
WALL_DIR = "catppuccin"
WALL_KEYS = ["wallpaper", "wallpaper_style"]
KEYS = ["backdrop", "term_palette", "term_palette_bright",
        "term_background", "term_foreground", "term_background_bright", "term_foreground_bright",
        "interface_branding_colour", "interface_branding_color", "interface_help_colour",
        "interface_help_color", "interface_help_colour_bright", "interface_help_color_bright"]


PARTS = ("menu", "wallpaper")            # -a menu=ACCENT wallpaper=ACCENT (core.parts)


class LimineTarget(Target):
    name = "limine"
    help = "Catppuccin colours + wallpaper for the Limine boot menu"
    links = WALLPAPER_LINKS
    online = [WALLHAVEN]
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

    def locations(self):
        return [section("Set in limine.conf", current_wallpapers), *wallpaper_sections()]

    def outputs(self, a):
        return outputs(a)


CURRENT = "current"           # --wallpaper current: the wallpaper(s) limine.conf sets
WALLPAPER = ["wallpaper"]     # a wallpaper to recolour
MENU_ONLY = ("only the menu colours change (text, highlight, frame): the wallpaper set in "
             "limine.conf is kept as it is")
OPTIONS = [
    Option("--wallpaper", label="Wallpaper", type=Path, metavar="IMAGE", accept="image", source=True,
           empty=MENU_ONLY,
           help="image to recolour and use as the Limine wallpaper, or 'current' for the "
                "one limine.conf sets (empty: only the menu colours change)"),
    # how the wallpaper is recoloured and shown: only when there is one to recolour
    *recolor.method_options(needs=WALLPAPER),
    Option("--style", label="Wallpaper style", choices=["stretched", "centered", "tiled"], needs=WALLPAPER,
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
    Option("--conf", label="limine.conf file", type=Path, accept="file", stage="apply",
           help="limine.conf to edit (default: searched on the ESP)"),
    Option("--esp", label="ESP folder", type=Path, accept="dir", stage="apply",
           help="ESP mount point (default: ESP_PATH of /etc/default/limine, or /boot)"),
]


def check_args(a):
    check_parts(a, PARTS)
    if (a.install or a.apply) and (len(a.flavor) > 1 or not single(a, PARTS)):
        raise SystemExit("--install / --apply need a single flavour and a single accent "
                         "(-f FLAVOR -a ACCENT)")
    if a.wallpaper and not is_current(a) and not a.wallpaper.is_file():
        raise SystemExit(f"Not found: {a.wallpaper}")


def is_current(a):
    """--wallpaper current (and no file of that name): the wallpaper limine.conf sets."""
    return a.wallpaper is not None and str(a.wallpaper) == CURRENT and not a.wallpaper.exists()


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


# ------------------------------------------------------------- menu preview
# what the menu shows when limine.conf cannot be read (only root can read the ESP)
SAMPLE_CONF = "default_entry: 2\n/+Linux\n//Linux\n//Linux (fallback initramfs)\n"
LIMINE_DEFAULTS = {"interface_branding_colour": "00aaaa", "interface_help_colour": "00aa00",
                   "term_foreground": "aaaaaa", "term_background": "00000000",
                   "backdrop": "000000", "timeout": "5", "editor_enabled": "yes",
                   "term_palette": "000000;aa0000;00aa00;aa5500;0000aa;aa00aa;00aaaa;aaaaaa"}


def screen_size():
    """The resolution of the first connected screen (Limine takes the screen's own),
    else 1920x1080."""
    for f in sorted(Path("/sys/class/drm").glob("card*-*/status")):
        try:
            if f.read_text().strip() == "connected":
                m = re.match(r"(\d+)x(\d+)", (f.parent / "modes").read_text())
                if m:
                    return int(m.group(1)), int(m.group(2))
        except OSError:
            continue
    return 1920, 1080


@lru_cache(maxsize=1)
def default_branding():
    """Limine's own title: "Limine <version> (<arch>, UEFI|BIOS)"."""
    version = ""
    exe = which("limine")
    if exe:
        with contextlib.suppress(OSError, subprocess.SubprocessError):
            out = subprocess.run([exe, "--version"], capture_output=True, text=True,
                                 timeout=5, check=False).stdout
            m = re.match(r"Limine (\S+)", out)
            version = m.group(1) if m else ""
    arch = {"x86_64": "x86-64", "i686": "ia-32", "aarch64": "aarch64", "riscv64": "riscv64",
            "loongarch64": "loongarch64"}.get(platform.machine(), platform.machine())
    firmware = "UEFI" if Path("/sys/firmware/efi").is_dir() else "BIOS"
    return f"Limine{' ' + version if version else ''} ({arch}, {firmware})"


def settings_of(text):
    """The global options of a limine.conf text (before the first entry): {key: value}."""
    out = {}
    for line in text.splitlines():
        if line.lstrip().startswith("/"):
            break
        k, sep, v = line.partition(":")
        if sep and not line.lstrip().startswith("#"):
            out[k.strip().lower().replace("color", "colour")] = v.strip()
    return out


def menu_entries(text):
    """The entries of a limine.conf text: [{depth, name, expanded, comment, dir}]."""
    entries = []
    for line in text.splitlines():
        st = line.strip()
        m = re.match(r"(/+)(\+?)(.*)", st)
        if m and m.group(3).strip():
            entries.append({"depth": len(m.group(1)), "expanded": bool(m.group(2)),
                            "name": m.group(3).strip(), "comment": None, "dir": False})
        elif entries and st.lower().startswith("comment:"):
            entries[-1]["comment"] = st.partition(":")[2].strip()
    for e, nxt in zip(entries, entries[1:]):
        e["dir"] = nxt["depth"] > e["depth"]
    return entries


def tree_lines(entries):
    """The visible entries (inside expanded directories) and their tree prefix, as
    Limine draws them: [(entry, prefix)]."""
    out, ancestors = [], []                  # ancestors: [(entry, is last sibling)]
    for i, e in enumerate(entries):
        d = e["depth"]
        ancestors = ancestors[:d - 1]
        if len(ancestors) < d - 1 or not all(a["expanded"] for a, _ in ancestors):
            ancestors.append((e, True))        # inside a collapsed directory: hidden
            continue
        rest = entries[i + 1:]
        later = next((x["depth"] for x in rest if x["depth"] <= d), 0)
        last = later != d
        guides = "".join("  " if alast else " │" for _, alast in ancestors[1:])
        branch = (" └" if last else " ├") if d > 1 else ""
        marker = ("[-]" if e["expanded"] else "[+]") if e["dir"] else ("──►" if d > 1 else "   ")
        out.append((e, guides + branch + marker))
        ancestors.append((e, last))
    return out


def number(value):
    v = float(value)
    return str(int(v)) if v == int(v) else f"{v:g}"


def menu_screen(theme, conf_text, wallpaper=None, size=None):
    """The Limine menu as it boots: theme (our limine-theme.conf lines) over the
    global options of conf_text (limine.conf, or SAMPLE_CONF), wallpaper (a PIL image,
    or None) shown as wallpaper_style says. Laid out as Limine's menu.c does: the
    branding on row 1, the key help on row 3 (and the secondary help on row 5), the
    entry tree centred, the selected entry in reverse video, its comment and the
    countdown at the bottom."""
    size = size or screen_size()
    st = {**LIMINE_DEFAULTS, **settings_of(conf_text), **settings_of("\n".join(theme))}
    colour = lambda key: hex2rgb(st[key][-6:])                       # noqa: E731
    fg = colour("term_foreground")
    bgv = st["term_background"].rjust(8, "0")
    background = (*hex2rgb(bgv[2:]), int(bgv[:2], 16))
    margin = gradient = 0
    if wallpaper is not None:
        margin, gradient = int(st.get("term_margin", 64)), int(st.get("term_margin_gradient", 4))
        wallpaper = placed(wallpaper, size, st.get("wallpaper_style", "stretched"),
                           colour("backdrop"))
    w, h = size
    auto = 4 if w >= 5120 and h >= 2880 else 2 if w >= 2560 and h >= 1440 else 1
    scale = int(re.match(r"\d+", st.get("term_font_scale", str(auto))).group(0) or auto)
    scr = TextScreen(size, background, fg, wallpaper, margin, gradient, scale,
                     int(st.get("term_font_spacing", 1)))
    cols, rows = scr.cols, scr.rows
    help_c, bright = colour("interface_help_colour"), hex2rgb(
        st.get("interface_help_colour_bright") or "".join(
            f"{min(255, int(st['interface_help_colour'][i:i + 2], 16) + 0x55):02x}" for i in (0, 2, 4)))

    def line(row, parts):
        """parts: [(text, colour)], centred."""
        col = (cols - sum(len(t) for t, _ in parts)) // 2
        for t, c in parts:
            scr.put(col, row, t, c)
            col += len(t)

    branding = st.get("interface_branding") or default_branding()
    header = 2 if branding else 0
    if branding:
        if len(branding) > cols - 2:
            branding = branding[:cols - 5] + "..."
        line(1, [(branding, colour("interface_branding_colour"))])
    editor = st["editor_enabled"] != "no"
    firmware = Path("/sys/firmware/efi").is_dir()
    secondary = editor or firmware
    header += 2 if secondary else 0

    visible = tree_lines(menu_entries(conf_text))
    sel = 0
    with contextlib.suppress(ValueError):
        sel = min(max(int(st.get("default_entry", "1")) - 1, 0), len(visible) - 1)
    if not visible:
        msg = "[config file contains no valid entries]"
        scr.put((cols - len(msg)) // 2, (rows - 1) // 2, msg)
        return scr.image()
    chosen = visible[sel][0]
    if st.get("interface_help_hidden") != "yes":
        row = 1 + header - (2 if secondary else 0)
        if chosen["dir"]:
            act = "Collapse" if chosen["expanded"] else "Expand"
            line(row, [("ARROWS", help_c), (" Select    ", fg), ("ENTER", help_c), (f" {act}", fg)])
        else:
            line(row, [("ARROWS", help_c), (" Select    ", fg), ("ENTER", help_c), (" Boot", fg),
                       *([("    ", fg), ("E", help_c), (" Edit", fg)] if editor else [])])
        if secondary:
            items = ([("S", " Firmware Setup")] if firmware else []) + ([("B", " Blank Entry")] if editor else [])
            parts = []
            for k, (key, label) in enumerate(items):
                parts += [("    ", fg)] * bool(k) + [(key, help_c), (label, fg)]
            line(1 + header, parts)
    height = min(len(visible), rows - 8 - header)
    top = max((rows - height) // 2, 4 + header)
    widest = max(len(pre) + len(e["name"]) for e, pre in visible)
    shift = max(1, (cols - widest - 3) // 2)
    first = max(0, min(sel - height + 1, len(visible) - height)) if sel >= height else 0
    for k, (e, pre) in enumerate(visible[first:first + height]):
        scr.put(shift, top + k, pre)
        name = f" {e['name']} "
        if e is chosen:
            scr.put(shift + len(pre), top + k, name, fg=background[:3], bg=fg)    # reverse video
        else:
            scr.put(shift + len(pre), top + k, name)
    countdown = st["timeout"] not in ("no", "0") and not chosen["dir"]
    if chosen["comment"]:
        teal = hex2rgb(st["term_palette"].split(";")[6]) if st["term_palette"].count(";") >= 6 else fg
        line(rows - 3 if countdown else rows - 2, [(chosen["comment"], teal)])
    if countdown:
        n = number(st["timeout"]) if re.fullmatch(r"[\d.]+", st["timeout"]) else "5"
        line(rows - 2, [("Booting automatically in ", help_c), (n, bright), ("...", help_c)])
    return scr.image()


def placed(wallpaper, size, style, backdrop):
    """The wallpaper on a screen of this size: stretched (default), centered on the
    backdrop colour, or tiled."""
    im = wallpaper.convert("RGB")
    if style == "centered":
        out = Image.new("RGB", size, tuple(backdrop))
        out.paste(im, ((size[0] - im.width) // 2, (size[1] - im.height) // 2))
        return out
    if style == "tiled":
        out = Image.new("RGB", size)
        for y in range(0, size[1], im.height):
            for x in range(0, size[0], im.width):
                out.paste(im, (x, y))
        return out
    return im.resize(size)


def preview(a, esp, theme, src, im, method, grp, dst):
    """--preview: the original wallpaper (if any) | the menu as it boots | (keys) what
    the detection sees. theme: (flavour, accent, wallpaper style). Without
    --wallpaper, the menu is drawn over the wallpaper limine.conf sets, when it can
    be read."""
    conf_text, wall = None, im
    with contextlib.redirect_stdout(io.StringIO()):
        with contextlib.suppress(SystemExit, OSError):
            conf_text = strip_theme(read(a.conf or find_conf(esp)))
    if conf_text is None:
        print("  preview: limine.conf cannot be read (run with sudo to see yours): "
              "sample menu entries")
    current = global_values(conf_text, "wallpaper") if conf_text else []
    if wall is None and current:
        with contextlib.suppress(SystemExit, OSError):
            wall = Image.open(resolve_on_esp(current[0], esp))
    flv, acc, style = theme
    style = style or next(iter(global_values(conf_text or "", "wallpaper_style")), None)
    lines = theme_lines(flv, acc, ["preview"] if src else [], style,
                        over_wallpaper=bool(current) and src is None)
    screen = menu_screen(lines, conf_text or SAMPLE_CONF, wall)
    panels = [screen]
    if src is not None:
        panels.insert(0, Image.open(src).convert("RGB").resize(screen.size))
        if grp is not None and method == "keys":
            sep, legend = recolor.separation_image(src, grp)
            panels.append(recolor.draw_legend(sep.resize(screen.size), legend))
    dst.parent.mkdir(parents=True, exist_ok=True)
    recolor.sheet(panels).save(dst)
    print(f"  preview: {dst}")


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
    if is_current(a):
        if not current:
            raise SystemExit("limine.conf has no wallpaper to recolour (give --wallpaper IMAGE)")
        sources = [resolve_on_esp(w, esp) for w in current]
        for src in sources:
            if not src.is_file():
                raise SystemExit(f"Wallpaper not found on the ESP: {src} (use --esp or --wallpaper)")
    return conf, current, style, sources


def current_wallpapers():
    """The wallpapers limine.conf sets (without the catppuccinizer theme: the one it
    replaced, which is the one to recolour). When only root can read the ESP, one
    item, 'current': the wallpaper is read from limine.conf when the command runs."""
    esp = default_esp()
    if esp.is_dir() and not os.access(esp, os.R_OK | os.X_OK):
        yield item(CURRENT, "Current Limine wallpaper",
                   f"the one set in limine.conf, read when the command runs ({esp} can only "
                   "be read by root: run with sudo)", current=True)
        return
    conf = find_conf(esp)
    for ref in global_values(strip_theme(read(conf)), "wallpaper"):
        f = resolve_on_esp(ref, esp)
        yield item(f, f.name, f"{ref} in {conf}" + ("" if f.is_file() else ", not found"),
                   current=True, thumb=f if f.is_file() else None)


def colours(a):
    """--colours: the menu (fixed roles, nothing to remap) and each wallpaper."""
    sources = wallpapers(a, a.esp or default_esp(), is_current(a))[3]
    return [colour_report("menu", "fixed", part="menu", accent=True,
                          note="Catppuccin roles: text in the flavour's text colour, the title and "
                               "the highlighted help in the accent"),
            *(recolor.colour_report(src, *recolor.plan(src, a, verbose=False), part="wallpaper")
              for src in sources)]


def results(a, plans):
    """core.parts.accent_sets of the menu and the wallpapers (when one uses the accent)."""
    wall = any(recolor.accent_ignored_reason(m, g) is None for m, g in plans)
    using = ["menu", *(["wallpaper"] if wall else [])]
    note_unused(a, using, {"wallpaper": "as no wallpaper is given" if not plans else
                           "as the wallpaper does not use it"})
    return accent_sets(a, using)


def wallpaper_stem(flv, k, n, acc, suffix):
    return output_name(flv, "wallpaper" + (f"-{k + 1}" if n > 1 else ""), acc, suffix)


def outputs(a):
    """Per flavour and accent: the folder, its wallpapers and limine-theme.conf; the
    menu preview with --preview."""
    sources = wallpapers(a, a.esp or default_esp(), is_current(a))[3]
    plans = [recolor.plan(src, a, verbose=False) for src in sources]
    out = []
    with contextlib.redirect_stdout(io.StringIO()):          # notes: the build says them
        sets = results(a, plans)
    for flv in a.flavor:
        for accents, aname in sets:
            dst = a.out / output_name(flv, "limine", aname, a.suffix)
            if a.preview:
                out.append(planned(a.out / "previews" / f"{dst.name}.png"))
                continue
            out.append(planned(dst, folder=True))
            for k, (src, (method, grp)) in enumerate(zip(sources, plans)):
                wacc = None if recolor.accent_ignored_reason(method, grp) else accents["wallpaper"]
                stem = wallpaper_stem(flv, k, len(sources), wacc, a.suffix)
                out.append(planned(dst / (stem + recolor.output_suffix(method, src, opaque=True))))
            out.append(planned(dst / "limine-theme.conf"))
    return out


def build(a):
    """The snippet and wallpapers of each flavour and accent; for the system steps,
    those of the last one (they need a single flavour and accent)."""
    esp = a.esp or default_esp()
    conf, current, style, sources = wallpapers(a, esp, a.apply or is_current(a))
    if not sources:
        print("Menu colours only: the wallpaper set in limine.conf is kept "
              "(--wallpaper IMAGE, or --wallpaper current, recolours one)")
    built = None
    plans = [recolor.plan(src, a) for src in sources]          # analysed once per image
    done = {}       # (image, flavour, accent or None) -> files already written for it
    sets = results(a, plans)
    for flv in a.flavor:
        for accents, aname in sets:
            acc = accents["menu"]
            name = output_name(flv, "limine", aname, a.suffix)
            dst = a.out / name
            if a.preview:            # the first wallpaper: Limine picks one of them at boot
                src, (method, grp) = (sources[0], plans[0]) if sources else (None, (None, None))
                wacc = None if src is None or recolor.accent_ignored_reason(method, grp) \
                    else accents["wallpaper"]
                im = recolor.render(src, method, grp, flv, wacc, a) if src else None
                preview(a, esp, (flv, acc, style), src, im, method, grp,
                        a.out / "previews" / f"{name}.png")
                continue
            dst.mkdir(parents=True, exist_ok=True)
            wall_files = []
            for k, (src, (method, grp)) in enumerate(zip(sources, plans)):
                # a wallpaper that ignores the accent is the same for every accent:
                # rendered once per flavour, named without the accent, copied
                wacc = None if recolor.accent_ignored_reason(method, grp) else accents["wallpaper"]
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
                done[key] = files
                wall_files.append(files[0])
            wall_refs = [f"boot():/{WALL_DIR}/{f.name}" for f in wall_files]
            lines = theme_lines(flv, acc, wall_refs, style,
                                over_wallpaper=bool(current) and not wall_files)
            (dst / "limine-theme.conf").write_text("\n".join(lines) + "\n")
            print(f"Catppuccin {FLAVOR_TITLES[flv]} ({aname}) -> {dst}")
            if not a.apply:
                print(f"  add {dst / 'limine-theme.conf'} to limine.conf, before the first menu entry"
                      + (f", copy {', '.join(f.name for f in wall_files)} to <ESP>/{WALL_DIR}/"
                         if wall_files else "")
                      + ", or rerun with --apply (sudo)")
            built = {"esp": esp, "conf": conf, "lines": lines, "wallpapers": wall_files}
    return None if previewing(a) else built


TARGET = LimineTarget()
