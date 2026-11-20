# KDE splash screen

[← Back to the README](../README.md) · [Getting started](getting-started.md)

The Plasma splash screen (KSplash, shown after login) is the `contents/splash/`
folder of a look-and-feel package. Any of them can be recoloured:

```bash
catppuccinize ksplash --list                           # installed splash screens
catppuccinize ksplash org.kde.breeze.desktop -a mauve --test
catppuccinize ksplash CachyOS-Nord -f macchiato -a teal --apply
catppuccinize ksplash --restore                        # your previous splash screen
catppuccinize ksplash ~/Downloads/some-splash -m '#3daee9=peach'
```

![KDE splash](../assets/demo-ksplash.png)

```
Breeze (/usr/share/plasma/look-and-feel/org.kde.breeze.desktop)
  QML / SVG colours
    gray       #31363b -> surface1  (x6)
    blue       #3daee9 -> accent  (x6)
    white      #eff0f1 -> text  (x5)
    ...
```

## What is recoloured

| Part | How it is recoloured |
|---|---|
| `Splash.qml` | `"#rrggbb"` / `"#aarrggbb"` strings, `"black"`/`"white"`, `Qt.rgba()` |
| SVG / SVGZ | `fill`, `stroke`, `stop-color`, `color` (incl. Plasma colour-scheme stylesheets) |
| PNG / JPEG | like the [image](images.md) target (keys for flat art, LUT for photos) |
| animated GIF or WebP | every frame, with one mapping detected over the animation |
| `contents/previews/splash.png` | the thumbnail shown in System Settings: when it is a still of the animation, it takes the animation's colours and `-m`, so it matches the splash |

QML/SVG colours: grays go to the neutral ramp (`base` … `text`, by lightness),
the most used saturated colour becomes the **accent**, the others the closest
Catppuccin hue; `-m` remaps any of them by name or `#rrggbb`. `--colours`
lists them (QML / SVG colours, then each image and animation) without building
anything; a name applies to every part that has it.

## Steps

No step needs root. Install, apply and test need a single flavour and accent;
add `--dry-run` to only list what they would copy and run.

### Build (default)

A new look-and-feel package (`themes/catppuccin-<flavor>-<name>[-<accent>][-<suffix>]/`)
containing only the splash screen. As a derived work, its `metadata.json` keeps
the original authors, licence and website (catppuccinizer is added as an
author), and the original licence file is copied when there is one.
`--preview` is not available: use `--test`.

### Install

`--install` copies it to `~/.local/share/plasma/look-and-feel/`, where
*System Settings → Colours & Themes → Splash Screen* lists it.

### Apply

`--apply` installs, then selects it as the splash screen (`kwriteconfig6`,
`ksplashrc`). The splash screen in use before is remembered (in
`~/.local/state/catppuccinizer/ksplash.json`) for `--restore`.

### Test

`--test` shows the built package in a window (`ksplashqml --test --window`);
it closes by itself, or click it.

### Restore

`--restore` selects the previous splash screen again and removes the packages
catppuccinizer installed. It builds nothing.

See `catppuccinize ksplash --help` for all options.
