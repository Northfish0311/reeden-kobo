#!/bin/sh
set -eu
APP=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
case "$APP" in /mnt/onboard/.adds/reeden-kobo) :;; *) echo 'Run the installed uninstall.sh on Kobo'; exit 64;; esac
if [ -d "$APP/state/active" ]; then echo 'Exit Reeden first; uninstall did not change anything.'; exit 1; fi
DEST="/mnt/onboard/.adds/reeden-kobo-uninstalled-$(date +%Y%m%d-%H%M%S)-$$"
if [ -e "$DEST" ]; then echo 'Backup destination already exists; uninstall did not change anything.'; exit 1; fi
if ! mv "$APP" "$DEST"; then
    echo 'Could not preserve the app directory; menu entry was kept. Uninstall failed.'
    exit 1
fi
ENTRY=/mnt/onboard/.adds/nm/reeden-kobo
if [ -f "$ENTRY" ]; then
    if cmp -s "$ENTRY" "$DEST/nickelmenu.conf"; then
        if ! rm "$ENTRY"; then
            echo "App and all reading data preserved at: $DEST"
            echo "Could not remove menu entry; remove it manually: $ENTRY"
            exit 1
        fi
    else
        echo 'Menu entry was edited; preserved it. Remove your Reeden entry manually.'
    fi
fi
echo "Uninstalled; preserved whole app and all reading data at: $DEST"
echo 'You may archive this directory on your computer, then delete it yourself.'
