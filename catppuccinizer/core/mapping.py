"""Colour mappings: --map overrides and automatic mapping of plain colour lists
(QML/SVG/CSS colours) onto the Catppuccin palette."""
import colorsys
import re
from collections import Counter

import numpy as np

from .palette import (AUTO_HUE_TARGETS, TARGETS, colour_name, hex2rgb, hue_dist, hue_of, rgb,
                      srgb_to_oklab)

# neutral roles from background to foreground
RAMP = ["base", "surface0", "surface1", "surface2", "overlay0", "overlay1", "overlay2",
        "subtext0", "subtext1", "text"]


def apply_maps(cfg, maps, strict=True):
    """Apply NAME=TARGET overrides; unknown names fail when strict, else are skipped."""
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
        if not hit and not strict:
            continue
        if not hit:
            have = sorted({f"{g}.{n}" for g, grp in groups.items() for n in grp["colors"]})
            raise SystemExit(f"--map {m}: no colour named '{k}' "
                             f"(have: {', '.join(have)}; or use a #rrggbb source)")


def map_colour_counts(counts):
    """{hex: count} -> {name: {source, target, count}}.

    Grays go to the neutral ramp by lightness (very dark -> base, near white ->
    text), the most used saturated colour becomes the accent, the other
    saturated colours the closest Catppuccin hue."""
    colors, saturated = {}, []
    for hx, n in Counter(counts).most_common():
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


def uses_accent(colors):
    return any(c["target"] == "accent" for c in colors.values())


NO_ACCENT = "as no colour is mapped to accent (map one with -m NAME=accent)"


def note_accent_ignored(a, reason=NO_ACCENT, indent="  "):
    """Tell the user that the accent they passed with -a has no effect, and why
    (silent when -a was not given: the default accent is nobody's request)."""
    if getattr(a, "accent_given", False):
        print(f"{indent}note: accent ignored {reason}")


def resolve_target(flavor, accent, target):
    """Catppuccin RGB of a target name ("accent" -> the chosen accent)."""
    return rgb(flavor, accent if target == "accent" else target)


def print_colours(colors, indent="    ", show_share=True):
    for n, c in colors.items():
        extra = ""
        if show_share and "share" in c:
            extra = f"  ({c['share'] * 100:.0f}%)"
        elif "count" in c:
            extra = f"  (x{c['count']})"
        print(f"{indent}{n:10s} {c['source']} -> {c['target']}{extra}")
