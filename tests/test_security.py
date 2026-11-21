"""Security: names checked before any system path, copies that do not follow links
out of the source, atomic writes, pruned backups, commands without a shell
(docs/architecture.md, Security)."""
import contextlib
import http.client
import io
import json
import os
import stat
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
sys.dont_write_bytecode = True

from PIL import Image  # noqa: E402

from catppuccinizer import gui  # noqa: E402
from catppuccinizer.cli import main  # noqa: E402
from catppuccinizer.core import system as core_system  # noqa: E402
from catppuccinizer.core.naming import check_name  # noqa: E402
from catppuccinizer.core.system import (KEEP_BACKUPS, System, copy_folder, place,  # noqa: E402
                                        source_file, which)
from catppuccinizer.targets import limine  # noqa: E402
from test_regression import FIXTURES, LIMINE_CONF  # noqa: E402

BAD_NAMES = ["", ".", "..", "../etc", "a/b", "/etc", "-R", ".hidden", "a..b", "a b", "a\nb",
             "x" * 200, None, 3]


def quiet(fn, *args, **kw):
    with contextlib.redirect_stdout(io.StringIO()) as out:
        result = fn(*args, **kw)
    return result, out.getvalue()


class Tmp(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="catppuccinizer-test-"))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)


class Names(unittest.TestCase):
    def test_good_names(self):
        for name in ("catppuccin-mocha-glow", "org.kde.breeze.desktop", "bgrt", "KSplashQML",
                     "theme_2+x"):
            self.assertEqual(check_name(name), name)
            self.assertEqual(place("/usr/share/plymouth/themes", name).name, name)

    def test_bad_names(self):
        for name in BAD_NAMES:
            with self.subTest(name=name), self.assertRaises(SystemExit):
                place("/usr/share/plymouth/themes", name)


class Copies(Tmp):
    def make_source(self):
        src = self.tmp / "theme"
        (src / "sub").mkdir(parents=True)
        (src / "a.txt").write_text("a")
        (src / "sub/b.txt").write_text("b")
        (self.tmp / "secret").write_text("secret")
        (self.tmp / "outside").mkdir()
        (self.tmp / "outside/c.txt").write_text("c")
        (src / "inside-link").symlink_to("a.txt")                 # inside: copied as a file
        (src / "secret-link").symlink_to(self.tmp / "secret")     # out of the theme
        (src / "dotdot-link").symlink_to("../secret")
        (src / "dir-link").symlink_to(self.tmp / "outside")      # a folder: never entered
        (src / "broken").symlink_to(self.tmp / "nope")
        os.mkfifo(src / "fifo")                                   # not a regular file
        return src

    def test_source_file(self):
        src = self.make_source()
        self.assertEqual(source_file(src / "a.txt", src), (src / "a.txt").resolve())
        self.assertEqual(source_file(src / "inside-link", src), (src / "a.txt").resolve())
        for name in ("secret-link", "dotdot-link", "dir-link", "broken", "fifo", "sub", "missing"):
            self.assertIsNone(source_file(src / name, src), name)

    def test_copy_folder(self):
        src = self.make_source()
        skipped, out = quiet(copy_folder, src, self.tmp / "out", ignore=("*.qmlc",))
        dst = self.tmp / "out"
        self.assertEqual(sorted(str(p.relative_to(dst)) for p in dst.rglob("*")),
                         ["a.txt", "inside-link", "sub", "sub/b.txt"])
        self.assertFalse((dst / "inside-link").is_symlink())
        self.assertEqual((dst / "inside-link").read_text(), "a")
        self.assertEqual(sorted(p.name for p in skipped),
                         ["broken", "dir-link", "dotdot-link", "fifo", "secret-link"])
        self.assertIn("note: skipped", out)

    def test_install_copy(self):
        src = self.make_source()
        dst = self.tmp / "themes/x"
        dst.mkdir(parents=True)
        (dst / "old.txt").write_text("old")
        old = os.umask(0o077)               # rights are explicit, not the umask's
        try:
            quiet(System().copy_tree, src, dst)
        finally:
            os.umask(old)
        self.assertFalse((dst / "old.txt").exists())              # replaced, not merged
        self.assertFalse((dst / "secret-link").exists())
        self.assertEqual(stat.S_IMODE((dst / "a.txt").stat().st_mode), 0o644)   # not the umask
        self.assertEqual(stat.S_IMODE((dst / "sub").stat().st_mode), 0o755)
        self.assertEqual([p.name for p in dst.parent.iterdir()], ["x"])      # no temporary left

    def test_install_over_a_link(self):
        src = self.make_source()
        (self.tmp / "themes").mkdir()
        (self.tmp / "themes/x").symlink_to(self.tmp / "outside")
        quiet(System().copy_tree, src, self.tmp / "themes/x")
        self.assertFalse((self.tmp / "themes/x").is_symlink())
        self.assertEqual([p.name for p in (self.tmp / "outside").iterdir()], ["c.txt"])

    def test_remove_a_link(self):
        (self.tmp / "outside").mkdir()
        (self.tmp / "outside/c.txt").write_text("c")
        (self.tmp / "link").symlink_to(self.tmp / "outside")
        quiet(System().remove, self.tmp / "link")
        self.assertTrue((self.tmp / "outside/c.txt").exists())


class Writes(Tmp):
    def test_atomic_keeps_rights(self):
        f = self.tmp / "limine.conf"
        f.write_text("old")
        f.chmod(0o600)
        quiet(System().write_text, f, "new\r\nline\n")
        self.assertEqual(f.read_bytes(), b"new\r\nline\n")       # no newline translation
        self.assertEqual(stat.S_IMODE(f.stat().st_mode), 0o600)
        self.assertEqual([p.name for p in self.tmp.iterdir()], ["limine.conf"])

    def test_failed_write_leaves_the_file(self):
        f = self.tmp / "conf"
        f.write_text("old")
        real = os.replace

        def boom(*a):
            raise OSError("disk full")
        core_system.os.replace = boom
        try:
            with self.assertRaises(OSError):
                quiet(System().write_text, f, "new")
        finally:
            core_system.os.replace = real
        self.assertEqual(f.read_text(), "old")
        self.assertEqual([p.name for p in self.tmp.iterdir()], ["conf"])

    def test_backups_are_pruned(self):
        f = self.tmp / "limine.conf"
        f.write_text("0")
        s = System()
        for i in range(KEEP_BACKUPS + 3):
            quiet(s.write_text, f, str(i + 1), backup=True)
        baks = sorted(self.tmp.glob("limine.conf.*.bak"))
        self.assertEqual(len(baks), KEEP_BACKUPS)
        self.assertEqual([b.read_text() for b in baks], [str(i) for i in range(3, KEEP_BACKUPS + 3)])
        (self.tmp / "limine.conf.mine.bak").write_text("user's own")     # not ours: kept
        quiet(s.write_text, f, "x", backup=True)
        self.assertTrue((self.tmp / "limine.conf.mine.bak").exists())

    def test_state_must_be_an_object(self):
        (self.tmp / "s.json").write_text("[1]")
        with self.assertRaises(SystemExit):
            System.load_state(self.tmp / "s.json")


class Commands(Tmp):
    def test_which(self):
        self.assertEqual(which(sys.executable), sys.executable)
        self.assertIsNone(which("catppuccinizer-no-such-command"))
        self.assertTrue(os.path.isabs(which("sh")))

    def test_run_resolves_and_never_uses_a_shell(self):
        s = System(dry_run=True)
        quiet(s.run, ["sh", "-c", "x; rm -rf ~"])
        self.assertTrue(os.path.isabs(s.done[0][1][0]))           # an absolute path
        self.assertEqual(s.done[0][1][1:], ["-c", "x; rm -rf ~"])  # arguments untouched
        with self.assertRaises(SystemExit):
            quiet(System().run, ["catppuccinizer-no-such-command"])

    def test_no_shell_anywhere(self):
        root = HERE.parent / "catppuccinizer"
        for f in root.rglob("*.py"):
            text = f.read_text()
            self.assertNotIn("shell=True", text, f)
            self.assertNotIn("os.system(", text, f)
            self.assertNotIn("os.popen(", text, f)


class StateNames(Tmp):
    """Names read back from a state file are checked before restore uses them."""
    def setUp(self):
        super().setUp()
        os.environ["CATPPUCCINIZER_STATE"] = str(self.tmp)

    def tearDown(self):
        os.environ.pop("CATPPUCCINIZER_STATE", None)
        super().tearDown()

    def test_plymouth(self):
        for state in ({"installed": ["../../../etc"]}, {"installed": [], "previous": "-x"}):
            (self.tmp / "plymouth.json").write_text(json.dumps(state))
            with self.subTest(state=state):
                with self.assertRaises(SystemExit) as e:
                    quiet(main, ["plymouth", "--restore", "--dry-run"])
                self.assertIn("Invalid theme name", str(e.exception))

    def test_ksplash(self):
        (self.tmp / "ksplash.json").write_text(json.dumps({"installed": ["../../.ssh"]}))
        with self.assertRaises(SystemExit) as e:
            quiet(main, ["ksplash", "--restore", "--dry-run"])
        self.assertIn("Invalid package id", str(e.exception))


class SourceLinks(Tmp):
    """A theme's links out of its folder are not read, so not copied into the output
    (and installed, world-readable) under sudo."""
    def test_plymouth(self):
        import shutil
        theme = self.tmp / "glow_mini"
        shutil.copytree(FIXTURES / "glow_mini", theme)
        (self.tmp / "secret").write_text("root only")
        (theme / "font.ttf").symlink_to(self.tmp / "secret")
        _, out = quiet(main, ["plymouth", str(theme), "-a", "mauve", "-o", str(self.tmp / "out")])
        self.assertIn("note: skipped", out)
        self.assertFalse(any(p.name == "font.ttf" for p in (self.tmp / "out").rglob("*")))


class Limine(Tmp):
    """limine.conf: only the block is added, checked before writing; restore takes
    away exactly that, so the file comes back byte for byte."""
    def apply(self, conf_bytes, *extra):
        esp = self.tmp / "esp"
        esp.mkdir(exist_ok=True)
        (esp / "limine.conf").write_bytes(conf_bytes)
        quiet(main, ["limine", "-a", "mauve", "--apply", "--esp", str(esp),
                     "-o", str(self.tmp / "out"), *extra])
        return esp

    def restore(self, esp):
        quiet(main, ["limine", "--restore", "--esp", str(esp)])
        return (esp / "limine.conf").read_bytes()

    def test_byte_for_byte(self):
        odd = (LIMINE_CONF.replace("\n", "\r\n").encode()     # CRLF, no final newline,
               .rstrip(b"\r\n") + b"\n# caf\xe9 \xff  ")       # bytes that are not UTF-8
        for original in (LIMINE_CONF.encode(), odd, b"timeout: 3\n", b"timeout: 3", b""):
            with self.subTest(original=original[:20]):
                esp = self.apply(original)
                new = (esp / "limine.conf").read_bytes()
                self.assertEqual(new.count(limine.BEGIN.encode()), 1)
                self.assertEqual(self.restore(esp), original)
                first = min(esp.glob("limine.conf.*.bak"))         # the backup apply made
                self.assertEqual(first.read_bytes(), original)
                import shutil
                shutil.rmtree(esp)

    def test_apply_twice_one_block(self):
        esp = self.apply(LIMINE_CONF.encode())
        self.apply((esp / "limine.conf").read_bytes())
        text = (esp / "limine.conf").read_text()
        self.assertEqual(text.count(limine.BEGIN), 1)
        self.assertEqual(self.restore(esp), LIMINE_CONF.encode())

    def test_restore_keeps_later_changes(self):
        esp = self.apply(LIMINE_CONF.encode())
        entry = "\n/+Linux LTS\n    //linux-lts\n        protocol: linux\n"
        with open(esp / "limine.conf", "a") as f:        # a kernel update adds an entry
            f.write(entry)
        self.assertEqual(self.restore(esp), (LIMINE_CONF + entry).encode())

    def test_restore_without_theme_writes_nothing(self):
        esp = self.apply(LIMINE_CONF.encode())
        self.restore(esp)
        n = len(list(esp.glob("*.bak")))
        self.restore(esp)
        self.assertEqual(len(list(esp.glob("*.bak"))), n)

    def test_broken_block_is_refused(self):
        broken = LIMINE_CONF.replace("timeout: 3\n", f"{limine.BEGIN}: x\nbackdrop: 000000\n")
        with self.assertRaises(SystemExit) as e:
            self.apply(broken.encode())
        self.assertIn("fix it by hand", str(e.exception))
        self.assertEqual((self.tmp / "esp/limine.conf").read_text(), broken)
        self.assertEqual([p.name for p in (self.tmp / "esp").iterdir()], ["limine.conf"])

    def test_check_insert(self):
        lines = limine.theme_lines("mocha", "mauve")
        new = limine.insert_theme(LIMINE_CONF, lines)
        block = "".join(x + "\n" for x in lines) + "\n"
        limine.check_insert(LIMINE_CONF, new, block)                   # fine
        for bad in (new.replace("timeout: 3", "timeout: 0"),          # something else changed
                    new.replace("backdrop:", "backdrop: 0 #"),         # not our block
                    new + block):                                     # two blocks
            with self.assertRaises(SystemExit):
                limine.check_insert(LIMINE_CONF, bad, block)

    def test_wallpaper_stays_on_the_esp(self):
        esp = self.tmp / "esp"
        esp.mkdir()
        self.assertEqual(limine.resolve_on_esp("boot():/w.png#x", esp), esp / "w.png")
        for ref in ("boot():/../etc/shadow", "boot():/a/../../x.png"):
            with self.assertRaises(SystemExit):
                limine.resolve_on_esp(ref, esp)


class GuiRequests(unittest.TestCase):
    """The local server: who may call it, which files it serves or opens, what a
    run may contain, uploads."""
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="catppuccinizer-test-"))
        os.environ["CATPPUCCINIZER_CACHE"] = str(cls.tmp / "cache")
        cls.app = gui.App()
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), gui.make_handler(cls.app))
        cls.app.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        Image.new("RGB", (8, 8), (30, 30, 46)).save(cls.tmp / "ok.png")
        (cls.tmp / "notes.txt").write_text("private")
        (cls.tmp / "run.sh").write_text("#!/bin/sh\n")
        (cls.tmp / "passwd.png").symlink_to("/etc/passwd")       # an image by its name only

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        os.environ.pop("CATPPUCCINIZER_CACHE", None)

    def request(self, path, body=None, token=True, headers=None, raw=None):
        """(status, parsed JSON or bytes)."""
        data = raw if raw is not None else None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(f"http://127.0.0.1:{self.app.port}{path}", data=data)
        if token:
            req.add_header("X-Token", self.app.token)
        for k, v in (headers or {}).items():
            req.add_header(k, v)
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                status, content, ctype = r.status, r.read(), r.headers.get("Content-Type", "")
        except urllib.error.HTTPError as e:
            with e:
                status, content, ctype = e.code, e.read(), e.headers.get("Content-Type", "")
        return status, json.loads(content) if ctype.startswith("application/json") else content

    # ------------------------------------------------------------- access
    def test_token_host_origin(self):
        self.assertEqual(self.request("/api/ping")[0], 200)
        self.assertEqual(self.request("/api/ping", token=False)[0], 403)
        self.assertEqual(self.request("/api/ping", token=False,
                                      headers={"X-Token": self.app.token[:-1] + "x"})[0], 403)
        self.assertEqual(self.request(f"/api/ping?t={self.app.token}", token=False)[0], 200)
        own = f"http://127.0.0.1:{self.app.port}"
        for headers in ({"Host": f"evil.example:{self.app.port}"},          # DNS rebinding
                        {"Host": "127.0.0.1"},                              # another port
                        {"Origin": "https://evil.example"},                 # CSRF, even with
                        {"Origin": "null"},                                 # the token
                        {"Sec-Fetch-Site": "cross-site"},
                        {"Sec-Fetch-Site": "same-site"}):
            with self.subTest(headers=headers):
                self.assertEqual(self.request("/api/ping", headers=headers)[0], 403)
                self.assertEqual(self.request("/api/command", {"target": "lut"}, headers=headers)[0], 403)
        self.assertEqual(self.request("/api/ping", headers={"Origin": own,
                                                            "Sec-Fetch-Site": "same-origin"})[0], 200)

    def test_listens_on_localhost_and_never_as_root(self):
        real = gui.os.geteuid
        gui.os.geteuid = lambda: 0
        try:
            with self.assertRaises(SystemExit) as e:
                gui.serve(browser=False)
        finally:
            gui.os.geteuid = real
        self.assertIn("not with sudo", str(e.exception))
        self.assertIn('ThreadingHTTPServer(("127.0.0.1", port)', Path(gui.__file__).read_text())

    # -------------------------------------------------------------- files
    def test_files_served(self):
        q = lambda p: urllib.request.quote(str(p))      # noqa: E731
        status, content = self.request(f"/api/file?path={q(self.tmp / 'ok.png')}")
        self.assertEqual((status, content[:4]), (200, b"\x89PNG"))
        self.assertEqual(self.request(f"/api/thumb?s=32&path={q(self.tmp / 'ok.png')}")[0], 200)
        self.assertEqual(self.request(f"/api/thumb?s=x&path={q(self.tmp / 'ok.png')}")[0], 200)
        refused = ["/etc/passwd", self.tmp / "notes.txt", self.tmp / "passwd.png",
                   "/proc/self/environ", "/proc/self/root/etc/passwd", "ok.png",
                   self.tmp / "../" / self.tmp.name / "notes.txt", self.tmp / "missing.png"]
        if os.geteuid() != 0:
            (self.tmp / "locked.png").write_bytes((self.tmp / "ok.png").read_bytes())
            (self.tmp / "locked.png").chmod(0)
            refused.append(self.tmp / "locked.png")
        for path in refused:
            with self.subTest(path=path):
                self.assertEqual(self.request(f"/api/file?path={q(path)}")[0], 404)
                self.assertEqual(self.request(f"/api/thumb?path={q(path)}")[0], 404)

    def test_svg_runs_no_script(self):
        svg = self.tmp / "x.svg"
        svg.write_text('<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>')
        req = urllib.request.Request(f"http://127.0.0.1:{self.app.port}/api/file?path="
                                     f"{urllib.request.quote(str(svg))}", headers={"X-Token": self.app.token})
        with urllib.request.urlopen(req, timeout=30) as r:
            self.assertIn("sandbox", r.headers["Content-Security-Policy"])
            self.assertIn("default-src 'none'", r.headers["Content-Security-Policy"])

    def test_open_refuses_what_could_run(self):
        for path in (self.tmp / "run.sh", self.tmp / "passwd.png", "/etc/passwd", "relative",
                     "/proc/self"):
            with self.subTest(path=path):
                self.assertEqual(self.request("/api/open", {"path": str(path)}), (200, {"ok": False}))

    # ------------------------------------------------------------ uploads
    def upload(self, name, data=b"\x89PNG fake", length=None):
        c = http.client.HTTPConnection("127.0.0.1", self.app.port, timeout=30)
        c.putrequest("POST", "/api/upload")
        for k, v in (("X-Token", self.app.token), ("X-Filename", name),
                     ("Content-Length", str(len(data) if length is None else length))):
            c.putheader(k, v)
        c.endheaders()
        if length is None:
            c.send(data)
        r = c.getresponse()
        out = r.status, json.loads(r.read())
        c.close()
        return out

    def test_upload(self):
        base = self.tmp / "cache/gui-uploads"
        for name, expected in (("wall.png", "wall.png"), ("../../../evil.png", "evil.png"),
                               ("..%2F..%2Fevil.png", "evil.png"), (".hidden.png", "hidden.png"),
                               ("été 2024;rm -rf.jpg", "t_2024_rm_-rf.jpg")):
            with self.subTest(name=name):
                status, r = self.upload(name)
                self.assertEqual(status, 200, r)
                f = Path(r["path"])
                self.assertEqual(f.parent.parent, base)
                self.assertEqual(f.name, expected)
                self.assertEqual(f.read_bytes(), b"\x89PNG fake")
        self.assertEqual(stat.S_IMODE(base.stat().st_mode), 0o700)
        for name in ("script.sh", ".bashrc", "x.png.desktop", ""):
            with self.subTest(name=name):
                self.assertEqual(self.upload(name)[0], 400)
        self.assertEqual(self.upload("big.png", length=gui.MAX_UPLOAD + 1)[0], 413)
        self.assertEqual(self.upload("neg.png", length=-1)[0], 413)

    # ---------------------------------------------------------------- runs
    def test_run_values(self):
        bad = [{"images": ["--apply"]}, {"images": "-o/etc"}, {"images": ["a\nb"]},
               {"images": [{"x": 1}]}, {"images": ["a.png"], "suffix": "--x"},
               {"images": ["a.png"], "map": ["white=accent", "-f"]}, ["images"]]
        for values in bad:
            for route in ("/api/command", "/api/run", "/api/colours"):
                with self.subTest(values=values, route=route):
                    status, r = self.request(route, {"target": "image", "values": values})
                    self.assertEqual(status, 200)
                    self.assertTrue(r.get("error"), r)
                    self.assertNotIn("job", r)
        self.assertIn("unknown target", self.request("/api/run", {"target": "../x"})[1]["error"])
        # unknown keys never reach the command line; a negative number is a value
        status, r = self.request("/api/command", {"target": "image", "values": {
            "images": ["a.png"], "apply": True, "shell": "rm -rf ~", "keep_lum": "-0.5"}})
        self.assertEqual(r["argv"], ["image", "a.png", "--keep-lum", "-0.5"])
        self.assertIn("between 0 and 1", r["error"])           # the command line's own check

    def test_bodies(self):
        # announced, not sent: the server answers before reading (sending it all could
        # hit the closed connection)
        c = http.client.HTTPConnection("127.0.0.1", self.app.port, timeout=30)
        c.putrequest("POST", "/api/command")
        c.putheader("X-Token", self.app.token)
        c.putheader("Content-Length", str(gui.MAX_JSON + 1))
        c.endheaders()
        r = c.getresponse()
        self.assertEqual(r.status, 413)
        r.read()
        c.close()
        self.assertEqual(self.request("/api/command", raw=b"[1, 2]")[0], 400)
        self.assertEqual(self.request("/api/command", raw=b"{nope")[0], 400)
        self.assertEqual(self.request("/api/job?id=x&since=-3")[0], 404)


if __name__ == "__main__":
    unittest.main()
