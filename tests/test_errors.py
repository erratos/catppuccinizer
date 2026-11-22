"""User mistakes end with a one-line message, not a traceback."""
import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.dont_write_bytecode = True

from catppuccinizer.cli import main  # noqa: E402


def message(*argv):
    """The SystemExit text of a command (fails the test if it does not exit)."""
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        try:
            main([str(a) for a in argv])
        except SystemExit as e:
            return str(e.code)
    raise AssertionError(f"no error for {argv}")


class Errors(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="catppuccinizer-test-"))
        (self.tmp / "fake.png").write_text("not an image")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_unreadable_image(self):
        out = self.tmp / "out"
        self.assertIn("cannot identify image file", message("image", self.tmp / "fake.png", "-o", out))
        self.assertIn("cannot identify image file",
                      message("limine", "--wallpaper", self.tmp / "fake.png", "-o", out))

    def test_missing_files(self):
        self.assertIn("Not found", message("image", self.tmp / "nope.png"))
        self.assertIn("Not found", message("limine", "--wallpaper", self.tmp / "nope.png"))

    def test_unwritable_output(self):
        self.assertTrue(message("lut", "-o", "/proc/catppuccinizer-test").startswith("error: "))

    def test_option_ranges(self):
        self.assertEqual(message("lut", "--keep-lum", "5"), "--keep-lum must be between 0 and 1")
        self.assertEqual(message("lut", "--smooth", "0"), "--smooth must be between 0.01 and 0.5")
        self.assertEqual(message("lut", "--chroma", "0.5"), "--chroma must be between 0.02 and 0.3")
        self.assertEqual(message("lut", "--dark-fade", "-1"), "--dark-fade must be between 0 and 1.5")
        self.assertEqual(message("image", "x.png", "--auto-fit", "50"), "--auto-fit must be between 0 and 30")


if __name__ == "__main__":
    unittest.main()
