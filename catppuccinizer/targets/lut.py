"""LUT target: export the colour look-up table of a flavour, to recolour images
and videos with other tools.

- Hald CLUT (PNG): GIMP, ImageMagick (-hald-clut), ffmpeg (haldclut), lutgen
  apply --hald-clut, darktable…
- .cube: ffmpeg (lut3d), mpv (--vf=lut3d), OBS, DaVinci Resolve, Photoshop…

The table is the one `catppuccinize image --method lut|lutgen` applies, with
the same options (--keep-lum, --smooth, --lutgen-*).

  ffmpeg -i in.mp4 -vf lut3d=catppuccin-mocha.cube out.mp4
  magick in.jpg catppuccin-mocha-hald.png -hald-clut out.jpg
"""
from ..core import clut, recolor
from ..core.palette import FLAVOR_TITLES
from ..core.target import Target


class LutTarget(Target):
    name = "lut"
    help = "export the colour look-up table (Hald CLUT, .cube)"
    default_out = "luts"
    default_accent = ()

    def add_arguments(self, p):
        p.add_argument("--format", nargs="+", choices=["hald", "cube"], default=["hald", "cube"],
                       help="file format(s) (default: both)")
        p.add_argument("--hald-level", type=int, default=8, metavar="2..16",
                       help="Hald CLUT level: level^3 pixels square, level^2 points per axis "
                            "(default: 8, 512x512)")
        p.add_argument("--cube-size", type=int, default=33, metavar="N",
                       help=".cube points per axis (default: 33)")
        p.add_argument("-s", "--suffix", default="", help="extra suffix for the file names")
        recolor.add_method_arguments(p)
        p.set_defaults(method="lut")

    def check(self, a):
        if a.method not in recolor.LUT_METHODS:
            raise SystemExit("lut: --method must be lut or lutgen")
        if not 2 <= a.hald_level <= 16:
            raise SystemExit("--hald-level must be between 2 and 16")
        if not 2 <= a.cube_size <= 256:
            raise SystemExit("--cube-size must be between 2 and 256")
        if a.method == "lutgen":
            recolor.lutgen.options(a)
        if a.preview or a.map:
            print("note: --preview and -m are ignored by the lut target")

    def run(self, a):
        a.out.mkdir(parents=True, exist_ok=True)
        for flv in a.flavor:
            stem = "-".join(x for x in ("catppuccin", flv, a.method if a.method != "lut" else "",
                                        a.suffix) if x)
            title = f"Catppuccin {FLAVOR_TITLES[flv]}"
            if "hald" in a.format:
                n = a.hald_level ** 2
                dst = a.out / f"{stem}-hald.png"
                clut.write_hald(clut.resample(recolor.lut_for(a.method, flv, a, n), n), dst)
                print(f"  -> {dst}  ({title}, Hald level {a.hald_level})")
            if "cube" in a.format:
                n = a.cube_size
                dst = a.out / f"{stem}.cube"
                clut.write_cube(clut.resample(recolor.lut_for(a.method, flv, a, n), n), dst, title)
                print(f"  -> {dst}  ({title}, {n}^3)")


TARGET = LutTarget()
