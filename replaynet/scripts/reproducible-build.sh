#!/bin/sh
set -e

# Portable SHA-256 (Linux sha256sum, macOS shasum)
sha256_file() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | cut -d' ' -f1
  else
    shasum -a 256 "$1" | cut -d' ' -f1
  fi
}

go build -trimpath -buildvcs=false -o /tmp/replaynet-build1 ./cmd/replaynet
go build -trimpath -buildvcs=false -o /tmp/replaynet-build2 ./cmd/replaynet

HASH1=$(sha256_file /tmp/replaynet-build1)
HASH2=$(sha256_file /tmp/replaynet-build2)

echo "build 1: $HASH1"
echo "build 2: $HASH2"

if [ "$HASH1" = "$HASH2" ]; then
  echo "MATCH: reproducible build confirmed"
else
  echo "MISMATCH: builds are not identical"
  exit 1
fi
