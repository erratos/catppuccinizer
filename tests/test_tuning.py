"""Fine-tuning options of the methods: --chroma and --dark-fade (lut), --auto-fit
(auto); their defaults are the constants they replace (the goldens do not move)."""
import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.dont_write_bytecode = True

from catppuccinizer.core import recolor  # noqa: E402
from catppuccinizer.core.clut import apply_cube  # noqa: E402
from catppuccinizer.core.options import defaults  # noqa: E402
from catppuccinizer.core.palette import srgb_to_oklab  # noqa: E402


def opts(**kw):
    return defaults(recolor.method_options(), map=[], **kw)


def chroma_of(colour, **kw):
    """Oklab chroma of one colour after the lut method with these options (Mocha)."""
    out = apply_cube(np.array([[colour]], np.float32), recolor.lut_for("lut", "mocha", opts(**kw)))
    lab = srgb_to_oklab(np.clip(out.reshape(1, 3), 0, 255))
    return float(np.hypot(lab[0, 1], lab[0, 2]))


class Tuning(unittest.TestCase):
    def test_defaults_are_the_former_constants(self):
        a = opts()
        self.assertEqual((a.chroma, a.dark_fade, a.auto_fit),
                         (recolor.CHROMA_REF, recolor.DARK_FADE, recolor.FIT_THRESHOLD))
        self.assertTrue(np.array_equal(recolor.lut_for("lut", "mocha", a),
                                       recolor.build_lut("mocha", a.smooth, a.keep_lum)))

    def test_chroma(self):
        muted = (110, 120, 140)                    # a bluish gray
        self.assertGreater(chroma_of(muted, chroma=0.04), chroma_of(muted) + 0.01)
        self.assertLess(chroma_of(muted, chroma=0.25), chroma_of(muted) - 0.005)

    def test_dark_fade(self):
        dark = (45, 0, 70)                         # a deep purple
        none, default, strong = (chroma_of(dark, dark_fade=f) for f in (0, 0.75, 1.5))
        self.assertGreater(none, default + 0.01)
        self.assertGreater(default, strong + 0.005)
        self.assertTrue(np.isfinite(recolor.lut_for("lut", "mocha", opts(dark_fade=0))).all())

    def test_auto_fit(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "flat.png"
            im = Image.new("RGB", (160, 90), (8, 14, 40))
            ImageDraw.Draw(im).ellipse([20, 10, 140, 80], outline=(60, 220, 255), width=3)
            im.save(path)
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(recolor.plan(path, opts())[0], "keys")
                self.assertEqual(recolor.plan(path, opts(auto_fit=0))[0], "lut")
                self.assertEqual(recolor.plan(path, opts(auto_fit=0, method="keys"))[0], "keys")

    def test_offered_with_their_methods(self):
        dests = lambda methods: {o.dest for o in recolor.method_options(methods)}  # noqa: E731
        self.assertTrue({"auto_fit", "chroma", "dark_fade", "separation"} <= dests(None))
        self.assertEqual(dests(recolor.NO_ACCENT_METHODS) & {"auto_fit", "separation"}, set())
        self.assertIn("chroma", dests(recolor.NO_ACCENT_METHODS))           # the lut target


if __name__ == "__main__":
    unittest.main()
