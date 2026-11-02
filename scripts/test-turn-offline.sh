#!/bin/sh
# Native mocked tests only. Does not use SSH, FBInk or a real framebuffer.
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"
OUT="$ROOT/build/turn-offline"
mkdir -p "$OUT"
CC=${CC:-clang}
TEST_FB=
if [ "$(uname -s)" = Darwin ]; then TEST_FB=-Itests/native_include; fi
for name in refresh_policy turn_timing display_transaction; do
    extra=
    case "$name" in turn_timing|display_transaction) extra=src/turn_timing.c;; esac
    "$CC" -std=gnu11 -O1 -g -Wall -Wextra -Werror -Wno-unused-parameter \
        -fsanitize=address,undefined -fno-omit-frame-pointer \
        $TEST_FB -Iinclude -Isrc "tests/${name}_test.c" src/refresh_policy.c $extra \
        -lpthread -o "$OUT/$name"
    "$OUT/$name" > "$OUT/$name.log" 2>&1
    printf 'PASS: %s (native ASan/UBSan; mocked hardware)\n' "$name"
done
python3 tests/turn_trace_test.py
