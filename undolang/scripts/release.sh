#!/bin/sh
set -eu

repo_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
dist_dir="$repo_dir/dist"
mkdir -p "$dist_dir"
cd "$repo_dir"

build_target() {
  target_os=$1
  target_arch=$2
  suffix=$3
  output="$dist_dir/undo_0.1.0_${target_os}_${target_arch}${suffix}"
  CGO_ENABLED=0 GOOS=$target_os GOARCH=$target_arch GOTOOLCHAIN=go1.27.0 GOPROXY=off \
    go build -trimpath -buildvcs=false -o "$output" ./cmd/undo
}

build_target linux amd64 ""
build_target linux arm64 ""
build_target darwin amd64 ""
build_target darwin arm64 ""
build_target windows amd64 ".exe"

cd "$dist_dir"
go run "$repo_dir/tools/buildproof" -output SHA256SUMS undo_0.1.0_*
