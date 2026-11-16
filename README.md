# catppuccin-adi1090x-plymouth

[Catppuccin](https://catppuccin.com) adaptations (Latte, Frappé, Macchiato,
Mocha) of Plymouth boot animations from [adi1090x/plymouth-themes](https://github.com/adi1090x/plymouth-themes).
**hexa_retro** and **infinite_seal** are prebuilt; the generator can recolour
**any of the 80 adi1090x themes**, with automatic colour detection and manual
remapping.

| hexa_retro | infinite_seal (mauve) |
|:---:|:---:|
| ![hexa_retro](assets/hexa-retro.gif) | ![infinite_seal](assets/infinite-seal-mauve.gif) |

### Four flavours

![flavours](assets/hexa-flavors.png)

### infinite_seal: one theme per accent (Mocha shown)

![accents](assets/infinite-seal-accents.png)

## Themes

| Theme | Colours |
|---|---|
| `catppuccin-<flavor>-hexa-retro` | white → `text`, red → `red`, yellow → `yellow`, blue → `blue`, cyan → `teal` |
| `catppuccin-<flavor>-infinite-seal-<accent>` | white → accent (rosewater, flamingo, pink, mauve, red, maroon, peach, yellow, green, teal, sky, sapphire, blue, lavender) |

`<flavor>` is `latte`, `frappe`, `macchiato` or `mocha`. All themes use the
flavour's `base` for the whole screen and `text` for password prompts and messages.
Prebuilt [releases](../../releases) contain the Mocha themes; build any other
flavour/accent combination from source (see below).

### `-status` variants

Every theme also comes as a `…-status` variant that adds, under the animation:

- a thin **progress bar** (`surface0` track, accent fill) driven by the
  real boot progress reported by Plymouth (boot only, hidden on shutdown);
- the **last 4 services** started by systemd, newest in `subtext0`, older ones
  fading in `overlay1`, disappearing after 3 s of inactivity.

## Installation

### From a release

Download the archive of the theme you want from the
[Releases](../../releases) page, then:

```bash
tar xf catppuccin-mocha-infinite-seal-mauve.tar.gz
./install.sh ./catppuccin-mocha-infinite-seal-mauve
```

Or without the script:

```bash
sudo cp -r catppuccin-mocha-infinite-seal-mauve /usr/share/plymouth/themes/
sudo plymouth-set-default-theme -R catppuccin-mocha-infinite-seal-mauve
```

`-R` rebuilds the initramfs (needed for the theme to show at boot). On KDE you
can also pick the theme in *System Settings → Boot Splash Screen* once copied.

Make sure `splash` is in your kernel command line and the `plymouth` hook is
enabled in your initramfs (e.g. `HOOKS=(… plymouth …)` in `/etc/mkinitcpio.conf`).

### From source

Requires Python 3.11+ with `numpy` and `Pillow`, and `git`.

```bash
git clone https://github.com/erratos/catppuccin-adi1090x-plymouth.git
cd catppuccin-adi1090x-plymouth
python3 generate.py          # hexa_retro + infinite_seal, Mocha, all accents
./install.sh catppuccin-mocha-hexa-retro-status
```

Upstream themes are fetched on demand (sparse git checkout into `upstream/`).

## Generator

### Any adi1090x theme

![other themes](assets/other-themes.png)

```bash
python3 generate.py --list                     # the 80 upstream themes
python3 generate.py rings_2 owl -f macchiato   # recolour any of them
```

The first time a theme is used, its colours are **detected automatically** and
saved to `configs/<theme>.toml`:

```
$ python3 generate.py rings_2 --detect
rings_2: background #000000
  blue       #32bcff -> sapphire  (46%)
  green      #8cff4a -> green  (32%)
  pink       #ff42a5 -> pink  (22%)
```

- a theme with **a single colour** (white, cyan, orange…) is mapped to `accent`
  and built once per accent chosen with `-a`;
- otherwise whites/grays go to `text` and each hue to the closest Catppuccin
  colour (red, peach, yellow, green, teal, sky, sapphire, blue, mauve, pink).

### Manual mapping

Override any colour on the command line, using the names printed above (or a
`#rrggbb` source colour):

```bash
python3 generate.py rings_2 -m pink=mauve green=peach
python3 generate.py hexa_retro -m yellow=red white=lavender -s alt   # -s: name suffix
python3 generate.py owl -m white=accent -a mauve                     # turn a colour into the accent
```

or edit `configs/<theme>.toml` for a permanent change (targets can be any
Catppuccin colour: the 14 accents, `text`, `subtext1/0`, `overlay2/1/0`,
`surface2/1/0`, `base`, `mantle`, `crust`, or `accent`). Use `--preview` to
render a single before/after image per theme in `themes/previews/` instead of
building everything.

### Options

| Option | Default | Meaning |
|---|---|---|
| `THEME …` | `hexa_retro infinite_seal` | adi1090x theme name(s) |
| `-f, --flavor` | `mocha` | `latte`, `frappe`, `macchiato`, `mocha` or `all` |
| `-a, --accent` | `all` | accent(s) for colours mapped to `accent`, or `all` |
| `-m, --map` | | `NAME=TARGET …` overrides for this run |
| `-s, --suffix` | | extra suffix for the theme names |
| `--bar` | auto | `-status` progress bar colour |
| `--no-status` | | skip the `-status` variants |
| `--detect` | | re-detect colours, overwrite the config, stop |
| `--preview` | | only render before/after images |
| `--list` | | list upstream themes (`[config]` = has a config) |
| `-o, --out` | `themes/` | output folder |
| `--src` | | local `adi1090x/plymouth-themes` checkout instead of fetching |

Output names: `catppuccin-<flavor>-<theme>[-<accent>][-<suffix>]` (+ `-status`).

## Tools

| Script | What it does |
|---|---|
| `generate.py` | The generator described above. |
| `configs/*.toml` | Colour mappings (hand-tuned for hexa_retro and infinite_seal, auto-created for others). |
| `extras.script` | Plymouth script code appended to the `-status` variants (progress bar + service list). |
| `install.sh <name\|folder>` | Installs a theme, sets it as default and rebuilds the initramfs. |
| `preview.sh [theme] [seconds]` | Shows the theme without rebooting, with simulated service messages. Always quits Plymouth at the end, even after Ctrl+C, and restores your previous default theme. Run it from a text console (Ctrl+Alt+F3) if nothing appears. |
| `boot-delay.sh <seconds\|off>` | Keeps the splash up to 15 s longer at boot, handy on fast machines to actually see the theme. Remember to turn it `off`. |

## How it works

- **Detection**: on ~24 frames, the background is the most common border
  colour; bright content pixels are split into grays and hues, hue clusters are
  found from histogram peaks (plus extra centres for spread-out rainbows), and
  each cluster's brightest pixels give its source colour.
- **Recolouring**: every pixel is modelled as `background + t × (source −
  background)`. For each pixel the source colour and intensity `t` that explain
  it best are found, then it is rebuilt as `base + t × (target − base)`, so
  anti-aliasing, glow and shading are preserved over the Catppuccin background.
  Single-colour themes are stored as indexed PNGs whose palette is the exact
  `base → target` ramp (lossless).
- **Limits**: where two colours blend (overlapping lines, gradients between
  hues) a pixel is attached to one of them; very photographic themes keep their
  shapes but lose subtle hue variations.

## Credits & licence

- Original animations and scripts: [Aditya Shakya (@adi1090x)](https://github.com/adi1090x/plymouth-themes), GPL-3.0.
- Colours: [Catppuccin](https://github.com/catppuccin/catppuccin).
- This project is released under the GPL-3.0, like the original themes.
  Not affiliated with the official [catppuccin/plymouth](https://github.com/catppuccin/plymouth) port.
