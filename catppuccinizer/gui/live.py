"""Live preview of the GUI: an image recoloured in the server's own process, on a
reduced copy, as the options change (/api/live).

The analysis of a file (core.recolor.plan: detection, the dominant hue) is done
on the full image, as the build does it, and kept with the reduced copy, so that
moving a slider (--keep-lum, --smooth, the flavour, the accent, -m) only renders
again; the LUT cubes are cached by core.recolor itself (build_lut, lutgen.build).
A file is analysed again when it changes (modification time, size) or when an
option of the analysis does (--separation, --method).
"""
import base64
import contextlib
import io
import threading
import time
from collections import OrderedDict
from pathlib import Path

from PIL import Image

from ..core import recolor

SIZE = 512                 # pixels, the longest side of the live image
KEEP = 8                   # files whose reduced copy and analysis are kept
# what the live preview recolours: still raster images (an SVG keeps its own
# colours written as text, an animation is previewed with --preview-animation)
EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".qoi"}


def reduced(path, size=SIZE):
    """The image at most size pixels wide and high, in RGB, or RGBA when it has
    transparency (as core.detect.load_rgba reads it)."""
    with Image.open(path) as im:
        im.seek(0)
        im.draft("RGB", (size, size))      # JPEG: decoded at a fraction of its size
        alpha = im.mode in ("RGBA", "LA", "PA") or "transparency" in im.info
        im = im.convert("RGBA" if alpha else "RGB")
    im.thumbnail((size, size), Image.Resampling.LANCZOS)
    return im


def png(im):
    """A data: URL of the image as PNG (compress_level 1: ~3 ms for 512 px, lossless)."""
    buf = io.BytesIO()
    im.save(buf, "PNG", compress_level=1)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


class Live:
    """The files seen by the live preview: their reduced copy and the analysis
    plan() keeps for them, the KEEP most recent. One render at a time (the page
    sends the next request when the previous one is answered)."""

    def __init__(self, size=SIZE):
        self.size = size
        self.files = OrderedDict()          # (path, mtime_ns, size in bytes) -> entry
        self.lock = threading.Lock()

    def entry(self, path):
        st = Path(path).stat()
        key = (str(Path(path).resolve()), st.st_mtime_ns, st.st_size)
        if key not in self.files:
            self.files[key] = {"small": reduced(path, self.size), "memo": {}}
            while len(self.files) > KEEP:
                self.files.popitem(last=False)
        self.files.move_to_end(key)
        return self.files[key]

    def render(self, path, a):
        """The recoloured image for the first flavour and accent (as --preview), with
        the method chosen, why the accent is ignored (or None) and the times in ms:
        analysis (0 when kept from before) and render."""
        with self.lock:
            t0 = time.perf_counter()
            e = self.entry(path)
            known = len(e["memo"])
            with contextlib.redirect_stdout(io.StringIO()):       # plan's notes (-m with a LUT)
                method, grp = recolor.plan(Path(path), a, verbose=False, memo=e["memo"])
            t1 = time.perf_counter()
            flavor, accent = a.flavor[0], a.accent[0]
            im = recolor.render(e["small"], method, grp, flavor, accent, a)
            out = png(im)
            t2 = time.perf_counter()
        return {"image": out, "width": im.width, "height": im.height, "method": method,
                "flavor": flavor, "accent": accent,
                "accent_ignored": recolor.accent_ignored_reason(method, grp),
                "analysed": len(e["memo"]) > known,
                "ms": {"analysis": round((t1 - t0) * 1000), "render": round((t2 - t1) * 1000)}}
