#!/bin/sh
set -u
. "$(dirname -- "$0")/session.sh"
product=$(awk -F, '{print substr($NF,length($NF)-2)}' /mnt/onboard/.kobo/version 2>/dev/null)
[ "$product" = 393 ] || { echo 'Only Kobo Clara Colour product 393 is supported; launch cancelled.'; exit 12; }
mkdir -p "$APP/logs" "$STATE" "$APP/cache" "$APP/userdata" "$APP/storage/books" "$APP/storage/documents" "$APP/storage/screenshots" "$APP/userdata/.config" "$APP/userdata/.local/share" "$APP/userdata/.cache"
# Keep the diagnostics directory and the append-only logs from growing forever on the
# user partition: drop week-old hardware captures and rotate a log once it passes 256 KiB.
find "$STATE" -maxdepth 1 -name 'hardware-events-*' -mtime +7 -exec rm -f {} + 2>/dev/null || true
for log in power.log wifi.log native.log guardian.log; do
    if [ -f "$APP/logs/$log" ] && [ "$(wc -c < "$APP/logs/$log")" -gt 262144 ]; then
        mv -f "$APP/logs/$log" "$APP/logs/$log.1"
    fi
done
STARTED_AT=$(date +%s)
exec >> "$APP/logs/launcher.log" 2>&1
echo "[launcher] $(date)"
if [ -d "$STATE/active" ]; then
    if [ -f "$STATE/owner" ]; then read -r pid start < "$STATE/owner"; if same_process "$pid" "$start"; then echo "Already running"; exit 0; fi; fi
    "$APP/recover.sh"; recovery=$?
    if [ -d "$STATE/active" ]; then
        # Recovery can decide there is nothing to do and leave the lock behind, which
        # makes every later launch look like it did nothing. Only that case is cleared;
        # a recovery that reported failure or busy keeps blocking the launch.
        live=false
        if [ -f "$STATE/owner" ]; then read -r pid start < "$STATE/owner"; same_process "$pid" "$start" && live=true; fi
        if [ "$recovery" -eq 0 ] && [ "$live" = false ]; then
            echo '[launcher] clearing stale session state left by an empty recovery'
            rm -rf "$STATE/active" "$STATE/recovering" "$STATE/owner" "$STATE/host" "$STATE/ready" "$STATE/handoff"
        else
            echo "Previous session recovery is busy or failed; see launcher.log"
            exit 14
        fi
    fi
fi
# Never take display ownership from KOReader. Return to Nickel first.
for pid in $(pidof luajit 2>/dev/null); do
    if tr '\000' ' ' < "/proc/$pid/cmdline" | grep -q reader.lua; then echo "Exit KOReader and launch from NickelMenu"; exit 10; fi
done
NICKEL=$(pidof nickel 2>/dev/null) || { echo "Nickel is not running; refusing to take ownership"; exit 11; }
chmod 755 "$APP"/*.sh "$APP"/bin/* "$APP"/runtime/* "$APP"/checks/* 2>/dev/null || true
[ -f "$APP/SHA256SUMS" ] && [ -s "$APP/SHA256SUMS" ] && [ ! -L "$APP/SHA256SUMS" ] || {
    echo 'Package checksum manifest is missing, empty or not a regular file; reinstall using the computer installer'
    exit 12
}
# Recheck on every launch: resources can disappear after first installation.
# A full SHA-256 pass over ~484 files costs several seconds on the device, which is
# most of the launch delay and used to eat into the first-frame budget. Keep the
# repair path, but skip re-hashing when the manifest is unchanged and every listed
# file still exists; run the full pass at least once a week or whenever that differs.
VERIFY_STAMP="$STATE/verify-stamp"
verify_manifest() {
    if [ -f "$APP/integrity.sh" ]; then
        expected=$(awk '$2 == "integrity.sh" {print $1; n++} END {if (n != 1) exit 1}' "$APP/SHA256SUMS") || exit 12
        actual=$(sha256sum "$APP/integrity.sh") || exit 12
        actual=${actual%% *}
        [ "$actual" = "$expected" ] || { echo 'Integrity helper checksum failed; reinstall the package'; exit 12; }
        if ! sh "$APP/integrity.sh" repair > "$APP/install-verification.log" 2>&1; then
            # Repair can fail on an archive entry this package no longer ships. If every
            # file on disk still matches, nothing needs restoring and the session can run.
            if (cd "$APP" && sha256sum -c SHA256SUMS > "$APP/install-verification.log" 2>&1); then
                echo '[verify] repair failed but every file on disk matches; continuing'
            else
                echo 'Package checksum verification failed; see install-verification.log'
                grep -E 'FAILED|INTEGRITY|No such file|WARNING' "$APP/install-verification.log" | head -n 12
                exit 12
            fi
        fi
    else
        (cd "$APP" && sha256sum -c SHA256SUMS > "$APP/install-verification.log" 2>&1) || { echo "Package checksum verification failed; see install-verification.log"; exit 12; }
    fi
    printf '%s %s\n' "$1" "$(date +%s)" > "$VERIFY_STAMP"
}
stamp=$(cd "$APP" && sha256sum SHA256SUMS) || exit 12
stamp=${stamp%% *}
cached_stamp=""
cached_age=999999
if [ -f "$VERIFY_STAMP" ]; then
    read -r cached_stamp cached_at < "$VERIFY_STAMP" || true
    now=$(date +%s)
    case "$cached_at" in ''|*[!0-9]*) cached_age=999999;; *) cached_age=$((now-cached_at));; esac
fi
if [ "$cached_stamp" = "$stamp" ] && [ "$cached_age" -lt 604800 ] && \
   awk '{print $2}' "$APP/SHA256SUMS" | while IFS= read -r rel; do [ -f "$APP/$rel" ] || exit 1; done; then
    echo '[verify] manifest unchanged and every file present; skipped full hashing'
else
    verify_manifest "$stamp"
fi
: > "$STATE/install-verified"
"$APP/bin/fb-guard" --inspect || { echo "Unsupported framebuffer configuration"; exit 12; }
"$APP/runtime/reeden-kindle" --verify "$APP/bin/reeden-kindle" || exit 13
mkdir "$STATE/active" || exit 14
echo "$$ $(token $$)" > "$STATE/owner"
rm -f "$STATE/host" "$STATE/heartbeat" "$STATE/ready" "$STATE/handoff" "$STATE/asleep" "$STATE/power-cancel" "$STATE/power-phase" "$STATE/power-phase.new" "$STATE/clean-exit" "$STATE/native-was-connected"
: > "$STATE/paused"
if [ -f "$APP/logs/current.log" ]; then mv -f "$APP/logs/current.log" "$APP/logs/previous.log"; fi
: > "$APP/logs/current.log"
REEDEN_CHOICES=
rm -f "$STATE/cover-closed"
finish_session() {
    "$APP/recover.sh"
    if [ -n "$REEDEN_CHOICES" ]; then
        rm -f "$REEDEN_CHOICES/brightness" "$REEDEN_CHOICES/warmth" "$REEDEN_CHOICES/wifi"
        rmdir "$REEDEN_CHOICES" 2>/dev/null || :
    fi
}
trap finish_session EXIT
trap 'exit 143' TERM HUP INT
nohup "$APP/guardian.sh" > "$APP/logs/guardian.log" 2>&1 < /dev/null &
read -r light < /sys/class/backlight/mxc_msp430.0/brightness
read -r warm < /sys/class/backlight/lm3630a_led/color
echo "$light $warm" > "$STATE/light"
if [ -x "$APP/wifi.sh" ] && [ "$("$APP/wifi.sh" status)" = CONNECTED ]; then : > "$STATE/native-was-connected"; fi
REEDEN_CHOICES=$(mktemp -d /tmp/reeden-kobo-choices-XXXXXX) || REEDEN_CHOICES=
export REEDEN_CHOICES
export REEDEN_KOBO_DIR="$APP"
export REEDEN_BUNDLE_DIR="$APP/core"
export REEDEN_ASSETS_DIR="$APP/ui-assets"
export HOME="$APP/userdata" XDG_CONFIG_HOME="$APP/userdata/.config" XDG_DATA_HOME="$APP/userdata/.local/share" XDG_CACHE_HOME="$APP/userdata/.cache"
export TMPDIR="$APP/cache" LANG=C.UTF-8 LC_ALL=C.UTF-8
export PATH="$APP/bin:/usr/local/Kobo:/usr/sbin:/usr/bin:/sbin:/bin"
export REEDEN_LOWMEM_SUPPORTED=0 REEDEN_LOWMEM_DEFAULT=0 REEDEN_LOWMEM_FILE="$APP/userdata/lowmem"
export FLUTTER_FONT_DIRECTORY="$APP/fonts/"
# A Kindle self-update must never replace the Kobo host. No auth checks altered.
export REEDEN_UPDATE_FEED=http://127.0.0.1:9/kobo-updates-disabled.json
export GIO_USE_VFS=local GSETTINGS_BACKEND=memory
export SSL_CERT_FILE="$APP/certs/ca-certificates.crt" SSL_CERT_DIR="$APP/certs"
unset LD_LIBRARY_PATH LD_PRELOAD LD_AUDIT
# Optional per-device animation profile. It lives in userdata so reinstalling or
# upgrading keeps the choice, and stays empty on a stock install.
#   stable (default) | off | timed | reagl | clean
if [ -f "$APP/userdata/turn-profile" ]; then
    profile=$(head -c 32 "$APP/userdata/turn-profile" | tr -d ' \t\r\n')
    case "$profile" in
        stable|off|timed) export REEDEN_TURN_PROFILE="$profile"; unset REEDEN_TEXT_BAND_PATH REEDEN_TEXT_QUALITY_AFTER_TURN REEDEN_TEXT_QUALITY_EVERY ;;
        reagl) export REEDEN_TURN_PROFILE=stable REEDEN_TEXT_BAND_PATH=reagl; unset REEDEN_TEXT_QUALITY_AFTER_TURN REEDEN_TEXT_QUALITY_EVERY ;;
        clean) export REEDEN_TURN_PROFILE=stable REEDEN_TEXT_QUALITY_AFTER_TURN=1; unset REEDEN_TEXT_BAND_PATH REEDEN_TEXT_QUALITY_EVERY ;;
        sweep) export REEDEN_TURN_PROFILE=stable REEDEN_TEXT_QUALITY_AFTER_TURN=1 REEDEN_TEXT_QUALITY_EVERY=5; unset REEDEN_TEXT_BAND_PATH ;;
    esac
fi
cd "$APP/core" || exit 18
"$APP/runtime/reeden-kindle" --library-path "$APP/runtime:$APP/lib:$APP/core/lib" --preload "$APP/lib/libreeden_kobo_compat.so" "$APP/bin/reeden-kindle" >> "$APP/logs/current.log" 2>&1 &
HOST=$!
echo "$HOST $(token "$HOST")" > "$STATE/host"
# Initialize the app while Nickel remains responsive. No framebuffer writes or
# input grabs occur until the engine has delivered an actual frame in memory.
attempt=0
while [ ! -f "$STATE/ready" ]; do
    owned_host || break
    [ -d "$STATE/active" ] && [ ! -d "$STATE/recovering" ] || exit 19
    if [ "$attempt" -ge 20 ]; then echo '[launcher] no first frame in 20s; Nickel was never paused'; exit 20; fi
    sleep 1; attempt=$((attempt+1))
done
if [ -f "$STATE/ready" ]; then
    [ -d "$STATE/active" ] && [ ! -d "$STATE/recovering" ] && [ "$(cat "$STATE/owner" 2>/dev/null)" = "$$ $(token $$)" ] || exit 19
    # KOReader or USB mode may have been entered during warmup. Recheck.
    for pid in $(pidof luajit 2>/dev/null); do
        if tr '\000' ' ' < "/proc/$pid/cmdline" | grep -q reader.lua; then echo 'KOReader entered during warmup; cancel'; exit 10; fi
    done
    pidof nickel >/dev/null 2>&1 || exit 11
    "$APP/native-session.sh" capture || exit 16
    "$APP/bin/fb-guard" --snapshot "$STATE/framebuffer" || exit 15
    "$APP/native-session.sh" stop || exit 17
    [ -d "$STATE/active" ] && [ ! -d "$STATE/recovering" ] && [ "$(cat "$STATE/owner" 2>/dev/null)" = "$$ $(token $$)" ] || exit 19
    : > "$STATE/handoff"
    echo '[launcher] first frame ready; hardware handoff authorized'
    echo "[launcher] first frame took $(( $(date +%s) - STARTED_AT ))s"
    : > "$STATE/first-frame-ok"
fi
wait "$HOST"
code=$?
echo "[launcher] host exit=$code"
exit "$code"
