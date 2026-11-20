"""Graphical interface: `catppuccinize gui`.

A small web page served on 127.0.0.1 (standard library only). The forms are built
from the same argparse subparsers as the command line, so every target, built-in
or added by an entry point, gets its options without GUI-specific code. A run is
the equivalent `catppuccinize ...` command in a subprocess; its output is
streamed to the page, and the files it wrote are shown as thumbnails.

Every API call needs the random token printed with the address, and the Host
header must be the local address (no other site or local user can drive it).
"""
import argparse
import contextlib
import io
import json
import mimetypes
import os
import re
import secrets
import shlex
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from PIL import Image

from .. import __version__
from ..core.palette import ACCENTS, FLAVOR_TITLES, FLAVORS, PALETTES, TARGETS
from ..core.paths import cache_dir
from ..core.recolor import LUT_METHODS
from ..core.target import Target, discover

HERE = Path(__file__).resolve().parent
PKG_PARENT = HERE.parent.parent
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".qoi", ".svg", ".svgz"}
BROWSER_IMAGES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
IDLE_EXIT = 600            # seconds without any request (and no job) before the server stops
# the subprocess: the installed package, or this checkout when run from the sources
BOOT = (f"import sys; sys.dont_write_bytecode = True; sys.path.insert(0, {str(PKG_PARENT)!r}); "
        "from catppuccinizer.cli import main; main()")


# -------------------------------------------------------------------- schema
def _kind(action):
    if isinstance(action, (argparse._StoreTrueAction, argparse._StoreFalseAction)):
        return "bool"
    if action.dest in ("flavor", "accent"):
        return action.dest
    if action.dest == "map":
        return "map"
    if action.nargs == "?" and action.option_strings and action.const is not None:
        return "optional"                      # --test [SECONDS]: a switch with an optional value
    if action.choices:
        return "multichoice" if action.nargs in ("+", "*") else "choice"
    if action.type in (int, float):
        return "int" if action.type is int else "float"
    if action.type is Path or not action.option_strings:
        return "path"
    return "text"


def _range(metavar):
    m = re.fullmatch(r"(-?[\d.]+)\.\.(-?[\d.]+)", metavar or "")
    return [float(m.group(1)), float(m.group(2))] if m else None


def _when(group_title):
    """'lutgen method (--method lutgen, ...)' -> {"method": "lutgen"}: shown only then."""
    m = re.search(r"\(--([\w-]+) ([\w-]+)", group_title or "")
    return {m.group(1).replace("-", "_"): m.group(2)} if m else None


def _plain(v):
    if isinstance(v, Path):
        return str(v)
    if isinstance(v, (list, tuple)):
        return [_plain(x) for x in v]
    return v if v is None or isinstance(v, (str, int, float, bool)) else str(v)


def options_of(sp):
    groups = {id(a): g.title for g in sp._action_groups for a in g._group_actions}
    out = []
    for a in sp._actions:
        if isinstance(a, argparse._HelpAction) or a.dest == "target" or a.help == argparse.SUPPRESS:
            continue
        kind = _kind(a)
        title = groups.get(id(a))
        is_source = not a.option_strings or (kind == "path" and a.metavar == "IMAGE")
        out.append({
            "dest": a.dest, "flags": a.option_strings, "kind": kind,
            "positional": not a.option_strings, "nargs": a.nargs,
            "multiple": a.nargs in ("+", "*"), "required": bool(a.required),
            "choices": _plain(list(a.choices)) if a.choices else None,
            "default": _plain(a.default), "const": _plain(a.const),
            "metavar": a.metavar if isinstance(a.metavar, str) else None,
            "help": (a.help or "").replace("%%", "%"), "range": _range(a.metavar),
            "group": title if title not in ("options", "positional arguments") else None,
            "when": _when(title),
            "role": "source" if is_source else ("common" if a.dest in COMMON else "option"),
            "sudo": "sudo" in (a.help or ""),
        })
    return out


COMMON = {"flavor", "accent", "map", "preview", "out"}


def first_paragraph(text):
    return (text or "").strip().split("\n\n")[0].replace("\n", " ")


def schema(targets, subparsers):
    out = []
    for name, t in targets.items():
        sp = subparsers[name]
        out.append({
            "name": name, "help": t.help, "summary": first_paragraph(sp.description),
            "description": sp.description or "", "default_out": t.default_out,
            "default_accent": list(t.default_accent), "accent_also": t.accent_also,
            "has_sources": type(t).sources is not Target.sources,
            "options": options_of(sp),
        })
    return {"version": __version__, "targets": out, "cwd": str(Path.cwd()),
            "home": str(Path.home()), "flavors": FLAVORS, "flavor_titles": FLAVOR_TITLES,
            "accents": ACCENTS, "map_targets": TARGETS, "lut_methods": list(LUT_METHODS),
            "palettes": {f: {k: "#" + v for k, v in p.items()} for f, p in PALETTES.items()},
            "askpass": bool(askpass()), "places": places()}


def places():
    home = Path.home()
    out = [("Home", home), ("Current folder", Path.cwd())]
    for label, rel in (("Pictures", "Pictures"), ("Images", "Images"), ("Downloads", "Downloads"),
                       ("Téléchargements", "Téléchargements")):
        if (home / rel).is_dir():
            out.append((label, home / rel))
    for label, p in (("Plymouth themes", Path("/usr/share/plymouth/themes")),
                     ("Look-and-feel", Path("/usr/share/plasma/look-and-feel")),
                     ("Wallpapers", Path("/usr/share/wallpapers"))):
        if p.is_dir():
            out.append((label, p))
    return [{"label": label, "path": str(p)} for label, p in dict(
        (str(p), (label, p)) for label, p in out).values()]


# ---------------------------------------------------------------- arguments
def build_argv(target, values, options):
    """Command-line arguments for a target from the form values {dest: value}."""
    # sources first (catppuccinize image wall.jpg -f mocha): an option taking several
    # values (-f latte mocha) would otherwise swallow them
    argv, positionals = [], []
    for o in options:
        v = values.get(o["dest"])
        if v is None or v == "" or v == [] or v is False:
            continue
        if o["positional"]:
            positionals += [str(x) for x in (v if isinstance(v, list) else [v])]
            continue
        flag = o["flags"][0]
        if o["kind"] == "bool":
            argv.append(flag)
        elif o["kind"] == "optional":
            argv += [flag] if v is True or str(v) == str(o["const"]) else [flag, str(v)]
        elif o["multiple"] or isinstance(v, list):
            v = v if isinstance(v, list) else [v]
            if v != o["default"]:
                argv += [flag, *map(str, v)]
        elif str(v) != str(o["default"]):
            argv += [flag, str(v)]
    return [target, *positionals, *argv]


def check_argv(argv, parser):
    """(parsed args, None) or (None, error message), as the command line would say it."""
    from ..cli import parse
    err, out = io.StringIO(), io.StringIO()
    try:
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(out):
            return parse(argv, parser), None
    except SystemExit as e:
        msg = err.getvalue().strip().splitlines()
        if isinstance(e.code, str):
            return None, e.code
        msg = msg[-1] if msg else "invalid options"
        return None, re.sub(r"^catppuccinize( \w+)?: error: ", "", msg)


def command_line(argv, sudo=False):
    return shlex.join((["sudo"] if sudo else []) + ["catppuccinize", *argv])


def askpass():
    """A graphical sudo password prompt, so that sudo works without a terminal."""
    for c in (os.environ.get("SUDO_ASKPASS"), "ksshaskpass", "ssh-askpass", "lxqt-openssh-askpass",
              "/usr/lib/ssh/ssh-askpass", "/usr/lib/ssh/gnome-ssh-askpass3"):
        if c and (shutil.which(c) or (Path(c).is_file() and os.access(c, os.X_OK))):
            return shutil.which(c) or c
    return None


# ---------------------------------------------------------------------- jobs
class Job:
    def __init__(self, argv, out, sudo):
        self.id = uuid.uuid4().hex[:12]
        self.argv, self.out, self.sudo = argv, Path(out), sudo
        self.lines, self.code, self.started = [], None, time.time()
        self.outputs = None
        env = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONDONTWRITEBYTECODE="1")
        if askpass():
            env["SUDO_ASKPASS"] = askpass()
        cmd = [sys.executable, "-B", "-c", BOOT, *argv]
        if sudo:
            cmd = ["sudo", "-A", "--", *cmd]
        self.lines.append("$ " + command_line(argv, sudo))
        try:
            # own session: no controlling terminal, so sudo asks with SUDO_ASKPASS
            self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                         stdin=subprocess.DEVNULL, env=env, text=True, bufsize=1,
                                         errors="replace", start_new_session=True)
        except OSError as e:
            self.proc, self.code = None, 127
            self.lines.append(str(e))
            self.outputs = []
            return
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        for line in self.proc.stdout:
            self.lines.append(line.rstrip("\n"))
        self.proc.stdout.close()
        self.code = self.proc.wait()
        self.outputs = outputs(self.out, self.started)

    def stop(self):
        if self.proc and self.code is None:
            with contextlib.suppress(OSError):
                os.killpg(self.proc.pid, signal.SIGTERM)

    def state(self, since=0):
        return {"id": self.id, "lines": self.lines[since:], "next": len(self.lines),
                "done": self.outputs is not None, "code": self.code, "outputs": self.outputs,
                "out": str(self.out)}


def representative(folder):
    """An image that shows what a generated folder looks like (theme, splash...)."""
    for rel in ("contents/previews/splash.png", "preview.png", "wallpaper.png"):
        if (folder / rel).is_file():
            return folder / rel
    imgs = []
    for k, f in enumerate(folder.rglob("*")):
        if k > 2000:
            break
        if f.suffix.lower() in BROWSER_IMAGES and f.is_file():
            imgs.append(f)
    if not imgs:
        return None
    walls = [f for f in imgs if "wallpaper" in f.name or "background" in f.name]
    if walls:
        return walls[0]
    imgs.sort()
    big = max(imgs[:400], key=lambda f: f.stat().st_size)
    return big


def outputs(out, since, limit=80):
    """Files and folders written into the output folder by a run."""
    found = []
    for base in (out / "previews", out):
        if not base.is_dir():
            continue
        for f in sorted(base.iterdir(), key=lambda f: f.name):
            if f.name == "previews" and base == out:
                continue
            try:
                if f.stat().st_mtime < since - 2:
                    continue
            except OSError:
                continue
            thumb = f if f.suffix.lower() in IMAGE_EXTS else (representative(f) if f.is_dir() else None)
            found.append({"path": str(f), "name": f.name, "dir": f.is_dir(),
                          "preview": base.name == "previews" and base != out,
                          "thumb": str(thumb) if thumb else None})
    return found[:limit]


# ------------------------------------------------------------------ handler
class App:
    def __init__(self):
        self.token = secrets.token_urlsafe(18)
        self.targets = discover()
        from ..cli import build_parser
        self.parser, self.subparsers = build_parser(self.targets)
        self.schema = schema(self.targets, self.subparsers)
        self.options = {t["name"]: t["options"] for t in self.schema["targets"]}
        self.jobs = {}
        self.last_seen = time.time()
        self.port = None

    def command(self, body):
        name = body.get("target")
        if name not in self.options:
            return {"error": f"unknown target {name}"}
        argv = build_argv(name, body.get("values") or {}, self.options[name])
        a, err = check_argv(argv, self.parser)
        sudo = bool(body.get("sudo"))
        return {"argv": argv, "command": command_line(argv, sudo), "error": err,
                "out": str(a.out) if a else None}

    def run(self, body):
        c = self.command(body)
        if c.get("error") or "argv" not in c:
            return c
        if any(j.code is None and j.proc for j in self.jobs.values()):
            return {"error": "a run is already in progress"}
        job = Job(c["argv"], c["out"], bool(body.get("sudo")))
        self.jobs[job.id] = job
        return {**c, "job": job.id}

    def busy(self):
        return any(j.code is None and j.proc for j in self.jobs.values())


def listing(path, show_hidden=False):
    p = Path(path or Path.home()).expanduser()
    if p.is_file():
        p = p.parent
    if not p.is_dir():
        p = Path.home()
    entries = []
    try:
        items = list(p.iterdir())
    except OSError as e:
        return {"path": str(p), "parent": str(p.parent), "entries": [], "error": str(e)}
    for f in items:
        if f.name.startswith(".") and not show_hidden:
            continue
        try:
            is_dir = f.is_dir()
        except OSError:
            continue
        ext = f.suffix.lower()
        entries.append({"name": f.name, "path": str(f), "dir": is_dir,
                        "image": not is_dir and ext in IMAGE_EXTS,
                        "theme": is_dir and (any(f.glob("*.plymouth"))
                                             or (f / "contents/splash/Splash.qml").exists())})
    entries.sort(key=lambda e: (not e["dir"], e["name"].lower()))
    return {"path": str(p), "parent": str(p.parent), "entries": entries[:3000]}


def thumbnail(path, size):
    p = Path(path)
    ext = p.suffix.lower()
    if p.is_dir():
        p = representative(p)
        if p is None:
            return None, None
        ext = p.suffix.lower()
    if ext == ".svg":
        return p.read_bytes(), "image/svg+xml"
    with Image.open(p) as im:
        im.seek(0)
        im = im.convert("RGBA")
        if size:
            im.thumbnail((size, size), Image.Resampling.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, "PNG" if size and size <= 512 else "WEBP", **({} if size and size <= 512
                                                                   else {"quality": 92}))
        return buf.getvalue(), "image/png" if size and size <= 512 else "image/webp"


def make_handler(app):
    class Handler(BaseHTTPRequestHandler):
        server_version = f"catppuccinizer/{__version__}"

        def log_message(self, fmt, *args):         # quiet
            pass

        # ---------------------------------------------------------- helpers
        def send(self, status, body=b"", ctype="application/json", cache=False):
            if isinstance(body, (dict, list)):
                body = json.dumps(body).encode()
            elif isinstance(body, str):
                body = body.encode()
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "private, max-age=300" if cache else "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            if ctype.startswith("text/html"):
                self.send_header("Content-Security-Policy",
                                 "default-src 'self'; img-src 'self' data: blob:; "
                                 "style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; "
                                 "frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(body)

        def allowed(self, query):
            host = self.headers.get("Host", "")
            if host not in (f"127.0.0.1:{app.port}", f"localhost:{app.port}"):
                return False
            given = self.headers.get("X-Token") or (query.get("t") or [""])[0]
            return secrets.compare_digest(given, app.token)

        def body(self):
            n = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(n) if n else b""
            return raw

        # ----------------------------------------------------------- routes
        def do_GET(self):
            u = urlparse(self.path)
            q = parse_qs(u.query)
            if not self.allowed(q):
                return self.send(HTTPStatus.FORBIDDEN, {"error": "forbidden"})
            app.last_seen = time.time()
            if u.path in ("/", "/index.html"):
                return self.send(200, (HERE / "index.html").read_bytes(), "text/html; charset=utf-8")
            if u.path == "/api/schema":
                return self.send(200, {**app.schema, "askpass": bool(askpass())})
            if u.path == "/api/ping":
                return self.send(200, {"ok": True, "busy": app.busy()})
            if u.path == "/api/ls":
                return self.send(200, listing((q.get("path") or [""])[0],
                                              (q.get("hidden") or ["0"])[0] == "1"))
            if u.path == "/api/sources":
                name = (q.get("target") or [""])[0]
                t = app.targets.get(name)
                if t is None:
                    return self.send(404, {"error": "unknown target"})
                try:
                    with contextlib.redirect_stdout(io.StringIO()):
                        return self.send(200, {"sources": t.sources() or []})
                except (SystemExit, Exception) as e:  # noqa: BLE001 - shown in the page
                    return self.send(200, {"sources": [], "error": str(e) or type(e).__name__})
            if u.path == "/api/job":
                job = app.jobs.get((q.get("id") or [""])[0])
                if not job:
                    return self.send(404, {"error": "no such run"})
                return self.send(200, job.state(int((q.get("since") or ["0"])[0])))
            if u.path == "/api/thumb":
                path = (q.get("path") or [""])[0]
                size = int((q.get("s") or ["256"])[0])
                try:
                    data, ctype = thumbnail(path, size)
                except (OSError, ValueError, Image.DecompressionBombError) as e:
                    return self.send(404, {"error": str(e)})
                if data is None:
                    return self.send(404, {"error": "no image"})
                return self.send(200, data, ctype, cache=True)
            if u.path == "/api/file":
                p = Path((q.get("path") or [""])[0])
                if not p.is_file():
                    return self.send(404, {"error": "not found"})
                ctype = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
                if not ctype.startswith("image/"):
                    ctype = "text/plain; charset=utf-8"
                return self.send(200, p.read_bytes(), ctype)
            return self.send(404, {"error": "not found"})

        def do_POST(self):
            u = urlparse(self.path)
            if not self.allowed({}):
                return self.send(HTTPStatus.FORBIDDEN, {"error": "forbidden"})
            app.last_seen = time.time()
            if u.path == "/api/upload":
                name = Path(unquote(self.headers.get("X-Filename") or "image")).name or "image"
                if Path(name).suffix.lower() not in IMAGE_EXTS:
                    return self.send(400, {"error": f"{name}: not an image"})
                d = cache_dir() / "gui-uploads" / uuid.uuid4().hex[:8]
                d.mkdir(parents=True, exist_ok=True)
                (d / name).write_bytes(self.body())
                return self.send(200, {"path": str(d / name)})
            try:
                data = json.loads(self.body() or b"{}")
            except ValueError:
                return self.send(400, {"error": "bad json"})
            if u.path == "/api/command":
                return self.send(200, app.command(data))
            if u.path == "/api/run":
                return self.send(200, app.run(data))
            if u.path == "/api/stop":
                job = app.jobs.get(data.get("id", ""))
                if job:
                    job.stop()
                return self.send(200, {"ok": bool(job)})
            if u.path == "/api/open":
                p = Path(data.get("path", ""))
                if not p.exists() or not shutil.which("xdg-open"):
                    return self.send(200, {"ok": False})
                subprocess.Popen(["xdg-open", str(p)], stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL, start_new_session=True)
                return self.send(200, {"ok": True})
            return self.send(404, {"error": "not found"})

    return Handler


def serve(port=0, browser=True):
    app = App()
    httpd = ThreadingHTTPServer(("127.0.0.1", port), make_handler(app))
    httpd.daemon_threads = True
    app.port = httpd.server_address[1]
    url = f"http://127.0.0.1:{app.port}/?t={app.token}"
    print(f"catppuccinizer GUI: {url}\n(Ctrl+C to stop; it also stops by itself "
          f"{IDLE_EXIT // 60} minutes after the page is closed)", flush=True)

    def watchdog():
        while True:
            time.sleep(15)
            if not app.busy() and time.time() - app.last_seen > IDLE_EXIT:
                print("No page open any more, stopping.", flush=True)
                httpd.shutdown()
                return
    threading.Thread(target=watchdog, daemon=True).start()
    if browser:
        threading.Timer(0.3, webbrowser.open, args=(url,)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        for j in app.jobs.values():
            j.stop()
        httpd.server_close()


def main():
    """Entry point of the catppuccinize-gui script."""
    p = argparse.ArgumentParser(prog="catppuccinize-gui", description="catppuccinizer in your browser")
    p.add_argument("--port", type=int, default=0, help="port (default: a free one)")
    p.add_argument("--no-browser", action="store_true", help="only print the address")
    a = p.parse_args()
    sys.dont_write_bytecode = True
    serve(port=a.port, browser=not a.no_browser)


if __name__ == "__main__":
    main()
