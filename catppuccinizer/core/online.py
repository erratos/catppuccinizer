"""Online sources: other sources the GUI browses itself (Target.online), as a grid
of thumbnails filled by a site's API; choosing one downloads it into the cache
(downloads(): ~/.cache/catppuccinizer/downloads/<source>/) and gives its path to
the source argument, like a file chosen with the file browser.

An online source (OnlineSource) says:
- name (a slug, in the GUI's requests), title, home (its https:// page: the
  credit, and what --list prints with the other sources), note;
- hosts: the only hosts it reaches (its API, its files, its thumbnails), and
  thumb_hosts, those its thumbnails come from;
- accept: what fetch() gives, "image" or "dir";
- search(query, page): {"items": [item(), ...], "page": n, "pages": n};
- fetch(id): the local path of an item, downloaded once (kept and reused).

Network rules (get()): https:// only, to the source's hosts only (redirects
included), a time limit, a size limit. Nothing is requested until the GUI's
panel asks. Thumbnails reach the page through the GUI's server (thumbnail()),
decoded and written again as JPEG there: the page still loads images from the
server only.
"""
import contextlib
import http.client
import io
import json
import os
import re
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from PIL import Image

from .. import __version__
from .paths import cache_dir
from .sources import link, tidy

TIMEOUT = 20                 # seconds, per request
MAX_JSON = 4 << 20           # bytes of an API answer
MAX_THUMB = 4 << 20          # bytes of a thumbnail
MAX_DOWNLOAD = 200 << 20     # bytes of a downloaded file
IMAGE_FORMATS = {"JPEG", "PNG", "WEBP", "GIF"}


class NetworkError(Exception):
    """A request that failed or was refused: its message is shown to the user."""


def downloads():
    return cache_dir() / "downloads"


def item(id, label, note="", thumb=None, url=None):
    """One result of a search: id (what fetch() takes), label and note (shown),
    thumb (an image URL on one of the source's thumb_hosts), url (its page)."""
    return {"id": str(id), "label": label, "note": note or "", "thumb": thumb, "url": url}


def check_url(url, hosts):
    """url, when it is https:// on one of hosts (port 443, no user name), else
    NetworkError."""
    u = urllib.parse.urlsplit(str(url))
    try:
        port = u.port
    except ValueError:
        port = -1
    if u.scheme != "https" or u.hostname not in hosts or port not in (None, 443) \
            or u.username is not None or u.password is not None:
        raise NetworkError(f"refused: {url} is not an https:// address of "
                           f"{', '.join(sorted(hosts))}")
    return url


class _Redirects(urllib.request.HTTPRedirectHandler):
    """Follows a redirect only to an allowed host, over https."""

    def __init__(self, hosts):
        self.hosts = hosts

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_url(urllib.parse.urljoin(req.full_url, newurl), self.hosts)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _open(url, hosts):
    """The response for url; the opener is built here so that only https and the
    checked redirects are possible."""
    opener = urllib.request.build_opener(_Redirects(hosts))
    req = urllib.request.Request(url, headers={"User-Agent": f"catppuccinizer/{__version__}"})
    return opener.open(req, timeout=TIMEOUT)


def get(url, hosts, limit, out=None):
    """The bytes at url, or, with out (an open binary file), the number of bytes
    written to it. NetworkError when it is refused (check_url), fails, or is over
    limit bytes."""
    check_url(url, hosts)
    host = urllib.parse.urlsplit(url).hostname
    chunks, total = [], 0
    try:
        with _open(url, hosts) as r:
            size = r.headers.get("Content-Length", "")
            if size.isdigit() and int(size) > limit:
                raise NetworkError(f"{host}: over {limit >> 20} MB")
            while True:
                b = r.read(1 << 16)
                if not b:
                    break
                total += len(b)
                if total > limit:
                    raise NetworkError(f"{host}: over {limit >> 20} MB")
                if out is None:
                    chunks.append(b)
                else:
                    out.write(b)
    except urllib.error.HTTPError as e:
        e.close()
        hint = ", too many requests: wait a minute" if e.code == 429 else ""
        raise NetworkError(f"{host}: HTTP {e.code}{hint}") from None
    except urllib.error.URLError as e:
        raise NetworkError(f"{host}: {e.reason} (no network?)") from None
    except (OSError, http.client.HTTPException) as e:
        raise NetworkError(f"{host}: {e or type(e).__name__}") from None
    return total if out is not None else b"".join(chunks)


def download(url, hosts, dest, limit=MAX_DOWNLOAD):
    """url saved as dest: written to a temporary file next to it, renamed when
    complete (never a half-written file). The folders are the user's only (700)."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, tmp = tempfile.mkstemp(dir=dest.parent, prefix=f".{dest.name}.", suffix=".part")
    try:
        with os.fdopen(fd, "wb") as f:
            get(url, hosts, limit, out=f)
        os.chmod(tmp, 0o600)
        os.replace(tmp, dest)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise
    return dest


def thumbnail(source, url, size=256):
    """The thumbnail at url (one of the source's thumb_hosts) as JPEG bytes, at most
    size pixels: decoded and written again, so that only a plain image reaches the
    page."""
    data = get(check_url(url, source.thumb_hosts), source.thumb_hosts, MAX_THUMB)
    try:
        with Image.open(io.BytesIO(data)) as im:
            if im.format not in IMAGE_FORMATS:
                raise NetworkError(f"not an image: {url}")
            im.draft("RGB", (size, size))
            im = im.convert("RGB")
    except (OSError, ValueError, Image.DecompressionBombError) as e:
        raise NetworkError(f"not an image: {url} ({e})") from None
    im.thumbnail((size, size), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=85)
    return buf.getvalue()


def check_image(path):
    """path when it is an image Pillow reads, else NetworkError (the file removed)."""
    try:
        with Image.open(path) as im:
            if im.format not in IMAGE_FORMATS:
                raise OSError(f"{im.format} file")
            im.verify()
    except (OSError, ValueError, Image.DecompressionBombError) as e:
        path.unlink(missing_ok=True)
        raise NetworkError(f"the download is not an image ({e})") from None
    return path


class OnlineSource:
    name = ""                    # slug: the GUI's requests name it
    title = ""
    home = ""                    # https:// page of the site
    note = ""
    hosts = frozenset()          # every host it reaches
    thumb_hosts = frozenset()    # the hosts of its thumbnails
    accept = "image"             # what fetch() gives: "image" or "dir"

    def link(self):
        """As one of the other sources' links (--list)."""
        return link(self.title, self.home, self.note)

    def info(self):
        """What the GUI's page needs."""
        return {"name": self.name, "title": self.title, "home": self.home,
                "note": self.note, "accept": self.accept, "folder": tidy(self.folder())}

    def folder(self):
        return downloads() / self.name

    def json(self, url):
        try:
            return json.loads(get(url, self.hosts, MAX_JSON))
        except ValueError:
            raise NetworkError(f"{self.title}: an answer that is not JSON") from None

    def search(self, query="", page=1):
        raise NotImplementedError

    def fetch(self, item_id):
        raise NotImplementedError


def _dict(value):
    return value if isinstance(value, dict) else {}


def _int(value, default):
    return value if isinstance(value, int) and not isinstance(value, bool) else default


def _size(n):
    return f"{n / (1 << 20):.1f} MB" if n >= 1 << 20 else f"{max(n, 0) >> 10} KB"


class Wallhaven(OnlineSource):
    """wallhaven.cc through its API (https://wallhaven.cc/help/api): no key, images
    safe for work only (purity 100), general and anime categories (people: photos of
    people, rarely a wallpaper for a theme)."""
    name = "wallhaven"
    title = "Wallhaven"
    home = "https://wallhaven.cc"
    note = ("a large wallpaper collection, searchable by tag and colour (the GUI shows "
            "its safe for work images); each keeps its author's rights")
    API = "https://wallhaven.cc/api/v1"
    hosts = frozenset({"wallhaven.cc", "w.wallhaven.cc", "th.wallhaven.cc"})
    thumb_hosts = frozenset({"th.wallhaven.cc"})
    files = frozenset({"w.wallhaven.cc"})
    ID = re.compile(r"[a-z0-9]{1,16}")
    EXTS = {".jpg", ".jpeg", ".png", ".webp"}

    def search(self, query="", page=1):
        query = str(query).strip()[:200]
        page = min(max(_int(page, 1), 1), 1000)
        params = {"q": query, "categories": "110", "purity": "100", "page": page,
                  "sorting": "relevance" if query else "toplist"}
        d = _dict(self.json(f"{self.API}/search?{urllib.parse.urlencode(params)}"))
        items = []
        for w in d.get("data") or []:
            w = _dict(w)
            wid = str(w.get("id", ""))
            thumb = _dict(w.get("thumbs")).get("small")
            if not self.ID.fullmatch(wid) or w.get("purity") != "sfw" or not isinstance(thumb, str):
                continue
            note = " · ".join(x for x in (_size(_int(w.get("file_size"), 0)) if w.get("file_size") else "",
                                          str(w.get("category") or "")) if x)
            items.append(item(wid, str(w.get("resolution") or wid), note, thumb,
                              f"https://wallhaven.cc/w/{wid}"))
        meta = _dict(d.get("meta"))
        return {"items": items, "page": _int(meta.get("current_page"), page),
                "pages": max(_int(meta.get("last_page"), 1), 1)}

    def fetch(self, item_id):
        item_id = str(item_id)
        if not self.ID.fullmatch(item_id):
            raise NetworkError(f"not a Wallhaven id: {item_id}")
        for kept in sorted(self.folder().glob(f"wallhaven-{item_id}.*")):
            if kept.suffix.lower() in self.EXTS and kept.is_file() and not kept.is_symlink():
                return kept
        w = _dict(_dict(self.json(f"{self.API}/w/{item_id}")).get("data"))
        if w.get("purity") != "sfw":
            raise NetworkError(f"{item_id}: not a safe for work image")
        url = check_url(w.get("path", ""), self.files)
        ext = Path(urllib.parse.urlsplit(url).path).suffix.lower()
        if ext not in self.EXTS:
            raise NetworkError(f"{item_id}: not a JPEG, PNG or WebP image")
        return check_image(download(url, self.files, self.folder() / f"wallhaven-{item_id}{ext}"))


WALLHAVEN = Wallhaven()
