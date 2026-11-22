"""Online sources (core.online) and safe archives (core.archives), without network:
the requests are answered by a fake opener."""
import hashlib
import io
import json
import os
import shutil
import stat
import sys
import tarfile
import tempfile
import unittest
import urllib.error
import zipfile
from pathlib import Path
from unittest import mock

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.dont_write_bytecode = True

from catppuccinizer.core import archives, online  # noqa: E402
from catppuccinizer.core.archives import ArchiveError  # noqa: E402
from catppuccinizer.core.online import KDE_WALLPAPERS, WALLHAVEN, NetworkError, Ocs  # noqa: E402


def png_bytes(size=(8, 8), fmt="PNG"):
    buf = io.BytesIO()
    Image.new("RGB", size, (30, 30, 46)).save(buf, fmt)
    return buf.getvalue()


class Response:
    """What urllib's opener returns, enough for online.get()."""

    def __init__(self, data, length=True):
        self.data = io.BytesIO(data)
        self.headers = {"Content-Length": str(len(data))} if length else {}

    def read(self, n=-1):
        return self.data.read(n)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def answers(routes):
    """A fake online._open: url -> bytes (or an exception), the URLs asked kept."""
    asked = []

    def fake(url, hosts):
        asked.append(url)
        for prefix, value in routes.items():
            if url.startswith(prefix):
                if isinstance(value, Exception):
                    raise value
                return Response(value)
        raise AssertionError(f"unexpected request: {url}")
    return fake, asked


SEARCH = {"data": [
    {"id": "abc123", "purity": "sfw", "category": "general", "resolution": "3840x2160",
     "file_size": 3 << 20, "thumbs": {"small": "https://th.wallhaven.cc/small/ab/abc123.jpg"}},
    {"id": "nsfw01", "purity": "nsfw", "thumbs": {"small": "https://th.wallhaven.cc/small/x.jpg"}},
    {"id": "../bad", "purity": "sfw", "thumbs": {"small": "https://th.wallhaven.cc/small/y.jpg"}},
    "not a dict",
], "meta": {"current_page": 2, "last_page": 9}}


class Tmp(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="catppuccinizer-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        env = mock.patch.dict(os.environ, {"CATPPUCCINIZER_CACHE": str(self.tmp / "cache")})
        env.start()
        self.addCleanup(env.stop)


class Requests(Tmp):
    HOSTS = frozenset({"example.org"})

    def test_check_url(self):
        self.assertEqual(online.check_url("https://example.org/a?b=1", self.HOSTS), "https://example.org/a?b=1")
        for url in ("http://example.org/", "https://other.org/", "https://example.org:8443/",
                    "https://user@example.org/", "javascript:alert(1)", "file:///etc/passwd",
                    "https://example.org.evil.com/", "", "https://example.org:bad/"):
            with self.subTest(url=url), self.assertRaises(NetworkError):
                online.check_url(url, self.HOSTS)

    def test_subdomains(self):
        hosts = frozenset({"*.example.org", "cdn.other.net"})
        for url in ("https://files06.example.org/a", "https://a.b.example.org/", "https://cdn.other.net/x"):
            self.assertEqual(online.check_url(url, hosts), url)
        for url in ("https://example.org/", "https://evilexample.org/", "https://example.org.evil.com/",
                    "https://x.cdn.other.net/", "https://other.net/"):
            with self.subTest(url=url), self.assertRaises(NetworkError):
                online.check_url(url, hosts)

    def test_quoted(self):
        """A file name as a site gives it (spaces, accents) is encoded; what is already
        encoded stays as it is."""
        self.assertEqual(online.quoted("https://example.org/a/My Theme é.png?x=1 2"),
                         "https://example.org/a/My%20Theme%20%C3%A9.png?x=1%202")
        self.assertEqual(online.quoted("https://example.org/a%20b/c.tar.gz?s=a%2Fb&t=1"),
                         "https://example.org/a%20b/c.tar.gz?s=a%2Fb&t=1")

    def test_rate_limit(self):
        err = urllib.error.HTTPError("https://example.org/", 403, "Forbidden",
                                     {"X-RateLimit-Remaining": "0"}, io.BytesIO())
        self.addCleanup(err.close)
        with mock.patch.object(online, "_open", side_effect=err):
            with self.assertRaisesRegex(NetworkError, "HTTP 403, too many requests"):
                online.get("https://example.org/", self.HOSTS, 99)

    def test_md5(self):
        f = self.tmp / "f.bin"
        f.write_bytes(b"theme")
        good = hashlib.md5(b"theme").hexdigest()
        self.assertEqual(online.check_md5(f, good.upper()), f)
        self.assertEqual(online.check_md5(f, ""), f)                     # not given: not checked
        with self.assertRaisesRegex(NetworkError, "checksum"):
            online.check_md5(f, "0" * 32)
        self.assertFalse(f.exists())

    def test_redirects_stay_on_the_hosts(self):
        handler = online._Redirects(self.HOSTS)
        req = mock.Mock(full_url="https://example.org/a")
        with self.assertRaises(NetworkError):
            handler.redirect_request(req, None, 302, "Found", {}, "https://evil.org/b")
        with self.assertRaises(NetworkError):
            handler.redirect_request(req, None, 302, "Found", {}, "http://example.org/b")

    def test_limits_and_errors(self):
        with mock.patch.object(online, "_open", return_value=Response(b"x" * 100)):
            self.assertEqual(online.get("https://example.org/", self.HOSTS, 100), b"x" * 100)
            with self.assertRaisesRegex(NetworkError, "over"):
                online.get("https://example.org/", self.HOSTS, 99)
        with mock.patch.object(online, "_open", return_value=Response(b"x" * 100, length=False)):
            with self.assertRaisesRegex(NetworkError, "over"):      # counted, not trusted
                online.get("https://example.org/", self.HOSTS, 99)
        err = urllib.error.HTTPError("https://example.org/", 429, "Too Many", {}, io.BytesIO())
        self.addCleanup(err.close)
        with mock.patch.object(online, "_open", side_effect=err):
            with self.assertRaisesRegex(NetworkError, "HTTP 429, too many requests"):
                online.get("https://example.org/", self.HOSTS, 99)
        with mock.patch.object(online, "_open", side_effect=urllib.error.URLError("Name or service not known")):
            with self.assertRaisesRegex(NetworkError, "no network"):
                online.get("https://example.org/", self.HOSTS, 99)

    def test_download_is_atomic(self):
        dest = self.tmp / "d/file.jpg"
        with mock.patch.object(online, "_open", return_value=Response(b"x" * 10)):
            with self.assertRaises(NetworkError):
                online.download("https://example.org/f", self.HOSTS, dest, limit=5)
            self.assertEqual(list(dest.parent.iterdir()), [])        # nothing half-written
            online.download("https://example.org/f", self.HOSTS, dest, limit=50)
        self.assertEqual(dest.read_bytes(), b"x" * 10)
        self.assertEqual(stat.S_IMODE(dest.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(dest.parent.stat().st_mode) & 0o077, 0)


class Thumbnails(Tmp):
    def test_thumbnail(self):
        fake, _ = answers({"https://th.wallhaven.cc/": png_bytes((600, 400), "JPEG")})
        with mock.patch.object(online, "_open", fake):
            data = online.thumbnail(WALLHAVEN, "https://th.wallhaven.cc/small/ab/abc123.jpg", 240)
        with Image.open(io.BytesIO(data)) as im:
            self.assertEqual((im.format, im.size), ("JPEG", (240, 160)))
        with self.assertRaises(NetworkError):         # not a thumbnail host
            online.thumbnail(WALLHAVEN, "https://w.wallhaven.cc/full/ab/x.jpg")
        fake, _ = answers({"https://th.wallhaven.cc/": b"<svg onload='x'/>"})
        with mock.patch.object(online, "_open", fake), self.assertRaisesRegex(NetworkError, "not an image"):
            online.thumbnail(WALLHAVEN, "https://th.wallhaven.cc/small/ab/abc123.jpg")


class Wallhaven(Tmp):
    def test_search(self):
        fake, asked = answers({"https://wallhaven.cc/api/v1/search": json.dumps(SEARCH).encode()})
        with mock.patch.object(online, "_open", fake):
            r = WALLHAVEN.search(" forest ", 2)
            WALLHAVEN.search("", "x")
        self.assertEqual((r["page"], r["pages"]), (2, 9))
        self.assertEqual(r["items"], [{"id": "abc123", "label": "3840x2160", "note": "3.0 MB · general",
                                       "thumb": "https://th.wallhaven.cc/small/ab/abc123.jpg",
                                       "url": "https://wallhaven.cc/w/abc123", "choices": None}])
        self.assertIn("q=forest", asked[0])
        for part in ("purity=100", "categories=110", "sorting=relevance", "page=2"):
            self.assertIn(part, asked[0])
        self.assertIn("sorting=toplist", asked[1])            # nothing typed: the popular ones
        self.assertIn("page=1", asked[1])

    def test_fetch(self):
        info = {"data": {"id": "abc123", "purity": "sfw", "path": "https://w.wallhaven.cc/full/ab/wallhaven-abc123.png"}}
        fake, asked = answers({"https://wallhaven.cc/api/v1/w/abc123": json.dumps(info).encode(),
                               "https://w.wallhaven.cc/full/": png_bytes()})
        with mock.patch.object(online, "_open", fake):
            p = WALLHAVEN.fetch("abc123")
            self.assertEqual(p, [self.tmp / "cache/downloads/wallhaven/wallhaven-abc123.png"])
            self.assertEqual(WALLHAVEN.fetch("abc123"), p)                # kept: no new request
        self.assertEqual(len(asked), 2)
        with self.assertRaisesRegex(NetworkError, "not a Wallhaven id"):
            WALLHAVEN.fetch("../../etc")

    def test_fetch_refuses(self):
        cases = {
            "foreign": {"purity": "sfw", "path": "https://evil.org/x.png"},
            "nsfw": {"purity": "nsfw", "path": "https://w.wallhaven.cc/full/ab/x.png"},
            "svg": {"purity": "sfw", "path": "https://w.wallhaven.cc/full/ab/x.svg"},
        }
        for wid, data in cases.items():
            fake, asked = answers({f"https://wallhaven.cc/api/v1/w/{wid}": json.dumps({"data": data}).encode()})
            with self.subTest(case=wid), mock.patch.object(online, "_open", fake), self.assertRaises(NetworkError):
                WALLHAVEN.fetch(wid)
            self.assertEqual(len(asked), 1)                          # never downloaded
        info = {"data": {"purity": "sfw", "path": "https://w.wallhaven.cc/full/ab/wallhaven-fake01.jpg"}}
        fake, _ = answers({"https://wallhaven.cc/api/v1/w/fake01": json.dumps(info).encode(),
                           "https://w.wallhaven.cc/full/": b"<html>not an image</html>"})
        with mock.patch.object(online, "_open", fake), self.assertRaisesRegex(NetworkError, "not an image"):
            WALLHAVEN.fetch("fake01")
        self.assertEqual(list((self.tmp / "cache/downloads/wallhaven").glob("*fake01*")), [])


def tar_bytes(members):
    """A .tar.gz of members: (name, bytes)."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        for n, data in members:
            info = tarfile.TarInfo(n)
            info.size = len(data)
            t.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def ocs_item(cid, files, **extra):
    """An OCS content entry; files: (name, link, md5) for downloadnameN / linkN / md5sumN."""
    x = {"id": cid, "name": f"Theme {cid}", "downloads": "1234", "ghns_excluded": 0,
         "smallpreviewpic1": f"https://images.pling.com/cache/770x540-4/img/{cid}.png"}
    for n, (name, link, md5) in enumerate(files, 1):
        x.update({f"downloadname{n}": name, f"downloadlink{n}": link, f"downloadmd5sum{n}": md5,
                  f"downloadsize{n}": 2048, f"downloadprice{n}": "0"})
    return {**x, **extra}


GRUB = Ocs("gnome-look", 109, "Gnome-look: GRUB themes", marker="theme.txt")
API = "https://api.gnome-look.org/ocs/v1/content/data"
FILE = "https://files06.pling.com/api/files/download/j/token"


class OcsStore(Tmp):
    def test_declared(self):
        self.assertEqual((GRUB.name, GRUB.home), ("gnome-look-109", "https://www.gnome-look.org/browse?cat=109"))
        self.assertEqual((KDE_WALLPAPERS.name, KDE_WALLPAPERS.accept), ("kde-store-299", "image"))
        for bad in ({"store": "evil"}, {"category": "109"}, {"category": 0}, {"category": True},
                    {"marker": None}, {"accept": "image", "marker": "theme.txt"}):
            args = {"store": "gnome-look", "category": 109, "marker": "theme.txt", **bad}
            with self.subTest(**bad), self.assertRaises(ValueError):
                Ocs(**args)

    def test_search(self):
        data = {"statuscode": 100, "totalitems": 50, "data": [
            ocs_item(11, [("a.tar.gz", f"{FILE}/a.tar.gz", "")]),
            ocs_item(12, [("b.rar", f"{FILE}/b.rar", ""), ("b-dark.zip", f"{FILE}/b-dark.zip", ""),
                          ("b-light.tar.xz", f"{FILE}/b-light.tar.xz", "")]),
            ocs_item(13, [("c.rar", f"{FILE}/c.rar", "")]),                    # nothing usable
            ocs_item(14, [("d.zip", f"{FILE}/d.zip", "")], ghns_excluded=1),   # hidden by the store
            ocs_item(15, [("e.zip", f"{FILE}/e.zip", "")], downloadprice1="2"),  # paid
            ocs_item("16", [("f.zip", f"{FILE}/f.zip", "")]),                  # not an id
            "not a dict"]}
        fake, asked = answers({API: json.dumps(data).encode()})
        with mock.patch.object(online, "_open", fake):
            r = GRUB.search(" catppuccin ", 2)
            GRUB.search("", 1)
        self.assertEqual((r["page"], r["pages"]), (2, 3))
        a, b = r["items"]
        self.assertEqual(a, {"id": "11-1", "label": "Theme 11", "note": "2.0 MB · 1,234 downloads",
                             "thumb": "https://images.pling.com/cache/280x171-2/img/11.png",
                             "url": "https://www.gnome-look.org/p/11", "choices": None})
        self.assertEqual([c["id"] for c in b["choices"]], ["12-2", "12-3"])        # .rar left out
        self.assertEqual(b["note"], "2 files · 1,234 downloads")
        for part in ("categories=109", "search=catppuccin", "page=1", "pagesize=24", "format=json"):
            self.assertIn(part, asked[0])
        self.assertIn("page=0", asked[1])                                         # OCS counts from 0
        self.assertNotIn("search=", asked[1])
        fake, _ = answers({API: json.dumps({"statuscode": 999, "message": "unknown request"}).encode()})
        with mock.patch.object(online, "_open", fake), self.assertRaisesRegex(NetworkError, "unknown request"):
            GRUB.search("")

    def detail(self, cid, files):
        return {f"{API}/{cid}?": json.dumps({"statuscode": 100, "data": [ocs_item(cid, files)]}).encode()}

    def test_fetch_theme(self):
        arc = tar_bytes([("Neon Grub/theme.txt", b"x"), ("Neon Grub/bg.png", png_bytes())])
        md5 = hashlib.md5(arc).hexdigest()
        fake, asked = answers({**self.detail(21, [("Neon Grub.tar.gz", f"{FILE}/Neon Grub.tar.gz", md5)]),
                               FILE: arc})
        with mock.patch.object(online, "_open", fake):
            paths = GRUB.fetch("21-1")
            self.assertEqual(GRUB.fetch("21-1"), paths)        # kept: the link is asked again, no download
        root = self.tmp / f"cache/downloads/gnome-look-109/21-1-{md5[:8]}/neon-grub"
        self.assertEqual(paths, [root / "Neon Grub"])
        self.assertEqual([u.startswith(FILE) for u in asked], [False, True, False])
        self.assertEqual([p.name for p in root.parent.iterdir()], ["neon-grub"])     # archive removed

    def test_fetch_several_or_none(self):
        arc = tar_bytes([("theme.txt", b"top"), ("a/theme.txt", b"a")])   # the top folder is a theme
        fake, _ = answers({**self.detail(22, [("pack.tar.gz", f"{FILE}/pack.tar.gz", "")]), FILE: arc})
        with mock.patch.object(online, "_open", fake):
            (top,) = GRUB.fetch("22-1")                        # not looked into
        self.assertEqual(top.name, "pack")
        arc = tar_bytes([("x/a/theme.txt", b"a"), ("x/b/theme.txt", b"b"), ("x/readme", b"")])
        fake, _ = answers({**self.detail(23, [("two.zip.tar.gz", f"{FILE}/two.tar.gz", "")]), FILE: arc})
        with mock.patch.object(online, "_open", fake):
            self.assertEqual([p.name for p in GRUB.fetch("23-1")], ["a", "b"])
        arc = tar_bytes([("x/readme.txt", b"no theme")])
        fake, _ = answers({**self.detail(24, [("x.tar.gz", f"{FILE}/x.tar.gz", "")]), FILE: arc})
        with mock.patch.object(online, "_open", fake), self.assertRaisesRegex(NetworkError, "no theme.txt"):
            GRUB.fetch("24-1")
        self.assertEqual(list((self.tmp / "cache/downloads/gnome-look-109/24-1-x").iterdir()), [])

    def test_fetch_refuses(self):
        for iid in ("../1-1", "21", "21-1/../x", "1-1-1"):
            with self.subTest(id=iid), self.assertRaisesRegex(NetworkError, "not an item"):
                GRUB.fetch(iid)
        cases = {31: [("a.tar.gz", "https://evil.org/a.tar.gz", "")],          # not the store's host
                 32: [("a.rar", f"{FILE}/a.rar", "")],                          # not unpacked
                 33: [("a.tar.gz", f"{FILE}/a.tar.gz", "0" * 32)]}             # damaged
        for cid, files in cases.items():
            fake, asked = answers({**self.detail(cid, files), FILE: tar_bytes([("t/theme.txt", b"x")])})
            with self.subTest(cid=cid), mock.patch.object(online, "_open", fake), self.assertRaises(NetworkError):
                GRUB.fetch(f"{cid}-1")
        for d in (self.tmp / "cache/downloads/gnome-look-109").glob("*"):
            self.assertEqual(list(d.iterdir()), [], d)                         # nothing left

    def test_fetch_image(self):
        img = png_bytes()
        fake, _ = answers({f"https://api.kde-look.org/ocs/v1/content/data/41?": json.dumps(
            {"statuscode": 100, "data": [ocs_item(41, [("Pack.tar.xz", f"{FILE}/Pack.tar.xz", ""),
                                                       ("Blue Sky.PNG", f"{FILE}/Blue Sky.PNG", "")])]}).encode(),
            FILE: img})
        with mock.patch.object(online, "_open", fake):
            (p,) = KDE_WALLPAPERS.fetch("41-2")
            with self.assertRaisesRegex(NetworkError, "no file 1"):              # an archive: not an image
                KDE_WALLPAPERS.fetch("41-1")
        self.assertEqual(p, self.tmp / "cache/downloads/kde-store-299/41-2-x/blue-sky.png")
        self.assertEqual(p.read_bytes(), img)


class Archives(Tmp):
    def tar(self, members, name="a.tar.gz"):
        """members: (name, bytes | "dir" | "link" | "fifo")."""
        path = self.tmp / name
        with tarfile.open(path, "w:gz") as t:
            for n, data in members:
                info = tarfile.TarInfo(n)
                if data == "dir":
                    info.type = tarfile.DIRTYPE
                    t.addfile(info)
                elif data == "link":
                    info.type, info.linkname = tarfile.SYMTYPE, "/etc/passwd"
                    t.addfile(info)
                elif data == "fifo":
                    info.type = tarfile.FIFOTYPE
                    t.addfile(info)
                else:
                    info.size, info.mode = len(data), 0o4755           # setuid: not kept
                    t.addfile(info, io.BytesIO(data))
        return path

    def zip(self, members, name="a.zip"):
        path = self.tmp / name
        with zipfile.ZipFile(path, "w") as z:
            for n, data in members:
                if data == "link":
                    info = zipfile.ZipInfo(n)
                    info.external_attr = (stat.S_IFLNK | 0o777) << 16
                    z.writestr(info, "/etc/passwd")
                else:
                    z.writestr(n, data)
        return path

    def test_good_archives(self):
        for arc in (self.tar([("theme", "dir"), ("theme/theme.txt", b"x"), ("./theme/img/a.png", b"png"),
                              ("theme/link", "link"), ("theme/pipe", "fifo")]),
                    self.zip([("theme/theme.txt", b"x"), ("theme\\img\\a.png", b"png"), ("theme/link", "link")])):
            with self.subTest(archive=arc.name):
                dest = self.tmp / f"out-{arc.name}"
                skipped = archives.extract(arc, dest)
                self.assertEqual((dest / "theme/theme.txt").read_bytes(), b"x")
                self.assertEqual((dest / "theme/img/a.png").read_bytes(), b"png")
                self.assertFalse((dest / "theme/link").exists() or (dest / "theme/link").is_symlink())
                self.assertEqual(skipped, 2 if arc.suffix == ".gz" else 1)
                self.assertEqual(stat.S_IMODE((dest / "theme/theme.txt").stat().st_mode), 0o644)
                self.assertEqual(stat.S_IMODE((dest / "theme/img").stat().st_mode), 0o755)
                with self.assertRaisesRegex(ArchiveError, "already exists"):
                    archives.extract(arc, dest)

    def test_unsafe_names(self):
        for n in ("../evil.txt", "a/../../evil.txt", "/etc/evil.txt", "C:/evil.txt", "..\\evil.txt"):
            for make in (self.tar, self.zip):
                arc = make([("ok.txt", b"ok"), (n, b"evil")], name=f"x{'.zip' if make == self.zip else '.tar.gz'}")
                dest = self.tmp / "out"
                with self.subTest(name=n, kind=arc.suffix), self.assertRaisesRegex(ArchiveError, "unsafe name"):
                    archives.extract(arc, dest)
                self.assertFalse(dest.exists())
                self.assertFalse((self.tmp / "evil.txt").exists())
                self.assertEqual([p.name for p in self.tmp.iterdir() if p.name.startswith(".")], [])

    def test_limits(self):
        arc = self.zip([(f"f{i}.txt", b"x" * 100) for i in range(5)])
        with self.assertRaisesRegex(ArchiveError, "more than 4 files"):
            archives.extract(arc, self.tmp / "o1", max_files=4)
        with self.assertRaisesRegex(ArchiveError, "MB once unpacked"):
            archives.extract(arc, self.tmp / "o2", max_total=450)
        self.assertEqual(archives.extract(arc, self.tmp / "o3", max_total=500), 0)

    def test_not_an_archive(self):
        (self.tmp / "a.rar").write_bytes(b"Rar!")
        with self.assertRaisesRegex(ArchiveError, "not an archive this tool unpacks"):
            archives.extract(self.tmp / "a.rar", self.tmp / "o")
        (self.tmp / "b.zip").write_bytes(b"not a zip")
        with self.assertRaises(ArchiveError):
            archives.extract(self.tmp / "b.zip", self.tmp / "o")
        self.assertTrue(archives.is_archive("x.TAR.GZ"))
        self.assertEqual([archives.suffix(n) for n in ("A.TAR.GZ", "b.tar", "c.zip", "d.rar", "e.gz")],
                         [".tar.gz", ".tar", ".zip", "", ""])
        self.assertEqual([online.archive_stem(n) for n in ("Neon Grub.tar.gz", "x.v2.zip", "?.tgz")],
                         ["neon-grub", "x-v2", "theme"])
        self.assertFalse(archives.is_archive("x.rar"))


if __name__ == "__main__":
    unittest.main()
