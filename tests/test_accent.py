"""When the accent passed with -a has no effect, the command says so (and only then)."""
import contextlib
import io
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.dont_write_bytecode = True

from catppuccinizer.cli import parse  # noqa: E402
from catppuccinizer.core import recolor  # noqa: E402
from catppuccinizer.core.mapping import NO_ACCENT, note_accent_ignored  # noqa: E402


def printed(fn, *args, **kw):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        fn(*args, **kw)
    return out.getvalue()


class AccentNotes(unittest.TestCase):
    def test_accent_given(self):
        self.assertTrue(parse(["image", "x.png", "-a", "peach"]).accent_given)
        self.assertFalse(parse(["image", "x.png"]).accent_given)       # default accent

    def test_reason(self):
        keys_accent = {"colors": {"blue": {"source": "#0000ff", "target": "accent"}}}
        keys_plain = {"colors": {"blue": {"source": "#0000ff", "target": "sky"}}}
        self.assertEqual(recolor.accent_ignored_reason("lut", None), "by the lut method")
        self.assertEqual(recolor.accent_ignored_reason("lutgen", None), "by the lutgen method")
        self.assertIsNone(recolor.accent_ignored_reason("keys", keys_accent))
        self.assertEqual(recolor.accent_ignored_reason("keys", keys_plain), NO_ACCENT)

    def test_note_only_when_asked(self):
        asked = parse(["image", "x.png", "-a", "peach"])
        self.assertIn("note: accent ignored by the lut method",
                      printed(note_accent_ignored, asked, "by the lut method"))
        self.assertEqual(printed(note_accent_ignored, parse(["image", "x.png"]), "by the lut method"), "")
        self.assertIn("accent ignored by the lut target",
                      printed(parse, ["lut", "-a", "peach", "--format", "cube"]))


if __name__ == "__main__":
    unittest.main()
