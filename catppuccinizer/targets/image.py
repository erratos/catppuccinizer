"""Image target: recolour wallpapers and other pictures.

Two methods (core.recolor):
- keys: source colours + intensity over a background; best for flat art (line
  art, logos, neon on a plain background). Supports --map and "accent".
- lut:  a colour look-up table that pulls every colour towards the Catppuccin
  palette in Oklab, keeping part of the original lightness; for photos,
  paintings and soft gradients.
"auto" picks keys when the source colours explain the image well, the
background is plain and the edges are crisp.
"""
from pathlib import Path

from ..core import recolor
from ..core.palette import FLAVOR_TITLES
from ..core.target import Target

EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".qoi"}


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


class ImageTarget(Target):
    name = "image"
    help = "recolour wallpapers and other images"
    default_out = "wallpapers"
    default_accent = ("mauve",)

    def add_arguments(self, p):
        p.add_argument("images", nargs="+", metavar="IMAGE", help="image file(s) or folder(s)")
        recolor.add_method_arguments(p)
        p.add_argument("-s", "--suffix", default="", help="extra suffix for the file names")

    def run(self, a):
        files = collect(a.images)
        if not files:
            raise SystemExit("No images found")
        a.out.mkdir(parents=True, exist_ok=True)
        a.strict_map = len(files) == 1      # with several images, a name may exist in only some
        for path in files:
            method, grp = recolor.plan(path, a)
            accents = a.accent if recolor.method_uses_accent(method, grp) else [None]
            for flv in a.flavor:
                for acc in accents:
                    name = "-".join(x for x in (path.stem, "catppuccin", flv, acc, a.suffix) if x)
                    im = recolor.render(path, method, grp, flv, acc, a)
                    if a.preview:
                        (a.out / "previews").mkdir(exist_ok=True)
                        dst = a.out / "previews" / f"{name}.png"
                        recolor.side_by_side(path, im, dst)
                    else:
                        dst = recolor.save_image(im, a.out / name, method, path)
                    print(f"  -> {dst}  (Catppuccin {FLAVOR_TITLES[flv]}{' ' + acc if acc else ''})")


TARGET = ImageTarget()
