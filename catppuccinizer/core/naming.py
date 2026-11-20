"""Output names, the same for every target:

    catppuccin-<flavour>-<source>[-<accent>][-<suffix>]

- source: what was recoloured (image file name, theme, splash screen, "limine",
  "lut"…), reduced to lowercase letters, digits and "-" (what Plymouth accepts
  in a theme name, and safe everywhere else);
- accent: only when the output uses it (None otherwise), so one output per
  flavour when the accent has no effect;
- suffix: --suffix, same characters as the source.
"""
import argparse
import re
import unicodedata

SAFE = re.compile(r"[a-z0-9-]+")


def slug(text, default="x"):
    """'Été 2024.png' -> 'ete-2024-png': lowercase ASCII letters, digits and '-'."""
    ascii_text = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-") or default


def output_name(flavor, source, accent=None, suffix=""):
    """catppuccin-<flavour>-<source>[-<accent>][-<suffix>] (no extension)."""
    return "-".join(x for x in ("catppuccin", flavor, slug(source), accent, suffix) if x)


def suffix_type(value):
    """argparse type of --suffix (core.options.COMMON)."""
    if value and not SAFE.fullmatch(value):
        raise argparse.ArgumentTypeError("use lowercase letters, digits and '-'")
    return value



# a theme / package name that goes into a system path (/usr/share/plymouth/themes/<name>)
# or a system command: no "/", no "..", no leading "-" or "."
NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,127}")


def check_name(name, what="name"):
    """name itself if it is safe in a system path or command, else SystemExit."""
    if not isinstance(name, str) or not NAME.fullmatch(name) or ".." in name:
        raise SystemExit(f"Invalid {what}: {name!r} (letters, digits, '.', '_', '+', '-'; "
                         "no '/' or '..')")
    return name
