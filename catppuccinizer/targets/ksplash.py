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
previous splash screen again and removes the installed ones. --preview shows the
thumbnail of System Settings (or a frame of an animation) before and after,
--preview-animation the longest animation, without building the package.
"""
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from ..core import naming, recolor
from ..core.detect import detect_group, detect_params
from ..core.formats import (RASTER, anim_frames, anim_info, anim_sample, is_animated,
                            recolour_text_file, save_animation, text_files)
from ..core.mapping import (apply_maps, background_of, colour_report, note_accent_ignored,
                            print_colours, text_colours, text_lookup, uses_accent)
from ..core.palette import FLAVOR_TITLES
from ..core.options import PREVIEW_ANIMATION, Option, previewing, step
from ..core.parts import accent_sets, check_parts, note_unused, single
from ..core.paths import state_file
from ..core.naming import check_name
from ..core.sources import item, section, theme_folders, tidy
from ..core.system import copy_folder, source_file, which
from ..core.target import Target

SEARCH = [Path.home() / ".local/share/plasma/look-and-feel", Path("/usr/share/plasma/look-and-feel")]
USER_DIR = SEARCH[0]
SETTINGS = ("Theme", "Engine")              # [KSplash] of ksplashrc
MARKER = "contents/splash/Splash.qml"       # what makes a look-and-feel package a splash screen


# -a PART=ACCENT (core.parts): the QML / SVG colours, the animations, the other images
PARTS = ("vector", "animations", "images")


class KSplashTarget(Target):
    name = "ksplash"
    help = "recolour a KDE Plasma splash screen"
    accent_also = "the QML / SVG colours mapped to accent"

    def options(self):
        return [
            Option("theme", label="Splash screen", nargs="?", default="org.kde.breeze.desktop", metavar="THEME",
                   accept="dir", help="look-and-feel id or folder (default: org.kde.breeze.desktop)"),
            *recolor.method_options(keys_always=True),
            PREVIEW_ANIMATION,
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
        check_parts(a, PARTS)
        if (a.install or a.apply or a.test) and (len(a.flavor) > 1 or not single(a, PARTS)):
            raise SystemExit("--install / --apply / --test need a single flavour and a single accent "
                             "(-f FLAVOR -a ACCENT)")
        if a.preview_animation and not animations(resolve(a.theme)):
            raise SystemExit("--preview-animation: this splash screen has no animated GIF or "
                             "WebP (its QML moves it: see it with --test)")
        if a.preview and not stills(resolve(a.theme)):
            raise SystemExit("--preview: this splash screen has no image to show (only QML and "
                             "SVG: see it with --test)")

    def build(self, a):
        return build(a)

    def install(self, a, built, system):
        system.install_tree(built[0], USER_DIR, state_file("ksplash"), "package id")

    def apply(self, a, built, system):
        current = {key: read_setting(key) for key in SETTINGS}
        system.keep_previous(state_file("ksplash"), current, current["Theme"])   # for restore
        set_settings(system, {"Theme": built[0].name, "Engine": "KSplashQML"})

    def test(self, a, built, system):
        print("  (closes by itself, or click it)")
        system.run(["ksplashqml", "--test", "--window", built[0]])

    def restore(self, a, system):
        state, installed = system.restore_state(state_file("ksplash"), "package id")
        if "previous" in state:
            set_settings(system, state["previous"])
        system.uninstall(state_file("ksplash"), USER_DIR, installed)

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
    # user packages override system ones
    return {d.name: d for base in reversed(SEARCH) for d in theme_folders(base, MARKER)}


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
    for d in theme_folders(base, MARKER):
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


def animations(pkg):
    """The animated GIFs and WebPs of the splash screen."""
    splash = pkg / "contents/splash"
    return [f for f in sorted(splash.rglob("*")) if source_file(f, splash) and is_animated(f)]


def stills(pkg):
    """What --preview can show: the preview (contents/previews/splash.png), or images."""
    splash = pkg / "contents/splash"
    return ([pkg / "contents/previews/splash.png"] if source_file(pkg / "contents/previews/splash.png", pkg)
            else []) + [f for f in sorted(splash.rglob("*"))
                        if f.suffix.lower() in RASTER and source_file(f, splash)]


# ---------------------------------------------------------------------- main
def analyse(a, pkg, tmp):
    """Colours of a splash package after -m: (QML / SVG colours, {image: (method or
    "anim", group, extra)}). Animations are sampled into tmp."""
    splash = pkg / "contents/splash"
    vcolors = text_colours(text_files(splash), a.map, strict=False, group="vector")
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
            grp = detect_group(anim_sample(f, n, tmp), is_ui=False,
                               params=detect_params(a.separation))
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
    out = [colour_report("QML / SVG", "text", vcolors, part="vector")] if vcolors else []
    for f, (method, grp, extra) in rasters.items():
        name = f.relative_to(pkg)
        if method == "anim":
            out.append(colour_report(name, "keys", grp["colors"], background=background_of(grp),
                                     note=f"animation, {extra[0]} frames", part="animations"))
        elif part_of(method, grp, rasters) == "images":
            out.append(recolor.colour_report(name, method, grp, part="images"))
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


def part_of(method, grp, rasters):
    """The part of an image: the animations, with the preview when it is a still of
    one (it takes its colours), else the images."""
    if method == "anim" or any(g is grp for m, g, _ in rasters.values() if m == "anim"):
        return "animations"
    return "images"


def results(a, vcolors, rasters):
    """(parts that use the accent, core.parts.accent_sets), in PARTS order."""
    used = {"vector"} if uses_accent(vcolors) else set()
    used |= {part_of(m, g, rasters) for m, g, _ in rasters.values() if raster_accent(m, g)}
    using = [p for p in PARTS if p in used]
    return using, accent_sets(a, using)


def raster_accent(method, grp):
    """Whether an image (or an animation: keys) uses the accent."""
    return not recolor.accent_ignored_reason("keys" if method == "anim" else method, grp)


def package_id(flv, slug, acc, a):
    return naming.output_name(flv, slug, acc, a.suffix)


def outputs(a):
    """One look-and-feel package per flavour (and accent, when something uses it)."""
    pkg = resolve(a.theme)
    slug = naming.slug(package_name(pkg), "splash")
    tmp = Path(tempfile.mkdtemp(prefix="catppuccinize-"))
    try:
        _, sets = results(a, *analyse(a, pkg, tmp))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if previewing(a):
        ext = ".webp" if a.preview_animation else ".png"
        return [naming.planned(a.out / "previews" / f"{package_id(flv, slug, name, a)}{ext}")
                for flv in a.flavor for _, name in sets]
    return [naming.planned(a.out / package_id(flv, slug, name, a), folder=True)
            for flv in a.flavor for _, name in sets]


def build(a):
    pkg = resolve(a.theme)
    splash = pkg / "contents/splash"
    title = package_name(pkg)
    slug = naming.slug(title, "splash")
    print(f"{title} ({pkg})")

    tmp = Path(tempfile.mkdtemp(prefix="catppuccinize-"))
    vcolors, rasters = analyse(a, pkg, tmp)
    preview_src = source_file(pkg / "contents/previews/splash.png", pkg)

    using, sets = results(a, vcolors, rasters)
    if not using:
        note_accent_ignored(a)
    note_unused(a, using)
    if previewing(a):
        try:
            preview(a, pkg, slug, rasters, sets)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        return None
    built = []
    done = {}      # (image, flavour, accent or None) -> recoloured file, copied for other accents
    for flv in a.flavor:
        for accents, aname in sets:
            pid = package_id(flv, slug, aname, a)
            name = (f"{title} - Catppuccin {FLAVOR_TITLES[flv]}" + (f" {aname.title()}" if aname else "")
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

            lookup = text_lookup(vcolors, flv, accents.get("vector"))
            for f in text_files(dst / "contents/splash"):
                recolour_text_file(f, lookup)

            for src, (method, grp, extra) in rasters.items():
                rel = src.relative_to(splash) if src.is_relative_to(splash) else None
                out = dst / "contents/splash" / rel if rel else dst / "contents/previews/splash.png"
                # an image that ignores the accent is the same in every accent's package
                acc = accents.get(part_of(method, grp, rasters)) if raster_accent(method, grp) else None
                key = (src, flv, acc)
                if key in done:
                    shutil.copyfile(done[key], out)
                    continue
                done[key] = out
                if method == "anim":
                    n, durations, loop = extra
                    if n > 100:
                        print(f"  recolouring {n} frames of {src.name}…", flush=True)
                    frames = recolor.recolor_frames(
                        anim_frames(src), *recolor.keys_plan(grp, flv, acc),
                        quantize=out.suffix.lower() == ".gif", parallel=n > 48)
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


def preview(a, pkg, slug, rasters, sets):
    """--preview: the thumbnail of System Settings before and after (else a frame of
    the longest animation, else the first image); --preview-animation: the longest
    animation, before | after. The first flavour and accent (core.options.previewing)."""
    flv, (accents, aname) = a.flavor[0], sets[0]
    out = a.out / "previews"
    out.mkdir(parents=True, exist_ok=True)
    anims = sorted((f for f, (m, _, _) in rasters.items() if m == "anim"),
                   key=lambda f: -rasters[f][2][0])
    def acc_of(method, grp):
        return accents.get(part_of(method, grp, rasters)) if raster_accent(method, grp) else None
    if a.preview_animation:
        src = anims[0]
        method, grp, (n, durations, _) = rasters[src]
        plan = recolor.keys_plan(grp, flv, acc_of(method, grp))
        after = recolor.recolor_frames(anim_frames(src), *plan, quantize=False, parallel=n > 48)
        pairs = ((recolor.on_black(b), recolor.on_black(r)) for b, r in zip(anim_frames(src), after))
        dst = out / f"{package_id(flv, slug, aname, a)}.webp"
        print(f"  recolouring {n} frames of {src.name}…", flush=True)
        recolor.preview_animation(pairs, n, dst, durations)
    else:
        still = next((f for f in rasters if f.name == "splash.png" and f.parent.name == "previews"),
                     None)
        dst = out / f"{package_id(flv, slug, aname, a)}.png"
        if still or not anims:
            src = still or next(f for f, (m, _, _) in rasters.items() if m != "anim")
            method, grp, _ = rasters[src]
            im = recolor.render(src, method, grp, flv, acc_of(method, grp), a)
            recolor.side_by_side(src, im, dst, grp if method == "keys" else None)
        else:                                  # the middle frame of the longest animation
            src = anims[0]
            method, grp, (n, _, _) = rasters[src]
            frame = next(anim_frames(src, {n // 2}))
            im = recolor.recolor_image(frame, *recolor.keys_plan(grp, flv, acc_of(method, grp)),
                                       quantize=False)
            recolor.side_by_side(frame, im, dst, grp)
    print(f"  preview: {dst}  (Catppuccin {FLAVOR_TITLES[flv]}{' ' + aname if aname else ''})")


TARGET = KSplashTarget()
