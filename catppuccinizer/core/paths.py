"""Where things live: user configuration, cache, restore state, and sudo-aware file ownership."""
import os
from pathlib import Path


def user_home():
    """The user's home, also under sudo (the invoking user's, not root's): the tuned
    configs and downloads stay the same whether a command runs with sudo or not."""
    if os.geteuid() == 0 and os.environ.get("SUDO_USER"):
        return Path(os.path.expanduser(f"~{os.environ['SUDO_USER']}"))
    return Path.home()


def config_dir(target):
    """User configuration of a target: $CATPPUCCINIZER_CONFIGS/<target> or
    $XDG_CONFIG_HOME/catppuccinizer/<target> (~/.config/catppuccinizer/<target>)."""
    base = os.environ.get("CATPPUCCINIZER_CONFIGS")
    if not base:
        base = Path(os.environ.get("XDG_CONFIG_HOME", user_home() / ".config")) / "catppuccinizer"
    return Path(base) / target


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
    """Under sudo, hand files we created back to the invoking user."""
    if os.geteuid() != 0 or "SUDO_UID" not in os.environ:
        return
    uid, gid = int(os.environ["SUDO_UID"]), int(os.environ.get("SUDO_GID", os.environ["SUDO_UID"]))
    for root in paths:
        root = Path(root)
        if root.exists():
            for p in [root, *root.rglob("*")]:
                os.chown(p, uid, gid)
