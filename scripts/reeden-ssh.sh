#!/bin/sh
set -eu
APP=/mnt/onboard/.adds/reeden-kobo
SERVER="$APP/diagnostics/ssh/reeden-ssh"
PIDFILE=/tmp/dropbear_reeden_diag.pid
if [ -f "$PIDFILE" ]; then
    read -r pid < "$PIDFILE"
    case "$pid" in ''|*[!0-9]*) exit 1;; esac
    if [ -r "/proc/$pid/cmdline" ] && tr '\000' ' ' < "/proc/$pid/cmdline" | grep -Fq "$SERVER "; then
        kill -0 "$pid" && exit 0
    fi
fi
address=$(/sbin/ifconfig wlan0 | awk '/inet addr:/{sub("addr:","",$2);print $2;exit}')
[ -n "$address" ] || { echo 'Enable Wi-Fi first'; exit 1; }
if [ ! -x "$SERVER" ]; then
    [ -f /mnt/onboard/.adds/koreader/dropbear ] || { echo 'KOReader dropbear not found'; exit 1; }
    mkdir -p "$APP/diagnostics/ssh"
    cp /mnt/onboard/.adds/koreader/dropbear "$SERVER"
    chmod 755 "$SERVER"
fi
cd /mnt/onboard/.adds/koreader
# Reuse KOReader's existing host keys and login mode, without exporting keys.
# A separate executable name keeps KOReader's SSH stop action from killing it.
"$SERVER" -E -R -j -k -p "$address:2223" -P "$PIDFILE" -n >> "$APP/diagnostics/ssh/server.log" 2>&1
