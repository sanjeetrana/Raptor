#!/bin/sh
set -eu

repo_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$repo_dir"

modules=$(GOTOOLCHAIN=go1.27.0 GOPROXY=off go list -m all)
[ "$modules" = "github.com/daniel-oluwadunsin/undolang" ] || {
  printf '%s\n' "dependency proof failed: unexpected module list" >&2
  exit 1
}

printf '%s\n' "$modules"
GOTOOLCHAIN=go1.27.0 GOPROXY=off go test ./...
mkdir -p "$repo_dir/dist"
CGO_ENABLED=0 GOTOOLCHAIN=go1.27.0 GOPROXY=off \
  go build -trimpath -buildvcs=false -o "$repo_dir/dist/undo-deps-proof" ./cmd/undo
printf '%s\n' "offline build: PASS"
