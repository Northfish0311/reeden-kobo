#!/bin/sh
# Optional diagnostics only. No autostart and no password-bypass mode.
set -eu
APP=/mnt/onboard/.adds/reeden-kobo
SSH_HOME="$APP/diagnostics/ssh"
SERVER="$SSH_HOME/reeden-ssh"
KEYS="$SSH_HOME/settings/SSH/authorized_keys"
PIDFILE=/tmp/dropbear_reeden_diag.pid
owned_server() {
    [ -f "$PIDFILE" ] || return 1
    read -r pid < "$PIDFILE" || return 1
    case "$pid" in ''|*[!0-9]*) return 1;; esac
    [ -r "/proc/$pid/cmdline" ] || return 1
    tr '\000' '\n' < "/proc/$pid/cmdline" | grep -Fxq "$SERVER" || return 1
    kill -0 "$pid" 2>/dev/null
}
case "${1:-status}" in
status)
    if owned_server; then
        if tr '\000' '\n' < "/proc/$pid/cmdline" | grep -Fxq -- '-n'; then
            echo 'Legacy insecure SSH listener is running. Stop it, configure a public key, then start again.'
        else echo 'SSH listener is running; use stop to close the listener.'; fi
    else echo 'Reeden SSH is stopped. Public releases never start SSH automatically.'; fi
    exit 0;;
stop)
    if owned_server; then
        kill -TERM "$pid"
        echo 'SSH listener stop requested. Existing authenticated sessions may remain until disconnected.'
    else echo 'No owned SSH listener is running.'; fi
    exit 0;;
start) ;;
*) echo 'Usage: reeden-ssh.sh start|stop|status'; exit 64;;
esac
if owned_server; then
    echo 'An SSH listener already exists. Check status and stop it before restarting.' >&2
    exit 1
fi
[ -s "$KEYS" ] && grep -Eq '^(ssh-ed25519|ssh-rsa|ecdsa-sha2-[^ ]+) [A-Za-z0-9+/=]+' "$KEYS" || {
    echo "Key-only SSH requires your public key in $KEYS; no server was started." >&2; exit 1;
}
address=$(/sbin/ifconfig wlan0 | awk '/inet addr:/{sub("addr:","",$2);print $2;exit}')
[ -n "$address" ] || { echo 'Enable Wi-Fi first'; exit 1; }
if [ ! -x "$SERVER" ]; then
    [ -f /mnt/onboard/.adds/koreader/dropbear ] || { echo 'Optional SSH requires KOReader dropbear; the reader itself does not.'; exit 1; }
    cp /mnt/onboard/.adds/koreader/dropbear "$SERVER"
    chmod 755 "$SERVER"
fi
# KOReader's patched server reads keys and host keys relative to cwd.
cd "$SSH_HOME"
"$SERVER" -E -R -s -j -k -p "$address:2223" -P "$PIDFILE" >> "$SSH_HOME/server.log" 2>&1
