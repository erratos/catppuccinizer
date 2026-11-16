"""catppuccinizer: recolour boot themes, wallpapers and other artwork with Catppuccin.

catppuccinizer.core     palettes, colour detection, recolouring, formats
catppuccinizer.targets  one module per target (plymouth, image, limine, ksplash)

A target only uses catppuccinizer.core, never another target. Third-party
targets can be added with the "catppuccinizer.targets" entry point group.
"""
__version__ = "2.0.0"
