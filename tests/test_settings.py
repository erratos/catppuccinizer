"""System settings (core.settings, --configure): value checks, the values replaced
kept and put back by 'default', the INI editor, the command-line rules, and the
settings of Limine (their own block of limine.conf), Plymouth (plymouthd.conf, the
hold drop-in) and the KDE splash (ksplashrc), written for real in a temporary
folder: undone, each file is back byte for byte."""
import argparse
import contextlib
import io
import json
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

from catppuccinizer.cli import main, parse  # noqa: E402
from catppuccinizer.core import settings  # noqa: E402
from catppuccinizer.core.system import System, get_ini, set_ini  # noqa: E402
from catppuccinizer.core.target import discover  # noqa: E402
from catppuccinizer.targets import ksplash, limine  # noqa: E402
from catppuccinizer.targets.plymouth import target as plymouth  # noqa: E402
from test_regression import LIMINE_CONF  # noqa: E402

TARGETS = discover()


def cli(*argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
        main([str(a) for a in argv])
    return out.getvalue()


class Tmp(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="catppuccinizer-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        env = mock.patch.dict(os.environ, {"CATPPUCCINIZER_STATE": str(self.tmp / "state")})
        env.start()
        self.addCleanup(env.stop)


class Values(unittest.TestCase):
    def parse(self, option, text):
        p = argparse.ArgumentParser(exit_on_error=False)
        p.add_argument(*option.flags, **option.argparse_kwargs())
        return getattr(p.parse_args([option.flags[0], text]), option.dest)

    def test_checks(self):
        timeout = settings.setting("--timeout", "t", check=settings.integer(0, 60, words=("no",)))
        self.assertEqual([self.parse(timeout, v) for v in ("5", " 007 ", "no", "default")],
                         ["5", "7", "no", "default"])
        for bad in ("61", "-1", "5s", "", "yes"):
            with self.subTest(value=bad), self.assertRaises(argparse.ArgumentError) as e:
                self.parse(timeout, bad)
            self.assertIn("a whole number from 0 to 60 or no, or default", str(e.exception))
        size = settings.setting("--size", "s", check=settings.pattern(r"\d+x\d+", "WxH"))
        self.assertEqual(self.parse(size, "1920x1080"), "1920x1080")
        with self.assertRaises(argparse.ArgumentError):
            self.parse(size, "1920x1080;reboot")
        title = settings.setting("--title", "t", check=settings.plain_text(10, forbid="$"))
        for bad in ("a\nb", "x" * 11, "$HOME"):
            with self.subTest(value=bad), self.assertRaises(argparse.ArgumentError):
                self.parse(title, bad)
        delay = settings.setting("--delay", "d", check=settings.decimal(0, 5))
        self.assertEqual(self.parse(delay, "0.5"), "0.5")
        choice = settings.setting("--x", "x", choices=["yes", "no"])
        self.assertEqual((choice.kind, choice.choices, choice.stage), ("choice", ["yes", "no", "default"], "configure"))
        with self.assertRaises(ValueError):
            settings.setting("--y", "y")

    def test_remember(self):
        tmp = Path(tempfile.mkdtemp(prefix="catppuccinizer-test-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        state, s = tmp / "s.json", System()
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(settings.remember(s, state, {"A": "1", "B": "2"}, {"A": "0", "B": None}),
                             {"A": "1", "B": "2"})
            self.assertEqual(settings.remember(s, state, {"A": "3"}, {"A": "1"}), {"A": "3"})
            self.assertEqual(json.loads(state.read_text()), {"previous": {"A": "0", "B": None}})
            self.assertEqual(settings.remember(s, state, {"A": "default", "C": "default"}, {}), {"A": "0"})
            self.assertEqual(settings.remember(s, state, {"B": "default"}, {}), {"B": None})
        self.assertIn("C: as it was, nothing to undo", out.getvalue())
        self.assertFalse(state.exists())                        # nothing left to undo

    def test_ini(self):
        text = "# conf\r\n[Daemon]\r\nTheme=bgrt\r\n\r\n[Other]\r\nShowDelay=9\r\n"
        new = set_ini(text, "Daemon", "ShowDelay", "2")
        self.assertEqual(new, "# conf\r\n[Daemon]\r\nTheme=bgrt\r\nShowDelay=2\r\n\r\n[Other]\r\nShowDelay=9\r\n")
        self.assertEqual((get_ini(new, "Daemon", "ShowDelay"), get_ini(new, "Other", "ShowDelay")), ("2", "9"))
        self.assertEqual(set_ini(new, "Daemon", "ShowDelay", None), text)          # back byte for byte
        self.assertEqual(set_ini(text, "Daemon", "Theme", "x").count("Theme=x"), 1)
        self.assertEqual(set_ini("", "Daemon", "A", "1"), "[Daemon]\nA=1\n")
        self.assertEqual(set_ini("x=1", "Daemon", "A", "1"), "x=1\n\n[Daemon]\nA=1\n")
        for bad in (("Daemon", "A", "1\nTheme=evil"), ("Dae]mon", "A", "1"), ("Daemon", "A=B", "1")):
            with self.subTest(args=bad), self.assertRaises(SystemExit):
                set_ini(text, *bad)


class CommandLine(Tmp):
    def test_rules(self):
        for argv, msg in ((["limine", "--timeout", "3"], "--timeout: system settings, written with --configure"),
                          (["limine", "--configure", "--apply"], "--configure goes alone"),
                          (["limine", "--configure", "--restore"], "goes alone")):
            with self.subTest(argv=argv), self.assertRaises(SystemExit) as e:
                parse(argv)
            self.assertIn(msg, str(e.exception))
        a = parse(["plymouth", "--configure", "--hold", "3"])     # no theme in use needed
        self.assertEqual((a.configure, a.hold, a.show_delay), (True, "3", None))
        self.assertEqual(settings.given(a, TARGETS["plymouth"].all_options()), {"hold": "3"})

    def test_steps_and_options(self):
        for name in ("limine", "plymouth", "ksplash", "grub"):
            t = TARGETS[name]
            with self.subTest(target=name):
                self.assertTrue(t.has_settings)
                self.assertEqual(t.steps[-1], "configure")
                self.assertTrue(settings.setting_options(t.all_options()))
                self.assertTrue(t.tips)
        for name in ("image", "lut"):
            self.assertFalse(TARGETS[name].has_settings)

    def test_listing(self):
        """--configure alone: the current values and the tips, nothing written."""
        esp = self.tmp / "esp"
        esp.mkdir()
        (esp / "limine.conf").write_text(LIMINE_CONF)
        out = cli("limine", "--configure", "--esp", esp)
        self.assertRegex(out, r"--timeout +3\n")
        self.assertRegex(out, r"--branding +Test\n")
        self.assertRegex(out, r"--resolution +\(not set\)\n")
        self.assertIn("Tips", out)
        self.assertEqual((esp / "limine.conf").read_text(), LIMINE_CONF)


class Limine(Tmp):
    def setUp(self):
        super().setUp()
        self.esp = self.tmp / "esp"
        self.esp.mkdir()
        self.conf = self.esp / "limine.conf"
        self.conf.write_bytes(LIMINE_CONF.replace("\n", "\r\n").encode())    # CRLF kept

    def configure(self, *argv):
        return cli("limine", "--configure", "--esp", self.esp, *argv)

    def test_cycle(self):
        self.configure("--timeout", "1", "--branding", "My PC", "--font-scale", "2x2")
        text = self.conf.read_bytes().decode()
        self.assertIn("# (catppuccinizer settings) timeout: 3\r\n", text)
        self.assertIn("# (catppuccinizer settings) interface_branding: Test\r\n", text)
        block = limine.SETTINGS.lines(text)
        self.assertEqual(block, ["timeout: 1", "interface_branding: My PC", "term_font_scale: 2x2"])
        self.assertLess(text.index(limine.SETTINGS.end), text.index("/+Linux"))
        now = TARGETS["limine"].settings_now(parse(["limine", "--configure", "--esp", str(self.esp)]))
        self.assertEqual((now["timeout"], now["branding"], now["margin"]), ("1", "My PC", None))
        # the theme applied meanwhile: the two blocks live side by side
        lines = limine.theme_lines("mocha", "mauve")
        with_theme = limine.insert_theme(text, lines)
        self.assertEqual(limine.SETTINGS.lines(with_theme), block)
        self.assertEqual(limine.strip_theme(with_theme), text)
        self.conf.write_bytes(with_theme.encode())
        self.configure("--timeout", "default", "--margin", "0")
        text = self.conf.read_bytes().decode()
        self.assertEqual(limine.SETTINGS.lines(text), ["interface_branding: My PC", "term_font_scale: 2x2",
                                                       "term_margin: 0"])
        self.assertTrue(text.startswith("timeout: 3\r\n"))             # its own line again
        self.assertEqual(limine.THEME.lines(text), lines[1:-1])       # the theme untouched
        self.configure("--branding", "default", "--font-scale", "default", "--margin", "default")
        self.assertEqual(limine.strip_theme(self.conf.read_bytes().decode()),
                         LIMINE_CONF.replace("\n", "\r\n"))           # byte for byte
        out = self.configure("--remember-last", "default")
        self.assertIn("remember_last_entry: as it was, nothing to undo", out)
        self.assertIn("nothing to change", out)

    def test_dry_run_and_refusals(self):
        out = self.configure("--timeout", "no", "--dry-run")
        self.assertIn(f"would write {self.conf}", out)
        self.assertEqual(self.conf.read_bytes().decode(), LIMINE_CONF.replace("\n", "\r\n"))
        broken = LIMINE_CONF.replace("timeout: 3\n", f"{limine.SETTINGS.begin}\ntimeout: 1\n")
        self.conf.write_text(broken)
        with self.assertRaises(SystemExit) as e:
            self.configure("--timeout", "2")
        self.assertIn("fix it by hand", str(e.exception))
        self.assertEqual(self.conf.read_text(), broken)
        with self.assertRaises(SystemExit):
            cli("limine", "--configure", "--esp", self.esp, "--branding", "a\nb")


class Plymouth(Tmp):
    def setUp(self):
        super().setUp()
        self.conf = self.tmp / "etc/plymouth/plymouthd.conf"
        self.conf.parent.mkdir(parents=True)
        self.conf.write_text("[Daemon]\nTheme=spinner\nShowDelay=5\n")
        self.defaults = self.tmp / "plymouthd.defaults"
        self.defaults.write_text("[Daemon]\nTheme=bgrt\nShowDelay=0\nDeviceTimeout=8\n")
        self.dropin = self.tmp / "etc/systemd/system/plymouth-quit.service.d/catppuccinizer.conf"
        self.ran = []
        for patch in (mock.patch.object(plymouth, "DAEMON_CONF", self.conf),
                      mock.patch.object(plymouth, "DAEMON_DEFAULTS", self.defaults),
                      mock.patch.object(plymouth, "HOLD_DROPIN", self.dropin),
                      mock.patch.object(plymouth, "default_theme", lambda: "spinner"),
                      mock.patch.object(System, "run", lambda s, cmd: self.ran.append([str(c) for c in cmd]) or 0)):
            patch.start()
            self.addCleanup(patch.stop)

    def test_cycle(self):
        before = self.conf.read_text()
        cli("plymouth", "--configure", "--show-delay", "1.5", "--scale", "2")
        self.assertEqual(self.conf.read_text(), "[Daemon]\nTheme=spinner\nShowDelay=1.5\nDeviceScale=2\n")
        self.assertEqual(self.ran, [["plymouth-set-default-theme", "-R", "spinner"]])    # initramfs
        now = plymouth.settings_now()
        self.assertEqual(now, {"show_delay": "1.5", "device_timeout": "8 (plymouthd.defaults)",
                               "scale": "2", "hold": None})
        cli("plymouth", "--configure", "--show-delay", "default", "--scale", "default")
        self.assertEqual(self.conf.read_text(), before)                  # 5 back, no DeviceScale
        self.assertFalse((self.tmp / "state/plymouth-settings.json").exists())

    def test_hold(self):
        cli("plymouth", "--configure", "--hold", "3")
        self.assertRegex(self.dropin.read_text(), r"\[Service\]\nExecStartPre=\S*sleep 3\n")
        self.assertEqual(self.ran, [["systemctl", "daemon-reload"]])      # plymouthd.conf untouched
        self.assertEqual(plymouth.settings_now()["hold"], "3")
        cli("plymouth", "--configure", "--hold", "default")
        self.assertFalse(self.dropin.parent.exists())
        self.assertIn("nothing to undo", cli("plymouth", "--configure", "--hold", "default"))


class KSplash(Tmp):
    def test_cycle(self):
        rc = {"Engine": ""}
        def write(system, values):
            for k, v in values.items():
                rc[k] = v or ""
        with mock.patch.object(ksplash, "read_setting", lambda key: rc[key]), \
                mock.patch.object(ksplash, "set_settings", write):
            cli("ksplash", "--configure", "--splash", "off")
            self.assertEqual(rc["Engine"], "none")
            self.assertEqual(TARGETS["ksplash"].settings_now(), {"splash": "off"})
            cli("ksplash", "--configure", "--splash", "on")
            self.assertEqual(rc["Engine"], "KSplashQML")
            cli("ksplash", "--configure", "--splash", "default")
            self.assertEqual(rc["Engine"], "")                        # unset again, as before


if __name__ == "__main__":
    unittest.main()
