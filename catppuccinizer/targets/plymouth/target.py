"""Plymouth target: recolour any Plymouth theme folder (script, two-step,
fade-throbber, ...) or any of the 80 adi1090x themes, fetched by name.

Colours are detected per group of images (each numbered sequence, plus "ui"
for single images) and saved in ~/.config/catppuccinizer/plymouth/<theme>.toml
(hand-tuned defaults ship with the package). Themes built on adi1090x's script
template also get a "-status" variant (progress bar + latest systemd services).
"""
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

from ...core.detect import UI_GROUP, detect_group
from ...core.mapping import apply_maps, note_accent_ignored, print_colours, uses_accent
from ...core.palette import ACCENTS, FLAVOR_TITLES, PALETTES, TARGETS, color_args, hex2rgb, rgb
from ...core.paths import config_dir
from ...core.recolor import recolor_image, recolor_job
from ...core.target import Target
from .upstream import resolve_theme, upstream_themes

HERE = Path(__file__).resolve().parent
DEFAULT_CONFIGS = HERE / "configs"
SCRIPTS = HERE / "scripts"

INSTALL_DIR = "/usr/share/plymouth/themes"
DEFAULT_THEMES = ["hexa_retro", "infinite_seal"]


class PlymouthTarget(Target):
    name = "plymouth"
    help = "recolour Plymouth themes (folders or adi1090x names)"

    def add_arguments(self, p):
        add_arguments(p)

    def check(self, a):
        check_args(a)

    def run(self, a):
        run(a)

    def sources(self):
        themes = upstream_themes()
        return [{"value": name, "label": name,
                 "note": path.split("/")[0] + ("  · tuned" if config_path(name).exists() else "")}
                for name, path in sorted(themes.items(), key=lambda kv: kv[1])]


def add_arguments(p):
    p.add_argument("themes", nargs="*", default=DEFAULT_THEMES, metavar="THEME",
                   help="theme folder, or adi1090x theme name (default: hexa_retro infinite_seal)")
    p.add_argument("-s", "--suffix", default="", help="extra suffix for the theme names")
    p.add_argument("--bar", metavar="COLOUR", help="progress bar colour")
    p.add_argument("--no-status", action="store_true", help="skip the -status variants")
    p.add_argument("--detect", action="store_true",
                   help="(re)detect colours, overwrite the theme's config, then stop")
    p.add_argument("--list", action="store_true", help="list adi1090x themes and exit")
    p.add_argument("--src", type=Path,
                   help="local adi1090x/plymouth-themes checkout (default: fetched into the cache)")
    p.add_argument("--install", action="store_true",
                   help="install the result (its -status variant if any) and rebuild the initramfs")
    p.add_argument("--test", nargs="?", const=10, type=int, metavar="SECONDS",
                   help="show the result without rebooting (default: 10 s)")
    p.add_argument("--boot-delay", metavar="SECONDS|off",
                   help="keep the splash N more seconds at boot (max 15), or 'off', then exit")


def check_args(a):
    if (a.install or a.test) and (len(a.themes) > 1 or len(a.flavor) > 1 or len(a.accent) > 1):
        raise SystemExit("--install / --test need a single theme, flavour and accent")
    if a.bar and a.bar not in PALETTES["mocha"]:
        raise SystemExit(f"--bar: unknown colour '{a.bar}'")
    if a.suffix and not re.fullmatch(r"[a-z0-9-]+", a.suffix):
        raise SystemExit("--suffix: use lowercase letters, digits and '-'")


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
    """User config if any, else the default shipped with the package."""
    user = config_dir("plymouth") / f"{name}.toml"
    default = DEFAULT_CONFIGS / f"{name}.toml"
    return user if user.exists() or not default.exists() else default


def save_config(theme, cfg):
    path = config_dir("plymouth") / f"{theme.name}.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    src = theme.dir
    try:
        src = src.relative_to(Path.cwd())
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
    path.write_text("\n".join(lines) + "\n")


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


def print_mapping(theme, cfg):
    print(f"{theme.title} [{theme.module}]")
    for g, grp in cfg["groups"].items():
        n = len(theme.groups.get(g, []))
        bg = "transparent" if grp["transparent"] else f"background {grp['background']}"
        print(f"  {g} ({n} image{'s' if n > 1 else ''}, {bg})")
        print_colours(grp["colors"])


# --------------------------------------------------------------- theme files

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

    extras = ((HERE / "extras.script").read_text()
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


def list_themes():
    themes = upstream_themes()
    for name, path in sorted(themes.items(), key=lambda kv: kv[1]):
        mark = "  [config]" if config_path(name).exists() else ""
        print(f"{path}{mark}")


def script(name, *args):
    """Run one of the helper shell scripts (they call sudo themselves)."""
    return subprocess.run(["bash", str(SCRIPTS / name), *map(str, args)], check=False).returncode


def run(a):
    if a.list:
        return list_themes()
    if a.boot_delay:
        raise SystemExit(script("boot-delay.sh", a.boot_delay))

    jobs, status, copies = [], [], []
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

        accent_used = any(uses_accent(grp["colors"]) for grp in cfg["groups"].values())
        if not accent_used:
            note_accent_ignored(a)
        main_colours = [c["target"] for grp in cfg["groups"].values()
                        for c in sorted(grp["colors"].values(), key=lambda c: -c.get("share", 0))
                        if c["target"] in ACCENTS]
        with_status = not a.no_status and theme.adi_template
        done = {}      # (flavour, group, accent or None) -> folder whose images can be copied
        if not a.no_status and not theme.adi_template and not a.preview:
            print("  (no -status variant: only for adi1090x-style script themes)")
        for flv in a.flavor:
            base = rgb(flv, "base")
            for acc in (a.accent if accent_used else [None]):
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
                    # a group without "accent" is the same for every accent: recoloured
                    # once, then copied into the other accents' themes
                    gkey = (flv, g, acc if uses_accent(cfg["groups"][g]["colors"]) else None)
                    if gkey in done:
                        copies += [(done[gkey] / p.name, a.out / out_name / p.name)
                                   for p in theme.groups[g]]
                        continue
                    done[gkey] = a.out / out_name
                    jobs += [(p, a.out / out_name / p.name, src_bg, keys, targets, base)
                             for p in theme.groups[g]]
                status.append(((a.out / out_name, flv, bar, cfg["bar_width"], cfg["bar_gap"]),
                               with_status))

    if not jobs:
        return
    print(f"{len(status)} theme(s), {len(jobs)} images", flush=True)
    with Pool() as pool:
        for i, _ in enumerate(pool.imap_unordered(recolor_job, jobs, chunksize=8), 1):
            if i % 500 == 0 or i == len(jobs):
                print(f"{i}/{len(jobs)} images", flush=True)
    for src, dst in copies:
        shutil.copyfile(src, dst)
    for args, with_st in status:
        if with_st:
            write_status_variant(*args)
        print(f"  {args[0].name}" + (f"  (+ {args[0].name}-status)" if with_st else ""))

    if (a.install or a.test) and status:
        folder, with_st = status[0][0][0], status[0][1]
        folder = folder.parent / f"{folder.name}-status" if with_st else folder
        if a.test:
            script("preview.sh", folder, a.test)
        if a.install:
            script("install.sh", folder)


TARGET = PlymouthTarget()
