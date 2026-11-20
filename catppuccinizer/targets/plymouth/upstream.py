"""The adi1090x/plymouth-themes themes, by name: fetched on demand (sparse git
checkout in the cache), or taken from a local copy named by
$CATPPUCCINIZER_PLYMOUTH_SRC. The catalogue and the name lookup use the same
source."""
import os
import subprocess
from pathlib import Path

from ...core.paths import cache_dir

UPSTREAM = cache_dir() / "plymouth-themes"
UPSTREAM_REPO = "https://github.com/adi1090x/plymouth-themes.git"
SRC_ENV = "CATPPUCCINIZER_PLYMOUTH_SRC"


def local_src():
    """Folder named by $CATPPUCCINIZER_PLYMOUTH_SRC (a copy of the adi1090x
    repository, or any folder of themes), or None to fetch from GitHub."""
    value = os.environ.get(SRC_ENV)
    if not value:
        return None
    src = Path(value).expanduser()
    if not src.is_dir():
        raise SystemExit(f"{SRC_ENV}={value}: not a folder")
    return src


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
    """{theme name: 'pack_N/theme'} for every adi1090x theme (paths relative to
    the local copy when $CATPPUCCINIZER_PLYMOUTH_SRC is set; any theme folder
    there counts, in pack_N/ or at the top)."""
    src = local_src()
    if src:
        return {d.name: str(d.relative_to(src))
                for d in sorted([*src.glob("pack_*/*"), *src.glob("*")])
                if d.is_dir() and any(d.glob("*.plymouth"))}
    ensure_clone()
    dirs = git("ls-tree", "-d", "--name-only", "HEAD", "pack_1/", "pack_2/", "pack_3/", "pack_4/")
    return {Path(d).name: d for d in dirs.split()}


def resolve_theme(arg):
    """Folder of a theme given as a path, or as an adi1090x name (from the local
    copy, or fetched on demand)."""
    p = Path(arg).expanduser()
    if p.is_dir():
        return p.resolve()
    if "/" in arg:
        raise SystemExit(f"Theme folder not found: {arg}")
    themes = upstream_themes()
    src = local_src()
    if arg not in themes:
        where = f" in {src} (${SRC_ENV})" if src else ""
        raise SystemExit(f"Unknown theme: {arg}{where} (give a folder path, or see --list)")
    if src:
        return src / themes[arg]
    d = UPSTREAM / themes[arg]
    if not (d / f"{arg}.plymouth").exists():
        print(f"Fetching {themes[arg]} ...", flush=True)
        current = git("sparse-checkout", "list").split()
        git("sparse-checkout", "set", *sorted(set(current) | {themes[arg]}))
    return d
