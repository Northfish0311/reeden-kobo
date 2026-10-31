#!/bin/sh
set -eu
APP=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
case "$APP" in /mnt/onboard/.adds/reeden-kobo) :;; *) echo 'Run the installed uninstall.sh on Kobo'; exit 64;; esac
if [ -d "$APP/state/active" ]; then echo 'Exit Reeden first; uninstall did not change anything.'; exit 1; fi
ENTRY=/mnt/onboard/.adds/nm/reeden-kobo
if [ -f "$ENTRY" ]; then
    if cmp -s "$ENTRY" "$APP/nickelmenu.conf"; then rm "$ENTRY"; else echo 'Menu entry was edited; preserved it. Remove your Reeden entry manually.'; fi
fi
DEST="/mnt/onboard/.adds/reeden-kobo-uninstalled-$(date +%Y%m%d-%H%M%S)"
mv "$APP" "$DEST"
echo "Removed launch entry; preserved whole app and all reading data at: $DEST"
echo 'You may archive this directory on your computer, then delete it yourself.'
