# LUT export

[← Back to the README](../README.md) · [Getting started](getting-started.md)

Writes the colour table that `image --method lut` (or `lutgen`) applies, as a
Hald CLUT image and/or a `.cube` file, so other tools give the same result:
ffmpeg and ImageMagick match catppuccinizer to within 1/255 on average. Use it
for videos, OBS / Resolve colour grading, GIMP (*Colors → Map → Hald CLUT* with
G'MIC) or darktable.

```bash
catppuccinize lut                                  # Mocha: luts/catppuccin-mocha-lut.cube + -lut-hald.png
catppuccinize lut -f all --format cube --keep-lum 0.7
catppuccinize lut --method lutgen --lutgen-algo rbf   # lutgen's table instead of the built-in one
```

Using the files elsewhere:

```bash
ffmpeg -i in.mp4 -vf lut3d=luts/catppuccin-mocha-lut.cube out.mp4
mpv --vf=lut3d=luts/catppuccin-mocha-lut.cube video.mkv
magick in.jpg luts/catppuccin-mocha-lut-hald.png -hald-clut out.jpg
```

A LUT has no source colours: `-m` and `--colours` do not apply. There is no
preview and nothing to install: the files are written into the output folder
only.

## Options

| Option | Default | Meaning |
|---|---|---|
| `-f, --flavor` | `mocha` | `latte`, `frappe`, `macchiato`, `mocha` or `all` |
| `--method` | `lut` | `lut` (built-in) or `lutgen` |
| `--format` | `hald cube` | `hald` (PNG image), `cube` (text), or both |
| `--hald-level` | `8` | Hald level 2–16: a level³ × level³ PNG (8 → 512×512, 64³ points) |
| `--cube-size` | `33` | `.cube` points per axis (33 is the usual size; 65 for more precision) |
| `--keep-lum`, `--smooth`, `--lutgen-*` | | as for [images](images.md#options) |
| `-s, --suffix` | | extra word at the end of the file names |
| `--names` | | only list the files and folders the build would write (existing ones marked); `--json` for JSON |
| `-o, --out` | `luts/` | output folder |

Output: `catppuccin-<flavor>-<method>[-<suffix>].cube` and
`catppuccin-<flavor>-<method>-hald[-<suffix>].png`, `<method>` being `lut` or `lutgen`.
