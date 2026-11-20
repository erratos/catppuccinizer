# Plymouth

[← Back to the README](../README.md) · [Getting started](getting-started.md)

Recolours any Plymouth boot splash theme folder (`script`, `two-step`,
`fade-throbber`…), or any of the 80 animations of
[adi1090x/plymouth-themes](https://github.com/adi1090x/plymouth-themes), fetched
by name (needs `git`, or a [local copy](#using-a-local-copy-of-the-adi1090x-themes)).

```bash
catppuccinize plymouth --list                          # installed themes, adi1090x themes by name
catppuccinize plymouth rings_2 -a mauve                # build it into themes/
sudo catppuccinize plymouth rings_2 -a mauve --test    # build it and show it, no reboot
sudo catppuccinize plymouth rings_2 -a mauve --apply   # install, make it the default
sudo catppuccinize plymouth --restore                  # back to your previous theme
catppuccinize plymouth /usr/share/plymouth/themes/spinner -a mauve   # a theme you have
```

## Examples

Left: original. Right: generated theme.

### Automatic detection: `angular` in Macchiato

```bash
catppuccinize plymouth angular -f macchiato
```

```
angular: background #000000
  blue       #0129aa -> blue  (24%)
  orange     #ff8800 -> peach  (19%)
  blue-2     #0199c5 -> sky  (18%)
  yellow     #ffec01 -> yellow  (12%)
  purple     #2b08ac -> mauve  (11%)
  pink       #f00048 -> red  (11%)
  green      #67bb02 -> green  (6%)
```

![angular](../assets/demo-angular.gif)

Even a rainbow is split into hue clusters, each mapped to the closest Catppuccin colour.

### Manual mapping: `rings_2` with your own colours

```bash
catppuccinize plymouth rings_2 -m pink=mauve green=peach blue=lavender
```

![rings_2](../assets/demo-rings-2.gif)

### Accent mode: `cyanide` in Frappé peach

```bash
catppuccinize plymouth cyanide -f frappe -m cyan=accent -a peach
```

![cyanide](../assets/demo-cyanide.gif)

Colours mapped to `accent` produce one theme per accent passed with `-a`
(`-a all` gives the 14 of them). The white ring keeps `text`.

### Any theme folder: `glow` (two-step), with per-group mapping

```bash
catppuccinize plymouth /usr/share/plymouth/themes/glow -f macchiato -a mauve \
    -m throbber.white=accent ui.white=lavender
```

```
Bizcom Glow [two-step]
  progress (33 images, transparent)
    white      #ffffff -> accent  (100%)
  throbber (20 images, transparent)
    white      #ffffff -> accent  (87%)
    yellow     #f9a905 -> yellow  (13%)
  ui (4 images, transparent)
    white      #ffffff -> lavender  (100%)
```

![glow](../assets/demo-glow.png)

Each animation sequence and the UI pieces (password box, lock, bullets…) are
detected separately; `group.name=target` remaps a colour in one group only.
The two-step colours of the `.plymouth` file (background, progress bar) are
rewritten too.

## Hand-tuned themes

`hexa_retro` and `infinite_seal` have hand-tuned configs shipped with the tool;
`catppuccinize plymouth` without a theme builds both (Mocha, all accents). The
results are published, with previews, in
[catppuccinized-themes](https://github.com/erratos/catppuccinized-themes).

```bash
catppuccinize plymouth hexa_retro infinite_seal -f latte -a mauve blue
```

## Supported themes

| Module | What is recoloured |
|---|---|
| `script` | all images, `Window.SetBackground…Color` calls (or added), white `Image.Text` colours |
| `two-step` | all images, `BackgroundStartColor`/`EndColor`, progress bar colours (alpha kept) |
| others (`fade-throbber`, `space-flares`…) | all images |

Other files (fonts, licences…) are copied, paths in the `.plymouth` file are
rewritten for the new theme name. Themes using `UseFirmwareBackground=true`
(e.g. CachyOS) keep showing the firmware logo screen behind the animation.

## Colour detection and mapping

The first time a theme is used, its colours are detected and saved to
`~/.config/catppuccinizer/plymouth/<theme>.toml`, **per group of images**: each
numbered sequence (`animation-*`, `throbber-*`, `progress-*`…) and `ui` for the
single images.

- a sequence with **a single colour** (white, cyan, orange…) is mapped to
  `accent`; a single-colour `ui` group goes to `text`;
- otherwise whites/grays go to `text` and each hue to the closest Catppuccin
  colour (red, peach, yellow, green, teal, sky, sapphire, blue, mauve, pink).

`--colours` lists it, saving nothing (a theme without a config is detected for
the listing, not saved). `--redetect` ignores the saved config and detects the
colours again: with a build it saves the new config, with `--colours` it only
lists the fresh detection.

To change it, use the colour names listed by `--colours`, prefixed by the group
when the theme has several (`ui.white`), or a `#rrggbb` source colour:

```bash
catppuccinize plymouth hexa_retro -m yellow=red white=lavender -s alt   # -s: name suffix
catppuccinize plymouth owl -m white=accent -a mauve
catppuccinize plymouth rings_2 -m '#32bcff=sky' --preview               # quick before/after image
```

`-m` applies to one run; edit `~/.config/catppuccinizer/plymouth/<theme>.toml`
for a permanent change (it overrides the defaults shipped with the tool). See
[Colours and mapping](colours.md) for the list of targets.

## `-status` variants

Themes built on adi1090x's script template also come as a `…-status`
variant that adds, under the animation:

- a thin **progress bar** (`surface0` track, accent fill) driven by the real
  boot progress reported by Plymouth (boot only, hidden on shutdown);
- the **last 4 services** started by systemd, newest in `subtext0`, older ones
  fading in `overlay1`, disappearing after 3 s of inactivity.

All themes use the flavour's `base` for the whole screen and `text` for
password prompts and messages.

## Steps

Building writes into the output folder only. The steps that change the system
are separate options; they need a single theme, flavour and accent, and root
(`sudo catppuccinize …`: your tuned configs and downloaded themes are still
taken from your home). Add `--dry-run` to any of them to only list what they
would copy, write and run.

### Preview

`--preview` renders one before/after image per theme into `<out>/previews/`,
nothing else.

### Build (default)

The theme folders, `themes/catppuccin-<flavor>-<theme>[-<accent>][-<suffix>]/`
(and their `-status` variant), ready to copy.

### Install

`--install` copies the result (its `-status` variant if any) to
`/usr/share/plymouth/themes/`, without selecting it. On KDE you can then pick
it in *System Settings → Boot Splash Screen*.

### Apply

`--apply` installs, then makes the theme the default and rebuilds the
initramfs (`plymouth-set-default-theme -R`). The theme in use before is
remembered (in `/var/lib/catppuccinizer/plymouth.json`) for `--restore`.

### Test

`--test [SECONDS]` installs the theme and shows it for 10 seconds (or
SECONDS) without rebooting; it always quits Plymouth and restores your default
theme afterwards. Run it from a text console (Ctrl+Alt+F3) if the screen does
not switch.

### Restore

`--restore` makes the theme in use before `--apply` the default again (with
`-R`) and removes the themes catppuccinizer installed. It builds nothing.

### By hand

To install from an archive of
[catppuccinized-themes](https://github.com/erratos/catppuccinized-themes/releases):

```bash
tar xf plymouth-catppuccin-mocha-infinite-seal-mauve.tar.gz
sudo cp -r catppuccin-mocha-infinite-seal-mauve /usr/share/plymouth/themes/
sudo plymouth-set-default-theme -R catppuccin-mocha-infinite-seal-mauve
```

`-R` rebuilds the initramfs (needed for the theme to show at boot). On KDE you
can also pick the theme in *System Settings → Boot Splash Screen* once copied.
Make sure `splash` is in your kernel command line and the `plymouth` hook is
enabled in your initramfs (e.g. `HOOKS=(… plymouth …)` in `/etc/mkinitcpio.conf`).

## Tips

### Using a local copy of the adi1090x themes

Themes given by name are fetched with git into
`~/.cache/catppuccinizer/plymouth-themes/`, one at a time. To use a copy you
already have instead (a clone of the repository, an extracted archive, or any
folder of themes), point `CATPPUCCINIZER_PLYMOUTH_SRC` to it:

```bash
export CATPPUCCINIZER_PLYMOUTH_SRC=~/src/plymouth-themes
catppuccinize plymouth --list            # the themes found there
catppuccinize plymouth rings_2 -a mauve  # taken from that folder, nothing fetched
catppuccinize gui                        # the catalogue lists the same themes
```

Every folder holding a `.plymouth` file counts, in `pack_N/` or at the top.
To recolour a single theme folder, just give its path instead.

### Seeing the splash on a fast machine

On a fast machine the splash may vanish before you see it. A systemd drop-in
can delay the end of Plymouth by a few seconds (and so the login screen):

```bash
sudo mkdir -p /etc/systemd/system/plymouth-quit.service.d
printf '[Service]\nExecStartPre=/usr/bin/sleep 5\n' |
    sudo tee /etc/systemd/system/plymouth-quit.service.d/delay.conf
sudo systemctl daemon-reload
```

To remove it: `sudo rm /etc/systemd/system/plymouth-quit.service.d/delay.conf`,
then `sudo systemctl daemon-reload`. Keep the delay short: the whole boot waits
for it.

## Options

| Option | Default | Meaning |
|---|---|---|
| `THEME …` | `hexa_retro infinite_seal` | theme folder(s) or adi1090x theme name(s) |
| `-f, --flavor` | `mocha` | `latte`, `frappe`, `macchiato`, `mocha` or `all` |
| `-a, --accent` | `all` | accent(s) for colours mapped to `accent`, or `all` |
| `-m, --map` | | `[GROUP.]NAME=TARGET …` overrides for this run |
| `-s, --suffix` | | extra suffix for the theme names |
| `--bar` | auto | progress bar colour (`-status` variants, two-step bar) |
| `--no-status` | | skip the `-status` variants |
| `--redetect` | | detect the colours again instead of using the saved config (a build saves it) |
| `--preview` | | only render one before/after image per theme in `<out>/previews/` |
| `--list` | | list the installed themes (`*` = the default one) and the adi1090x themes (*tuned* = has a config) |
| `--colours` | | only list the colours `-m` can remap (per group), save nothing; `--json` for JSON |
| `-o, --out` | `themes/` | output folder |
| `--install` | | copy the result (its `-status` variant if any) to `/usr/share/plymouth/themes/` (sudo) |
| `--apply` | | install, make it the default theme, rebuild the initramfs (sudo) |
| `--test [S]` | `10` | install and show it for S seconds without rebooting (sudo) |
| `--restore` | | previous default theme again, installed themes removed (sudo) |
| `--dry-run` | | with the steps above: only list what they would change |

Output names: `catppuccin-<flavor>-<theme>[-<accent>][-<suffix>]`.
