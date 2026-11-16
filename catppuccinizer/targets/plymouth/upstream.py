"""Fetch adi1090x/plymouth-themes on demand (sparse git checkout)."""
import subprocess
from pathlib import Path

from ...core.paths import cache_dir

UPSTREAM = cache_dir() / "plymouth-themes"
UPSTREAM_REPO = "https://github.com/adi1090x/plymouth-themes.git"


def git(*args):
    return subprocess.run(["git", "-C", str(UPSTREAM), *args], check=True,
                          capture_output=True, text=True).stdout


def ensure_clone():
    if (UPSTREAM / ".git").exists():
        return
    print(f"Fetching {UPSTREAM_REPO} ...", flush=True)
    UPSTREAM.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "clone", "--depth", "1", "--filter=blob:none", "--sparse",
                    UPSTREAM_REPO, str(UPSTREAM)], check=True)


def upstream_themes():
    """{theme name: 'pack_N/theme'} for every adi1090x theme."""
    ensure_clone()
    dirs = git("ls-tree", "-d", "--name-only", "HEAD", "pack_1/", "pack_2/", "pack_3/", "pack_4/")
    return {Path(d).name: d for d in dirs.split()}


def resolve_theme(arg, src):
    """Folder of a theme given as a path, or as an adi1090x name (fetched on demand)."""
    p = Path(arg).expanduser()
    if p.is_dir():
        return p.resolve()
    if "/" in arg:
        raise SystemExit(f"Theme folder not found: {arg}")
    if src:
        for cand in (src / arg, *src.glob(f"pack_*/{arg}")):
            if cand.is_dir():
                return cand
        raise SystemExit(f"Theme {arg} not found in {src}")
    themes = upstream_themes()
    if arg not in themes:
        raise SystemExit(f"Unknown theme: {arg} (give a folder path, or see --list)")
    d = UPSTREAM / themes[arg]
    if not (d / f"{arg}.plymouth").exists():
        print(f"Fetching {themes[arg]} ...", flush=True)
        current = git("sparse-checkout", "list").split()
        git("sparse-checkout", "set", *sorted(set(current) | {themes[arg]}))
    return d
