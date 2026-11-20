# Graphical interface

[← Back to the README](../README.md) · [Getting started](getting-started.md)

Everything the command line does, in a page of your browser: pick a target,
its source and options, see the equivalent command, run it, and look at the
results.

```bash
catppuccinize gui            # opens the page in your browser
catppuccinize-gui            # same thing, for a desktop launcher
```

The page is served by catppuccinizer itself on `127.0.0.1` (nothing leaves your
computer, no extra dependency). Stop it with Ctrl+C; it also stops by itself
ten minutes after the page is closed. `--port N` picks the port,
`--no-browser` only prints the address.

## Using it

1. **Target**: the tabs at the top (`plymouth`, `image`, `limine`, `ksplash`,
   `lut`).
2. **Source**
   - images: *Browse files…* (several at once, or a whole folder), drop them on
     the page, or type a path;
   - Plymouth: *Choose from catalogue…* lists the 80 adi1090x themes (fetched
     with git the first time, or those of your
     [local copy](plymouth.md#using-a-local-copy-of-the-adi1090x-themes);
     *tuned* ones have a hand-made colour config), or browse to any theme folder;
   - KDE splash: the catalogue lists the splash screens installed on the
     system;
   - Limine: the wallpaper is optional.
3. **Colours**: click a flavour (Ctrl/Shift+click for several, one result
   each) and an accent. The page itself takes the colours you choose. Both are
   kept when you switch targets. When the chosen method cannot use the accent
   (`lut`, `lutgen`), the accents are dimmed and the hint says why; with
   `auto` it depends on each image, so the output notes it after the run
   (*the accent was ignored* next to *Done*).
4. **Options**: every option of the target, with its help. Options that only
   apply to a method or a setting show up when it is chosen: `--keep-lum` and
   `--smooth` with `auto` / `lut`, the `--lutgen-*` ones with `lutgen` (and
   each algorithm's own knobs with that algorithm), `--hald-level` /
   `--cube-size` with their format.
5. **Preview** renders the before/after images (`--preview`); **Build** writes
   the result into the output folder, without sudo and without installing
   anything (the line under the buttons says where). The output folder defaults
   to `./<target folder>` in the folder the GUI was started from.

The *Command* box always shows the exact `catppuccinize …` line the page runs,
with the error the command line would give when something is missing (hover a
step button to see its own command). Copy it to script the same thing later.

### Remapping a colour

As soon as a source is chosen, the *Colours* card lists its **source colours**,
before any run: for each image (or Plymouth image group), the method it will
get, then each colour -m can change, with its name, what it goes to and its
share. It is `catppuccinize … --colours` ([Colours and mapping](colours.md#manual-mapping)),
run again when the source or an option that changes the analysis (`--method`…)
changes; *Analyse again* reruns it (e.g. after editing the files).

Click a colour: a row is added to *Colour remapping (-m)*, where you choose its
new target; the list then shows the new target. A name the analysis did not
find is underlined in red (a `#rrggbb` source colour is always accepted). When
nothing can be remapped (`--method lut`, a LUT has no source colours), the
editor is hidden and the list says why.

### Install, apply, test, restore

Targets that can change the system (Plymouth, Limine, KDE splash) get one
button per step under *Preview* and *Build*: **Install**, **Apply** (installs
first), **Test**, **Restore** ([what each one does](architecture.md#steps)).
Each button builds, then runs its step; *Restore* only undoes. Their settings
(`--esp`, `--conf`…) are in the *System steps* group of the options.

- **Dry run**: the step only lists the files it would copy, change or remove
  and the commands it would run; nothing is changed. A step marked **sudo**
  still asks for the password: it may have to read the system (the ESP).
- A button marked **sudo** runs the command with sudo: the password is asked by
  a graphical prompt (`ksshaskpass`, `ssh-askpass`…, through `SUDO_ASKPASS`).
  Without one, copy its command (hover the button) and run it in a terminal.
  *Always with sudo* runs the other buttons with sudo too.

## Security

The server only listens on `127.0.0.1` and runs as your user: started with
sudo, it refuses (it would serve root's files); the steps that need root ask
for the password themselves. It refuses any request:

- without the random token of the address;
- whose `Host` is not the local address (DNS rebinding);
- sent by another site's page: an `Origin` that is not the GUI's, or a
  `Sec-Fetch-Site` other than `same-origin` / `none` (CSRF).

What the page can reach:

| Request | Allowed |
|---|---|
| files and thumbnails | images only (by extension), readable by you, not in `/proc`, `/sys`, `/dev`, `/run`, up to 200 MB; a link is judged by the file it points to |
| open (`xdg-open`) | folders, images and plain text outputs (`.conf`, `.txt`, `.json`, `.toml`, `.cube`), never a script or a `.desktop` file |
| folder listing | any folder you can read (the file browser) |
| upload | images up to 200 MB, in `~/.cache/catppuccinizer/gui-uploads/<random>/` (only for you, `700`), the name reduced to letters, digits, `.`, `_`, `-` |
| run, command, colours | a known target and its declared options only; values are text, numbers or on/off, without control characters, and never start with `-` (no value can pass for an option) |

Non-HTML answers forbid scripts (an SVG opened on its own cannot read the
token), and requests are limited in size (1 MB of JSON).

## For target authors

The forms are built from the options the target declares (`Target.options()`,
see [Architecture](architecture.md#options)), the same ones the command line
is built from, so a new target (or one added by an entry point) appears in the
GUI without GUI code:

- a positional argument, or an option with `source=True`, goes to the
  *Source* card; `accept` picks what the file browser offers (`image`,
  `images`, `dir`, `file`), and `image` / `images` sources accept dropped files;
- `choices` become buttons, a `range` a slider, `kind="colour"` a palette
  colour list;
- `when` shows an option only when it matters: `--lutgen-*` with
  `--method lutgen`, `--lutgen-radius` with `--lutgen-algo blur`, `-m` only
  for targets that have colours to remap; options whose `when` is not met are
  left out of the command;
- a step option (`options.step()`) becomes a button, `sudo="run"` marks it
  **sudo** and runs it with sudo; options of the `install` / `apply` / `test` /
  `restore` stages go to the *System steps* group, the other ones of `analyse`
  to *Analyse*;
- `Target.colours()` fills the *Source colours* list and its `when`
  facts (`analysis.remappable`: the remap editor is shown only when something
  can be remapped);
- `gui=False` keeps an option out of the forms (`--colours`: the page shows
  that list by itself; `--list` repeats the catalogue);
- `Target.sources()` fills the catalogue (see [Architecture](architecture.md));
- `Target.accent_also` names what still uses the accent when `--method` is a
  LUT (Limine: the menu colours); without it, the accents are dimmed then.
