"""Ready-made sources a target offers (Target.sources()): the GUI's catalogue and
`--list` on the command line.

sources() returns sections, each with its items:

    [{"section": "Installed (/usr/share/plymouth/themes)", "items": [item, ...]},
     {"section": "adi1090x themes", "items": [], "error": "git: not found"}]

An item (item()) is {"value", "label", "note", "current", "thumb"}: value is what
goes into the source argument (a path or a name), current marks what the
system uses now (the active theme), thumb is an image or folder the GUI shows.
A section is made with section(), which turns a failure into its "error": one
section that cannot be read (no network, an ESP only root can read) does not
hide the others.
"""
import json
import os
import re
from pathlib import Path

from .paths import user_home

IMAGES = {".png", ".jpg", ".jpeg", ".webp"}
MAX_ITEMS = 500                 # per section


def item(value, label=None, note="", current=False, thumb=None):
    return {"value": str(value), "label": label or str(value), "note": note or "",
            "current": bool(current), "thumb": str(thumb) if thumb else None}


def section(title, make):
    """{"section": title, "items": make()}, or the error make() raised (a message,
    not a traceback: the GUI shows it in the section, --list prints it)."""
    try:
        return {"section": title, "items": list(make())[:MAX_ITEMS]}
    except (SystemExit, Exception) as e:         # noqa: BLE001 - shown to the user
        msg = e.code if isinstance(e, SystemExit) else str(e)
        return {"section": title, "items": [], "error": str(msg or type(e).__name__)}


def format_sources(sections):
    """The text of --list: a heading per section, '*' before what is in use."""
    lines = []
    for sec in sections:
        if not sec["items"] and not sec.get("error"):
            continue
        lines.append(sec["section"])
        if sec.get("error"):
            lines.append(f"  ({sec['error']})")
        for it in sec["items"]:
            extra = "  ".join(x for x in (it["label"] if it["label"] != it["value"] else "",
                                          f"({it['note']})" if it["note"] else "") if x)
            lines.append(f"  {'*' if it['current'] else ' '} {it['value']}" + (f"  {extra}" if extra else ""))
        lines.append("")
    return "\n".join(lines).rstrip() or "Nothing found."


def tidy(path):
    """~/… for a path in the user's home."""
    try:
        return "~/" + str(Path(path).relative_to(user_home()))
    except ValueError:
        return str(path)


# --------------------------------------------------------------- wallpapers
def wallpaper_dirs():
    return [("System wallpapers", Path("/usr/share/wallpapers")),
            ("Backgrounds", Path("/usr/share/backgrounds")),
            ("Your wallpapers", user_home() / ".local/share/wallpapers")]


def wallpaper_sections():
    """One section per wallpaper folder that exists (image, limine)."""
    return [section(f"{title} ({tidy(d)})", lambda d=d: wallpapers(d))
            for title, d in wallpaper_dirs() if d.is_dir()]


def package_label(pkg):
    """Name of a KDE wallpaper package (metadata.json, or metadata.desktop)."""
    try:
        return json.loads((pkg / "metadata.json").read_text())["KPlugin"]["Name"]
    except (OSError, KeyError, ValueError, TypeError):
        pass
    try:
        m = re.search(r"^Name=(.+)$", (pkg / "metadata.desktop").read_text(), re.M)
        if m:
            return m.group(1).strip()
    except OSError:
        pass
    return pkg.name


def largest_image(folder):
    """The largest image of a KDE package's contents/images (1920x1080.jpg,
    3840x2160.png…): by the size in its name, else by file size."""
    def size(f):
        m = re.match(r"(\d+)x(\d+)", f.stem)
        return (int(m.group(1)) * int(m.group(2)) if m else 0, f.stat().st_size)
    imgs = [f for f in folder.iterdir() if f.suffix.lower() in IMAGES and f.is_file()]
    return max(imgs, key=size) if imgs else None


def wallpapers(base, depth=3):
    """Items of the images under base: loose files, and KDE wallpaper packages
    (a folder with contents/images/: its largest image, named after the package)."""
    base = Path(base)
    for dirpath, dirnames, filenames in os.walk(base):
        d = Path(dirpath)
        rel = d.relative_to(base)
        where = str(rel.parent if (d / "contents/images").is_dir() else rel)
        where = "" if where == "." else where
        if (d / "contents/images").is_dir():
            img = largest_image(d / "contents/images")
            if img:
                shot = next((s for s in (d / "contents").glob("screenshot.*")
                             if s.suffix.lower() in IMAGES), img)
                yield item(img, package_label(d), " · ".join(x for x in (where, "KDE package") if x),
                           thumb=shot)
            dirnames.clear()
            continue
        dirnames[:] = sorted(n for n in dirnames if not n.startswith(".")) if len(rel.parts) < depth else []
        for f in sorted(filenames):
            if Path(f).suffix.lower() in IMAGES and not f.startswith("."):
                yield item(d / f, Path(f).stem, where, thumb=d / f)
