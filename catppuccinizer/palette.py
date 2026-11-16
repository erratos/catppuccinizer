"""Catppuccin palettes and colour helpers."""
import colorsys

import numpy as np

# ------------------------------------------------------------------ palettes
# https://github.com/catppuccin/palette
_ORDER = ["rosewater", "flamingo", "pink", "mauve", "red", "maroon", "peach", "yellow",
          "green", "teal", "sky", "sapphire", "blue", "lavender", "text", "subtext1",
          "subtext0", "overlay2", "overlay1", "overlay0", "surface2", "surface1",
          "surface0", "base", "mantle", "crust"]
_HEX = {
    "latte": "dc8a78 dd7878 ea76cb 8839ef d20f39 e64553 fe640b df8e1d 40a02b 179299 04a5e5 "
             "209fb5 1e66f5 7287fd 4c4f69 5c5f77 6c6f85 7c7f93 8c8fa1 9ca0b0 acb0be bcc0cc "
             "ccd0da eff1f5 e6e9ef dce0e8",
    "frappe": "f2d5cf eebebe f4b8e4 ca9ee6 e78284 ea999c ef9f76 e5c890 a6d189 81c8be 99d1db "
              "85c1dc 8caaee babbf1 c6d0f5 b5bfe2 a5adce 949cbb 838ba7 737994 626880 51576d "
              "414559 303446 292c3c 232634",
    "macchiato": "f4dbd6 f0c6c6 f5bde6 c6a0f6 ed8796 ee99a0 f5a97f eed49f a6da95 8bd5ca 91d7e3 "
                 "7dc4e4 8aadf4 b7bdf8 cad3f5 b8c0e0 a5adcb 939ab7 8087a2 6e738d 5b6078 494d64 "
                 "363a4f 24273a 1e2030 181926",
    "mocha": "f5e0dc f2cdcd f5c2e7 cba6f7 f38ba8 eba0ac fab387 f9e2af a6e3a1 94e2d5 89dceb "
             "74c7ec 89b4fa b4befe cdd6f4 bac2de a6adc8 9399b2 7f849c 6c7086 585b70 45475a "
             "313244 1e1e2e 181825 11111b",
}
PALETTES = {f: dict(zip(_ORDER, h.split())) for f, h in _HEX.items()}
FLAVORS = list(PALETTES)
FLAVOR_TITLES = {"latte": "Latte", "frappe": "Frappé", "macchiato": "Macchiato", "mocha": "Mocha"}
ACCENTS = _ORDER[:14]
TARGETS = _ORDER + ["accent"]
# colours used for automatic mapping of saturated source colours
AUTO_HUE_TARGETS = ["red", "peach", "yellow", "green", "teal", "sky", "sapphire",
                    "blue", "mauve", "pink"]


def hex2rgb(h):
    h = h.lstrip("#")
    return np.array([int(h[i:i + 2], 16) for i in (0, 2, 4)], dtype=np.float32)


def rgb2hex(c):
    return "#" + "".join(f"{int(round(v)):02x}" for v in np.clip(c, 0, 255))


def rgb(flavor, name):
    return hex2rgb(PALETTES[flavor][name])


def hue_of(c):
    r, g, b = (np.asarray(c, dtype=float) / 255).tolist()
    return colorsys.rgb_to_hsv(r, g, b)[0] * 360


def hue_dist(a, b):
    d = abs(a - b) % 360
    return min(d, 360 - d)


HUE_NAMES = [(15, "red"), (35, "orange"), (70, "yellow"), (160, "green"), (190, "cyan"),
             (250, "blue"), (290, "purple"), (345, "pink"), (361, "red")]


def colour_name(hue, sat, val):
    if sat < 0.25 or val < 0.15:
        return "white" if val > 0.7 else "black" if val < 0.15 else "gray"
    return next(n for limit, n in HUE_NAMES if hue < limit)


def color_args(flavor, name):
    """'r, g, b' as 0..1 floats, for Plymouth scripts."""
    c = rgb(flavor, name) / 255
    return f"{c[0]:.3f}, {c[1]:.3f}, {c[2]:.3f}"


def expand(values, allowed, what):
    """Resolve 'all' and validate a list of flavours / accents."""
    if "all" in values:
        return list(allowed)
    bad = [v for v in values if v not in allowed]
    if bad:
        raise SystemExit(f"Unknown {what}: {', '.join(bad)} (choose from: all, {', '.join(allowed)})")
    return list(dict.fromkeys(values))


# ------------------------------------------------------------------- Oklab
def srgb_to_oklab(c):
    """(..., 3) sRGB 0..255 -> Oklab (L, a, b)."""
    c = np.asarray(c, dtype=np.float32) / 255
    lin = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    m1 = np.array([[0.4122214708, 0.5363325363, 0.0514459929],
                   [0.2119034982, 0.6806995451, 0.1073969566],
                   [0.0883024619, 0.2817188376, 0.6299787005]], np.float32)
    m2 = np.array([[0.2104542553, 0.7936177850, -0.0040720468],
                   [1.9779984951, -2.4285922050, 0.4505937099],
                   [0.0259040371, 0.7827717662, -0.8086757660]], np.float32)
    return np.cbrt(lin @ m1.T) @ m2.T


def oklab_to_srgb(lab):
    """(..., 3) Oklab -> sRGB 0..255 (clipped)."""
    m2i = np.array([[1, 0.3963377774, 0.2158037573],
                    [1, -0.1055613458, -0.0638541728],
                    [1, -0.0894841775, -1.2914855480]], np.float32)
    m1i = np.array([[4.0767416621, -3.3077115913, 0.2309699292],
                    [-1.2684380046, 2.6097574011, -0.3413193965],
                    [-0.0041960863, -0.7034186147, 1.7076147010]], np.float32)
    lin = np.clip((np.asarray(lab, np.float32) @ m2i.T) ** 3 @ m1i.T, 0, 1)
    c = np.where(lin <= 0.0031308, lin * 12.92, 1.055 * lin ** (1 / 2.4) - 0.055)
    return np.clip(c * 255, 0, 255)
