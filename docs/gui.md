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
     the page, or type a path; *Choose from catalogue…* shows the wallpapers
     installed in `/usr/share/wallpapers`, `/usr/share/backgrounds` and
     `~/.local/share/wallpapers` (a KDE wallpaper package: its largest image);
   - Plymouth: left empty, the theme in use is recoloured. The catalogue shows
     the installed themes first (the one in use marked *in use*), then an extra
     catalogue, the 80 adi1090x themes (fetched with git when chosen, or those
     of your [local copy](plymouth.md#using-a-local-copy-of-the-adi1090x-themes));
     or browse to any theme folder;
   - KDE splash: the catalogue lists the splash screens installed for you and
     for the system, the selected one marked *in use*;
   - Limine: the wallpaper is optional: left empty, only the menu colours
     change and the current wallpaper is kept (the card says so). The
     catalogue shows the wallpaper set in `limine.conf` (*in use*: choose it
     to recolour it) and the installed wallpapers; when only root can read the
     ESP, *Current Limine wallpaper* (`--wallpaper current`) is read when the
     command runs, with sudo.

   The catalogue is grouped in sections; one that cannot be read (no network
   for the adi1090x themes, an ESP only root can read) shows why, the others
   are still there.
3. **Colours**: click a flavour (Ctrl/Shift+click for several, one result
   each) and an accent. The page itself takes the colours you choose. Both are
   kept when you switch targets. When the chosen method cannot use the accent
   (`lut`, `lutgen`), the accents are dimmed and the hint says why; with
   `auto` it depends on each image, so the output notes it after the run
   (*the accent was ignored* next to *Done*).
4. **Options**: every option of the target, with its help; **?** next to an
   option opens a longer explanation and, for the colour options, a comparison
   picture (click it to enlarge). The flavours, the accents, the remapping and
   the system steps have one too. An option that has no effect with the
   current choices is greyed, and hovering it says why: `--keep-lum` and
   `--smooth` need `auto` / `lut`, the `--lutgen-*` ones `lutgen` (and each
   algorithm's own knobs that algorithm; the whole group stays folded until
   then), `--separation` `auto` / `keys`, `--hald-level` / `--cube-size` their
   format; for Limine, the recolouring options and `--style` need a wallpaper.
   Preview, Build and the system steps are greyed the same way when their
   command would fail (several accents for Install, no wallpaper for a
   Limine preview…): the tooltip gives the command line's own message.
5. **Preview** renders the before/after images (`--preview`); **Build** writes
   the result into the output folder, without sudo and without installing
   anything (the line under the buttons says where). The *Output* card sets
   the folder (by default `./<target folder>` in the folder the GUI was started
   from) and `--suffix`, the word added to the output names.

The *Command* box always shows the exact `catppuccinize …` line the page runs,
with the error the command line would give when something is missing (hover a
step button to see its own command). Copy it to script the same thing later.
Under it, the files and folders **Build** would write are listed as you change
the options (`catppuccinize … --names`); those already there are marked
*replaced*.

### Remapping a colour

As soon as a source is chosen, the *Colours* card lists its **source colours**,
before any run: for each image (or Plymouth image group), the method it will
get, then each colour -m can change, with its name, what it goes to and its
share. It is `catppuccinize … --colours` ([Colours and mapping](colours.md#manual-mapping)),
run again when the source or an option that changes the analysis (`--method`…)
changes; *Analyse again* reruns it (e.g. after editing the files).

Click a colour: a row is added to *Colour remapping (-m)*, where you choose its
new target; the list then shows the new target. *Colour separation*
(`--separation`) changes the list as it moves: raise it when a part of the
image is missing from it ([Separating colours](colours.md#separating-colours)).

A colour the analysis missed can be picked in a preview: open one (click it
under *Results*) and click a colour of the **original** image, on the left. It
is added as a `#rrggbb` row, a source colour of its own once you choose its
target. The preview's third panel, for pictures recoloured with `keys`, shows
the colour each pixel is attached to. A name the analysis did not
find is underlined in red (a `#rrggbb` source colour is always accepted). When
nothing can be remapped (`--method lut`, a LUT has no source colours), the
editor is hidden and the list says why.

### Install, apply, test, restore

Targets that can change the system (Plymouth, Limine, KDE splash) get one
button per step under *Preview* and *Build*: **Install**, **Apply** (installs
first), **Test**, **Restore** ([what each one does](architecture.md#steps)).
Each button builds, then runs its step; *Restore* only undoes. Their settings
(`--esp`, `--conf`…) are in the *System steps* group of the options; a step
that takes a value has its field next to its button (Plymouth's **Test**: how
many seconds, 10 by default).

- **Dry run**: the step only lists the files it would copy, change or remove
  and the commands it would run; nothing is changed. A step marked **sudo**
  still asks for the password: it may have to read the system (the ESP).
- A button marked **sudo** runs the command with sudo: the password is asked by
  a graphical prompt (`ksshaskpass`, `ssh-askpass`…, through `SUDO_ASKPASS`).
  Without one, copy its command (hover the button) and run it in a terminal.
- **with sudo**, next to *Build*: runs *Preview* and *Build*, and the analysis
  of the source colours, with sudo, to read files only root can read (Limine's
  wallpaper on an ESP only root can read). What they write is handed back to
  you.

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
| open (`xdg-open`) | folders, images and plain text outputs (`.conf`, `.txt`, `.json`, `.cube`), never a script or a `.desktop` file |
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
- `when`, `needs` and `unless` grey an option out while it has no effect, with
  the reason as its tooltip: `--lutgen-*` without `--method lutgen`, Limine's
  `--style` without a wallpaper (`needs`), two options that exclude each other
  (`unless`); such options are left out of the command; `empty` says what
  leaving a source empty does (Limine: only the menu colours change).
  A `when` on an analysis fact (`-m` only when something can be remapped)
  hides the option instead;
- `label` is the name shown for an option ("Keep lightness" for
  `--keep-lum`);
- a step option (`options.step()`) becomes a button, `sudo="run"` marks it
  **sudo** and runs it with sudo, an optional value (`nargs="?"`, `--test
  [SECONDS]`) a field next to it; options of the `install` / `apply` / `test` /
  `restore` stages go to the *System steps* group, the other ones of `analyse`
  to *Analyse*;
- `Target.outputs()` fills the list of what Build would write;
- `Target.colours()` fills the *Source colours* list and its `when`
  facts (`analysis.remappable`: the remap editor is shown only when something
  can be remapped);
- `explain` and `image` fill the **?** panel of an option (a step's text starts
  with what every target's step does);
- `gui=False` keeps an option out of the forms (`--colours`: the page shows
  that list by itself; `--list` repeats the catalogue);
- `Target.sources()` fills the catalogue, by sections, with thumbnails and
  what is *in use* (see [Architecture](architecture.md#writing-a-target));
- `Target.accent_also` names what still uses the accent when `--method` is a
  LUT (Limine: the menu colours); without it, the accents are dimmed then.
