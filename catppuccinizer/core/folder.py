"""A theme folder recoloured as a whole: its text files (QML, SVG, theme files),
images and animations, each file in a part of the result (core.parts: -a PART=ACCENT).

    PARTS = [Part("text", "text", ("*.qml", "*.svg")), Part("animations", "animation"),
             Part("images", "image")]
    fold = analyse(root, PARTS, a)              # the colours of every file, after -m
    using, sets = results(a, fold, PARTS)       # the parts that use the accent
    done = {}
    for flv in a.flavor:
        for accents, name in sets:
            copy_folder(root, dst)              # what no part takes is copied as it is
            write(fold, flv, accents, a, lambda f: dst / f.relative_to(root), done)

A part's globs are matched against the path relative to the folder, without
case, '*' going across folders ('*.png': every PNG, 'images/*': everything under
images/). A file goes to the first part it matches whose kind fits it: a text
part takes any file, an image part still images (PNG, JPEG, WebP, BMP), an
animation part GIFs and animated WebPs. Links out of the folder are left out
(core.system.source_file), as copy_folder() leaves them out of the copy.
"""
import fnmatch
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image

from . import recolor
from .detect import detect_group, detect_params
from .formats import (RASTER, SYNTAXES, anim_frames, anim_info, anim_sample, is_animated,
                      recolour_text_file, save_animation)
from .mapping import (apply_maps, background_of, colour_report, print_colours, text_colours,
                      text_lookup, uses_accent)
from .parts import accent_sets
from .system import source_file

KINDS = ("text", "image", "animation")


@dataclass(frozen=True)
class Part:
    """What a part of the result takes from the folder."""
    name: str                  # -a NAME=ACCENT, -m NAME.COLOUR for a text part
    kind: str                  # KINDS
    files: tuple = ("*",)      # globs, relative to the folder
    label: str = None          # how --colours names a text part (default: its name)
    syntax: str = None         # text: how colours are written (core.formats.SYNTAXES);
                               # None: from each file's extension

    def __post_init__(self):
        if self.kind not in KINDS:
            raise ValueError(f"part {self.name}: unknown kind {self.kind!r}")
        if self.syntax is not None and self.syntax not in SYNTAXES:
            raise ValueError(f"part {self.name}: unknown colour syntax {self.syntax!r}")

    def takes(self, rel, f):
        """Whether this part takes the file f (rel: its path in the folder)."""
        if not any(fnmatch.fnmatchcase(rel.lower(), g.lower()) for g in self.files):
            return False
        if self.kind == "text":
            return True
        if f.suffix.lower() not in RASTER | {".gif"}:
            return False
        return is_animated(f) == (self.kind == "animation")


@dataclass
class Texts:
    """The text files of a part and their colours (after -m)."""
    label: str
    syntax: str
    files: list
    colors: dict


@dataclass
class Picture:
    """An image or an animation of the folder, analysed."""
    part: str
    method: str                # core.recolor's method, or "anim" (keys, frame by frame)
    grp: dict = None
    frames: tuple = None       # animation: (count, durations, loop)
    listed: bool = True        # False: its colours are another picture's (--colours skips it)

    @property
    def uses_accent(self):
        return not recolor.accent_ignored_reason("keys" if self.method == "anim" else self.method,
                                                 self.grp)

    def accent(self, accents):
        """Its accent among a result's {part: accent} (None when it uses none)."""
        return accents.get(self.part) if self.uses_accent else None


@dataclass
class Folder:
    root: Path
    texts: dict = field(default_factory=dict)       # part name -> Texts
    pictures: dict = field(default_factory=dict)    # path -> Picture, in folder order

    def animations(self):
        """The animations, longest first."""
        anims = [f for f, p in self.pictures.items() if p.method == "anim"]
        return sorted(anims, key=lambda f: -self.pictures[f].frames[0])


# ------------------------------------------------------------------ analysis
def analyse(root, parts, a, verbose=True):
    """The colours of every file of root that a part takes, after -m (printed when
    verbose)."""
    root = Path(root)
    fold = Folder(root)
    texts, pictures = {p.name: [] for p in parts if p.kind == "text"}, []
    for f in sorted(root.rglob("*")):
        if not source_file(f, root):
            continue                          # folders, links out of root, special files
        rel = f.relative_to(root).as_posix()
        part = next((p for p in parts if p.takes(rel, f)), None)
        if part is None:
            continue
        if part.kind == "text":
            texts[part.name].append(f)
        else:
            pictures.append((f, part.name))
    for p in parts:
        if p.kind == "text":
            colors = text_colours(texts[p.name], a.map, strict=False, group=p.name, syntax=p.syntax)
            fold.texts[p.name] = Texts(p.label or p.name, p.syntax, texts[p.name], colors)
            if verbose and colors:
                print(f"  {p.label or p.name} colours")
                print_colours(colors)
    for f, part in pictures:
        fold.pictures[f] = picture(f, part, a, f.relative_to(root), verbose)
    return fold


def picture(f, part, a, name=None, verbose=True):
    """Analyse one image or animation of a part (name: how to print it)."""
    if is_animated(f):
        n, durations, loop = anim_info(f)
        with tempfile.TemporaryDirectory(prefix="catppuccinize-") as tmp:
            grp = detect_group(anim_sample(f, n, Path(tmp)), is_ui=False,
                               params=detect_params(a.separation))
        apply_maps({"groups": {"image": grp}}, a.map, strict=False)
        pic, what = Picture(part, "anim", grp, (n, durations, loop)), f"{n} frames"
    else:
        a.strict_map = False                  # a name of -m may be in only some files
        method, grp = recolor.plan(f, a, verbose=False)
        pic, what = Picture(part, method, grp), method
    if verbose:
        print(f"  {name or f.name}: {what}")
        if pic.grp is not None and pic.method not in recolor.LUT_METHODS:
            print_colours(pic.grp["colors"], show_share=False)
    return pic


def results(a, fold, parts):
    """(the parts that use the accent, in parts' order; core.parts.accent_sets)."""
    used = {name for name, t in fold.texts.items() if uses_accent(t.colors)}
    used |= {p.part for p in fold.pictures.values() if p.uses_accent}
    using = [p.name for p in parts if p.name in used]
    return using, accent_sets(a, using)


def colours(fold, name=None):
    """--colours: each text part, then each picture (name(path): how to call it)."""
    name = name or (lambda f: f.relative_to(fold.root))
    out = [colour_report(t.label, "text", t.colors, part=part)
           for part, t in fold.texts.items() if t.colors]
    for f, p in fold.pictures.items():
        if not p.listed:
            continue
        if p.method == "anim":
            out.append(colour_report(name(f), "keys", p.grp["colors"], background=background_of(p.grp),
                                     note=f"animation, {p.frames[0]} frames", part=p.part))
        else:
            out.append(recolor.colour_report(name(f), p.method, p.grp, part=p.part))
    return out


# ------------------------------------------------------------------- writing
def write(fold, flavor, accents, a, out_of, done):
    """Recolour one result: the copied text files in place, the pictures over their
    copies. out_of(path): where a file of the folder is in the result. done: {(path,
    flavour, accent): output} across the results of a build: a picture that does not
    use the accent is rendered once per flavour and copied into the other results.
    Still images are rendered in parallel (core.recolor.run_jobs), animations frame
    by frame."""
    for part, t in fold.texts.items():
        lookup = text_lookup(t.colors, flavor, accents.get(part))
        for f in t.files:
            recolour_text_file(out_of(f), lookup, t.syntax)
    jobs = []
    for src, p in fold.pictures.items():
        out, acc = out_of(src), p.accent(accents)
        key = (src, flavor, acc)
        if key in done:
            shutil.copyfile(done[key], out)
            continue
        done[key] = out
        if p.method == "anim":
            n, durations, loop = p.frames
            if n > 100:
                print(f"  recolouring {n} frames of {src.name}…", flush=True)
            frames = recolor.recolor_frames(anim_frames(src), *recolor.keys_plan(p.grp, flavor, acc),
                                            quantize=out.suffix.lower() == ".gif", parallel=n > 48)
            save_animation(frames, n, out, durations, loop)
        else:
            jobs.append((src, out, p.method, p.grp, flavor, acc, a))
    recolor.run_jobs(jobs)


# ------------------------------------------------------------------ previews
def preview_still(fold, flavor, accents, a, dst, prefer=None):
    """--preview: before | after of one picture: prefer (a path of fold.pictures), else
    the middle frame of the longest animation, else the largest still image."""
    stills = [f for f, p in fold.pictures.items() if p.method != "anim"]
    anims = fold.animations()
    if prefer is None and not anims:
        if not stills:
            raise SystemExit("--preview: no image to show")
        prefer = max(stills, key=lambda f: Image.open(f).size[0] * Image.open(f).size[1])
    dst.parent.mkdir(parents=True, exist_ok=True)
    if prefer is not None:
        p = fold.pictures[prefer]
        im = recolor.render(prefer, p.method, p.grp, flavor, p.accent(accents), a)
        recolor.side_by_side(prefer, im, dst, p.grp if p.method == "keys" else None)
        return
    src = anims[0]
    p = fold.pictures[src]
    frame = next(anim_frames(src, {p.frames[0] // 2}))
    im = recolor.recolor_image(frame, *recolor.keys_plan(p.grp, flavor, p.accent(accents)),
                               quantize=False)
    recolor.side_by_side(frame, im, dst, p.grp)


def preview_moving(fold, flavor, accents, dst):
    """--preview-animation: the longest animation, before | after, as an animated WebP."""
    anims = fold.animations()
    if not anims:
        raise SystemExit("--preview-animation: no animated GIF or WebP")
    src = anims[0]
    p = fold.pictures[src]
    n, durations, _ = p.frames
    dst.parent.mkdir(parents=True, exist_ok=True)
    after = recolor.recolor_frames(anim_frames(src), *recolor.keys_plan(p.grp, flavor, p.accent(accents)),
                                   quantize=False, parallel=n > 48)
    pairs = ((recolor.on_black(b), recolor.on_black(r)) for b, r in zip(anim_frames(src), after))
    print(f"  recolouring {n} frames of {src.name}…", flush=True)
    recolor.preview_animation(pairs, n, dst, durations)
