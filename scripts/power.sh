#!/bin/sh
# Clara Colour / MT8113T only. Never unload this platform's Wi-Fi modules.
. "$(dirname -- "$0")/session.sh"
export PATH=/usr/local/Kobo:/usr/sbin:/usr/bin:/sbin:/bin
unset LD_LIBRARY_PATH LD_PRELOAD LD_AUDIT
exec >> "$APP/logs/power.log" 2>&1
echo "[power] invoked arg=${1:-} $(date)"
power_phase() {
    read -r power_uptime power_rest < /proc/uptime
    power_uptime=${power_uptime%%.*}
    printf '%s %s %s\n' "$1" "$power_uptime" "$$" > "$STATE/power-phase.new"
    mv -f "$STATE/power-phase.new" "$STATE/power-phase"
    echo "[power] phase=$1 uptime=$power_uptime pid=$$ $(date)"
}
power_sample() {
    battery=$(cat /sys/class/power_supply/bd71827_bat/status 2>/dev/null) || battery=unreadable
    case "$battery" in Discharging|Charging|Full|Unknown|unreadable) :;; 'Not charging') battery=NotCharging;; *) battery=unknown;; esac
    capacity=$(cat /sys/class/power_supply/bd71827_bat/capacity 2>/dev/null) || capacity=unknown
    case "$capacity" in ''|*[!0-9]*|????*) capacity=unknown;; *) [ "$capacity" -le 100 ] || capacity=unknown;; esac
    external=unexposed
    for supply in /sys/class/power_supply/*; do
        [ -f "$supply/online" ] || continue
        case "$(cat "$supply/type" 2>/dev/null)" in USB*|Mains|Wireless) :;; *) continue;; esac
        case "$(cat "$supply/online" 2>/dev/null)" in
            0) [ "$external" != unexposed ] || external=off;;
            1|2) external=on; break;;
            *) external=unknown;;
        esac
    done
    echo "[power] sample=$1 battery=$battery external=$external capacity=$capacity"
}
on_battery() {
    power_sample "$1"
    [ "$battery" = Discharging ] && { [ "$external" = off ] || [ "$external" = unexposed ]; } && return 0
    echo "[power] screen-only: supply guard battery=$battery external=$external"
    return 1
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
            return 1
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
    if [ -f "$STATE/cover-closed" ] && [ ! -f "$STATE/power-cancel" ]; then
        restore_power_flags
        [ ! -f "$STATE/wifi-restore" ] || echo '[power] Wi-Fi resume deferred while cover remains closed'
    else
        restore_network
    fi
    power_phase complete
    echo "[power] helper exiting=$power_result $(date)"
    exit "$power_result"
}
trap 'finish_power' EXIT
trap 'exit 143' TERM INT HUP
power_phase preparing
echo "[power] preparing $(date)"
# MTK suspend while USB charging can hang the kernel (same guard as KOReader).
on_battery prepare || exit 3
if ifconfig wlan0 2>/dev/null | grep -q 'UP '; then
    : > "$STATE/wifi-restore"
    stop_network || { echo '[power] Wi-Fi could not be suspended'; exit 4; }
fi
[ ! -f "$STATE/power-cancel" ] || exit 2
echo 1 > /sys/power/state-extended || exit 4
sleep 2
# Update completion does not imply that the panel's XON timers have expired.
# Wait for the driver wake locks AND its XON timers; never force a GPIO or
# shorten a panel-specific timing parameter.
attempt=0
idle=0
check_locks=true
if [ ! -r /sys/kernel/debug/wakeup_sources ]; then
    check_locks=false
    echo '[power] wakeup_sources unreadable; fixed settle before suspend'
    sleep 2
fi
# A missing debug view does not make an observable XON timer disappear.
while [ "$idle" -lt 2 ]; do
    [ ! -f "$STATE/power-cancel" ] || exit 2
    [ "$attempt" -lt 48 ] || { echo '[power] display did not become idle'; exit 75; }
    busy=false
    if [ "$check_locks" = true ]; then
        awk '$1 == "hwtcon_wakelock" || $1 == "cmdq_wakelock" { if ($6 != 0) busy=1 } END { exit (NR ? busy : 2) }' /sys/kernel/debug/wakeup_sources || busy=true
    fi
    if [ -r /proc/timer_list ]; then
        grep -q '_hrtint_xon_' /proc/timer_list
        [ "$?" = 1 ] || busy=true
    fi
    if [ "$busy" = false ]; then idle=$((idle+1)); else idle=0; fi
    attempt=$((attempt+1))
    [ "$idle" -eq 2 ] || usleep 250000
done
echo "[power] display settle completed after $attempt polls"
# During physical acceptance only, a previously unused RTC alarm provides a
# bounded wakeup. Never overwrite an existing alarm.
if [ -f "$STATE/power-test" ]; then
    [ -z "$(cat /sys/class/rtc/rtc0/wakealarm)" ] || { echo '[power] existing alarm: suspend cancelled'; exit 2; }
    echo +30 > /sys/class/rtc/rtc0/wakealarm || exit 2
    : > "$STATE/power-alarm"
fi
[ ! -f "$STATE/power-cancel" ] || exit 2
sync
on_battery before_mem || exit 3
[ ! -f "$STATE/power-cancel" ] || exit 2
echo "[power] entering mem $(date)"
power_phase suspended
began=$power_uptime
echo mem > /sys/power/state
result=$?
power_phase resuming
echo "[power] mem returned=$result $(date)"
power_sample after_mem
# An immediate kernel return is not by itself a user request to turn the
# light back on. Leave the host time to receive the wake key before retrying.
case "$began:$power_uptime" in *[!0-9:]*|:*|*:) ;;
*) span=$((power_uptime-began))
   if [ "$result" = 0 ] && [ "$span" -ge 0 ] && [ "$span" -le 5 ] &&
      [ ! -f "$STATE/power-cancel" ] && [ ! -f "$STATE/power-test" ]; then
       echo "[power] short mem return after ${span}s; wake source unknown"
       exit 76
   fi;;
esac
exit "$result"
