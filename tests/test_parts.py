"""Parts of a result (core.parts): -a PART=ACCENT gives one part its own accent;
the output name carries the main part's accent, then the parts that differ."""
import contextlib
import io
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
sys.dont_write_bytecode = True

from catppuccinizer.cli import main, parse  # noqa: E402
from catppuccinizer.core import parts  # noqa: E402
from test_regression import FIXTURES, make_images, make_splash  # noqa: E402


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


class Core(unittest.TestCase):
    def test_split(self):
        self.assertEqual(parts.split_accents(["mauve", "menu=peach"]), (["mauve"], {"menu": "peach"}))
        for bad in (["menu=nope"], ["Menu?=peach"], ["menu=peach", "menu=red"]):
            with self.assertRaises(SystemExit):
                parts.split_accents(bad)

    def test_sets(self):
        a = SimpleNamespace(accent=["mauve", "peach"], part_accents={"wallpaper": "green"})
        self.assertEqual(parts.accent_sets(a, []), [({}, None)])
        self.assertEqual([n for _, n in parts.accent_sets(a, ["menu", "wallpaper"])],
                         ["mauve-wallpaper-green", "peach-wallpaper-green"])
        a.part_accents = {"menu": "red", "wallpaper": "red"}
        self.assertEqual(parts.accent_sets(a, ["menu", "wallpaper"]),
                         [({"menu": "red", "wallpaper": "red"}, "red")])      # one result
        a.part_accents = {"wallpaper": "mauve"}
        self.assertEqual([n for _, n in parts.accent_sets(a, ["menu", "wallpaper"])],
                         ["mauve", "peach-wallpaper-mauve"])                  # same: not repeated

    def test_parsed(self):
        a = parse(["limine", "-a", "mauve", "wallpaper=peach"])
        self.assertEqual((a.accent, a.part_accents), (["mauve"], {"wallpaper": "peach"}))
        a = parse(["limine", "-a", "wallpaper=peach"])
        self.assertEqual(len(a.accent), 14)             # the other parts: the default (all)
        self.assertIn("no part named 'logo'", cli("limine", "-a", "logo=peach", "--names"))


class Targets(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="catppuccinizer-test-"))
        make_images(cls.tmp / "img")
        make_splash(cls.tmp / "splash")
        (cls.tmp / "esp").mkdir()
        (cls.tmp / "esp/limine.conf").write_text("timeout: 3\n\n/Linux\n    protocol: linux\n")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_limine(self):
        esp, out = self.tmp / "esp", self.tmp / "out"
        flat = self.tmp / "img/flat.png"
        got = names("limine", "--esp", esp, "-o", out, "-a", "mauve", "peach", "wallpaper=green",
                    "--wallpaper", flat, "--method", "keys", "-m", "pink=accent")
        self.assertIn("catppuccin-mocha-limine-mauve-wallpaper-green", got)
        self.assertIn("catppuccin-mocha-wallpaper-green.png", got)
        self.assertNotIn("catppuccin-mocha-wallpaper-mauve.png", got)
        # a wallpaper that does not use the accent: no wallpaper part in the names
        got = names("limine", "--esp", esp, "-o", out, "-a", "mauve", "wallpaper=green",
                    "--wallpaper", self.tmp / "img/photo.jpg", "--method", "lut")
        self.assertIn("catppuccin-mocha-limine-mauve", got)
        # built: the menu takes its accent, the wallpaper its own
        cli("limine", "--esp", esp, "-o", out, "-a", "menu=peach", "wallpaper=green",
            "--wallpaper", flat, "--method", "keys", "-m", "pink=accent")
        conf = (out / "catppuccin-mocha-limine-peach-wallpaper-green/limine-theme.conf").read_text()
        self.assertIn("interface_branding_colour: fab387", conf)                 # peach
        self.assertIn("catppuccin-mocha-wallpaper-green.png", conf)

    def test_plymouth(self):
        theme = FIXTURES / "glow_mini"
        got = names("plymouth", theme, "-o", self.tmp / "out", "-a", "mauve", "throbber=green")
        self.assertEqual(got, ["catppuccin-mocha-glow-mini-mauve-throbber-green"])
        got = names("plymouth", FIXTURES / "hexa_mini", "-o", self.tmp / "out", "-a", "bar=red")
        self.assertEqual(got[0], "catppuccin-mocha-hexa-mini-red")     # only the bar uses one
        report = json.loads(cli("plymouth", theme, "--colours", "--json"))
        self.assertEqual([it["part"] for it in report], ["progress", "throbber", "ui", "bar"])
        self.assertIn("no part named 'nope'", cli("plymouth", theme, "-a", "nope=red", "--names"))

    def test_image(self):
        img = self.tmp / "img"
        got = names("image", img / "logo.png", img / "speck.png", "-o", self.tmp / "out",
                    "-a", "mauve", "peach", "speck=green")
        self.assertEqual(sorted(got), ["catppuccin-mocha-logo.png",           # no accent in it
                                       "catppuccin-mocha-speck-green.png"])

    def test_ksplash(self):
        report = json.loads(cli("ksplash", self.tmp / "splash", "--colours", "--json"))
        self.assertEqual({it["part"] for it in report}, {"vector", "images", "animations"})
        got = names("ksplash", self.tmp / "splash", "-o", self.tmp / "out", "-a", "mauve",
                    "vector=peach")
        self.assertEqual(len(got), 1)
        self.assertTrue(got[0].startswith("catppuccin-mocha-test-splash-peach"), got)


if __name__ == "__main__":
    unittest.main()
