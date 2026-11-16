"""KDE splash target: recolour a Plasma splash screen (KSplash).

A splash screen is the contents/splash/ folder of a Plasma look-and-feel
package: Splash.qml plus images. Colours are recoloured everywhere:
- QML and SVG/SVGZ colours: grays go to the Catppuccin neutral ramp
  (base ... text, by lightness), the most used saturated colour becomes the
  accent, the others the closest Catppuccin hue;
- PNG/JPEG images: like the image target (keys for flat art, LUT for photos);
- animated GIFs: frame by frame, with the same mapping for every frame.
The result is a new look-and-feel package containing only the splash screen.
"""
import colorsys
import gzip
import json
import re
import shutil
import subprocess
import tempfile
from collections import Counter
from pathlib import Path

import numpy as np
from PIL import Image, ImageSequence

from . import ROOT
from . import image as img
from .colours import apply_maps, detect_group, recolor_image
from .palette import (AUTO_HUE_TARGETS, FLAVOR_TITLES, PALETTES, colour_name, hex2rgb,
                      hue_dist, hue_of, rgb, rgb2hex, srgb_to_oklab)

SEARCH = [Path.home() / ".local/share/plasma/look-and-feel", Path("/usr/share/plasma/look-and-feel")]
USER_DIR = SEARCH[0]
RAMP = ["base", "surface0", "surface1", "surface2", "overlay0", "overlay1", "overlay2",
        "subtext0", "subtext1", "text"]
NAMED = {"black": "#000000", "white": "#ffffff", "gray": "#808080", "grey": "#808080"}
RASTER = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}

# colour syntaxes
SVG_RE = re.compile(r"((?:fill|stroke|stop-color|flood-color|lighting-color|color)\s*[:=]\s*[\"']?)"
                    r"(#[0-9a-fA-F]{8}|#[0-9a-fA-F]{6}|#[0-9a-fA-F]{3}\b|white|black)", re.I)
QML_HEX_RE = re.compile(r"\"(#[0-9a-fA-F]{8}|#[0-9a-fA-F]{6}|#[0-9a-fA-F]{3})\"")
QML_NAMED_RE = re.compile(r"(\b(?:color|[a-zA-Z]*Color)\s*:\s*)\"(black|white|gray|grey)\"")
QML_RGBA_RE = re.compile(r"Qt\.rgba\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*\)")


def add_arguments(p):
    p.add_argument("theme", nargs="?", default="org.kde.breeze.desktop", metavar="THEME",
                   help="look-and-feel id or folder (default: org.kde.breeze.desktop)")
    img.add_method_arguments(p)
    p.add_argument("-s", "--suffix", default="", help="extra suffix for the package id")
    p.add_argument("--list", action="store_true", help="list installed splash screens and exit")
    p.add_argument("--install", action="store_true",
                   help=f"copy to {USER_DIR} and select it as the splash screen")
    p.add_argument("--test", action="store_true", help="show the result with ksplashqml --test")
    p.set_defaults(out_default=ROOT / "themes", default_accent=["mauve"])


def check_args(a):
    if (a.install or a.test) and (len(a.flavor) > 1 or len(a.accent) > 1):
        raise SystemExit("--install / --test need a single flavour and a single accent")


# ------------------------------------------------------------------ packages
def splash_packages():
    found = {}
    for base in reversed(SEARCH):                  # user packages override system ones
        if base.is_dir():
            for d in base.iterdir():
                if (d / "contents/splash/Splash.qml").exists():
                    found[d.name] = d
    return found


def resolve(arg):
    p = Path(arg).expanduser()
    if (p / "contents/splash/Splash.qml").exists():
        return p.resolve()
    if (p / "Splash.qml").exists():                # the splash folder itself
        return p.resolve().parent.parent
    pkgs = splash_packages()
    if arg in pkgs:
        return pkgs[arg]
    raise SystemExit(f"No splash screen '{arg}' (see --list, or give a folder)")


def package_name(pkg):
    try:
        return json.loads((pkg / "metadata.json").read_text())["KPlugin"]["Name"]
    except (OSError, KeyError, ValueError):
        return pkg.name


def list_packages():
    for pid, d in sorted(splash_packages().items()):
        print(f"{pid:42s} {package_name(d)}  ({d.parent})")


# ------------------------------------------------------------ vector colours
def parse_hex(h, qml):
    """'#rgb' / '#rrggbb' / '#aarrggbb' (QML) or '#rrggbbaa' (SVG) -> (rgb hex, alpha hex, layout)."""
    h = h.lstrip("#").lower()
    if len(h) == 3:
        return "#" + "".join(c * 2 for c in h), None
    if len(h) == 8:
        return ("#" + h[2:], h[:2]) if qml else ("#" + h[:6], h[6:])
    return "#" + h, None


def text_files(splash):
    for f in sorted(splash.rglob("*")):
        if f.suffix.lower() in (".qml", ".svg", ".svgz") and f.is_file():
            yield f


def read_text(f):
    return gzip.decompress(f.read_bytes()).decode() if f.suffix.lower() == ".svgz" else f.read_text()


def write_text(f, text):
    if f.suffix.lower() == ".svgz":
        f.write_bytes(gzip.compress(text.encode()))
    else:
        f.write_text(text)


def collect_vector_colours(splash):
    counts = Counter()
    for f in text_files(splash):
        text, qml = read_text(f), f.suffix.lower() == ".qml"
        if qml:
            for m in QML_HEX_RE.finditer(text):
                counts[parse_hex(m.group(1), True)[0]] += 1
            for m in QML_NAMED_RE.finditer(text):
                counts[NAMED[m.group(2).lower()]] += 1
            for m in QML_RGBA_RE.finditer(text):
                counts[rgb2hex([float(m.group(i)) * 255 for i in (1, 2, 3)])] += 1
        else:
            for m in SVG_RE.finditer(text):
                v = m.group(2).lower()
                counts[NAMED.get(v) or parse_hex(v, False)[0]] += 1
    return counts


def vector_mapping(counts):
    """{name: {source, target, count}}: grays -> neutral ramp, main hue -> accent."""
    colors, saturated = {}, []
    for hx, n in counts.most_common():
        c = hex2rgb(hx)
        h, s, v = colorsys.rgb_to_hsv(*(c / 255))
        name, i = colour_name(h * 360, s, v), 2
        base_name = name
        while name in colors:
            name, i = f"{base_name}-{i}", i + 1
        entry = {"source": hx, "count": n}
        if s < 0.25 or v < 0.15:
            # very dark (<= 0.2 Oklab lightness) -> base, near white (>= 0.95) -> text
            L = float(np.clip((srgb_to_oklab(c)[0] - 0.2) / 0.75, 0, 1))
            entry["target"] = RAMP[int(round(L * (len(RAMP) - 1)))]
        else:
            saturated.append(name)
        colors[name] = entry
    ref = {t: hue_of(rgb("mocha", t)) for t in AUTO_HUE_TARGETS}
    for k, name in enumerate(saturated):
        if k == 0:
            colors[name]["target"] = "accent"
        else:
            hue = hue_of(hex2rgb(colors[name]["source"]))
            colors[name]["target"] = min(ref, key=lambda t: hue_dist(hue, ref[t]))
    return colors


def recolour_text(text, qml, lookup):
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
            new = hex2rgb(lookup.get(rgb2hex([float(m.group(i)) * 255 for i in (1, 2, 3)]),
                                     rgb2hex([float(m.group(i)) * 255 for i in (1, 2, 3)]))) / 255
            return f"Qt.rgba({new[0]:.3f}, {new[1]:.3f}, {new[2]:.3f}, {m.group(4)})"
        return QML_RGBA_RE.sub(sub_rgba, text)

    def sub_svg(m):
        v = m.group(2).lower()
        if v in NAMED:
            return m.group(1) + lookup[NAMED[v]]
        return m.group(1) + sub_hex(v)
    return SVG_RE.sub(sub_svg, text)


# ------------------------------------------------------------------- rasters
def gif_frames(path, tmp):
    im = Image.open(path)
    frames, durations = [], []
    for k, fr in enumerate(ImageSequence.Iterator(im)):
        f = tmp / f"{path.stem}-{k:04d}.png"
        fr.convert("RGBA").save(f)
        frames.append(f)
        durations.append(fr.info.get("duration", im.info.get("duration", 50)))
    return frames, durations, im.info.get("loop", 0)


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


def target_rgb(flavor, accent, name):
    return rgb(flavor, accent if name == "accent" else name)


# ---------------------------------------------------------------------- main
def run(a):
    if a.list:
        return list_packages()
    if a.preview:
        print("note: --preview is not available for splash screens, use --test to see the result")
    pkg = resolve(a.theme)
    splash = pkg / "contents/splash"
    title = package_name(pkg)
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-") or "splash"
    print(f"{title} ({pkg})")

    vector = {"groups": {"vector": {"colors": vector_mapping(collect_vector_colours(splash))}}}
    apply_maps(vector, a.map, strict=False)
    vcolors = vector["groups"]["vector"]["colors"]
    if vcolors:
        print("  QML / SVG colours")
        for n, c in vcolors.items():
            print(f"    {n:10s} {c['source']} -> {c['target']}  (x{c['count']})")

    tmp = Path(tempfile.mkdtemp(prefix="catppuccinize-"))
    rasters = {}                                   # path -> ("gif"|method, grp, extra)
    previews = pkg / "contents/previews/splash.png"
    for f in sorted([*splash.rglob("*"), *([previews] if previews.exists() else [])]):
        ext = f.suffix.lower()
        if ext == ".gif":
            frames, durations, loop = gif_frames(f, tmp)
            grp = detect_group(frames, is_ui=False)
            cfg = {"groups": {"image": grp}}
            apply_maps(cfg, a.map, strict=False)
            rasters[f] = ("gif", grp, (frames, durations, loop))
            print(f"  {f.relative_to(pkg)}: {len(frames)} frames")
        elif ext in RASTER:
            a.strict_map = False
            method, grp = img.plan_image(f, a, verbose=False)
            rasters[f] = (method, grp, None)
            print(f"  {f.relative_to(pkg)}: {method}")
        else:
            continue
        if rasters[f][1] is not None and rasters[f][0] != "lut":
            for n, c in rasters[f][1]["colors"].items():
                print(f"    {n:10s} {c['source']} -> {c['target']}")

    uses_accent = any(c["target"] == "accent" for c in vcolors.values()) or any(
        m != "lut" and any(c["target"] == "accent" for c in g["colors"].values())
        for m, g, _ in rasters.values())
    built = []
    for flv in a.flavor:
        for acc in (a.accent if uses_accent else [None]):
            pid = "-".join(x for x in (f"catppuccin-{flv}-{slug}", acc, a.suffix) if x)
            name = f"{title} - Catppuccin {FLAVOR_TITLES[flv]}" + (f" {acc.title()}" if acc else "")
            dst = a.out / pid
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(splash, dst / "contents/splash",
                            ignore=shutil.ignore_patterns("*.qmlc", "*.jsc"))  # stale caches
            if previews.exists():
                (dst / "contents/previews").mkdir(parents=True)
                shutil.copy(previews, dst / "contents/previews/splash.png")
            (dst / "metadata.json").write_text(json.dumps({
                "KPackageStructure": "Plasma/LookAndFeel",
                "KPlugin": {"Id": pid, "Name": name, "Category": "Plasma Look And Feel",
                            "Description": f"Catppuccin {FLAVOR_TITLES[flv]} recolour of the "
                                           f"{title} splash screen",
                            "License": "GPL-3.0", "Version": "1.0", "EnabledByDefault": True,
                            "Authors": [{"Name": "catppuccinizer"}]}}, indent=4) + "\n")

            lookup = {c["source"]: rgb2hex(target_rgb(flv, acc, c["target"])) for c in vcolors.values()}
            for f in text_files(dst / "contents/splash"):
                write_text(f, recolour_text(read_text(f), f.suffix.lower() == ".qml", lookup))

            for src, (method, grp, extra) in rasters.items():
                rel = src.relative_to(splash) if src.is_relative_to(splash) else None
                out = dst / "contents/splash" / rel if rel else dst / "contents/previews/splash.png"
                if method == "gif":
                    frames, durations, loop = extra
                    keys = np.array([hex2rgb(c["source"]) for c in grp["colors"].values()])
                    targets = np.array([target_rgb(flv, acc, c["target"]) for c in grp["colors"].values()])
                    ims = [rgba_to_p(recolor_image(fr, hex2rgb(grp["background"]), keys, targets,
                                                   rgb(flv, "base")).convert("RGBA")) for fr in frames]
                    ims[0].save(out, save_all=True, append_images=ims[1:], duration=durations,
                                loop=loop, disposal=2, transparency=255, optimize=False)
                else:
                    im = img.render(src, method, grp, flv, acc, a)
                    if out.suffix.lower() in (".jpg", ".jpeg"):
                        im.convert("RGB").save(out, quality=95)
                    else:
                        im.save(out)
            built.append(dst)
            print(f"  -> {dst}  ({name})")
    shutil.rmtree(tmp, ignore_errors=True)

    if a.install and built:
        target = USER_DIR / built[0].name
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(built[0], target)
        subprocess.run(["kwriteconfig6", "--file", "ksplashrc", "--group", "KSplash",
                        "--key", "Theme", built[0].name], check=False)
        subprocess.run(["kwriteconfig6", "--file", "ksplashrc", "--group", "KSplash",
                        "--key", "Engine", "KSplashQML"], check=False)
        print(f"  installed in {target} and selected as splash screen")
    if a.test and built:
        print("  showing it with ksplashqml (closes by itself, or click it)")
        subprocess.run(["ksplashqml", "--test", "--window", str(built[0])], check=False)
