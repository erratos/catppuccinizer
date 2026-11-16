"""File formats: colours written as text (QML, SVG/SVGZ) and animated GIFs."""
import gzip
import re
from collections import Counter

import numpy as np
from PIL import Image, ImageSequence

from .palette import hex2rgb, rgb2hex

RASTER = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
NAMED = {"black": "#000000", "white": "#ffffff", "gray": "#808080", "grey": "#808080"}

# ---------------------------------------------------------------- text colours
SVG_RE = re.compile(r"((?:fill|stroke|stop-color|flood-color|lighting-color|color)\s*[:=]\s*[\"']?)"
                    r"(#[0-9a-fA-F]{8}|#[0-9a-fA-F]{6}|#[0-9a-fA-F]{3}\b|white|black)", re.I)
QML_HEX_RE = re.compile(r"\"(#[0-9a-fA-F]{8}|#[0-9a-fA-F]{6}|#[0-9a-fA-F]{3})\"")
QML_NAMED_RE = re.compile(r"(\b(?:color|[a-zA-Z]*Color)\s*:\s*)\"(black|white|gray|grey)\"")
QML_RGBA_RE = re.compile(r"Qt\.rgba\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*\)")
TEXT_SUFFIXES = {".qml", ".svg", ".svgz"}


def parse_hex(h, qml):
    """'#rgb' / '#rrggbb' / '#aarrggbb' (QML) or '#rrggbbaa' (SVG) -> (rgb hex, alpha hex)."""
    h = h.lstrip("#").lower()
    if len(h) == 3:
        return "#" + "".join(c * 2 for c in h), None
    if len(h) == 8:
        return ("#" + h[2:], h[:2]) if qml else ("#" + h[:6], h[6:])
    return "#" + h, None


def text_files(folder):
    for f in sorted(folder.rglob("*")):
        if f.suffix.lower() in TEXT_SUFFIXES and f.is_file():
            yield f


def read_text(f):
    return gzip.decompress(f.read_bytes()).decode() if f.suffix.lower() == ".svgz" else f.read_text()


def write_text(f, text):
    if f.suffix.lower() == ".svgz":
        f.write_bytes(gzip.compress(text.encode()))
    else:
        f.write_text(text)


def _rgba_hex(m):
    return rgb2hex([float(m.group(i)) * 255 for i in (1, 2, 3)])


def collect_text_colours(files):
    """Counter {#rrggbb: occurrences} over QML / SVG / SVGZ files."""
    counts = Counter()
    for f in files:
        text, qml = read_text(f), f.suffix.lower() == ".qml"
        if qml:
            for m in QML_HEX_RE.finditer(text):
                counts[parse_hex(m.group(1), True)[0]] += 1
            for m in QML_NAMED_RE.finditer(text):
                counts[NAMED[m.group(2).lower()]] += 1
            for m in QML_RGBA_RE.finditer(text):
                counts[_rgba_hex(m)] += 1
        else:
            for m in SVG_RE.finditer(text):
                v = m.group(2).lower()
                counts[NAMED.get(v) or parse_hex(v, False)[0]] += 1
    return counts


def recolour_text(text, qml, lookup):
    """Replace colours in QML (qml=True) or SVG text; lookup: {#src: #new}. Alpha is kept."""
    def sub_hex(h):
        rgbhex, alpha = parse_hex(h, qml)
        new = lookup.get(rgbhex, rgbhex).lstrip("#")
        if alpha is None:
            return "#" + new
        return "#" + (alpha + new if qml else new + alpha)

    if qml:
        text = QML_HEX_RE.sub(lambda m: f'"{sub_hex(m.group(1))}"', text)
        text = QML_NAMED_RE.sub(lambda m: f'{m.group(1)}"{lookup[NAMED[m.group(2).lower()]]}"', text)

        def sub_rgba(m):
            new = hex2rgb(lookup.get(_rgba_hex(m), _rgba_hex(m))) / 255
            return f"Qt.rgba({new[0]:.3f}, {new[1]:.3f}, {new[2]:.3f}, {m.group(4)})"
        return QML_RGBA_RE.sub(sub_rgba, text)

    def sub_svg(m):
        v = m.group(2).lower()
        if v in NAMED:
            return m.group(1) + lookup[NAMED[v]]
        return m.group(1) + sub_hex(v)
    return SVG_RE.sub(sub_svg, text)


def recolour_text_file(f, lookup):
    write_text(f, recolour_text(read_text(f), f.suffix.lower() == ".qml", lookup))


# ------------------------------------------------------------------------ GIF
def gif_frames(path, tmp):
    """Write every (composited) frame as PNG in tmp -> (frame paths, durations, loop)."""
    frames, durations = [], []
    with Image.open(path) as im:
        for k, fr in enumerate(ImageSequence.Iterator(im)):
            f = tmp / f"{path.stem}-{k:04d}.png"
            fr.convert("RGBA").save(f)
            frames.append(f)
            durations.append(fr.info.get("duration", im.info.get("duration", 50)))
        loop = im.info.get("loop", 0)
    return frames, durations, loop


def rgba_to_p(im):
    """RGBA frame -> palette image with a real transparent index (GIF keeps alpha)."""
    alpha = np.asarray(im.getchannel("A"))
    p = im.convert("RGB").quantize(255, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    idx = np.asarray(p).copy()
    idx[alpha < 128] = 255
    out = Image.fromarray(idx, "P")
    pal = p.getpalette()[:765]
    out.putpalette(pal + [0] * (768 - len(pal)))
    out.info["transparency"] = 255
    return out


def save_gif(images, out, durations, loop):
    ims = [rgba_to_p(im.convert("RGBA")) for im in images]
    ims[0].save(out, save_all=True, append_images=ims[1:], duration=durations,
                loop=loop, disposal=2, transparency=255, optimize=False)
