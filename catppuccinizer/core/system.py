"""Changes to the system, made by the install / apply / test / restore steps.

Every file a step copies, writes or removes outside the output folder, and
every command it runs, goes through a System object: each change is printed,
and with --dry-run it is only printed ("would copy …"), nothing is done.
System.done keeps the list, for tests.

Reading the system (the current theme, limine.conf…) is not a change: steps do
it directly, even in a dry run.
"""
import json
import shutil
import subprocess
from datetime import datetime
from pathlib import Path


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
        """dst becomes a copy of the folder src (an older dst is replaced)."""
        src, dst = Path(src), Path(dst)
        if self._say("copy", f"{src} -> {dst}", str(src), str(dst)):
            def copy():
                if dst.exists():
                    shutil.rmtree(dst)
                shutil.copytree(src, dst, symlinks=True)
            self._do("write", copy)

    def copy_file(self, src, dst):
        src, dst = Path(src), Path(dst)
        if self._say("copy", f"{src} -> {dst}", str(src), str(dst)):
            def copy():
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(src, dst)
            self._do("write", copy)

    def write_text(self, path, text, backup=False):
        """Write a file; backup=True first copies it next to itself, with the date
        (returns that copy's path)."""
        path = Path(path)
        bak = None
        if backup and path.exists():
            bak = path.with_name(path.name + datetime.now().strftime(".%Y%m%d-%H%M%S-%f.bak"))
            if self._say("back up", f"{path} -> {bak}", str(path), str(bak)):
                self._do("write", shutil.copy2, path, bak)
        if self._say("write", str(path), str(path)):
            def write():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text)
            self._do("write", write)
        return bak

    def remove(self, path):
        """Remove a file or a folder (nothing if it does not exist)."""
        path = Path(path)
        if not path.exists() and not path.is_symlink():
            return
        if self._say("remove", str(path), str(path)):
            self._do("remove", lambda: shutil.rmtree(path) if path.is_dir() and not path.is_symlink()
                     else path.unlink())

    # ---------------------------------------------------------- commands
    def run(self, cmd):
        """Run a command (a list, no shell); its return code (0 in a dry run)."""
        cmd = [str(c) for c in cmd]
        if not self._say("run", " ".join(cmd), cmd):
            return 0
        try:
            return subprocess.run(cmd, check=False).returncode
        except FileNotFoundError:
            raise SystemExit(f"{cmd[0]} not found")

    # ------------------------------------------------------------- state
    # what a step needs to be undone by restore (the theme in use before…), kept
    # in a JSON file (core.paths.state_file)
    @staticmethod
    def load_state(path):
        try:
            return json.loads(Path(path).read_text())
        except FileNotFoundError:
            return {}
        except (OSError, ValueError) as e:
            raise SystemExit(f"Cannot read {path}: {e}")

    def save_state(self, path, data):
        if data:
            self.write_text(path, json.dumps(data, indent=2) + "\n")
        else:
            self.remove(path)
