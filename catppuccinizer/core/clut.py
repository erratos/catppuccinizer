"""3D colour look-up tables: Hald CLUT images and .cube files.

A cube is a float32 array (n, n, n, 3) indexed [r, g, b], values 0..255.
- Hald CLUT of level L: an L^3 x L^3 RGB image holding a cube of size L^2, red
  varying fastest, then green, then blue (lutgen, ImageMagick, GIMP, ffmpeg haldclut).
- .cube (Adobe/Resolve): LUT_3D_SIZE n, then n^3 "r g b" lines in 0..1, red fastest
  (ffmpeg lut3d, mpv, Resolve, Photoshop, OBS…).
"""
import numpy as np
from PIL import Image


def apply_cube(arr, cube):
    """Trilinear interpolation of an (..., 3) array of 0..255 values through a cube."""
    n = cube.shape[0]
    flat = arr.reshape(-1, 3)
    out = np.empty_like(flat, dtype=np.float32)
    for s in range(0, len(flat), 1 << 20):
        f = flat[s:s + (1 << 20)] * ((n - 1) / 255)
        i0 = np.clip(np.floor(f).astype(np.int32), 0, n - 2)
        d = f - i0
        acc = np.zeros_like(f)
        for dx in (0, 1):
            wx = d[:, 0] if dx else 1 - d[:, 0]
            for dy in (0, 1):
                wy = d[:, 1] if dy else 1 - d[:, 1]
                for dz in (0, 1):
                    wz = d[:, 2] if dz else 1 - d[:, 2]
                    acc += (wx * wy * wz)[:, None] * cube[i0[:, 0] + dx, i0[:, 1] + dy, i0[:, 2] + dz]
        out[s:s + len(f)] = acc
    return out.reshape(arr.shape)


def resample(cube, n):
    """The same cube with n points per axis (exact when n == cube size)."""
    if cube.shape[0] == n:
        return cube
    g = np.linspace(0, 255, n, dtype=np.float32)
    grid = np.stack(np.meshgrid(g, g, g, indexing="ij"), -1)
    return apply_cube(grid, cube)


def hald_level(n):
    """Hald level whose cube has n points per axis (n must be a square)."""
    level = round(n ** 0.5)
    if level * level != n or not 2 <= level <= 16:
        raise ValueError(f"no Hald CLUT has a cube of size {n}")
    return level


def read_hald(path):
    arr = np.asarray(Image.open(path).convert("RGB"), dtype=np.float32)
    level = round(arr.shape[0] ** (1 / 3))
    if arr.shape[0] != arr.shape[1] or level ** 3 != arr.shape[0]:
        raise ValueError(f"{path}: not a Hald CLUT ({arr.shape[1]}x{arr.shape[0]})")
    n = level * level
    return arr.reshape(n, n, n, 3).transpose(2, 1, 0, 3)       # [b, g, r] -> [r, g, b]


def write_hald(cube, path):
    n = cube.shape[0]
    side = hald_level(n) ** 3
    data = np.clip(cube.transpose(2, 1, 0, 3) + 0.5, 0, 255).astype(np.uint8)
    Image.fromarray(data.reshape(side, side, 3), "RGB").save(path, optimize=True)


def write_cube(cube, path, title):
    n = cube.shape[0]
    rows = (np.clip(cube, 0, 255) / 255).transpose(2, 1, 0, 3).reshape(-1, 3)
    with open(path, "w") as f:
        f.write(f'TITLE "{title}"\nLUT_3D_SIZE {n}\nDOMAIN_MIN 0.0 0.0 0.0\nDOMAIN_MAX 1.0 1.0 1.0\n')
        np.savetxt(f, rows, fmt="%.6f")
