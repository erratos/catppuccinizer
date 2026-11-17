#!/usr/bin/env python3
"""Build the option comparison grids used in docs/ (assets/options-*.jpg).

Each grid shows the same two pictures through several settings: a sunset scene
(the left half of assets/demo-wallpaper-photo.jpg) and a colour chart (every hue
from dark to light, plus a gray ramp), so the effect of an option on each kind
of colour can be seen at a glance.

    python3 tools/doc_previews.py            # all grids (lutgen ones need lutgen)
    python3 tools/doc_previews.py lut keep-lum
"""
import argparse
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

ASSETS = ROOT / "assets"
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
    p = argparse.ArgumentParser()
    recolor.add_method_arguments(p)
    a = p.parse_args([])
    a.map = []
    for k, v in kw.items():
        setattr(a, k, v)
    return a


def flat():
    im = Image.open(ASSETS / "demo-wallpaper-flat.jpg").convert("RGB")
    left = im.crop((0, 0, (im.width - 6) // 2, im.height))
    return left.resize((480, 270), Image.LANCZOS)


def render(src, method, flavor, a):
    if method == "original":
        return Image.open(src).convert("RGB")
    if method == "keys":
        a.method = "keys"
        m, grp = recolor.plan(src, a, verbose=False)
        im = recolor.render(src, m, grp, flavor, "mauve", a).convert("RGBA")
        bg = Image.new("RGBA", im.size, BG + (255,))
        bg.alpha_composite(im)
        return bg.convert("RGB")
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
            im = render(src, method, flavor, a).resize((tw, th), Image.LANCZOS)
            sheet.paste(im, (x, title_h + LABEL_H + j * (th + GAP)))
    out = ASSETS / f"options-{name}.jpg"
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
        files = {"scene": scene(), "chart": chart(), "flat": flat()}
        paths = {}
        for k, im in files.items():
            paths[k] = Path(d) / f"{k}.png"
            im.save(paths[k])
        for name in names:
            title, cols = GRIDS[name]
            rows = ["flat", "scene"] if name == "method" else ["scene", "chart"]
            grid(name, title, cols, [paths[r] for r in rows])


if __name__ == "__main__":
    main()
