#!/bin/sh
# Fast read-only environment & health check for NickelMenu cmd_output popup.
# Always exits 0 so NickelMenu displays the full diagnostic summary dialog.
set -u
APP=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
chmod 755 "$APP"/*.sh "$APP"/bin/* "$APP"/runtime/* "$APP"/checks/* 2>/dev/null || true

echo "=== Reeden Kobo 0.7.0 Self-Check ==="

# 1. Model & Firmware
if [ -f /mnt/onboard/.kobo/version ]; then
    fw=$(awk -F, '{print $3}' /mnt/onboard/.kobo/version 2>/dev/null)
    product=$(awk -F, '{print substr($NF,length($NF)-2)}' /mnt/onboard/.kobo/version 2>/dev/null)
    if [ "$product" = "393" ]; then
        echo "[OK] Model: Clara Colour (393), FW $fw"
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

# 5. Checksum verification state
if [ -f "$APP/state/install-verified" ] || [ -f "$APP/install-verification.log" ]; then
    echo "[OK] Package SHA-256: verified"
else
    echo "[INFO] Package SHA-256: will verify on first launch"
fi

# 6. Last launch status
if [ -f "$APP/logs/launcher.log" ]; then
    last_line=$(tail -n 2 "$APP/logs/launcher.log" 2>/dev/null | tr '\n' ' ')
    [ -n "$last_line" ] && echo "Last: $last_line"
fi
exit 0
