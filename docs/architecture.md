# Architecture

[← Back to the README](../README.md)

catppuccinizer is a small **core library** plus independent **targets**
(subcommands of `catppuccinize`). The rule that keeps it from turning into a
tangle: *a target only talks to the core, never to another target*, and the
core never knows about targets. `tests/test_architecture.py` enforces it.

```
catppuccinizer/
  cli.py              builds the command line from the discovered targets
  core/
    palette.py        Catppuccin palettes, colour helpers, Oklab
    detect.py         background + source colours of a group of images
    mapping.py        --map overrides, automatic mapping of plain colour lists
    recolor.py        keys method, LUT methods (lut, lutgen), auto choice, render/save/preview
    clut.py           3D LUTs: trilinear application, resampling, Hald CLUT and .cube files
    lutgen.py         --lutgen-* options, runs the external lutgen binary
    formats.py        colours written as text (QML, SVG/SVGZ), animations (GIF, WebP)
    paths.py          user config / cache folders, sudo-aware ownership
    target.py         Target base class + discovery
  targets/
    plymouth/         Plymouth themes (+ adi1090x fetcher, shipped configs, scripts)
    image.py          images (wallpapers, logos…)
    limine.py         Limine boot menu
    ksplash.py        KDE Plasma splash screen
    lut.py            LUT export (Hald CLUT, .cube)
tests/
  test_regression.py  every target on small fixtures, compared with golden.json
  test_architecture.py
```

## Core API (what targets use)

| Function | Purpose |
|---|---|
| `detect.detect_group(paths, is_ui)` | detect the background and source colours of images, with automatic targets |
| `mapping.apply_maps(cfg, maps, strict)` | apply `-m NAME=TARGET` to `{"groups": {name: group}}` |
| `mapping.map_colour_counts(counts)` | map a `{#hex: count}` list (QML, SVG, CSS…) to Catppuccin roles |
| `mapping.resolve_target(flavor, accent, target)` | target name -> RGB |
| `recolor.recolor_image(path, bg, keys, targets, base)` | keys method on one image (alpha kept) |
| `recolor.plan(path, args)` / `render(...)` / `save_image(...)` | one image, method chosen automatically (keys or LUT) |
| `recolor.add_method_arguments(parser)` | `--method`, `--keep-lum`, `--smooth`, `--lutgen-*` |
| `recolor.LUT_METHODS` / `recolor.lut_for(method, flavor, args, n)` | the LUT methods (no source colours, no accent) and their cube |
| `clut.apply_cube` / `resample` / `read_hald` / `write_hald` / `write_cube` | 3D LUT application and files |
| `formats.collect_text_colours(files)` / `recolour_text_file(f, lookup)` | colours inside QML / SVG / SVGZ |
| `formats.is_animated(f)` / `anim_info` / `anim_frames` / `anim_sample` / `save_animation(...)` | animated GIF and WebP, streamed frame by frame |
| `recolor.recolor_frames(frames, ...)` | keys method over a stream of frames, in parallel |
| `paths.config_dir(target)` / `cache_dir()` / `give_back(path)` | where to store things, sudo ownership |

## Writing a target

```python
# catppuccinizer/targets/grub.py   (or any package, see below)
"""GRUB target: recolour a GRUB theme (theme.txt + images)."""
from ..core import recolor
from ..core.target import Target


class GrubTarget(Target):
    name = "grub"
    help = "recolour a GRUB theme"
    default_accent = ("mauve",)

    def add_arguments(self, p):
        p.add_argument("theme", help="theme folder")
        recolor.add_method_arguments(p)

    def run(self, a):
        # a.flavor, a.accent, a.map, a.preview, a.out are already resolved
        ...


TARGET = GrubTarget()
```

Then add `"grub"` to `BUILTIN` in `core/target.py`, or, from another package,
declare an entry point and install it next to catppuccinizer:

```toml
[project.entry-points."catppuccinizer.targets"]
grub = "my_package.grub:TARGET"
```

Add a case to `tests/test_regression.py` (small synthetic fixture) and run
`python3 tests/test_regression.py --update` once the output looks right.

## Changing the core

Run `python3 -m unittest discover -s tests`. If a golden output changes on
purpose (better LUT, new detection rule…), look at the result, then update
`tests/golden.json` with `--update` in the same commit.
