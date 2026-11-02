#!/bin/sh
# Clara Colour / MT8113T only. Never unload this platform's Wi-Fi modules.
. "$(dirname -- "$0")/session.sh"
export PATH=/usr/local/Kobo:/usr/sbin:/usr/bin:/sbin:/bin
unset LD_LIBRARY_PATH LD_PRELOAD LD_AUDIT
exec >> "$APP/logs/power.log" 2>&1
power_phase() {
    read -r power_uptime power_rest < /proc/uptime
    power_uptime=${power_uptime%%.*}
    printf '%s %s %s\n' "$1" "$power_uptime" "$$" > "$STATE/power-phase.new"
    mv -f "$STATE/power-phase.new" "$STATE/power-phase"
    echo "[power] phase=$1 uptime=$power_uptime pid=$$ $(date)"
}
restore_power_flags() {
    echo 0 > /sys/power/state-extended
    if [ -f "$STATE/power-alarm" ]; then echo 0 > /sys/class/rtc/rtc0/wakealarm; rm -f "$STATE/power-alarm"; fi
}
stop_network() {
    "$APP/wifi.sh" suspend
}
restore_network() {
    restore_power_flags
    if [ -f "$STATE/wifi-restore" ]; then
        if "$APP/wifi.sh" resume; then
            rm -f "$STATE/wifi-restore"
            echo "[power] Wi-Fi services started; actual connection queried separately $(date)"
        else
            echo "[power] Wi-Fi restore failed; retaining retry marker $(date)"
        fi
    fi
}

case "${1:-}" in
restore) restore_network; exit;;
native)
    # A newly started Nickel must own Wi-Fi from the powered-down state.
    # Keeping our supplicant/radio up here can leave its scan UI out of sync.
    restore_power_flags
    if ! "$APP/wifi.sh" native; then echo '[power] native Wi-Fi power-down failed'; exit 1; fi
    rm -f "$STATE/wifi-restore"
    echo "[power] Wi-Fi handed to native UI in powered-down state $(date)"
    exit;;
suspend) ;;
*) exit 64;;
esac
finish_power() {
    power_result=$?
    trap - EXIT
    restore_network
    power_phase complete
    echo "[power] helper exiting=$power_result $(date)"
    exit "$power_result"
}
trap 'finish_power' EXIT
trap 'exit 143' TERM INT HUP
power_phase preparing
echo "[power] preparing $(date)"
# MTK suspend while USB charging can hang the kernel (same guard as KOReader).
if [ "$(cat /sys/class/power_supply/bd71827_bat/status)" != Discharging ]; then
    echo '[power] charging: retaining screen lock without kernel suspend'; exit 3
fi
if ifconfig wlan0 2>/dev/null | grep -q 'UP '; then
    : > "$STATE/wifi-restore"
    stop_network || exit 4
fi
[ ! -f "$STATE/power-cancel" ] || exit 2
echo 1 > /sys/power/state-extended || exit 4
sleep 2
# Update completion does not imply that the panel's XON timers have expired.
# Wait for the driver wake locks AND its XON timers; never force a GPIO or
# shorten a panel-specific timing parameter.
attempt=0
idle=0
while [ "$idle" -lt 2 ]; do
    [ ! -f "$STATE/power-cancel" ] || exit 2
    [ "$attempt" -lt 48 ] || { echo '[power] display did not become idle'; exit 4; }
    if awk '$1 == "hwtcon_wakelock" || $1 == "cmdq_wakelock" { if ($6 != 0) busy=1 } END { exit busy }' /sys/kernel/debug/wakeup_sources && ! grep -q '_hrtint_xon_' /proc/timer_list; then
        idle=$((idle+1))
    else idle=0
    fi
    usleep 250000
    attempt=$((attempt+1))
done
echo "[power] display idle after $attempt polls"
# During physical acceptance only, a previously unused RTC alarm provides a
# bounded wakeup. Never overwrite an existing alarm.
if [ -f "$STATE/power-test" ]; then
    [ -z "$(cat /sys/class/rtc/rtc0/wakealarm)" ] || { echo '[power] existing alarm: suspend cancelled'; exit 2; }
    echo +30 > /sys/class/rtc/rtc0/wakealarm || exit 2
    : > "$STATE/power-alarm"
fi
[ ! -f "$STATE/power-cancel" ] || exit 2
sync
echo "[power] entering mem $(date)"
power_phase suspended
echo mem > /sys/power/state
result=$?
power_phase resuming
echo "[power] mem returned=$result $(date)"
exit "$result"
