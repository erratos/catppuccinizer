# catppuccinizer

Recolour your boot chain and desktop with [Catppuccin](https://catppuccin.com)
(Latte, Frappé, Macchiato, Mocha). The original colours are **detected
automatically** and mapped to the palette; anti-aliasing, glow, shading and
transparency are preserved, and any colour can be remapped by hand.

![before / after](assets/other-themes.png)

## What it recolours

| Command | What | Guide |
|---|---|---|
| `catppuccinize image` | images: wallpapers, photos, flat art, SVG logos | [Images](docs/images.md) |
| `catppuccinize plymouth` | boot splash themes: yours, or downloaded ones such as the 80 of [adi1090x](https://github.com/adi1090x/plymouth-themes) | [Plymouth](docs/plymouth.md) |
| `catppuccinize limine` | the Limine boot menu, with its wallpaper | [Limine](docs/limine.md) |
| `catppuccinize ksplash` | the KDE Plasma splash screen shown after login | [KDE splash](docs/ksplash.md) |
| `catppuccinize grub` | GRUB themes (`theme.txt`, images, icons), **untested** | [GRUB](docs/grub.md) |
| `catppuccinize lut` | a colour table (`.cube`, Hald CLUT) for ffmpeg, GIMP, OBS… | [LUT export](docs/lut.md) |

> [!WARNING]
> The GRUB target has not been tested on a real GRUB install yet: the themes it
> writes and its `--install` / `--apply` / `--restore` steps are untested.
> Check with `--preview` and `--dry-run` first, and keep a way to boot without
> GRUB's theme (a live USB) at hand.

## Quick start

```bash
pipx install git+https://github.com/erratos/catppuccinizer.git
```

```bash
catppuccinize image ~/Pictures/wall.jpg -f macchiato     # -> ./images/
sudo catppuccinize plymouth -a mauve --test              # your boot splash, shown without rebooting
```

`-f` picks the flavour, `-a` the accent colour, `--preview` writes a
before/after image instead of the result (`--preview-animation`: the animation
of a boot splash, as an animated WebP). Nothing is installed on your system
unless you pass `--install` or `--apply` (`--dry-run` lists what they would
change, `--restore` undoes them). Apart from the theme, `--configure` sets how
it is shown (Limine's timeout and resolution, Plymouth's delay, GRUB's
resolution…): `sudo catppuccinize limine --configure` prints the current values.

Every command names its outputs `catppuccin-<flavor>-<source>[-<accent>][-<suffix>]`
([output names](docs/colours.md#output-names)).

Prefer clicking? `catppuccinize gui` opens the [graphical interface](#graphical-interface).

**New here?** Follow the [getting started guide](docs/getting-started.md).

Ready-made themes built with the tool (Plymouth, KDE splash screens, Limine,
images) are published in [catppuccinized-themes](https://github.com/erratos/catppuccinized-themes).

## Graphical interface

```bash
catppuccinize gui
```

opens a page in your browser with everything the command line does, one tab
per target. It is served by catppuccinizer itself on `127.0.0.1`: nothing
leaves your computer, nothing more to install.

- **Source**: the wallpapers and themes installed on your system (the one in
  use marked), any file or folder (or drop images on the page), or the web:
  Wallhaven, Gnome-look, the KDE Store and adi1090x's themes are searched and
  downloaded right in the page.
- **Colours**: click a flavour and an accent, and the page itself takes them.
  The colours found in the source are listed before any run: click one to send
  it elsewhere (`-m`), or pick one in a preview.
- **Options**: every option of the target, each with a **?** that explains it
  and, for the colour options, a picture comparing their values. Those without
  effect with the current choices are greyed, with the reason.
- **Live preview**: an image is shown recoloured as you move the options; drag
  across it to compare with the original.
- **Run**: *Preview image*, *Preview animation* (a boot splash, played in the
  page), *Build*, then *Install*, *Apply*, *Test*, *Restore* for the targets
  that change the system, with a *Dry run* switch; the password for `sudo` is
  asked by a graphical prompt. A *System settings* card shows and changes how
  the theme is displayed (timeout, resolution, delay…).
- **Command**: the exact `catppuccinize …` line the page runs, and the files
  *Build* would write, are shown as you go: copy it to script the same thing.

More in the [GUI guide](docs/gui.md).

## Documentation

- [Getting started](docs/getting-started.md): install and first steps
- [Graphical interface](docs/gui.md): `catppuccinize gui`
- [Colours and mapping](docs/colours.md): shared options, colour names, `-m`, how it works
- [Images](docs/images.md): photo vs flat art, SVG, built-in `lut` vs lutgen,
  every option shown side by side
- [Plymouth](docs/plymouth.md) ·
  [Limine](docs/limine.md) · [KDE splash](docs/ksplash.md) · [GRUB](docs/grub.md) ·
  [LUT export](docs/lut.md)
- [Architecture](docs/architecture.md): code layout, core API, writing a new target
  (in Python, or in TOML for a theme folder)

## Requirements

Python 3.11+ with `numpy` and `Pillow`. Optional:
[lutgen](https://github.com/ozwaldorf/lutgen-rs) for the
[`lutgen` method](docs/images.md#lutgen-method), `rsvg-convert` for SVG
previews.

## Credits & licence

- Original animations and scripts: [Aditya Shakya (@adi1090x)](https://github.com/adi1090x/plymouth-themes), GPL-3.0.
- Colours: [Catppuccin](https://github.com/catppuccin/catppuccin).
- This project is released under the GPL-3.0, like the original themes.
  Not affiliated with the official [catppuccin/plymouth](https://github.com/catppuccin/plymouth) port.
