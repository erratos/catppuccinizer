"""Regression tests: every target is run on small fixtures and the outputs
(decoded pixels, text files) are compared with tests/golden.json.

    python3 -m unittest discover -s tests          # check
    python3 tests/test_regression.py --update      # accept the current outputs
"""
import contextlib
import hashlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageSequence

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
FIXTURES = HERE / "fixtures"
GOLDEN = HERE / "golden.json"
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True

from catppuccinizer.targets import limine  # noqa: E402

# the tests write limine.conf files of their own: never enroll this machine's Limine
# (limine-enroll-config when /etc/default/limine turns config enrollment on); every
# test module that runs Limine's steps imports this one
limine.ENROLL_CONFS = ()


# ------------------------------------------------------------ synthetic inputs
def make_images(d):
    rng = np.random.default_rng(1)
    d.mkdir(parents=True, exist_ok=True)
    # flat line art: two colours on a plain navy background
    im = Image.new("RGB", (320, 180), (8, 14, 40))
    dr = ImageDraw.Draw(im)
    for k in range(12):
        dr.ellipse([20 + k * 6, 10 + k * 5, 300 - k * 6, 170 - k * 5],
                   outline=(60, 220, 255) if k % 3 else (255, 70, 140), width=2)
    im.save(d / "flat.png")
    # photo-like gradient with noise
    y = np.linspace(0, 1, 180)[:, None, None]
    grad = (1 - y) * np.array([40, 20, 90]) + y * np.array([255, 160, 60])
    arr = np.broadcast_to(grad, (180, 320, 3)) + rng.normal(0, 6, (180, 320, 3))
    Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8)).save(d / "photo.jpg", quality=95)
    # blurred blobs (must go to the LUT)
    im = Image.new("RGB", (320, 180), (17, 26, 46))
    dr = ImageDraw.Draw(im)
    dr.ellipse([20, 0, 140, 90], fill=(120, 60, 160))
    dr.ellipse([150, 10, 280, 100], fill=(60, 90, 200))
    im.filter(ImageFilter.GaussianBlur(30)).save(d / "blobs.png")
    # transparent logo
    im = Image.new("RGBA", (96, 96), (0, 0, 0, 0))
    dr = ImageDraw.Draw(im)
    dr.ellipse([8, 8, 88, 88], fill=(255, 255, 255, 255))
    dr.ellipse([30, 30, 66, 66], fill=(23, 147, 209, 255))
    im.save(d / "logo.png")
    # tiny logo on a big plain background: still flat art (keys), not the LUT
    im = Image.new("RGB", (320, 180), (0, 0, 0))
    ImageDraw.Draw(im).ellipse([150, 80, 162, 92], fill=(232, 232, 232))
    im.save(d / "speck.png")
    # vector logo: stays an SVG, only the colours written in it change
    (d / "mark.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
        '<linearGradient id="g"><stop stop-color="#0cf" offset="0"/>'
        '<stop stop-color="#00aa88" stop-opacity="0" offset="1"/></linearGradient>'
        '<rect width="10" height="10" fill="#fff"/>'
        '<circle cx="5" cy="5" r="4" style="fill:#e0306a;stroke:#0cf"/>'
        '<circle cx="5" cy="5" r="2" fill="url(#g)"/></svg>\n')


def make_splash(d):
    s = d / "contents/splash"
    (s / "images").mkdir(parents=True)
    (d / "metadata.json").write_text(json.dumps(
        {"KPackageStructure": "Plasma/LookAndFeel", "KPlugin": {"Id": "test.splash", "Name": "Test Splash"}}))
    (s / "Splash.qml").write_text(
        'import QtQuick 2.5\nRectangle {\n  color: "black"\n'
        '  Text { color: "#eff0f1"; text: "hi" }\n'
        '  Rectangle { color: "#803daee9" }\n'
        '  Rectangle { color: Qt.rgba(0.2, 0.2, 0.25, 0.5) }\n'
        '  Image { source: "images/logo.svg" }\n}\n')
    (s / "images/logo.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10">'
        '<style>.ColorScheme-Highlight { color:#3daee9; }</style>'
        '<rect fill="#3daee9" stroke="#31363b" width="5" height="5"/>'
        '<circle style="fill:#da4453;stroke:white" r="2"/>'
        '<use href="#abc123"/></svg>')
    frames = []
    for k in range(3):
        im = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        ImageDraw.Draw(im).ellipse([8 + k * 4, 8, 40 + k * 4, 40], fill=(255, 255, 255, 255))
        frames.append(im)
    frames[0].save(s / "images/spin.gif", save_all=True, append_images=frames[1:],
                   duration=40, loop=0, disposal=2)
    Image.new("RGB", (64, 36), (40, 60, 90)).save(s / "images/bg.png")
    # animated WebP: every frame must survive (it used to be saved as one still)
    frames = []
    for k in range(4):
        im = Image.new("RGB", (64, 36), (0, 0, 0))
        ImageDraw.Draw(im).rectangle([4 + k * 10, 8, 14 + k * 10, 28], fill=(120, 240, 100))
        frames.append(im)
    frames[0].save(s / "images/rain.webp", save_all=True, append_images=frames[1:],
                   duration=33, loop=0, lossless=True)
    # preview = a glowing still of that animation: alone it would go to the LUT
    # (which ignores -m); it must take the animation's colours instead
    (d / "contents/previews").mkdir(parents=True)
    frames[1].filter(ImageFilter.GaussianBlur(8)).save(d / "contents/previews/splash.png")


GRUB_THEME_TXT = """# GRUB theme for tests
desktop-image: "background.png"
desktop-color: "#0b1020"
title-text: ""
+ boot_menu {
  left = 20%
  width = 60%
  item_color = "#c0c8d8"
  selected_item_color = "white"
  selected_item_pixmap_style = "select_*.png"
}
+ label { id = "__timeout__" text = "Booting in %d seconds" color = "#3daee9" }
+ progress_bar { id = "__timeout__" fg_color = "#3daee9" bg_color = "#1b2030" }
"""


def make_grub(d):
    """A GRUB theme: theme.txt, a photo-like background, a flat highlight box, an
    icon, a font (copied as it is)."""
    (d / "icons").mkdir(parents=True)
    (d / "theme.txt").write_text(GRUB_THEME_TXT)
    y = np.linspace(0, 1, 90)[:, None, None]
    grad = (1 - y) * np.array([20, 30, 70]) + y * np.array([200, 120, 60])
    arr = np.broadcast_to(grad, (90, 160, 3)) + np.random.default_rng(2).normal(0, 5, (90, 160, 3))
    Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8)).save(d / "background.png")
    im = Image.new("RGBA", (12, 12), (0, 0, 0, 0))
    ImageDraw.Draw(im).rectangle([1, 1, 10, 10], outline=(61, 174, 233, 255), width=2)
    im.save(d / "select_c.png")
    im = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
    ImageDraw.Draw(im).ellipse([2, 2, 30, 30], fill=(23, 147, 209, 255))
    ImageDraw.Draw(im).ellipse([11, 11, 21, 21], fill=(255, 255, 255, 255))
    im.save(d / "icons/arch.png")
    (d / "unifont.pf2").write_bytes(b"FILE\x00\x00\x00\x04PFF2")


LIMINE_CONF = """timeout: 3
wallpaper: boot():/limine-splash.png
wallpaper_style: centered
interface_branding: Test
term_palette: 000000;aa0000;00aa00;aa5500;0000aa;aa00aa;00aaaa;aaaaaa

/+Linux
    //linux
        protocol: linux
        path: boot():/vmlinuz#abc
"""


# ------------------------------------------------------------------- hashing
def digest(path, tmp):
    if path.suffix.lower() == ".webp":
        # lossy: the exact pixels depend on the libwebp version, so hash the frame
        # count and each frame's rounded mean colour instead
        with Image.open(path) as im:
            means = [tuple(int(v) // 8 for v in np.asarray(fr.convert("RGBA"), np.float32)
                           .reshape(-1, 4).mean(0)) for fr in ImageSequence.Iterator(im)]
            return hashlib.sha256(f"{im.size}{means}".encode()).hexdigest()[:16]
    if path.suffix.lower() in (".png", ".jpg", ".jpeg", ".gif"):
        with Image.open(path) as im:
            h = hashlib.sha256(f"{im.size}".encode())
            for fr in ImageSequence.Iterator(im):
                h.update(fr.convert("RGBA").tobytes())
        return h.hexdigest()[:16]
    data = path.read_bytes()
    if path.suffix.lower() == ".svgz":
        import gzip
        data = gzip.decompress(data)
    text = data.decode(errors="replace").replace(str(tmp), "<tmp>")
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def tree(d, tmp, skip=(".bak",)):
    return {str(p.relative_to(d)): digest(p, tmp) for p in sorted(d.rglob("*"))
            if p.is_file() and not any(s in p.name for s in skip)}


def cli(*argv):
    from catppuccinizer.cli import main
    with contextlib.redirect_stdout(io.StringIO()):
        main([str(a) for a in argv])


def colours(tmp, *argv):
    """--colours --json output, temporary paths replaced by <tmp>."""
    from catppuccinizer.cli import main
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
        main([str(a) for a in argv] + ["--colours", "--json"])
    return json.loads(out.getvalue().replace(str(tmp), "<tmp>"))


# --------------------------------------------------------------------- cases
def has_lutgen():
    from catppuccinizer.core import lutgen
    try:
        return bool(lutgen.binary())
    except SystemExit:
        return False


HAS_LUTGEN = has_lutgen()


def run_all():
    tmp = Path(tempfile.mkdtemp(prefix="catppuccinizer-test-"))
    out = {}
    try:
        cli("plymouth", FIXTURES / "hexa_mini", "-f", "mocha", "macchiato", "-a", "mauve",
            "-o", tmp / "plymouth")
        cli("plymouth", FIXTURES / "glow_mini", "-f", "latte", "-a", "teal", "mauve",
            "-m", "throbber.white=accent", "-o", tmp / "plymouth")
        out["plymouth"] = tree(tmp / "plymouth", tmp)

        make_images(tmp / "img")
        cli("image", tmp / "img", "-f", "mocha", "frappe", "-a", "mauve", "-o", tmp / "image")
        cli("image", tmp / "img/flat.png", "-a", "mauve", "-m", "pink=peach", "-s", "mapped", "-o", tmp / "image")
        cli("image", tmp / "img/mark.svg", "-a", "mauve", "-m", "blue=lavender", "-s", "mapped", "-o", tmp / "image")
        out["image"] = tree(tmp / "image", tmp)

        cli("lut", "-f", "mocha", "latte", "--hald-level", "4", "--cube-size", "9", "-o", tmp / "lut")
        cli("lut", "-f", "frappe", "--format", "cube", "--cube-size", "5", "--keep-lum", "0.8",
            "-s", "soft", "-o", tmp / "lut")
        out["lut"] = tree(tmp / "lut", tmp)

        if HAS_LUTGEN:     # external binary: only checked where it is installed
            for algo in ("blur", "rbf", "shepard", "nearest"):
                cli("image", tmp / "img/photo.jpg", "--method", "lutgen", "--lutgen-algo", algo,
                    "--lutgen-level", "6", "-s", algo, "-o", tmp / "lutgen")
            cli("image", tmp / "img/logo.png", "--method", "lutgen", "--lutgen-preserve",
                "--lutgen-lum", "0.5", "--lutgen-level", "6", "-o", tmp / "lutgen")
            cli("lut", "--method", "lutgen", "--lutgen-algo", "rbf", "--lutgen-shape", "64",
                "--lutgen-level", "4", "--hald-level", "4", "--cube-size", "5", "-o", tmp / "lutgen")
            out["lutgen"] = tree(tmp / "lutgen", tmp)

        esp = tmp / "esp"
        esp.mkdir()
        (esp / "limine.conf").write_text(LIMINE_CONF)
        shutil.copy(tmp / "img/blobs.png", esp / "limine-splash.png")
        steps = {}
        cli("limine", "-a", "lavender", "--apply", "--esp", esp, "-o", tmp / "limine")
        steps["keep"] = (esp / "limine.conf").read_text()
        cli("limine", "-a", "lavender", "--wallpaper", "current", "--apply", "--esp", esp,
            "-o", tmp / "limine")
        # several accents, a LUT wallpaper: rendered once, the same file in each folder
        cli("limine", "-a", "lavender", "peach", "--wallpaper", tmp / "img/photo.jpg",
            "-o", tmp / "limine-accents")
        out["limine_accents"] = tree(tmp / "limine-accents", tmp)
        steps["recolor"] = (esp / "limine.conf").read_text()
        steps["recolor_files"] = tree(esp, tmp)
        cli("limine", "--restore", "--esp", esp)
        steps["removed_is_original"] = (esp / "limine.conf").read_text() == LIMINE_CONF
        out["limine"] = {k: (hashlib.sha256(v.encode()).hexdigest()[:16] if isinstance(v, str) else v)
                         for k, v in steps.items()}
        out["limine_out"] = tree(tmp / "limine", tmp)

        make_splash(tmp / "splash-src")
        cli("ksplash", tmp / "splash-src", "-a", "peach", "mauve", "-o", tmp / "ksplash")
        cli("ksplash", tmp / "splash-src", "-a", "mauve", "-m", "green=lavender", "-s", "lav", "-o", tmp / "ksplash")
        out["ksplash"] = tree(tmp / "ksplash", tmp)
        make_grub(tmp / "grub-src")
        cli("grub", tmp / "grub-src", "-a", "mauve", "peach", "-o", tmp / "grub")
        cli("grub", tmp / "grub-src" / "theme.txt", "-a", "mauve", "icons=peach", "-m", "blue=sapphire",
            "-s", "mapped", "-o", tmp / "grub")
        out["grub"] = tree(tmp / "grub", tmp)
        out["colours"] = {
            "image": colours(tmp, "image", tmp / "img"),
            "image_mapped": colours(tmp, "image", tmp / "img/flat.png", "-m", "pink=peach"),
            "plymouth": colours(tmp, "plymouth", FIXTURES / "glow_mini", "-m", "throbber.white=accent"),
            "ksplash": colours(tmp, "ksplash", tmp / "splash-src", "-m", "green=lavender"),
            "limine": colours(tmp, "limine", "--wallpaper", tmp / "img/speck.png"),
            "grub": colours(tmp, "grub", tmp / "grub-src"),
        }
        pv = next((tmp / "ksplash").glob("*-lav/contents/previews/splash.png"))
        r, g, b = np.asarray(Image.open(pv).convert("RGB"), np.int32)[18, 19]   # centre of the bar
        out["ksplash_preview_lavender"] = bool(b > g > r)    # lavender, not a LUT green
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return out


class Regression(unittest.TestCase):
    maxDiff = None

    @classmethod
    def setUpClass(cls):
        cls.result = run_all()
        cls.golden = json.loads(GOLDEN.read_text())

    def check(self, key):
        self.assertEqual(self.result[key], self.golden[key])

    def test_plymouth(self):
        self.check("plymouth")

    def test_image(self):
        self.check("image")

    def test_lut(self):
        self.check("lut")

    def test_colours(self):
        self.check("colours")

    @unittest.skipUnless(HAS_LUTGEN, "lutgen is not installed")
    def test_lutgen(self):
        self.check("lutgen")

    def test_lutgen_options(self):
        from catppuccinizer.cli import main
        with self.assertRaises(SystemExit) as e:
            main(["lut", "--method", "lutgen", "--lutgen-algo", "rbf", "--lutgen-radius", "3"])
        self.assertIn("does not apply", str(e.exception))

    def test_limine(self):
        self.check("limine")
        self.check("limine_out")
        self.assertTrue(self.result["limine"]["removed_is_original"])

    def test_grub(self):
        self.check("grub")         # a TOML target (core.declarative)

    def test_ksplash(self):
        self.check("ksplash")      # the rain.webp digest includes its frame count
        self.assertTrue(self.result["ksplash_preview_lavender"])   # -m reaches the preview


if __name__ == "__main__":
    if "--update" in sys.argv:
        new = run_all()
        if not HAS_LUTGEN and GOLDEN.exists():      # keep the lutgen outputs of a machine that has it
            old = json.loads(GOLDEN.read_text())
            if "lutgen" in old:
                new["lutgen"] = old["lutgen"]
        GOLDEN.write_text(json.dumps(new, indent=1, sort_keys=True) + "\n")
        print(f"updated {GOLDEN}")
    else:
        unittest.main()
