"""GUI: forms built from the declared options, command lines, access control, a run,
the live preview."""
import base64
import io
import json
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True

from catppuccinizer.gui import App, build_argv, make_handler  # noqa: E402


class Gui(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = App()
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(cls.app))
        cls.app.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def call(self, path, body=None, token=True, host=None):
        req = urllib.request.Request(f"http://127.0.0.1:{self.app.port}{path}",
                                     data=None if body is None else json.dumps(body).encode())
        if token:
            req.add_header("X-Token", self.app.token)
        if host:
            req.add_header("Host", host)
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())

    def test_schema_covers_every_target(self):
        s = self.call("/api/schema")
        names = [t["name"] for t in s["targets"]]
        for name in ("plymouth", "image", "limine", "ksplash", "lut"):
            self.assertIn(name, names)
        image = next(t for t in s["targets"] if t["name"] == "image")
        kinds = {o["dest"]: o for o in image["options"]}
        self.assertEqual(kinds["images"]["role"], "source")
        self.assertEqual(kinds["method"]["kind"], "choice")
        self.assertEqual(kinds["keep_lum"]["range"], [0.0, 1.0])
        self.assertEqual(kinds["lutgen_algo"]["when"], {"method": ["lutgen"]})
        self.assertEqual(kinds["lutgen_radius"]["when"], {"method": ["lutgen"], "lutgen_algo": ["blur"]})
        self.assertEqual(kinds["map"]["when"], {"analysis.remappable": [True]})
        self.assertNotIn("colours", kinds)               # lists, does not run: not in the form
        self.assertTrue(image["has_colours"])
        self.assertIsNone(image["accent_also"])          # lut: the accents are dimmed
        limine = next(t for t in s["targets"] if t["name"] == "limine")
        self.assertTrue(limine["accent_also"])           # the menu still uses it
        lim = {o["dest"]: o for o in limine["options"]}
        self.assertEqual((lim["apply"]["sudo"], lim["apply"]["stage"]), ("run", "apply"))
        self.assertEqual(lim["wallpaper"]["role"], "source")
        self.assertEqual(lim["esp"]["accept"], "dir")
        self.assertEqual(s["no_accent_methods"], ["lut", "lutgen"])
        plymouth = next(t for t in s["targets"] if t["name"] == "plymouth")
        self.assertTrue(plymouth["has_sources"])
        ply = {o["dest"]: o for o in plymouth["options"]}
        self.assertEqual(ply["test"]["kind"], "optional")
        self.assertEqual((ply["install"]["sudo"], ply["install"]["role"]), ("run", "step"))
        self.assertEqual(ply["dry_run"]["role"], "common")
        self.assertNotIn("list", ply)                           # the catalogue does it
        self.assertNotIn("detect", ply)                         # --colours, for every target
        self.assertNotIn("bar", ply)                            # -a bar=ACCENT (core.parts)
        self.assertEqual((ply["preview"]["role"], ply["preview_animation"]["role"]),
                         ("preview", "preview"))                 # buttons next to Build
        self.assertEqual(kinds["preview"]["role"], "preview")
        self.assertNotIn("preview_animation", kinds)            # a picture does not move
        lut = next(t for t in s["targets"] if t["name"] == "lut")
        self.assertFalse(lut["has_colours"])
        self.assertEqual({o["dest"]: o for o in lut["options"]}["method"]["choices"], ["lut", "lutgen"])
        self.assertNotIn("boot_delay", [o["dest"] for o in plymouth["options"]])

    def test_command_line(self):
        opts = self.app.options["image"]
        argv = build_argv("image", {"images": ["a.png"], "flavor": ["latte", "mocha"],
                                    "method": "auto", "keep_lum": 0.7, "preview": True}, opts)
        # sources first, defaults left out, several flavours not swallowing the source
        self.assertEqual(argv, ["image", "a.png", "-f", "latte", "mocha", "--preview",
                                "--keep-lum", "0.7"])
        # an option whose `when` is not met is left out (--lutgen-radius without lutgen)
        argv = build_argv("image", {"images": ["a.png"], "lutgen_radius": 4}, opts)
        self.assertEqual(argv, ["image", "a.png"])
        argv = build_argv("image", {"images": ["a.png"], "method": "lutgen", "lutgen_radius": 4}, opts)
        self.assertEqual(argv, ["image", "a.png", "--method", "lutgen", "--lutgen-radius", "4"])
        argv = build_argv("plymouth", {"test": True}, self.app.options["plymouth"])
        self.assertEqual(argv, ["plymouth", "--test"])
        argv = build_argv("plymouth", {"test": 5}, self.app.options["plymouth"])
        self.assertEqual(argv, ["plymouth", "--test", "5"])

    def test_options_that_do_not_count_are_left_out(self):
        opts = self.app.options["limine"]
        self.assertEqual(build_argv("limine", {"style": "tiled", "keep_lum": 0.3}, opts), ["limine"])
        self.assertEqual(build_argv("limine", {"style": "tiled", "wallpaper": "current"}, opts),
                         ["limine", "--wallpaper", "current", "--style", "tiled"])
        lim = {o["dest"]: o for o in opts}
        self.assertEqual(lim["style"]["needs"], ["wallpaper"])
        self.assertIn("menu colours", lim["wallpaper"]["empty"])

    def test_errors_are_the_cli_ones(self):
        r = self.call("/api/command", {"target": "image", "values": {}})
        self.assertIn("required", r["error"])
        r = self.call("/api/command", {"target": "lut", "values": {"method": "keys"}})
        self.assertIn("invalid choice: 'keys'", r["error"])
        r = self.call("/api/command", {"target": "limine", "values": {"apply": True}, "sudo": True})
        self.assertIn("single flavour and a single accent", r["error"])   # all 14 by default
        r = self.call("/api/command", {"target": "limine", "values": {"apply": True, "accent": ["mauve"]},
                                       "sudo": True})
        self.assertIsNone(r["error"])
        self.assertEqual(r["command"], "sudo catppuccinize limine -a mauve --apply")

    def test_colours_before_a_run(self):
        with tempfile.TemporaryDirectory() as d:
            im = Image.new("RGB", (160, 90), (8, 14, 40))
            ImageDraw.Draw(im).ellipse([20, 10, 140, 80], outline=(60, 220, 255), width=3)
            im.save(Path(d) / "flat.png")
            values = {"images": [str(Path(d) / "flat.png")], "flavor": ["latte"],
                      "map": ["not-a-name=red"]}       # -m is left out: no error while typing
            r = self.call("/api/colours", {"target": "image", "values": values})
            self.assertIsNone(r.get("error"), r)
            self.assertEqual(r["items"][0]["method"], "keys")
            self.assertTrue(r["items"][0]["colours"])
            self.assertEqual(r["facts"], {"remappable": True})
            self.assertNotIn("-m", r["command"])
            r = self.call("/api/colours", {"target": "image", "values": {**values, "method": "lut"}})
            self.assertEqual(r["facts"], {"remappable": False})   # the editor is hidden
        self.assertIn("error", self.call("/api/colours", {"target": "lut", "values": {}}))
        self.assertIn("required", self.call("/api/colours", {"target": "image", "values": {}})["error"])

    def test_names_before_a_run(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            Image.new("RGB", (64, 36), (8, 14, 40)).save(d / "flat.png")
            (d / "out").mkdir()
            (d / "out/catppuccin-latte-flat.png").write_bytes(b"x")       # replaced
            r = self.call("/api/names", {"target": "image", "values": {
                "images": [str(d / "flat.png")], "out": str(d / "out"), "flavor": ["latte", "mocha"],
                "install": True}})                                       # steps left out
            self.assertNotIn("error", r)
            self.assertEqual(r["out"], str(d / "out"))
            self.assertEqual([(Path(it["path"]).name, it["exists"]) for it in r["items"]],
                             [("catppuccin-latte-flat.png", True), ("catppuccin-mocha-flat.png", False)])
            self.assertIn("--names --json", r["command"])
            self.assertEqual(sorted(p.name for p in (d / "out").iterdir()), ["catppuccin-latte-flat.png"])
        self.assertIn("error", self.call("/api/names", {"target": "nope"}))
        self.assertIn("required", self.call("/api/names", {"target": "image", "values": {}})["error"])
        self.assertTrue(next(t for t in self.call("/api/schema")["targets"] if t["name"] == "lut")["has_outputs"])

    def test_live_preview(self):
        """/api/live: the source recoloured in the server's process, on a reduced copy;
        the analysis of the full image is kept, so a slider only renders again."""
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            im = Image.new("RGB", (1600, 900), (8, 14, 40))
            ImageDraw.Draw(im).ellipse([200, 100, 1400, 800], outline=(60, 220, 255), width=24)
            im.save(d / "flat.png")
            Image.new("RGB", (64, 64), (200, 40, 40)).save(d / "b.jpg")
            (d / "c.svg").write_text("<svg/>")
            values = {"images": [str(d / "flat.png")], "accent": ["mauve"]}
            r = self.call("/api/live", {"target": "image", "values": values})
            self.assertNotIn("error", r)
            self.assertEqual((r["method"], r["flavor"], r["accent"], r["analysed"]), ("keys", "mocha", "mauve", True))
            self.assertEqual((r["width"], r["height"]), (512, 288))
            self.assertIsNone(r["accent_ignored"])
            png = base64.b64decode(r["image"].split(",", 1)[1])
            with Image.open(io.BytesIO(png)) as out:
                self.assertEqual(out.size, (512, 288))
                # its one colour goes to the accent: the ring is mauve
                ring = out.convert("RGB").getpixel((256, 288 * 100 // 900 + 2))
                self.assertLessEqual(max(abs(x - y) for x, y in zip(ring, (203, 166, 247))), 3, ring)
            # flavour, accent, -m (even a name being typed): rendered again, not analysed
            for extra in ({"flavor": ["latte"]}, {"accent": ["red"]}, {"map": ["no-such=red"]}):
                r = self.call("/api/live", {"target": "image", "values": {**values, **extra}})
                self.assertFalse(r["analysed"], (extra, r))
            # an option of the analysis: analysed again, then kept too
            sep = {**values, "separation": 0.8}
            self.assertTrue(self.call("/api/live", {"target": "image", "values": sep})["analysed"])
            self.assertFalse(self.call("/api/live", {"target": "image", "values": sep})["analysed"])
            r = self.call("/api/live", {"target": "image", "values": {**values, "method": "lut", "keep_lum": 0.2}})
            self.assertEqual((r["method"], r["analysed"]), ("lut", False))
            self.assertIn("lut method", r["accent_ignored"])
            # a folder: its still images, one picked by the page (the first otherwise)
            folder = {"images": [str(d)]}
            r = self.call("/api/live", {"target": "image", "values": folder})
            self.assertEqual(r["images"], [str(d / "b.jpg"), str(d / "flat.png")])
            self.assertEqual(r["path"], str(d / "b.jpg"))
            r = self.call("/api/live", {"target": "image", "values": folder, "image": str(d / "flat.png")})
            self.assertEqual(r["path"], str(d / "flat.png"))
            r = self.call("/api/live", {"target": "image", "values": folder, "image": "/etc/passwd"})
            self.assertEqual(r["path"], str(d / "b.jpg"))        # not one of the source's images
            self.assertEqual(self.call("/api/live", {"target": "limine", "values": {
                "wallpaper": str(d / "b.jpg")}})["method"], "lut")
            for body in ({"target": "image", "values": {"images": [str(d / "c.svg")]}},
                         {"target": "image", "values": {"images": [str(d / "nope.png")]}},
                         {"target": "image", "values": {}},                 # required, as Build says
                         {"target": "image", "values": {**values, "keep_lum": 3}},
                         {"target": "plymouth", "values": {}}, {"target": "nope"}):
                with self.subTest(body=body):
                    self.assertTrue(self.call("/api/live", body).get("error"))

    def test_illustrations(self):
        """/api/asset serves the illustrations the options declare, nothing else."""
        url = f"http://127.0.0.1:{self.app.port}/api/asset?name="
        req = urllib.request.Request(url + "options-method.jpg", headers={"X-Token": self.app.token})
        with urllib.request.urlopen(req, timeout=30) as r:
            self.assertEqual(r.headers["Content-Type"], "image/jpeg")
            self.assertEqual(r.read()[:2], b"\xff\xd8")
        for name in ("../../pyproject.toml", "demo-glow.png", "options-nope.jpg", ""):
            with self.subTest(name=name), self.assertRaises(urllib.error.HTTPError) as e:
                urllib.request.urlopen(urllib.request.Request(
                    url + urllib.request.quote(name), headers={"X-Token": self.app.token}), timeout=30)
            self.assertEqual(e.exception.code, 404)
            e.exception.close()
        with self.assertRaises(urllib.error.HTTPError) as e:              # no token
            urllib.request.urlopen(url + "options-method.jpg", timeout=30)
        self.assertEqual(e.exception.code, 403)
        e.exception.close()

    def test_access_control(self):
        with self.assertRaises(urllib.error.HTTPError) as e:
            self.call("/api/schema", token=False)
        self.assertEqual(e.exception.code, 403)
        with self.assertRaises(urllib.error.HTTPError) as e:     # DNS rebinding
            self.call("/api/schema", host=f"evil.example:{self.app.port}")
        self.assertEqual(e.exception.code, 403)

    def test_run_lists_outputs(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            im = Image.new("RGB", (160, 90), (8, 14, 40))
            ImageDraw.Draw(im).ellipse([20, 10, 140, 80], outline=(60, 220, 255), width=3)
            im.save(d / "flat.png")
            r = self.call("/api/run", {"target": "image", "values": {
                "images": [str(d / "flat.png")], "out": str(d / "out"), "preview": True,
                "accent": ["mauve"]}})                  # its one colour goes to the accent
            self.assertIsNone(r["error"])
            for _ in range(300):
                state = self.call(f"/api/job?id={r['job']}")
                if state["done"]:
                    break
                time.sleep(0.1)
            self.assertEqual(state["code"], 0, "\n".join(state["lines"]))
            names = [o["name"] for o in state["outputs"]]
            self.assertEqual(len(names), 1)
            self.assertGreater(state["outputs"][0]["version"], 0)   # new file, new thumbnail URL
            self.assertTrue(names[0].startswith("catppuccin-mocha-flat"), names)
            self.assertTrue(state["outputs"][0]["preview"])


if __name__ == "__main__":
    unittest.main()
