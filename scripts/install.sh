#!/bin/sh
# Run only after unpacking in /mnt/onboard/.adds/.reeden-kobo-stage-TIMESTAMP.
set -eu
UPGRADE=0
if [ "${1:-}" = "--upgrade" ]; then UPGRADE=1; shift; fi
SOURCE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
DEST=/mnt/onboard/.adds/reeden-kobo
ENTRY=/mnt/onboard/.adds/nm/reeden-kobo
case "$SOURCE" in /mnt/onboard/.adds/.reeden-kobo-stage-*) :;; *) echo 'Unpack to an .adds/.reeden-kobo-stage-* directory first.'; exit 64;; esac
if [ -e "$DEST" ]; then
    if [ "$UPGRADE" -ne 1 ]; then
        echo 'Existing installation preserved. Exit Reeden and pass --upgrade (or archive/rename it) before installing another build.'
        exit 1
    fi
    if [ -d "$DEST/state/active" ]; then
        echo 'Reeden is currently active. Exit Reeden before upgrading.'
        exit 1
    fi
fi
[ -d /mnt/onboard/.adds/nm ] || { echo 'NickelMenu is required; no system changes were made.'; exit 1; }
if [ -e "$ENTRY" ] && [ "$UPGRADE" -ne 1 ]; then
    echo 'Existing menu file preserved; pass --upgrade or choose a different entry name manually.'
    exit 1
fi
product=$(awk -F, '{print substr($NF,length($NF)-2)}' /mnt/onboard/.kobo/version)
[ "$product" = 393 ] || { echo 'Only Kobo Clara Colour product 393 is supported by this test build.'; exit 1; }
cd "$SOURCE"
sha256sum -c SHA256SUMS > install-verification.log 2>&1 || { echo 'Checksum failed; see install-verification.log'; exit 1; }
chmod 755 ./*.sh ./bin/* ./runtime/* ./checks/*
./bin/fb-guard --inspect || { echo 'Wrong framebuffer/model; installation aborted.'; exit 1; }
for file in ./*.sh ./bin/lipc-get-prop ./bin/lipc-set-prop; do sh -n "$file"; done
BACKUP=""
if [ -e "$DEST" ]; then
    BACKUP="/mnt/onboard/.adds/reeden-kobo-backup-$(date +%Y%m%d-%H%M%S)"
    mv "$DEST" "$BACKUP"
    for keep in userdata storage; do
        if [ -d "$BACKUP/$keep" ]; then
            mkdir -p "$SOURCE/$keep"
            if ! cp -R "$BACKUP/$keep/." "$SOURCE/$keep/"; then
                echo "Upgrade failed while copying $keep; restoring previous installation from $BACKUP." >&2
                mv "$BACKUP" "$DEST"
                exit 1
            fi
        fi
    done
fi
mv "$SOURCE" "$DEST"
if ! cp "$DEST/nickelmenu.conf" "$ENTRY"; then
    mv "$DEST" "$SOURCE"
    if [ -n "$BACKUP" ] && [ -e "$BACKUP" ]; then mv "$BACKUP" "$DEST"; fi
    exit 1
fi
if [ -n "$BACKUP" ]; then
    echo "Upgraded /mnt/onboard/.adds/reeden-kobo (previous build backed up to $BACKUP, userdata and storage preserved); FIRST LAUNCH WAS NOT PERFORMED."
else
    echo 'Installed to /mnt/onboard/.adds/reeden-kobo; FIRST LAUNCH WAS NOT PERFORMED.'
fi
