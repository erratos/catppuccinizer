"""Previews: --preview (one image) and --preview-animation (an animated WebP), for the
first flavour and accent only, into <out>/previews/; no system step runs."""
import contextlib
import io
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
sys.dont_write_bytecode = True

from catppuccinizer.cli import main, parse  # noqa: E402
from test_regression import FIXTURES, make_splash  # noqa: E402


def cli(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            main([str(a) for a in argv])
        except SystemExit as e:
            return out.getvalue() + err.getvalue() + str(e.code or "")
    return out.getvalue()


def names(*argv):
    return [Path(e["path"]).name for e in json.loads(cli(*argv, "--names", "--json"))]


class Previews(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="catppuccinizer-test-"))
        make_splash(cls.tmp / "splash")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_first_flavour_and_accent(self):
        a = parse(["plymouth", str(FIXTURES / "glow_mini"), "-f", "all", "-a", "peach", "blue",
                   "--preview"])
        self.assertEqual((a.flavor, a.accent, a.preview_of), (["latte"], ["peach"], ("latte", "peach")))
        a = parse(["plymouth", str(FIXTURES / "glow_mini"), "-f", "all"])
        self.assertEqual(len(a.flavor), 4)                       # not a preview: all of them
        self.assertIn("use either --preview-animation or --preview",
                      cli("plymouth", FIXTURES / "glow_mini", "--preview", "--preview-animation"))

    def test_plymouth(self):
        out = self.tmp / "ply"
        theme = FIXTURES / "glow_mini"
        self.assertEqual(names("plymouth", theme, "-o", out, "-a", "mauve", "red", "--preview-animation"),
                         ["catppuccin-mocha-glow-mini-mauve.webp"])
        log = cli("plymouth", theme, "-o", out, "-a", "mauve", "red", "--preview-animation")
        self.assertIn("the first flavour and accent only (mocha, mauve)", log)
        with Image.open(out / "previews/catppuccin-mocha-glow-mini-mauve.webp") as im:
            self.assertGreater(im.n_frames, 1)                  # before | after, side by side
        self.assertEqual(sorted(p.name for p in out.iterdir()), ["previews"])    # nothing built

    def test_ksplash(self):
        out = self.tmp / "ks"
        cli("ksplash", self.tmp / "splash", "-o", out, "-f", "latte", "frappe", "--preview")
        cli("ksplash", self.tmp / "splash", "-o", out, "--preview-animation")
        self.assertEqual(sorted(p.name for p in (out / "previews").iterdir()),
                         ["catppuccin-latte-test-splash-rosewater.png",
                          "catppuccin-mocha-test-splash-rosewater.webp"])
        with Image.open(out / "previews/catppuccin-mocha-test-splash-rosewater.webp") as im:
            self.assertEqual(im.n_frames, 4)
        (self.tmp / "still/contents/splash").mkdir(parents=True)          # QML only
        (self.tmp / "still/contents/splash/Splash.qml").write_text("Rectangle {}\n")
        self.assertIn("no animated GIF or WebP", cli("ksplash", self.tmp / "still", "--preview-animation"))
        self.assertIn("no image to show", cli("ksplash", self.tmp / "still", "--preview"))


if __name__ == "__main__":
    unittest.main()
