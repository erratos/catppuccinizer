"""Graphical interface: `catppuccinize gui`.

A small web page served on 127.0.0.1 (standard library only). The forms are built
from the options the targets declare (core.options), like the command line, so
every target, built-in or added by an entry point, gets its options without
GUI-specific code. A run is
the equivalent `catppuccinize ...` command in a subprocess; its output is
streamed to the page, and the files it wrote are shown as thumbnails. The live
preview (gui.live) is rendered in this process instead, on a reduced image.

Access (docs/gui.md, Security): it listens on 127.0.0.1 only and never runs as
root; every request needs the random token printed with the address, a Host
header that is the local address (DNS rebinding) and, when the browser says
where it comes from (Origin, Sec-Fetch-Site), this page (no other site can
drive it). Files are served only when they are images the user can read; a run
only gets known options, and values that cannot pass for options.
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
from ..core.archives import ArchiveError
from ..core.online import NetworkError, thumbnail as online_thumbnail
from ..core.paths import cache_dir
from ..core.options import STEPS, active, analysis, image_file
from ..core.recolor import NO_ACCENT_METHODS
from ..core.target import discover
from . import live

HERE = Path(__file__).resolve().parent
PKG_PARENT = HERE.parent.parent
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".qoi", ".svg", ".svgz"}
BROWSER_IMAGES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
IDLE_EXIT = 600            # seconds without any request (and no job) before the server stops
MAX_JSON = 1 << 20         # bytes of a JSON request
MAX_UPLOAD = 200 << 20     # bytes of a dropped image
MAX_FILE = 200 << 20       # bytes of a file served whole (/api/file)
SYSTEM_FS = ("/proc", "/sys", "/dev", "/run")      # never served, even when readable
# what /api/open hands to xdg-open: folders, images and plain text outputs, never
# something xdg-open could run (a script, a .desktop file)
OPENABLE = IMAGE_EXTS | {".conf", ".txt", ".json", ".cube"}
# the subprocess: the installed package, or this checkout when run from the sources
BOOT = (f"import sys; sys.dont_write_bytecode = True; sys.path.insert(0, {str(PKG_PARENT)!r}); "
        "from catppuccinizer.cli import main; main()")


# -------------------------------------------------------------------- schema
def first_paragraph(text):
    return (text or "").strip().split("\n\n")[0].replace("\n", " ")


def summary(doc):
    """The intro of a target's page: its docstring's first paragraph, without the
    "Plymouth target:" its tab already says."""
    text = re.sub(r"^[\w ]{1,30} target:\s*", "", first_paragraph(doc))
    return text[:1].upper() + text[1:]


def schema(targets):
    out = []
    for name, t in targets.items():
        out.append({
            "name": name, "help": t.help, "summary": summary(t.doc),
            "description": t.doc or "", "default_out": t.default_out,
            "default_accent": list(t.default_accent), "accent_also": t.accent_also,
            "has_locations": t.has_locations, "links": list(t.links),
            "online": [s.info() for s in t.online],
            "has_settings": t.has_settings, "tips": list(t.tips),
            "has_colours": t.has_colours, "has_outputs": t.has_outputs,
            "options": [o.schema() for o in t.all_options() if o.gui],
        })
    return {"version": __version__, "targets": out, "cwd": str(Path.cwd()),
            "home": str(Path.home()), "flavors": FLAVORS, "flavor_titles": FLAVOR_TITLES,
            "accents": ACCENTS, "map_targets": TARGETS, "no_accent_methods": list(NO_ACCENT_METHODS),
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


# options that do not change what --colours finds: left out of the analysis (and of
# its cache key in the page), so that picking a flavour does not analyse again
NOT_ANALYSED = {"map", "preview", "preview_animation", "out", "suffix", "dry_run", "flavor", "accent"}


# ---------------------------------------------------------------- arguments
def check_values(values, options):
    """None, or why the form values cannot become arguments: only plain values
    (text, numbers, on/off, lists of them), no control characters, and no text
    starting with '-' (it would pass for an option: a source "--apply")."""
    if not isinstance(values, dict):
        return "values: not an object"
    for o in options:
        v = values.get(o["dest"])
        for x in (v if isinstance(v, list) else [v]):
            if x is None or isinstance(x, (bool, int, float)):
                continue
            if not isinstance(x, str):
                return f"{o['dest']}: not a plain value"
            if re.search(r"[\x00-\x1f\x7f]", x):
                return f"{o['dest']}: control characters are not allowed"
            if x.startswith("-"):
                try:
                    float(x)                         # a negative number is fine
                except ValueError:
                    return f"{o['dest']}: a value cannot start with '-' ({x})"
    return None


def build_argv(target, values, options):
    """Command-line arguments for a target from the form values {dest: value};
    options that do not count (core.options.active: --lutgen-* without --method
    lutgen, Limine's --style without a wallpaper) are left out."""
    # sources first (catppuccinize image wall.jpg -f mocha): an option taking several
    # values (-f latte mocha) would otherwise swallow them
    argv, positionals = [], []
    for o in options:
        v = values.get(o["dest"])
        if v is None or v == "" or v == [] or v is False or not active(o, values, options):
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


def version(path):
    try:
        return int(path.stat().st_mtime_ns // 1_000_000) if path else 0
    except OSError:
        return 0


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
                          "thumb": str(thumb) if thumb else None,
                          # in the thumbnail's address: a file written again gets a new one,
                          # so the browser does not show its cached copy of the old image
                          "version": version(thumb)})
    return found[:limit]


# ------------------------------------------------------------------ handler
class App:
    def __init__(self):
        self.token = secrets.token_urlsafe(18)
        self.targets = discover()
        from ..cli import build_parser
        self.parser = build_parser(self.targets)
        self.schema = schema(self.targets)
        self.options = {t["name"]: t["options"] for t in self.schema["targets"]}
        # the illustrations the options declare: the only files /api/asset serves
        self.images = {o.image: image_file(o.image) for t in self.targets.values()
                       for o in t.all_options() if o.image}
        self.jobs = {}
        self.live_view = live.Live()
        self.last_seen = time.time()
        self.port = None

    def command(self, body):
        name = body.get("target")
        if name not in self.options:
            return {"error": f"unknown target {name}"}
        values = body.get("values") or {}
        if err := check_values(values, self.options[name]):
            return {"error": err}
        argv = build_argv(name, values, self.options[name])
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

    def colours(self, body):
        """The colours -m can remap, before any run: `catppuccinize ... --colours --json`
        in a subprocess (as the command line does it), without the options that do
        not change the analysis (-m is shown over it by the page, so that a name
        being typed is not an error)."""
        name = body.get("target")
        t = self.targets.get(name)
        if t is None or not t.has_colours:
            return {"error": f"{name}: no colours to list"}
        values = body.get("values") or {}
        if err := check_values(values, self.options[name]):
            return {"error": err}
        values = {k: v for k, v in values.items() if k not in NOT_ANALYSED and k not in STEPS}
        argv = [*build_argv(name, values, self.options[name]), "--colours", "--json"]
        a, err = check_argv(argv, self.parser)
        if err:
            return {"error": err}
        items, err = listing_output(argv, bool(body.get("sudo")))
        if err:
            return {"error": err}
        return {"items": items, "facts": analysis(items),
                "command": command_line(argv, bool(body.get("sudo")))}

    def names(self, body):
        """What Build would write, before running it: `catppuccinize ... --names --json`
        in a subprocess, with the form values but the system steps; entries that
        exist are marked (the build replaces them)."""
        name = body.get("target")
        t = self.targets.get(name)
        if t is None or not t.has_outputs:
            return {"error": f"{name}: no output names to list"}
        values = body.get("values") or {}
        if err := check_values(values, self.options[name]):
            return {"error": err}
        values = {k: v for k, v in values.items() if k not in STEPS and k != "dry_run"}
        argv = [*build_argv(name, values, self.options[name]), "--names", "--json"]
        a, err = check_argv(argv, self.parser)
        if err:
            return {"error": err}
        items, err = listing_output(argv, bool(body.get("sudo")))
        if err:
            return {"error": err}
        return {"items": items, "out": str(a.out), "command": command_line(argv, bool(body.get("sudo")))}

    def online_source(self, q):
        """The online source a request names ({"target": [...], "source": [...]}, as
        parse_qs gives them), or None."""
        t = self.targets.get((q.get("target") or [""])[0])
        name = (q.get("source") or [""])[0]
        return next((s for s in (t.online if t else ()) if s.name == name), None)

    def live(self, body):
        """The live preview: the source image recoloured with the form values, in this
        process, on a reduced copy (gui.live), for the first flavour and accent. Only
        for targets whose source is an image; body["image"] picks one of the source's
        images (the first by default)."""
        name = body.get("target")
        if name not in self.options:
            return {"error": f"unknown target {name}"}
        sources = [o for o in self.options[name]
                   if o["role"] == "source" and o["accept"] in ("image", "images")]
        if not sources:
            return {"error": f"{name}: no image to preview live"}
        values = body.get("values") or {}
        if err := check_values(values, self.options[name]):
            return {"error": err}
        values = {k: v for k, v in values.items() if k not in STEPS and k not in LIVE_LEFT_OUT}
        a, err = check_argv(build_argv(name, values, self.options[name]), self.parser)
        if err:
            return {"error": err}
        images = live_images(a, sources)
        if not images:
            return {"error": "no still image you can read in the source (an SVG or an "
                             "animation: Preview image / Preview animation)"}
        path = body.get("image") if body.get("image") in images else images[0]
        a.strict_map = False            # a name being typed in -m is not an error here
        try:
            r = self.live_view.render(path, a)
        except SystemExit as e:
            return {"error": str(e)}
        except (OSError, ValueError, Image.DecompressionBombError) as e:
            return {"error": f"{Path(path).name}: {e}"}
        return {**r, "path": path, "images": images, "version": version(Path(path))}

    def busy(self):
        return any(j.code is None and j.proc for j in self.jobs.values())


# what the live preview leaves out of the form values: it shows the result itself
LIVE_LEFT_OUT = {"preview", "preview_animation", "dry_run"}
LIVE_IMAGES = 200            # images of a source the live preview offers


def live_images(a, sources):
    """The still images of the parsed sources (files, or the images of a folder, in
    order) that the page may get, as strings: what the live preview can show."""
    out = []
    for o in sources:
        v = getattr(a, o["dest"], None)
        for p in (v if isinstance(v, list) else [v] if v else []):
            p = Path(p).expanduser().absolute()
            files = sorted(f for f in p.rglob("*") if f.suffix.lower() in live.EXTS) if p.is_dir() else [p]
            for f in files:
                if f.suffix.lower() in live.EXTS and servable(str(f)) and str(f) not in out:
                    out.append(str(f))
                if len(out) >= LIVE_IMAGES:
                    return out
    return out


def listing_output(argv, sudo=False):
    """(JSON printed by `catppuccinize argv`, None) or (None, error message): the
    analysis runs in a subprocess, as the command line does it; with sudo when asked
    (a source only root can read: Limine's wallpaper on the ESP)."""
    cmd = [sys.executable, "-B", "-c", BOOT, *argv]
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    if sudo:
        if not askpass():
            return None, "no graphical sudo prompt (ksshaskpass, ssh-askpass): run the command in a terminal"
        cmd, env["SUDO_ASKPASS"] = ["sudo", "-A", "--", *cmd], askpass()
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=600,
                           stdin=subprocess.DEVNULL, env=env, start_new_session=True)
    except subprocess.TimeoutExpired:
        return None, "the analysis took more than 10 minutes"
    if r.returncode:
        lines = (r.stderr or r.stdout).strip().splitlines()
        return None, lines[-1] if lines else f"the analysis failed ({r.returncode})"
    try:
        return json.loads(r.stdout), None
    except ValueError:
        return None, "unreadable analysis output"


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


def servable(path, folders=False, exts=IMAGE_EXTS):
    """The image file (or, with folders, the folder) at path when the page may get
    it, else None: an absolute path, readable by the user, not in /proc, /sys…,
    an image by its extension (exts), a regular file of reasonable size."""
    if not path or "\0" in path or not os.path.isabs(path):
        return None
    p = Path(path)
    try:
        real = p.resolve(strict=True)
    except (OSError, RuntimeError):
        return None
    if any(real == Path(d) or real.is_relative_to(d) for d in SYSTEM_FS):
        return None
    if real.is_dir():
        return p if folders and os.access(real, os.R_OK | os.X_OK) else None
    if (real.suffix.lower() not in exts or not real.is_file()
            or not os.access(real, os.R_OK) or real.stat().st_size > MAX_FILE):
        return None
    return p


def upload_name(raw):
    """A dropped file's name, reduced to letters, digits, '.', '_', '-' (no folder,
    no leading dot), or None when it is not an image."""
    name = Path(unquote(raw or "")).name
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", name).lstrip("._")[:100] or "image"
    return name if Path(name).suffix.lower() in IMAGE_EXTS else None


def thumbnail(path, size):
    p = servable(path, folders=True)
    if p is None:
        return None, None
    ext = p.suffix.lower()
    if p.is_dir():
        p = representative(p)
        if p is None or servable(str(p)) is None:       # the image itself, checked too
            return None, None
        ext = p.suffix.lower()
    if ext == ".svg":
        return p.read_bytes(), "image/svg+xml"
    with Image.open(p) as im:
        im.seek(0)
        if size:
            im.draft("RGB", (size, size))     # JPEG: decoded at a fraction of its size, fast
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
            else:       # an SVG opened on its own runs no script (it could read the token)
                self.send_header("Content-Security-Policy",
                                 "default-src 'none'; style-src 'unsafe-inline'; sandbox")
            self.end_headers()
            self.wfile.write(body)

        def allowed(self, query):
            hosts = (f"127.0.0.1:{app.port}", f"localhost:{app.port}")
            if self.headers.get("Host", "") not in hosts:            # DNS rebinding
                return False
            # sent by browsers: a request made by another site's page is refused
            # (CSRF), even before the token is checked
            origin = self.headers.get("Origin")
            if origin is not None and origin not in {f"http://{h}" for h in hosts}:
                return False
            if self.headers.get("Sec-Fetch-Site", "same-origin") not in ("same-origin", "none"):
                return False
            given = self.headers.get("X-Token") or (query.get("t") or [""])[0]
            return secrets.compare_digest(given.encode(), app.token.encode())

        def body(self, limit):
            """The request body, or None when its size is missing, wrong or over limit."""
            try:
                n = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                return None
            if n < 0 or n > limit:
                return None
            return self.rfile.read(n) if n else b""

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
            if u.path == "/api/locations":
                name = (q.get("target") or [""])[0]
                t = app.targets.get(name)
                if t is None:
                    return self.send(404, {"error": "unknown target"})
                try:
                    with contextlib.redirect_stdout(io.StringIO()):
                        return self.send(200, {"sections": t.locations()})
                except (SystemExit, Exception) as e:  # noqa: BLE001 - shown in the page
                    return self.send(200, {"sections": [], "error": str(e) or type(e).__name__})
            if u.path == "/api/settings":           # the system settings as they are now
                t = app.targets.get((q.get("target") or [""])[0])
                if not t or not t.has_settings:
                    return self.send(404, {"error": "unknown target"})
                try:
                    return self.send(200, {"values": t.settings_now()})
                except (SystemExit, Exception) as e:  # noqa: BLE001 - shown in the page
                    msg = e.code if isinstance(e, SystemExit) else e
                    return self.send(200, {"values": {}, "error": str(msg) or type(e).__name__})
            if u.path in ("/api/online", "/api/online/thumb"):
                src = app.online_source(q)
                if src is None:
                    return self.send(404, {"error": "unknown online source"})
                try:
                    if u.path == "/api/online":
                        page = (q.get("page") or ["1"])[0]
                        return self.send(200, src.search((q.get("q") or [""])[0][:200],
                                                         int(page) if page.isdigit() else 1))
                    size = (q.get("s") or ["256"])[0]
                    size = min(int(size), 512) if size.isdigit() and int(size) else 256
                    return self.send(200, online_thumbnail(src, (q.get("url") or [""])[0], size),
                                     "image/jpeg", cache=True)
                except NetworkError as e:
                    status = 200 if u.path == "/api/online" else 404
                    return self.send(status, {"error": str(e)})
            if u.path == "/api/job":
                job = app.jobs.get((q.get("id") or [""])[0])
                if not job:
                    return self.send(404, {"error": "no such run"})
                since = (q.get("since") or ["0"])[0]
                return self.send(200, job.state(int(since) if since.isdigit() else 0))
            if u.path == "/api/thumb":
                path = (q.get("path") or [""])[0]
                size = (q.get("s") or ["256"])[0]
                size = min(int(size), 4096) if size.isdigit() else 256
                try:
                    data, ctype = thumbnail(path, size)
                except (OSError, ValueError, Image.DecompressionBombError) as e:
                    return self.send(404, {"error": str(e)})
                if data is None:
                    return self.send(404, {"error": "no image"})
                return self.send(200, data, ctype, cache=True)
            if u.path == "/api/asset":           # an option's illustration (Option.image)
                f = app.images.get((q.get("name") or [""])[0])
                ctype = mimetypes.guess_type(f.name)[0] if f else None
                if not f or not ctype or not ctype.startswith("image/") or not f.is_file():
                    return self.send(404, {"error": "no such illustration"})
                return self.send(200, f.read_bytes(), ctype, cache=True)
            if u.path == "/api/file":            # the lightbox: images only
                p = servable((q.get("path") or [""])[0])
                if p is None:
                    return self.send(404, {"error": "not found"})
                ctype = mimetypes.guess_type(p.name)[0] or ""
                if not ctype.startswith("image/"):
                    return self.send(404, {"error": "not an image"})
                try:
                    return self.send(200, p.read_bytes(), ctype)
                except OSError as e:
                    return self.send(404, {"error": str(e)})
            return self.send(404, {"error": "not found"})

        def do_POST(self):
            u = urlparse(self.path)
            if not self.allowed({}):
                return self.send(HTTPStatus.FORBIDDEN, {"error": "forbidden"})
            app.last_seen = time.time()
            if u.path == "/api/upload":
                name = upload_name(self.headers.get("X-Filename"))
                if name is None:
                    return self.send(400, {"error": "not an image"})
                data = self.body(MAX_UPLOAD)
                if data is None:
                    return self.send(HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                                     {"error": f"images up to {MAX_UPLOAD >> 20} MB"})
                base = cache_dir() / "gui-uploads"           # only for the user
                base.mkdir(parents=True, exist_ok=True, mode=0o700)
                os.chmod(base, 0o700)
                d = base / uuid.uuid4().hex[:12]
                d.mkdir(mode=0o700)
                with open(d / name, "xb") as f:               # x: a new file, never through a link
                    f.write(data)
                return self.send(200, {"path": str(d / name)})
            raw = self.body(MAX_JSON)
            if raw is None:
                return self.send(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"error": "request too large"})
            try:
                data = json.loads(raw or b"{}")
            except ValueError:
                return self.send(400, {"error": "bad json"})
            if not isinstance(data, dict):
                return self.send(400, {"error": "bad json"})
            if u.path == "/api/command":
                return self.send(200, app.command(data))
            if u.path == "/api/colours":
                return self.send(200, app.colours(data))
            if u.path == "/api/names":
                return self.send(200, app.names(data))
            if u.path == "/api/live":
                return self.send(200, app.live(data))
            if u.path == "/api/online/fetch":       # download an item into the cache
                src = app.online_source({k: [v] for k, v in data.items() if isinstance(v, str)})
                if src is None:
                    return self.send(404, {"error": "unknown online source"})
                try:
                    return self.send(200, {"paths": [str(p) for p in src.fetch(str(data.get("id", "")))]})
                except (NetworkError, ArchiveError) as e:
                    return self.send(200, {"error": str(e)})
            if u.path == "/api/run":
                return self.send(200, app.run(data))
            if u.path == "/api/stop":
                job = app.jobs.get(data.get("id", ""))
                if job:
                    job.stop()
                return self.send(200, {"ok": bool(job)})
            if u.path == "/api/open":
                # a folder or an image only: xdg-open on a script or a .desktop file
                # could run it
                p = servable(str(data.get("path", "")), folders=True, exts=OPENABLE)
                opener = shutil.which("xdg-open")
                if p is None or not opener:
                    return self.send(200, {"ok": False})
                subprocess.Popen([opener, str(p)], stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL, start_new_session=True)
                return self.send(200, {"ok": True})
            return self.send(404, {"error": "not found"})

    return Handler


def serve(port=0, browser=True):
    if os.geteuid() == 0:
        # as root it would serve root's files to the page: a step that needs root
        # asks for sudo itself
        raise SystemExit("Run the GUI as your user, not with sudo: the steps that need "
                         "root ask for the password themselves")
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
