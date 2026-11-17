# catppuccinizer

Recolour your boot chain and desktop with [Catppuccin](https://catppuccin.com)
(Latte, Frappé, Macchiato, Mocha). The original colours are **detected
automatically** and mapped to the palette; anti-aliasing, glow, shading and
transparency are preserved, and any colour can be remapped by hand.

![before / after](assets/other-themes.png)

## What it recolours

| Command | What | Guide |
|---|---|---|
| `catppuccinize plymouth` | boot splash themes, including the 80 of [adi1090x](https://github.com/adi1090x/plymouth-themes) | [Plymouth](docs/plymouth.md) |
| `catppuccinize image` | images: wallpapers, photos, flat art, SVG logos | [Images](docs/images.md) |
| `catppuccinize limine` | the Limine boot menu, with its wallpaper | [Limine](docs/limine.md) |
| `catppuccinize ksplash` | the KDE Plasma splash screen shown after login | [KDE splash](docs/ksplash.md) |
| `catppuccinize lut` | a colour table (`.cube`, Hald CLUT) for ffmpeg, GIMP, OBS… | [LUT export](docs/lut.md) |

## Quick start

```bash
pipx install git+https://github.com/erratos/catppuccinizer.git
```

```bash
catppuccinize image ~/Pictures/wall.jpg -f macchiato     # -> ./wallpapers/
catppuccinize plymouth rings_2 -a mauve --test           # boot splash, shown without rebooting
```

`-f` picks the flavour, `-a` the accent colour, `--preview` writes a
before/after image instead of the result. Nothing is installed on your system
unless you pass `--install` or `--apply`.

**New here?** Follow the [getting started guide](docs/getting-started.md).

Ready-made themes built with the tool (Plymouth, KDE splash screens, Limine,
images) are published in [catppuccinized-themes](https://github.com/erratos/catppuccinized-themes).

## Documentation

- [Getting started](docs/getting-started.md): install and first steps
- [Colours and mapping](docs/colours.md): shared options, colour names, `-m`, how it works
- [Images](docs/images.md): photo vs flat art, SVG, built-in `lut` vs lutgen,
  every option shown side by side
- [Plymouth](docs/plymouth.md) ·
  [Limine](docs/limine.md) · [KDE splash](docs/ksplash.md) · [LUT export](docs/lut.md)
- [Architecture](docs/architecture.md): code layout, core API, writing a new target

## Requirements

Python 3.11+ with `numpy` and `Pillow`; `git` for adi1090x themes. Optional:
[lutgen](https://github.com/ozwaldorf/lutgen-rs) for the
[`lutgen` method](docs/images.md#lutgen-method), `rsvg-convert` for SVG
previews.

## Credits & licence

- Original animations and scripts: [Aditya Shakya (@adi1090x)](https://github.com/adi1090x/plymouth-themes), GPL-3.0.
- Colours: [Catppuccin](https://github.com/catppuccin/catppuccin).
- This project is released under the GPL-3.0, like the original themes.
  Not affiliated with the official [catppuccin/plymouth](https://github.com/catppuccin/plymouth) port.
