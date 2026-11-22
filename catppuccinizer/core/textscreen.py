"""A text screen as a boot menu draws it: a grid of character cells in an 8x16
bitmap font over a background (the canvas), for previews of boot menus (Limine).

The font is the system's VGA console font (kbd's default8x16, a PSF file), the
closest to what boot loaders build in; without it, Pillow's own font stands in.

The canvas follows Limine's terminal (flanterm, gterm): with a wallpaper, a
margin around the text area shows the plain wallpaper, a band of `gradient`
pixels inside it fades from the wallpaper to the terminal background, and the
text area is the background blended over the wallpaper (its alpha byte is a
transparency: 0 = opaque, 255 = see-through). Without a wallpaper, the whole
screen is the background colour. A cell with no colour of its own shows the
canvas; text is drawn in the cell's foreground colour.
"""
import gzip
import struct
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

CONSOLE_FONTS = [Path("/usr/share/kbd/consolefonts/default8x16.psfu.gz"),
                 Path("/usr/share/kbd/consolefonts/default8x16.psf.gz"),
                 Path("/usr/share/consolefonts/default8x16.psfu.gz")]
FONT_W, FONT_H = 8, 16


def read_psf(data):
    """A PSF1 / PSF2 font of 8-pixel-wide glyphs -> {character: 16x8 bool array}
    (glyph order is code page 437 when the file has no Unicode table)."""
    if data[:2] == b"\x36\x04":
        mode, height = data[2], data[3]
        count, start, width = (512 if mode & 1 else 256), 4, 8
        has_table = bool(mode & 6)
    elif data[:4] == b"\x72\xb5\x4a\x86":
        _, start, flags, count, _, height, width = struct.unpack("<7I", data[4:32])
        has_table = bool(flags & 1)
    else:
        raise ValueError("not a PSF font")
    if width != FONT_W or height != FONT_H:
        raise ValueError(f"a {width}x{height} font, not {FONT_W}x{FONT_H}")
    size = height * ((width + 7) // 8)
    raw = np.frombuffer(data[start:start + count * size], np.uint8).reshape(count, height)
    glyphs = np.unpackbits(raw[:, :, None], axis=2).astype(bool)          # (count, 16, 8)
    table = {}
    if not has_table:
        for i in range(min(count, 256)):
            table[bytes([i]).decode("cp437")] = glyphs[i]
        return table
    pos = start + count * size
    if data[:2] == b"\x36\x04":            # UCS-2 entries, 0xFFFF ends a glyph's list
        codes = np.frombuffer(data[pos:pos + (len(data) - pos) // 2 * 2], "<u2")
        g, seq = 0, False
        for c in codes:
            if c == 0xFFFF:
                g, seq = g + 1, False
            elif c == 0xFFFE:
                seq = True
            elif not seq and g < count:
                table.setdefault(chr(c), glyphs[g])
    else:                                  # UTF-8 entries, 0xFF ends a glyph's list
        for g, entry in enumerate(data[pos:].split(b"\xff")[:count]):
            single = entry.split(b"\xfe")[0]
            for ch in single.decode("utf-8", "ignore"):
                table.setdefault(ch, glyphs[g])
    return table


@lru_cache(maxsize=1)
def console_font():
    """{character: 16x8 bool array}: the system's VGA console font, else None."""
    for f in CONSOLE_FONTS:
        try:
            data = f.read_bytes()
            return read_psf(gzip.decompress(data) if f.suffix == ".gz" else data)
        except (OSError, ValueError, EOFError):
            continue
    return None


@lru_cache(maxsize=512)
def fallback_glyph(ch):
    """A glyph drawn with Pillow's font, when there is no console font."""
    im = Image.new("L", (FONT_W, FONT_H), 0)
    ImageDraw.Draw(im).text((0, 1), ch, fill=255, font=ImageFont.load_default(size=13))
    return np.asarray(im) > 96


def glyph(ch):
    font = console_font()
    if font is None:
        return fallback_glyph(ch)
    return font.get(ch, font.get("?"))


def canvas(size, background, wallpaper=None, margin=0, gradient=0):
    """The screen behind the text: background = (r, g, b, transparency)."""
    w, h = size
    bg = np.array(background[:3], np.float32)
    if wallpaper is None:
        return np.broadcast_to(bg, (h, w, 3)).copy()
    wall = np.asarray(wallpaper.convert("RGB").resize(size), np.float32)
    gradient = min(gradient, margin)
    ys, xs = np.mgrid[0:h, 0:w]
    dx = np.maximum(np.maximum(margin - xs, xs - (w - margin - 1)), 0)
    dy = np.maximum(np.maximum(margin - ys, ys - (h - margin - 1)), 0)
    dist = np.sqrt(dx.astype(np.float32) ** 2 + dy ** 2)
    a = float(background[3])
    step = (255 - a) / gradient if gradient else 0
    t = np.where(dist == 0, a, np.where(dist <= gradient, a + step * dist, 255))[..., None]
    return bg * (255 - t) / 255 + wall * t / 255


class TextScreen:
    """Character cells over a canvas (see canvas()); put() writes text, image() draws it."""

    def __init__(self, size, background, foreground, wallpaper=None, margin=0, gradient=0,
                 scale=1, spacing=1):
        self.size, self.scale = size, scale
        self.fg = tuple(foreground)
        self.cell = ((FONT_W + spacing) * scale, FONT_H * scale)
        self.cols = (size[0] - 2 * margin) // self.cell[0]
        self.rows = (size[1] - 2 * margin) // self.cell[1]
        # the grid is centred in the area inside the margin
        self.origin = (margin + (size[0] - 2 * margin) % self.cell[0] // 2,
                       margin + (size[1] - 2 * margin) % self.cell[1] // 2)
        self.pixels = canvas(size, background, wallpaper, margin, gradient)
        self.cells = {}

    def put(self, col, row, text, fg=None, bg=None):
        """text from (col, row), clipped to the screen; bg None: the canvas shows."""
        for i, ch in enumerate(text):
            if 0 <= col + i < self.cols and 0 <= row < self.rows:
                self.cells[(col + i, row)] = (ch, self.fg if fg is None else tuple(fg),
                                              None if bg is None else tuple(bg))

    def image(self):
        px = self.pixels.copy()
        cw, chh = self.cell
        for (c, r), (ch, fg, bg) in self.cells.items():
            x, y = self.origin[0] + c * cw, self.origin[1] + r * chh
            if bg is not None:
                px[y:y + chh, x:x + cw] = bg
            g = glyph(ch)
            if g is None or ch == " ":
                continue
            mask = np.kron(g, np.ones((self.scale, self.scale), bool))
            px[y:y + mask.shape[0], x:x + mask.shape[1]][mask] = fg
        return Image.fromarray(np.clip(px + 0.5, 0, 255).astype(np.uint8), "RGB")
