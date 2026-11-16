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
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np

from ..core import recolor
from ..core.detect import detect_group
from ..core.formats import (RASTER, collect_text_colours, gif_frames, recolour_text_file,
                            save_gif, text_files)
from ..core.mapping import (apply_maps, map_colour_counts, print_colours, resolve_target,
                            uses_accent)
from ..core.palette import FLAVOR_TITLES, hex2rgb, rgb, rgb2hex
from ..core.target import Target

SEARCH = [Path.home() / ".local/share/plasma/look-and-feel", Path("/usr/share/plasma/look-and-feel")]
USER_DIR = SEARCH[0]


class KSplashTarget(Target):
    name = "ksplash"
    help = "recolour a KDE Plasma splash screen"
    default_accent = ("mauve",)

    def add_arguments(self, p):
        p.add_argument("theme", nargs="?", default="org.kde.breeze.desktop", metavar="THEME",
                       help="look-and-feel id or folder (default: org.kde.breeze.desktop)")
        recolor.add_method_arguments(p)
        p.add_argument("-s", "--suffix", default="", help="extra suffix for the package id")
        p.add_argument("--list", action="store_true", help="list installed splash screens and exit")
        p.add_argument("--install", action="store_true",
                       help=f"copy to {USER_DIR} and select it as the splash screen")
        p.add_argument("--test", action="store_true", help="show the result with ksplashqml --test")

    def check(self, a):
        if (a.install or a.test) and (len(a.flavor) > 1 or len(a.accent) > 1):
            raise SystemExit("--install / --test need a single flavour and a single accent")

    def run(self, a):
        run(a)


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

    vector = {"groups": {"vector": {"colors": map_colour_counts(
        collect_text_colours(text_files(splash)))}}}
    apply_maps(vector, a.map, strict=False)
    vcolors = vector["groups"]["vector"]["colors"]
    if vcolors:
        print("  QML / SVG colours")
        print_colours(vcolors)

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
            method, grp = recolor.plan(f, a, verbose=False)
            rasters[f] = (method, grp, None)
            print(f"  {f.relative_to(pkg)}: {method}")
        else:
            continue
        if rasters[f][1] is not None and rasters[f][0] != "lut":
            print_colours(rasters[f][1]["colors"], show_share=False)

    accent_used = uses_accent(vcolors) or any(
        m != "lut" and uses_accent(g["colors"]) for m, g, _ in rasters.values())
    built = []
    for flv in a.flavor:
        for acc in (a.accent if accent_used else [None]):
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

            lookup = {c["source"]: rgb2hex(resolve_target(flv, acc, c["target"]))
                      for c in vcolors.values()}
            for f in text_files(dst / "contents/splash"):
                recolour_text_file(f, lookup)

            for src, (method, grp, extra) in rasters.items():
                rel = src.relative_to(splash) if src.is_relative_to(splash) else None
                out = dst / "contents/splash" / rel if rel else dst / "contents/previews/splash.png"
                if method == "gif":
                    frames, durations, loop = extra
                    keys = np.array([hex2rgb(c["source"]) for c in grp["colors"].values()])
                    targets = np.array([resolve_target(flv, acc, c["target"])
                                        for c in grp["colors"].values()])
                    save_gif([recolor.recolor_image(fr, hex2rgb(grp["background"]), keys, targets,
                                                    rgb(flv, "base")) for fr in frames],
                             out, durations, loop)
                else:
                    im = recolor.render(src, method, grp, flv, acc, a)
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


TARGET = KSplashTarget()
