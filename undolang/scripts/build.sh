#!/bin/sh
set -eu

repo_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
mkdir -p "$repo_dir/dist"
cd "$repo_dir"
CGO_ENABLED=0 GOTOOLCHAIN=go1.27.0 GOPROXY=off \
  go build -trimpath -buildvcs=false -o "$repo_dir/dist/undo" ./cmd/undo
printf '%s\n' "built $repo_dir/dist/undo"
