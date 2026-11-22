# Limine

[← Back to the README](../README.md) · [Getting started](getting-started.md)

Catppuccin colours for the [Limine](https://github.com/limine-bootloader/limine)
boot menu, optionally with a recoloured wallpaper.

```bash
catppuccinize limine -f mocha -a mauve                        # menu colours only
catppuccinize limine -a mauve --preview                       # the menu as it will boot
catppuccinize limine -a mauve --wallpaper wall.jpg            # + recoloured wallpaper
sudo catppuccinize limine -a mauve --apply --dry-run          # what --apply would change
sudo catppuccinize limine -a mauve --apply                    # menu only: wallpaper kept
sudo catppuccinize limine -a mauve --wallpaper current --apply  # recolours your wallpaper
sudo catppuccinize limine -a mauve --wallpaper wall.jpg --apply # replaces it
sudo catppuccinize limine --restore
```

**Only the menu colours, wallpaper unchanged**: give no `--wallpaper`. The text,
the highlight and the frame take the Catppuccin colours; the wallpaper set in
`limine.conf` stays as it is (the menu background becomes slightly see-through
over it). In the GUI, leave the wallpaper empty: the *Source* card says so.

The result has two [parts](colours.md#parts-an-accent-each): the **menu** (the
title and the highlighted help in the accent, the text in the flavour's
`text`, the frame and background in its neutrals) and the **wallpaper**
(flavour and method; the accent only when a colour goes to it with `keys`, or
with `lut-accent`). `-a mauve wallpaper=peach` gives the wallpaper its own
accent.

`--wallpaper current` recolours the wallpaper `limine.conf` sets (the GUI's
system locations offer it as the *in use* one; when only root can read the ESP, it is
read when the command runs, with sudo).

Building writes into the output folder only; `--install`, `--apply` and
`--restore` change the ESP (root needed, a single flavour and accent). Add
`--dry-run` to only list what they would copy and write (with sudo too when the
ESP is only readable by root: it reads `limine.conf`, it changes nothing).

## Preview

`--preview` draws the boot menu as Limine will show it, into
`<out>/previews/catppuccin-<flavor>-limine-<accent>.png` (the first flavour
and accent, [previews](colours.md#previews)); nothing else is written. It
follows Limine's own layout (its `menu.c` and terminal):

- the screen at the resolution of your monitor (1920×1080 when it cannot be
  read), the text in the VGA console font (`default8x16` of `kbd`), twice as
  big from 2560×1440 as Limine does, or `term_font_scale`;
- the title (`interface_branding`, by default `Limine <version> (x86-64,
  UEFI)`) on row 1 in the accent; the key help (`ARROWS Select    ENTER Boot
  E Edit`, the keys in `interface_help_colour`) on row 3, and `S Firmware Setup
  B Blank Entry` on row 5;
- the entries of your `limine.conf` as a tree (`[-]` / `[+]` directories,
  `├──►` entries), centred, the default entry (`default_entry`, else the
  first) in reverse video; its `comment` and `Booting automatically in N...`
  at the bottom;
- with a wallpaper, a 64-pixel margin showing it, a 4-pixel fade, and the
  text area in `base` slightly see-through over it (`term_background`).

With `--wallpaper`, the original wallpaper is on the left (and, with `keys`,
[what the detection sees](colours.md#separating-colours) on the right).
Without it, the menu is drawn over the wallpaper `limine.conf` sets, as it is.
`limine.conf` is on the ESP, which often only root can read: without sudo, the
preview says so and shows sample entries (and no wallpaper).

## Build (default): a snippet

A `limine-theme.conf` snippet (and the wallpaper) is written to
`themes/catppuccin-<flavor>-limine-<accent>[-<suffix>]/`, to paste into
`limine.conf` yourself. The wallpaper is named
`catppuccin-<flavor>-wallpaper[-<accent>][-<suffix>]`: the accent
only appears when the wallpaper uses it (flat art with a colour mapped to
`accent`); otherwise it is rendered once per flavour and the same file is put
in every accent's folder.

```
# >>> catppuccinizer: Catppuccin Mocha (mauve)
wallpaper: boot():/catppuccin/catppuccin-mocha-wallpaper.png
wallpaper_style: stretched
backdrop: 1e1e2e
term_palette: 45475a;f38ba8;a6e3a1;f9e2af;89b4fa;f5c2e7;94e2d5;bac2de
term_palette_bright: 585b70;f38ba8;a6e3a1;f9e2af;89b4fa;f5c2e7;94e2d5;a6adc8
term_background: 331e1e2e
term_foreground: cdd6f4
term_background_bright: 313244
term_foreground_bright: cdd6f4
interface_branding_colour: cba6f7
interface_help_colour: a6adc8
interface_help_colour_bright: cba6f7
# <<< catppuccinizer
```

## Install

`--install` copies the wallpaper to `<ESP>/catppuccin/` (the ESP is
`ESP_PATH` from `/etc/default/limine`, or `/boot`; override with `--esp`).
`limine.conf` is not touched.

## Apply: edits `limine.conf` for you

`--apply` installs, then:

1. finds `limine.conf` on the ESP (override with `--conf`);
2. **backs it up** (`limine.conf.<date>.bak`, the 5 most recent are kept);
3. inserts the block before the first menu entry (at the top when there is
   none) and comments out the global options it replaces;
4. reads the result back before writing it: one block, exactly the theme, and
   the rest of the file unchanged byte for byte (line endings included).
   Otherwise nothing is written. The file is replaced atomically, with its
   rights.

A wallpaper already set in `limine.conf` is kept (the menu background becomes
slightly see-through over it) unless `--wallpaper IMAGE` replaces it or
`--wallpaper current` recolours it (its `wallpaper_style` is kept).

Running it again replaces the block. Menu entries are not touched, so tools
that regenerate them (e.g. CachyOS's `limine-entry-tool`) keep the theme.

**Config enrollment** (`ENABLE_ENROLL_LIMINE_CONFIG=yes` in `/etc/default/limine`
or `/etc/limine-entry-tool.conf`): the checksum of `limine.conf` is written into
Limine's EFI binary, which refuses to boot a `limine.conf` that no longer matches
it. Every write of `limine.conf` (`--apply`, `--restore`, `--configure`) is then
followed by `limine-enroll-config`. When that tool is missing, nothing is
written; when it fails, the command stops with the backup to put back.

## Restore

`--restore` removes the block from `limine.conf` (after a backup), restores
the options it had commented out and deletes the copied wallpapers. It builds
nothing.

It takes away exactly what `--apply` added: if nothing else changed, the file
is the backup made by the first `--apply`, byte for byte. Changes made since
(a kernel update that added a menu entry) are kept, which putting the backup
back would lose; the backups stay on the ESP if you want one anyway. A file
without a theme is left as it is; a broken block (a begin line without its end)
is refused, to be fixed by hand.

## Display settings

How the menu behaves and is drawn, apart from the theme: `--configure` writes
the settings given into a block of their own in `limine.conf` (between
`# >>> display settings (catppuccinizer)` and its end line), after a backup.
It builds nothing, and leaves the theme's block alone (and the theme's steps
leave it alone). The global options it replaces are commented out, as for the
theme; `default` removes a setting from the block, so the line it had
commented out comes back, and when the block is empty the file is as it was,
byte for byte.

```bash
sudo catppuccinize limine --configure                          # the current values, and tips
sudo catppuccinize limine --configure --timeout 2 --font-scale 2x2 --branding "My PC"
sudo catppuccinize limine --configure --timeout default        # undo one
sudo catppuccinize limine --wallpaper current --preview        # see them in the preview
```

| Setting | Writes | Value | Not set |
|---|---|---|---|
| `--timeout` | `timeout` | seconds (0: at once), or `no` to wait | 5 |
| `--resolution` | `interface_resolution` | `WIDTHxHEIGHT` | the screen's own |
| `--branding` | `interface_branding` | the title at the top | Limine and its version |
| `--hide-help` | `interface_help_hidden` | `yes` / `no`: the lines of keys | no |
| `--font-scale` | `term_font_scale` | `WxH`, `2x2` doubles the text | 2x2 from 2560×1440, 4x4 from 5120×2880 |
| `--margin` | `term_margin` | pixels around the menu frame, over a wallpaper | 64 |
| `--margin-gradient` | `term_margin_gradient` | pixels of the frame's fade | 4 |
| `--remember-last` | `remember_last_entry` | `yes` / `no` | no |
| `--editor` | `editor_enabled` | `yes` / `no`: editing an entry with E | yes |

The [preview](#preview) reads `limine.conf`, so it shows the settings once
written. With [config enrollment](#apply-edits-limineconf-for-you), `limine-enroll-config` runs after the
change.

## Options

| Option | Meaning |
|---|---|
| `-f, --flavor`, `-a, --accent` | flavour and accent; `-a menu=ACCENT` / `wallpaper=ACCENT` for one part (see [Colours and mapping](colours.md#parts-an-accent-each)) |
| `--wallpaper IMAGE` | image to recolour and use as the Limine wallpaper |
| `--style` | `stretched`, `centered` or `tiled` (with `--wallpaper`) |
| `--preview` | only draw the boot menu as it will look (first flavour and accent) in `<out>/previews/`: [Preview](#preview) |
| `--list` | list the wallpaper set in `limine.conf` (needs to read the ESP), the installed wallpapers and wallpaper sites to download more from (the GUI searches Wallhaven and the KDE Store itself) |
| `--names` | only list the folders and files the build would write (existing ones marked); `--json` for JSON |
| `--colours` | only list the wallpaper colours `-m` can remap (the menu has none); `--json` for JSON |
| `-s, --suffix` | extra word at the end of the folder and wallpaper names |
| `--install` | copy the wallpaper to `<ESP>/catppuccin/` (sudo) |
| `--apply` | install, then write the theme into `limine.conf` (sudo) |
| `--restore` | remove the theme from `limine.conf` and its wallpapers (sudo) |
| `--configure` | write the [display settings](#display-settings) given (sudo); alone: print them |
| `--dry-run` | with the steps above: only list what they would change |
| `--conf`, `--esp` | `limine.conf` to edit, ESP mount point (searched by default) |
| `--method`, `--separation`, `--auto-fit`, `--keep-lum`, `--smooth`, `--chroma`, `--dark-fade`, `--lutgen-*` | how the wallpaper is recoloured, as for [images](images.md#options) (with `--wallpaper`) |
| `-o, --out` | output folder (default `themes/`) |
