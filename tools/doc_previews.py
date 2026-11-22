#!/usr/bin/env python3
"""Build the option comparison grids used in docs/ and the GUI
(catppuccinizer/assets/options-*.jpg, package data).

Each grid shows the same two pictures through several settings: a sunset scene
(the left half of assets/demo-wallpaper-photo.jpg) and a colour chart (every hue
from dark to light, plus a gray ramp), so the effect of an option on each kind
of colour can be seen at a glance.

    python3 tools/doc_previews.py            # all grids (lutgen ones need lutgen)
    python3 tools/doc_previews.py lut keep-lum
"""
import colorsys
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from catppuccinizer.core import recolor  # noqa: E402
from catppuccinizer.core.options import defaults  # noqa: E402

ASSETS = ROOT / "assets"                     # the demo pictures
OPTION_IMAGES = ROOT / "catppuccinizer/assets"
WIDTH = 1000                 # total grid width
GAP = 6
LABEL_H = 30
BG = (30, 30, 46)            # Mocha base
FG = (205, 214, 244)         # Mocha text
SUB = (166, 173, 200)        # Mocha subtext0


def font(size, bold=False):
    try:
        name = "DejaVu Sans:bold" if bold else "DejaVu Sans"
        path = subprocess.run(["fc-match", "-f", "%{file}", name],
                              capture_output=True, text=True).stdout
        return ImageFont.truetype(path, size)
    except Exception:
        return ImageFont.load_default(size)


def chart(w=480, h=270):
    """Hue across, light -> dark down, then a gray ramp at the bottom."""
    img = np.zeros((h, w, 3), np.uint8)
    gray_h = h // 6
    for y in range(h - gray_h):
        light = 0.88 - 0.78 * y / (h - gray_h - 1)
        for x in range(w):
            r, g, b = colorsys.hls_to_rgb(x / w, light, 1.0)
            img[y, x] = (r * 255, g * 255, b * 255)
    ramp = np.linspace(0, 255, w).astype(np.uint8)
    img[h - gray_h:] = ramp[None, :, None]
    return Image.fromarray(img)


def scene():
    im = Image.open(ASSETS / "demo-wallpaper-photo.jpg").convert("RGB")
    left = im.crop((0, 0, (im.width - 6) // 2, im.height))
    return left.resize((480, 270), Image.LANCZOS)


def options(**kw):
    return defaults(recolor.method_options(), map=[], **kw)


def flat():
    im = Image.open(ASSETS / "demo-wallpaper-flat.jpg").convert("RGB")
    left = im.crop((0, 0, (im.width - 6) // 2, im.height))
    return left.resize((480, 270), Image.LANCZOS)


def poster(w=480, h=270):
    """Flat art with faint and dark parts: a yellow sun on an orange sky (close
    colours), white clouds (far more contrasted) and hills darker than the sky."""
    im = Image.new("RGB", (w, h), (240, 120, 30))
    d = ImageDraw.Draw(im)
    d.ellipse((60, 50, 170, 160), fill=(250, 205, 60))
    for x, y in ((250, 50), (330, 85), (200, 110)):
        d.rounded_rectangle((x, y, x + 110, y + 26), radius=13, fill=(255, 255, 255))
    d.polygon([(0, h), (0, 200), (120, 160), (260, 215), (380, 170), (w, 205), (w, h)],
              fill=(110, 40, 15))
    return im


def render(src, method, flavor, a, mode="result"):
    if method == "original":
        return Image.open(src).convert("RGB")
    if method == "keys":
        a.method = "keys"
        m, grp = recolor.plan(src, a, verbose=False)
        if mode == "separation":
            im, legend = recolor.separation_image(src, grp)
            return recolor.draw_legend(im, legend)
        im = recolor.render(src, m, grp, flavor, "mauve", a).convert("RGBA")
        bg = Image.new("RGBA", im.size, BG + (255,))
        bg.alpha_composite(im)
        return bg.convert("RGB")
    if method == "lut-accent":
        cube = recolor.lut_for(method, flavor, a, accent=a.accent[0], hue=recolor.dominant_hue(src))
        return recolor.recolor_lut(src, cube).convert("RGB")
    return recolor.recolor_lut(src, recolor.lut_for(method, flavor, a)).convert("RGB")


def grid(name, title, columns, sources):
    """columns: [(label, sublabel, method, flavor, options)]"""
    n = len(columns)
    tw = (WIDTH - GAP * (n + 1)) // n
    th = tw * 270 // 480
    title_h = 40
    H = title_h + LABEL_H + len(sources) * (th + GAP) + GAP
    sheet = Image.new("RGB", (WIDTH, H), BG)
    d = ImageDraw.Draw(sheet)
    d.text((GAP + 4, 12), title, font=font(17, bold=True), fill=FG)
    f, fs = font(14, bold=True), font(12)
    for i, (label, sub, method, flavor, a) in enumerate(columns):
        x = GAP + i * (tw + GAP)
        d.text((x + 2, title_h), label, font=f, fill=FG)
        if sub:
            lw = d.textlength(label, font=f)
            d.text((x + lw + 10, title_h + 2), sub, font=fs, fill=SUB)
        for j, src in enumerate(sources):
            src, mode = src if isinstance(src, tuple) else (src, "result")
            if mode == "separation" and method == "original":
                im = Image.new("RGB", (tw, th), BG)
                ImageDraw.Draw(im).text((12, th // 2 - 20), "what keys sees:\none plain colour\n"
                                        "per source colour", font=font(14), fill=SUB)
            else:
                im = render(src, method, flavor, a, mode).resize((tw, th), Image.LANCZOS)
            sheet.paste(im, (x, title_h + LABEL_H + j * (th + GAP)))
    out = OPTION_IMAGES / f"options-{name}.jpg"
    sheet.save(out, quality=88, optimize=True, progressive=True)
    print(out.relative_to(ROOT), sheet.size, f"{out.stat().st_size // 1024} KB")


def O(**kw):
    return options(**kw)


GRIDS = {
    "method": ("--method: keys for flat art, lut for photos (Mocha)", [
        ("original", "", "original", "mocha", O()),
        ("keys", "--method keys", "keys", "mocha", O()),
        ("lut", "--method lut", "lut", "mocha", O()),
    ]),
    "separation": ("--separation: how source colours are told apart (keys, Mocha)", [
        ("original", "", "original", "mocha", O()),
        ("0.5", "default", "keys", "mocha", O(separation=0.5)),
        ("0.6", "", "keys", "mocha", O(separation=0.6)),
        ("0.8", "", "keys", "mocha", O(separation=0.8)),
    ]),
    "lut-accent": ("lut vs lut-accent: the dominant hue takes the accent (Mocha)", [
        ("original", "", "original", "mocha", O()),
        ("lut", "any accent", "lut", "mocha", O()),
        ("lut-accent", "-a mauve", "lut-accent", "mocha", O(accent=["mauve"])),
        ("lut-accent", "-a green", "lut-accent", "mocha", O(accent=["green"])),
    ]),
    "lut": ("Built-in lut vs lutgen (Mocha, default settings)", [
        ("original", "", "original", "mocha", O()),
        ("lut", "--method lut", "lut", "mocha", O()),
        ("lutgen", "--method lutgen", "lutgen", "mocha", O()),
    ]),
    "flavors": ("Flavours (-f), lut method", [
        ("latte", "", "lut", "latte", O()),
        ("frappe", "", "lut", "frappe", O()),
        ("macchiato", "", "lut", "macchiato", O()),
        ("mocha", "", "lut", "mocha", O()),
    ]),
    "keep-lum": ("--keep-lum: how much of the original lightness is kept (lut)", [
        ("original", "", "original", "mocha", O()),
        ("0", "palette", "lut", "mocha", O(keep_lum=0.0)),
        ("0.5", "default", "lut", "mocha", O(keep_lum=0.5)),
        ("1", "original", "lut", "mocha", O(keep_lum=1.0)),
    ]),
    "smooth": ("--smooth: how much neighbouring accents blend (lut)", [
        ("original", "", "original", "mocha", O()),
        ("0.02", "pure accents", "lut", "mocha", O(smooth=0.02)),
        ("0.08", "default", "lut", "mocha", O(smooth=0.08)),
        ("0.25", "soft", "lut", "mocha", O(smooth=0.25)),
    ]),
    "chroma": ("--chroma: how colourful a colour must be to take its accent (lut)", [
        ("original", "", "original", "mocha", O()),
        ("0.04", "colourful", "lut", "mocha", O(chroma=0.04)),
        ("0.1", "default", "lut", "mocha", O(chroma=0.1)),
        ("0.25", "muted", "lut", "mocha", O(chroma=0.25)),
    ]),
    "dark-fade": ("--dark-fade: how much dark colours lose their accent (lut)", [
        ("original", "", "original", "mocha", O()),
        ("0", "no fade", "lut", "mocha", O(dark_fade=0.0)),
        ("0.75", "default", "lut", "mocha", O(dark_fade=0.75)),
        ("1.5", "gray shadows", "lut", "mocha", O(dark_fade=1.5)),
    ]),
    "lutgen-algo": ("--lutgen-algo: interpolation algorithm (lutgen, defaults)", [
        ("blur", "default", "lutgen", "mocha", O(method="lutgen")),
        ("rbf", "", "lutgen", "mocha", O(lutgen_algo="rbf")),
        ("shepard", "", "lutgen", "mocha", O(lutgen_algo="shepard")),
        ("sampling", "", "lutgen", "mocha", O(lutgen_algo="sampling")),
        ("nearest", "", "lutgen", "mocha", O(lutgen_algo="nearest")),
    ]),
    "lutgen-lum": ("--lutgen-preserve and --lutgen-lum (lutgen, blur)", [
        ("default", "", "lutgen", "mocha", O()),
        ("--preserve", "", "lutgen", "mocha", O(lutgen_preserve=True)),
        ("--lum 0.5", "+ preserve", "lutgen", "mocha", O(lutgen_preserve=True, lutgen_lum=0.5)),
        ("--lum 2", "+ preserve", "lutgen", "mocha", O(lutgen_preserve=True, lutgen_lum=2.0)),
    ]),
    "lutgen-blend": ("How much palette colours blend: one knob per algorithm (lutgen)", [
        ("--radius 2", "blur", "lutgen", "mocha", O(lutgen_radius=2.0)),
        ("--radius 24", "blur", "lutgen", "mocha", O(lutgen_radius=24.0)),
        ("--shape 16", "rbf", "lutgen", "mocha", O(lutgen_algo="rbf", lutgen_shape=16.0)),
        ("--shape 512", "rbf", "lutgen", "mocha", O(lutgen_algo="rbf", lutgen_shape=512.0)),
    ]),
}


def main():
    names = sys.argv[1:] or list(GRIDS)
    with tempfile.TemporaryDirectory() as d:
        files = {"scene": scene(), "chart": chart(), "flat": flat(), "poster": poster()}
        paths = {}
        for k, im in files.items():
            paths[k] = Path(d) / f"{k}.png"
            im.save(paths[k])
        for name in names:
            title, cols = GRIDS[name]
            rows = {"method": [paths["flat"], paths["scene"]],
                    "separation": [paths["poster"], (paths["poster"], "separation")],
                    "lut-accent": [paths["scene"], paths["flat"]]}
            grid(name, title, cols, rows.get(name, [paths["scene"], paths["chart"]]))


if __name__ == "__main__":
    main()
