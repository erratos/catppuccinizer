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
5. **Preview** renders the before/after images (`--preview`); **Run** writes
   the result. The output folder defaults to `./<target folder>` in the folder
   the GUI was started from.

The *Command* box always shows the exact `catppuccinize …` line the page runs,
with the error the command line would give when something is missing. Copy it
to script the same thing later.

### Remapping a colour

After a run (a preview is enough), the colours that were detected are listed
under the output, with what they were mapped to. Click one: it is added to
*Colour remapping* in the Colours card, where you choose its new target.
This is the same as `-m NAME=TARGET` ([Colours and mapping](colours.md)).

### Install, apply, test

Options that change the system (`plymouth --install / --test`,
`limine --apply / --remove`, `ksplash --install`) work from the page too.
When an option needs root (marked **sudo**), *Run with sudo* is ticked (for
`limine`; Plymouth's helper scripts ask for it themselves): the
password is asked by a graphical prompt (`ksshaskpass`, `ssh-askpass`…, through
`SUDO_ASKPASS`). Without one, copy the command and run it in a terminal.

## Security

The address contains a random token; the server refuses any request without
it, and any request whose `Host` is not the local address. It only listens on
`127.0.0.1`. Dropped images are copied into `~/.cache/catppuccinizer/gui-uploads/`.

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
- `sudo="run"` ticks *Run with sudo*; `sudo="self"` (the target calls sudo
  itself, like `plymouth --install`) only needs the graphical password prompt;
  both show a **sudo** badge;
- `gui=False` keeps an option out of the forms (`--colours` lists, it does not run);
- `Target.sources()` fills the catalogue (see [Architecture](architecture.md));
- `Target.accent_also` names what still uses the accent when `--method` is a
  LUT (Limine: the menu colours); without it, the accents are dimmed then.
