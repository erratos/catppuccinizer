"""Output names before building (Target.outputs, --names, the GUI's preview): for
every target, the list is exactly what the build then writes, and what already
exists is marked."""
import contextlib
import io
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
sys.dont_write_bytecode = True

from catppuccinizer.cli import main  # noqa: E402
from catppuccinizer.core.naming import format_planned, planned  # noqa: E402
from catppuccinizer.core.target import discover  # noqa: E402
from test_regression import FIXTURES, make_images, make_splash  # noqa: E402


def cli(*argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
        main([str(a) for a in argv])
    return out.getvalue()


def written(out):
    """Every file and folder under out, as paths."""
    return {str(p) for p in out.rglob("*")} if out.exists() else set()


class Names(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="catppuccinizer-test-"))
        make_images(cls.tmp / "img")
        make_splash(cls.tmp / "splash")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def check(self, *argv, contents=True):
        """--names lists what the build writes: every entry is written, and every file or
        folder written is listed (contents=False: the files inside a listed folder,
        a theme or a package, are not listed one by one)."""
        out = self.tmp / f"out-{self.id().rsplit('.', 1)[-1]}-{abs(hash(argv))}"
        names = json.loads(cli(*argv, "-o", out, "--names", "--json"))
        self.assertFalse(out.exists(), "--names wrote something")
        self.assertTrue(names)
        self.assertFalse(any(it["exists"] for it in names))
        cli(*argv, "-o", out)
        listed = {it["path"] for it in names}
        self.assertEqual(len(listed), len(names), "an entry is listed twice")
        made = written(out) - {str(out / "previews")}       # the folder of the previews
        if not contents:
            folders = [x for x in listed if Path(x).is_dir()]
            made = {p for p in made if not any(p.startswith(x + "/") for x in folders)}
        self.assertEqual(listed - written(out), set(), "listed, not written")
        self.assertEqual(made - listed, set(), "written, not listed")
        for it in names:
            self.assertEqual(it["folder"], Path(it["path"]).is_dir(), it["path"])
        again = json.loads(cli(*argv, "-o", out, "--names", "--json"))
        self.assertTrue(all(it["exists"] for it in again))          # now replaced
        return names

    def test_image(self):
        names = self.check("image", self.tmp / "img", "-f", "latte", "mocha", "-a", "mauve", "peach")
        got = {Path(it["path"]).name for it in names}
        for name in ("catppuccin-mocha-photo.jpg",        # a LUT keeps the JPEG
                     "catppuccin-mocha-flat.png",         # no accent used: one per flavour
                     "catppuccin-latte-mark-mauve.svg",   # SVG stays SVG, its accent is used
                     "catppuccin-mocha-speck-peach.png"):
            self.assertIn(name, got)
        self.check("image", self.tmp / "img/flat.png", "--preview", "-s", "x")

    def test_plymouth(self):
        names = self.check("plymouth", FIXTURES / "hexa_mini", FIXTURES / "glow_mini",
                           "-a", "mauve", "teal", contents=False)
        self.assertTrue(any(it["path"].endswith("-status") for it in names))
        self.check("plymouth", FIXTURES / "glow_mini", "-a", "mauve", "--preview")

    def test_limine(self):
        self.check("limine", "-a", "mauve", "peach", "--wallpaper", self.tmp / "img/photo.jpg",
                   "--esp", self.tmp)
        self.check("limine", "-a", "mauve", "--wallpaper", self.tmp / "img/flat.png", "--preview",
                   "--esp", self.tmp)

    def test_ksplash(self):
        names = self.check("ksplash", self.tmp / "splash", "-f", "latte", "mocha", contents=False)
        self.assertTrue(all(it["folder"] for it in names))

    def test_lut(self):
        self.check("lut", "-f", "mocha", "--format", "hald", "cube", "--hald-level", "4",
                   "--cube-size", "9")

    def test_every_target_offers_names(self):
        for name, t in discover().items():
            with self.subTest(target=name):
                self.assertTrue(t.has_outputs)
                self.assertIn("--names", [f for o in t.all_options() for f in o.flags])

    def test_format_and_flags(self):
        f = self.tmp / "exists.png"
        f.write_bytes(b"x")
        text = format_planned([planned(self.tmp / "d", folder=True), planned(f)])
        self.assertEqual(text, f"  {self.tmp / 'd'}/\n  {f}  (exists: replaced)\n"
                               "1 of 2 already exist and would be replaced.")
        self.assertEqual(format_planned([]), "Nothing would be written.")
        with self.assertRaises(SystemExit):
            cli("lut", "--json")
        with self.assertRaises(SystemExit):
            cli("image", f, "--colours", "--names")


if __name__ == "__main__":
    unittest.main()
