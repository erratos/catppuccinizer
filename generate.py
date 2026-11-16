#!/usr/bin/env python3
"""Generate Catppuccin adaptations of adi1090x's Plymouth themes.

- hexa_retro    -> themes/catppuccin-<flavor>-hexa-retro
- infinite_seal -> themes/catppuccin-<flavor>-infinite-seal-<accent>
+ for every theme, a "-status" variant (progress bar + latest systemd services
  under the animation, see extras.script)

Examples:
  python3 generate.py                                  # mocha, all accents
  python3 generate.py -f frappe macchiato -a mauve blue
  python3 generate.py -f all -a all                    # everything (120 themes)
  python3 generate.py -f latte -a pink -t seal --no-status

The upstream themes are fetched into upstream/ with git unless --src is given.
"""
import argparse
import re
import shutil
import subprocess
from multiprocessing import Pool
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent
DEFAULT_SRC = ROOT / "upstream/plymouth-themes/pack_3"
INSTALL_DIR = "/usr/share/plymouth/themes"
UPSTREAM_REPO = "https://github.com/adi1090x/plymouth-themes.git"

# Catppuccin palettes (https://github.com/catppuccin/palette)
PALETTES = {
    "latte": {
        "rosewater": "#dc8a78", "flamingo": "#dd7878", "pink": "#ea76cb",
        "mauve": "#8839ef", "red": "#d20f39", "maroon": "#e64553",
        "peach": "#fe640b", "yellow": "#df8e1d", "green": "#40a02b",
        "teal": "#179299", "sky": "#04a5e5", "sapphire": "#209fb5",
        "blue": "#1e66f5", "lavender": "#7287fd",
        "text": "#4c4f69", "subtext0": "#6c6f85", "overlay1": "#8c8fa1",
        "surface0": "#ccd0da", "base": "#eff1f5",
    },
    "frappe": {
        "rosewater": "#f2d5cf", "flamingo": "#eebebe", "pink": "#f4b8e4",
        "mauve": "#ca9ee6", "red": "#e78284", "maroon": "#ea999c",
        "peach": "#ef9f76", "yellow": "#e5c890", "green": "#a6d189",
        "teal": "#81c8be", "sky": "#99d1db", "sapphire": "#85c1dc",
        "blue": "#8caaee", "lavender": "#babbf1",
        "text": "#c6d0f5", "subtext0": "#a5adce", "overlay1": "#838ba7",
        "surface0": "#414559", "base": "#303446",
    },
    "macchiato": {
        "rosewater": "#f4dbd6", "flamingo": "#f0c6c6", "pink": "#f5bde6",
        "mauve": "#c6a0f6", "red": "#ed8796", "maroon": "#ee99a0",
        "peach": "#f5a97f", "yellow": "#eed49f", "green": "#a6da95",
        "teal": "#8bd5ca", "sky": "#91d7e3", "sapphire": "#7dc4e4",
        "blue": "#8aadf4", "lavender": "#b7bdf8",
        "text": "#cad3f5", "subtext0": "#a5adcb", "overlay1": "#8087a2",
        "surface0": "#363a4f", "base": "#24273a",
    },
    "mocha": {
        "rosewater": "#f5e0dc", "flamingo": "#f2cdcd", "pink": "#f5c2e7",
        "mauve": "#cba6f7", "red": "#f38ba8", "maroon": "#eba0ac",
        "peach": "#fab387", "yellow": "#f9e2af", "green": "#a6e3a1",
        "teal": "#94e2d5", "sky": "#89dceb", "sapphire": "#74c7ec",
        "blue": "#89b4fa", "lavender": "#b4befe",
        "text": "#cdd6f4", "subtext0": "#a6adc8", "overlay1": "#7f849c",
        "surface0": "#313244", "base": "#1e1e2e",
    },
}
FLAVORS = list(PALETTES)
FLAVOR_TITLES = {"latte": "Latte", "frappe": "Frappé", "macchiato": "Macchiato", "mocha": "Mocha"}
ACCENTS = ["rosewater", "flamingo", "pink", "mauve", "red", "maroon", "peach",
           "yellow", "green", "teal", "sky", "sapphire", "blue", "lavender"]

# hexa_retro: original colour (full intensity) -> Catppuccin colour
HEXA_MAP = [
    ((246, 255, 239), "text"),    # white
    ((251, 66, 99), "red"),       # red
    ((255, 173, 3), "yellow"),    # yellow
    ((68, 171, 204), "blue"),     # blue
    ((96, 234, 221), "teal"),     # cyan (light blue)
]


def rgb(flavor, name):
    h = PALETTES[flavor][name].lstrip("#")
    return np.array([int(h[i:i + 2], 16) for i in (0, 2, 4)], dtype=np.float32)


def fetch_upstream(src):
    """Sparse-clone only the two source themes from adi1090x/plymouth-themes."""
    if src.exists():
        return
    if src != DEFAULT_SRC:
        raise SystemExit(f"Source folder not found: {src}")
    repo = ROOT / "upstream/plymouth-themes"
    print(f"Fetching {UPSTREAM_REPO} ...", flush=True)
    repo.parent.mkdir(exist_ok=True)
    subprocess.run(["git", "clone", "--depth", "1", "--filter=blob:none", "--sparse",
                    UPSTREAM_REPO, str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "sparse-checkout", "set",
                    "pack_3/infinite_seal", "pack_3/hexa_retro"], check=True)


# ---------------------------------------------------------------- recolouring
def recolor_hexa(src, dst, flavor):
    """Each pixel ~ t * key_colour over black: find the closest key and its
    intensity t, then rebuild it as t * target over the flavour's base."""
    base = rgb(flavor, "base")
    px = np.asarray(Image.open(src).convert("RGB"), dtype=np.float32)
    flat = px.reshape(-1, 3)
    keys = np.array([k for k, _ in HEXA_MAP], dtype=np.float32)
    targets = np.array([rgb(flavor, n) for _, n in HEXA_MAP])
    # project every pixel on every key vector
    t = np.clip((flat @ keys.T) / (keys ** 2).sum(1), 0, 1)          # (N, K)
    resid = ((flat[:, None, :] - t[..., None] * keys[None]) ** 2).sum(-1)
    best = resid.argmin(1)
    tb = t[np.arange(len(flat)), best][:, None]
    out = base + tb * (targets[best] - base)
    im = Image.fromarray(np.clip(out.reshape(px.shape) + 0.5, 0, 255).astype(np.uint8), "RGB")
    im.quantize(256, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE).save(dst, optimize=True)


def recolor_mono(src, dst, flavor, accent):
    """White on black: intensity -> blend between the base and the accent."""
    base, acc = rgb(flavor, "base"), rgb(flavor, accent)
    px = np.asarray(Image.open(src).convert("RGB"))
    # indexed PNG: index = intensity, palette = base -> accent gradient (lossless)
    idx = px.max(-1).astype(np.uint8)
    t = np.arange(256, dtype=np.float32)[:, None] / 255.0
    pal = np.clip(base + t * (acc - base) + 0.5, 0, 255).astype(np.uint8)
    im = Image.fromarray(idx, "P")
    im.putpalette(pal.flatten().tolist())
    im.save(dst, optimize=True)


def _job(args):
    kind, src, dst, flavor, accent = args
    if kind == "hexa":
        recolor_hexa(src, dst, flavor)
    else:
        recolor_mono(src, dst, flavor, accent)


# -------------------------------------------------------------------- scripts
def color_args(flavor, name):
    c = rgb(flavor, name) / 255
    return f"{c[0]:.3f}, {c[1]:.3f}, {c[2]:.3f}"


def patch_script(text, flavor):
    """Flavour base for the whole window + flavour `text` colour for messages."""
    b = color_args(flavor, "base")
    bg = (f"// Catppuccin {FLAVOR_TITLES[flavor]} background\n"
          f"Window.SetBackgroundTopColor({b});\n"
          f"Window.SetBackgroundBottomColor({b});\n\n")
    text = text.replace("// Screen size", bg + "// Screen size", 1)
    return text.replace(", 1, 1, 1)", f", {color_args(flavor, 'text')})")


def write_theme(src_dir, name, desc, dst_dir, flavor):
    old = src_dir.name
    if dst_dir.exists():
        shutil.rmtree(dst_dir)
    dst_dir.mkdir(parents=True)
    (dst_dir / f"{name}.script").write_text(
        patch_script((src_dir / f"{old}.script").read_text(), flavor))
    conf = (src_dir / f"{old}.plymouth").read_text()
    conf = re.sub(r"^Name=.*$", f"Name={name}", conf, flags=re.M)
    conf = re.sub(r"^Description=.*$", f"Description={desc}", conf, flags=re.M)
    conf = re.sub(r"^Comment=.*$",
                  f"Comment=Catppuccin {FLAVOR_TITLES[flavor]} adaptation of a theme "
                  "by Aditya Shakya (@adi1090x)", conf, flags=re.M)
    conf = conf.replace(f"/{old}/{old}.script", f"/{name}/{name}.script")
    conf = conf.replace(f"{INSTALL_DIR}/{old}", f"{INSTALL_DIR}/{name}")
    (dst_dir / f"{name}.plymouth").write_text(conf)
    shutil.copy(src_dir / "LICENSE", dst_dir / "LICENSE")


def write_status_variant(base_dir, flavor, accent, bar_frac, bar_gap):
    """"-status" variant: same frames + progress bar + latest services."""
    base = base_dir.name
    name = base + "-status"
    dst = base_dir.parent / name
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(base_dir, dst)
    # rename script / config and update paths
    (dst / f"{base}.script").rename(dst / f"{name}.script")
    conf = (dst / f"{base}.plymouth").read_text().replace(base, name)
    conf = re.sub(r"^Description=(.*)$", r"Description=\1 (progress + status)", conf, flags=re.M)
    (dst / f"{name}.plymouth").write_text(conf)
    (dst / f"{base}.plymouth").unlink()

    extras = ((ROOT / "extras.script").read_text()
              .replace("@SUBTEXT@", color_args(flavor, "subtext0"))
              .replace("@OVERLAY@", color_args(flavor, "overlay1"))
              .replace("@BARFRAC@", str(bar_frac))
              .replace("@BARGAP@", str(bar_gap)))
    with open(dst / f"{name}.script", "a") as f:
        f.write(extras)

    for fname, col in (("bar-track.png", "surface0"), ("bar-fill.png", accent)):
        Image.new("RGB", (1, 1), tuple(int(v) for v in rgb(flavor, col))).save(dst / fname)


def frames(d):
    return sorted(d.glob("progress-*.png"), key=lambda p: int(p.stem.split("-")[1]))


# ----------------------------------------------------------------------- main
def expand(values, allowed, what):
    if "all" in values:
        return list(allowed)
    bad = [v for v in values if v not in allowed]
    if bad:
        raise SystemExit(f"Unknown {what}: {', '.join(bad)} (choose from: all, {', '.join(allowed)})")
    return list(dict.fromkeys(values))   # dedupe, keep order


def parse_args():
    p = argparse.ArgumentParser(
        description="Generate Catppuccin adaptations of adi1090x's hexa_retro and infinite_seal.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"flavors: {', '.join(FLAVORS)}\naccents: {', '.join(ACCENTS)}")
    p.add_argument("-f", "--flavor", nargs="+", default=["mocha"], metavar="FLAVOR",
                   help="one or more flavors, or 'all' (default: mocha)")
    p.add_argument("-a", "--accent", nargs="+", default=["all"], metavar="ACCENT",
                   help="infinite_seal accent(s), or 'all' (default: all)")
    p.add_argument("-t", "--theme", nargs="+", default=["hexa", "seal"], choices=["hexa", "seal"],
                   help="which animations to build (default: both)")
    p.add_argument("--hexa-bar", default="blue", metavar="ACCENT",
                   help="progress bar colour of hexa_retro -status (default: blue)")
    p.add_argument("--no-status", action="store_true", help="skip the -status variants")
    p.add_argument("-o", "--out", type=Path, default=ROOT / "themes",
                   help="output folder (default: themes/)")
    p.add_argument("--src", type=Path, default=DEFAULT_SRC,
                   help="path to adi1090x plymouth-themes/pack_3 (default: fetched into upstream/)")
    a = p.parse_args()
    a.flavor = expand(a.flavor, FLAVORS, "flavor")
    a.accent = expand(a.accent, ACCENTS, "accent")
    expand([a.hexa_bar], ACCENTS, "accent")
    return a


def main():
    a = parse_args()
    fetch_upstream(a.src)
    a.out.mkdir(parents=True, exist_ok=True)
    jobs, built = [], []   # built: (theme dir, flavor, bar accent, bar frac, bar gap)

    for flv in a.flavor:
        title = FLAVOR_TITLES[flv]
        if "hexa" in a.theme:
            src = a.src / "hexa_retro"
            name = f"catppuccin-{flv}-hexa-retro"
            write_theme(src, name, f"Retro styled hexagons - Catppuccin {title}", a.out / name, flv)
            jobs += [("hexa", f, a.out / name / f.name, flv, None) for f in frames(src)]
            built.append((a.out / name, flv, a.hexa_bar, 0.5, 20))
        if "seal" in a.theme:
            src = a.src / "infinite_seal"
            for acc in a.accent:
                name = f"catppuccin-{flv}-infinite-seal-{acc}"
                write_theme(src, name, f"Infinite style seal - Catppuccin {title} {acc}",
                            a.out / name, flv)
                jobs += [("mono", f, a.out / name / f.name, flv, acc) for f in frames(src)]
                built.append((a.out / name, flv, acc, 0.4, 0))

    print(f"{len(built)} theme(s), {len(jobs)} images", flush=True)
    with Pool() as pool:
        for i, _ in enumerate(pool.imap_unordered(_job, jobs, chunksize=8), 1):
            if i % 500 == 0 or i == len(jobs):
                print(f"{i}/{len(jobs)} images", flush=True)

    if not a.no_status:
        for args in built:
            write_status_variant(*args)
    for d, *_ in built:
        print(f"  {d.name}" + ("" if a.no_status else f"  (+ {d.name}-status)"))


if __name__ == "__main__":
    main()
