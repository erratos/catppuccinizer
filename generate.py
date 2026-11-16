#!/usr/bin/env python3
"""Recolour Plymouth themes with Catppuccin.

Works with any theme folder (script, two-step, fade-throbber, ...) and can fetch
any of the 80 themes of adi1090x/plymouth-themes by name. The original colours
are detected automatically, per group of images (each animation sequence, plus
the UI pieces), and saved in configs/<theme>.toml so they can be edited, or
overridden on the command line with --map.

Examples:
  python3 generate.py                                  # hexa_retro + infinite_seal, mocha
  python3 generate.py --list                           # adi1090x themes
  python3 generate.py rings_2 -m pink=mauve green=peach
  python3 generate.py /usr/share/plymouth/themes/spinner -f frappe -a mauve
  python3 generate.py ./my-theme --detect              # detect colours, write config, stop
  python3 generate.py cyanide -m cyan=accent -a peach --preview

A target is any Catppuccin colour name (red, mauve, text, overlay1, ...) or
"accent": themes using "accent" are generated once per accent chosen with -a.
"""
import argparse
import colorsys
import configparser
import re
import shutil
import subprocess
import tomllib
from collections import defaultdict
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
UI_GROUP = "ui"


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
def git(*args):
    return subprocess.run(["git", "-C", str(UPSTREAM), *args], check=True,
                          capture_output=True, text=True).stdout


def ensure_clone():
    if (UPSTREAM / ".git").exists():
        return
    print(f"Fetching {UPSTREAM_REPO} ...", flush=True)
    UPSTREAM.parent.mkdir(exist_ok=True)
    subprocess.run(["git", "clone", "--depth", "1", "--filter=blob:none", "--sparse",
                    UPSTREAM_REPO, str(UPSTREAM)], check=True)


def upstream_themes():
    """{theme name: 'pack_N/theme'} for every adi1090x theme."""
    ensure_clone()
    dirs = git("ls-tree", "-d", "--name-only", "HEAD", "pack_1/", "pack_2/", "pack_3/", "pack_4/")
    return {Path(d).name: d for d in dirs.split()}


def resolve_theme(arg, src):
    """Folder of a theme given as a path, or as an adi1090x name (fetched on demand)."""
    p = Path(arg).expanduser()
    if p.is_dir():
        return p.resolve()
    if "/" in arg:
        raise SystemExit(f"Theme folder not found: {arg}")
    if src:
        for cand in (src / arg, *src.glob(f"pack_*/{arg}")):
            if cand.is_dir():
                return cand
        raise SystemExit(f"Theme {arg} not found in {src}")
    themes = upstream_themes()
    if arg not in themes:
        raise SystemExit(f"Unknown theme: {arg} (give a folder path, or see --list)")
    d = UPSTREAM / themes[arg]
    if not (d / f"{arg}.plymouth").exists():
        print(f"Fetching {themes[arg]} ...", flush=True)
        current = git("sparse-checkout", "list").split()
        git("sparse-checkout", "set", *sorted(set(current) | {themes[arg]}))
    return d


# --------------------------------------------------------------- theme model
class Theme:
    """A source theme: its .plymouth, module, script and image groups."""

    def __init__(self, folder):
        self.dir = folder
        files = sorted(folder.glob("*.plymouth"))
        own = folder / f"{folder.name}.plymouth"
        if own.exists():
            files = [own]
        if not files:
            raise SystemExit(f"No .plymouth file in {folder}")
        self.conf_file = files[0]
        self.conf_text = self.conf_file.read_text()
        cp = configparser.ConfigParser(interpolation=None, strict=False)
        cp.optionxform = str
        cp.read_string(self.conf_text)
        self.cp = cp
        main = cp["Plymouth Theme"] if cp.has_section("Plymouth Theme") else {}
        self.module = main.get("ModuleName", "script")
        self.title = main.get("Name", folder.name)
        if " " not in self.title and "_" in self.title:      # hexa_retro -> Hexa Retro
            self.title = self.title.replace("_", " ").title()
        self.name = folder.name
        self.slug = re.sub(r"[^a-z0-9]+", "-", folder.name.lower()).strip("-")

        self.script = None
        if self.module == "script":
            sf = cp.get("script", "ScriptFile", fallback=f"{folder.name}.script")
            cand = folder / Path(sf).name
            self.script = cand if cand.exists() else next(iter(folder.glob("*.script")), None)

        # images: theme folder, or the ImageDir of the module if it lives elsewhere
        self.image_dir = folder
        if not list(folder.glob("*.png")):
            idir = cp.get(self.module, "ImageDir", fallback="")
            if idir and Path(idir).is_dir():
                self.image_dir = Path(idir)
        self.groups = group_images(sorted(self.image_dir.glob("*.png")))

    @property
    def adi_template(self):
        """True for scripts built on adi1090x's template (needed for -status)."""
        if not self.script:
            return False
        s = self.script.read_text()
        return "flyingman_image" in s and "refresh_callback" in s


def group_images(paths):
    """Numbered sequences (animation-1.png ...) get their own group; single
    images are gathered into the 'ui' group."""
    seq = defaultdict(list)
    for p in paths:
        m = re.fullmatch(r"(.*?)[-_]?(\d+)", p.stem)
        seq[m.group(1) if m and m.group(1) else p.stem].append(p)
    groups, ui = {}, []
    for prefix, items in seq.items():
        if len(items) > 1:
            groups[prefix] = sorted(items, key=lambda p: int(re.search(r"(\d+)$", p.stem).group(1)))
        else:
            ui += items
    if ui:
        groups[UI_GROUP] = ui
    # biggest animation first
    return dict(sorted(groups.items(), key=lambda kv: (kv[0] == UI_GROUP, -len(kv[1]))))


def load_rgba(path):
    """Image as float RGB plus alpha (0..255), or alpha=None when fully opaque."""
    im = Image.open(path)
    has_alpha = im.mode in ("RGBA", "LA", "PA") or "transparency" in im.info
    im = im.convert("RGBA")
    arr = np.asarray(im, dtype=np.float32)
    alpha = arr[..., 3]
    if not has_alpha or alpha.min() >= 255:
        return arr[..., :3], None
    return arr[..., :3], alpha


# ----------------------------------------------------------------- detection
def detect_group(paths, is_ui, max_colors=8):
    sample = [paths[int(i)] for i in np.linspace(0, len(paths) - 1, min(24, len(paths)))]
    imgs = [load_rgba(f) for f in sample]
    transparent = any(a is not None for _, a in imgs)
    h, w = imgs[0][0].shape[:2]

    if transparent:
        bg = np.zeros(3, np.float32)
    else:   # background = most common border colour
        border = np.concatenate([np.concatenate([im[0], im[-1], im[:, 0], im[:, -1]])
                                 for im, _ in imgs])
        vals, counts = np.unique(border.astype(np.uint8), axis=0, return_counts=True)
        bg = vals[counts.argmax()].astype(np.float32)

    ds, content = [], np.zeros((h, w), bool)
    rng = np.random.default_rng(0)
    for im, a in imgs:
        d = im - bg
        visible = (a >= 128) if a is not None else np.ones(im.shape[:2], bool)
        dv = d[visible]
        dv = dv[dv.max(-1) > 16]
        if is_ui and len(dv) > 20_000:           # every UI image weighs the same
            dv = dv[rng.choice(len(dv), 20_000, replace=False)]
        ds.append(dv)
        if im.shape[:2] == (h, w):
            content |= visible & ((d.max(-1) > 16) if a is None else True)
    d = np.concatenate(ds)
    inten = d.max(-1)
    ys, xs = np.nonzero(content)
    bbox = (xs.min(), ys.min(), xs.max(), ys.max()) if len(xs) else (0, 0, w - 1, h - 1)

    thr = 0.5 * np.percentile(inten[inten > 16], 99) if (inten > 16).any() else 255
    sel = d[inten >= max(thr, 24)]
    if len(sel) > 400_000:
        sel = sel[np.random.default_rng(0).choice(len(sel), 400_000, replace=False)]
    colors = {}
    if len(sel):
        colors = cluster_colours(sel, bg, max_colors)
    if not colors:
        colors["white"] = {"source": "#ffffff", "share": 1.0}
    auto_targets(colors, single_to_accent=not is_ui)
    return {"background": rgb2hex(bg), "transparent": transparent, "colors": colors,
            "_bbox": bbox, "_size": (w, h)}


def cluster_colours(sel, bg, max_colors):
    I = sel.max(-1, keepdims=True)
    c = sel / I                                  # chroma, max channel = 1
    sat = 1 - c.min(-1)
    r, g, b = c.T
    delta = np.maximum(sat, 1e-6)
    hue = np.where(r >= 1 - 1e-6, ((g - b) / delta) % 6,
          np.where(g >= 1 - 1e-6, (b - r) / delta + 2, (r - g) / delta + 4)) * 60

    clusters = []
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
        centers = [(i + 0.5) * 5 for i in sorted(peaks, key=lambda i: -sm[i])[:budget]]
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
    return colors


def auto_targets(colors, single_to_accent=True):
    """One colour -> accent (text for UI); else grays -> text, hues -> closest hue."""
    if len(colors) == 1:
        next(iter(colors.values()))["target"] = "accent" if single_to_accent else "text"
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
            colors[name]["target"] = t
            used.add(t)
    for _, name, t in sorted(pairs):            # more colours than targets: reuse
        colors[name].setdefault("target", t)


def detect(theme):
    groups = {g: detect_group(paths, g == UI_GROUP) for g, paths in theme.groups.items()}
    cfg = {"bar": None, "bar_gap": 20, "bar_width": 0.5, "groups": groups}
    anim = next((g for g in groups.values() if g is not groups.get(UI_GROUP)), None)
    if anim:
        x0, _, x1, y1 = anim["_bbox"]
        w, h = anim["_size"]
        cfg["bar_gap"] = int(20 - (h - 1 - y1))
        cfg["bar_width"] = round(float(0.6 * (x1 - x0 + 1) / w), 2)
    return cfg


# -------------------------------------------------------------------- config
def config_path(name):
    return CONFIGS / f"{name}.toml"


def save_config(theme, cfg):
    CONFIGS.mkdir(exist_ok=True)
    src = theme.dir
    try:
        src = src.relative_to(ROOT)
    except ValueError:
        pass
    lines = [
        f"# Colour mapping for the Plymouth theme {theme.title!r} ({src})",
        "# Edit the targets: any Catppuccin colour name (" + ", ".join(ACCENTS) + ",",
        "# text, subtext1/0, overlay2/1/0, surface2/1/0, base, mantle, crust) or \"accent\"",
        "# (\"accent\" = one theme per accent chosen with -a). You can also add colours.",
        "",
        f'bar_gap = {cfg["bar_gap"]}              # -status: px between frame bottom and bar',
        f'bar_width = {cfg["bar_width"]}          # -status: bar width / frame width',
        f'bar = "{cfg["bar"]}"            # progress bar colour' if cfg.get("bar") else
        '# bar = "blue"          # progress bar colour (default: accent or main colour)',
    ]
    for g, grp in cfg["groups"].items():
        files = ", ".join(p.name for p in theme.groups.get(g, [])[:3])
        if len(theme.groups.get(g, [])) > 3:
            files += f", ... ({len(theme.groups[g])} files)"
        lines += ["", f"[groups.{g}]   # {files}",
                  f'background = "{grp["background"]}"',
                  f'transparent = {"true" if grp["transparent"] else "false"}']
        for n, c in grp["colors"].items():
            lines += ["", f"[groups.{g}.colors.{n}]",f'source = "{c["source"]}"',
                      f'target = "{c["target"]}"']
            if "share" in c:
                lines.append(f'share = {c["share"]}   # informative')
    config_path(theme.name).write_text("\n".join(lines) + "\n")


def load_config(theme):
    cfg = tomllib.loads(config_path(theme.name).read_text())
    if "colors" in cfg:                          # legacy single-group format
        first = next(iter(theme.groups), "progress")
        cfg["groups"] = {first: {"background": cfg.pop("background", "#000000"),
                                 "transparent": False, "colors": cfg.pop("colors")}}
    cfg.setdefault("bar", None)
    cfg.setdefault("bar_gap", 20)
    cfg.setdefault("bar_width", 0.5)
    for g, grp in cfg["groups"].items():
        grp.setdefault("transparent", False)
        for n, c in grp["colors"].items():
            if c.get("target") not in TARGETS:
                raise SystemExit(f"{config_path(theme.name)}: [groups.{g}.colors.{n}] target "
                                 f"'{c.get('target')}' is not a Catppuccin colour or 'accent'")
    missing = set(theme.groups) - set(cfg["groups"])
    if missing:   # new images since the config was written
        fresh = detect(theme)["groups"]
        for g in missing:
            cfg["groups"][g] = fresh[g]
    return cfg


def apply_maps(cfg, maps):
    groups = cfg["groups"]
    for m in maps:
        if "=" not in m:
            raise SystemExit(f"--map expects NAME=TARGET, got '{m}'")
        k, t = (s.strip() for s in m.split("=", 1))
        if t not in TARGETS:
            raise SystemExit(f"--map {m}: unknown target '{t}' (choose from: {', '.join(TARGETS)})")
        gname, _, k2 = k.rpartition(".") if "." in k and k.split(".")[0] in groups else ("", "", k)
        scope = {gname: groups[gname]} if gname else groups
        hit = False
        for grp in scope.values():
            if k2 in grp["colors"]:
                grp["colors"][k2]["target"], hit = t, True
            elif re.fullmatch(r"#?[0-9a-fA-F]{6}", k2):
                hx = "#" + k2.lstrip("#").lower()
                for c in grp["colors"].values():
                    if c["source"] == hx:
                        c["target"], hit = t, True
        if not hit and re.fullmatch(r"#?[0-9a-fA-F]{6}", k2):
            hx = "#" + k2.lstrip("#").lower()      # new source colour in the first group
            next(iter(scope.values()))["colors"][hx] = {"source": hx, "target": t}
            hit = True
        if not hit:
            have = sorted({f"{g}.{n}" for g, grp in groups.items() for n in grp["colors"]})
            raise SystemExit(f"--map {m}: no colour named '{k}' "
                             f"(have: {', '.join(have)}; or use a #rrggbb source)")


def print_mapping(theme, cfg):
    print(f"{theme.title} [{theme.module}]")
    for g, grp in cfg["groups"].items():
        n = len(theme.groups.get(g, []))
        bg = "transparent" if grp["transparent"] else f"background {grp['background']}"
        print(f"  {g} ({n} image{'s' if n > 1 else ''}, {bg})")
        for name, c in grp["colors"].items():
            share = f"  ({c['share'] * 100:.0f}%)" if "share" in c else ""
            print(f"    {name:10s} {c['source']} -> {c['target']}{share}")


# --------------------------------------------------------------- recolouring
def recolor_image(path, src_bg, keys, targets, base):
    """Each pixel ~ bg + t * (key - bg): find the key and intensity t that explain
    it best, then rebuild it as base + t * (target - base). Alpha is kept."""
    px, alpha = load_rgba(path)
    flat = px.reshape(-1, 3) - src_bg
    k = keys - src_bg
    t = np.clip((flat @ k.T) / np.maximum((k ** 2).sum(1), 1e-6), 0, 1)       # (N, K)
    if len(keys) == 1 and alpha is None:
        # single colour: indexed PNG whose palette is the exact base -> target ramp
        idx = np.round(t[:, 0] * 255).astype(np.uint8).reshape(px.shape[:2])
        ramp = np.arange(256, dtype=np.float32)[:, None] / 255
        pal = np.clip(base + ramp * (targets[0] - base) + 0.5, 0, 255).astype(np.uint8)
        im = Image.fromarray(idx, "P")
        im.putpalette(pal.flatten().tolist())
        return im
    if len(keys) == 1:
        best = np.zeros(len(flat), int)
    else:
        best = (((flat[:, None, :] - t[..., None] * k[None]) ** 2).sum(-1)).argmin(1)
    tb = t[np.arange(len(flat)), best][:, None]
    out = np.clip((base + tb * (targets[best] - base)).reshape(px.shape) + 0.5, 0, 255)
    if alpha is not None:
        rgba = np.dstack([out, alpha]).astype(np.uint8)
        return Image.fromarray(rgba, "RGBA")
    im = Image.fromarray(out.astype(np.uint8), "RGB")
    return im.quantize(256, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)


def _job(args):
    path, dst, src_bg, keys, targets, base = args
    recolor_image(path, src_bg, keys, targets, base).save(dst, optimize=True)


# --------------------------------------------------------------- theme files
def color_args(flavor, name):
    c = rgb(flavor, name) / 255
    return f"{c[0]:.3f}, {c[1]:.3f}, {c[2]:.3f}"


def patch_script(text, flavor):
    """Flavour base for the whole window + flavour `text` colour for white text."""
    b = color_args(flavor, "base")
    text, n = re.subn(r"Window\.SetBackground(Top|Bottom)Color\s*\([^)]*\)",
                      lambda m: f"Window.SetBackground{m.group(1)}Color({b})", text)
    if not n:
        bg = (f"// Catppuccin {FLAVOR_TITLES[flavor]} background\n"
              f"Window.SetBackgroundTopColor({b});\n"
              f"Window.SetBackgroundBottomColor({b});\n\n")
        if "// Screen size" in text:
            text = text.replace("// Screen size", bg + "// Screen size", 1)
        else:
            text = bg + text
    white = r",\s*1(?:\.0*)?\s*,\s*1(?:\.0*)?\s*,\s*1(?:\.0*)?\s*([,)])"
    return re.sub(white, lambda m: f", {color_args(flavor, 'text')}{m.group(1)}", text)


def plymouth_colour(flavor, name, old):
    """0xRRGGBB / 0xAARRGGBB value keeping the original alpha byte, if any."""
    hx = PALETTES[flavor][name]
    v = old.strip().lower().removeprefix("0x")
    return "0x" + (v[:2] + hx if len(v) == 8 else hx)


def colour_key_target(key, bar):
    k = key.lower()
    if "progressbarforeground" in k:
        return bar
    if "progressbarbackground" in k:
        return "surface0"
    if "background" in k:
        return "base"
    return "text"


def patch_plymouth(theme, new_name, desc, flavor, bar):
    text = theme.conf_text
    text = re.sub(r"^Name(\[[^]]*\])?=.*\n?", "", text, flags=re.M)
    text = re.sub(r"^Description(\[[^]]*\])?=.*\n?", "", text, flags=re.M)
    text = re.sub(r"^(\[Plymouth Theme\]\s*\n)",
                  f"\\1Name={new_name}\nDescription={desc}\n", text, count=1, flags=re.M)
    comment = f"Catppuccin {FLAVOR_TITLES[flavor]} recolour of {theme.title}"
    old = re.search(r"^Comment=(.*)$", text, flags=re.M)
    if old:
        text = text.replace(old.group(0), f"Comment={comment} ({old.group(1).strip()})", 1)
    else:
        text = re.sub(r"^(Description=.*\n)", f"\\1Comment={comment}\n", text, count=1, flags=re.M)
    text = re.sub(r"^(\s*ImageDir\s*=).*$", rf"\g<1>{INSTALL_DIR}/{new_name}", text, flags=re.M)
    text = re.sub(r"^(\s*ScriptFile\s*=).*$", rf"\g<1>{INSTALL_DIR}/{new_name}/{new_name}.script",
                  text, flags=re.M)
    if theme.module == "two-step":
        text = re.sub(r"^(\s*(\w*Color)\s*=\s*)(0x[0-9a-fA-F]{6,8})\s*$",
                      lambda m: m.group(1) + plymouth_colour(
                          flavor, colour_key_target(m.group(2), bar), m.group(3)),
                      text, flags=re.M)
        if not re.search(r"^\s*BackgroundStartColor", text, flags=re.M):
            base = plymouth_colour(flavor, "base", "0x000000")
            text = re.sub(r"^(\[two-step\]\s*\n)",
                          f"\\1BackgroundStartColor={base}\nBackgroundEndColor={base}\n",
                          text, count=1, flags=re.M)
    return text


def write_theme(theme, new_name, flavor, acc, bar, dst_dir):
    if dst_dir.exists():
        shutil.rmtree(dst_dir)
    dst_dir.mkdir(parents=True)
    skip = {theme.conf_file.name, theme.script.name if theme.script else None}
    for f in theme.dir.iterdir():                # fonts, licences, ... (symlinks followed)
        if f.is_file() and f.suffix != ".png" and f.name not in skip:
            shutil.copy(f, dst_dir / f.name)
    desc = f"{theme.title} - Catppuccin {FLAVOR_TITLES[flavor]}" + (f" {acc}" if acc else "")
    (dst_dir / f"{new_name}.plymouth").write_text(patch_plymouth(theme, new_name, desc, flavor, bar))
    if theme.script:
        (dst_dir / f"{new_name}.script").write_text(patch_script(theme.script.read_text(), flavor))


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


# ------------------------------------------------------------------- preview
def preview_sheet(theme, plan, base, out):
    """One row per image group: original (over its background) | recoloured (over base)."""
    rows = []
    for g, (src_bg, keys, targets) in plan.items():
        paths = theme.groups[g]
        if g == UI_GROUP:   # the largest UI image is the most telling
            path = max(paths, key=lambda p: Image.open(p).size[0] * Image.open(p).size[1]
                       if Image.open(p).size[0] < 4000 else 0)
        else:
            path = paths[len(paths) // 2]
        im = Image.open(path).convert("RGBA")
        before = Image.new("RGBA", im.size, tuple(int(v) for v in src_bg) + (255,))
        before.alpha_composite(im)
        after = Image.new("RGBA", im.size, tuple(int(v) for v in base) + (255,))
        after.alpha_composite(recolor_image(path, src_bg, keys, targets, base).convert("RGBA"))
        scale = min(240 / im.height, 560 / im.width, 8)
        size = (max(1, round(im.width * scale)), max(1, round(im.height * scale)))
        rows.append((before.resize(size), after.resize(size)))
    W = max(a.width for a, _ in rows) * 2 + 8
    H = sum(a.height + 8 for a, _ in rows)
    sheet = Image.new("RGB", (W, H), (69, 71, 90))
    y = 0
    for a, b in rows:
        sheet.paste(a.convert("RGB"), (0, y))
        sheet.paste(b.convert("RGB"), (W // 2 + 4, y))
        y += a.height + 8
    sheet.save(out)


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
        description="Recolour Plymouth themes with Catppuccin.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"flavors: {', '.join(FLAVORS)}\naccents: {', '.join(ACCENTS)}\n"
               f"targets: {', '.join(TARGETS)}")
    p.add_argument("themes", nargs="*", default=DEFAULT_THEMES, metavar="THEME",
                   help="theme folder, or adi1090x theme name (default: hexa_retro infinite_seal)")
    p.add_argument("-f", "--flavor", nargs="+", default=["mocha"], metavar="FLAVOR",
                   help="one or more flavors, or 'all' (default: mocha)")
    p.add_argument("-a", "--accent", nargs="+", default=["all"], metavar="ACCENT",
                   help="accent(s) for colours mapped to 'accent', or 'all' (default: all)")
    p.add_argument("-m", "--map", nargs="+", default=[], metavar="NAME=TARGET",
                   help="override the mapping: white=mauve, ui.white=text, '#ffad03=peach'")
    p.add_argument("-s", "--suffix", default="", help="extra suffix for the theme names")
    p.add_argument("--bar", metavar="COLOUR", help="progress bar colour")
    p.add_argument("--no-status", action="store_true", help="skip the -status variants")
    p.add_argument("--detect", action="store_true",
                   help="(re)detect colours, overwrite configs/<theme>.toml, then stop")
    p.add_argument("--preview", action="store_true",
                   help="only render a before/after image per theme into <out>/previews/")
    p.add_argument("--list", action="store_true", help="list adi1090x themes and exit")
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

    jobs, status = [], []
    for arg in a.themes:
        theme = Theme(resolve_theme(arg, a.src))
        if not theme.groups:
            print(f"{theme.title}: no PNG images, nothing to recolour")
            continue
        if a.detect or not config_path(theme.name).exists():
            print(f"Detecting colours of {theme.title} ...", flush=True)
            save_config(theme, detect(theme))
            print(f"  -> {config_path(theme.name)}")
        cfg = load_config(theme)
        apply_maps(cfg, a.map)
        print_mapping(theme, cfg)
        if a.detect:
            continue

        uses_accent = any(c["target"] == "accent"
                          for grp in cfg["groups"].values() for c in grp["colors"].values())
        main_colours = [c["target"] for grp in cfg["groups"].values()
                        for c in sorted(grp["colors"].values(), key=lambda c: -c.get("share", 0))
                        if c["target"] in ACCENTS]
        with_status = not a.no_status and theme.adi_template
        if not a.no_status and not theme.adi_template and not a.preview:
            print("  (no -status variant: only for adi1090x-style script themes)")
        for flv in a.flavor:
            base = rgb(flv, "base")
            for acc in (a.accent if uses_accent else [None]):
                out_name = "-".join(x for x in (f"catppuccin-{flv}-{theme.slug}", acc, a.suffix) if x)
                # bar colour: option > config > accent > most common colour target
                bar = a.bar or cfg["bar"] or acc or (main_colours[0] if main_colours else "blue")
                bar = acc if bar == "accent" else bar
                plan = {}
                for g, grp in cfg["groups"].items():
                    if g not in theme.groups:
                        continue
                    keys = np.array([hex2rgb(c["source"]) for c in grp["colors"].values()])
                    targets = np.array([rgb(flv, acc if c["target"] == "accent" else c["target"])
                                        for c in grp["colors"].values()])
                    plan[g] = (hex2rgb(grp["background"]), keys, targets)
                if a.preview:
                    (a.out / "previews").mkdir(parents=True, exist_ok=True)
                    out = a.out / "previews" / f"{out_name}.png"
                    preview_sheet(theme, plan, base, out)
                    print(f"  preview: {out}")
                    continue
                write_theme(theme, out_name, flv, acc, bar, a.out / out_name)
                for g, (src_bg, keys, targets) in plan.items():
                    jobs += [(p, a.out / out_name / p.name, src_bg, keys, targets, base)
                             for p in theme.groups[g]]
                status.append(((a.out / out_name, flv, bar, cfg["bar_width"], cfg["bar_gap"]),
                               with_status))

    if not jobs:
        return
    print(f"{len(status)} theme(s), {len(jobs)} images", flush=True)
    with Pool() as pool:
        for i, _ in enumerate(pool.imap_unordered(_job, jobs, chunksize=8), 1):
            if i % 500 == 0 or i == len(jobs):
                print(f"{i}/{len(jobs)} images", flush=True)
    for args, with_st in status:
        if with_st:
            write_status_variant(*args)
        print(f"  {args[0].name}" + (f"  (+ {args[0].name}-status)" if with_st else ""))


if __name__ == "__main__":
    main()
