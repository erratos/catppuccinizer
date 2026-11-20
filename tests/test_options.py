"""Declared options (core.options): every option of every target is complete and
coherent, and the rules shared by the command line and the GUI."""
import argparse
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True

from catppuccinizer.cli import parse  # noqa: E402
from catppuccinizer.core import options  # noqa: E402
from catppuccinizer.core.options import Option, condition_met  # noqa: E402
from catppuccinizer.core.target import discover  # noqa: E402

TARGETS = discover()


def every_option():
    for name, t in TARGETS.items():
        for o in t.all_options():
            yield name, t, o


class Declarations(unittest.TestCase):
    def test_help_is_one_line(self):
        for name, _, o in every_option():
            with self.subTest(target=name, option=o.dest):
                self.assertTrue(o.help and o.help.strip(), "no help")
                self.assertNotIn("\n", o.help)

    def test_fields_are_known_values(self):
        for name, _, o in every_option():
            with self.subTest(target=name, option=o.dest):
                self.assertIn(o.stage, options.STAGES)
                self.assertIn(o.scope.partition(":")[0], options.SCOPES)
                self.assertIn(o.sudo, options.SUDO)
                self.assertIn(o.accept, options.ACCEPT)
                self.assertIn(o.kind, options.KINDS)
                if o.image:
                    self.assertTrue((ROOT / o.image).is_file(), o.image)

    def test_stage_is_coherent(self):
        for name, _, o in every_option():
            with self.subTest(target=name, option=o.dest):
                if o.sudo:              # only what touches the system needs root
                    self.assertIn(o.stage, options.SYSTEM_STAGES)
                if o.source:            # what is recoloured
                    self.assertEqual(o.stage, "build")
                if o.scope != "target":  # core options do not touch the system
                    self.assertIn(o.stage, ("analyse", "preview", "build"))

    def test_when_refers_to_existing_options(self):
        facts = options.analysis([])
        for name, t, o in every_option():
            dests = {x.dest for x in t.all_options()}
            for key in o.when or {}:
                with self.subTest(target=name, option=o.dest, key=key):
                    if key.startswith("analysis."):
                        self.assertIn(key.partition(".")[2], facts)
                    else:
                        self.assertIn(key, dests)

    def test_targets_declare_only_their_own(self):
        common = {o.dest for o in options.COMMON + options.COLOURS}
        for name, t in TARGETS.items():
            for o in t.options():
                with self.subTest(target=name, option=o.dest):
                    self.assertNotEqual(o.scope, "common")
                    self.assertNotIn(o.dest, common)

    def test_method_options_come_from_the_core(self):
        image = {o.dest: o for o in TARGETS["image"].options()}
        self.assertEqual(image["method"].scope, "method")
        self.assertEqual(image["keep_lum"].scope, "method:lut")
        self.assertEqual(image["lutgen_algo"].scope, "method:lutgen")
        self.assertEqual(image["lutgen_algo"].when, {"method": ["lutgen"]})   # from the scope


class Rules(unittest.TestCase):
    def test_condition(self):
        when = {"method": ["lutgen"], "lutgen_algo": ["blur"]}
        self.assertTrue(condition_met(when, {"method": "lutgen", "lutgen_algo": "blur"}))
        self.assertFalse(condition_met(when, {"method": "lut", "lutgen_algo": "blur"}))
        self.assertTrue(condition_met({"format": ["hald"]}, {"format": ["cube", "hald"]}))
        self.assertFalse(condition_met({"format": ["hald"]}, {"format": ["cube"]}))
        self.assertTrue(condition_met(None, {}))

    def test_analysis_facts(self):
        when = {"analysis.remappable": [True]}
        self.assertTrue(condition_met(when, {}))                         # not analysed yet
        self.assertFalse(condition_met(when, {}, {"remappable": False}))
        lut = {"remap": False, "colours": []}
        keys = {"remap": True, "colours": [{"name": "white"}]}
        self.assertEqual(options.analysis([lut]), {"remappable": False})
        self.assertEqual(options.analysis([lut, keys]), {"remappable": True})

    def test_range_is_checked(self):
        with self.assertRaises(SystemExit) as e:
            parse(["image", "x.png", "--keep-lum", "2"])
        self.assertEqual(str(e.exception), "--keep-lum must be between 0 and 1")
        with self.assertRaises(SystemExit) as e:
            parse(["lut", "--hald-level", "20"])
        self.assertEqual(str(e.exception), "--hald-level must be between 2 and 16")

    def test_argparse_from_options(self):
        p = options.add_to(argparse.ArgumentParser(), [
            Option("src", nargs="+", help="sources"),
            Option("--level", type=int, default=3, range=(1, 9), help="level"),
            Option("--fast", switch=True, help="fast"),
            Option("--tag", nargs="+", extend=True, default=[], help="100% sure")])
        a = p.parse_args(["a", "b", "--tag", "x", "--tag", "y", "--fast"])
        self.assertEqual((a.src, a.level, a.fast, a.tag), (["a", "b"], 3, True, ["x", "y"]))
        self.assertIn("1..9", p.format_help())                          # metavar from the range
        with self.assertRaises(ValueError):                             # one dest, one option
            options.add_to(argparse.ArgumentParser(), [Option("--x", help="a"),
                                                       Option("--x", help="b")])

    def test_replace(self):
        o = Option("--method", choices=["a", "b"], default="a", scope="method", help="m")
        r = o.replace(choices=["b"], default="b")
        self.assertEqual((r.choices, r.default, r.scope, r.help), (["b"], "b", "method", "m"))
        self.assertEqual(o.choices, ["a", "b"])


if __name__ == "__main__":
    unittest.main()
