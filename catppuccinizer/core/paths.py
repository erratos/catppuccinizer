"""Where things live: user configuration, cache, and sudo-aware file ownership."""
import os
from pathlib import Path


def config_dir(target):
    """User configuration of a target: $CATPPUCCINIZER_CONFIGS/<target> or
    $XDG_CONFIG_HOME/catppuccinizer/<target> (~/.config/catppuccinizer/<target>)."""
    base = os.environ.get("CATPPUCCINIZER_CONFIGS")
    if not base:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "catppuccinizer"
    return Path(base) / target


def cache_dir():
    """Downloads (e.g. upstream themes): $CATPPUCCINIZER_CACHE or ~/.cache/catppuccinizer."""
    base = os.environ.get("CATPPUCCINIZER_CACHE")
    if not base:
        base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "catppuccinizer"
    return Path(base)


def give_back(*paths):
    """Under sudo, hand files we created back to the invoking user."""
    if os.geteuid() != 0 or "SUDO_UID" not in os.environ:
        return
    uid, gid = int(os.environ["SUDO_UID"]), int(os.environ.get("SUDO_GID", os.environ["SUDO_UID"]))
    for root in paths:
        root = Path(root)
        if root.exists():
            for p in [root, *root.rglob("*")]:
                os.chown(p, uid, gid)
