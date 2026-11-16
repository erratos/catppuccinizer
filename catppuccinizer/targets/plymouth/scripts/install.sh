#!/usr/bin/env bash
# Install a theme, set it as default and rebuild the initramfs.
#
#   ./install.sh catppuccin-mocha-hexa-retro          # theme generated in themes/
#   ./install.sh ./catppuccin-mocha-hexa-retro        # folder extracted from a release
set -euo pipefail
[[ $EUID -eq 0 ]] || exec sudo "$0" "$@"

arg="${1:?Usage: $0 <theme-name | path/to/theme-folder>}"
if [[ -d "$arg" ]]; then
    src="$(readlink -f "$arg")"
else
    src="$PWD/themes/$arg"
fi
name="$(basename "$src")"
[[ -f "$src/$name.plymouth" ]] || { echo "Theme not found: $src" >&2; exit 1; }

install -d "/usr/share/plymouth/themes/$name"
cp -r "$src"/. "/usr/share/plymouth/themes/$name/"
plymouth-set-default-theme -R "$name"   # -R: rebuild the initramfs
echo "Theme $name installed and enabled."
