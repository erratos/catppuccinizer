# Architecture

[← Back to the README](../README.md)

catppuccinizer is a small **core library** plus independent **targets**
(subcommands of `catppuccinize`). The rule that keeps it from turning into a
tangle: *a target only talks to the core, never to another target*, and the
core never knows about targets. `tests/test_architecture.py` enforces it.

```
catppuccinizer/
  cli.py              builds the command line from the discovered targets
  gui/                `catppuccinize gui`: local web page built from the same options
    live.py           its live preview: render in the server's process, on a reduced image
  core/
    options.py        Option: every option declared once (CLI + GUI), the common ones
    system.py         System: every change of the install / apply / test / restore steps
    palette.py        Catppuccin palettes, colour helpers, Oklab
    detect.py         background + source colours of a group of images
    mapping.py        --map overrides, automatic mapping of plain colour lists
    recolor.py        keys method, LUT methods (lut, lutgen), auto choice, render/save/preview
    clut.py           3D LUTs: trilinear application, resampling, Hald CLUT and .cube files
    lutgen.py         --lutgen-* options, runs the external lutgen binary
    formats.py        colours written as text (QML, SVG/SVGZ, theme files), animations (GIF, WebP)
    folder.py         a theme folder recoloured by parts: text files, images, animations
    textscreen.py     a boot menu's text screen (bitmap font, cells, margin), for previews
    paths.py          cache / restore state, sudo-aware home and ownership
    naming.py         output names (catppuccin-<flavor>-<source>[-<accent>][-<suffix>])
    target.py         Target base class + discovery (Python, TOML, entry points, the user's TOML)
    declarative.py    targets described in TOML (a theme folder, install, KEY="value" settings)
    sources.py        ready-made sources (catalogue, --list): sections, items, wallpapers
  targets/
    plymouth/         Plymouth themes (+ adi1090x fetcher, scripts)
    image.py          images (wallpapers, logos…)
    limine.py         Limine boot menu
    ksplash.py        KDE Plasma splash screen
    lut.py            LUT export (Hald CLUT, .cube)
    grub.toml         GRUB themes: a declarative target
tests/
  test_regression.py  every target on small fixtures, compared with golden.json
  test_steps.py       System, step chaining, each target's steps in a dry run
  test_architecture.py
  test_options.py     every declared option is complete and coherent
  test_gui.py         forms, command lines, access control, live preview of the GUI
  test_security.py    names, links, atomic writes, backups, commands, GUI requests
  test_sources.py     catalogue sections, installed themes and wallpapers, --list
  test_outputs.py     --names of every target against what the build writes
  test_previews.py    --preview / --preview-animation: first flavour and accent, no build
  test_folder.py      core.folder (parts of a theme folder) and the "hex" colour syntax
  test_declarative.py TOML targets: schema, trust, discovery, steps in a temporary home
```

## Core API (what targets use)

| Function | Purpose |
|---|---|
| `detect.detect_group(paths, is_ui, params)` / `detect.detect_params(separation)` | detect the background and source colours of images, with automatic targets; the thresholds (`DetectParams`) from `--separation` (the default gives the default thresholds) |
| `mapping.apply_maps(cfg, maps, strict)` | apply `-m NAME=TARGET` to `{"groups": {name: group}}` |
| `mapping.map_colour_counts(counts)` | map a `{#hex: count}` list (QML, SVG, CSS…) to Catppuccin roles |
| `mapping.resolve_target(flavor, accent, target)` | target name -> RGB |
| `mapping.colour_report(source, method, colors, ..., part, accent)` / `recolor.colour_report(path, method, grp, part=)` | one entry of `--colours` (names as `-m` accepts them, source, target, share; the part it belongs to and whether it uses the accent) |
| `parts.accent_sets(args, using)` / `check_parts(args, known)` / `note_unused(args, using)` / `single(args, parts)` | the results to write from `-a` (`PART=ACCENT` entries: `args.part_accents`), each with its accent per part and the accent of its output name |
| `mapping.uses_accent(colors)` / `note_accent_ignored(a, reason)` | whether a colour goes to `accent`; the note printed when `-a` was given for nothing |
| `recolor.recolor_image(path, bg, keys, targets, base)` / `keys_plan(grp, flavor, accent)` | keys method on one image (alpha kept); the `bg, keys, targets, base` of a detected group for a flavour and an accent |
| `recolor.run_jobs(jobs)` / `render_job(job)` | `render()` + save of many images, `(src, dst, method, grp, flavor, accent, a)` each, in worker processes when there are more than 8 |
| `recolor.plan(path, args, memo=None)` / `render(...)` / `save_image(...)` | one image, method chosen automatically (keys or LUT); `memo`: a dict the caller keeps for the file, where the analysis (per `--separation`) and the dominant hue are kept for the next call (the GUI's live preview); `render` also takes a PIL image |
| `options.Option(...)` / `options.defaults(opts, **values)` | declare an option ([below](#options)); a namespace of defaults for scripts |
| `recolor.method_options(methods=None, help=None, needs=None, keys_always=False)` | `--method`, `--separation`, `--keep-lum`, `--smooth`, `--lutgen-*` (only the given methods; `keys_always`: `--separation` matters whatever `--method`, for a target that also recolours with keys on its own) |
| `recolor.SEPARATION` / `side_by_side(src, im, out, grp)` / `separation_image(path, grp)` | the `--separation` option (Plymouth adds it alone); a before/after preview, with a keys group the separation panel |
| `textscreen.TextScreen(size, background, foreground, wallpaper, margin, gradient, scale)` / `console_font()` | a text screen as a boot loader draws it (Limine's terminal: margin, fade, see-through background), in the system's VGA console font: `put(col, row, text, fg, bg)`, `image()` |
| `options.PREVIEW_ANIMATION` / `options.previewing(args)` / `recolor.preview_animation(pairs, n, out, duration)` | `--preview-animation` (added by the targets whose result moves); whether a preview is asked for (the command line then keeps the first flavour and accent and runs no step); (before, after) frames as an animated WebP |
| `recolor.LUT_METHODS` / `NO_ACCENT_METHODS` / `lut_for(method, flavor, args, n, accent, hue)` | the LUT methods (no source colours), those without accent (all but `lut-accent`), and their cube (`lut-accent`: the accent given to `dominant_hue(path)`) |
| `recolor.accent_ignored_reason(method, grp)` | why the accent has no effect on an image, or None |
| `clut.apply_cube` / `resample` / `read_hald` / `write_hald` / `write_cube` | 3D LUT application and files |
| `formats.collect_text_colours(files, syntax)` / `recolour_text_file(f, lookup, syntax)` | colours inside text files, written as `qml`, `svg` or `hex` (`"#rrggbb"` strings: GRUB's `theme.txt`); `syntax_of(path)` from the extension |
| `folder.Part(name, kind, files)` / `analyse(root, parts, a)` / `results(a, fold, parts)` / `colours(fold)` / `write(fold, flavor, accents, a, out_of, done)` / `preview_still` / `preview_moving` | a theme folder recoloured as a whole ([below](#theme-folders)) |
| `mapping.text_colours(files, maps, strict, group)` / `text_lookup(colors, flavor, accent)` | the colours of text files mapped to roles, after `-m`; their `{#source: #new}` for a flavour and accent |
| `formats.is_animated(f)` / `anim_info` / `anim_frames` / `anim_sample` / `save_animation(...)` | animated GIF and WebP, streamed frame by frame |
| `recolor.recolor_frames(frames, ...)` | keys method over a stream of frames, in parallel |
| `paths.cache_dir()` / `give_back(path)` | where to store things (the invoking user's home under sudo), sudo ownership |
| `paths.state_file(target, system)` | where a step keeps what `restore` needs (the theme in use before…) |
| `system.System` | `copy_tree`, `copy_file`, `write_text(…, backup=True)`, `remove`, `run`, `load_state` / `save_state`: every change a step makes, printed (only listed with `--dry-run`) |
| `System.install_tree(src, base, state)` / `keep_previous(state, current, name)` / `restore_state(state)` / `uninstall(state, base, names)` | results installed as folders of one system folder: copied and remembered; what apply replaced, remembered once; for restore, the state and the installed names (checked); removed |
| `system.get_variable(text, key)` / `set_variable(text, key, value, raw)` / `unquote(raw)` | a `KEY="value"` file (`/etc/default/grub`): the raw value; the text with it set (checked and quoted), restored (`raw`) or removed (`None`), the rest byte for byte |
| `paths.config_dir()` | the user's configuration folder (`~/.config/catppuccinizer`, the invoking user's under sudo) |
| `declarative.load(path, builtin)` | the `Target` a TOML file describes ([below](#declarative-targets-toml)) |
| `sources.theme_folders(base, marker)` | the theme folders of a folder: those with a file matching `marker` (`"*.plymouth"`) |
| `system.place(base, name)` / `naming.check_name(name)` | a system path built from a theme or package name, checked first (no `/`, `..`, leading `-`) |
| `system.copy_folder(src, dst)` / `source_file(path, root)` | copy a source theme without following links out of it; the file to read for a theme file, or None |
| `system.which(name)` / `read_text(path)` | a command's absolute path (as root: system folders only); a text file as it is, for a byte-exact rewrite |
| `options.step(name, help, sudo, explain)` | the option of a system step: `--install`, `--apply`, `--test`, `--restore`; its long text is the common one (`STEP_EXPLAIN`) followed by `explain`, what this target's step does |
| `options.image_file(image)` | the file of an option's illustration |
| `naming.output_name(flavor, source, accent, suffix)` / `slug(text)` | the name of every output: `catppuccin-<flavor>-<source>[-<accent>][-<suffix>]` |
| `naming.planned(path, folder)` | one entry of `outputs()` / `--names` (`exists`: the build would replace it) |
| `recolor.output_suffix(method, src)` | the extension a recoloured image gets (a LUT keeps an opaque JPEG / WebP) |

## Writing a target

A target that recolours a theme folder, copies it and sets a `KEY="value"`
line may need no code: see [declarative targets](#declarative-targets-toml).
Otherwise, in Python:

```python
# catppuccinizer/targets/sddm.py   (or any package, see below)
"""SDDM target: recolour an SDDM login theme (Main.qml + images)."""
from pathlib import Path

from ..core import recolor
from ..core.options import Option, step
from ..core.target import Target


class SddmTarget(Target):
    name = "sddm"
    help = "recolour an SDDM login theme"
    accent_also = "the menu colours"   # optional: what uses -a even with --method lut
    # unused_common = ("preview",)     # optional: common options that mean nothing here

    def options(self):
        return [
            Option("theme", accept="dir", help="theme folder"),
            *recolor.method_options(),
            step("install", sudo="run", help="copy the theme to /usr/share/sddm/themes (sudo)"),
            step("apply", sudo="run", help="install, then select it in /etc/sddm.conf.d/ (sudo)"),
            step("restore", sudo="run", help="select the previous theme again (sudo)"),
        ]

    def build(self, a):
        # a.flavor, a.accent, a.map, a.preview, a.out, a.suffix are already resolved;
        # name outputs with naming.output_name(flavor, source, accent, a.suffix).
        # Write into a.out only; return what the steps work on (or None).
        ...
        return a.out / name

    def install(self, a, built, system):
        system.install_tree(built, "/usr/share/sddm/themes", state_file("sddm", system=True))

    def apply(self, a, built, system):
        ...                      # system.write_text(..., backup=True), system.run([...])

    def restore(self, a, system):
        ...


TARGET = SddmTarget()
```

Optionally, `def sources(self)` returns ready-made sources for the source
argument, in sections: the GUI shows them as a catalogue, and `--list` is added
to the target's options to print them.

```python
from ..core.sources import item, section, wallpaper_sections

def sources(self):
    return [section("Installed (/usr/share/sddm/themes)", installed),   # installed() yields items
            *wallpaper_sections()]                             # the system's wallpapers

def installed():
    for d in theme_folders("/usr/share/sddm/themes", "metadata.desktop"):
        yield item(d, label=d.name, note="", current=d.name == active_theme(), thumb=d)
```

`item(value, label, note, current, thumb)`: `value` goes into the argument
(a path or a name), `current` marks what the system uses now (shown *in use*,
`*` in `--list`), `thumb` is an image or folder for the GUI's thumbnail.
`section(title, make)` calls `make()` and turns a failure (`SystemExit`, no
network, no rights) into the section's `error`, so one section that cannot be
read does not hide the others. Plymouth: installed themes + adi1090x; image:
the wallpapers; Limine: the wallpaper of `limine.conf` + the wallpapers; KDE
splash: the user's and the system's splash screens. The GUI needs nothing else:
its forms come from `options()`
(see [Graphical interface](gui.md#for-target-authors)).

Optionally too, `def colours(self, a)` does only the analysis and returns the
colours `-m` can remap, as `mapping.colour_report(...)` entries (or
`recolor.colour_report(path, *recolor.plan(path, a, verbose=False))` for an
image). It must write nothing. When a target defines it, `--colours` and
`--json` are added to its options and the command line prints the list.

Each entry may name its `part` (`-a PART=ACCENT`, see
[Colours and mapping](colours.md#parts-an-accent-each)) and whether it uses
the accent; the GUI groups the list by part, with an accent choice each. The
target then loops over `parts.accent_sets(a, using)` instead of the accents:
`using` lists the parts that use one, main first, and each result comes with
its accent per part and the name to give `output_name()`. `check_parts(a,
known)` refuses a part the result does not have.

Optionally as well, `def outputs(self, a)` returns what `build()` would write
with these options, in the order it writes them, as `naming.planned(path,
folder)` entries (files and folders; the files inside a written folder may be
listed too). It may analyse (whether the accent is used decides the names) but
writes nothing. It adds `--names` (and `--json`) and fills the GUI's list under
the command; `tests/test_outputs.py` checks it against a real build.

Then add `"sddm"` to `BUILTIN` in `core/target.py`, or, from another package,
declare an entry point and install it next to catppuccinizer:

```toml
[project.entry-points."catppuccinizer.targets"]
sddm = "my_package.sddm:TARGET"
```

### Theme folders

A target whose source is a folder of files to recolour (KDE splash, the TOML
targets) describes its parts with `core.folder.Part(name, kind, files)`: `kind`
is `text` (colours written in the files, `syntax` from the extension unless
given), `image` (still images, with the `--method` options) or `animation`
(GIFs and animated WebPs, keys frame by frame); `files` are globs relative to
the folder, without case, `*` going across folders. A file goes to the first
part it matches whose kind fits it; links out of the folder are left out.

```python
FILES = [Part("text", "text", ("*.qml", "*.svg")), Part("animations", "animation"),
         Part("images", "image")]
fold = folder.analyse(src, FILES, a)              # every file's colours, after -m
using, sets = folder.results(a, fold, FILES)      # parts that use the accent
done = {}
for flv in a.flavor:
    for accents, name in sets:
        copy_folder(src, dst)                     # the files no part takes stay as they are
        folder.write(fold, flv, accents, a, lambda f: dst / f.relative_to(src), done)
```

`write` recolours the copied text files in place and renders the pictures over
their copies, still images in parallel; `done` makes a picture that does not
use the accent rendered once per flavour, then copied. `colours(fold)` is the
`--colours` list; `preview_still` / `preview_moving` the `--preview` /
`--preview-animation` of the folder (the largest image, the longest animation).

### Steps

`build()` writes the result into the output folder (`--preview`: only
before/after images) and returns what the system steps work on. The steps are
optional methods, each with its option made by `options.step()`; the command
line runs build, then `install` (also for `--apply`), `apply` and `test`, in
that order. `restore` runs alone, without building; `--dry-run` is added to
targets that have steps.

| Step | Effect | Typical rights |
|---|---|---|
| `preview` | before/after images (`--preview`) or an animated WebP (`--preview-animation`) in `<out>/previews/`, first flavour and accent (`options.previewing()`) | user |
| `build` | the result in the output folder (default) | user |
| `install` | copied where the system looks for it, not selected | often root |
| `apply` | selected / configured | often root |
| `test` | shown without rebooting or logging out | depends |
| `restore` | `apply` and `install` undone | as `apply` |

A step changes the system only through the `System` object it gets: each change
is printed, and with `--dry-run` only listed. Reading the system (the current
theme, `limine.conf`) is done directly, also in a dry run, which therefore
keeps the step's rights. What `restore` needs (the theme in use before `apply`)
goes into `paths.state_file()` with `system.save_state()`. When a step needs
root, the whole command runs with sudo (`sudo="run"`): downloads
still come from the invoking user's home, and what build wrote is handed back
to them.

### Options

`options()` returns the target's own options only; the common ones (`-f -a -m
--preview -o -s`; `--list`, `--colours`, `--names`, `--json` when `sources()`,
`colours()`, `outputs()` are defined) are
declared once in `core/options.py`, the method ones in `core/recolor.py` and
`core/lutgen.py`. An `Option` takes the flags and the argparse fields (`type`,
`choices`, `default`, `nargs`, `metavar`, `const`; `switch=True` for an on/off
option), then:

| Field | Meaning |
|---|---|
| `label` | the name the GUI shows ("Keep lightness"); without it, the dest spaced and capitalised (`tests/test_options.py` asks one of every built-in option) |
| `help` | one line (`--help`, the GUI) |
| `explain`, `image` | a longer text and an illustration, shown by the GUI's **?** next to the option; `image` is a file of `catppuccinizer/assets/` (`"options-method.jpg"`, package data, made by `tools/doc_previews.py`) or an absolute path for a target from another package |
| `scope` | `common`, `method` / `method:<name>` (core) or `target` (default) |
| `stage` | `analyse`, `preview`, `build` (default), `install`, `apply`, `test`, `restore`; the GUI makes a button of each `preview` option, next to Build |
| `sudo` | `"run"`: the command must run as root |
| `when` | when it matters: `{"method": ["lutgen"]}` (another option's value) or `{"analysis.remappable": [True]}` (a fact from `--colours`); `method:<name>` options get `{"method": [<name>]}` |
| `needs` | options of which one must be given for this one to have an effect (Limine's `--style`: `["wallpaper"]`): the command line notes it, the GUI greys the option and says why; `recolor.method_options(needs=…)` puts it on every method option |
| `unless` | options it cannot go with: the command line refuses both (`use either …`), the GUI greys the other one |
| `empty` | what leaving it empty does, when worth saying (Limine's `--wallpaper`: only the menu colours change): shown by the GUI while it is empty |
| `source` | what is recoloured (positional arguments by default): the GUI's *Source* card |
| `accept` | for a path: `image`, `images` (files or folders), `dir`, `file` |
| `range` | `(low, high)`: checked after parsing, shown as a slider |
| `kind` | the GUI control when it cannot be guessed (`colour`: a palette colour) |

`tests/test_options.py` checks every declared option (a help, a known stage,
`sudo` only on a system stage, `when` naming existing options, one step option
per step method).

Add a case to `tests/test_regression.py` (small synthetic fixture) and run
`python3 tests/test_regression.py --update` once the output looks right.

## Declarative targets (TOML)

A target that recolours a **theme folder** and installs it by copying it and
setting a line of a configuration file needs no Python: a TOML file describes
it, and `core.declarative` turns it into a `Target` (options, `--colours`,
`--names`, `--list`, the GUI, `--preview`, the steps and `--dry-run` come with
it). GRUB is written this way: [`targets/grub.toml`](../catppuccinizer/targets/grub.toml).

### How far without code

A TOML target can say:

- **where its sources are**: a file every theme folder has (`marker`), the
  folders where themes are looked up by name (`search`, also the catalogue of
  `--list` and the GUI), a default;
- **what is recoloured**: its parts, each a `core.folder.Part` (name, kind
  `text` / `image` / `animation`, globs, colour syntax of the text files);
  everything else in the folder is copied as it is, except the `ignore` globs;
- **how results are named**: always `output_name(flavour, <folder name>,
  accent, suffix)`, like every target;
- **install**: copy the result to `<to>/<output name>`, as the user or with
  sudo;
- **apply**: set variables in configuration files of the `KEY="value"` kind
  (`/etc/default/grub`), each written atomically with a dated backup, then run
  commands;
- **restore**: generated: the variables get back their previous values (or
  their lines are removed when they had none), the commands that name no
  `{…}` run again, the installed results are removed.

What needs a decision about the content stays in Python: files generated from
scratch (KDE's `metadata.json`), formats edited by rules (Plymouth scripts, the
`limine.conf` block), drawing a whole screen for the preview, reading the
current setting through a command (`kreadconfig6`), a `test` step. Such a
target is written in Python, possibly next to TOML ones, with the same core.

### Commands in `apply`

Allowed, because most installs need one (`grub-mkconfig` after
`/etc/default/grub`), with these limits:

- **allow list**: the program must be one of `core.declarative.COMMANDS`
  (bootloader and cache refreshers); adding one is a change to catppuccinizer,
  reviewed like code. The arguments are fixed in the file; only `{name}` and
  `{installed}` are replaced, with checked names. No shell, and as root the
  program is looked up in the system folders only (`System.run`).
- **`--dry-run`**: every step goes through `System`, so `--dry-run` lists the
  commands with the files, and each one is printed before it runs.
- **confirmation**: the step itself (`--apply`, or its button in the GUI), as
  for Python targets; no prompt, which the GUI could not answer. `--dry-run`
  is the way to look first.

### Trust

- TOML files **shipped with catppuccinizer** (`catppuccinizer/targets/*.toml`)
  may use sudo (`install.sudo = true`) and write system files.
- TOML files of the **user** (`~/.config/catppuccinizer/targets/*.toml`, see
  [discovery](#discovery)) run with the user's rights only: `sudo = true` is
  refused, and the install folder and the files of `set` must be in the user's
  home. A file dropped in that folder (a download) should not become a root
  action; a target that needs root is a Python package the user installs, or a
  TOML file added to catppuccinizer.
- A user file writable by others than its owner, or owned by someone else
  than the user (or root), is skipped with a note.
- The schema is strict: an unknown key, a missing one or a wrong type stops
  that file with a message naming it; the other targets still work.

### Format

```toml
name = "grub"                         # the subcommand: a-z, 0-9, '-'
help = "recolour a GRUB theme"        # one line for catppuccinize --help
description = """…"""                 # the long --help (optional)
default_out = "themes"                # output folder (optional, default "themes")
ignore = ["*.bak"]                    # files left out of the result (optional)

[source]
marker = "theme.txt"                  # glob of a file every theme folder has
search = ["/boot/grub/themes", "/usr/share/grub/themes"]   # names, catalogue (optional)
default = "…"                         # when no source is given (optional)
label = "Theme"                       # the GUI's label (optional)
help = "installed theme name or theme folder"              # (optional)

[[parts]]                             # in order: a file goes to the first that takes it
name = "text"                         # -a text=ACCENT, -m text.NAME
kind = "text"                         # text | image | animation
files = ["*.txt"]                     # globs in the folder (default ["*"])
syntax = "hex"                        # text: qml | svg | hex (default: by extension)
label = "theme.txt"                   # text: its name in --colours (optional)

[install]
to = "/boot/grub/themes"              # results go to <to>/<output name>
sudo = true                           # needs root (built-in files only)
help = "…"                            # (optional)

[apply]                               # needs [install]
help = "…"
explain = "…"                         # the GUI's long text (optional)
set = [{ file = "/etc/default/grub", key = "GRUB_THEME", value = "{installed}/theme.txt" }]
run = [["grub-mkconfig", "-o", "/boot/grub/grub.cfg"]]

[restore]                             # optional: its help; restore exists with [install]
help = "…"
```

`{installed}` is `<to>/<output name>`, `{name}` the output name; paths are
absolute, `~/` being the user's home (the invoking user's under sudo), and
never hold `..`. A value of
`set` cannot hold `"`, `$`, `` ` ``, `\` or a line break, so it reads the same
in any shell. The previous values go into the target's state file
(`paths.state_file`): `restore` puts them back, and `apply` does not record a
value that already points to one of its results.

### Discovery

`core.target.discover()` loads, in this order, the built-in Python targets,
the built-in TOML files (`catppuccinizer/targets/*.toml`), the entry points,
then the user's TOML files (`$XDG_CONFIG_HOME/catppuccinizer/targets/*.toml`,
`~/.config/…` by default, the invoking user's under sudo). A name already
taken is skipped with a note.

## Changing the core

Run `python3 -m unittest discover -s tests`. If a golden output changes on
purpose (better LUT, new detection rule…), look at the result, then update
`tests/golden.json` with `--update` in the same commit.

User mistakes end with a one-line message, never a traceback: a target raises
`SystemExit("...")`, and `cli.main` turns file errors (`OSError`: missing,
unreadable or unwritable files) into `error: ...`. Set `CATPPUCCINIZER_DEBUG=1`
to get the traceback back.

## Security

What catppuccinizer writes, where, and with which rights. Everything outside the
output folder goes through `core.system` (the `System` object of the steps).

| Where | What | Step | Rights |
|---|---|---|---|
| output folder (`-o`) | the results | build | the user; under sudo, handed back to them |
| `~/.cache/catppuccinizer/` | adi1090x themes (git), GUI uploads | build, GUI | the user |
| `/usr/share/plymouth/themes/<name>/` | Plymouth themes | install | root, files 644, folders 755 |
| `/var/lib/catppuccinizer/<target>.json` | what `restore` needs (system-wide steps) | install, apply | root, 644 |
| `~/.local/state/catppuccinizer/<target>.json` | the same, for the user's steps | install, apply | the user |
| `<ESP>/catppuccin/` | Limine wallpapers | install | root (FAT: no Unix rights) |
| `<ESP>/…/limine.conf` + dated backups | the theme block | apply, restore | root, rights of the existing file |
| `~/.local/share/plasma/look-and-feel/<id>/` | KDE splash packages | install | the user, 644 / 755 |
| `ksplashrc`, Plymouth default theme | through `kwriteconfig6`, `plymouth-set-default-theme -R` | apply, restore | the user / root |
| `/boot/grub/themes/<name>/` | GRUB themes | install | root, 644 / 755 |
| `/etc/default/grub` + dated backups | `GRUB_THEME`, then `grub-mkconfig` | apply, restore | root, rights of the existing file |
| what a user's TOML target names | its install folder, its `KEY="value"` files | install, apply, restore | the user, inside their home only |

How:

- **Names**: a theme or package name that goes into a system path or command is
  checked first (`system.place`, `naming.check_name`: letters, digits, `.`, `_`,
  `+`, `-`, no `/`, no `..`, no leading `-` or `.`), also when it is read back
  from a state file by `restore`.
- **Source themes**: a theme's links are followed only to files inside the theme
  folder (`system.source_file`, `copy_folder`); links out of it (to
  `/etc/shadow`, `~/.ssh`…), links to folders and special files are skipped
  with a note, so a downloaded theme cannot make a sudo run copy a private file
  into a world-readable theme.
- **Copies** to the system get explicit rights (files 644, folders 755, whatever
  the umask), and replace the old copy at once: written under a temporary name
  next to it, then renamed. A link at the destination is replaced, never
  followed; `remove` removes a link, never what it points to.
- **Files** are written atomically (temporary file in the same folder, flushed,
  `os.replace`), keep the rights and owner of the file they replace, and are
  written byte for byte (`system.read_text` keeps line endings and undecodable
  bytes). `write_text(…, backup=True)` first copies the file next to itself as
  `<name>.<date>.bak`; the `KEEP_BACKUPS` (5) most recent are kept.
- **`limine.conf`** is read back before it is written (`limine.check_insert`):
  exactly one block, exactly the theme, and the rest of the file unchanged
  byte for byte once the options it commented out are enabled again; otherwise
  nothing is written. `restore` removes exactly that, so an untouched file
  comes back as the backup of the first `apply`, and later changes (new kernel
  entries) are kept. A wallpaper path of `limine.conf` that leaves the ESP
  (`boot():/../…`) is refused.
- **`KEY="value"` files** (`/etc/default/grub`) change only the line that sets
  the variable (or one line added at the end); a value is quoted and cannot
  hold `"`, `$`, `` ` ``, `\` or a line break, so no shell reads more into it;
  `restore` writes back the line's old value as it was.
- **TOML targets** of the user cannot use sudo and only install or configure
  inside the user's home; their commands, like those of the built-in TOML
  files, come from an allow list ([trust](#trust)).
- **Commands** are lists, never a shell. Run as root, a command is looked up in
  the system folders only (`/usr/sbin`, `/usr/bin`…, not `$PATH`) and run by
  its absolute path. `plymouth/scripts/preview.sh` sets its own `PATH` and
  checks its arguments.
- **Under sudo**, what the run wrote in the user's folders is handed back to
  them (`paths.give_back`): only files root owns, never through a link, never a
  file with other hard links.

The GUI (`catppuccinize gui`) is a local server: it listens on `127.0.0.1`,
never runs as root, and checks the token, the `Host`, the `Origin` and
`Sec-Fetch-Site` of every request; it serves only images, opens only folders,
images and plain text, and a run only gets declared options with values that
cannot pass for options ([details](gui.md#security)).

`tests/test_security.py` covers each point (malicious names, links out of a
theme, atomic writes, backups, commands, `limine.conf` byte for byte, GUI
requests without the token or from another origin, malicious paths and uploads).

## Performances

Work that does not depend on the accent is done once: each image is analysed
once, and an image whose colours do not go to `accent` (LUT methods, or `keys`
without an `accent` colour) is rendered once per flavour, then copied into the
other accents' outputs (Limine, KDE splash, Plymouth image groups). The LUT
cube is cached per flavour and options (`lru_cache` on `build_lut`, 128
cubes of 33³, and `lutgen.build`, 16: bounded, as the GUI's live preview asks
for a new one at each step of a slider).

Measured with `python3 -m cProfile -s cumtime` (one machine, 32 threads, for
orders of magnitude):

| Case | Time |
|---|---|
| `image`, 3840×2160 photo (`lut`) | 3.2 s: analysis 1.2 s (detection 1.0 s), `apply_cube` 1.8 s |
| `image`, 3840×2160 PNG | 3.4 s (was 5.1 s with `optimize=True` on the PNG) |
| `limine`, same photo, 4 accents | 3.3 s (was 12.2 s: analysed and rendered once per accent) |
| `plymouth rings_2` (270 images, 800×600), 2 accents | 3.8 s in parallel; 21.5 s of CPU per accent |
| `lut -f all` (Hald + .cube) | 1.6 s, 0.85 s of it in `build_lut` |
| fixtures (any target) | under 1 s |

The three slowest points, in order:

1. **`keys` recolouring** (`recolor_image`): per pixel, the best source colour
   is found over an `(N, K, 3)` array, then opaque results are quantized to 256
   colours (MEDIANCUT, ~20 % of the time). It dominates Plymouth themes
   (hundreds of frames) and animated splash screens.
2. **`clut.apply_cube`**: trilinear interpolation in numpy, ~0.2 s per
   megapixel; it dominates `lut` / `lutgen` on large wallpapers.
3. **Analysis of a large image** (`detect_group`, `fit_error`, `sharpness`):
   about 1 s and 500 MB for a 4K picture, as `detect_group` works on the full
   resolution in float32.

These are the candidates for a compiled implementation.

### Live preview

The GUI's live preview (`gui/live.py`, `/api/live`) renders in the server's
process, on a copy reduced to 512 pixels, and keeps per file (the 8 most
recent) that copy and the analysis `recolor.plan(memo=…)` stores: a change of
flavour, accent, `-m`, `--keep-lum` or `--smooth` only renders again. Server
time per update (same machine):

| Case | First update (analysis) | Next updates |
|---|---|---|
| 3840×2160 PNG photo, `auto` → `lut` | 1.3 s | 50 ms with a new cube (`build_lut` ~25 ms, `apply_cube` + PNG ~25 ms), 27 ms with a cached one |
| 3440×1440 JPEG line art, `auto` → `keys` | 0.63 s | 2 ms; `lut-accent` 45 ms with a new accent (its cube) |
| `--separation` moved, 4K photo | — | 1.3 s: the analysis itself changes, done again on the full image |

In the page, from a change to the new image: about 200 ms, 120 of them the
debounce. The goal (under 200 ms on the server) is met for everything but
`--separation` and `--method`, which change the analysis; making that fast
means analysing a reduced image (and accepting that it may differ from the
build) or compiling `detect_group`.
