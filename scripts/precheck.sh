#!/bin/sh
# Environment and current-file integrity check for NickelMenu cmd_output popup.
# Always exits 0 so NickelMenu displays the full diagnostic summary dialog.
set -u
APP=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

port_ver=$(sed -n 's/.*"port_version":[[:space:]]*"\([^"]*\)".*/\1/p' "$APP/build-info.json" 2>/dev/null | head -n 1)
echo "=== Reeden Kobo ${port_ver:-unknown} Self-Check ==="

# 1. Model & Firmware
fw_baseline=$(sed -n 's/.*"firmware":[[:space:]]*"\([^"]*\)".*/\1/p' "$APP/build-info.json" 2>/dev/null | head -n 1)
if [ -f /mnt/onboard/.kobo/version ]; then
    fw=$(awk -F, '{print $3}' /mnt/onboard/.kobo/version 2>/dev/null)
    product=$(awk -F, '{print substr($NF,length($NF)-2)}' /mnt/onboard/.kobo/version 2>/dev/null)
    if [ "$product" = "393" ]; then
        echo "[OK] Model: Clara Colour (393), FW $fw"
        if [ -n "${fw_baseline:-}" ] && [ "$fw" != "$fw_baseline" ]; then
            echo "[WARN] FW $fw differs from the validated baseline $fw_baseline"
        fi
    else
        echo "[FAIL] Model code: $product (FW $fw) - Only 393 supported"
    fi
else
    echo "[WARN] /mnt/onboard/.kobo/version not found"
fi

# 2. Framebuffer & Rotation
fb_out=$("$APP/bin/fb-guard" --inspect 2>&1)
if [ $? -eq 0 ]; then
    echo "[OK] Display: $fb_out"
else
    echo "[FAIL] Display: $fb_out (Ensure portrait rotation=3)"
fi

# 3. Official Core & Loader
if [ -f "$APP/core/lib/libflutter_engine.so" ] && [ -f "$APP/core/lib/libapp.so" ] && [ -f "$APP/ui-assets/assets/fonts/KoboCJKMath-Regular.ttf" ]; then
    if "$APP/runtime/reeden-kindle" --verify "$APP/bin/reeden-kindle" >/dev/null 2>&1; then
        core_ver=$(sed -n 's/.*"official_version":[[:space:]]*"\([^"]*\)".*/\1/p' "$APP/build-info.json" 2>/dev/null | head -n 1)
        echo "[OK] Core ${core_ver:-verified} & ARMHF Loader verified"
    else
        echo "[FAIL] Private glibc loader verify failed"
    fi
else
    echo "[FAIL] Missing official core or CJK/Math font overlay"
fi

# 4. Backlight & Warmth interfaces
if [ -r /sys/class/backlight/mxc_msp430.0/brightness ] && [ -r /sys/class/backlight/lm3630a_led/color ]; then
    read -r br < /sys/class/backlight/mxc_msp430.0/brightness 2>/dev/null || br="?"
    read -r wm < /sys/class/backlight/lm3630a_led/color 2>/dev/null || wm="?"
    echo "[OK] Light sysfs: brightness=$br, raw_mixer=$wm"
else
    echo "[WARN] Frontlight/warmth sysfs path missing"
fi

# 5. Check the current files, never infer success from an old log/marker.
if [ -f "$APP/SHA256SUMS" ]; then
    check_log=$(mktemp /tmp/reeden-check-XXXXXX) || { echo '[FAIL] Unable to create checksum scratch file'; exit 0; }
    trap 'rm -f "$check_log"' EXIT
    trap 'exit 0' HUP INT TERM
    if (cd "$APP" && sha256sum -c SHA256SUMS) > "$check_log" 2>&1; then
        echo '[OK] Package SHA-256: current files verified'
    else
        echo '[FAIL] Package SHA-256: current file checksum failed'
        grep -E 'FAILED|No such file|WARNING|INTEGRITY' "$check_log" | head -n 12
        echo '[INFO] Full details: .adds/reeden-kobo/install-verification.log after a failed launch'
    fi
else
    echo '[FAIL] Package SHA-256: manifest missing'
fi

# 6. Last launch status
if [ -f "$APP/logs/launcher.log" ]; then
    last_line=$(tail -n 2 "$APP/logs/launcher.log" 2>/dev/null | tr '\n' ' ')
    [ -n "$last_line" ] && echo "Last: $last_line"
fi
exit 0
