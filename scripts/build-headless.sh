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
mkdir -p "$ROOT/build/headless"
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
"$ZIG" cc -target arm-linux-gnueabihf.2.28 -mcpu=cortex_a7 -fPIC -pie -O2 -Wall -Wextra -Werror -Wno-unused-parameter -DREEDEN_HEADLESS_DIAGNOSTIC \
    -Iinclude -Isrc -Ivendor -Itests \
    src/host.c src/power_worker.c src/display.c src/refresh_policy.c src/turn_timing.c src/frame_evidence.c src/light_panel.c src/input.c src/codec.c vendor/cJSON.c \
    -L"$ENGINE_LIB_DIR" -lflutter_engine -lpthread -ldl -lm -Wl,--strip-all -o "$ROOT/build/headless/reeden-kindle"
echo 'Built diagnostic host; not deployed or run'
