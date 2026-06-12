#!/bin/sh
# Encrypted, restore-testable backup of MediaHub's irreplaceable data.
# docs/security/DATA_PROTECTION.md explains what's included and why.
#
#   Create:  MEDIAHUB_BACKUP_PASSPHRASE=... scripts/backup_mediahub.sh [outdir]
#   Verify:  MEDIAHUB_BACKUP_PASSPHRASE=... scripts/backup_mediahub.sh --verify <archive>
#
# Encryption: age (if installed) else OpenSSL AES-256-CBC + PBKDF2.
# Free tooling only. Passphrase comes from the environment, never argv.
set -eu

: "${DATA_DIR:?set DATA_DIR to the data directory to back up}"
: "${MEDIAHUB_BACKUP_PASSPHRASE:?set MEDIAHUB_BACKUP_PASSPHRASE (not on the command line)}"
RUNS_DIR="${RUNS_DIR:-$DATA_DIR/runs_v4}"
UPLOADS_DIR="${UPLOADS_DIR:-$DATA_DIR/uploads_v4}"

# OpenSSL only: age's passphrase mode is interactive (needs a TTY), which a
# cron/scheduled backup doesn't have. AES-256-CBC with PBKDF2 from openssl
# works headless everywhere and stays free.
encrypt() {  # stdin -> $1
  openssl enc -aes-256-cbc -pbkdf2 -salt -pass env:MEDIAHUB_BACKUP_PASSPHRASE -out "$1"
}

decrypt() {  # $1 -> stdout
  openssl enc -d -aes-256-cbc -pbkdf2 -pass env:MEDIAHUB_BACKUP_PASSPHRASE -in "$1"
}

if [ "${1:-}" = "--verify" ]; then
  archive="${2:?usage: backup_mediahub.sh --verify <archive>}"
  workdir="$(mktemp -d)"
  trap 'rm -rf "$workdir"' EXIT
  echo "verify: decrypting $archive"
  decrypt "$archive" > "$workdir/backup.tar.gz"
  echo "verify: checking tar integrity"
  tar -tzf "$workdir/backup.tar.gz" > "$workdir/listing.txt"
  for needle in "data.db" "club_profiles" "compliance"; do
    if grep -q "$needle" "$workdir/listing.txt"; then
      echo "verify: found $needle"
    else
      echo "verify: WARNING — '$needle' not present in archive (empty deployment?)"
    fi
  done
  echo "verify: OK ($(wc -l < "$workdir/listing.txt") entries)"
  exit 0
fi

outdir="${1:-.}"
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
out="$outdir/mediahub-backup-$stamp.tar.gz.enc"

# Rebuildable caches are excluded — they regenerate and bloat the archive.
tar -czf - \
  --exclude='.cache' \
  --exclude='data/discovered' \
  --exclude='discovered' \
  --exclude='motion_cache' \
  -C "$(dirname "$DATA_DIR")" "$(basename "$DATA_DIR")" \
  $( [ -d "$RUNS_DIR" ] && [ "${RUNS_DIR#"$DATA_DIR"}" = "$RUNS_DIR" ] && printf ' -C %s %s' "$(dirname "$RUNS_DIR")" "$(basename "$RUNS_DIR")" ) \
  $( [ -d "$UPLOADS_DIR" ] && [ "${UPLOADS_DIR#"$DATA_DIR"}" = "$UPLOADS_DIR" ] && printf ' -C %s %s' "$(dirname "$UPLOADS_DIR")" "$(basename "$UPLOADS_DIR")" ) \
  | encrypt "$out"

chmod 600 "$out"
echo "backup written: $out"
echo "REMINDER: run '$0 --verify $out' — an unverified backup is a hope, not a backup."
