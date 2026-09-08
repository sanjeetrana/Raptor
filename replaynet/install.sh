#!/usr/bin/env bash
set -e

echo "==> Installing ReplayNet (Zero-Dependency Network Virtualizer)..."

# Ensure Go is available
if ! command -v go >/dev/null 2>&1; then
  echo "Error: Go toolchain is required to build ReplayNet from source."
  echo "Please install Go: https://go.dev/dl/"
  exit 1
fi

TEMP_DIR=$(mktemp -d)
trap 'rm -rf "$TEMP_DIR"' EXIT

cd "$TEMP_DIR"
git clone --depth 1 https://github.com/benjaminnkem/replaynet.git .
make build

INSTALL_DIR="/usr/local/bin"
if [ -w "$INSTALL_DIR" ]; then
  install -m 755 bin/replaynet "$INSTALL_DIR/replaynet"
elif [ -n "$GOPATH" ]; then
  mkdir -p "$GOPATH/bin"
  cp bin/replaynet "$GOPATH/bin/replaynet"
  INSTALL_DIR="$GOPATH/bin"
else
  mkdir -p "$HOME/go/bin"
  cp bin/replaynet "$HOME/go/bin/replaynet"
  INSTALL_DIR="$HOME/go/bin"
fi

echo "✓ ReplayNet successfully installed to $INSTALL_DIR/replaynet"
echo "  Run 'replaynet --help' to get started!"
