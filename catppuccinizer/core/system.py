"""Changes to the system, made by the install / apply / test / restore steps.

Every file a step copies, writes or removes outside the output folder, and
every command it runs, goes through a System object: each change is printed,
and with --dry-run it is only printed ("would copy …"), nothing is done.
System.done keeps the list, for tests.

Reading the system (the current theme, limine.conf…) is not a change: steps do
it directly, even in a dry run.

How the changes are made (docs/architecture.md, Security):
- a name that goes into a system path is checked first (place(), naming.check_name);
- copies never follow a link out of the source folder (copy_folder), and give
  explicit rights: 644 for files, 755 for folders;
- a file or folder is replaced atomically: written next to it under a temporary
  name, then renamed over it (os.replace), so it is never half written;
- write_text(…, backup=True) first copies the file next to itself, with the date;
  only the KEEP_BACKUPS most recent copies are kept;
- commands are lists, never a shell; as root, a bare command name is only looked
  up in the system folders (TRUSTED_DIRS), not in $PATH.
"""
import contextlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path

from .naming import check_name

FILE_MODE, DIR_MODE = 0o644, 0o755
KEEP_BACKUPS = 5
BACKUP = re.compile(r"\.\d{8}-\d{6}-\d{6}\.bak$")
TRUSTED_DIRS = ("/usr/local/sbin", "/usr/local/bin", "/usr/sbin", "/usr/bin", "/sbin", "/bin")


# ------------------------------------------------------------------ helpers
def place(base, name, what="name"):
    """base / name, once name is checked: no '/', '..' or leading '-' (naming.check_name)."""
    return Path(base) / check_name(name, what)


def which(name):
    """Absolute path of a command, or None. As root, only the system folders are
    searched (a user's $PATH is not trusted); an absolute path is kept."""
    if os.path.isabs(name):
        return name if os.access(name, os.X_OK) else None
    if os.geteuid() == 0:
        return shutil.which(name, path=os.pathsep.join(TRUSTED_DIRS))
    return shutil.which(name)


def source_file(path, root):
    """The file to read for path, a file of the source folder root: path itself, or
    what its link points to when that is a regular file inside root. None for a
    link out of root, a broken link, or anything that is not a regular file."""
    path, root = Path(path), Path(root).resolve()
    try:
        real = path.resolve(strict=True)
    except (OSError, RuntimeError):
        return None
    if not real.is_relative_to(root) or not real.is_file():
        return None
    return real


def _chmod(path, mode):
    # filesystems without Unix rights (the FAT ESP) refuse chmod: nothing to set there
    with contextlib.suppress(OSError):
        os.chmod(path, mode)


def copy_folder(src, dst, ignore=(), file_mode=None, dir_mode=None):
    """Copy the folder src into dst (created), without following links out of src:
    a link to a file inside src is copied as that file, any other link (to a
    folder, out of src, broken) and special files are skipped, with a note.
    ignore: glob patterns of names to leave out. Returns the skipped paths."""
    src, dst = Path(src), Path(dst)
    root, skipped = src.resolve(), []
    for dirpath, dirnames, filenames in os.walk(src):     # does not enter linked folders
        d = Path(dirpath)
        out = dst / d.relative_to(src)
        out.mkdir(parents=True, exist_ok=True)
        if dir_mode is not None:
            _chmod(out, dir_mode)
        for name in list(dirnames):
            if (d / name).is_symlink() or any(Path(name).match(p) for p in ignore):
                dirnames.remove(name)
                if (d / name).is_symlink():
                    skipped.append(d / name)
        for name in filenames:
            if any(Path(name).match(p) for p in ignore):
                continue
            real = source_file(d / name, root)
            if real is None:
                skipped.append(d / name)
                continue
            shutil.copyfile(real, out / name)
            if file_mode is not None:
                _chmod(out / name, file_mode)
    for f in skipped:
        print(f"note: skipped {f}: a link out of {src}, or not a regular file")
    return skipped


def _temp_name(path, tag):
    return path.with_name(f".{path.name}.{tag}-{os.urandom(4).hex()}")


def atomic_write(path, data, mode=None):
    """Write bytes to path atomically: a temporary file next to it, flushed to disk,
    then renamed over it. An existing file keeps its rights and owner; a new one
    gets mode (FILE_MODE by default)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        st = path.stat()
    except FileNotFoundError:
        st = None
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        _chmod(tmp, st.st_mode & 0o7777 if st else (FILE_MODE if mode is None else mode))
        if st and os.geteuid() == 0:
            with contextlib.suppress(OSError):
                os.chown(tmp, st.st_uid, st.st_gid)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def encode(text):
    """str -> bytes, so that a file read with read_text() is written back byte for byte."""
    return text if isinstance(text, bytes) else text.encode("utf-8", "surrogateescape")


def read_text(path):
    """A text file as it is: no newline translation, undecodable bytes kept."""
    with open(path, encoding="utf-8", errors="surrogateescape", newline="") as f:
        return f.read()


class System:
    def __init__(self, dry_run=False):
        self.dry_run = dry_run
        self.done = []                     # (action, path or command, …)

    def _say(self, action, text, *record):
        self.done.append((action, *record))
        print(f"  {'would ' if self.dry_run else ''}{action} {text}", flush=True)
        return not self.dry_run

    def _do(self, what, fn, *args):
        try:
            return fn(*args)
        except PermissionError as e:
            raise SystemExit(f"Cannot {what} {e.filename}: permission denied (run with sudo, "
                             "or add --dry-run to only see what would be done)")

    # ------------------------------------------------------------- files
    def copy_tree(self, src, dst):
        """dst becomes a copy of the folder src (an older dst is replaced at once):
        files 644, folders 755, no link followed out of src."""
        src, dst = Path(src), Path(dst)
        if self._say("copy", f"{src} -> {dst}", str(src), str(dst)):
            def copy():
                dst.parent.mkdir(parents=True, exist_ok=True)
                new, old = _temp_name(dst, "new"), _temp_name(dst, "old")
                try:
                    copy_folder(src, new, file_mode=FILE_MODE, dir_mode=DIR_MODE)
                    if dst.is_symlink():
                        dst.unlink()            # replace the link itself, not what it points to
                    elif dst.exists():
                        os.rename(dst, old)
                    os.rename(new, dst)
                finally:
                    shutil.rmtree(new, ignore_errors=True)
                    shutil.rmtree(old, ignore_errors=True)
            self._do("write", copy)

    def copy_file(self, src, dst):
        """dst becomes a copy of the file src (644, replaced at once)."""
        src, dst = Path(src), Path(dst)
        if self._say("copy", f"{src} -> {dst}", str(src), str(dst)):
            self._do("write", lambda: atomic_write(dst, Path(src).read_bytes(), FILE_MODE))

    def write_text(self, path, text, backup=False):
        """Write a file atomically (str or bytes); backup=True first copies it next to
        itself, with the date, and keeps only the KEEP_BACKUPS most recent copies.
        Returns that copy's path."""
        path = Path(path)
        bak = None
        if backup and path.exists():
            bak = path.with_name(path.name + datetime.now().strftime(".%Y%m%d-%H%M%S-%f.bak"))
            if self._say("back up", f"{path} -> {bak}", str(path), str(bak)):
                self._do("write", shutil.copy2, path, bak)
            old = sorted(p for p in path.parent.glob(glob_escape(path.name) + ".*.bak")
                         if BACKUP.search(p.name) and p != bak)
            for p in old[:max(0, len(old) + 1 - KEEP_BACKUPS)]:
                self.remove(p)
        if self._say("write", str(path), str(path)):
            self._do("write", atomic_write, path, encode(text))
        return bak

    def remove(self, path):
        """Remove a file or a folder (nothing if it does not exist); a link is removed,
        never what it points to."""
        path = Path(path)
        if not path.exists() and not path.is_symlink():
            return
        if self._say("remove", str(path), str(path)):
            self._do("remove", lambda: shutil.rmtree(path) if path.is_dir() and not path.is_symlink()
                     else path.unlink())

    # ---------------------------------------------------------- commands
    def run(self, cmd):
        """Run a command (a list, no shell); its return code (0 in a dry run). The
        command is looked up with which(): as root, only in the system folders."""
        cmd = [str(c) for c in cmd]
        exe = which(cmd[0])
        if exe is None and not self.dry_run:
            raise SystemExit(f"{cmd[0]} not found"
                             + (f" in {', '.join(TRUSTED_DIRS)}" if os.geteuid() == 0 else ""))
        cmd[0] = exe or cmd[0]
        if not self._say("run", " ".join(cmd), cmd):
            return 0
        return subprocess.run(cmd, check=False).returncode

    # ------------------------------------------------------------- state
    # what a step needs to be undone by restore (the theme in use before…), kept
    # in a JSON file (core.paths.state_file)
    @staticmethod
    def load_state(path):
        try:
            data = json.loads(Path(path).read_text())
        except FileNotFoundError:
            return {}
        except (OSError, ValueError) as e:
            raise SystemExit(f"Cannot read {path}: {e}")
        if not isinstance(data, dict):
            raise SystemExit(f"Cannot read {path}: not a JSON object")
        return data

    def save_state(self, path, data):
        if data:
            self.write_text(path, json.dumps(data, indent=2) + "\n")
        else:
            self.remove(path)

    # ------------------------------------------------ installed results
    # A target that installs its results as folders of one system folder keeps their
    # names in its state file ("installed"), with what its apply step replaced
    # ("previous"): restore selects that again, then removes them.
    def install_tree(self, src, base, state, what="name"):
        """Copy the folder src to base/<its name> (the name checked first) and add it
        to the state file's installed results. Returns the installed folder."""
        src = Path(src)
        data = self.load_state(state)
        dst = place(base, src.name, what)
        self.copy_tree(src, dst)
        data["installed"] = sorted({*data.get("installed", []), src.name})
        self.save_state(state, data)
        return dst

    def keep_previous(self, state, current, name=None):
        """Before apply: remember current (what restore selects again), unless one was
        remembered already, current is None (not known), or it is an installed
        result (name: the result's name in current; default current itself)."""
        data = self.load_state(state)
        if ("previous" not in data and current is not None
                and (current if name is None else name) not in data.get("installed", [])):
            data["previous"] = current
        self.save_state(state, data)

    def restore_state(self, state, what="name"):
        """For restore: (state, installed names); the names read back are checked like
        new ones. Fails when there is nothing to restore."""
        data = self.load_state(state)
        if not data:
            raise SystemExit(f"Nothing to restore ({state} not found: nothing was installed "
                             "or applied)")
        return data, [check_name(n, f"{what} in {state}") for n in data.get("installed", [])]

    def uninstall(self, state, base, names):
        """After restore selected the previous one: remove the installed results, and
        the state file."""
        for name in names:
            self.remove(place(base, name))
        self.save_state(state, {})


def glob_escape(name):
    return re.sub(r"([*?\[])", r"[\1]", name)
