# Limine

[← Back to the README](../README.md) · [Getting started](getting-started.md)

Catppuccin colours for the [Limine](https://github.com/limine-bootloader/limine)
boot menu, optionally with a recoloured wallpaper.

```bash
catppuccinize limine -f mocha -a mauve                        # snippet only
catppuccinize limine -a mauve --wallpaper wall.jpg --preview  # + recoloured wallpaper
sudo catppuccinize limine -a mauve --apply                    # keeps your current wallpaper
sudo catppuccinize limine -a mauve --recolor-wallpaper --apply  # recolours it
sudo catppuccinize limine -a mauve --wallpaper wall.jpg --apply # replaces it
sudo catppuccinize limine --remove
```

## Without `--apply`: a snippet

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

## With `--apply`: edits `limine.conf` for you

As root, the tool:

1. finds `limine.conf` on the ESP (`ESP_PATH` from `/etc/default/limine`, or
   `/boot`; override with `--esp` / `--conf`);
2. **backs it up**;
3. inserts the block before the first menu entry and comments out the global
   options it replaces;
4. copies the wallpaper to `<ESP>/catppuccin/`.

A wallpaper already set in `limine.conf` is kept (the menu background becomes
slightly see-through over it) unless `--wallpaper` replaces it or
`--recolor-wallpaper` recolours it (its `wallpaper_style` is kept).

Running it again replaces the block; `--remove` restores the original options
and deletes the copied wallpapers. Menu entries are not touched, so tools that
regenerate them (e.g. CachyOS's `limine-entry-tool`) keep the theme. If config
enrollment is enabled, run `sudo limine-enroll-config` afterwards.

## Options

| Option | Meaning |
|---|---|
| `-f, --flavor`, `-a, --accent` | flavour and accent of the menu (see [Colours and mapping](colours.md)) |
| `--wallpaper IMAGE` | image to recolour and use as the Limine wallpaper |
| `--recolor-wallpaper` | recolour the wallpaper(s) already set in `limine.conf` |
| `--style` | `stretched`, `centered` or `tiled` |
| `--preview` | also render before/after images of the wallpaper in `<out>/previews/` |
| `--colours` | only list the wallpaper colours `-m` can remap (the menu has none); `--json` for JSON |
| `-s, --suffix` | extra word at the end of the folder and wallpaper names |
| `--apply` | write the theme into `limine.conf` (with sudo) |
| `--remove` | remove the theme from `limine.conf` |
| `--conf`, `--esp` | `limine.conf` to edit, ESP mount point (searched by default) |
| `--method`, `--keep-lum`, `--smooth`, `--lutgen-*` | how the wallpaper is recoloured, as for [images](images.md#options) |
| `-o, --out` | output folder (default `themes/`) |
