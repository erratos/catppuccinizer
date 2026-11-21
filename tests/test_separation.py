"""Colour separation of the keys method (--separation): an element close to the
background (a yellow sun on an orange sky, next to far more contrasted white) or
darker than it gets a source colour of its own when the setting is raised, and
the default changes nothing."""
import contextlib
import io
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.dont_write_bytecode = True

from catppuccinizer.cli import main  # noqa: E402
from catppuccinizer.core import detect, recolor  # noqa: E402
from catppuccinizer.core.palette import hex2rgb, rgb  # noqa: E402

SKY, SUN, WHITE, HILL = (240, 120, 30), (250, 210, 60), (255, 255, 255), (90, 30, 10)


def sun(path, dark=False):
    im = Image.new("RGB", (400, 300), SKY)
    d = ImageDraw.Draw(im)
    d.ellipse((60, 60, 160, 160), fill=SUN)
    d.rectangle((220, 200, 380, 230), fill=WHITE)
    if dark:
        d.polygon([(250, 40), (360, 40), (305, 140)], fill=HILL)
    im.save(path)
    return path


def size(path):
    with Image.open(path) as im:
        return im.size


def colours(path, separation):
    return detect.detect_group([path], False, detect.detect_params(separation))["colors"]


def has(cols, colour, tol=12):
    return any(np.abs(hex2rgb(c["source"]) - colour).max() <= tol for c in cols.values())


def cli(*argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
        main([str(a) for a in argv])
    return out.getvalue()


class Separation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="catppuccinizer-test-"))
        cls.sun = sun(cls.tmp / "sun.png")
        cls.dark = sun(cls.tmp / "sun-dark.png", dark=True)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_default_is_the_former_detection(self):
        self.assertEqual(detect.detect_params(), detect.DetectParams())
        self.assertEqual(detect.detect_params(detect.DEFAULT_SEPARATION), detect.DetectParams())
        self.assertFalse(detect.DetectParams().darker)

    def test_settings_move_together(self):
        lo, mid, hi = (detect.detect_params(s) for s in (0, 0.5, 1))
        for k in ("intensity", "floor", "group", "peak", "hue_gap"):
            self.assertGreater(getattr(lo, k), getattr(mid, k), k)
            self.assertGreater(getattr(mid, k), getattr(hi, k), k)
        self.assertLess(lo.max_colors, mid.max_colors)
        self.assertLess(mid.max_colors, hi.max_colors)
        self.assertTrue(hi.darker)

    def test_sun_lost_by_default_found_when_raised(self):
        self.assertFalse(has(colours(self.sun, 0.5), SUN))       # the bug this setting is for
        self.assertTrue(has(colours(self.sun, 0.8), SUN))
        self.assertTrue(has(colours(self.sun, 0.8), WHITE))

    def test_darker_than_the_background(self):
        self.assertFalse(has(colours(self.dark, 0.5), HILL))
        self.assertTrue(has(colours(self.dark, 0.6), HILL))
        self.assertTrue(has(colours(self.dark, 0.8), SUN))

    def test_the_sun_is_rendered(self):
        """Recoloured: at the default the sun is a faint shade of the background;
        raised, it gets its own target."""
        def sun_pixel(separation):
            a = SimpleNamespace(method="keys", map=[], separation=separation, smooth=0.08,
                                keep_lum=0.5)
            with contextlib.redirect_stdout(io.StringIO()):
                m, grp = recolor.plan(self.sun, a)
            im = recolor.render(self.sun, m, grp, "mocha", "mauve", a).convert("RGB")
            return np.asarray(im, float)[110, 110]
        base = rgb("mocha", "base")
        self.assertLess(np.abs(sun_pixel(0.8) - rgb("mocha", "yellow")).max(), 3)
        self.assertGreater(np.abs(sun_pixel(0.8) - base).max(), 3 * np.abs(sun_pixel(0.5) - base).max())

    def test_colours_lists_the_new_ones(self):
        default = json.loads(cli("image", self.sun, "--method", "keys", "--colours", "--json"))
        raised = json.loads(cli("image", self.sun, "--method", "keys", "--separation", "0.8",
                                "--colours", "--json"))
        self.assertEqual(len(default[0]["colours"]), 1)
        self.assertIn("yellow", [c["name"] for c in raised[0]["colours"]])

    def test_preview_has_a_separation_panel(self):
        out = self.tmp / "out"
        cli("image", self.sun, "--method", "keys", "--separation", "0.8", "--preview", "-a", "mauve",
            "-o", out)
        with Image.open(next((out / "previews").glob("*.png"))) as im:
            sheet = im.convert("RGB")
        w = size(self.sun)[0]
        self.assertEqual(sheet.width, 3 * w + 2 * recolor.SHEET_GAP)
        gap = np.asarray(sheet)[:, w:w + recolor.SHEET_GAP]
        self.assertTrue((gap == recolor.SHEET_GAP_COLOUR).all())    # what the GUI's picker finds
        grp = detect.detect_group([self.sun], False, detect.detect_params(0.8))
        im, legend = recolor.separation_image(self.sun, grp)
        self.assertEqual([n for n, _ in legend], list(grp["colors"]))
        self.assertEqual(im.size, size(self.sun))
        # a LUT image has no source colours: before | after only
        out2 = self.tmp / "out2"
        cli("image", self.sun, "--method", "lut", "--preview", "-o", out2)
        self.assertEqual(size(next((out2 / "previews").glob("*.png")))[0], 2 * w + recolor.SHEET_GAP)

    def test_shown_with_keys_only(self):
        from catppuccinizer.core.target import discover
        targets = discover()
        sep = {n: next((o for o in t.all_options() if o.dest == "separation"), None)
               for n, t in targets.items()}
        self.assertIsNone(sep["lut"])
        self.assertEqual(sep["image"].when, {"method": ["auto", "keys"]})
        self.assertIsNone(sep["plymouth"].when)          # always keys
        self.assertIsNone(sep["ksplash"].when)           # its animations always use keys


if __name__ == "__main__":
    unittest.main()
