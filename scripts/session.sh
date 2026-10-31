#!/bin/sh
# Sourced by launcher, guardian and recovery. PID start times avoid PID reuse.
APP=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
STATE="$APP/state"
token() { awk '{print $22}' "/proc/$1/stat" 2>/dev/null; }
same_process() { [ -n "$1" ] && [ -n "$2" ] && [ "$(token "$1")" = "$2" ]; }
owned_host() {
    [ -f "$STATE/host" ] || return 1
    read -r HOST HOST_TOKEN < "$STATE/host"
    same_process "$HOST" "$HOST_TOKEN" || return 1
    exe=$(readlink "/proc/$HOST/exe")
    case "$exe" in "$APP/bin/reeden-kindle") return 0;; "$APP/runtime/reeden-kindle") tr '\000' '\n' < "/proc/$HOST/cmdline" | grep -Fxq "$APP/bin/reeden-kindle";; *) return 1;; esac
}
