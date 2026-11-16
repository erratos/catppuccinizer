"""Image target: recolour wallpapers and other pictures.

Two methods:
- keys: the Plymouth method (source colours + intensity over a background);
  best for flat art (line art, logos, neon on a plain background). Supports
  --map and "accent".
- lut:  a colour look-up table that pulls every colour towards the Catppuccin
  palette in Oklab, keeping part of the original lightness; for photos,
  paintings and gradients.
"auto" picks keys when the source colours explain the image well.
"""
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image

from . import ROOT
from .colours import apply_maps, detect_group, load_rgba, recolor_image
from .palette import ACCENTS, FLAVOR_TITLES, PALETTES, hex2rgb, oklab_to_srgb, rgb, srgb_to_oklab

EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".qoi"}
FIT_THRESHOLD = 6.0          # mean error (0..255) on content pixels under which "keys" is chosen
CHROMA_REF = 0.10           # lut: Oklab chroma at which a colour fully takes its accent
NEUTRALS = ["crust", "mantle", "base", "surface0", "surface1", "surface2", "overlay0",
            "overlay1", "overlay2", "subtext0", "subtext1", "text"]
MIN_BG_SHARE = 0.35          # ... and the plain background must cover at least this share
MIN_SHARPNESS = 0.08         # ... and edges must be crisp (blurred blobs/gradients -> lut)


def add_arguments(p):
    p.add_argument("images", nargs="+", metavar="IMAGE", help="image file(s) or folder(s)")
    add_method_arguments(p)
    p.add_argument("-s", "--suffix", default="", help="extra suffix for the file names")
    p.set_defaults(out_default=ROOT / "wallpapers", default_accent=["mauve"])


def add_method_arguments(p):
    p.add_argument("--method", choices=["auto", "keys", "lut"], default="auto",
                   help="keys = flat art, lut = photos (default: auto)")
    p.add_argument("--keep-lum", type=float, default=0.5, metavar="0..1",
                   help="lut: 0 = palette lightness, 1 = original lightness (default: 0.5)")
    p.add_argument("--smooth", type=float, default=0.08, metavar="R",
                   help="lut: blend radius in Oklab; smaller = purer palette colours (default: 0.08)")


def collect(paths):
    files = []
    for p in map(Path, paths):
        if p.is_dir():
            files += sorted(f for f in p.rglob("*") if f.suffix.lower() in EXTS)
        elif p.is_file():
            files.append(p)
        else:
            raise SystemExit(f"Not found: {p}")
    return files


# ---------------------------------------------------------------- analysis
def analyse(path):
    """Detect source colours; return them with the reconstruction error on the
    content pixels and the share of the image covered by the plain background."""
    grp = detect_group([path], is_ui=False)
    im = Image.open(path)
    im.thumbnail((512, 512))
    px = np.asarray(im.convert("RGB"), np.float32).reshape(-1, 3)
    bg = hex2rgb(grp["background"])
    keys = np.array([hex2rgb(c["source"]) for c in grp["colors"].values()]) - bg
    d = px - bg
    t = np.clip((d @ keys.T) / np.maximum((keys ** 2).sum(1), 1e-6), 0, 1)
    recon = t[..., None] * keys[None]
    err = np.abs(d[:, None, :] - recon).mean(-1).min(1)
    content = np.abs(d).max(-1) > 24
    return (grp, float(err[content].mean() if content.any() else 0), float(1 - content.mean()),
            sharpness(path))


def sharpness(path):
    """99th percentile of the local contrast, relative to the image's range:
    ~0.01-0.03 for blurred blobs and soft gradients, > 0.2 for line art and photos."""
    im = Image.open(path).convert("L")
    im.thumbnail((1024, 1024))
    a = np.asarray(im, np.float32)
    g = np.maximum(np.abs(np.diff(a, axis=1))[:-1], np.abs(np.diff(a, axis=0))[:, :-1])
    return float(np.percentile(g, 99) / (np.percentile(a, 99) - np.percentile(a, 1) + 1))


# --------------------------------------------------------------------- LUT
@lru_cache(maxsize=None)
def build_lut(flavor, smooth, keep_lum, n=33):
    """n^3 RGB grid -> Catppuccin, as float32 (n, n, n, 3).

    - lightness: the original lightness is mapped onto the flavour's neutral ramp
      (crust ... text), then blended with the original by keep_lum;
    - colour: the hue goes to a soft mix of the closest accents (in the a/b plane),
      applied in proportion to the original chroma, so grays stay neutral.
    """
    p = PALETTES[flavor]
    neutrals = srgb_to_oklab(np.array([hex2rgb(p[c]) for c in NEUTRALS]))
    neutrals = neutrals[np.argsort(neutrals[:, 0])]
    accents = srgb_to_oklab(np.array([hex2rgb(p[c]) for c in ACCENTS]))
    g = np.linspace(0, 255, n, dtype=np.float32)
    grid = np.stack(np.meshgrid(g, g, g, indexing="ij"), -1).reshape(-1, 3)
    lab = srgb_to_oklab(grid)
    L, ab = lab[:, 0], lab[:, 1:]

    # neutral ramp: original lightness 0..1 spread over [crust, text]
    lo, hi = neutrals[0, 0], neutrals[-1, 0]
    ramp_L = lo + np.clip(L, 0, 1) * (hi - lo)
    neutral = np.stack([np.interp(ramp_L, neutrals[:, 0], neutrals[:, k]) for k in range(3)], -1)

    # accent mix by hue/chroma distance
    d2 = ((ab[:, None, :] - accents[None, :, 1:]) ** 2).sum(-1)
    w = np.exp(-(d2 - d2.min(1, keepdims=True)) / (2 * smooth ** 2))
    acc_ab = (w[..., None] * accents[None, :, 1:]).sum(1) / w.sum(1, keepdims=True)
    # mixing neighbouring accents shortens the a/b vector: restore the accents' chroma
    acc_c = (w * np.linalg.norm(accents[:, 1:], axis=1)[None]).sum(1) / w.sum(1)
    acc_ab *= (acc_c / np.maximum(np.linalg.norm(acc_ab, axis=1), 1e-6))[:, None]
    k = np.clip(np.linalg.norm(ab, axis=1) / CHROMA_REF, 0, 1)[:, None]

    out = np.empty_like(lab)
    out[:, 0] = keep_lum * L + (1 - keep_lum) * neutral[:, 0]
    # darker than the accents -> proportionally less chroma (avoids neon on dark pixels)
    dim = np.clip(out[:, 0] / (0.75 * accents[:, 0].mean()), 0, 1)[:, None]
    out[:, 1:] = (1 - k) * neutral[:, 1:] + k * acc_ab * dim
    return oklab_to_srgb(out).reshape(n, n, n, 3).astype(np.float32)


def apply_lut(arr, lut):
    n = lut.shape[0]
    flat = arr.reshape(-1, 3)
    out = np.empty_like(flat, dtype=np.float32)
    for s in range(0, len(flat), 1 << 20):
        f = flat[s:s + (1 << 20)] * ((n - 1) / 255)
        i0 = np.clip(np.floor(f).astype(np.int32), 0, n - 2)
        d = f - i0
        acc = np.zeros_like(f)
        for dx in (0, 1):
            wx = d[:, 0] if dx else 1 - d[:, 0]
            for dy in (0, 1):
                wy = d[:, 1] if dy else 1 - d[:, 1]
                for dz in (0, 1):
                    wz = d[:, 2] if dz else 1 - d[:, 2]
                    acc += (wx * wy * wz)[:, None] * lut[i0[:, 0] + dx, i0[:, 1] + dy, i0[:, 2] + dz]
        out[s:s + len(f)] = acc
    return out.reshape(arr.shape)


def recolor_lut(path, flavor, smooth, keep_lum):
    rgb_arr, alpha = load_rgba(path)
    out = np.clip(apply_lut(rgb_arr, build_lut(flavor, smooth, keep_lum)) + 0.5, 0, 255)
    if alpha is not None:
        return Image.fromarray(np.dstack([out, alpha]).astype(np.uint8), "RGBA")
    return Image.fromarray(out.astype(np.uint8), "RGB")


# --------------------------------------------------------------------- API
def plan_image(path, a, verbose=True):
    """Return (method, group config or None) for one image."""
    grp, err, bg_share, sharp = None, None, None, None
    if a.method in ("auto", "keys"):
        grp, err, bg_share, sharp = analyse(path)
    flat = (err is not None and err < FIT_THRESHOLD and bg_share >= MIN_BG_SHARE
            and sharp >= MIN_SHARPNESS)
    method = a.method if a.method != "auto" else ("keys" if flat else "lut")
    if method == "keys":
        cfg = {"groups": {"image": grp}}
        apply_maps(cfg, a.map, strict=getattr(a, "strict_map", True))
    elif a.map:
        print(f"  note: --map is ignored by the lut method ({path.name})")
    if verbose:
        fit = (f" (fit error {err:.1f}, background {bg_share:.0%}, sharpness {sharp:.2f})"
               if err is not None else "")
        print(f"{path.name}: {method}{fit}")
        if method == "keys":
            bg = "transparent" if grp["transparent"] else f"background {grp['background']}"
            print(f"  {bg}")
            for n, c in grp["colors"].items():
                print(f"    {n:10s} {c['source']} -> {c['target']}  ({c['share'] * 100:.0f}%)")
    return method, grp


def render(path, method, grp, flavor, accent, a):
    if method == "lut":
        return recolor_lut(path, flavor, a.smooth, a.keep_lum)
    keys = np.array([hex2rgb(c["source"]) for c in grp["colors"].values()])
    targets = np.array([rgb(flavor, accent if c["target"] == "accent" else c["target"])
                        for c in grp["colors"].values()])
    return recolor_image(path, hex2rgb(grp["background"]), keys, targets, rgb(flavor, "base"))


def uses_accent(method, grp):
    return method == "keys" and any(c["target"] == "accent" for c in grp["colors"].values())


def save(im, dst, method, src):
    ext = src.suffix.lower()
    if method == "lut" and ext in (".jpg", ".jpeg", ".webp") and im.mode == "RGB":
        dst = dst.with_suffix(ext)
        im.save(dst, quality=95)
    else:
        dst = dst.with_suffix(".png")
        im.save(dst, optimize=True)
    return dst


def side_by_side(src, im, out):
    before = Image.open(src).convert("RGB")
    after = im.convert("RGBA")
    bg = Image.new("RGBA", after.size, (0, 0, 0, 255))
    bg.alpha_composite(after)
    after = bg.convert("RGB")
    for x in (before, after):
        x.thumbnail((900, 900))
    sheet = Image.new("RGB", (before.width * 2 + 8, before.height), (69, 71, 90))
    sheet.paste(before, (0, 0))
    sheet.paste(after.resize(before.size), (before.width + 8, 0))
    sheet.save(out)


def run(a):
    files = collect(a.images)
    if not files:
        raise SystemExit("No images found")
    a.out.mkdir(parents=True, exist_ok=True)
    a.strict_map = len(files) == 1      # with several images, a name may exist in only some
    for path in files:
        method, grp = plan_image(path, a)
        accents = a.accent if uses_accent(method, grp) else [None]
        for flv in a.flavor:
            for acc in accents:
                name = "-".join(x for x in (path.stem, "catppuccin", flv, acc, a.suffix) if x)
                im = render(path, method, grp, flv, acc, a)
                if a.preview:
                    (a.out / "previews").mkdir(exist_ok=True)
                    dst = a.out / "previews" / f"{name}.png"
                    side_by_side(path, im, dst)
                else:
                    dst = save(im, a.out / name, method, path)
                print(f"  -> {dst}  (Catppuccin {FLAVOR_TITLES[flv]}{' ' + acc if acc else ''})")
