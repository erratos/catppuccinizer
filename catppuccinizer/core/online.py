"""Online sources: other sources the GUI browses itself (Target.online), as a grid
of thumbnails filled by a site's API; choosing one downloads it into the cache
(downloads(): ~/.cache/catppuccinizer/downloads/<source>/) and gives its path to
the source argument, like a file chosen with the file browser.

An online source (OnlineSource) says:
- name (a slug, in the GUI's requests), title, home (its https:// page: the
  credit, and what --list prints with the other sources), note;
- hosts: the only hosts it reaches (its API, its files, its thumbnails), and
  thumb_hosts, those its thumbnails come from; "*.example.org" stands for the
  site's own subdomains (files01.example.org…);
- accept: what fetch() gives, "image" or "dir" (then marker: a file every theme
  folder has, a glob as core.sources.theme_folders() takes);
- search(query, page): {"items": [item(), ...], "page": n, "pages": n};
- fetch(id): the local paths of an item, downloaded once (kept and reused): an
  image, or the theme folders found in an archive (unpacked(): one or more).

Network rules (get()): https:// only, to the source's hosts only (redirects
included), a time limit, a size limit. Nothing is requested until the GUI's
panel asks. Thumbnails reach the page through the GUI's server (thumbnail()),
decoded and written again as JPEG there: the page still loads images from the
server only.
"""
import contextlib
import hashlib
import http.client
import io
import json
import os
import re
import shutil
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from PIL import Image

from .. import __version__
from .archives import extract, is_archive, suffix
from .naming import slug
from .paths import cache_dir
from .sources import link, tidy

TIMEOUT = 20                 # seconds, per request
MAX_JSON = 4 << 20           # bytes of an API answer
MAX_THUMB = 4 << 20          # bytes of a thumbnail
MAX_DOWNLOAD = 200 << 20     # bytes of a downloaded file
IMAGE_FORMATS = {"JPEG", "PNG", "WEBP", "GIF"}
IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp")
MAX_THEMES = 50              # theme folders listed from one archive
THEME_DEPTH = 4              # how deep they are looked for in it


class NetworkError(Exception):
    """A request that failed or was refused: its message is shown to the user."""


def downloads():
    return cache_dir() / "downloads"


def item(id, label, note="", thumb=None, url=None, choices=None):
    """One result of a search: id (what fetch() takes), label and note (shown),
    thumb (an image URL on one of the source's thumb_hosts), url (its page),
    choices: the files of an item that has several (variants), item()s without
    thumb, one of which the GUI asks for (their id is what fetch() takes)."""
    return {"id": str(id), "label": label, "note": note or "", "thumb": thumb, "url": url,
            "choices": list(choices) if choices else None}


def host_allowed(host, hosts):
    """Whether host is one of hosts, "*.example.org" taking every subdomain of
    example.org (not example.org itself)."""
    return bool(host) and any(host == h or (h.startswith("*.") and host.endswith(h[1:]))
                              for h in hosts)


def check_url(url, hosts):
    """url, when it is https:// on one of hosts (port 443, no user name), else
    NetworkError."""
    u = urllib.parse.urlsplit(str(url))
    try:
        port = u.port
    except ValueError:
        port = -1
    if u.scheme != "https" or not host_allowed(u.hostname, hosts) or port not in (None, 443) \
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


def quoted(url):
    """url with the characters a request line cannot hold (spaces, accents: a file
    name as a site gives it) percent-encoded; what is already encoded stays."""
    u = urllib.parse.urlsplit(str(url))
    safe = "/%:@!$&'()*+,;=-._~"
    return urllib.parse.urlunsplit((u.scheme, u.netloc, urllib.parse.quote(u.path, safe=safe),
                                    urllib.parse.quote(u.query, safe=safe + "?"), ""))


def get(url, hosts, limit, out=None):
    """The bytes at url, or, with out (an open binary file), the number of bytes
    written to it. NetworkError when it is refused (check_url), fails, or is over
    limit bytes."""
    url = quoted(check_url(url, hosts))
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
        limited = e.code == 429 or (e.code == 403 and e.headers is not None
                                    and e.headers.get("X-RateLimit-Remaining") == "0")
        e.close()
        hint = ", too many requests: wait a while" if limited else ""
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


DIGESTS = {"md5": 32, "sha256": 64}           # hex digits


def check_digest(path, digest, algo="md5"):
    """path when its digest (algo: md5, sha256) is digest, when the site gives one
    (hex digits), else NetworkError (the file removed): a download cut short or
    changed on the way."""
    digest = str(digest or "").lower()
    if not re.fullmatch(rf"[0-9a-f]{{{DIGESTS[algo]}}}", digest):
        return path
    h = hashlib.new(algo, usedforsecurity=False)
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    if h.hexdigest() != digest:
        path.unlink(missing_ok=True)
        raise NetworkError(f"{path.name}: the download does not match its checksum")
    return path


def archive_stem(name):
    """'Dnd Classic.tar.gz' -> 'dnd-classic': the archive's name without its
    extensions, as a folder name."""
    n = Path(str(name)).name
    ext = suffix(n) or Path(n).suffix
    return slug(n[:len(n) - len(ext)], "theme")


def theme_dirs(root, marker):
    """The theme folders under root (root itself included): those with a file
    matching marker, not looked into (a theme's own subfolders are not themes), at
    most THEME_DEPTH folders down, MAX_THEMES of them, by path."""
    found, root = [], Path(root)
    for d, dirs, _ in os.walk(root):
        d = Path(d)
        if any(d.glob(marker)):
            found.append(d)
            dirs.clear()
            continue
        dirs[:] = sorted(n for n in dirs if not n.startswith(".")) \
            if len(d.relative_to(root).parts) < THEME_DEPTH else []
    return sorted(found)[:MAX_THEMES]


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
    marker = None                # "dir": a file every theme folder has

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

    def unpacked(self, url, hosts, dest, filename, digest=None, algo="md5"):
        """The theme folders (marker) of the archive at url, unpacked once into
        dest/<archive_stem(filename)>/: downloaded next to it, checked against
        digest when given (check_digest), unpacked (core.archives.extract), then the
        archive removed. An archive without a theme folder is removed too, with a
        NetworkError."""
        dest = Path(dest)
        root = dest / archive_stem(filename)
        if not root.is_dir():
            arc = dest / f".download{suffix(filename)}"
            try:
                check_digest(download(url, hosts, arc), digest, algo)
                extract(arc, root)
            finally:
                arc.unlink(missing_ok=True)
        found = theme_dirs(root, self.marker)
        if not found:
            shutil.rmtree(root, ignore_errors=True)
            raise NetworkError(f"{filename}: no {self.marker} in it, not a theme for this")
        return found


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
                return [kept]
        w = _dict(_dict(self.json(f"{self.API}/w/{item_id}")).get("data"))
        if w.get("purity") != "sfw":
            raise NetworkError(f"{item_id}: not a safe for work image")
        url = check_url(w.get("path", ""), self.files)
        ext = Path(urllib.parse.urlsplit(url).path).suffix.lower()
        if ext not in self.EXTS:
            raise NetworkError(f"{item_id}: not a JPEG, PNG or WebP image")
        return [check_image(download(url, self.files, self.folder() / f"wallhaven-{item_id}{ext}"))]


WALLHAVEN = Wallhaven()


# ---------------------------------------------------------------------- OCS
# the stores of the pling network (Open Collaboration Services API, the one of
# KDE's "Get New…"): title, site, API host
STORES = {
    "gnome-look": ("Gnome-look", "https://www.gnome-look.org", "api.gnome-look.org"),
    "kde-store": ("KDE Store", "https://store.kde.org", "api.kde-look.org"),
}
OCS_FILES = frozenset({"*.pling.com", "ocs-dl.fra1.cdn.digitaloceanspaces.com"})
OCS_THUMBS = frozenset({"images.pling.com"})
OCS_PAGE = 24
OCS_THUMB_SIZE = "280x171-2"     # a size images.pling.com/cache/ serves


class Ocs(OnlineSource):
    """A category of a store of the pling network (STORES) through its OCS API:
    https://<api>/ocs/v1/content/data?categories=N. Each item may have several
    files (variants): only those this target takes are offered (archives for a
    folder, .rar and others left out; images for an image), free ones only. The
    link of a file is a token that expires: fetch() asks for it again."""
    ID = re.compile(r"(\d{1,10})-(\d{1,3})")

    def __init__(self, store, category, title=None, note="", accept="dir", marker=None):
        if store not in STORES:
            raise ValueError(f"unknown store {store!r} (known: {', '.join(STORES)})")
        if not isinstance(category, int) or isinstance(category, bool) or not 0 < category < 1 << 31:
            raise ValueError(f"an OCS category is a positive number, not {category!r}")
        if accept not in ("dir", "image") or (accept == "dir") != bool(marker):
            raise ValueError("an OCS source gives a theme folder (with its marker) or an image")
        store_title, self.site, self.api = STORES[store]
        self.store, self.category, self.accept, self.marker = store, category, accept, marker
        self.name = f"{store}-{category}"
        self.title = title or f"{store_title}: category {category}"
        self.home = f"{self.site}/browse?cat={category}"
        self.note = note or (f"{store_title}'s {'themes' if accept == 'dir' else 'images'}, "
                             "each with its own licence")
        self.thumb_hosts = OCS_THUMBS
        self.hosts = frozenset({self.api, *OCS_FILES, *OCS_THUMBS})

    def usable(self, name):
        name = str(name).lower()
        return is_archive(name) if self.accept == "dir" else name.endswith(IMAGE_EXTS)

    def files(self, x):
        """{n: (name, size in bytes, link, md5)} of the files of an item this source
        gives (downloadlinkN…)."""
        out = {}
        for n in range(1, 100):
            link_, name = x.get(f"downloadlink{n}"), x.get(f"downloadname{n}")
            if not isinstance(link_, str) or not link_:
                if f"downloadlink{n}" not in x:
                    break
                continue
            price = str(x.get(f"downloadprice{n}") or "0")
            if not isinstance(name, str) or not self.usable(name) or price not in ("0", "0.0", "0.00"):
                continue
            size = x.get(f"downloadsize{n}")
            size = int(size) << 10 if isinstance(size, int) or str(size).isdigit() else 0   # KB
            out[n] = (name, size, link_, x.get(f"downloadmd5sum{n}"))
        return out

    def search(self, query="", page=1):
        query = str(query).strip()[:200]
        page = min(max(_int(page, 1), 1), 1000)
        params = {"categories": self.category, "format": "json", "pagesize": OCS_PAGE,
                  "page": page - 1, "sortmode": "down", **({"search": query} if query else {})}
        d = _dict(self.json(f"https://{self.api}/ocs/v1/content/data?{urllib.parse.urlencode(params)}"))
        if d.get("statuscode") != 100:
            raise NetworkError(f"{self.title}: {d.get('message') or 'the request failed'}")
        items = []
        for x in d.get("data") if isinstance(d.get("data"), list) else []:
            x = _dict(x)
            cid = x.get("id")
            files = self.files(x)
            if not isinstance(cid, int) or isinstance(cid, bool) or cid <= 0 \
                    or x.get("ghns_excluded") in (1, "1") or not files:
                continue
            thumb = x.get("smallpreviewpic1") or x.get("previewpic1")
            thumb = re.sub(r"^(https://images\.pling\.com/cache/)[^/]+/", rf"\g<1>{OCS_THUMB_SIZE}/",
                           thumb) if isinstance(thumb, str) else None
            downloads = x.get("downloads")
            downloads = f"{int(downloads):,} downloads" if str(downloads).isdigit() else ""
            choices = [item(f"{cid}-{n}", name, _size(size) if size else "")
                       for n, (name, size, _, _) in files.items()]
            n, (name, size, _, _) = next(iter(files.items()))
            note = " · ".join(v for v in ((_size(size) if size else "") if len(files) == 1
                                          else f"{len(files)} files", downloads) if v)
            items.append(item(f"{cid}-{n}", str(x.get("name") or cid)[:120], note, thumb,
                              f"{self.site}/p/{cid}", choices if len(files) > 1 else None))
        total = _int(d.get("totalitems"), 0)
        return {"items": items, "page": page, "pages": max(-(-total // OCS_PAGE), 1)}

    def fetch(self, item_id):
        m = self.ID.fullmatch(str(item_id))
        if not m:
            raise NetworkError(f"not an item of {self.title}: {item_id}")
        cid, n = int(m.group(1)), int(m.group(2))
        d = _dict(self.json(f"https://{self.api}/ocs/v1/content/data/{cid}?format=json"))
        data = d.get("data")
        x = _dict(data[0] if isinstance(data, list) and data else data)
        if d.get("statuscode") != 100 or x.get("id") != cid:
            raise NetworkError(f"{self.title}: no item {cid}")
        if n not in (files := self.files(x)):
            raise NetworkError(f"{self.title}: item {cid} has no file {n} this tool takes")
        name, size, url, md5 = files[n]
        if size > MAX_DOWNLOAD:
            raise NetworkError(f"{name}: over {MAX_DOWNLOAD >> 20} MB")
        md5 = str(md5 or "").lower()
        dest = self.folder() / f"{cid}-{n}-{md5[:8] if re.fullmatch(r'[0-9a-f]{32}', md5) else 'x'}"
        if self.accept == "dir":
            return self.unpacked(url, self.hosts, dest, name, md5)
        kept = dest / f"{slug(Path(name).stem, 'image')}{Path(name).suffix.lower()}"
        if kept.is_file() and not kept.is_symlink():
            return [kept]
        return [check_image(check_digest(download(url, self.hosts, kept), md5))]


KDE_WALLPAPERS = Ocs("kde-store", 299, "KDE Store: wallpapers", accept="image",
                     note="wallpapers shared by the KDE community, each with its own licence "
                          "(its images only: wallpaper packages are left out)")


# ------------------------------------------------------------ GitHub release
GITHUB_HOSTS = frozenset({"api.github.com", "github.com", "release-assets.githubusercontent.com",
                          "objects.githubusercontent.com"})
GITHUB_PAGE = 60
REPO = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9._-]{1,100}")
ASSET = re.compile(r"([A-Za-z0-9][A-Za-z0-9._+-]{0,99})/([A-Za-z0-9][A-Za-z0-9._+-]{0,199})")


class GithubRelease(OnlineSource):
    """The archives of a GitHub repository's latest release, one theme each
    (adi1090x/plymouth-themes: one .tar.gz per theme): listed through the API
    (one request, without a key: 60 an hour), downloaded from the release, checked
    against the digest GitHub gives (newer assets), unpacked. No thumbnails: a
    release has none (a repository's README may show previews: its page is the
    item's link)."""
    thumb_hosts = frozenset()
    hosts = GITHUB_HOSTS

    def __init__(self, repo, title, note="", marker=None):
        if not REPO.fullmatch(repo) or ".." in repo:
            raise ValueError(f"not a GitHub repository: {repo!r} (owner/name)")
        if not marker:
            raise ValueError("a GitHub release source gives theme folders: give their marker")
        self.repo, self.title, self.marker, self.accept = repo, title, marker, "dir"
        self.name = "github-" + slug(repo)
        self.home = f"https://github.com/{repo}"
        self.note = note or f"the themes of {repo}'s latest release"

    def search(self, query="", page=1):
        query = re.sub(r"[\s_-]+", " ", str(query).strip().lower())[:200]
        page = min(max(_int(page, 1), 1), 1000)
        r = _dict(self.json(f"https://api.github.com/repos/{self.repo}/releases/latest"))
        tag = str(r.get("tag_name") or "")
        assets = []
        for a in r.get("assets") if isinstance(r.get("assets"), list) else []:
            a = _dict(a)
            name = a.get("name")
            if not isinstance(name, str) or not is_archive(name) or not ASSET.fullmatch(f"{tag}/{name}"):
                continue
            label = re.sub(r"[_-]+", " ", archive_stem(name)).capitalize()
            if query in label.lower():
                assets.append((-_int(a.get("download_count"), 0), label, name, _int(a.get("size"), 0)))
        assets.sort()
        pages = max(-(-len(assets) // GITHUB_PAGE), 1)
        page = min(page, pages)
        items = [item(f"{tag}/{name}", label, " · ".join(
                     v for v in (_size(size) if size else "", f"{-count:,} downloads" if count else "") if v),
                     url=self.home)
                 for count, label, name, size in assets[(page - 1) * GITHUB_PAGE:page * GITHUB_PAGE]]
        return {"items": items, "page": page, "pages": pages}

    def fetch(self, item_id):
        m = ASSET.fullmatch(str(item_id))
        if not m or ".." in item_id or not is_archive(m.group(2)):
            raise NetworkError(f"not a theme of {self.title}: {item_id}")
        tag, name = m.groups()
        dest = self.folder() / slug(tag, "release")
        url = digest = None
        if not (dest / archive_stem(name)).is_dir():   # not kept: its size and digest first
            r = _dict(self.json(f"https://api.github.com/repos/{self.repo}/releases/tags/"
                                f"{urllib.parse.quote(tag)}"))
            a = next((_dict(a) for a in r.get("assets") or [] if _dict(a).get("name") == name), None)
            if a is None:
                raise NetworkError(f"{self.title}: no {name} in release {tag}")
            if _int(a.get("size"), 0) > MAX_DOWNLOAD:
                raise NetworkError(f"{name}: over {MAX_DOWNLOAD >> 20} MB")
            algo, _, value = str(a.get("digest") or "").partition(":")
            digest = value if algo == "sha256" else None
            url = f"https://github.com/{self.repo}/releases/download/{urllib.parse.quote(tag)}/{name}"
        return self.unpacked(url, self.hosts, dest, name, digest, "sha256")
