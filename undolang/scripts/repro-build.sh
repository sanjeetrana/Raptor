#!/bin/sh
set -eu

repo_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
build_dir=$(mktemp -d "${TMPDIR:-/tmp}/undolang-repro.XXXXXX")
trap 'rm -rf "$build_dir"' EXIT HUP INT TERM
cd "$repo_dir"
go_command=${GO:-go}

go_is_compatible() {
  version=$(GOTOOLCHAIN=local "$1" version 2>/dev/null || true)
  case "$version" in
    *"go1.27"|*"go1.27 "*|*"go1.27."*) return 0 ;;
    *) return 1 ;;
  esac
}

# install.sh keeps a verified compiler in this user-local location. Reuse it
# when the system `go` is an older release (for example Go 1.26 with
# GOTOOLCHAIN=local), so the proof remains a single command after installation.
if ! go_is_compatible "$go_command" && { [ -z "${GO+x}" ] || [ "$go_command" = "go" ]; }; then
  local_go="${HOME:-}/.local/share/undolang/toolchains/go1.27.0/bin/go"
  if [ -x "$local_go" ] && go_is_compatible "$local_go"; then
    go_command=$local_go
  fi
fi
if ! go_is_compatible "$go_command"; then
  printf '%s\n' "Go 1.27.0 is required for reproducible-build; install it with ./install.sh or pass GO=/path/to/go" >&2
  exit 1
fi

printf '%s\n' "Reproducible build proof (Go 1.27.0, CGO_ENABLED=0)"
printf '%s\n' "Build A: $build_dir/undo-a"
CGO_ENABLED=0 GOTOOLCHAIN=go1.27.0 GOPROXY=off \
  "$go_command" build -trimpath -buildvcs=false -o "$build_dir/undo-a" ./cmd/undo
printf '%s\n' "Build B: $build_dir/undo-b"
CGO_ENABLED=0 GOTOOLCHAIN=go1.27.0 GOPROXY=off \
  "$go_command" build -trimpath -buildvcs=false -o "$build_dir/undo-b" ./cmd/undo

hashes=$(GOTOOLCHAIN=go1.27.0 GOPROXY=off \
  "$go_command" run ./tools/buildproof -hash-only "$build_dir/undo-a" "$build_dir/undo-b")
build_a_hash=$(printf '%s\n' "$hashes" | sed -n '1p')
build_b_hash=$(printf '%s\n' "$hashes" | sed -n '2p')
[ -n "$build_a_hash" ] && [ -n "$build_b_hash" ] || {
  printf '%s\n' "reproducible build: missing hash output" >&2
  exit 1
}
printf '%s\n' "Build A SHA-256: $build_a_hash"
printf '%s\n' "Build B SHA-256: $build_b_hash"
printf '%s\n' "Result: PASS — outputs are byte-identical"
