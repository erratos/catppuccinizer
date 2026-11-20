"""Security: names checked before any system path, copies that do not follow links
out of the source, atomic writes, pruned backups, commands without a shell
(docs/architecture.md, Security)."""
import contextlib
import io
import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
sys.dont_write_bytecode = True

from catppuccinizer.cli import main  # noqa: E402
from catppuccinizer.core import system as core_system  # noqa: E402
from catppuccinizer.core.naming import check_name  # noqa: E402
from catppuccinizer.core.system import (KEEP_BACKUPS, System, copy_folder, place,  # noqa: E402
                                        source_file, which)
from catppuccinizer.targets import limine  # noqa: E402
from test_regression import FIXTURES, LIMINE_CONF  # noqa: E402

BAD_NAMES = ["", ".", "..", "../etc", "a/b", "/etc", "-R", ".hidden", "a..b", "a b", "a\nb",
             "x" * 200, None, 3]


def quiet(fn, *args, **kw):
    with contextlib.redirect_stdout(io.StringIO()) as out:
        result = fn(*args, **kw)
    return result, out.getvalue()


class Tmp(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="catppuccinizer-test-"))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)


class Names(unittest.TestCase):
    def test_good_names(self):
        for name in ("catppuccin-mocha-glow", "org.kde.breeze.desktop", "bgrt", "KSplashQML",
                     "theme_2+x"):
            self.assertEqual(check_name(name), name)
            self.assertEqual(place("/usr/share/plymouth/themes", name).name, name)

    def test_bad_names(self):
        for name in BAD_NAMES:
            with self.subTest(name=name), self.assertRaises(SystemExit):
                place("/usr/share/plymouth/themes", name)


class Copies(Tmp):
    def make_source(self):
        src = self.tmp / "theme"
        (src / "sub").mkdir(parents=True)
        (src / "a.txt").write_text("a")
        (src / "sub/b.txt").write_text("b")
        (self.tmp / "secret").write_text("secret")
        (self.tmp / "outside").mkdir()
        (self.tmp / "outside/c.txt").write_text("c")
        (src / "inside-link").symlink_to("a.txt")                 # inside: copied as a file
        (src / "secret-link").symlink_to(self.tmp / "secret")     # out of the theme
        (src / "dotdot-link").symlink_to("../secret")
        (src / "dir-link").symlink_to(self.tmp / "outside")      # a folder: never entered
        (src / "broken").symlink_to(self.tmp / "nope")
        os.mkfifo(src / "fifo")                                   # not a regular file
        return src

    def test_source_file(self):
        src = self.make_source()
        self.assertEqual(source_file(src / "a.txt", src), (src / "a.txt").resolve())
        self.assertEqual(source_file(src / "inside-link", src), (src / "a.txt").resolve())
        for name in ("secret-link", "dotdot-link", "dir-link", "broken", "fifo", "sub", "missing"):
            self.assertIsNone(source_file(src / name, src), name)

    def test_copy_folder(self):
        src = self.make_source()
        skipped, out = quiet(copy_folder, src, self.tmp / "out", ignore=("*.qmlc",))
        dst = self.tmp / "out"
        self.assertEqual(sorted(str(p.relative_to(dst)) for p in dst.rglob("*")),
                         ["a.txt", "inside-link", "sub", "sub/b.txt"])
        self.assertFalse((dst / "inside-link").is_symlink())
        self.assertEqual((dst / "inside-link").read_text(), "a")
        self.assertEqual(sorted(p.name for p in skipped),
                         ["broken", "dir-link", "dotdot-link", "fifo", "secret-link"])
        self.assertIn("note: skipped", out)

    def test_install_copy(self):
        src = self.make_source()
        dst = self.tmp / "themes/x"
        dst.mkdir(parents=True)
        (dst / "old.txt").write_text("old")
        old = os.umask(0o077)               # rights are explicit, not the umask's
        try:
            quiet(System().copy_tree, src, dst)
        finally:
            os.umask(old)
        self.assertFalse((dst / "old.txt").exists())              # replaced, not merged
        self.assertFalse((dst / "secret-link").exists())
        self.assertEqual(stat.S_IMODE((dst / "a.txt").stat().st_mode), 0o644)   # not the umask
        self.assertEqual(stat.S_IMODE((dst / "sub").stat().st_mode), 0o755)
        self.assertEqual([p.name for p in dst.parent.iterdir()], ["x"])      # no temporary left

    def test_install_over_a_link(self):
        src = self.make_source()
        (self.tmp / "themes").mkdir()
        (self.tmp / "themes/x").symlink_to(self.tmp / "outside")
        quiet(System().copy_tree, src, self.tmp / "themes/x")
        self.assertFalse((self.tmp / "themes/x").is_symlink())
        self.assertEqual([p.name for p in (self.tmp / "outside").iterdir()], ["c.txt"])

    def test_remove_a_link(self):
        (self.tmp / "outside").mkdir()
        (self.tmp / "outside/c.txt").write_text("c")
        (self.tmp / "link").symlink_to(self.tmp / "outside")
        quiet(System().remove, self.tmp / "link")
        self.assertTrue((self.tmp / "outside/c.txt").exists())


class Writes(Tmp):
    def test_atomic_keeps_rights(self):
        f = self.tmp / "limine.conf"
        f.write_text("old")
        f.chmod(0o600)
        quiet(System().write_text, f, "new\r\nline\n")
        self.assertEqual(f.read_bytes(), b"new\r\nline\n")       # no newline translation
        self.assertEqual(stat.S_IMODE(f.stat().st_mode), 0o600)
        self.assertEqual([p.name for p in self.tmp.iterdir()], ["limine.conf"])

    def test_failed_write_leaves_the_file(self):
        f = self.tmp / "conf"
        f.write_text("old")
        real = os.replace

        def boom(*a):
            raise OSError("disk full")
        core_system.os.replace = boom
        try:
            with self.assertRaises(OSError):
                quiet(System().write_text, f, "new")
        finally:
            core_system.os.replace = real
        self.assertEqual(f.read_text(), "old")
        self.assertEqual([p.name for p in self.tmp.iterdir()], ["conf"])

    def test_backups_are_pruned(self):
        f = self.tmp / "limine.conf"
        f.write_text("0")
        s = System()
        for i in range(KEEP_BACKUPS + 3):
            quiet(s.write_text, f, str(i + 1), backup=True)
        baks = sorted(self.tmp.glob("limine.conf.*.bak"))
        self.assertEqual(len(baks), KEEP_BACKUPS)
        self.assertEqual([b.read_text() for b in baks], [str(i) for i in range(3, KEEP_BACKUPS + 3)])
        (self.tmp / "limine.conf.mine.bak").write_text("user's own")     # not ours: kept
        quiet(s.write_text, f, "x", backup=True)
        self.assertTrue((self.tmp / "limine.conf.mine.bak").exists())

    def test_state_must_be_an_object(self):
        (self.tmp / "s.json").write_text("[1]")
        with self.assertRaises(SystemExit):
            System.load_state(self.tmp / "s.json")


class Commands(Tmp):
    def test_which(self):
        self.assertEqual(which(sys.executable), sys.executable)
        self.assertIsNone(which("catppuccinizer-no-such-command"))
        self.assertTrue(os.path.isabs(which("sh")))

    def test_run_resolves_and_never_uses_a_shell(self):
        s = System(dry_run=True)
        quiet(s.run, ["sh", "-c", "x; rm -rf ~"])
        self.assertTrue(os.path.isabs(s.done[0][1][0]))           # an absolute path
        self.assertEqual(s.done[0][1][1:], ["-c", "x; rm -rf ~"])  # arguments untouched
        with self.assertRaises(SystemExit):
            quiet(System().run, ["catppuccinizer-no-such-command"])

    def test_no_shell_anywhere(self):
        root = HERE.parent / "catppuccinizer"
        for f in root.rglob("*.py"):
            text = f.read_text()
            self.assertNotIn("shell=True", text, f)
            self.assertNotIn("os.system(", text, f)
            self.assertNotIn("os.popen(", text, f)


class StateNames(Tmp):
    """Names read back from a state file are checked before restore uses them."""
    def setUp(self):
        super().setUp()
        os.environ["CATPPUCCINIZER_STATE"] = str(self.tmp)

    def tearDown(self):
        os.environ.pop("CATPPUCCINIZER_STATE", None)
        super().tearDown()

    def test_plymouth(self):
        for state in ({"installed": ["../../../etc"]}, {"installed": [], "previous": "-x"}):
            (self.tmp / "plymouth.json").write_text(json.dumps(state))
            with self.subTest(state=state):
                with self.assertRaises(SystemExit) as e:
                    quiet(main, ["plymouth", "--restore", "--dry-run"])
                self.assertIn("Invalid theme name", str(e.exception))

    def test_ksplash(self):
        (self.tmp / "ksplash.json").write_text(json.dumps({"installed": ["../../.ssh"]}))
        with self.assertRaises(SystemExit) as e:
            quiet(main, ["ksplash", "--restore", "--dry-run"])
        self.assertIn("Invalid package id", str(e.exception))


class SourceLinks(Tmp):
    """A theme's links out of its folder are not read, so not copied into the output
    (and installed, world-readable) under sudo."""
    def test_plymouth(self):
        import shutil
        theme = self.tmp / "glow_mini"
        shutil.copytree(FIXTURES / "glow_mini", theme)
        (self.tmp / "secret").write_text("root only")
        (theme / "font.ttf").symlink_to(self.tmp / "secret")
        os.environ["CATPPUCCINIZER_CONFIGS"] = str(self.tmp / "configs")
        try:
            _, out = quiet(main, ["plymouth", str(theme), "-a", "mauve", "-o", str(self.tmp / "out")])
        finally:
            os.environ.pop("CATPPUCCINIZER_CONFIGS", None)
        self.assertIn("note: skipped", out)
        self.assertFalse(any(p.name == "font.ttf" for p in (self.tmp / "out").rglob("*")))


class Limine(Tmp):
    """limine.conf: only the block is added, checked before writing; restore takes
    away exactly that, so the file comes back byte for byte."""
    def apply(self, conf_bytes, *extra):
        esp = self.tmp / "esp"
        esp.mkdir(exist_ok=True)
        (esp / "limine.conf").write_bytes(conf_bytes)
        quiet(main, ["limine", "-a", "mauve", "--apply", "--esp", str(esp),
                     "-o", str(self.tmp / "out"), *extra])
        return esp

    def restore(self, esp):
        quiet(main, ["limine", "--restore", "--esp", str(esp)])
        return (esp / "limine.conf").read_bytes()

    def test_byte_for_byte(self):
        odd = (LIMINE_CONF.replace("\n", "\r\n").encode()     # CRLF, no final newline,
               .rstrip(b"\r\n") + b"\n# caf\xe9 \xff  ")       # bytes that are not UTF-8
        for original in (LIMINE_CONF.encode(), odd, b"timeout: 3\n", b"timeout: 3", b""):
            with self.subTest(original=original[:20]):
                esp = self.apply(original)
                new = (esp / "limine.conf").read_bytes()
                self.assertEqual(new.count(limine.BEGIN.encode()), 1)
                self.assertEqual(self.restore(esp), original)
                first = min(esp.glob("limine.conf.*.bak"))         # the backup apply made
                self.assertEqual(first.read_bytes(), original)
                import shutil
                shutil.rmtree(esp)

    def test_apply_twice_one_block(self):
        esp = self.apply(LIMINE_CONF.encode())
        self.apply((esp / "limine.conf").read_bytes())
        text = (esp / "limine.conf").read_text()
        self.assertEqual(text.count(limine.BEGIN), 1)
        self.assertEqual(self.restore(esp), LIMINE_CONF.encode())

    def test_restore_keeps_later_changes(self):
        esp = self.apply(LIMINE_CONF.encode())
        entry = "\n/+Linux LTS\n    //linux-lts\n        protocol: linux\n"
        with open(esp / "limine.conf", "a") as f:        # a kernel update adds an entry
            f.write(entry)
        self.assertEqual(self.restore(esp), (LIMINE_CONF + entry).encode())

    def test_restore_without_theme_writes_nothing(self):
        esp = self.apply(LIMINE_CONF.encode())
        self.restore(esp)
        n = len(list(esp.glob("*.bak")))
        self.restore(esp)
        self.assertEqual(len(list(esp.glob("*.bak"))), n)

    def test_broken_block_is_refused(self):
        broken = LIMINE_CONF.replace("timeout: 3\n", f"{limine.BEGIN}: x\nbackdrop: 000000\n")
        with self.assertRaises(SystemExit) as e:
            self.apply(broken.encode())
        self.assertIn("fix it by hand", str(e.exception))
        self.assertEqual((self.tmp / "esp/limine.conf").read_text(), broken)
        self.assertEqual([p.name for p in (self.tmp / "esp").iterdir()], ["limine.conf"])

    def test_check_insert(self):
        lines = limine.theme_lines("mocha", "mauve")
        new = limine.insert_theme(LIMINE_CONF, lines)
        block = "".join(x + "\n" for x in lines) + "\n"
        limine.check_insert(LIMINE_CONF, new, block)                   # fine
        for bad in (new.replace("timeout: 3", "timeout: 0"),          # something else changed
                    new.replace("backdrop:", "backdrop: 0 #"),         # not our block
                    new + block):                                     # two blocks
            with self.assertRaises(SystemExit):
                limine.check_insert(LIMINE_CONF, bad, block)

    def test_wallpaper_stays_on_the_esp(self):
        esp = self.tmp / "esp"
        esp.mkdir()
        self.assertEqual(limine.resolve_on_esp("boot():/w.png#x", esp), esp / "w.png")
        for ref in ("boot():/../etc/shadow", "boot():/a/../../x.png"):
            with self.assertRaises(SystemExit):
                limine.resolve_on_esp(ref, esp)


if __name__ == "__main__":
    unittest.main()
