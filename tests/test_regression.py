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
    if path.suffix.lower() in (".png", ".jpg", ".jpeg", ".gif", ".webp"):
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


# --------------------------------------------------------------------- cases
def run_all():
    tmp = Path(tempfile.mkdtemp(prefix="catppuccinizer-test-"))
    os.environ["CATPPUCCINIZER_CONFIGS"] = str(tmp / "configs")
    out = {}
    try:
        cli("plymouth", FIXTURES / "hexa_mini", "-f", "mocha", "macchiato", "-a", "mauve",
            "-o", tmp / "plymouth")
        cli("plymouth", FIXTURES / "glow_mini", "-f", "latte", "-a", "teal",
            "-m", "throbber.white=accent", "-o", tmp / "plymouth")
        out["plymouth"] = tree(tmp / "plymouth", tmp)
        out["configs"] = tree(tmp / "configs", tmp)

        make_images(tmp / "img")
        cli("image", tmp / "img", "-f", "mocha", "frappe", "-o", tmp / "image")
        cli("image", tmp / "img/flat.png", "-m", "pink=peach", "-s", "mapped", "-o", tmp / "image")
        out["image"] = tree(tmp / "image", tmp)

        esp = tmp / "esp"
        esp.mkdir()
        (esp / "limine.conf").write_text(LIMINE_CONF)
        shutil.copy(tmp / "img/blobs.png", esp / "limine-splash.png")
        steps = {}
        cli("limine", "-a", "lavender", "--apply", "--esp", esp, "-o", tmp / "limine")
        steps["keep"] = (esp / "limine.conf").read_text()
        cli("limine", "-a", "lavender", "--recolor-wallpaper", "--apply", "--esp", esp,
            "-o", tmp / "limine")
        steps["recolor"] = (esp / "limine.conf").read_text()
        steps["recolor_files"] = tree(esp, tmp)
        cli("limine", "--remove", "--esp", esp)
        steps["removed_is_original"] = (esp / "limine.conf").read_text() == LIMINE_CONF
        out["limine"] = {k: (hashlib.sha256(v.encode()).hexdigest()[:16] if isinstance(v, str) else v)
                         for k, v in steps.items()}
        out["limine_out"] = tree(tmp / "limine", tmp)

        make_splash(tmp / "splash-src")
        cli("ksplash", tmp / "splash-src", "-a", "peach", "-o", tmp / "ksplash")
        out["ksplash"] = tree(tmp / "ksplash", tmp)
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
        self.check("configs")

    def test_image(self):
        self.check("image")

    def test_limine(self):
        self.check("limine")
        self.check("limine_out")
        self.assertTrue(self.result["limine"]["removed_is_original"])

    def test_ksplash(self):
        self.check("ksplash")


if __name__ == "__main__":
    if "--update" in sys.argv:
        GOLDEN.write_text(json.dumps(run_all(), indent=1, sort_keys=True) + "\n")
        print(f"updated {GOLDEN}")
    else:
        unittest.main()
