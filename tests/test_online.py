"""Online sources (core.online) and safe archives (core.archives), without network:
the requests are answered by a fake opener."""
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
from catppuccinizer.core.online import WALLHAVEN, NetworkError  # noqa: E402


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
                                       "url": "https://wallhaven.cc/w/abc123"}])
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
            self.assertEqual(p, self.tmp / "cache/downloads/wallhaven/wallhaven-abc123.png")
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
        self.assertFalse(archives.is_archive("x.rar"))


if __name__ == "__main__":
    unittest.main()
