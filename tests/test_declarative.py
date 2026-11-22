"""Declarative (TOML) targets: core.declarative (strict schema, trust rules), the
built-in grub.toml in a dry run, the user's TOML targets (discovery, a real
install / apply / restore in a temporary home), and the KEY="value" helpers of
core.system."""
import contextlib
import io
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
sys.dont_write_bytecode = True

from catppuccinizer.cli import main                             # noqa: E402
from catppuccinizer.core import declarative                     # noqa: E402
from catppuccinizer.core.system import get_variable, set_variable  # noqa: E402
from catppuccinizer.core.target import discover                 # noqa: E402
from test_regression import make_grub                           # noqa: E402

USER_TOML = """name = "mygrub"
help = "a GRUB-like theme of mine"

[source]
marker = "theme.txt"

[[parts]]
name = "text"
kind = "text"
files = ["*.txt"]

[[parts]]
name = "images"
kind = "image"

[install]
to = "~/installed"

[apply]
set = [{ file = "~/conf/default", key = "THEME", value = "{installed}/theme.txt" }]
"""
CONF = "# settings\r\nTIMEOUT=5\r\nTHEME=/old/theme.txt\r\n"


def cli(*argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
        main([str(a) for a in argv])
    return out.getvalue()


class Home(unittest.TestCase):
    """A temporary home: its config, state and HOME."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="catppuccinizer-test-"))
        self.home = self.tmp / "home"
        self.targets = self.home / ".config/catppuccinizer/targets"
        self.targets.mkdir(parents=True)
        self.env = {k: os.environ.get(k) for k in ("HOME", "XDG_CONFIG_HOME", "CATPPUCCINIZER_STATE")}
        os.environ["HOME"] = str(self.home)
        os.environ.pop("XDG_CONFIG_HOME", None)
        os.environ["CATPPUCCINIZER_STATE"] = str(self.tmp / "state")

    def tearDown(self):
        for k, v in self.env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, text, name="mine.toml"):
        f = self.targets / name
        f.write_text(text)
        f.chmod(0o644)
        return f

    def load_error(self, text):
        with self.assertRaises(SystemExit) as e:
            declarative.load(self.write(text))
        return str(e.exception)


class Schema(Home):
    def test_strict(self):
        self.assertIn("unknown key 'colour'", self.load_error(USER_TOML.replace(
            'kind = "text"', 'kind = "text"\ncolour = "x"')))
        self.assertIn("'marker' is missing", self.load_error(USER_TOML.replace('marker = "theme.txt"', "")))
        self.assertIn("'files' must be a list of strings", self.load_error(
            USER_TOML.replace('files = ["*.txt"]', 'files = "*.txt"')))
        self.assertIn("kind must be one of", self.load_error(USER_TOML.replace('"image"', '"sound"')))
        self.assertIn("unknown {theme}", self.load_error(USER_TOML.replace("{installed}", "{theme}")))
        self.assertIn("name must be", self.load_error(USER_TOML.replace("mygrub", "My Grub")))
        self.assertIn("it needs [install]", self.load_error(
            USER_TOML.replace('[install]\nto = "~/installed"\n', "")))

    def test_links(self):
        """[[source.links]]: the other sources, https:// pages only."""
        links = ('[source]\nmarker = "theme.txt"\n\n[[source.links]]\nname = "Site"\n'
                 'url = "{}"\nnote = "themes"\n')
        t = declarative.load(self.write(USER_TOML.replace('[source]\nmarker = "theme.txt"\n',
                                                          links.format("https://example.org/t"))))
        self.assertEqual(t.links, [{"name": "Site", "url": "https://example.org/t", "note": "themes"}])
        self.assertIn("--list", [f for o in t.all_options() for f in o.flags])
        self.assertIn("must be an https:// address", self.load_error(USER_TOML.replace(
            '[source]\nmarker = "theme.txt"\n', links.format("http://example.org/t"))))
        self.assertIn("'url' is missing", self.load_error(USER_TOML.replace(
            '[source]\nmarker = "theme.txt"\n', '[source]\nmarker = "theme.txt"\n\n[[source.links]]\nname = "x"\n')))

    def test_online(self):
        """[[source.online]]: an OCS category browsed in the GUI, its themes found with
        the target's marker."""
        online = ('[source]\nmarker = "theme.txt"\n\n[[source.online]]\nstore = "{}"\n'
                  'category = {}\ntitle = "Store: themes"\n')
        make = lambda store, cat: USER_TOML.replace('[source]\nmarker = "theme.txt"\n',   # noqa: E731
                                                    online.format(store, cat))
        t = declarative.load(self.write(make("gnome-look", 109)))
        (src,) = t.online
        self.assertEqual((src.name, src.title, src.accept, src.marker), ("gnome-look-109", "Store: themes",
                                                                         "dir", "theme.txt"))
        self.assertEqual(t.other_sources[0]["url"], "https://www.gnome-look.org/browse?cat=109")
        self.assertIn("--list", [f for o in t.all_options() for f in o.flags])
        self.assertIn("unknown store", self.load_error(make("evil.org", 109)))
        self.assertIn("'category' must be a number", self.load_error(make("gnome-look", '"109"')))
        self.assertIn("positive number", self.load_error(make("gnome-look", -1)))
        self.assertIn("already given", self.load_error(make("gnome-look", 109).replace(
            'title = "Store: themes"\n', 'title = "Store: themes"\n\n[[source.online]]\n'
            'store = "gnome-look"\ncategory = 109\n')))

    def test_commands(self):
        text = USER_TOML + 'run = [["rm", "-rf", "{installed}"]]\n'
        self.assertIn("rm is not a command apply may run", self.load_error(text))
        t = declarative.load(self.write(USER_TOML + 'run = [["fc-cache"]]\n'))
        self.assertEqual(t.commands, [["fc-cache"]])

    def test_user_rights_only(self):
        self.assertIn("sudo = true is only for", self.load_error(
            USER_TOML.replace('to = "~/installed"', 'to = "~/installed"\nsudo = true')))
        self.assertIn("is not in your home", self.load_error(
            USER_TOML.replace('to = "~/installed"', 'to = "/usr/share/themes"')))
        self.assertIn("is not in your home", self.load_error(
            USER_TOML.replace("~/conf/default", "/etc/default/grub")))
        self.assertIn("no '..'", self.load_error(USER_TOML.replace("~/conf/default", "~/../../etc/x")))
        (self.home / "out").symlink_to(self.tmp)            # a link in the home that leads out of it
        self.assertIn("is not in your home", self.load_error(USER_TOML.replace("~/conf/default", "~/out/x")))

    def test_not_as_root(self):
        """Under sudo, a user's TOML target is refused: its commands and files would be
        root's (a file dropped in ~/.config must not become a root action)."""
        self.write(USER_TOML + 'run = [["grub-mkconfig", "-o", "/etc/shadow"]]\n')
        make_grub(self.tmp / "nebula")
        with mock.patch("os.geteuid", return_value=0), self.assertRaises(SystemExit) as e:
            cli("mygrub", self.tmp / "nebula", "-a", "mauve", "--apply", "--dry-run", "-o", self.tmp / "out")
        self.assertIn("runs with your rights only, not as root", str(e.exception))
        self.assertIsNone(discover()["grub"].root_refused)                 # built-in TOML: allowed

    def test_trust(self):
        f = self.write(USER_TOML)
        f.chmod(0o666)
        with self.assertRaises(SystemExit) as e:
            declarative.load(f)
        self.assertIn("can be changed by other users", str(e.exception))
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertNotIn("mygrub", discover())       # skipped with a note, the rest works
        self.assertIn("mine.toml skipped", err.getvalue())

    def test_discovery(self):
        self.write(USER_TOML)
        self.write(USER_TOML.replace("mygrub", "image"), "clash.toml")
        self.write("name = [", "broken.toml")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            targets = discover()
        self.assertEqual(targets["mygrub"].steps, ["install", "apply", "restore"])
        self.assertNotIsInstance(targets["image"], declarative.TomlTarget)   # built-in kept
        self.assertIn("a target named 'image' exists already", err.getvalue())
        self.assertIn("broken.toml skipped", err.getvalue())
        self.assertIsInstance(targets["grub"], declarative.TomlTarget)       # built-in TOML


SETTINGS_TOML = """
[configure]
help = "write the settings"
tips = ["a tip"]

[[configure.settings]]
name = "timeout"
file = "~/conf/default"
key = "TIMEOUT"
min = -1
max = 60
help = "seconds"

[[configure.settings]]
name = "style"
file = "~/conf/default"
key = "STYLE"
choices = ["menu", "hidden"]
help = "the style"

[[configure.settings]]
name = "mode"
file = "~/conf/default"
key = "MODE"
pattern = '\\d+x\\d+'
what = "WxH"
help = "resolution"

[[configure.settings]]
name = "title"
file = "~/conf/default"
key = "TITLE"
help = "free text"
"""


class Settings(Home):
    """[configure]: settings of KEY="value" files, declared in TOML."""

    def test_schema(self):
        t = declarative.load(self.write(USER_TOML + SETTINGS_TOML))
        self.assertEqual(t.steps, ["install", "apply", "restore", "configure"])
        self.assertEqual(t.tips, ["a tip"])
        flags = [f for o in t.all_options() for f in o.flags]
        self.assertLess(flags.index("--restore"), flags.index("--timeout"))
        self.assertLess(flags.index("--title"), flags.index("--configure"))
        for change, msg in (
                (('name = "style"', 'name = "timeout"'), "name must be unique"),
                (('min = -1', 'min = -1\nchoices = ["a"]'), "checked by choices"),
                (('max = 60\n', ''), "checked by choices"),
                (('key = "MODE"', 'key = "MO DE"'), "key must be a variable name"),
                (("pattern = '", "pattern = '("), "missing"),
                (('file = "~/conf/default"\nkey = "TITLE"', 'file = "/etc/default/x"\nkey = "TITLE"'),
                 "not in your home"),
                (('help = "write the settings"', 'help = "x"\nsudo = true'), "only for the TOML targets"),
                (('tips = ["a tip"]', 'run = [["rm", "-rf", "/"]]'), "is not a command configure may run"),
                (('tips = ["a tip"]', 'run = [["fc-cache", "{name}"]]'), "is not a command configure may run")):
            with self.subTest(change=change[1]):
                self.assertIn(msg, self.load_error(USER_TOML + SETTINGS_TOML.replace(*change)))

    def test_cycle(self):
        self.write(USER_TOML + SETTINGS_TOML)
        conf = self.home / "conf/default"
        conf.parent.mkdir()
        conf.write_bytes(CONF.encode())
        cli("mygrub", "--configure", "--timeout", "-1", "--style", "hidden", "--title", "My PC")
        text = conf.read_bytes().decode()
        self.assertIn('TIMEOUT="-1"\r\n', text)
        self.assertTrue(text.endswith('STYLE="hidden"\nTITLE="My PC"\n'))
        self.assertRegex(cli("mygrub", "--configure"), r"--timeout +-1\n")
        for bad in (["--title", "a$(reboot)"], ["--mode", "big"], ["--timeout", "61"], ["--style", "x"]):
            with self.subTest(value=bad), self.assertRaises(SystemExit):
                cli("mygrub", "--configure", *bad)
        cli("mygrub", "--configure", "--timeout", "default", "--style", "default", "--title", "default")
        self.assertEqual(conf.read_bytes().decode(), CONF)                # byte for byte
        self.assertFalse((self.tmp / "state/mygrub-settings.json").exists())

    def test_grub(self):
        grub = discover()["grub"]
        self.assertEqual([o.dest for o in grub.all_options() if o.stage == "configure"],
                         ["timeout", "timeout_style", "gfxmode", "gfxpayload", "configure"])
        self.assertEqual(grub.configure_run, [["grub-mkconfig", "-o", "/boot/grub/grub.cfg"]])


class UserSteps(Home):
    """A user's TOML target, really installed, applied and restored in the home."""

    def test_cycle(self):
        self.write(USER_TOML)
        make_grub(self.tmp / "nebula")
        conf = self.home / "conf/default"
        conf.parent.mkdir()
        conf.write_bytes(CONF.encode())
        out = cli("mygrub", self.tmp / "nebula", "-a", "mauve", "--apply", "-o", self.tmp / "out")
        theme = self.home / "installed/catppuccin-mocha-nebula-mauve"
        self.assertTrue((theme / "theme.txt").is_file())
        self.assertIn(f'THEME="{theme}/theme.txt"\r\n', conf.read_bytes().decode())
        self.assertIn("back up", out)
        # a second apply: the setting before the first one is still what restore puts back
        cli("mygrub", self.tmp / "nebula", "-a", "peach", "--apply", "-o", self.tmp / "out")
        self.assertIn("nebula-peach/theme.txt", conf.read_text())
        cli("mygrub", "--restore")
        self.assertEqual(conf.read_bytes().decode(), CONF)                # byte for byte
        self.assertEqual(list((self.home / "installed").iterdir()), [])
        self.assertFalse((self.tmp / "state/mygrub.json").exists())
        with self.assertRaises(SystemExit) as e:
            cli("mygrub", "--restore")
        self.assertIn("Nothing to restore", str(e.exception))

    def test_unset_before(self):
        """A variable the file did not set: restore removes the line apply added."""
        self.write(USER_TOML)
        make_grub(self.tmp / "nebula")
        conf = self.home / "conf/default"
        conf.parent.mkdir()
        conf.write_text("TIMEOUT=5")
        cli("mygrub", self.tmp / "nebula", "-a", "mauve", "--apply", "-o", self.tmp / "out")
        self.assertIn('\nTHEME="', conf.read_text())
        cli("mygrub", "--restore")
        self.assertEqual(conf.read_text(), "TIMEOUT=5\n")


class Grub(Home):
    def test_dry_run(self):
        make_grub(self.tmp / "nebula")
        out = cli("grub", self.tmp / "nebula", "-a", "mauve", "--apply", "--dry-run", "-o", self.tmp / "out")
        name = "catppuccin-mocha-nebula-mauve"
        self.assertIn(f"would copy {self.tmp / 'out' / name} -> /boot/grub/themes/{name}", out)
        self.assertIn("would write /etc/default/grub", out)
        self.assertRegex(out, r"would run (/\S+/)?grub-mkconfig -o /boot/grub/grub\.cfg")
        self.assertFalse((self.tmp / "state").exists())
        with self.assertRaises(SystemExit) as e:
            cli("grub", "--restore", "--dry-run")
        self.assertIn("Nothing to restore", str(e.exception))

    def test_single_result(self):
        make_grub(self.tmp / "nebula")
        with self.assertRaises(SystemExit) as e:
            cli("grub", self.tmp / "nebula", "-a", "mauve", "peach", "--install", "--dry-run")
        self.assertIn("single flavour and a single accent", str(e.exception))

    def test_source(self):
        with self.assertRaises(SystemExit) as e:
            cli("grub", "no-such-theme")
        self.assertIn("No theme 'no-such-theme'", str(e.exception))
        (self.tmp / "empty").mkdir()
        with self.assertRaises(SystemExit) as e:
            cli("grub", self.tmp / "empty")
        self.assertIn("no theme.txt in it", str(e.exception))


class Variables(unittest.TestCase):
    def test_round_trip(self):
        old = get_variable(CONF, "THEME")
        new = set_variable(CONF, "THEME", "/boot/grub/themes/x/theme.txt")
        self.assertEqual(new, CONF.replace("/old/theme.txt", '"/boot/grub/themes/x/theme.txt"'))
        self.assertEqual(set_variable(new, "THEME", old, raw=True), CONF)
        self.assertEqual(set_variable(CONF, "THEME", None), "# settings\r\nTIMEOUT=5\r\n")
        self.assertIsNone(get_variable("#THEME=/x\n", "THEME"))               # a comment

    def test_unsafe(self):
        for bad in ('/x"; rm -rf /', "$(id)", "`id`", "a\nB=1", "a\\b"):
            with self.subTest(value=bad), self.assertRaises(SystemExit):
                set_variable(CONF, "THEME", bad)
        with self.assertRaises(SystemExit):
            set_variable(CONF, "A;B", "x")


if __name__ == "__main__":
    unittest.main()
