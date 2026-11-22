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
`/boot`): the result is installed into `/boot/grub/themes/`.

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

`--install` copies it to `/boot/grub/themes/`.

### Apply

`--apply` installs, then sets `GRUB_THEME` in `/etc/default/grub` to the
installed `theme.txt` (a dated backup of the file is made next to it; the rest
of the file is kept byte for byte) and runs
`grub-mkconfig -o /boot/grub/grub.cfg`. The `GRUB_THEME` of before is
remembered (in `/var/lib/catppuccinizer/grub.json`) for `--restore`.

On distributions where the menu is `/boot/grub2/grub.cfg` (Fedora, openSUSE),
run `grub2-mkconfig` yourself after `--install`, or copy the TOML file with
your paths (see below).

### Restore

`--restore` puts the previous `GRUB_THEME` back (or removes the line when there
was none), runs `grub-mkconfig` again and removes the themes catppuccinizer
installed. It builds nothing.

## A target of your own

Copy `grub.toml` to `~/.config/catppuccinizer/targets/`, rename it (`name`)
and change what you need: it becomes `catppuccinize <name>`, in the GUI too.
A TOML target of yours runs with your rights only: no `sudo = true`, and it
installs and configures inside your home
([trust rules](architecture.md#trust)).

See `catppuccinize grub --help` for all options.
