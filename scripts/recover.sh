#!/bin/sh
. "$(dirname -- "$0")/session.sh"
[ -d "$STATE/active" ] || exit 0
generation=$(cat "$STATE/owner" 2>/dev/null) || generation=''
if [ "${1:-}" != --locked ]; then
    exec "$APP/bin/fb-guard" --recover-session "$APP" "$generation"
fi
[ "$generation" = "${2:-}" ] || exit 0
# Only the kernel-locked worker reaches here; the directory may be from a crash.
mkdir -p "$STATE/recovering" || exit 1
trap 'rmdir "$STATE/recovering" 2>/dev/null || :' EXIT
echo "[recovery] restoring this session" >> "$APP/logs/launcher.log"
choice_light=-1; choice_warm=-1; choice_wifi=-1; clean_exit=false
if ! owned_host && [ -f "$STATE/handoff" ] && [ ! -f "$STATE/asleep" ] &&
   [ -f "$STATE/clean-exit" ] && [ ! -L "$STATE/clean-exit" ] && [ -f "$STATE/host" ]; then
    read -r host_pid host_start < "$STATE/host"
    if read -r exit_pid level warm radio extra < "$STATE/clean-exit" &&
       [ "$exit_pid" = "$host_pid" ] && [ -n "$host_pid" ] && [ -z "$extra" ]; then
        choice_light=$level; choice_warm=$warm; choice_wifi=$radio
        clean_exit=true
    fi
fi
valid_level() {
    case "$1" in ''|*[!0-9]*|????*) return 1;; esac
    [ "$1" -le "$2" ]
}
restore_lights() {
    [ -f "$STATE/light" ] || return 0
    read -r brightness warmth < "$STATE/light" || return 0
    if valid_level "$choice_light" 100; then brightness=$choice_light; fi
    if valid_level "$choice_warm" 10; then warmth=$choice_warm; fi
    if valid_level "$brightness" 100; then echo "$brightness" > /sys/class/backlight/mxc_msp430.0/brightness; fi
    if valid_level "$warmth" 10; then echo "$warmth" > /sys/class/backlight/lm3630a_led/color; fi
}
if owned_host; then
    kill -TERM "$HOST" 2>/dev/null || :
    i=0
    while owned_host && [ "$i" -lt 5 ]; do sleep 1; i=$((i+1)); done
    if owned_host; then kill -KILL "$HOST" 2>/dev/null || :; sleep 1; fi
fi
case "${HOST:-}" in ''|*[!0-9]*) :;; *) rm -f "/tmp/reeden-kobo-$HOST.heartbeat";; esac
if [ -f "$STATE/night-invert" ]; then
    # Reset our global hardware inversion before Nickel owns the framebuffer.
    if printf 'night_mode 0' > /proc/hwtcon/cmd; then rm -f "$STATE/night-invert"; fi
fi
radio_failed=false
# Nickel re-applies the brightness stored in its own configuration when it starts,
# which is why a level chosen inside the reader was lost on exit. Write the hardware
# level into [PowerOptions] first so both UIs agree.
sync_nickel_light() {
    [ "$clean_exit" = true ] && valid_level "$choice_light" 100 && [ "$choice_light" -gt 0 ] || return 0
    cfg=${NICKEL_CONF:-/mnt/onboard/.kobo/Kobo/Kobo eReader.conf}
    [ -f "$cfg" ] && [ ! -L "$cfg" ] || return 0
    light_path=${LIGHT_PATH:-/sys/class/backlight/mxc_msp430.0/brightness}
    [ -r "$light_path" ] || return 0
    level=$(cat "$light_path" 2>/dev/null) || return 0
    case "$level" in ''|*[!0-9]*) return 0;; esac
    [ "$level" -gt 0 ] && [ "$level" -le 100 ] || return 0
    [ "$level" = "$choice_light" ] || return 0
    light_state=true
    current=$(awk '/^\[PowerOptions\]/{po=1;next} /^\[/{po=0} po&&/^FrontLightLevel[ \t]*=/{split($0,a,"=");gsub(/[ \t]/,"",a[2]);print a[2];exit}' "$cfg" 2>/dev/null)
    [ "$current" = "$level" ] && return 0
    tmp=$(mktemp "$cfg.reeden-XXXXXX") || return 1
    cp -p "$cfg" "$tmp" || { rm -f "$tmp"; return 1; }
    awk -v level="$level" -v state="$light_state" '
        { lines[NR]=$0 }
        END {
            for (i=1;i<=NR;i++) {
                line=lines[i]
                if (line ~ /^\[PowerOptions\][ \t]*$/) {
                    print line; print "FrontLightLevel=" level; print "FrontLightState=" state
                    inpo=1; found=1; continue
                }
                if (line ~ /^\[/) { inpo=0 }
                if (inpo && line ~ /^FrontLight(Level|State)[ \t]*=/) { continue }
                print line
            }
            if (!found) { print "[PowerOptions]"; print "FrontLightLevel=" level; print "FrontLightState=" state }
        }' "$cfg" > "$tmp" || { rm -f "$tmp"; return 1; }
    if [ -s "$tmp" ] && mv -f "$tmp" "$cfg"; then
        echo "[recovery] Nickel brightness updated to $level" >> "$APP/logs/launcher.log"
    else
        rm -f "$tmp"
        echo "[recovery] Nickel brightness update failed; hardware value kept" >> "$APP/logs/launcher.log"
        return 1
    fi
}
if [ -f "$STATE/native-restart" ]; then
    starting_native=false
    # Do not reset the radio underneath an already running Nickel.
    if ! pidof nickel >/dev/null 2>&1; then
        starting_native=true
        touch "$STATE/native-wifi-pending" || echo "[recovery] unable to persist Wi-Fi retry marker" >&2
        if "$APP/power.sh" native; then
            rm -f "$STATE/native-wifi-pending"
        else
            radio_failed=true
            echo "[recovery] native Wi-Fi handoff failed; continuing native UI restoration" >> "$APP/logs/launcher.log"
        fi
        restore_lights
        sync_nickel_light || true
    fi
    if ! "$APP/native-session.sh" start; then
        echo "[recovery] native restart failed; session state retained for retry" >> "$APP/logs/launcher.log"
        exit 1
    fi
    if [ "$starting_native" = true ] && [ "$radio_failed" = false ]; then
        case "$choice_wifi" in 0|1) request=$choice_wifi;;
            *) request=none; [ ! -f "$STATE/native-was-connected" ] || request=reconnect;;
        esac
        if [ "$request" != none ]; then
            if "$APP/native-session.sh" wifi-choice "$request"; then
                echo '[recovery] native Wi-Fi preference requested; connection unverified' >> "$APP/logs/launcher.log"
            else
                echo '[recovery] native Wi-Fi preference unavailable; Nickel retains control' >> "$APP/logs/launcher.log"
            fi
        fi
    fi
elif [ -s "$STATE/paused" ]; then
    # Restore framebuffer while Nickel is still paused, then resume exact PIDs.
    restore_lights
    if [ -f "$STATE/framebuffer" ]; then
        "$APP/bin/fb-guard" --restore "$STATE/framebuffer" >> "$APP/logs/launcher.log" 2>&1 &
        refresh=$!
        i=0; while kill -0 "$refresh" 2>/dev/null && [ "$i" -lt 5 ]; do sleep 1; i=$((i+1)); done
        if kill -0 "$refresh" 2>/dev/null; then
            kill -KILL "$refresh" 2>/dev/null || :
            echo "[recovery] framebuffer helper timed out; continuing process restoration" >> "$APP/logs/launcher.log"
            # Do not wait on a task stuck in a kernel ioctl: resume Nickel anyway.
        else
            wait "$refresh" 2>/dev/null || :
        fi
    fi
    # Nickel must be responsive before its watchdogs resume checking it.
    for phase in nickel watchdogs; do
        while read -r pid start name; do
            case "$phase:$name" in nickel:nickel|watchdogs:sickel|watchdogs:hindenburg|watchdogs:fickel|watchdogs:strickel) :;; *) continue;; esac
            if same_process "$pid" "$start" && [ "$(cat "/proc/$pid/comm" 2>/dev/null)" = "$name" ]; then
                kill -CONT "$pid" 2>/dev/null || :
            fi
        done < "$STATE/paused"
        [ "$phase" != nickel ] || sleep 1
    done
fi
rm -f "$STATE/clean-exit" "$STATE/native-was-connected" "$STATE/cover-closed"
rm -f "$STATE/host" "$STATE/owner" "$STATE/paused" "$STATE/light" "$STATE/framebuffer" "$STATE/heartbeat" "$STATE/ready" "$STATE/handoff" "$STATE/asleep" "$STATE/power-cancel" "$STATE/power-phase" "$STATE/power-phase.new" "$STATE/native-restart" "$STATE/native-env" "$STATE/native-pids"
rmdir "$STATE/active" || { echo "[recovery] active state could not be cleared" >> "$APP/logs/launcher.log"; exit 1; }
if [ "$radio_failed" = true ] || [ -f "$STATE/native-wifi-pending" ]; then
    echo "[recovery] native Wi-Fi handoff pending; retry before the next native start" >> "$APP/logs/launcher.log"
    exit 1
fi
echo "[recovery] completed" >> "$APP/logs/launcher.log"
