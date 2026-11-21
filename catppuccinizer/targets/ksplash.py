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
--install copies it to ~/.local/share/plasma/look-and-feel/, --apply (which
installs first) selects it, --test shows it in a window, --restore selects the
previous splash screen again and removes the installed ones.
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
from ..core.mapping import (apply_maps, background_of, colour_report, map_colour_counts,
                            note_accent_ignored, print_colours, resolve_target, uses_accent)
from ..core.palette import FLAVOR_TITLES, hex2rgb, rgb, rgb2hex
from ..core.options import Option, step
from ..core.paths import state_file
from ..core.naming import check_name
from ..core.sources import item, section, tidy
from ..core.system import copy_folder, place, source_file, which
from ..core.target import Target

SEARCH = [Path.home() / ".local/share/plasma/look-and-feel", Path("/usr/share/plasma/look-and-feel")]
USER_DIR = SEARCH[0]
SETTINGS = ("Theme", "Engine")              # [KSplash] of ksplashrc


class KSplashTarget(Target):
    name = "ksplash"
    help = "recolour a KDE Plasma splash screen"
    accent_also = "the QML / SVG colours mapped to accent"
    unused_common = ("preview",)                      # --test shows the result instead

    def options(self):
        return [
            Option("theme", label="Splash screen", nargs="?", default="org.kde.breeze.desktop", metavar="THEME",
                   accept="dir", help="look-and-feel id or folder (default: org.kde.breeze.desktop)"),
            *recolor.method_options(),
            step("install", help=f"copy the result to {USER_DIR}"),
            step("apply", help="install, then select it as the splash screen",
                 explain="Here: it becomes the splash screen in ksplashrc (kwriteconfig6), "
                         "as System Settings would do; seen at the next login."),
            step("test", help="show the result in a window (ksplashqml --test)",
                 explain="Here: ksplashqml shows it in a window, which closes by itself or "
                         "on a click."),
            step("restore", help="select the previous splash screen again and remove "
                                 "the installed ones"),
        ]

    def check(self, a):
        if (a.install or a.apply or a.test) and (len(a.flavor) > 1 or len(a.accent) > 1):
            raise SystemExit("--install / --apply / --test need a single flavour and a single accent "
                             "(-f FLAVOR -a ACCENT)")

    def build(self, a):
        return build(a)

    def install(self, a, built, system):
        state = system.load_state(state_file("ksplash"))
        system.copy_tree(built[0], place(USER_DIR, built[0].name, "package id"))
        state["installed"] = sorted({*state.get("installed", []), built[0].name})
        system.save_state(state_file("ksplash"), state)

    def apply(self, a, built, system):
        state = system.load_state(state_file("ksplash"))
        current = {key: read_setting(key) for key in SETTINGS}
        if "previous" not in state and current["Theme"] not in state.get("installed", []):
            state["previous"] = current             # what restore selects again
        set_settings(system, {"Theme": built[0].name, "Engine": "KSplashQML"})
        system.save_state(state_file("ksplash"), state)

    def test(self, a, built, system):
        print("  (closes by itself, or click it)")
        system.run(["ksplashqml", "--test", "--window", built[0]])

    def restore(self, a, system):
        state = system.load_state(state_file("ksplash"))
        if not state:
            raise SystemExit(f"Nothing to restore ({state_file('ksplash')} not found: nothing was installed "
                             "or applied)")
        if "previous" in state:
            set_settings(system, state["previous"])
        for pid in state.get("installed", []):      # read back: checked like new names
            system.remove(place(USER_DIR, pid, f"package id in {state_file('ksplash')}"))
        system.save_state(state_file("ksplash"), {})

    def colours(self, a):
        return colours(a)

    def outputs(self, a):
        return outputs(a)

    def sources(self):
        try:
            active = read_setting("Theme")
        except SystemExit:                         # no kreadconfig6: nothing marked
            active = None
        return [section(f"{title} ({tidy(base)})", lambda base=base: installed(base, active))
                for title, base in zip(("Your splash screens", "System splash screens"), SEARCH)
                if base.is_dir()]


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
    if p.is_dir():
        raise SystemExit(f"{arg} is not a splash screen: no contents/splash/Splash.qml in it "
                         "(give a look-and-feel package or its contents/splash folder)")
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


def installed(base, active):
    """The splash screens of a look-and-feel folder, the selected one marked."""
    for d in sorted(base.iterdir(), key=lambda d: d.name):
        if (d / "contents/splash/Splash.qml").exists():
            preview = d / "contents/previews/splash.png"
            yield item(d.name, package_name(d), current=d.name == active,
                       thumb=preview if preview.is_file() else None)


def preview_group(preview, rasters):
    """Colours of the animation the preview is a still of (the one that rebuilds it
    best), or None when no animation explains it well enough."""
    scored = [(recolor.fit_error(preview, g)[0], g) for m, g, _ in rasters.values() if m == "anim"]
    if not scored:
        return None
    err, grp = min(scored, key=lambda x: x[0])
    return grp if err < 2 * recolor.FIT_THRESHOLD else None


# ---------------------------------------------------------------------- main
def analyse(a, pkg, tmp):
    """Colours of a splash package after -m: (QML / SVG colours, {image: (method or
    "anim", group, extra)}). Animations are sampled into tmp."""
    splash = pkg / "contents/splash"
    vector = {"groups": {"vector": {"colors": map_colour_counts(
        collect_text_colours(text_files(splash)))}}}
    apply_maps(vector, a.map, strict=False)
    vcolors = vector["groups"]["vector"]["colors"]
    if vcolors:
        print("  QML / SVG colours")
        print_colours(vcolors)

    rasters = {}                                   # path -> ("anim"|method, grp, extra)
    previews = pkg / "contents/previews/splash.png"
    for f in [*sorted(splash.rglob("*")), *([previews] if previews.exists() else [])]:
        if not source_file(f, splash if f != previews else pkg):
            continue                               # not copied either (core.system.copy_folder)
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
    return vcolors, rasters


def colours(a):
    """--colours: the QML / SVG colours, then each image and animation. The preview
    (contents/previews/splash.png) is left out when it takes an animation's colours:
    it follows that animation, -m included, so it has nothing of its own to remap."""
    pkg = resolve(a.theme)
    tmp = Path(tempfile.mkdtemp(prefix="catppuccinize-"))
    try:
        vcolors, rasters = analyse(a, pkg, tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    out = [colour_report("QML / SVG", "text", vcolors)] if vcolors else []
    for f, (method, grp, extra) in rasters.items():
        name = f.relative_to(pkg)
        if method == "anim":
            out.append(colour_report(name, "keys", grp["colors"], background=background_of(grp),
                                     note=f"animation, {extra[0]} frames"))
        elif not (f == pkg / "contents/previews/splash.png"
                  and any(g is grp for m, g, _ in rasters.values() if m == "anim")):
            out.append(recolor.colour_report(name, method, grp))
    return out


def read_setting(key):
    """Current value of a KSplash setting of ksplashrc ("" when unset)."""
    exe = which("kreadconfig6")
    if not exe:
        raise SystemExit("kreadconfig6 not found (KDE Plasma 6)")
    r = subprocess.run([exe, "--file", "ksplashrc", "--group", "KSplash", "--key", key],
                       capture_output=True, text=True, check=False)
    return r.stdout.strip()


def set_settings(system, values):
    for key, value in values.items():
        if key not in SETTINGS:
            raise SystemExit(f"Unknown KSplash setting: {key!r}")
        if value:
            check_name(value, f"KSplash {key}")
        system.run(["kwriteconfig6", "--file", "ksplashrc", "--group", "KSplash", "--key", key,
                    *([value] if value else ["--delete"])])


def accent_used(vcolors, rasters):
    return uses_accent(vcolors) or any(
        m not in recolor.LUT_METHODS and uses_accent(g["colors"]) for m, g, _ in rasters.values())


def package_id(flv, slug, acc, a):
    return naming.output_name(flv, slug, acc, a.suffix)


def outputs(a):
    """One look-and-feel package per flavour (and accent, when something uses it)."""
    pkg = resolve(a.theme)
    slug = naming.slug(package_name(pkg), "splash")
    tmp = Path(tempfile.mkdtemp(prefix="catppuccinize-"))
    try:
        used = accent_used(*analyse(a, pkg, tmp))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return [naming.planned(a.out / package_id(flv, slug, acc, a), folder=True)
            for flv in a.flavor for acc in (a.accent if used else [None])]


def build(a):
    pkg = resolve(a.theme)
    splash = pkg / "contents/splash"
    title = package_name(pkg)
    slug = naming.slug(title, "splash")
    print(f"{title} ({pkg})")

    tmp = Path(tempfile.mkdtemp(prefix="catppuccinize-"))
    vcolors, rasters = analyse(a, pkg, tmp)
    preview_src = source_file(pkg / "contents/previews/splash.png", pkg)

    used = accent_used(vcolors, rasters)
    if not used:
        note_accent_ignored(a)
    built = []
    done = {}      # (image, flavour, accent or None) -> recoloured file, copied for other accents
    for flv in a.flavor:
        for acc in (a.accent if used else [None]):
            pid = package_id(flv, slug, acc, a)
            name = (f"{title} - Catppuccin {FLAVOR_TITLES[flv]}" + (f" {acc.title()}" if acc else "")
                    + (f" ({a.suffix})" if a.suffix else ""))
            dst = a.out / pid
            if dst.exists():
                shutil.rmtree(dst)
            # no link followed out of the package; *.qmlc / *.jsc: stale caches
            copy_folder(splash, dst / "contents/splash", ignore=("*.qmlc", "*.jsc"))
            if preview_src:
                (dst / "contents/previews").mkdir(parents=True)
                shutil.copyfile(preview_src, dst / "contents/previews/splash.png")
            for lic in pkg.iterdir():                # the original licence travels with it
                if re.match(r"(licen[cs]e|copying)", lic.name, re.I) and (real := source_file(lic, pkg)):
                    shutil.copyfile(real, dst / lic.name)
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
    return built or None


TARGET = KSplashTarget()
