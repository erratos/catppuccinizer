#!/usr/bin/env python3
"""Generate Catppuccin adaptations of any adi1090x Plymouth theme.

For each theme, the original colours are detected automatically and mapped to
Catppuccin colours. The mapping is saved in configs/<theme>.toml so it can be
edited by hand, or overridden on the command line with --map.

Examples:
  python3 generate.py                                  # hexa_retro + infinite_seal, mocha
  python3 generate.py --list                           # every upstream theme
  python3 generate.py rings_2 --detect                 # detect colours, write config, stop
  python3 generate.py rings_2 --map pink=mauve green=peach --preview
  python3 generate.py cyanide -f all -a mauve blue     # mono theme: one per accent
  python3 generate.py colorful --map yellow=red -s red # manual mapping, name suffix

A target is any Catppuccin colour name (red, mauve, text, overlay1, ...) or
"accent": themes using "accent" are generated once per accent chosen with -a.
"""
import argparse
import colorsys
import re
import shutil
import subprocess
import tomllib
from multiprocessing import Pool
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent
UPSTREAM = ROOT / "upstream/plymouth-themes"
UPSTREAM_REPO = "https://github.com/adi1090x/plymouth-themes.git"
CONFIGS = ROOT / "configs"
INSTALL_DIR = "/usr/share/plymouth/themes"
DEFAULT_THEMES = ["hexa_retro", "infinite_seal"]

# ------------------------------------------------------------------ palettes
# https://github.com/catppuccin/palette
_ORDER = ["rosewater", "flamingo", "pink", "mauve", "red", "maroon", "peach", "yellow",
          "green", "teal", "sky", "sapphire", "blue", "lavender", "text", "subtext1",
          "subtext0", "overlay2", "overlay1", "overlay0", "surface2", "surface1",
          "surface0", "base", "mantle", "crust"]
_HEX = {
    "latte": "dc8a78 dd7878 ea76cb 8839ef d20f39 e64553 fe640b df8e1d 40a02b 179299 04a5e5 "
             "209fb5 1e66f5 7287fd 4c4f69 5c5f77 6c6f85 7c7f93 8c8fa1 9ca0b0 acb0be bcc0cc "
             "ccd0da eff1f5 e6e9ef dce0e8",
    "frappe": "f2d5cf eebebe f4b8e4 ca9ee6 e78284 ea999c ef9f76 e5c890 a6d189 81c8be 99d1db "
              "85c1dc 8caaee babbf1 c6d0f5 b5bfe2 a5adce 949cbb 838ba7 737994 626880 51576d "
              "414559 303446 292c3c 232634",
    "macchiato": "f4dbd6 f0c6c6 f5bde6 c6a0f6 ed8796 ee99a0 f5a97f eed49f a6da95 8bd5ca 91d7e3 "
                 "7dc4e4 8aadf4 b7bdf8 cad3f5 b8c0e0 a5adcb 939ab7 8087a2 6e738d 5b6078 494d64 "
                 "363a4f 24273a 1e2030 181926",
    "mocha": "f5e0dc f2cdcd f5c2e7 cba6f7 f38ba8 eba0ac fab387 f9e2af a6e3a1 94e2d5 89dceb "
             "74c7ec 89b4fa b4befe cdd6f4 bac2de a6adc8 9399b2 7f849c 6c7086 585b70 45475a "
             "313244 1e1e2e 181825 11111b",
}
PALETTES = {f: dict(zip(_ORDER, h.split())) for f, h in _HEX.items()}
FLAVORS = list(PALETTES)
FLAVOR_TITLES = {"latte": "Latte", "frappe": "Frappé", "macchiato": "Macchiato", "mocha": "Mocha"}
ACCENTS = _ORDER[:14]
TARGETS = _ORDER + ["accent"]
# colours used for automatic mapping of saturated source colours
AUTO_HUE_TARGETS = ["red", "peach", "yellow", "green", "teal", "sky", "sapphire",
                    "blue", "mauve", "pink"]


def hex2rgb(h):
    h = h.lstrip("#")
    return np.array([int(h[i:i + 2], 16) for i in (0, 2, 4)], dtype=np.float32)


def rgb2hex(c):
    return "#" + "".join(f"{int(round(v)):02x}" for v in np.clip(c, 0, 255))


def rgb(flavor, name):
    return hex2rgb(PALETTES[flavor][name])


def hue_of(c):
    r, g, b = (np.asarray(c, dtype=float) / 255).tolist()
    return colorsys.rgb_to_hsv(r, g, b)[0] * 360


def hue_dist(a, b):
    d = abs(a - b) % 360
    return min(d, 360 - d)


HUE_NAMES = [(15, "red"), (35, "orange"), (70, "yellow"), (160, "green"), (190, "cyan"),
             (250, "blue"), (290, "purple"), (345, "pink"), (361, "red")]


def colour_name(hue, sat, val):
    if sat < 0.25:
        return "white" if val > 0.7 else "gray"
    return next(n for limit, n in HUE_NAMES if hue < limit)


# ------------------------------------------------------------------ upstream
def git(*args, **kw):
    return subprocess.run(["git", "-C", str(UPSTREAM), *args], check=True,
                          capture_output=True, text=True, **kw).stdout


def ensure_clone():
    if (UPSTREAM / ".git").exists():
        return
    print(f"Fetching {UPSTREAM_REPO} ...", flush=True)
    UPSTREAM.parent.mkdir(exist_ok=True)
    subprocess.run(["git", "clone", "--depth", "1", "--filter=blob:none", "--sparse",
                    UPSTREAM_REPO, str(UPSTREAM)], check=True)


def upstream_themes():
    """{theme name: 'pack_N/theme'} for every upstream theme."""
    ensure_clone()
    dirs = git("ls-tree", "-d", "--name-only", "HEAD", "pack_1/", "pack_2/", "pack_3/", "pack_4/")
    return {Path(d).name: d for d in dirs.split()}


def theme_dir(name, src):
    """Return the folder of a source theme, fetching it if needed."""
    name = Path(name).name
    if src:
        for cand in (src / name, *src.glob(f"pack_*/{name}"), src):
            if (cand / f"{name}.script").exists():
                return cand
        raise SystemExit(f"Theme {name} not found in {src}")
    themes = upstream_themes()
    if name not in themes:
        raise SystemExit(f"Unknown theme: {name} (see --list)")
    d = UPSTREAM / themes[name]
    if not (d / f"{name}.script").exists():
        print(f"Fetching {themes[name]} ...", flush=True)
        current = git("sparse-checkout", "list").split()
        git("sparse-checkout", "set", *sorted(set(current) | {themes[name]}))
    return d


def frames(d):
    return sorted(d.glob("progress-*.png"), key=lambda p: int(p.stem.split("-")[1]))


def load_rgb(path):
    """Frame as float RGB; transparent images are flattened onto black."""
    im = Image.open(path)
    if im.mode in ("RGBA", "LA", "PA") or "transparency" in im.info:
        im = im.convert("RGBA")
        flat = Image.new("RGBA", im.size, (0, 0, 0, 255))
        flat.alpha_composite(im)
        im = flat
    return np.asarray(im.convert("RGB"), dtype=np.float32)


# ----------------------------------------------------------------- detection
def detect(src_dir, max_colors=8):
    files = frames(src_dir)
    sample = [files[int(i)] for i in np.linspace(0, len(files) - 1, min(24, len(files)))]
    imgs = [load_rgb(f) for f in sample]
    h, w = imgs[0].shape[:2]

    # background = most common border colour
    border = np.concatenate([np.concatenate([im[0], im[-1], im[:, 0], im[:, -1]]) for im in imgs])
    vals, counts = np.unique(border.astype(np.uint8), axis=0, return_counts=True)
    bg = vals[counts.argmax()].astype(np.float32)

    # content pixels, expressed as offset from the background
    d = np.concatenate([(im - bg).reshape(-1, 3) for im in imgs])
    inten = d.max(-1)
    content = np.zeros((h, w), bool)
    for im in imgs:
        content |= (im - bg).max(-1) > 16
    ys, xs = np.nonzero(content)
    bbox = (xs.min(), ys.min(), xs.max(), ys.max()) if len(xs) else (0, 0, w - 1, h - 1)

    thr = 0.5 * np.percentile(inten[inten > 16], 99) if (inten > 16).any() else 255
    sel = d[inten >= max(thr, 24)]
    if len(sel) > 400_000:
        sel = sel[np.random.default_rng(0).choice(len(sel), 400_000, replace=False)]
    I = sel.max(-1, keepdims=True)
    c = sel / I                                  # chroma, max channel = 1
    mn = c.min(-1)
    sat = 1 - mn
    r, g, b = c.T
    delta = np.maximum(sat, 1e-6)
    hue = np.where(r >= 1 - 1e-6, ((g - b) / delta) % 6,
          np.where(g >= 1 - 1e-6, (b - r) / delta + 2, (r - g) / delta + 4)) * 60

    clusters = []                                # (mask over sel)
    gray = sat < 0.25
    if gray.mean() > 0.02:
        clusters.append(gray)
    col = ~gray
    if col.mean() > 0.02:
        hist, _ = np.histogram(hue[col], bins=72, range=(0, 360))
        sm = sum(np.roll(hist, k) * wgt for k, wgt in zip(range(-2, 3), (1, 2, 3, 2, 1)))
        peaks = [i for i in range(72) if sm[i] >= sm[i - 1] and sm[i] > sm[(i + 1) % 72]
                 and sm[i] >= 0.03 * sm.sum()]
        budget = max_colors - len(clusters)
        peaks = sorted(peaks, key=lambda i: -sm[i])[:budget]
        centers = [(i + 0.5) * 5 for i in peaks]
        hc = hue[col]

        def nearest_dist(cs):
            dd = np.abs((hc[:, None] - np.array(cs)[None]) % 360)
            return np.minimum(dd, 360 - dd)

        # spread-out hues (rainbows): add centres where many pixels are still far
        while len(centers) < budget:
            far = nearest_dist(centers).min(1) > 25 if centers else np.ones(len(hc), bool)
            if far.mean() < 0.08:
                break
            fh, _ = np.histogram(hc[far], bins=72, range=(0, 360))
            fs = sum(np.roll(fh, k) * wgt for k, wgt in zip(range(-2, 3), (1, 2, 3, 2, 1)))
            centers.append((fs.argmax() + 0.5) * 5)
        if centers:
            nearest = nearest_dist(centers).argmin(1)
            idx = np.nonzero(col)[0]
            for k in range(len(centers)):
                m = np.zeros(len(sel), bool)
                m[idx[nearest == k]] = True
                if m.mean() > 0.02:
                    clusters.append(m)

    colors = {}
    for m in clusters:
        px, it = sel[m], I[m, 0]
        key = np.median(px[it >= np.percentile(it, 75)], axis=0) + bg
        hh, ss, vv = colorsys.rgb_to_hsv(*(np.clip(key, 0, 255) / 255))
        name = colour_name(hh * 360, ss, vv)
        n, i = name, 2
        while n in colors:
            n, i = f"{name}-{i}", i + 1
        colors[n] = {"source": rgb2hex(key), "share": round(float(m.mean()), 3)}
    if not colors:
        colors["white"] = {"source": "#ffffff", "share": 1.0}

    auto_targets(colors)
    bottom_gap = h - 1 - bbox[3]                 # empty rows under the content
    return {
        "background": rgb2hex(bg),
        "bar": None,
        "bar_gap": int(20 - bottom_gap),
        "bar_width": round(float(0.6 * (bbox[2] - bbox[0] + 1) / w), 2),
        "colors": colors,
    }


def auto_targets(colors):
    """One colour -> accent; otherwise grays -> text, hues -> closest Catppuccin hue."""
    if len(colors) == 1:
        next(iter(colors.values()))["target"] = "accent"
        return
    ref = {t: hue_of(rgb("mocha", t)) for t in AUTO_HUE_TARGETS}
    pairs, used = [], set()
    for name, c in colors.items():
        src = hex2rgb(c["source"])
        _, s, v = colorsys.rgb_to_hsv(*(src / 255))
        if s < 0.25:
            c["target"] = "text" if v > 0.7 else "overlay2"
        else:
            pairs += [(hue_dist(hue_of(src), h), name, t) for t, h in ref.items()]
    for _, name, t in sorted(pairs):
        if "target" not in colors[name] and t not in used:
            colors[name]["target"], _ = t, used.add(t)
    for _, name, t in sorted(pairs):            # more colours than targets: reuse
        colors[name].setdefault("target", t)


# -------------------------------------------------------------------- config
def config_path(name):
    return CONFIGS / f"{name}.toml"


def save_config(name, pack, cfg):
    CONFIGS.mkdir(exist_ok=True)
    lines = [
        f"# Colour mapping for adi1090x/plymouth-themes {pack}",
        "# Edit the targets: any Catppuccin colour name (" + ", ".join(ACCENTS) + ",",
        "# text, subtext1/0, overlay2/1/0, surface2/1/0, base, mantle, crust) or \"accent\"",
        "# (\"accent\" = one theme per accent chosen with -a). You can also add colours.",
        "",
        f'background = "{cfg["background"]}"   # detected background of the source frames',
        f'bar_gap = {cfg["bar_gap"]}              # -status: px between frame bottom and bar',
        f'bar_width = {cfg["bar_width"]}          # -status: bar width / frame width',
    ]
    if cfg.get("bar"):
        lines.append(f'bar = "{cfg["bar"]}"            # -status: bar colour (default: auto)')
    else:
        lines.append('# bar = "blue"          # -status: bar colour (default: accent or main colour)')
    for n, c in cfg["colors"].items():
        lines += ["", f"[colors.{n}]", f'source = "{c["source"]}"', f'target = "{c["target"]}"']
        if "share" in c:
            lines.append(f'share = {c["share"]}   # informative: share of coloured pixels')
    config_path(name).write_text("\n".join(lines) + "\n")


def load_config(name):
    cfg = tomllib.loads(config_path(name).read_text())
    cfg.setdefault("bar", None)
    cfg.setdefault("bar_gap", 20)
    cfg.setdefault("bar_width", 0.5)
    for n, c in cfg["colors"].items():
        if c.get("target") not in TARGETS:
            raise SystemExit(f"{config_path(name)}: [colors.{n}] target "
                             f"'{c.get('target')}' is not a Catppuccin colour or 'accent'")
    return cfg


def apply_maps(cfg, maps):
    for m in maps:
        if "=" not in m:
            raise SystemExit(f"--map expects NAME=TARGET, got '{m}'")
        k, t = (s.strip() for s in m.split("=", 1))
        if t not in TARGETS:
            raise SystemExit(f"--map {m}: unknown target '{t}' (choose from: {', '.join(TARGETS)})")
        if k in cfg["colors"]:
            cfg["colors"][k]["target"] = t
        elif re.fullmatch(r"#?[0-9a-fA-F]{6}", k):
            k = "#" + k.lstrip("#").lower()
            hit = [n for n, c in cfg["colors"].items() if c["source"] == k]
            if hit:
                cfg["colors"][hit[0]]["target"] = t
            else:                                 # new source colour
                cfg["colors"][k] = {"source": k, "target": t}
        else:
            raise SystemExit(f"--map {m}: no colour named '{k}' "
                             f"(have: {', '.join(cfg['colors'])}; or use a #rrggbb source)")


def print_mapping(name, cfg):
    print(f"{name}: background {cfg['background']}")
    for n, c in cfg["colors"].items():
        share = f"  ({c['share'] * 100:.0f}%)" if "share" in c else ""
        print(f"  {n:10s} {c['source']} -> {c['target']}{share}")


# --------------------------------------------------------------- recolouring
def recolor(path, dst, src_bg, keys, targets, base):
    """Each pixel ~ bg + t * (key - bg): find the key and intensity t that explain
    it best, then rebuild it as base + t * (target - base)."""
    px = load_rgb(path)
    flat = px.reshape(-1, 3) - src_bg
    k = keys - src_bg
    t = np.clip((flat @ k.T) / np.maximum((k ** 2).sum(1), 1e-6), 0, 1)       # (N, K)
    if len(keys) == 1:
        # single colour: indexed PNG whose palette is the exact base -> target ramp
        idx = np.round(t[:, 0] * 255).astype(np.uint8).reshape(px.shape[:2])
        ramp = np.arange(256, dtype=np.float32)[:, None] / 255
        pal = np.clip(base + ramp * (targets[0] - base) + 0.5, 0, 255).astype(np.uint8)
        im = Image.fromarray(idx, "P")
        im.putpalette(pal.flatten().tolist())
    else:
        resid = ((flat[:, None, :] - t[..., None] * k[None]) ** 2).sum(-1)
        best = resid.argmin(1)
        tb = t[np.arange(len(flat)), best][:, None]
        out = (base + tb * (targets[best] - base)).reshape(px.shape)
        im = Image.fromarray(np.clip(out + 0.5, 0, 255).astype(np.uint8), "RGB")
        im = im.quantize(256, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    if dst is None:
        return im
    im.save(dst, optimize=True)


def _job(args):
    recolor(*args)


# ------------------------------------------------------------------- scripts
def color_args(flavor, name):
    c = rgb(flavor, name) / 255
    return f"{c[0]:.3f}, {c[1]:.3f}, {c[2]:.3f}"


def patch_script(text, flavor):
    """Flavour base for the whole window + flavour `text` colour for messages."""
    b = color_args(flavor, "base")
    bg = (f"// Catppuccin {FLAVOR_TITLES[flavor]} background\n"
          f"Window.SetBackgroundTopColor({b});\n"
          f"Window.SetBackgroundBottomColor({b});\n\n")
    if "// Screen size" in text:
        text = text.replace("// Screen size", bg + "// Screen size", 1)
    else:
        text = bg + text
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
    conf = re.sub(r"^ImageDir=.*$", f"ImageDir={INSTALL_DIR}/{name}", conf, flags=re.M)
    conf = re.sub(r"^ScriptFile=.*$", f"ScriptFile={INSTALL_DIR}/{name}/{name}.script",
                  conf, flags=re.M)
    (dst_dir / f"{name}.plymouth").write_text(conf)
    if (src_dir / "LICENSE").exists():
        shutil.copy(src_dir / "LICENSE", dst_dir / "LICENSE")


def write_status_variant(base_dir, flavor, bar, bar_width, bar_gap):
    """"-status" variant: same frames + progress bar + latest services."""
    base = base_dir.name
    name = base + "-status"
    dst = base_dir.parent / name
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(base_dir, dst)
    (dst / f"{base}.script").rename(dst / f"{name}.script")
    conf = (dst / f"{base}.plymouth").read_text().replace(base, name)
    conf = re.sub(r"^Description=(.*)$", r"Description=\1 (progress + status)", conf, flags=re.M)
    (dst / f"{name}.plymouth").write_text(conf)
    (dst / f"{base}.plymouth").unlink()

    extras = ((ROOT / "extras.script").read_text()
              .replace("@SUBTEXT@", color_args(flavor, "subtext0"))
              .replace("@OVERLAY@", color_args(flavor, "overlay1"))
              .replace("@BARFRAC@", str(bar_width))
              .replace("@BARGAP@", str(bar_gap)))
    with open(dst / f"{name}.script", "a") as f:
        f.write(extras)
    for fname, col in (("bar-track.png", "surface0"), ("bar-fill.png", bar)):
        Image.new("RGB", (1, 1), tuple(int(v) for v in rgb(flavor, col))).save(dst / fname)


# ---------------------------------------------------------------------- main
def expand(values, allowed, what):
    if "all" in values:
        return list(allowed)
    bad = [v for v in values if v not in allowed]
    if bad:
        raise SystemExit(f"Unknown {what}: {', '.join(bad)} (choose from: all, {', '.join(allowed)})")
    return list(dict.fromkeys(values))


def parse_args():
    p = argparse.ArgumentParser(
        description="Generate Catppuccin adaptations of adi1090x Plymouth themes.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"flavors: {', '.join(FLAVORS)}\naccents: {', '.join(ACCENTS)}\n"
               f"targets: {', '.join(TARGETS)}")
    p.add_argument("themes", nargs="*", default=DEFAULT_THEMES, metavar="THEME",
                   help="adi1090x theme name(s) (default: hexa_retro infinite_seal)")
    p.add_argument("-f", "--flavor", nargs="+", default=["mocha"], metavar="FLAVOR",
                   help="one or more flavors, or 'all' (default: mocha)")
    p.add_argument("-a", "--accent", nargs="+", default=["all"], metavar="ACCENT",
                   help="accent(s) for colours mapped to 'accent', or 'all' (default: all)")
    p.add_argument("-m", "--map", nargs="+", default=[], metavar="NAME=TARGET",
                   help="override the mapping, e.g. yellow=red green=mauve '#ffad03=peach'")
    p.add_argument("-s", "--suffix", default="", help="extra suffix for the theme names")
    p.add_argument("--bar", metavar="COLOUR", help="-status progress bar colour")
    p.add_argument("--no-status", action="store_true", help="skip the -status variants")
    p.add_argument("--detect", action="store_true",
                   help="(re)detect colours, overwrite configs/<theme>.toml, then stop")
    p.add_argument("--preview", action="store_true",
                   help="only render one before/after image per theme into <out>/previews/")
    p.add_argument("--list", action="store_true", help="list upstream themes and exit")
    p.add_argument("-o", "--out", type=Path, default=ROOT / "themes",
                   help="output folder (default: themes/)")
    p.add_argument("--src", type=Path,
                   help="local adi1090x/plymouth-themes checkout (default: fetched into upstream/)")
    a = p.parse_args()
    a.flavor = expand(a.flavor, FLAVORS, "flavor")
    a.accent = expand(a.accent, ACCENTS, "accent")
    if a.bar and a.bar not in PALETTES["mocha"]:
        raise SystemExit(f"--bar: unknown colour '{a.bar}'")
    if a.suffix and not re.fullmatch(r"[a-z0-9-]+", a.suffix):
        raise SystemExit("--suffix: use lowercase letters, digits and '-'")
    return a


def list_themes():
    themes = upstream_themes()
    for name, path in sorted(themes.items(), key=lambda kv: kv[1]):
        mark = "  [config]" if config_path(name).exists() else ""
        print(f"{path}{mark}")


def main():
    a = parse_args()
    if a.list:
        return list_themes()

    jobs, status, previews = [], [], []
    for theme in a.themes:
        src = theme_dir(theme, a.src)
        name = src.name
        pack = "/".join(src.parts[-2:])
        if a.detect or not config_path(name).exists():
            print(f"Detecting colours of {name} ...", flush=True)
            save_config(name, pack, detect(src))
            print(f"  -> {config_path(name)}")
        cfg = load_config(name)
        apply_maps(cfg, a.map)
        print_mapping(name, cfg)
        if a.detect:
            continue

        src_bg = hex2rgb(cfg["background"])
        keys = np.array([hex2rgb(c["source"]) for c in cfg["colors"].values()])
        tnames = [c["target"] for c in cfg["colors"].values()]
        uses_accent = "accent" in tnames
        fr = frames(src)
        slug = name.replace("_", "-")
        for flv in a.flavor:
            for acc in (a.accent if uses_accent else [None]):
                out_name = "-".join(x for x in (f"catppuccin-{flv}-{slug}", acc, a.suffix) if x)
                targets = np.array([rgb(flv, acc if t == "accent" else t) for t in tnames])
                base = rgb(flv, "base")
                if a.preview:
                    previews.append((fr[len(fr) // 2], out_name, src_bg, keys, targets, base))
                    continue
                desc = f"{name.replace('_', ' ').title()} - Catppuccin {FLAVOR_TITLES[flv]}" + (f" {acc}" if acc else "")
                write_theme(src, out_name, desc, a.out / out_name, flv)
                jobs += [(f, a.out / out_name / f.name, src_bg, keys, targets, base) for f in fr]
                # bar colour: option > config > accent > most common non-gray target
                coloured = [c["target"] for c in sorted(cfg["colors"].values(),
                            key=lambda c: -c.get("share", 0)) if c["target"] in ACCENTS]
                bar = a.bar or cfg["bar"] or acc or (coloured[0] if coloured else "blue")
                bar = acc if bar == "accent" else bar
                status.append((a.out / out_name, flv, bar, cfg["bar_width"], cfg["bar_gap"]))

    if previews:
        (a.out / "previews").mkdir(parents=True, exist_ok=True)
        for f, out_name, src_bg, keys, targets, base in previews:
            before = Image.fromarray(load_rgb(f).astype(np.uint8))
            after = recolor(f, None, src_bg, keys, targets, base).convert("RGB")
            sheet = Image.new("RGB", (before.width * 2, before.height))
            sheet.paste(before, (0, 0))
            sheet.paste(after, (before.width, 0))
            sheet.save(a.out / "previews" / f"{out_name}.png")
            print(f"  preview: {a.out / 'previews' / out_name}.png")
        return
    if not jobs:
        return

    print(f"{len(status)} theme(s), {len(jobs)} images", flush=True)
    with Pool() as pool:
        for i, _ in enumerate(pool.imap_unordered(_job, jobs, chunksize=8), 1):
            if i % 500 == 0 or i == len(jobs):
                print(f"{i}/{len(jobs)} images", flush=True)
    for args in status:
        if not a.no_status:
            write_status_variant(*args)
        print(f"  {args[0].name}" + ("" if a.no_status else f"  (+ {args[0].name}-status)"))


if __name__ == "__main__":
    main()
