"""$CATPPUCCINIZER_PLYMOUTH_SRC: the catalogue and the name lookup use the same
local folder of themes, and nothing is fetched."""
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.dont_write_bytecode = True

from catppuccinizer.targets.plymouth import upstream  # noqa: E402
from catppuccinizer.targets.plymouth.target import TARGET  # noqa: E402

FIXTURES = HERE / "fixtures"


class LocalSource(unittest.TestCase):
    def setUp(self):
        env = mock.patch.dict(os.environ, {upstream.SRC_ENV: str(FIXTURES)})
        env.start()
        self.addCleanup(env.stop)
        fetch = mock.patch.object(upstream, "ensure_clone",
                                  side_effect=AssertionError("must not fetch"))
        fetch.start()
        self.addCleanup(fetch.stop)

    def test_catalogue_and_lookup_agree(self):
        names = {s["value"] for s in TARGET.sources()}
        self.assertEqual(names, {"glow_mini", "hexa_mini"})
        for name in names:
            self.assertEqual(upstream.resolve_theme(name), FIXTURES / name)

    def test_unknown_name(self):
        with self.assertRaises(SystemExit) as e:
            upstream.resolve_theme("angular")
        self.assertIn(upstream.SRC_ENV, str(e.exception))

    def test_not_a_folder(self):
        with mock.patch.dict(os.environ, {upstream.SRC_ENV: str(FIXTURES / "nope")}):
            with self.assertRaises(SystemExit):
                upstream.upstream_themes()


if __name__ == "__main__":
    unittest.main()
