"""catppuccinizer: recolour Plymouth themes, wallpapers and boot loaders with Catppuccin."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIGS = Path(os.environ.get("CATPPUCCINIZER_CONFIGS", ROOT / "configs"))
