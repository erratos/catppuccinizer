#!/usr/bin/env python3
"""Generate Catppuccin Mocha adaptations of adi1090x's Plymouth themes.

- hexa_retro      -> themes/catppuccin-mocha-hexa-retro
- infinite_seal   -> themes/catppuccin-mocha-infinite-seal-<accent> (one per accent)
+ for every theme, a "-status" variant (progress bar + latest systemd services
  under the animation, see extras.script)

Usage: python3 generate.py [path/to/plymouth-themes/pack_3]
If no path is given, the upstream themes are fetched into upstream/ with git.
"""
import re
import shutil
import subprocess
import sys
from multiprocessing import Pool
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent
SRC = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "upstream/plymouth-themes/pack_3"
OUT = ROOT / "themes"
INSTALL_DIR = "/usr/share/plymouth/themes"
UPSTREAM_REPO = "https://github.com/adi1090x/plymouth-themes.git"


def fetch_upstream():
    """Sparse-clone only the two source themes from adi1090x/plymouth-themes."""
    if SRC.exists():
        return
    repo = ROOT / "upstream/plymouth-themes"
    print(f"Fetching {UPSTREAM_REPO} ...", flush=True)
    repo.parent.mkdir(exist_ok=True)
    subprocess.run(["git", "clone", "--depth", "1", "--filter=blob:none", "--sparse",
                    UPSTREAM_REPO, str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "sparse-checkout", "set",
                    "pack_3/infinite_seal", "pack_3/hexa_retro"], check=True)

# Catppuccin Mocha palette
MOCHA = {
    "rosewater": "#f5e0dc", "flamingo": "#f2cdcd", "pink": "#f5c2e7",
    "mauve": "#cba6f7", "red": "#f38ba8", "maroon": "#eba0ac",
    "peach": "#fab387", "yellow": "#f9e2af", "green": "#a6e3a1",
    "teal": "#94e2d5", "sky": "#89dceb", "sapphire": "#74c7ec",
    "blue": "#89b4fa", "lavender": "#b4befe",
    "text": "#cdd6f4", "subtext0": "#a6adc8", "overlay1": "#7f849c",
    "surface0": "#313244", "base": "#1e1e2e",
}
ACCENTS = ["rosewater", "flamingo", "pink", "mauve", "red", "maroon", "peach",
           "yellow", "green", "teal", "sky", "sapphire", "blue", "lavender"]


def rgb(name):
    h = MOCHA[name].lstrip("#")
    return np.array([int(h[i:i + 2], 16) for i in (0, 2, 4)], dtype=np.float32)


BASE = rgb("base")

# hexa_retro: original colour (full intensity) -> Mocha colour
HEXA_MAP = [
    ((246, 255, 239), "text"),    # white
    ((251, 66, 99), "red"),       # red
    ((255, 173, 3), "yellow"),    # yellow
    ((68, 171, 204), "blue"),     # blue
    ((96, 234, 221), "teal"),     # cyan (light blue)
]

HEXA_BAR_ACCENT = "blue"   # progress bar colour for hexa_retro


# ---------------------------------------------------------------- recoloration
def recolor_hexa(src, dst):
    """Each pixel ~ t * key_colour over black: find the closest key and its
    intensity t, then rebuild it as t * target over the Mocha base."""
    px = np.asarray(Image.open(src).convert("RGB"), dtype=np.float32)
    flat = px.reshape(-1, 3)
    keys = np.array([k for k, _ in HEXA_MAP], dtype=np.float32)
    targets = np.array([rgb(n) for _, n in HEXA_MAP])
    # project every pixel on every key vector
    t = (flat @ keys.T) / (keys ** 2).sum(1)            # (N, K)
    t = np.clip(t, 0, 1)
    resid = ((flat[:, None, :] - t[..., None] * keys[None]) ** 2).sum(-1)
    best = resid.argmin(1)
    tb = t[np.arange(len(flat)), best][:, None]
    out = BASE + tb * (targets[best] - BASE)
    save(out.reshape(px.shape), dst)


def recolor_mono(src, dst, accent):
    """White on black: intensity -> blend between Mocha base and accent."""
    px = np.asarray(Image.open(src).convert("RGB"))
    # indexed PNG: index = intensity, palette = base -> accent gradient (lossless)
    idx = px.max(-1).astype(np.uint8)
    t = np.arange(256, dtype=np.float32)[:, None] / 255.0
    pal = np.clip(BASE + t * (accent - BASE) + 0.5, 0, 255).astype(np.uint8)
    im = Image.fromarray(idx, "P")
    im.putpalette(pal.flatten().tolist())
    im.save(dst, optimize=True)


def save(arr, dst):
    im = Image.fromarray(np.clip(arr + 0.5, 0, 255).astype(np.uint8), "RGB")
    im.quantize(256, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE).save(dst, optimize=True)


# -------------------------------------------------------------------- scripts
def patch_script(text):
    """Mocha base for the whole window + Mocha `text` colour for messages."""
    b = BASE / 255
    t = rgb("text") / 255
    bg = (f"// Catppuccin Mocha background\n"
          f"Window.SetBackgroundTopColor({b[0]:.3f}, {b[1]:.3f}, {b[2]:.3f});\n"
          f"Window.SetBackgroundBottomColor({b[0]:.3f}, {b[1]:.3f}, {b[2]:.3f});\n\n")
    text = text.replace("// Screen size", bg + "// Screen size", 1)
    return text.replace(", 1, 1, 1)", f", {t[0]:.3f}, {t[1]:.3f}, {t[2]:.3f})")


def write_theme(src_dir, name, desc, dst_dir):
    old = src_dir.name
    dst_dir.mkdir(parents=True, exist_ok=True)
    script = patch_script((src_dir / f"{old}.script").read_text())
    (dst_dir / f"{name}.script").write_text(script)
    conf = (src_dir / f"{old}.plymouth").read_text()
    conf = re.sub(r"^Name=.*$", f"Name={name}", conf, flags=re.M)
    conf = re.sub(r"^Description=.*$", f"Description={desc}", conf, flags=re.M)
    conf = re.sub(r"^Comment=.*$",
                  "Comment=Catppuccin Mocha adaptation of a theme by Aditya Shakya (@adi1090x)",
                  conf, flags=re.M)
    conf = conf.replace(f"/{old}/{old}.script", f"/{name}/{name}.script")
    conf = conf.replace(f"{INSTALL_DIR}/{old}", f"{INSTALL_DIR}/{name}")
    (dst_dir / f"{name}.plymouth").write_text(conf)
    shutil.copy(src_dir / "LICENSE", dst_dir / "LICENSE")


def color_args(name):
    c = rgb(name) / 255
    return f"{c[0]:.3f}, {c[1]:.3f}, {c[2]:.3f}"


def write_status_variant(base_dir, accent, bar_frac, bar_gap):
    """"-status" variant: same frames + progress bar + latest services."""
    name = base_dir.name + "-status"
    dst = OUT / name
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(base_dir, dst)
    base = base_dir.name
    # rename script / config and update paths
    (dst / f"{base}.script").rename(dst / f"{name}.script")
    conf = (dst / f"{base}.plymouth").read_text().replace(base, name)
    conf = re.sub(r"^Description=(.*)$", r"Description=\1 (progress + status)", conf, flags=re.M)
    (dst / f"{name}.plymouth").write_text(conf)
    (dst / f"{base}.plymouth").unlink()

    extras = ((ROOT / "extras.script").read_text()
              .replace("@SUBTEXT@", color_args("subtext0"))
              .replace("@OVERLAY@", color_args("overlay1"))
              .replace("@BARFRAC@", str(bar_frac))
              .replace("@BARGAP@", str(bar_gap)))
    with open(dst / f"{name}.script", "a") as f:
        f.write(extras)

    for fname, col in (("bar-track.png", "surface0"), ("bar-fill.png", accent)):
        Image.new("RGB", (1, 1), tuple(int(v) for v in rgb(col))).save(dst / fname)


def frames(d):
    return sorted(d.glob("progress-*.png"), key=lambda p: int(p.stem.split("-")[1]))


def _job(args):
    kind, src, dst, accent = args
    if kind == "hexa":
        recolor_hexa(src, dst)
    else:
        recolor_mono(src, dst, accent)


def main():
    fetch_upstream()
    jobs = []

    src = SRC / "hexa_retro"
    name = "catppuccin-mocha-hexa-retro"
    write_theme(src, name, "Retro styled hexagons - Catppuccin Mocha", OUT / name)
    jobs += [("hexa", f, OUT / name / f.name, None) for f in frames(src)]

    src = SRC / "infinite_seal"
    for acc in ACCENTS:
        name = f"catppuccin-mocha-infinite-seal-{acc}"
        write_theme(src, name, f"Infinite style seal - Catppuccin Mocha {acc}", OUT / name)
        jobs += [("mono", f, OUT / name / f.name, rgb(acc)) for f in frames(src)]

    with Pool() as pool:
        for i, _ in enumerate(pool.imap_unordered(_job, jobs, chunksize=8), 1):
            if i % 500 == 0 or i == len(jobs):
                print(f"{i}/{len(jobs)} images", flush=True)

    # variants with progress bar + systemd status
    write_status_variant(OUT / "catppuccin-mocha-hexa-retro", HEXA_BAR_ACCENT, 0.5, 20)
    for acc in ACCENTS:
        write_status_variant(OUT / f"catppuccin-mocha-infinite-seal-{acc}", acc, 0.4, 0)
    print("-status variants written")


if __name__ == "__main__":
    main()
