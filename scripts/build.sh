#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
if [ -z "${ZIG:-}" ]; then
    if [ -x "$ROOT/../toolchains/zig-macos-aarch64-0.13.0/zig" ]; then
        ZIG="$ROOT/../toolchains/zig-macos-aarch64-0.13.0/zig"
    elif command -v zig >/dev/null 2>&1; then
        ZIG=$(command -v zig)
    else
        echo "Set ZIG to the Zig 0.13.0 binary" >&2
        exit 1
    fi
fi
mkdir -p "$ROOT/build" "$ROOT/package/bin" "$ROOT/package/lib"
cd "$ROOT"
if [ -n "${REEDEN_OFFICIAL_CORE:-}" ] && [ -f "${REEDEN_OFFICIAL_CORE}/lib/libflutter_engine.so" ]; then
    ENGINE_LIB_DIR="${REEDEN_OFFICIAL_CORE}/lib"
else
    mkdir -p "$ROOT/build/stub"
    "$ZIG" cc -target arm-linux-gnueabihf.2.17 -shared -fPIC \
        "$ROOT/src/flutter_engine_stub.c" -Wl,-soname,libflutter_engine.so \
        -Wl,--version-script="$ROOT/src/flutter_engine.map" \
        -o "$ROOT/build/stub/libflutter_engine.so"
    ENGINE_LIB_DIR="$ROOT/build/stub"
fi
# Sources are compiled with relative paths and without -g so that neither the
# DWARF debug info nor the STT_FILE symbol-table entries can embed the
# build machine's checkout directory, Zig installation path or username.
# This is required both for privacy and for byte-identical reproduction on CI.
"$ZIG" cc -target arm-linux-gnueabihf.2.28 -mcpu=cortex_a7 -fPIC -pie -O2 -Wall -Wextra -Werror -Wno-unused-parameter -Iinclude -Isrc -Ivendor \
    src/host.c src/power_worker.c src/cover.c src/display.c src/refresh_policy.c src/turn_timing.c src/frame_evidence.c src/light_panel.c src/input.c src/codec.c vendor/cJSON.c \
    -L"$ENGINE_LIB_DIR" -lflutter_engine -lpthread -ldl -lm -Wl,-rpath,'$ORIGIN/../core/lib:$ORIGIN/../lib' \
    -Wl,--strip-all -o "$ROOT/package/bin/reeden-kindle"
"$ZIG" cc -target arm-linux-gnueabihf.2.17 -mcpu=cortex_a7 -O2 -Wall -Wextra -Werror -shared -fPIC \
    src/path_compat.c -ldl -Wl,-soname,libreeden_kobo_compat.so -Wl,--strip-all -o "$ROOT/package/lib/libreeden_kobo_compat.so"
"$ZIG" cc -target arm-linux-musleabihf -static -mcpu=cortex_a7 -O2 -Wall -Wextra -Werror src/fb_guard.c -Wl,--strip-all -o "$ROOT/package/bin/fb-guard"
echo "Built Kobo host, path/child-runtime compatibility library and framebuffer guard"

"$ZIG" cc -target arm-linux-gnueabihf.2.17 -mcpu=cortex_a7 -fPIC -pie -O2 -Wall -Wextra -Werror -Isrc tests/codec_test.c src/codec.c -Wl,--strip-all -o "$ROOT/build/codec-test-armhf"

"$ZIG" cc -target arm-linux-gnueabihf.2.17 -mcpu=cortex_a7 -fPIC -pie -O2 -Wall -Wextra -Werror -Wno-unused-parameter -D_GNU_SOURCE -Iinclude -Isrc tests/input_test.c src/input.c -lpthread -Wl,--strip-all -o "$ROOT/build/input-test-armhf"
"$ZIG" cc -target arm-linux-gnueabihf.2.28 -mcpu=cortex_a7 -fPIC -pie -O2 -Wall -Wextra -Werror tests/compat_test.c -ldl -Wl,--strip-all -o "$ROOT/build/compat-test-armhf"

"$ZIG" cc -target arm-linux-gnueabihf.2.28 -mcpu=cortex_a7 -fPIC -pie -O2 -Wall -Wextra -Werror -Iinclude tests/runtime_test.c -L"$ENGINE_LIB_DIR" -lflutter_engine -Wl,--strip-all -o "$ROOT/build/runtime-test-armhf"
"$ZIG" cc -target arm-linux-musleabihf -static -mcpu=cortex_a7 -O2 -Wall -Wextra -Werror -Isrc tests/refresh_policy_test.c src/refresh_policy.c -Wl,--strip-all -o "$ROOT/build/refresh-policy-test-armhf"
"$ZIG" cc -target arm-linux-musleabihf -static -mcpu=cortex_a7 -O2 -Wall -Wextra -Werror -Isrc tests/power_worker_test.c src/power_worker.c -lpthread -Wl,--strip-all -o "$ROOT/build/power-worker-test-armhf"
"$ZIG" cc -target arm-linux-musleabihf -static -mcpu=cortex_a7 -O2 -Wall -Wextra -Werror -Iinclude -Isrc tests/display_transaction_test.c src/refresh_policy.c src/turn_timing.c src/frame_evidence.c -lpthread -Wl,--strip-all -o "$ROOT/build/display-transaction-test-armhf"

# Guard: refuse to ship any binary that still embeds an absolute build path.
# (Runtime paths such as /tmp/reeden-kobo-*.heartbeat are intentional and
# do not match; only build-machine paths like the Zig installation directory,
# the checkout directory under /Users or /home, or macOS /private prefixes.)
"${PYTHON:-python3}" "$ROOT/scripts/check_build_paths.py" \
    "$ROOT/package/bin/reeden-kindle" \
    "$ROOT/package/bin/fb-guard" \
    "$ROOT/package/lib/libreeden_kobo_compat.so" \
    "$ROOT/build/codec-test-armhf" \
    "$ROOT/build/input-test-armhf" \
    "$ROOT/build/compat-test-armhf" \
    "$ROOT/build/runtime-test-armhf" \
    "$ROOT/build/refresh-policy-test-armhf" \
    "$ROOT/build/power-worker-test-armhf" \
    "$ROOT/build/display-transaction-test-armhf"
echo "Path-leak guard: no absolute build paths embedded in any shipped artifact"
