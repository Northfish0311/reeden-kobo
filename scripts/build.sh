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
"$ZIG" cc -target arm-linux-gnueabihf.2.28 -mcpu=cortex_a7 -ffile-prefix-map="$ROOT"=. -fPIC -pie -O2 -g -Wall -Wextra -Werror -Wno-unused-parameter -I"$ROOT/include" -I"$ROOT/src" -I"$ROOT/vendor" \
    "$ROOT/src/host.c" "$ROOT/src/power_worker.c" "$ROOT/src/display.c" "$ROOT/src/refresh_policy.c" "$ROOT/src/light_panel.c" "$ROOT/src/input.c" "$ROOT/src/codec.c" "$ROOT/vendor/cJSON.c" \
    -L"$ENGINE_LIB_DIR" -lflutter_engine -lpthread -ldl -lm -Wl,-rpath,'$ORIGIN/../core/lib:$ORIGIN/../lib' \
    -o "$ROOT/package/bin/reeden-kindle"
"$ZIG" cc -target arm-linux-gnueabihf.2.17 -mcpu=cortex_a7 -ffile-prefix-map="$ROOT"=. -O2 -g -Wall -Wextra -Werror -shared -fPIC \
    "$ROOT/src/path_compat.c" -ldl -Wl,-soname,libreeden_kobo_compat.so -o "$ROOT/package/lib/libreeden_kobo_compat.so"
"$ZIG" cc -target arm-linux-musleabihf -static -mcpu=cortex_a7 -ffile-prefix-map="$ROOT"=. -O2 -g -Wall -Wextra -Werror "$ROOT/src/fb_guard.c" -o "$ROOT/package/bin/fb-guard"
echo "Built Kobo host, path/child-runtime compatibility library and framebuffer guard"

"$ZIG" cc -target arm-linux-gnueabihf.2.17 -mcpu=cortex_a7 -ffile-prefix-map="$ROOT"=. -fPIC -pie -O2 -Wall -Wextra -Werror -I"$ROOT/src" "$ROOT/tests/codec_test.c" "$ROOT/src/codec.c" -o "$ROOT/build/codec-test-armhf"

"$ZIG" cc -target arm-linux-gnueabihf.2.17 -mcpu=cortex_a7 -ffile-prefix-map="$ROOT"=. -fPIC -pie -O2 -Wall -Wextra -Werror -Wno-unused-parameter -D_GNU_SOURCE -I"$ROOT/include" -I"$ROOT/src" "$ROOT/tests/input_test.c" "$ROOT/src/input.c" -lpthread -o "$ROOT/build/input-test-armhf"
"$ZIG" cc -target arm-linux-gnueabihf.2.28 -mcpu=cortex_a7 -ffile-prefix-map="$ROOT"=. -fPIC -pie -O2 -Wall -Wextra -Werror "$ROOT/tests/compat_test.c" -ldl -o "$ROOT/build/compat-test-armhf"

"$ZIG" cc -target arm-linux-gnueabihf.2.28 -mcpu=cortex_a7 -ffile-prefix-map="$ROOT"=. -fPIC -pie -O2 -Wall -Wextra -Werror -I"$ROOT/include" "$ROOT/tests/runtime_test.c" -L"$ENGINE_LIB_DIR" -lflutter_engine -o "$ROOT/build/runtime-test-armhf"
"$ZIG" cc -target arm-linux-musleabihf -static -mcpu=cortex_a7 -ffile-prefix-map="$ROOT"=. -O2 -Wall -Wextra -Werror -I"$ROOT/src" "$ROOT/tests/refresh_policy_test.c" "$ROOT/src/refresh_policy.c" -o "$ROOT/build/refresh-policy-test-armhf"
"$ZIG" cc -target arm-linux-musleabihf -static -mcpu=cortex_a7 -ffile-prefix-map="$ROOT"=. -O2 -Wall -Wextra -Werror -I"$ROOT/src" "$ROOT/tests/power_worker_test.c" "$ROOT/src/power_worker.c" -lpthread -o "$ROOT/build/power-worker-test-armhf"
"$ZIG" cc -target arm-linux-musleabihf -static -mcpu=cortex_a7 -ffile-prefix-map="$ROOT"=. -O2 -Wall -Wextra -Werror -I"$ROOT/include" -I"$ROOT/src" "$ROOT/tests/display_transaction_test.c" "$ROOT/src/refresh_policy.c" -lpthread -o "$ROOT/build/display-transaction-test-armhf"
