# GRUB theme

[← Back to the README](../README.md) · [Getting started](getting-started.md)

A GRUB theme is a folder with `theme.txt`, images (background, menu boxes,
icons) and fonts. Any of them can be recoloured:

```bash
catppuccinize grub ~/Downloads/some-theme -a mauve --preview
catppuccinize grub ~/Downloads/some-theme -f macchiato -a teal
sudo catppuccinize grub ~/Downloads/some-theme -a teal --apply --dry-run
sudo catppuccinize grub --restore                   # your previous theme
sudo catppuccinize grub --list                      # installed themes, sites to get more
catppuccinize gui                                   # Other sources…: browse Gnome-look, click to use
```

This target is written in TOML, not in Python
([`targets/grub.toml`](../catppuccinizer/targets/grub.toml)): it is the
prototype of the [declarative targets](architecture.md#declarative-targets-toml),
and a model for a theme folder of your own.

## What is recoloured

| Part | Files | How it is recoloured |
|---|---|---|
| `text` | `theme.txt` (and any `.txt`) | `"#rrggbb"` / `"#rgb"` / `"#rrggbbaa"` strings, and `"white"`, `"black"`… after a key naming a colour (`item_color = "white"`); comments and free text are left alone |
| `icons` | `icons/*` | like the [image](images.md) target (keys for flat art, LUT for photos) |
| `images` | the other PNG / JPEG / WebP images | the same: the background usually goes to the LUT, the menu boxes to keys |

Fonts (`.pf2`) and every other file are copied as they are. Text colours:
grays go to the neutral ramp (`base` … `text`, by lightness), the most used
saturated colour becomes the **accent**, the others the closest Catppuccin hue
([colour names](colours.md#manual-mapping)). `--colours` lists them, then each
image; `-m` remaps any of them, `-a icons=peach` gives the icons their own
accent ([parts](colours.md#parts-an-accent-each)).

GRUB only reads themes from a filesystem it can reach at boot (usually
`/boot`): the result is installed into its themes folder ([Install](#install)).

## Steps

Install, apply and restore need root and a single flavour and accent; add
`--dry-run` to only list what they would copy, write and run.

### Build (default)

A theme folder per flavour (and accent, when something uses it):
`themes/catppuccin-<flavor>-<name>[-<accent>][-<suffix>]/`.

### Preview

`--preview` writes the largest image (the background) before and after into
`<out>/previews/`, for the first flavour and accent; nothing is built.

### Install

`--install` copies it to `/boot/grub/themes/`, or `/boot/grub2/themes/` where
GRUB's folder is `/boot/grub2` (Fedora, openSUSE).

### Apply

`--apply` installs, then sets `GRUB_THEME` in `/etc/default/grub` to the
installed `theme.txt` (a dated backup of the file is made next to it; the rest
of the file is kept byte for byte) and writes the menu again with the first
of these commands that is installed:

| Command | Distributions |
|---|---|
| `update-grub` | Debian, Ubuntu and their derivatives |
| `grub-mkconfig -o /boot/grub/grub.cfg` | Arch, Gentoo… |
| `grub2-mkconfig -o /boot/grub2/grub.cfg` | Fedora, openSUSE |

When none is found, nothing is done at all (not even the build), rather than
`/etc/default/grub` being changed without the menu following. The `GRUB_THEME`
of before is remembered (in `/var/lib/catppuccinizer/grub.json`) for
`--restore`.

### Restore

`--restore` puts the previous `GRUB_THEME` back (or removes the line when there
was none), writes the menu again (the same command) and removes the themes catppuccinizer
installed. It builds nothing.

## Display settings

How the menu behaves and is drawn, apart from the theme: `--configure` sets
variables of `/etc/default/grub` (a dated backup first, the rest of the file
kept byte for byte), then writes the menu again, with the command of
[`--apply`](#apply). It builds
nothing; `default` puts back what the variable was (or removes its line), the
values replaced being remembered in `/var/lib/catppuccinizer/grub-settings.json`.

```bash
sudo catppuccinize grub --configure                         # the current values, and tips
sudo catppuccinize grub --configure --timeout 3 --gfxmode 1920x1080,auto
sudo catppuccinize grub --configure --timeout default       # undo it
```

| Setting | Variable | Value | Not set |
|---|---|---|---|
| `--timeout` | `GRUB_TIMEOUT` | seconds (0: at once, -1: wait) | 5 |
| `--timeout-style` | `GRUB_TIMEOUT_STYLE` | `menu`, `countdown`, or `hidden` (Esc shows it) | menu |
| `--gfxmode` | `GRUB_GFXMODE` | `WIDTHxHEIGHT[xDEPTH]` or `auto`, several separated by commas | auto |
| `--gfxpayload` | `GRUB_GFXPAYLOAD_LINUX` | `keep`, `text` or `WIDTHxHEIGHT` | chosen by GRUB |

They are declared in `grub.toml` (`[configure]`), like the rest of the target:
a TOML target of yours can declare its own ([format](architecture.md#format)).

## A target of your own

Copy `grub.toml` to `~/.config/catppuccinizer/targets/`, rename it (`name`)
and change what you need: it becomes `catppuccinize <name>`, in the GUI too.
A TOML target of yours runs with your rights only: no `sudo = true`, and it
installs and configures inside your home
([trust rules](architecture.md#trust)).

See `catppuccinize grub --help` for all options.
