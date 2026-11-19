"""GUI: forms built from the argparse subparsers, command lines, access control, a run."""
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
        self.assertEqual(kinds["lutgen_algo"]["when"], {"method": "lutgen"})
        plymouth = next(t for t in s["targets"] if t["name"] == "plymouth")
        self.assertTrue(plymouth["has_sources"])
        self.assertEqual({o["dest"]: o["kind"] for o in plymouth["options"]}["test"], "optional")

    def test_command_line(self):
        opts = self.app.options["image"]
        argv = build_argv("image", {"images": ["a.png"], "flavor": ["latte", "mocha"],
                                    "method": "auto", "keep_lum": 0.7, "preview": True}, opts)
        # sources first, defaults left out, several flavours not swallowing the source
        self.assertEqual(argv, ["image", "a.png", "-f", "latte", "mocha", "--preview",
                                "--keep-lum", "0.7"])
        argv = build_argv("plymouth", {"test": True}, self.app.options["plymouth"])
        self.assertEqual(argv, ["plymouth", "--test"])
        argv = build_argv("plymouth", {"test": 5}, self.app.options["plymouth"])
        self.assertEqual(argv, ["plymouth", "--test", "5"])

    def test_errors_are_the_cli_ones(self):
        r = self.call("/api/command", {"target": "image", "values": {}})
        self.assertIn("required", r["error"])
        r = self.call("/api/command", {"target": "lut", "values": {"method": "keys"}})
        self.assertEqual(r["error"], "lut: --method must be lut or lutgen")
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
            self.assertTrue(names[0].startswith("flat-catppuccin-mocha"), names)
            self.assertTrue(state["outputs"][0]["preview"])


if __name__ == "__main__":
    unittest.main()
