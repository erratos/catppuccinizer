# Architecture

[← Back to the README](../README.md)

catppuccinizer is a small **core library** plus independent **targets**
(subcommands of `catppuccinize`). The rule that keeps it from turning into a
tangle: *a target only talks to the core, never to another target*, and the
core never knows about targets. `tests/test_architecture.py` enforces it.

```
catppuccinizer/
  cli.py              builds the command line from the discovered targets
  gui/                `catppuccinize gui`: local web page built from the same options
  core/
    options.py        Option: every option declared once (CLI + GUI), the common ones
    palette.py        Catppuccin palettes, colour helpers, Oklab
    detect.py         background + source colours of a group of images
    mapping.py        --map overrides, automatic mapping of plain colour lists
    recolor.py        keys method, LUT methods (lut, lutgen), auto choice, render/save/preview
    clut.py           3D LUTs: trilinear application, resampling, Hald CLUT and .cube files
    lutgen.py         --lutgen-* options, runs the external lutgen binary
    formats.py        colours written as text (QML, SVG/SVGZ), animations (GIF, WebP)
    paths.py          user config / cache folders, sudo-aware ownership
    naming.py         output names (catppuccin-<flavor>-<source>[-<accent>][-<suffix>])
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
  test_options.py     every declared option is complete and coherent
  test_gui.py         forms, command lines, access control of the GUI
```

## Core API (what targets use)

| Function | Purpose |
|---|---|
| `detect.detect_group(paths, is_ui)` | detect the background and source colours of images, with automatic targets |
| `mapping.apply_maps(cfg, maps, strict)` | apply `-m NAME=TARGET` to `{"groups": {name: group}}` |
| `mapping.map_colour_counts(counts)` | map a `{#hex: count}` list (QML, SVG, CSS…) to Catppuccin roles |
| `mapping.resolve_target(flavor, accent, target)` | target name -> RGB |
| `mapping.colour_report(source, method, colors, ...)` / `recolor.colour_report(path, method, grp)` | one entry of `--colours` (names as `-m` accepts them, source, target, share) |
| `mapping.uses_accent(colors)` / `note_accent_ignored(a, reason)` | whether a colour goes to `accent`; the note printed when `-a` was given for nothing |
| `recolor.recolor_image(path, bg, keys, targets, base)` | keys method on one image (alpha kept) |
| `recolor.plan(path, args)` / `render(...)` / `save_image(...)` | one image, method chosen automatically (keys or LUT) |
| `options.Option(...)` / `options.defaults(opts, **values)` | declare an option ([below](#options)); a namespace of defaults for scripts |
| `recolor.method_options(methods=None, help=None)` | `--method`, `--keep-lum`, `--smooth`, `--lutgen-*` (only the given methods) |
| `recolor.LUT_METHODS` / `recolor.lut_for(method, flavor, args, n)` | the LUT methods (no source colours, no accent) and their cube |
| `recolor.accent_ignored_reason(method, grp)` | why the accent has no effect on an image, or None |
| `clut.apply_cube` / `resample` / `read_hald` / `write_hald` / `write_cube` | 3D LUT application and files |
| `formats.collect_text_colours(files)` / `recolour_text_file(f, lookup)` | colours inside QML / SVG / SVGZ |
| `formats.is_animated(f)` / `anim_info` / `anim_frames` / `anim_sample` / `save_animation(...)` | animated GIF and WebP, streamed frame by frame |
| `recolor.recolor_frames(frames, ...)` | keys method over a stream of frames, in parallel |
| `paths.config_dir(target)` / `cache_dir()` / `give_back(path)` | where to store things, sudo ownership |
| `naming.output_name(flavor, source, accent, suffix)` / `slug(text)` | the name of every output: `catppuccin-<flavor>-<source>[-<accent>][-<suffix>]` |

## Writing a target

```python
# catppuccinizer/targets/grub.py   (or any package, see below)
"""GRUB target: recolour a GRUB theme (theme.txt + images)."""
from ..core import recolor
from ..core.options import Option
from ..core.target import Target


class GrubTarget(Target):
    name = "grub"
    help = "recolour a GRUB theme"
    default_accent = ("mauve",)
    accent_also = "the menu colours"   # optional: what uses -a even with --method lut

    def options(self):
        return [
            Option("theme", accept="dir", help="theme folder"),
            *recolor.method_options(),
            Option("--install", switch=True, stage="install", sudo="run",
                   help="copy the theme to /boot/grub/themes"),
        ]

    def run(self, a):
        # a.flavor, a.accent, a.map, a.preview, a.out, a.suffix are already resolved;
        # name outputs with naming.output_name(flavor, source, accent, a.suffix)
        ...


TARGET = GrubTarget()
```

Optionally, `def sources(self)` returns ready-made sources for the first
positional argument (`[{"value", "label", "note"}]`): the GUI shows them as a
catalogue (Plymouth: the adi1090x themes, KDE splash: the installed splash
screens). The GUI needs nothing else: its forms come from `options()`
(see [Graphical interface](gui.md#for-target-authors)).

Optionally too, `def colours(self, a)` does only the analysis and returns the
colours `-m` can remap, as `mapping.colour_report(...)` entries (or
`recolor.colour_report(path, *recolor.plan(path, a, verbose=False))` for an
image). It must write nothing. When a target defines it, `--colours` and
`--json` are added to its options and the command line prints the list.

Then add `"grub"` to `BUILTIN` in `core/target.py`, or, from another package,
declare an entry point and install it next to catppuccinizer:

```toml
[project.entry-points."catppuccinizer.targets"]
grub = "my_package.grub:TARGET"
```

### Options

`options()` returns the target's own options only; the common ones (`-f -a -m
--preview -o -s`, and `--colours --json` when `colours()` is defined) are
declared once in `core/options.py`, the method ones in `core/recolor.py` and
`core/lutgen.py`. An `Option` takes the flags and the argparse fields (`type`,
`choices`, `default`, `nargs`, `metavar`, `const`; `switch=True` for an on/off
option), then:

| Field | Meaning |
|---|---|
| `help` | one line (`--help`, the GUI) |
| `explain`, `image` | a longer text, an illustration in `assets/` |
| `scope` | `common`, `method` / `method:<name>` (core) or `target` (default) |
| `stage` | `analyse`, `preview`, `build` (default), `install`, `apply`, `test`, `restore` |
| `sudo` | `"run"`: the command must run as root; `"self"`: the target calls sudo itself |
| `when` | when it matters: `{"method": ["lutgen"]}` (another option's value) or `{"analysis.remappable": [True]}` (a fact from `--colours`); `method:<name>` options get `{"method": [<name>]}` |
| `source` | what is recoloured (positional arguments by default): the GUI's *Source* card |
| `accept` | for a path: `image`, `images` (files or folders), `dir`, `file` |
| `range` | `(low, high)`: checked after parsing, shown as a slider |
| `kind` | the GUI control when it cannot be guessed (`colour`: a palette colour) |

`tests/test_options.py` checks every declared option (a help, a known stage,
`sudo` only on a system stage, `when` naming existing options).

Add a case to `tests/test_regression.py` (small synthetic fixture) and run
`python3 tests/test_regression.py --update` once the output looks right.

## Changing the core

Run `python3 -m unittest discover -s tests`. If a golden output changes on
purpose (better LUT, new detection rule…), look at the result, then update
`tests/golden.json` with `--update` in the same commit.

User mistakes end with a one-line message, never a traceback: a target raises
`SystemExit("...")`, and `cli.main` turns file errors (`OSError`: missing,
unreadable or unwritable files) into `error: ...`. Set `CATPPUCCINIZER_DEBUG=1`
to get the traceback back.

## Performances

Work that does not depend on the accent is done once: each image is analysed
once, and an image whose colours do not go to `accent` (LUT methods, or `keys`
without an `accent` colour) is rendered once per flavour, then copied into the
other accents' outputs (Limine, KDE splash, Plymouth image groups). The LUT
cube is cached per flavour and options (`lru_cache` on `build_lut` and
`lutgen.build`).

Measured with `python3 -m cProfile -s cumtime` (one machine, 32 threads, for
orders of magnitude):

| Case | Time |
|---|---|
| `image`, 3840×2160 photo (`lut`) | 3.2 s: analysis 1.2 s (detection 1.0 s), `apply_cube` 1.8 s |
| `image`, 3840×2160 PNG | 3.4 s (was 5.1 s with `optimize=True` on the PNG) |
| `limine`, same photo, 4 accents | 3.3 s (was 12.2 s: analysed and rendered once per accent) |
| `plymouth rings_2` (270 images, 800×600), 2 accents | 3.8 s in parallel; 21.5 s of CPU per accent |
| `lut -f all` (Hald + .cube) | 1.6 s, 0.85 s of it in `build_lut` |
| fixtures (any target) | under 1 s |

The three slowest points, in order:

1. **`keys` recolouring** (`recolor_image`): per pixel, the best source colour
   is found over an `(N, K, 3)` array, then opaque results are quantized to 256
   colours (MEDIANCUT, ~20 % of the time). It dominates Plymouth themes
   (hundreds of frames) and animated splash screens.
2. **`clut.apply_cube`**: trilinear interpolation in numpy, ~0.2 s per
   megapixel; it dominates `lut` / `lutgen` on large wallpapers.
3. **Analysis of a large image** (`detect_group`, `fit_error`, `sharpness`):
   about 1 s and 500 MB for a 4K picture, as `detect_group` works on the full
   resolution in float32.

These are the candidates for a real-time preview (work on a reduced image) or
a compiled implementation.
