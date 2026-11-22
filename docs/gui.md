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
   `lut`, `grub`, and your [TOML targets](architecture.md#declarative-targets-toml)).
2. **Source**, from three places, a button each (or type a path):
   - *System locations…*: what this computer has, in sections, with what the
     system uses now marked *in use*; a section that cannot be read (an ESP
     only root can read) says why, the others are still there;
   - *Browse files…* / *Browse folders…*: any file or folder (your Pictures and
     Downloads folders are in its places); images can also be dropped on the
     page;
   - *Other sources…*: more on the web. Some sources are browsed right in the
     panel (*online sources*: Wallhaven, Gnome-look, the KDE Store,
     adi1090x's release), one tab each: search, pages of thumbnails, and a
     click downloads the file into `~/.cache/catppuccinizer/downloads/`,
     unpacks an archive and fills the field (one or more for a source that
     takes several). An item with several files (variants) first lists them;
     an archive holding several themes lists them too. The others are web pages, opened in your browser:
     download there, extract an archive, then choose what you downloaded with
     *Browse…*.

   What each target offers:
   - images: the wallpapers installed in `/usr/share/wallpapers`,
     `/usr/share/backgrounds` and `~/.local/share/wallpapers` (a KDE wallpaper
     package: its largest image); other sources: Wallhaven (in the panel,
     safe for work images only), the KDE Store wallpapers (in the panel, its
     images: wallpaper packages are left out), Unsplash;
   - Plymouth: left empty, the theme in use is recoloured. The installed themes;
     other sources: [adi1090x/plymouth-themes](plymouth.md#getting-themes) (80
     animations, in the panel without thumbnails: its previews are animated
     GIFs of a few MB, shown on its page) and the Gnome-look Plymouth themes (in
     the panel);
   - KDE splash: the splash screens installed for you and for the system;
     other sources: the KDE Store splash screens (in the panel);
   - Limine: the wallpaper is optional: left empty, only the menu colours
     change and the current wallpaper is kept (the card says so). The
     wallpaper set in `limine.conf` (*in use*: choose it to recolour it) and the
     installed wallpapers; when only root can read the ESP, *Current Limine
     wallpaper* (`--wallpaper current`) is read when the command runs, with
     sudo. Other sources: as for images;
   - GRUB: the installed themes; other sources: the Gnome-look GRUB themes (in
     the panel) and Gorgeous GRUB.
3. **Colours**: click a flavour (Ctrl/Shift+click for several, one result
   each) and an accent. The page itself takes the colours you choose. Both are
   kept when you switch targets. When the chosen method cannot use the accent
   (`lut`, `lutgen`), the accents are dimmed and the hint says why (`lut-accent`
   gives it to each image's main colour); with
   `auto` it depends on each image, so the output notes it after the run
   (*the accent was ignored* next to *Done*).
4. **Options**: every option of the target, with its help; **?** next to an
   option opens a longer explanation and, for the colour options, a comparison
   picture (click it to enlarge). The flavours, the accents, the remapping and
   the system steps have one too. An option that has no effect with the
   current choices is greyed, and hovering it says why: `--keep-lum`,
   `--smooth`, `--chroma` and `--dark-fade` need `auto` / `lut`, `--auto-fit`
   `auto`, the `--lutgen-*` ones `lutgen` (and each
   algorithm's own knobs that algorithm; the whole group stays folded until
   then), `--separation` `auto` / `keys`, `--hald-level` / `--cube-size` their
   format; for Limine, the recolouring options and `--style` need a wallpaper.
   Preview, Build and the system steps are greyed the same way when their
   command would fail (several accents for Install, no animation for
   Preview animation…): the tooltip gives the command line's own message.
5. **Live preview**: as soon as an image is chosen (`image`, Limine's
   wallpaper), the top of the right column shows it recoloured, updated as you
   change the flavour, the accent, the method, the sliders or `-m`. Drag across
   it to compare: the original on the left of the line, the result on its
   right. A folder or several images: the list under it picks the one shown.
   The line under it says the method used (with `auto`, what it chose), the
   first flavour and accent (as *Preview image*), whether the accent is
   ignored, and how long the update took
   ([how it works](#live-preview)). It shows the picture being recoloured,
   not a whole theme: for Limine, the wallpaper without the menu (*Preview
   image* draws the menu); for themes and splash screens, the previews below.
6. **Preview image** renders one before/after image (`--preview`), **Preview
   animation** the main animation of a Plymouth theme or splash screen
   (`--preview-animation`, played in the page), both for the first flavour and
   accent ([previews](colours.md#previews)); **Build** writes
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

### Live preview

The live image is rendered by the GUI server itself, without starting
`catppuccinize`, on a copy of the image reduced to 512 pixels: what you see is
the build's recolouring, at a smaller size. The analysis of an image (its
source colours, which method `auto` picks) is done once on the full image, as
the build does it, and kept while the GUI runs; moving a slider then only
renders the small copy again, in 2 to 60 ms (measured on 4K pictures); so
does *Auto: keys tolerance*, which only decides again from what was found. An
option that changes the analysis (*Colour separation*, the method) analyses
the full image again the first time a value is used: about 0.3 s for a 5
megapixel picture, 0.6 s for a 4K one, *Analysing the image…* meanwhile. The page waits
120 ms after the last change before asking, and sends one request at a time.

### Parts and remapping a colour

As soon as a source is chosen, the *Colours* card lists the **parts** of the
result and their **source colours**, before any run. Each
[part](colours.md#parts-an-accent-each) (Limine's menu and wallpaper, each
Plymouth image group and its progress bar…) says what changes it (flavour,
accent, method, `-m`) and has its own accent choice: *as above* follows the
*Accent* picker, another one becomes `-a PART=ACCENT`. A part with nothing
mapped to the accent says so. Under it: each image (or image group), the method
it will get, then each colour -m can change, with its name, what it goes to and
its share. It is `catppuccinize … --colours` ([Colours and mapping](colours.md#manual-mapping)),
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

Targets that can change the system (Plymouth, Limine, KDE splash, GRUB) get one
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
| run, command, colours, live | a known target and its declared options only; values are text, numbers or on/off, without control characters, and never start with `-` (no value can pass for an option) |
| live preview | one of the still images of the target's image source, under the rules of files above; rendered in the server's process, nothing written |

Non-HTML answers forbid scripts (an SVG opened on its own cannot read the
token), and requests are limited in size (1 MB of JSON).

The page itself reaches nothing outside the server: the web pages of the
other sources are plain `https://` links (a target cannot declare another
kind), opened in a new tab, without the page's address (`noopener`,
`noreferrer`: the token stays here). The online sources are reached by the
server, only when the panel asks:

| Online sources | Rule |
|---|---|
| hosts | `https://` only, to the hosts the source declares (Wallhaven: `wallhaven.cc`, `w.wallhaven.cc`, `th.wallhaven.cc`; Gnome-look and the KDE Store: their API host, `*.pling.com` and the storage host their downloads are sent to; a GitHub release: `api.github.com`, `github.com` and its release storage hosts), redirects included; 20 s per request |
| search | the source's API, its answer read as data (4 MB at most) |
| thumbnails | fetched by the server (4 MB at most), decoded and written again as JPEG: the page still loads images from the server only |
| downloads | an item the source lists, by its id (checked), up to 200 MB, written in full then renamed, only for you (`700` / `600`); checked against the digest the site gives (the stores' MD5, GitHub's SHA-256 of newer assets); a file already there is used again; a download that is not an image is removed |
| archives | (Gnome-look, the KDE Store, a GitHub release) `.zip` and `.tar.*` only, unpacked in a new folder: no absolute name or `..`, no link or device, 5000 files and 500 MB at most; the archive is then removed, and so is what holds no theme folder |

## For target authors

The forms are built from the options the target declares (`Target.options()`,
see [Architecture](architecture.md#options)), the same ones the command line
is built from, so a new target (or one added by an entry point) appears in the
GUI without GUI code:

- a positional argument, or an option with `source=True`, goes to the
  *Source* card; `accept` picks what the file browser offers (`image`,
  `images`, `dir`, `file`), and `image` / `images` sources accept dropped files
  and get the live preview (`core.recolor.plan()` and `render()` with the
  method options: a target whose images are recoloured otherwise should not
  declare its source this way);
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
  that list by itself; `--list` repeats the system locations and other sources);
- `Target.locations()` fills *System locations…*, by sections, with thumbnails
  and what is *in use*; `Target.online` (browsed in the panel) and
  `Target.links` (web pages) fill *Other sources…* (see
  [Architecture](architecture.md#writing-a-target));
- `Target.accent_also` names what still uses the accent when `--method` is a
  LUT (Limine: the menu colours); without it, the accents are dimmed then.
