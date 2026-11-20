"""Every target names its outputs catppuccin-<flavour>-<source>[-<accent>][-<suffix>]."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.dont_write_bytecode = True

from catppuccinizer.cli import parse  # noqa: E402
from catppuccinizer.core.naming import output_name, slug  # noqa: E402


class Naming(unittest.TestCase):
    def test_output_name(self):
        self.assertEqual(output_name("mocha", "rings_2"), "catppuccin-mocha-rings-2")
        self.assertEqual(output_name("mocha", "My Wall.png", "peach", "v2"),
                         "catppuccin-mocha-my-wall-png-peach-v2")
        self.assertEqual(output_name("latte", "wall", None, ""), "catppuccin-latte-wall")

    def test_slug(self):
        self.assertEqual(slug("Été 2024 (final)"), "ete-2024-final")
        self.assertEqual(slug("***", "splash"), "splash")

    def test_suffix_everywhere(self):
        for target in ("image x.png", "plymouth", "limine", "ksplash", "lut"):
            self.assertEqual(parse([*target.split(), "-s", "v2"]).suffix, "v2")

    def test_suffix_characters(self):
        with self.assertRaises(SystemExit):
            parse(["lut", "-s", "Not OK"])


if __name__ == "__main__":
    unittest.main()
