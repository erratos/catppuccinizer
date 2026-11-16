#!/usr/bin/env python3
"""Backward-compatible alias of `catppuccinize plymouth ...`."""
import sys

from catppuccinizer.cli import main

if __name__ == "__main__":
    main(["plymouth", *sys.argv[1:]])
