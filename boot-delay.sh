#!/usr/bin/env bash
# Keep the Plymouth splash on screen N extra seconds at boot (to enjoy the theme
# on fast machines). Delays plymouth-quit, hence the login screen.
#
#   ./boot-delay.sh 8     # add 8 s (max 15)
#   ./boot-delay.sh off   # remove the delay
set -eu
[[ $EUID -eq 0 ]] || exec sudo "$0" "$@"

dir=/etc/systemd/system/plymouth-quit.service.d
file="$dir/99-boot-delay.conf"
arg="${1:?Usage: $0 <seconds|off>}"

if [[ "$arg" == off ]]; then
    rm -f "$file"
    rmdir "$dir" 2>/dev/null || true
    echo "Delay removed."
else
    [[ "$arg" =~ ^[0-9]+$ ]] && (( arg >= 1 && arg <= 15 )) || { echo "Between 1 and 15 s." >&2; exit 1; }
    install -d "$dir"
    printf '[Service]\nExecStartPre=/usr/bin/sleep %s\n' "$arg" > "$file"
    echo "Plymouth will stay ${arg}s longer on next boot."
fi
systemctl daemon-reload
