#!/bin/sh
# Loader queries and isolated synthetic tests. Never enters the Reeden host main().
set -eu
APP=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$APP"
sha256sum -c SHA256SUMS > /dev/null
echo 'PASS: all shipped file hashes'
"$APP/bin/fb-guard" --inspect
echo 'PASS: framebuffer query only; no pixels written'
LOADER="$APP/runtime/reeden-kindle"
LIBS="$APP/runtime:$APP/lib:$APP/core/lib"
"$LOADER" --verify "$APP/bin/reeden-kindle"
for file in bin/reeden-kindle lib/libgio-2.0.so core/lib/libsqlcipher.so.0 core/lib/libpdfium.so core/lib/libflutter_7zip.so core/lib/libunrar.so; do
    echo "LOADER_LIST_ONLY: $file"
    "$LOADER" --library-path "$LIBS" --preload "$APP/lib/libreeden_kobo_compat.so" --list "$APP/$file"
done
echo 'PASS: target loader dependency/version checks; Reeden entry point was not executed'
"$LOADER" --library-path "$LIBS" "$APP/checks/codec-test-armhf"
"$LOADER" --library-path "$LIBS" "$APP/checks/input-test-armhf"
REEDEN_KOBO_DIR="$APP" "$LOADER" --library-path "$LIBS" --preload "$APP/lib/libreeden_kobo_compat.so" "$APP/checks/compat-test-armhf"
REEDEN_KOBO_DIR="$APP" "$LOADER" --library-path "$LIBS" --preload "$APP/lib/libreeden_kobo_compat.so" "$APP/checks/runtime-test-armhf"
echo 'PASS: private libc synthetic tests; no framebuffer writes or input device opens'
"$APP/checks/refresh-policy-test-armhf"
"$APP/checks/power-worker-test-armhf"
"$APP/checks/display-transaction-test-armhf"
test ! -d "$APP/state/active"
echo 'REEDEN_NOT_LAUNCHED_BY_VERIFY'
