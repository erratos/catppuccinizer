"""--colours lists what -m can remap and writes nothing."""
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.dont_write_bytecode = True

from catppuccinizer.cli import main, parse  # noqa: E402

FIXTURES = HERE / "fixtures"


def run(*argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
        main([str(a) for a in argv])
    return out.getvalue()


class Colours(unittest.TestCase):
    def test_writes_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            with mock.patch.dict(os.environ, {"CATPPUCCINIZER_CONFIGS": str(d / "configs")}):
                items = json.loads(run("plymouth", FIXTURES / "glow_mini", "--colours", "--json",
                                       "-o", d / "out"))
            self.assertEqual(sorted(p.name for p in d.iterdir()), [])   # no config, no output
        names = [c["name"] for it in items for c in it["colours"]]
        self.assertIn("throbber.white", names)      # the names -m accepts, with their group

    def test_names_are_accepted_by_map(self):
        theme = FIXTURES / "glow_mini"
        listed = json.loads(run("plymouth", theme, "--colours", "--json"))
        for name in [c["name"] for it in listed for c in it["colours"]]:
            items = json.loads(run("plymouth", theme, "--colours", "--json", "-m", f"{name}=maroon"))
            targets = {c["name"]: c["target"] for it in items for c in it["colours"]}
            self.assertEqual(targets[name], "maroon")

    def test_lut_has_no_source_colours(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            parse(["lut", "--colours"])

    def test_json_needs_colours(self):
        with self.assertRaises(SystemExit) as e:
            parse(["image", "x.png", "--json"])
        self.assertIn("--colours", str(e.exception))


if __name__ == "__main__":
    unittest.main()
