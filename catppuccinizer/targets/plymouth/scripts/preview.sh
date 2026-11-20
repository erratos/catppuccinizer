#!/usr/bin/env bash
# Show an installed Plymouth theme without rebooting; always gives control back.
# Run as root by `catppuccinize plymouth --test` (which installs the theme first).
#
#   preview.sh THEME [SECONDS]
#
# - simulates service status messages (names of your running services)
# - always quits Plymouth at the end, even after Ctrl+C, and restores
#   the previous default theme
# Run it from a text console (Ctrl+Alt+F3) if the screen does not switch.

set -u
[[ $EUID -eq 0 ]] || { echo "preview.sh must run as root" >&2; exit 1; }
# system tools only, whatever the caller's PATH
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
export PATH

theme="${1:?Usage: $0 THEME [SECONDS]}"
dur="${2:-10}"
# same rule as catppuccinizer.core.naming.check_name: no "/", "..", leading "-"
[[ "$theme" =~ ^[A-Za-z0-9][A-Za-z0-9._+-]*$ && "$theme" != *..* ]] || { echo "Invalid theme name: $theme" >&2; exit 1; }
[[ "$dur" =~ ^[0-9]+$ ]] || { echo "Invalid duration: $dur" >&2; exit 1; }
prev="$(plymouth-set-default-theme)"
[[ -f "/usr/share/plymouth/themes/$theme/$theme.plymouth" ]] || { echo "Theme not installed: $theme" >&2; exit 1; }

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
