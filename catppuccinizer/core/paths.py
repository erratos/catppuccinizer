"""Where things live: cache, restore state, and sudo-aware file ownership."""
import os
import stat
from pathlib import Path


def user_home():
    """The user's home, also under sudo (the invoking user's, not root's): the
    downloads stay the same whether a command runs with sudo or not."""
    if os.geteuid() == 0 and os.environ.get("SUDO_USER"):
        return Path(os.path.expanduser(f"~{os.environ['SUDO_USER']}"))
    return Path.home()


def cache_dir():
    """Downloads (e.g. upstream themes): $CATPPUCCINIZER_CACHE or ~/.cache/catppuccinizer."""
    base = os.environ.get("CATPPUCCINIZER_CACHE")
    if not base:
        base = Path(os.environ.get("XDG_CACHE_HOME", user_home() / ".cache")) / "catppuccinizer"
    return Path(base)


def state_file(target, system=False):
    """What restore needs to undo a target's install / apply: $CATPPUCCINIZER_STATE/<target>.json,
    else /var/lib/catppuccinizer/<target>.json for system-wide changes (made as root),
    or $XDG_STATE_HOME/catppuccinizer/<target>.json (~/.local/state) for the user's."""
    base = os.environ.get("CATPPUCCINIZER_STATE")
    if not base:
        base = (Path("/var/lib/catppuccinizer") if system else
                Path(os.environ.get("XDG_STATE_HOME", user_home() / ".local/state")) / "catppuccinizer")
    return Path(base) / f"{target}.json"


def give_back(*paths):
    """Under sudo, hand files we created back to the invoking user: only what root
    owns, never through a link (a link in the user's folders could point to a system
    file), never a file with other hard links."""
    if os.geteuid() != 0 or "SUDO_UID" not in os.environ:
        return
    uid, gid = int(os.environ["SUDO_UID"]), int(os.environ.get("SUDO_GID", os.environ["SUDO_UID"]))
    for root in paths:
        root = Path(root)
        if not root.is_dir() or root.is_symlink():
            continue
        for dirpath, dirnames, filenames in os.walk(root):     # does not enter linked folders
            for p in [Path(dirpath), *(Path(dirpath) / n for n in filenames)]:
                st = os.lstat(p)
                if (st.st_uid == 0 and not stat.S_ISLNK(st.st_mode)
                        and (stat.S_ISDIR(st.st_mode) or st.st_nlink == 1)):
                    os.chown(p, uid, gid, follow_symlinks=False)
