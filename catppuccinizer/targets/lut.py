"""LUT target: export the colour look-up table of a flavour, to recolour images
and videos with other tools.

- Hald CLUT (PNG): GIMP, ImageMagick (-hald-clut), ffmpeg (haldclut), lutgen
  apply --hald-clut, darktable…
- .cube: ffmpeg (lut3d), mpv (--vf=lut3d), OBS, DaVinci Resolve, Photoshop…

The table is the one `catppuccinize image --method lut|lutgen` applies, with
the same options (--keep-lum, --smooth, --lutgen-*).

  ffmpeg -i in.mp4 -vf lut3d=catppuccin-mocha-lut.cube out.mp4
  magick in.jpg catppuccin-mocha-lut-hald.png -hald-clut out.jpg
"""
from ..core import clut, recolor
from ..core.mapping import note_accent_ignored
from ..core.naming import output_name
from ..core.options import Option
from ..core.palette import FLAVOR_TITLES
from ..core.target import Target


class LutTarget(Target):
    name = "lut"
    help = "export the colour look-up table (Hald CLUT, .cube)"
    default_out = "luts"
    default_accent = ()

    def options(self):
        return [
            Option("--format", nargs="+", choices=["hald", "cube"], default=["hald", "cube"],
                   help="file format(s) (default: both)"),
            Option("--hald-level", type=int, default=8, range=(2, 16),
                   when={"format": ["hald"]},
                   help="Hald CLUT level: level^3 pixels square, level^2 points per axis "
                        "(default: 8, 512x512)"),
            Option("--cube-size", type=int, default=33, range=(2, 256), metavar="N",
                   when={"format": ["cube"]},
                   help=".cube points per axis (default: 33)"),
            *recolor.method_options(recolor.LUT_METHODS, help="lut = the built-in table, "
                                    "lutgen = a table made by lutgen (default: lut)"),
        ]

    def check(self, a):
        recolor.check_method_arguments(a)
        if a.preview or a.map:
            print("note: --preview and -m are ignored by the lut target")
        note_accent_ignored(a, "by the lut target (a LUT has no accent)", indent="")

    def build(self, a):
        a.out.mkdir(parents=True, exist_ok=True)
        for flv in a.flavor:
            title = f"Catppuccin {FLAVOR_TITLES[flv]}"
            if "hald" in a.format:
                n = a.hald_level ** 2
                dst = a.out / f"{output_name(flv, a.method + '-hald', suffix=a.suffix)}.png"
                clut.write_hald(clut.resample(recolor.lut_for(a.method, flv, a, n), n), dst)
                print(f"  -> {dst}  ({title}, Hald level {a.hald_level})")
            if "cube" in a.format:
                n = a.cube_size
                dst = a.out / f"{output_name(flv, a.method, suffix=a.suffix)}.cube"
                clut.write_cube(clut.resample(recolor.lut_for(a.method, flv, a, n), n), dst, title)
                print(f"  -> {dst}  ({title}, {n}^3)")


TARGET = LutTarget()
