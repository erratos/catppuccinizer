"""GUI: forms built from the declared options, command lines, access control, a run."""
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
        self.assertEqual(s["lut_methods"], ["lut", "lutgen"])
        plymouth = next(t for t in s["targets"] if t["name"] == "plymouth")
        self.assertTrue(plymouth["has_sources"])
        ply = {o["dest"]: o for o in plymouth["options"]}
        self.assertEqual(ply["test"]["kind"], "optional")
        self.assertEqual((ply["install"]["sudo"], ply["install"]["role"]), ("run", "step"))
        self.assertEqual(ply["dry_run"]["role"], "common")
        self.assertEqual(ply["detect"]["role"], "action")       # a button, not a setting
        self.assertNotIn("list", ply)                           # the catalogue does it
        self.assertEqual(ply["bar"]["kind"], "colour")
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

    def test_errors_are_the_cli_ones(self):
        r = self.call("/api/command", {"target": "image", "values": {}})
        self.assertIn("required", r["error"])
        r = self.call("/api/command", {"target": "lut", "values": {"method": "keys"}})
        self.assertIn("invalid choice: 'keys'", r["error"])
        r = self.call("/api/command", {"target": "limine", "values": {"apply": True}, "sudo": True})
        self.assertIsNone(r["error"])
        self.assertEqual(r["command"], "sudo catppuccinize limine --apply")

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
                "images": [str(d / "flat.png")], "out": str(d / "out"), "preview": True}})
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
