"""System steps: core.system.System (changes printed, or only listed with
--dry-run), how the command line chains build / install / apply / test / restore,
and each target's steps in a dry run (nothing outside the output folder changes)."""
import contextlib
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
sys.dont_write_bytecode = True

from catppuccinizer.cli import main, parse  # noqa: E402
from catppuccinizer.core.system import System  # noqa: E402
from test_regression import FIXTURES, LIMINE_CONF, make_images, make_splash  # noqa: E402


def cli(*argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        main([str(a) for a in argv])
    return out.getvalue()


class SystemObject(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="catppuccinizer-test-"))
        (self.tmp / "src").mkdir()
        (self.tmp / "src/a.txt").write_text("a")
        (self.tmp / "conf").write_text("old")

    def changes(self, s):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            s.copy_tree(self.tmp / "src", self.tmp / "dst")
            s.copy_file(self.tmp / "src/a.txt", self.tmp / "one/a.txt")
            bak = s.write_text(self.tmp / "conf", "new", backup=True)
            s.remove(self.tmp / "src")
            code = s.run([sys.executable, "-c", "raise SystemExit(3)"])
        return out.getvalue(), bak, code

    def test_dry_run_changes_nothing(self):
        s = System(dry_run=True)
        text, bak, code = self.changes(s)
        self.assertEqual(sorted(p.name for p in self.tmp.iterdir()), ["conf", "src"])
        self.assertEqual((self.tmp / "conf").read_text(), "old")
        self.assertEqual(code, 0)
        self.assertEqual([d[0] for d in s.done], ["copy", "copy", "back up", "write", "remove", "run"])
        self.assertTrue(all(line.startswith("  would ") for line in text.splitlines()))
        self.assertFalse(bak.exists())

    def test_changes(self):
        s = System()
        text, bak, code = self.changes(s)
        self.assertEqual((self.tmp / "dst/a.txt").read_text(), "a")
        self.assertEqual((self.tmp / "one/a.txt").read_text(), "a")
        self.assertEqual(((self.tmp / "conf").read_text(), bak.read_text()), ("new", "old"))
        self.assertFalse((self.tmp / "src").exists())
        self.assertEqual(code, 3)
        self.assertNotIn("would", text)

    def test_state(self):
        s, path = System(), self.tmp / "state/x.json"
        self.assertEqual(s.load_state(path), {})
        with contextlib.redirect_stdout(io.StringIO()):
            s.save_state(path, {"previous": "bgrt"})
            self.assertEqual(s.load_state(path), {"previous": "bgrt"})
            s.save_state(path, {})                      # nothing left to undo: removed
        self.assertFalse(path.exists())

    def test_permission_error_is_a_message(self):
        if os.geteuid() == 0:
            self.skipTest("root can write anywhere")
        (self.tmp / "ro").mkdir(mode=0o500)
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as e:
            System().write_text(self.tmp / "ro/f", "x")
        self.assertIn("run with sudo", str(e.exception))


class Chaining(unittest.TestCase):
    def test_flag_rules(self):
        with self.assertRaises(SystemExit) as e:
            parse(["limine", "--dry-run"])
        self.assertIn("--dry-run goes with", str(e.exception))
        with self.assertRaises(SystemExit) as e:
            parse(["limine", "--restore", "--apply"])
        self.assertIn("--restore goes alone", str(e.exception))
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            parse(["image", "x.png", "--install"])     # image has no system steps
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            parse(["limine", "--remove"])               # renamed --restore


class DryRun(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="catppuccinizer-test-"))
        os.environ["CATPPUCCINIZER_CONFIGS"] = str(self.tmp / "configs")
        os.environ["CATPPUCCINIZER_STATE"] = str(self.tmp / "state")

    def tearDown(self):
        os.environ.pop("CATPPUCCINIZER_STATE", None)

    def test_limine(self):
        esp = self.tmp / "esp"
        esp.mkdir()
        (esp / "limine.conf").write_text(LIMINE_CONF)
        make_images(self.tmp / "img")
        out = cli("limine", "-a", "mauve", "--wallpaper", self.tmp / "img/photo.jpg", "--apply",
                  "--dry-run", "--esp", esp, "-o", self.tmp / "out")
        self.assertEqual([p.name for p in esp.iterdir()], ["limine.conf"])     # untouched
        self.assertEqual((esp / "limine.conf").read_text(), LIMINE_CONF)
        self.assertIn("install (dry run", out)                 # --apply implies --install
        self.assertIn(f"would copy {self.tmp / 'out'}", out)
        self.assertIn(f"would write {esp / 'limine.conf'}", out)
        self.assertTrue(any((self.tmp / "out").rglob("limine-theme.conf")))   # built as usual
        out = cli("limine", "--restore", "--dry-run", "--esp", esp)
        self.assertIn("no catppuccinizer theme in it, left as it is", out)     # nothing applied
        self.assertEqual((esp / "limine.conf").read_text(), LIMINE_CONF)

    def test_plymouth(self):
        out = cli("plymouth", FIXTURES / "glow_mini", "-a", "mauve", "--apply", "--dry-run",
                  "-o", self.tmp / "out")
        name = "catppuccin-mocha-glow"
        self.assertIn(f"would copy {self.tmp / 'out' / name}", out)
        self.assertIn(f"-> /usr/share/plymouth/themes/{name}", out)
        self.assertRegex(out, rf"would run (/\S+/)?plymouth-set-default-theme -R {name}\b")
        self.assertFalse((self.tmp / "state").exists())
        out = cli("plymouth", FIXTURES / "glow_mini", "-a", "mauve", "--test", "3", "--dry-run",
                  "-o", self.tmp / "out")
        self.assertIn("would copy", out)                       # --test installs first
        self.assertRegex(out, rf"would run (/\S+/)?bash \S+preview\.sh {name}\S* 3")

    def test_ksplash(self):
        make_splash(self.tmp / "splash")
        user_dir = Path.home() / ".local/share/plasma/look-and-feel"
        before = sorted(user_dir.iterdir()) if user_dir.is_dir() else []
        out = cli("ksplash", self.tmp / "splash", "--install", "--dry-run", "-o", self.tmp / "out")
        self.assertIn(f"-> {user_dir}/catppuccin-mocha-test-splash", out)
        self.assertIn(f"would write {self.tmp / 'state/ksplash.json'}", out)
        self.assertEqual(sorted(user_dir.iterdir()) if user_dir.is_dir() else [], before)
        with self.assertRaises(SystemExit) as e:             # nothing installed yet
            cli("ksplash", "--restore")
        self.assertIn("Nothing to restore", str(e.exception))


if __name__ == "__main__":
    unittest.main()
