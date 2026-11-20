"""Colour detection: background, source colours (clustered by hue) and their
automatic Catppuccin targets."""
import colorsys

import numpy as np
from PIL import Image

from .palette import AUTO_HUE_TARGETS, colour_name, hex2rgb, hue_dist, hue_of, rgb, rgb2hex

UI_GROUP = "ui"


def load_rgba(path):
    """Image (path or PIL image) as float RGB plus alpha (0..255), or alpha=None
    when fully opaque."""
    try:
        im = path if isinstance(path, Image.Image) else Image.open(path)
        has_alpha = im.mode in ("RGBA", "LA", "PA") or "transparency" in im.info
        im = im.convert("RGBA")
    except (ValueError, SyntaxError) as e:      # a broken header: PIL is not consistent
        raise OSError(f"cannot read image file '{path}' ({e})") from e
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
