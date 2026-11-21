# Limine

[← Back to the README](../README.md) · [Getting started](getting-started.md)

Catppuccin colours for the [Limine](https://github.com/limine-bootloader/limine)
boot menu, optionally with a recoloured wallpaper.

```bash
catppuccinize limine -f mocha -a mauve                        # menu colours only
catppuccinize limine -a mauve --wallpaper wall.jpg --preview  # + recoloured wallpaper
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

`--wallpaper current` recolours the wallpaper `limine.conf` sets (the GUI's
catalogue offers it as the *in use* one; when only root can read the ESP, it is
read when the command runs, with sudo).

Building writes into the output folder only; `--install`, `--apply` and
`--restore` change the ESP (root needed, a single flavour and accent). Add
`--dry-run` to only list what they would copy and write (with sudo too when the
ESP is only readable by root: it reads `limine.conf`, it changes nothing).

## Preview

`--preview` also renders before/after images of the wallpaper in
`<out>/previews/`.

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
that regenerate them (e.g. CachyOS's `limine-entry-tool`) keep the theme. If
config enrollment is enabled, run `sudo limine-enroll-config` afterwards.

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

## Options

| Option | Meaning |
|---|---|
| `-f, --flavor`, `-a, --accent` | flavour and accent of the menu (see [Colours and mapping](colours.md)) |
| `--wallpaper IMAGE` | image to recolour and use as the Limine wallpaper |
| `--style` | `stretched`, `centered` or `tiled` (with `--wallpaper`) |
| `--preview` | also render before/after images of the wallpaper in `<out>/previews/` (needs `--wallpaper`) |
| `--list` | list the wallpaper set in `limine.conf` (needs to read the ESP) and the installed wallpapers |
| `--names` | only list the folders and files the build would write (existing ones marked); `--json` for JSON |
| `--colours` | only list the wallpaper colours `-m` can remap (the menu has none); `--json` for JSON |
| `-s, --suffix` | extra word at the end of the folder and wallpaper names |
| `--install` | copy the wallpaper to `<ESP>/catppuccin/` (sudo) |
| `--apply` | install, then write the theme into `limine.conf` (sudo) |
| `--restore` | remove the theme from `limine.conf` and its wallpapers (sudo) |
| `--dry-run` | with the steps above: only list what they would change |
| `--conf`, `--esp` | `limine.conf` to edit, ESP mount point (searched by default) |
| `--method`, `--separation`, `--keep-lum`, `--smooth`, `--lutgen-*` | how the wallpaper is recoloured, as for [images](images.md#options) (with `--wallpaper`) |
| `-o, --out` | output folder (default `themes/`) |
