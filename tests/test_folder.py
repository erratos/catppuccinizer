"""core.folder (a theme folder recoloured by parts) and the "hex" colour syntax of
core.formats (theme files: "#rrggbb" strings)."""
import argparse
import contextlib
import io
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.dont_write_bytecode = True

from catppuccinizer.core import folder, recolor                       # noqa: E402
from catppuccinizer.core.formats import collect_text_colours, recolour_text  # noqa: E402
from catppuccinizer.core.options import defaults                     # noqa: E402

THEME = '''# GRUB theme #abc
title-color: "#ffffff"
desktop-color: "#1e1e2e"
+ boot_menu { item_color = "#cccccc" selected_item_color = "white" text = "white" }
+ label { color = "#3daee980" }
'''

PARTS = [folder.Part("text", "text", ("*.txt",)), folder.Part("animations", "animation"),
         folder.Part("images", "image")]


def args(**kw):
    a = defaults(recolor.method_options(), **{"flavor": ["mocha"], "accent": ["mauve"], "map": [],
                                              "part_accents": {}, **kw})
    return argparse.Namespace(**vars(a))


class HexSyntax(unittest.TestCase):
    def test_collect(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "theme.txt"
            f.write_text(THEME)
            counts = collect_text_colours([f])
        # "#abc" in a comment and the free text "white" are not colours
        self.assertEqual(counts, {"#ffffff": 2, "#1e1e2e": 1, "#cccccc": 1, "#3daee9": 1})

    def test_recolour(self):
        new = recolour_text(THEME, "hex", {"#ffffff": "#cdd6f4", "#3daee9": "#cba6f7",
                                            "#cccccc": "#bac2de", "#1e1e2e": "#1e1e2e"})
        self.assertIn('title-color: "#cdd6f4"', new)
        self.assertIn('selected_item_color = "#cdd6f4" text = "white"', new)
        self.assertIn('color = "#cba6f780"', new)            # alpha kept, last
        self.assertIn("# GRUB theme #abc", new)

    def test_unknown_syntax(self):
        with self.assertRaises(ValueError):
            recolour_text(THEME, "css", {})
        with self.assertRaises(ValueError):
            folder.Part("x", "text", syntax="css")
        with self.assertRaises(ValueError):
            folder.Part("x", "sound")


class Folder(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="catppuccinizer-test-"))
        src = self.tmp / "src"
        (src / "icons").mkdir(parents=True)
        (src / "theme.txt").write_text(THEME)
        (src / "font.pf2").write_bytes(b"PFF2")
        im = Image.new("RGB", (64, 32), (8, 14, 40))
        ImageDraw.Draw(im).ellipse([20, 4, 44, 28], outline=(60, 220, 255), width=3)
        im.save(src / "icons/Select.PNG")
        frames = [Image.new("RGB", (16, 16), (0, 0, 0)) for _ in range(3)]
        for k, fr in enumerate(frames):
            ImageDraw.Draw(fr).rectangle([k * 4, 4, k * 4 + 4, 8], fill=(255, 255, 255))
        frames[0].save(src / "spin.gif", save_all=True, append_images=frames[1:], duration=40)
        (self.tmp / "secret").write_text("x")
        (src / "link.txt").symlink_to(self.tmp / "secret")        # out of the folder
        self.src = src

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def analyse(self, a):
        with contextlib.redirect_stdout(io.StringIO()):
            return folder.analyse(self.src, PARTS, a)

    def test_parts(self):
        fold = self.analyse(args())
        self.assertEqual(fold.texts["text"].files, [self.src / "theme.txt"])   # not the link
        self.assertEqual({f.name: p.part for f, p in fold.pictures.items()},
                         {"Select.PNG": "images", "spin.gif": "animations"})     # any case, any depth
        self.assertEqual(fold.pictures[self.src / "spin.gif"].frames[0], 3)
        self.assertEqual([c["part"] for c in folder.colours(fold)], ["text", "images", "animations"])

    def test_write(self):
        a = args(accent=["mauve", "peach"], map=["#3daee9=accent", "#1e1e2e=base"])
        fold = self.analyse(a)
        using, sets = folder.results(a, fold, PARTS)
        self.assertIn("text", using)
        done, outs = {}, []
        for accents, name in sets:
            dst = self.tmp / name
            shutil.copytree(self.src, dst, symlinks=True)
            with contextlib.redirect_stdout(io.StringIO()):
                folder.write(fold, "mocha", accents, a, lambda f, d=dst: d / f.relative_to(self.src), done)
            outs.append(dst)
        mauve, peach = ((d / "theme.txt").read_text() for d in outs)
        self.assertIn('"#cba6f780"', mauve)
        self.assertIn('"#fab38780"', peach)
        self.assertEqual((outs[0] / "font.pf2").read_bytes(), b"PFF2")
        for d in outs:
            with Image.open(d / "spin.gif") as im:
                self.assertEqual(im.n_frames, 3)
        # a picture without the accent is rendered once, then copied
        if not fold.pictures[self.src / "icons/Select.PNG"].uses_accent:
            self.assertEqual(sum(1 for k in done if k[0].name == "Select.PNG"), 1)

    def test_previews(self):
        a = args()
        fold = self.analyse(a)
        accents = folder.results(a, fold, PARTS)[1][0][0]
        dst = self.tmp / "p.png"
        folder.preview_still(fold, "mocha", accents, a, dst)     # the animation's middle frame
        self.assertTrue(dst.is_file())
        with contextlib.redirect_stdout(io.StringIO()):
            folder.preview_moving(fold, "mocha", accents, self.tmp / "p.webp")
        with Image.open(self.tmp / "p.webp") as im:
            self.assertEqual(im.n_frames, 3)


class Workers(unittest.TestCase):
    """The worker processes fit in the memory available (a folder of large wallpapers)."""

    def workers(self, memory, largest, jobs=None, cpus=32):
        from unittest import mock
        with mock.patch.object(recolor, "available_memory", return_value=memory), \
                mock.patch.object(recolor.os, "sched_getaffinity", return_value=set(range(cpus))):
            return recolor.workers(largest, jobs)

    def test_memory(self):
        gb = 1 << 30
        self.assertEqual(self.workers(40 * gb, 1920 * 1080), 32)          # small images: every processor
        self.assertEqual(self.workers(16 * gb, 3840 * 2160), 12)          # ~1 GB each, 80 % of 16 GB
        self.assertEqual(self.workers(8 * gb, 7680 * 4320), 1)            # ~3.8 GB each
        self.assertEqual(self.workers(1 * gb, 7680 * 4320), 1)            # never none
        self.assertEqual(self.workers(None, 7680 * 4320), 32)             # unknown: the processors
        self.assertEqual(self.workers(40 * gb, 100, jobs=3), 3)           # no more than the jobs

    def test_pixels(self):
        with tempfile.TemporaryDirectory() as tmp:
            Image.new("RGB", (30, 20)).save(Path(tmp) / "a.png")
            (Path(tmp) / "b.svg").write_text("<svg/>")
            self.assertEqual(recolor.pixels(Path(tmp) / "a.png"), 600)
            self.assertEqual(recolor.pixels(Image.new("RGB", (5, 4))), 20)
            self.assertEqual(recolor.pixels(Path(tmp) / "b.svg"), recolor.UNKNOWN_PIXELS)

    def test_frames_one_worker(self):
        """With room for one worker only, frames are recoloured here, in order."""
        from unittest import mock
        frames = [Image.new("RGB", (8, 8), c) for c in ("#000000", "#ff0000", "#0000ff")]
        plan = (np.array([0, 0, 0]), np.array([[255, 0, 0], [0, 0, 255]]),
                np.array([[243, 139, 168], [137, 180, 250]]), np.array([30, 30, 46]))
        with mock.patch.object(recolor, "workers", return_value=1), \
                mock.patch.object(recolor, "ProcessPoolExecutor", side_effect=AssertionError):
            out = list(recolor.recolor_frames(iter(frames), *plan, quantize=False))
        self.assertEqual([im.getpixel((0, 0)) for im in out], [(30, 30, 46), (243, 139, 168), (137, 180, 250)])
        self.assertEqual(list(recolor.recolor_frames(iter([]), *plan)), [])


if __name__ == "__main__":
    unittest.main()
