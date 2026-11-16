"""Colour detection and recolouring, shared by every target."""
import colorsys
import re

import numpy as np
from PIL import Image

from .palette import (ACCENTS, AUTO_HUE_TARGETS, TARGETS, colour_name, hex2rgb, hue_dist,
                      hue_of, rgb, rgb2hex)

UI_GROUP = "ui"


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
