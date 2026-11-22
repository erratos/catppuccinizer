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
    sources.py        where sources come from: system locations (sections, items), links
    online.py         online sources the GUI browses (Wallhaven, OCS stores, GitHub releases), downloads
    archives.py       archives unpacked safely (no '..', no links, limits)
    settings.py       system settings (--configure): declared, checked, values replaced kept
  targets/
    plymouth/         Plymouth themes (+ preview script)
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
  test_tuning.py      --chroma, --dark-fade, --auto-fit: effect, defaults = the former constants
  test_security.py    names, links, atomic writes, backups, commands, GUI requests
  test_sources.py     system locations, installed themes and wallpapers, links, --list
  test_online.py      online sources, request rules, Wallhaven, OCS, GitHub, safe archives (no network)
  test_settings.py    system settings: checks, values kept and undone, INI files, each target's
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
| `recolor.method_options(methods=None, help=None, needs=None, keys_always=False)` | `--method`, `--separation`, `--auto-fit` (with `auto`), `--keep-lum`, `--smooth`, `--chroma`, `--dark-fade`, `--lutgen-*` (only the given methods; `keys_always`: `--separation` matters whatever `--method`, for a target that also recolours with keys on its own) |
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
| `system.get_ini(text, section, key)` / `set_ini(text, section, key, value)` / `config_text(path)` | an INI file (`plymouthd.conf`): a key of a section read, set or removed (`None`), the rest byte for byte; a configuration file as it is (`""` when missing) |
| `settings.setting(flag, help, check=… / choices=…)` / `integer` / `decimal` / `pattern` / `plain_text` | a [system setting](#system-settings) and the checks of its value (`default` always accepted) |
| `settings.given(args, options)` / `remember(system, state, changes, current)` / `settings_state(target, system)` | the settings given; what to write for them, the values they replace kept in the settings state file (`default` writes them back) |
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

A source comes from one of three places: the **system locations** (what
this computer has), a **folder or file** anywhere (the GUI's file browser, a
path), or **other sources**, web pages to download from. A target describes the
first and the last; with either, `--list` is added to its options to print them.

Optionally, `def locations(self)` returns the system locations, in sections
(the GUI's *System locations…*), and `links` lists the other sources (the GUI's
*Other sources…*, opened in the browser; what is downloaded is then given as a
path):

```python
from ..core.sources import item, link, section, wallpaper_sections

links = [link("SDDM themes", "https://example.org/sddm", "what is found there")]

def locations(self):
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
rights) into the section's `error`, so one section that cannot be read does not
hide the others. `link(name, url, note)` takes `https://` addresses only.
Plymouth: the installed themes, adi1090x and Gnome-look (online);
image: the wallpapers, Wallhaven and the KDE Store wallpapers (online),
Unsplash (`WALLPAPER_LINKS`); Limine: the wallpaper of `limine.conf` + the
wallpapers, the same sites; KDE splash: the user's and the system's splash
screens, the KDE Store (online); GRUB (TOML): its `search` folders, Gnome-look
(online) and Gorgeous GRUB (a link). The GUI
needs nothing else:
its forms come from `options()`
(see [Graphical interface](gui.md#for-target-authors)).

Some other sources can be browsed in the GUI itself (`Target.online`, a list of
`core.online.OnlineSource`): the page searches them through the server and
shows their thumbnails; a click downloads the item into the cache and puts its
path in the source argument, as a file chosen with the browser would be.

```python
from ..core.online import KDE_WALLPAPERS, WALLHAVEN, GithubRelease, Ocs

online = [WALLHAVEN, KDE_WALLPAPERS]                       # image, limine
online = [GithubRelease("adi1090x/plymouth-themes", "adi1090x: Plymouth themes", marker="*.plymouth"),
          Ocs("gnome-look", 108, "Gnome-look: Plymouth themes", marker="*.plymouth")]
```

`Ocs(store, category, title, note, accept="dir", marker=…)` is a category of a
store of the pling network through its OCS API (the one of KDE's *Get New…*):
`store` is `"gnome-look"` or `"kde-store"` (`core.online.STORES`), `category`
the number of its `browse?cat=` page (Gnome-look: GRUB 109, Plymouth 108; KDE
Store: splash screens 488, wallpapers 299). It lists the files of each item
that the target takes (archives for a folder, `.rar` and the like left out;
images for an image), asks for the file's link again when it is chosen (a
token that expires), checks it against the MD5 the store gives, and unpacks an
archive; the theme folders are those holding `marker`, as for `--list`. A TOML
target declares one with [`[[source.online]]`](#format).

`GithubRelease(repo, title, note, marker=…)` is the latest release of a GitHub
repository whose assets are one theme archive each (adi1090x/plymouth-themes):
listed through the API (one request per search, 60 an hour without a key),
most downloaded first, without thumbnails; a chosen theme is downloaded from
the release (checked against the SHA-256 GitHub gives for newer assets),
unpacked and kept under its tag, asking nothing more the next time.

An `OnlineSource` declares its `name`, `title`, `home`, `note`, the `hosts` it
reaches (and `thumb_hosts`; `"*.example.org"` for the site's own subdomains),
what it gives (`accept`: `"image"`, or `"dir"` with its `marker`), and
implements `search(query, page)` (items from `core.online.item()`, with
`choices` for an item of several files) and `fetch(id)` (the local paths,
downloaded once: an image, or every theme folder of an archive, which the GUI
then asks to choose from). Its requests go through `core.online.get()` /
`download()`: `https://` to its hosts only, redirects included, a time and a
size limit, written in full then renamed. What comes as an archive goes
through `OnlineSource.unpacked(url, hosts, dest, filename, md5)`: downloaded,
checked, unpacked by `core.archives.extract()` (no absolute name or `..`, links
and devices left out, files and size limited), the theme folders found
(`core.online.theme_dirs()`), the archive removed. `--list` prints an online
source's page with the links.

### System settings

How the result is shown, set in the system's own files (a boot menu's timeout,
Plymouth's delay), apart from the theme: options made with
`core.settings.setting()` (stage `configure`, `None` when not given), the step
`step("configure")`, and two methods:

```python
from ..core.settings import given, integer, remember, setting, settings_state
from ..core.system import config_text, get_variable, set_variable, unquote

TIMEOUT = setting("--timeout", check=integer(0, 60), metavar="SECONDS",
                  help="seconds before the default entry (not set: 5)")
# in options(): TIMEOUT, step("configure", sudo="run", help="write the settings given")

def configure(self, a, system):            # runs alone: nothing is built
    changes = {"TIMEOUT": v for v in given(a, [TIMEOUT]).values()}   # a value or "default"
    text = config_text(CONF)
    current = {"TIMEOUT": get_variable(text, "TIMEOUT")}
    for key, value in remember(system, settings_state("mine"), changes, current).items():
        text = set_variable(text, key, value, raw=True)
    system.write_text(CONF, text, backup=True)

def settings_now(self, a=None):            # {dest: text or None}, for --configure and the GUI
    return {"timeout": unquote(get_variable(config_text(CONF), "TIMEOUT") or "") or None}
```

A value is checked when the command line is parsed (`integer`, `decimal`,
`pattern`, `plain_text`, or `choices`); `default` undoes a setting: where the
target writes its own block or file, it removes it; where it changes a line of
the system's file, `remember()` keeps the value replaced (first change only) in
`settings_state(<target>)` and gives it back. `--configure` goes alone (no
theme checks, nothing built); without a setting it prints the current values
(`settings_now(args)`) and `Target.tips`. Limine (its own block of
`limine.conf`), Plymouth (`plymouthd.conf`, a systemd drop-in), the KDE splash
(`ksplashrc`) and GRUB (TOML, [`[configure]`](#format)) have some.

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
that order. `restore` and `configure` run alone, without building; `--dry-run`
is added to targets that have steps.

| Step | Effect | Typical rights |
|---|---|---|
| `preview` | before/after images (`--preview`) or an animated WebP (`--preview-animation`) in `<out>/previews/`, first flavour and accent (`options.previewing()`) | user |
| `build` | the result in the output folder (default) | user |
| `install` | copied where the system looks for it, not selected | often root |
| `apply` | selected / configured | often root |
| `test` | shown without rebooting or logging out | depends |
| `restore` | `apply` and `install` undone | as `apply` |
| `configure` | the [system settings](#system-settings) given, apart from the theme | as `apply` |

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
--preview -o -s`; `--list`, `--colours`, `--names`, `--json` when `locations()`
or `links`, `colours()`, `outputs()` are defined) are
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
  folders where themes are looked up by name (`search`, also the system
  locations of `--list` and the GUI), web pages to download themes from
  (`[[source.links]]`, the other sources), a store category the GUI browses
  itself (`[[source.online]]`), a default;
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
  `{…}` run again, the installed results are removed;
- **configure**: [system settings](#system-settings) as variables of
  `KEY="value"` files, each checked (choices, a range, a pattern, or plain
  text), then commands; `default` gives a variable back its previous value.

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
  refused, the install folder and the files of `set` must be in the user's
  home (links followed: `~/x` leading to `/etc` is not the home), and the
  command line refuses to run such a target as root (`Target.root_refused`),
  as `sudo` would make its commands and files root's. A file dropped in that
  folder (a download) should not become a root action; a target that needs
  root is a Python package the user installs, or a TOML file added to
  catppuccinizer.
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
search = ["/boot/grub/themes", "/usr/share/grub/themes"]   # names, system locations (optional)
default = "…"                         # when no source is given (optional)
label = "Theme"                       # the GUI's label (optional)
help = "installed theme name or theme folder"              # (optional)

[[source.online]]                     # browsed in the GUI, any number (optional)
store = "gnome-look"                  # gnome-look | kde-store (core.online.STORES)
category = 109                        # the number of its browse?cat= page
title = "Gnome-look: GRUB themes"     # (optional)
note = "hundreds of themes"           # (optional)

[[source.links]]                      # other sources, any number (optional)
name = "Gorgeous GRUB"
url = "https://github.com/Jacksaur/Gorgeous-GRUB"          # https:// only
note = "a list of themes, each linking to its page"        # (optional)

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

[configure]                           # optional: system settings (--configure)
sudo = true                           # needs root (built-in files only)
help = "…"                            # (optional; explain too)
run = [["grub-mkconfig", "-o", "/boot/grub/grub.cfg"]]     # after a change (allow list, no {…})
tips = ["…"]                          # shown with the settings (optional)

[[configure.settings]]                # any number
name = "timeout"                      # --timeout
file = "/etc/default/grub"            # a KEY="value" file
key = "GRUB_TIMEOUT"
help = "seconds before the default entry boots (not set: 5)"
min = -1                              # checked by min and max,
max = 3600
# choices = ["menu", "hidden"]        # or choices,
# pattern = '\d+x\d+'                # or a pattern (what = its description),
                                      # or nothing: one line of text
label = "Timeout"                     # (optional)
```

A `[[source.online]]` store is reached as described in
[Writing a target](#writing-a-target): the GUI downloads what is chosen into
the cache and unpacks it safely; its theme folders are those holding `marker`.

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
| `~/.cache/catppuccinizer/` | GUI uploads, `downloads/<source>/` (online sources) | GUI | the user (`700`) |
| `/usr/share/plymouth/themes/<name>/` | Plymouth themes | install | root, files 644, folders 755 |
| `/var/lib/catppuccinizer/<target>.json` | what `restore` needs (system-wide steps) | install, apply | root, 644 |
| `~/.local/state/catppuccinizer/<target>.json` | the same, for the user's steps | install, apply | the user |
| `<ESP>/catppuccin/` | Limine wallpapers | install | root (FAT: no Unix rights) |
| `<ESP>/…/limine.conf` + dated backups | the theme block, then `limine-enroll-config` with config enrollment | apply, restore | root, rights of the existing file |
| `~/.local/share/plasma/look-and-feel/<id>/` | KDE splash packages | install | the user, 644 / 755 |
| `ksplashrc`, Plymouth default theme | through `kwriteconfig6`, `plymouth-set-default-theme -R` | apply, restore | the user / root |
| `/boot/grub/themes/<name>/` | GRUB themes | install | root, 644 / 755 |
| `/etc/default/grub` + dated backups | `GRUB_THEME`, then `grub-mkconfig` | apply, restore | root, rights of the existing file |
| `<ESP>/…/limine.conf` + dated backups | the display settings block | configure | root |
| `/etc/plymouth/plymouthd.conf` + dated backups | `ShowDelay`, `DeviceTimeout`, `DeviceScale`, then the initramfs rebuilt | configure | root, rights of the existing file |
| `/etc/systemd/system/plymouth-quit.service.d/catppuccinizer.conf` | `--hold`: a sleep before Plymouth quits, then `systemctl daemon-reload` | configure | root, 644 |
| `/etc/default/grub` + dated backups | `GRUB_TIMEOUT`, `GRUB_GFXMODE`…, then `grub-mkconfig` | configure | root |
| `ksplashrc` | `Engine` (splash on / off), through `kwriteconfig6` | configure | the user |
| `…/catppuccinizer/<target>-settings.json` | the values the settings replaced (for `default`) | configure | as the step |
| what a user's TOML target names | its install folder, its `KEY="value"` files | install, apply, restore | the user, inside their home only (refused as root) |

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
  next to it, then renamed (the old copy put back if the new one cannot take
  its place). A link at the destination is replaced, never
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
  (`boot():/../…`) is refused. With config enrollment on (its checksum in
  Limine's EFI binary), each write is followed by `limine-enroll-config`, and
  nothing is written when that tool is missing: Limine would refuse to boot.
- **System settings** are checked when the command line is parsed (numbers in
  a range, patterns, choices, one line of text), go through the same file
  rules as the steps (backup, atomic write, byte for byte, Limine's block read
  back before it is written), and `default` undoes each one.
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
| `image`, 3840×2160 PNG photo (`auto` → `lut`) | 2.85 s: analysis 0.55 s (was 1.2 s), render 1.75 s (`apply_cube`); 5.1 s with `optimize=True` on the PNG |
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
   about 0.6 s and 500 MB for a 4K picture, as `detect_group` works on the full
   resolution in float32: about ten passes over the pixels of 30 to 90 ms each
   (difference to the background, distance, selections, percentile, the
   400 000-pixel sample), none dominant. The per-pixel maximum over the three
   channels is written as two `np.maximum` (`detect.channel_max`): numpy
   reduces a 3-wide last axis ten times more slowly.

These are the candidates for a compiled implementation.

### Live preview

The GUI's live preview (`gui/live.py`, `/api/live`) renders in the server's
process, on a copy reduced to 512 pixels, and keeps per file (the 8 most
recent) that copy and the analysis `recolor.plan(memo=…)` stores: a change of
flavour, accent, `-m`, `--auto-fit`, `--keep-lum`, `--smooth`, `--chroma` or
`--dark-fade` only renders again. Server time per update (same machine):

| Case | First update (analysis) | Next updates |
|---|---|---|
| 3840×2160 PNG photo, `auto` → `lut` | 0.64 s | 50 ms with a new cube (`build_lut` ~25 ms, `apply_cube` + PNG ~25 ms), 27 ms with a cached one |
| 3440×1440 JPEG line art, `auto` → `keys` | 0.26 s | 2 ms; `lut-accent` 45 ms with a new accent (its cube) |
| `--separation` moved | — | the analysis itself changes, done again on the full image: 0.6 s (4K photo), 0.27 s (3440×1440) |

In the page, from a change to the new image: about 200 ms, 120 of them the
debounce. The goal (under 200 ms on the server) is met for everything but
`--separation` and `--method`, which change the analysis (0.6 s on a 4K
picture, was 1.3 s before `detect_group` was reworked); going further means
analysing a reduced image (and accepting that it may differ from the build)
or compiling `detect_group`.
