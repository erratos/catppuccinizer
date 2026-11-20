"""KDE splash target: recolour a Plasma splash screen (KSplash).

A splash screen is the contents/splash/ folder of a Plasma look-and-feel
package: Splash.qml plus images. Colours are recoloured everywhere:
- QML and SVG/SVGZ colours: grays go to the Catppuccin neutral ramp
  (base ... text, by lightness), the most used saturated colour becomes the
  accent, the others the closest Catppuccin hue;
- PNG/JPEG images: like the image target (keys for flat art, LUT for photos);
- animated GIFs and WebPs: frame by frame, with the same mapping for every
  frame (frames are streamed, so long animations do not fill the memory).
The result is a new look-and-feel package containing only the splash screen.
"""
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np

from ..core import naming, recolor
from ..core.detect import detect_group
from ..core.formats import (RASTER, anim_frames, anim_info, anim_sample, collect_text_colours,
                            is_animated, recolour_text_file, save_animation, text_files)
from ..core.mapping import (apply_maps, map_colour_counts, note_accent_ignored, print_colours,
                            resolve_target, uses_accent)
from ..core.palette import FLAVOR_TITLES, hex2rgb, rgb, rgb2hex
from ..core.target import Target

SEARCH = [Path.home() / ".local/share/plasma/look-and-feel", Path("/usr/share/plasma/look-and-feel")]
USER_DIR = SEARCH[0]


class KSplashTarget(Target):
    name = "ksplash"
    help = "recolour a KDE Plasma splash screen"
    default_accent = ("mauve",)
    accent_also = "the QML / SVG colours mapped to accent"

    def add_arguments(self, p):
        p.add_argument("theme", nargs="?", default="org.kde.breeze.desktop", metavar="THEME",
                       help="look-and-feel id or folder (default: org.kde.breeze.desktop)")
        recolor.add_method_arguments(p)
        p.add_argument("--list", action="store_true", help="list installed splash screens and exit")
        p.add_argument("--install", action="store_true",
                       help=f"copy to {USER_DIR} and select it as the splash screen")
        p.add_argument("--test", action="store_true", help="show the result with ksplashqml --test")

    def check(self, a):
        if (a.install or a.test) and (len(a.flavor) > 1 or len(a.accent) > 1):
            raise SystemExit("--install / --test need a single flavour and a single accent")

    def run(self, a):
        run(a)

    def sources(self):
        return [{"value": pid, "label": package_name(d), "note": str(d.parent)}
                for pid, d in sorted(splash_packages().items())]


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


def metadata(pkg, pid, name, description):
    """metadata.json of the recoloured package: keeps the original authors, licence
    and website (it is a derived work), adds catppuccinizer as an author."""
    try:
        orig = json.loads((pkg / "metadata.json").read_text()).get("KPlugin", {})
    except (OSError, ValueError):
        orig = {}
    authors = [x for x in orig.get("Authors", []) if isinstance(x, dict) and x.get("Name")]
    plugin = {"Id": pid, "Name": name, "Category": "Plasma Look And Feel",
              "Description": description,
              "License": orig.get("License") or "unknown (see the original package)",
              "Version": "1.0", "EnabledByDefault": True,
              "Authors": [*authors, {"Name": "catppuccinizer (Catppuccin recolour)"}]}
    if orig.get("Website"):
        plugin["Website"] = orig["Website"]
    return {"KPackageStructure": "Plasma/LookAndFeel", "KPlugin": plugin}


def list_packages():
    for pid, d in sorted(splash_packages().items()):
        print(f"{pid:42s} {package_name(d)}  ({d.parent})")


def preview_group(preview, rasters):
    """Colours of the animation the preview is a still of (the one that rebuilds it
    best), or None when no animation explains it well enough."""
    scored = [(recolor.fit_error(preview, g)[0], g) for m, g, _ in rasters.values() if m == "anim"]
    if not scored:
        return None
    err, grp = min(scored, key=lambda x: x[0])
    return grp if err < 2 * recolor.FIT_THRESHOLD else None


# ---------------------------------------------------------------------- main
def run(a):
    if a.list:
        return list_packages()
    if a.preview:
        print("note: --preview is not available for splash screens, use --test to see the result")
    pkg = resolve(a.theme)
    splash = pkg / "contents/splash"
    title = package_name(pkg)
    slug = naming.slug(title, "splash")
    print(f"{title} ({pkg})")

    vector = {"groups": {"vector": {"colors": map_colour_counts(
        collect_text_colours(text_files(splash)))}}}
    apply_maps(vector, a.map, strict=False)
    vcolors = vector["groups"]["vector"]["colors"]
    if vcolors:
        print("  QML / SVG colours")
        print_colours(vcolors)

    tmp = Path(tempfile.mkdtemp(prefix="catppuccinize-"))
    rasters = {}                                   # path -> ("anim"|method, grp, extra)
    previews = pkg / "contents/previews/splash.png"
    for f in [*sorted(splash.rglob("*")), *([previews] if previews.exists() else [])]:
        ext = f.suffix.lower()
        if f == previews and (grp := preview_group(f, rasters)):
            # the preview is a still of an animation: same colours and -m, so it
            # matches the splash in System Settings (alone it may go to the LUT)
            rasters[f] = ("keys", grp, None)
            print(f"  {f.relative_to(pkg)}: keys (colours of the animation)")
            continue
        if is_animated(f):
            n, durations, loop = anim_info(f)
            grp = detect_group(anim_sample(f, n, tmp), is_ui=False)
            cfg = {"groups": {"image": grp}}
            apply_maps(cfg, a.map, strict=False)
            rasters[f] = ("anim", grp, (n, durations, loop))
            print(f"  {f.relative_to(pkg)}: {n} frames")
        elif ext in RASTER:
            a.strict_map = False
            method, grp = recolor.plan(f, a, verbose=False)
            rasters[f] = (method, grp, None)
            print(f"  {f.relative_to(pkg)}: {method}")
        else:
            continue
        if rasters[f][1] is not None and rasters[f][0] not in recolor.LUT_METHODS:
            print_colours(rasters[f][1]["colors"], show_share=False)

    accent_used = uses_accent(vcolors) or any(
        m not in recolor.LUT_METHODS and uses_accent(g["colors"]) for m, g, _ in rasters.values())
    if not accent_used:
        note_accent_ignored(a)
    built = []
    done = {}      # (image, flavour, accent or None) -> recoloured file, copied for other accents
    for flv in a.flavor:
        for acc in (a.accent if accent_used else [None]):
            pid = naming.output_name(flv, slug, acc, a.suffix)
            name = (f"{title} - Catppuccin {FLAVOR_TITLES[flv]}" + (f" {acc.title()}" if acc else "")
                    + (f" ({a.suffix})" if a.suffix else ""))
            dst = a.out / pid
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(splash, dst / "contents/splash",
                            ignore=shutil.ignore_patterns("*.qmlc", "*.jsc"))  # stale caches
            if previews.exists():
                (dst / "contents/previews").mkdir(parents=True)
                shutil.copy(previews, dst / "contents/previews/splash.png")
            for lic in pkg.iterdir():                # the original licence travels with it
                if lic.is_file() and re.match(r"(licen[cs]e|copying)", lic.name, re.I):
                    shutil.copy(lic, dst / lic.name)
            (dst / "metadata.json").write_text(json.dumps(metadata(
                pkg, pid, name, f"Catppuccin {FLAVOR_TITLES[flv]} recolour of the "
                                f"{title} splash screen"), indent=4) + "\n")

            lookup = {c["source"]: rgb2hex(resolve_target(flv, acc, c["target"]))
                      for c in vcolors.values()}
            for f in text_files(dst / "contents/splash"):
                recolour_text_file(f, lookup)

            for src, (method, grp, extra) in rasters.items():
                rel = src.relative_to(splash) if src.is_relative_to(splash) else None
                out = dst / "contents/splash" / rel if rel else dst / "contents/previews/splash.png"
                # an image that ignores the accent is the same in every accent's package
                key = (src, flv, None if method in recolor.LUT_METHODS
                       or not uses_accent(grp["colors"]) else acc)
                if key in done:
                    shutil.copyfile(done[key], out)
                    continue
                done[key] = out
                if method == "anim":
                    n, durations, loop = extra
                    keys = np.array([hex2rgb(c["source"]) for c in grp["colors"].values()])
                    targets = np.array([resolve_target(flv, acc, c["target"])
                                        for c in grp["colors"].values()])
                    if n > 100:
                        print(f"  recolouring {n} frames of {src.name}…", flush=True)
                    frames = recolor.recolor_frames(
                        anim_frames(src), hex2rgb(grp["background"]), keys, targets,
                        rgb(flv, "base"), quantize=out.suffix.lower() == ".gif",
                        parallel=n > 48)
                    save_animation(frames, n, out, durations, loop)
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
