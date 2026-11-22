"""Archives (.zip, .tar, .tar.gz, .tar.bz2, .tar.xz) unpacked safely, for what an
online source downloads (core.online).

extract() never writes outside its folder and keeps only plain files and folders:
- a name that is absolute or goes up (`..`) stops it (ArchiveError);
- links, hard links, devices and pipes are left out (counted);
- the number of files and the total size are limited, counted on what is really
  unpacked (an archive can lie about its sizes);
- files get mode 644 and folders 755, whatever the archive says (no setuid, no
  executable).
It unpacks into a temporary folder next to the destination, renamed when done.
"""
import contextlib
import os
import shutil
import stat
import tarfile
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

MAX_FILES = 5000
MAX_TOTAL = 500 << 20        # bytes, unpacked
TAR = (".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tbz2", ".tar.xz", ".txz")
KINDS = (".zip", *TAR)


class ArchiveError(Exception):
    """An archive that cannot be unpacked safely: its message is shown to the user."""


def is_archive(name):
    return str(name).lower().endswith(KINDS)


def suffix(name):
    """The archive extension of name ('.tar.gz', '.zip'…, as in KINDS), or ''."""
    name = str(name).lower()
    return max((k for k in KINDS if name.endswith(k)), key=len, default="")


def safe_name(name):
    """The relative path of a member, or ArchiveError when it is absolute or goes
    up. Backslashes count as separators (archives made on Windows)."""
    raw = str(name).replace("\\", "/")
    p = PurePosixPath(raw)
    if raw.startswith("/") or (len(raw) > 1 and raw[1] == ":") or ".." in p.parts:
        raise ArchiveError(f"unsafe name in the archive: {name}")
    parts = [x for x in p.parts if x not in ("", ".")]
    return PurePosixPath(*parts) if parts else None


class _Budget:
    def __init__(self, max_files, max_total):
        self.files, self.total = 0, 0
        self.max_files, self.max_total = max_files, max_total

    def file(self):
        self.files += 1
        if self.files > self.max_files:
            raise ArchiveError(f"more than {self.max_files} files in the archive")

    def copy(self, src, dst):
        """src (a file object) into the new file dst, counted against the total."""
        with open(dst, "xb") as out:
            while True:
                b = src.read(1 << 16)
                if not b:
                    return
                self.total += len(b)
                if self.total > self.max_total:
                    raise ArchiveError(f"more than {self.max_total >> 20} MB once unpacked")
                out.write(b)


def _members(archive):
    """(name, kind, open) for each member: kind "dir", "file" or "other"."""
    name = str(archive).lower()
    if name.endswith(".zip"):
        with zipfile.ZipFile(archive) as z:
            for info in z.infolist():
                ftype = stat.S_IFMT(info.external_attr >> 16)    # 0: not said (Windows)
                if info.is_dir() or ftype == stat.S_IFDIR:
                    yield info.filename, "dir", None
                elif ftype not in (0, stat.S_IFREG):            # a link, a device…
                    yield info.filename, "other", None
                else:
                    yield info.filename, "file", lambda info=info: z.open(info)
    elif name.endswith(TAR):
        with tarfile.open(archive, "r:*") as t:
            for m in t:
                if m.isdir():
                    yield m.name, "dir", None
                elif m.isfile():
                    yield m.name, "file", lambda m=m: t.extractfile(m)
                else:
                    yield m.name, "other", None
    else:
        raise ArchiveError(f"not an archive this tool unpacks: {Path(archive).name} "
                           f"({', '.join(KINDS)})")


def extract(archive, dest, max_files=MAX_FILES, max_total=MAX_TOTAL):
    """Unpack archive into dest (a new folder). Returns the number of members left
    out (links, devices…)."""
    dest = Path(dest)
    if dest.exists():
        raise ArchiveError(f"{dest} already exists")
    dest.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = Path(tempfile.mkdtemp(dir=dest.parent, prefix=f".{dest.name}.", suffix=".part"))
    budget, skipped = _Budget(max_files, max_total), 0
    try:
        for name, kind, open_ in _members(archive):
            rel = safe_name(name)
            if rel is None:
                continue
            target = tmp.joinpath(*rel.parts)
            if kind == "other":
                skipped += 1
            elif kind == "dir":
                target.mkdir(parents=True, exist_ok=True)
            else:
                budget.file()
                target.parent.mkdir(parents=True, exist_ok=True)
                with open_() as src:
                    budget.copy(src, target)
                os.chmod(target, 0o644)
        for d, dirs, _ in os.walk(tmp):
            for n in dirs:
                os.chmod(Path(d) / n, 0o755)
        os.chmod(tmp, 0o755)
        os.replace(tmp, dest)
    except (OSError, EOFError, RuntimeError, zipfile.BadZipFile, tarfile.TarError) as e:
        shutil.rmtree(tmp, ignore_errors=True)
        raise ArchiveError(f"{Path(archive).name}: {e}") from None
    except BaseException:
        with contextlib.suppress(OSError):
            shutil.rmtree(tmp, ignore_errors=True)
        raise
    return skipped
