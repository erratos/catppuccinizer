"""Ready-made sources (core.sources, Target.sources): sections of items for the
GUI's catalogue and --list, with what is installed on the system."""
import contextlib
import io
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
sys.dont_write_bytecode = True

from catppuccinizer.cli import main  # noqa: E402
from catppuccinizer.core import sources  # noqa: E402
from catppuccinizer.core.target import discover  # noqa: E402
from catppuccinizer.targets import ksplash, limine  # noqa: E402
from catppuccinizer.targets.plymouth import target as plymouth  # noqa: E402
from test_regression import FIXTURES, LIMINE_CONF, make_splash  # noqa: E402

ITEM_KEYS = {"value", "label", "note", "current", "thumb"}


def png(path, size=(4, 4)):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, (30, 30, 46)).save(path)


class Tmp(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="catppuccinizer-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)


class Sections(unittest.TestCase):
    def test_section_keeps_errors(self):
        def fails():
            raise SystemExit("cannot read /boot")
        self.assertEqual(sources.section("A", fails), {"section": "A", "items": [], "error": "cannot read /boot"})
        self.assertEqual(sources.section("B", lambda: iter([sources.item("x")]))["items"][0]["value"], "x")

    def test_format(self):
        text = sources.format_sources([
            {"section": "Installed", "items": [sources.item("/t/a", "A", "two-step", current=True),
                                               sources.item("b")]},
            {"section": "Empty", "items": []},
            {"section": "Catalogue", "items": [], "error": "no network"}])
        self.assertEqual(text, "Installed\n  * /t/a  A  (two-step)\n    b\n\nCatalogue\n  (no network)")
        self.assertEqual(sources.format_sources([]), "Nothing found.")

    def test_every_target(self):
        """Every target that offers sources gives sections of well-formed items."""
        for name, t in discover().items():
            if not t.has_sources:
                continue
            with self.subTest(target=name), contextlib.redirect_stdout(io.StringIO()), \
                    mock.patch.object(plymouth, "upstream_themes", return_value={"glow": "pack_1/glow"}):
                secs = t.sources()
                self.assertIsInstance(secs, list)
                for sec in secs:
                    self.assertTrue(sec["section"])
                    for it in sec["items"]:
                        self.assertEqual(set(it), ITEM_KEYS)
                self.assertIn("--list", [f for o in t.all_options() for f in o.flags])


class Wallpapers(Tmp):
    def test_files_and_kde_packages(self):
        png(self.tmp / "a.png")
        png(self.tmp / "set/b.jpg")
        png(self.tmp / ".hidden/c.png")
        png(self.tmp / "a/b/c/d/too-deep.png")       # 4 folders down
        (self.tmp / "notes.txt").write_text("x")
        pkg = self.tmp / "Pack/Monterey"
        png(pkg / "contents/images/1920x1080.png")
        png(pkg / "contents/images/3840x2160.png")
        png(pkg / "contents/screenshot.png")
        (pkg / "metadata.desktop").write_text("[Desktop Entry]\nName=Monterey Day\n")
        items = {Path(i["value"]).relative_to(self.tmp).as_posix(): i for i in sources.wallpapers(self.tmp)}
        self.assertEqual(sorted(items), ["Pack/Monterey/contents/images/3840x2160.png", "a.png", "set/b.jpg"])
        mon = items["Pack/Monterey/contents/images/3840x2160.png"]
        self.assertEqual((mon["label"], mon["note"]), ("Monterey Day", "Pack · KDE package"))
        self.assertEqual(mon["thumb"], str(pkg / "contents/screenshot.png"))
        self.assertEqual((items["set/b.jpg"]["label"], items["set/b.jpg"]["note"]), ("b", "set"))

    def test_sections(self):
        png(self.tmp / "mine/w.png")
        dirs = [("System wallpapers", self.tmp / "none"), ("Your wallpapers", self.tmp / "mine")]
        with mock.patch.object(sources, "wallpaper_dirs", return_value=dirs):
            secs = sources.wallpaper_sections()
            self.assertEqual([s["section"] for s in secs], [f"Your wallpapers ({self.tmp / 'mine'})"])
            out = io.StringIO()
            with contextlib.redirect_stdout(out), self.assertRaises(SystemExit) as e:
                main(["image", "--list"])                # no image needed to list them
            self.assertEqual(e.exception.code, 0)
        self.assertIn(str(self.tmp / "mine/w.png"), out.getvalue())


class Installed(Tmp):
    def test_plymouth(self):
        for name in ("glow_mini", "hexa_mini"):
            shutil.copytree(FIXTURES / name, self.tmp / name)
        (self.tmp / "text").mkdir()                          # no image: nothing to recolour
        (self.tmp / "text/text.plymouth").write_text("[Plymouth Theme]\nName=Text\nModuleName=text\n")
        with mock.patch.object(plymouth, "INSTALL_DIR", str(self.tmp)), \
                mock.patch.object(plymouth, "default_theme", return_value="hexa_mini"):
            items = list(plymouth.installed_themes())
        self.assertEqual([Path(i["value"]).name for i in items], ["glow_mini", "hexa_mini"])
        self.assertEqual([i["current"] for i in items], [False, True])
        self.assertEqual(items[0]["thumb"], str(self.tmp / "glow_mini"))

    def test_plymouth_theme_in_use(self):
        """No theme given: the theme in use; installed themes by name; a catppuccinizer
        result in use: the theme it replaced, or a clear message."""
        import argparse
        import json
        shutil.copytree(FIXTURES / "glow_mini", self.tmp / "glow_mini")
        os.environ["CATPPUCCINIZER_STATE"] = str(self.tmp / "state")
        self.addCleanup(os.environ.pop, "CATPPUCCINIZER_STATE", None)
        a = argparse.Namespace(themes=[])
        with mock.patch.object(plymouth, "INSTALL_DIR", str(self.tmp)), \
                mock.patch.object(plymouth, "default_theme", return_value="glow_mini"), \
                contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(plymouth.themes_of(a), ["glow_mini"])
            self.assertEqual(plymouth.find_theme("glow_mini"), self.tmp / "glow_mini")
        self.assertIn("Theme in use: glow_mini", out.getvalue())
        self.assertEqual(plymouth.themes_of(argparse.Namespace(themes=["x"])), ["x"])
        (self.tmp / "state").mkdir()
        with mock.patch.object(plymouth, "default_theme", return_value="catppuccin-mocha-glow"):
            with self.assertRaises(SystemExit) as e:
                plymouth.themes_of(argparse.Namespace(themes=[]))
            self.assertIn("catppuccinizer result", str(e.exception))
            (self.tmp / "state/plymouth.json").write_text(json.dumps(
                {"installed": ["catppuccin-mocha-glow"], "previous": "bgrt"}))
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(plymouth.themes_of(argparse.Namespace(themes=[])), ["bgrt"])

    def test_ksplash(self):
        make_splash(self.tmp / "test.splash")
        (self.tmp / "other").mkdir()                         # not a splash screen
        items = list(ksplash.installed(self.tmp, "test.splash"))
        self.assertEqual([(i["value"], i["label"], i["current"]) for i in items],
                         [("test.splash", "Test Splash", True)])
        self.assertEqual(items[0]["thumb"], str(self.tmp / "test.splash/contents/previews/splash.png"))

    def test_limine(self):
        esp = self.tmp / "esp"
        png(esp / "limine-splash.png")
        (esp / "limine.conf").write_text(LIMINE_CONF)
        with mock.patch.object(limine, "default_esp", return_value=esp):
            items = list(limine.current_wallpapers())
            self.assertEqual([(i["value"], i["current"]) for i in items],
                             [(str(esp / "limine-splash.png"), True)])
            if os.geteuid() != 0:
                esp.chmod(0)
                try:
                    sec = sources.section("Set in limine.conf", limine.current_wallpapers)
                finally:
                    esp.chmod(0o755)
                # only root can read it: "current", read when the command runs (with sudo)
                self.assertEqual([(i["value"], i["current"]) for i in sec["items"]], [("current", True)])
                self.assertIn("run with sudo", sec["items"][0]["note"])


if __name__ == "__main__":
    unittest.main()
