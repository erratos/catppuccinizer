"""When the accent passed with -a has no effect, the command says so (and only then)."""
import contextlib
import io
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.dont_write_bytecode = True

from catppuccinizer.cli import parse  # noqa: E402
from catppuccinizer.core import recolor  # noqa: E402
from catppuccinizer.core.mapping import NO_ACCENT, note_accent_ignored  # noqa: E402


def printed(fn, *args, **kw):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        fn(*args, **kw)
    return out.getvalue()


class AccentNotes(unittest.TestCase):
    def test_accent_given(self):
        self.assertTrue(parse(["image", "x.png", "-a", "peach"]).accent_given)
        self.assertFalse(parse(["image", "x.png"]).accent_given)       # default accent

    def test_reason(self):
        keys_accent = {"colors": {"blue": {"source": "#0000ff", "target": "accent"}}}
        keys_plain = {"colors": {"blue": {"source": "#0000ff", "target": "sky"}}}
        self.assertTrue(recolor.accent_ignored_reason("lut", None).startswith("by the lut method"))
        self.assertIn("lut-accent", recolor.accent_ignored_reason("lutgen", None))
        self.assertIsNone(recolor.accent_ignored_reason("lut-accent", {"dominant": 30}))
        self.assertIn("no dominant colour", recolor.accent_ignored_reason("lut-accent", {"dominant": None}))
        self.assertIsNone(recolor.accent_ignored_reason("keys", keys_accent))
        self.assertEqual(recolor.accent_ignored_reason("keys", keys_plain), NO_ACCENT)

    def test_note_only_when_asked(self):
        asked = parse(["image", "x.png", "-a", "peach"])
        self.assertIn("note: accent ignored by the lut method",
                      printed(note_accent_ignored, asked, "by the lut method"))
        self.assertEqual(printed(note_accent_ignored, parse(["image", "x.png"]), "by the lut method"), "")
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            parse(["lut", "-a", "peach"])              # a LUT has no accent: no -a at all


class LutAccent(unittest.TestCase):
    """lut-accent: the image's dominant hue takes the accent; the rest is the lut table."""

    def setUp(self):
        import tempfile
        import numpy as np
        from PIL import Image
        self.np = np
        self.tmp = Path(tempfile.mkdtemp(prefix="catppuccinizer-test-"))
        y = np.linspace(0, 1, 120)[:, None, None]
        sky = (1 - y) * np.array([250, 120, 40]) + y * np.array([200, 80, 30])      # orange
        Image.fromarray(np.broadcast_to(sky, (120, 160, 3)).astype(np.uint8)).save(self.tmp / "sky.png")
        Image.new("RGB", (64, 64), (128, 128, 128)).save(self.tmp / "gray.png")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def render(self, name, method, accent):
        a = parse(["image", "x.png", "--method", method])
        with contextlib.redirect_stdout(io.StringIO()):
            m, grp = recolor.plan(self.tmp / name, a)
        im = recolor.render(self.tmp / name, m, grp, "mocha", accent, a)
        return self.np.asarray(im.convert("RGB"), float).mean((0, 1)), grp

    def test_dominant_hue(self):
        hue = recolor.dominant_hue(self.tmp / "sky.png")
        self.assertTrue(30 <= hue <= 75, hue)            # orange, in Oklab degrees
        self.assertIsNone(recolor.dominant_hue(self.tmp / "gray.png"))

    def test_the_accent_counts(self):
        mauve, _ = self.render("sky.png", "lut-accent", "mauve")
        green, _ = self.render("sky.png", "lut-accent", "green")
        lut_m, _ = self.render("sky.png", "lut", "mauve")
        lut_g, _ = self.render("sky.png", "lut", "green")
        self.assertTrue(self.np.allclose(lut_m, lut_g))  # lut: the accent changes nothing
        self.assertGreater(green[1] - green[0], 0)       # the orange sky turned green
        self.assertGreater(mauve[2] - mauve[1], 20)      # ... or mauve (blue over green)

    def test_offered_where_images_are(self):
        self.assertIn("lut-accent", recolor.METHOD.choices)
        self.assertNotIn("lut-accent", recolor.method_options(recolor.NO_ACCENT_METHODS)[0].choices)


if __name__ == "__main__":
    unittest.main()
