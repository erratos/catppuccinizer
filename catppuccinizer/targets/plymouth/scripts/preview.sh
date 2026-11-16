#!/usr/bin/env bash
# Preview a Plymouth theme without rebooting; always gives control back.
#
#   ./preview.sh [theme] [seconds]
#   ./preview.sh catppuccin-mocha-hexa-retro-status 12
#
# - no theme: uses the current default theme
# - copies the theme from themes/ (or from a given folder) if available
# - simulates service status messages (names of your running services)
# - always quits Plymouth at the end, even after Ctrl+C, and restores
#   the previous default theme
# Run it from a text console (Ctrl+Alt+F3) if the screen does not switch.

set -u
[[ $EUID -eq 0 ]] || exec sudo "$0" "$@"

prev="$(plymouth-set-default-theme)"
arg="${1:-$prev}"
dur="${2:-10}"

if [[ -d "$arg" ]]; then
    src="$(readlink -f "$arg")"
else
    src="$PWD/themes/$arg"
fi
theme="$(basename "$src")"
dest="/usr/share/plymouth/themes/$theme"

if [[ -d "$src" ]]; then
    install -d "$dest"
    cp -r "$src"/. "$dest/"
fi
[[ -f "$dest/$theme.plymouth" ]] || { echo "Theme not found: $theme" >&2; exit 1; }

cleanup() {
    plymouth --quit 2>/dev/null
    sleep 0.5
    pkill -x plymouthd 2>/dev/null
    [[ "$theme" != "$prev" ]] && plymouth-set-default-theme "$prev"
}
trap cleanup EXIT INT TERM

plymouth --ping 2>/dev/null && { plymouth --quit; sleep 1; }
[[ "$theme" != "$prev" ]] && plymouth-set-default-theme "$theme"

echo "Previewing $theme for ${dur}s..."
plymouthd || exit 1
plymouth --show-splash

# real names of running services, sent one by one like systemd does
mapfile -t units < <(systemctl list-units --type=service --state=running \
                       --no-legend --plain | awk '{print $1}' | shuf -n 40)
end=$((SECONDS + dur))
i=0
while (( SECONDS < end )); do
    plymouth update --status="${units[i % ${#units[@]}]:-test.service}"
    i=$((i + 1))
    sleep 0.4
done
