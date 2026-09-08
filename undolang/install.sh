#!/bin/sh
set -eu

# This installer can copy a prebuilt binary without a compiler. When it has to
# build the checkout, it bootstraps the exact Go release required by go.mod in
# a per-user directory. The bootstrap is verified before extraction and never
# writes to a system Go installation.
go_version=1.27.0
allow_go_bootstrap=1
source_binary=
install_dir=

usage() {
  cat <<'EOF'
Usage: ./install.sh [OPTIONS] [SOURCE_BINARY] [INSTALL_DIR]

Install a local UndoLang binary, or build ./cmd/undo from this checkout.

When a source build needs Go, the official Go 1.27.0 archive is downloaded,
SHA-256 verified, and installed under ~/.local/share/undolang/toolchains.
Use --no-install-go for an entirely offline/local-only install.

Options:
  --install-go       Explicitly allow the pinned Go bootstrap (the default).
  --no-install-go    Never download Go; fail if a compatible Go is unavailable.
  -h, --help         Show this help.

Positional arguments retain the original interface:
  SOURCE_BINARY      Existing binary (default: ./undo; source-build when absent).
  INSTALL_DIR        User install directory (default: ~/.local/bin).
EOF
}

die() {
  echo "UndoLang installer: $*" >&2
  exit 1
}

assign_positional() {
  if [ -z "$source_binary" ]; then
    source_binary=$1
  elif [ -z "$install_dir" ]; then
    install_dir=$1
  else
    die "too many positional arguments (try --help)"
  fi
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --install-go)
      allow_go_bootstrap=1
      ;;
    --no-install-go)
      allow_go_bootstrap=0
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    --)
      shift
      while [ "$#" -gt 0 ]; do
        assign_positional "$1"
        shift
      done
      break
      ;;
    -* )
      die "unknown option: $1 (try --help)"
      ;;
    *)
      assign_positional "$1"
      ;;
  esac
  shift
done

source_binary=${source_binary:-./undo}
install_dir=${install_dir:-"${HOME}/.local/bin"}
temporary_binary=
bootstrap_tmp=

cleanup() {
  if [ -n "$temporary_binary" ] && [ -f "$temporary_binary" ]; then
    rm -f "$temporary_binary"
  fi
  if [ -n "$bootstrap_tmp" ] && [ -d "$bootstrap_tmp" ]; then
    rm -rf "$bootstrap_tmp"
  fi
}
trap cleanup EXIT HUP INT TERM

go_is_compatible() {
  candidate=$1
  # Do not let an older local Go silently download a toolchain while probing.
  version=$(GOTOOLCHAIN=local "$candidate" version 2>/dev/null || true)
  case "$version" in
    *"go1.27"|*"go1.27 "*|*"go1.27."*) return 0 ;;
    *) return 1 ;;
  esac
}

sha256_file() {
  file=$1
  if command -v shasum >/dev/null 2>&1; then
    output=$(shasum -a 256 "$file")
    set -- $output
    printf '%s\n' "$1"
    return
  fi
  if command -v sha256sum >/dev/null 2>&1; then
    output=$(sha256sum "$file")
    set -- $output
    printf '%s\n' "$1"
    return
  fi
  if command -v openssl >/dev/null 2>&1; then
    output=$(openssl dgst -sha256 -r "$file")
    set -- $output
    printf '%s\n' "$1"
    return
  fi
  die "cannot verify Go archive: shasum, sha256sum, or openssl is required"
}

download_file() {
  url=$1
  destination=$2
  if command -v curl >/dev/null 2>&1; then
    curl --fail --location --silent --show-error --output "$destination" "$url"
    return
  fi
  if command -v wget >/dev/null 2>&1; then
    wget --quiet --output-document="$destination" "$url"
    return
  fi
  die "cannot download Go archive: curl or wget is required"
}

install_pinned_go() {
  os_name=$(uname -s 2>/dev/null || true)
  case "$os_name" in
    Darwin) platform=darwin ;;
    Linux) platform=linux ;;
    *) die "automatic Go bootstrap supports macOS and Linux; install Go 1.27.x manually on $os_name" ;;
  esac

  machine=$(uname -m 2>/dev/null || true)
  case "$machine" in
    arm64|aarch64) arch=arm64 ;;
    amd64|x86_64) arch=amd64 ;;
    *) die "automatic Go bootstrap does not support architecture $machine" ;;
  esac

  archive="go${go_version}.${platform}-${arch}.tar.gz"
  case "$archive" in
    go1.27.0.darwin-amd64.tar.gz) expected_sha256=d3314e25496e4381d71a5c51d2907e7af655d199f6780b549f015bd85fef4986 ;;
    go1.27.0.darwin-arm64.tar.gz) expected_sha256=90493b3bbd5e10f91d12153198bf1994fd756399b4fec93b49b0c6e2acdeeb3e ;;
    go1.27.0.linux-amd64.tar.gz) expected_sha256=675c26c449cbb18fc24b74650de1eabbae6e16f64326fd85a283fb3b58280685 ;;
    go1.27.0.linux-arm64.tar.gz) expected_sha256=51798d2c42d0e1c6ed7fd9f48728b4193abac9e8aad6dbac2fe96a81f5909bda ;;
    *) die "no pinned Go checksum for $archive" ;;
  esac

  toolchain_dir="${HOME}/.local/share/undolang/toolchains/go${go_version}"
  go_command="$toolchain_dir/bin/go"
  if [ -x "$go_command" ]; then
    go_is_compatible "$go_command" || die "existing toolchain is not a compatible Go ${go_version}: $toolchain_dir"
    return
  fi
  if [ -e "$toolchain_dir" ] || [ -L "$toolchain_dir" ]; then
    die "toolchain directory exists but is incomplete: $toolchain_dir (remove it manually and retry)"
  fi

  bootstrap_tmp=$(mktemp -d "${TMPDIR:-/tmp}/undolang-go.XXXXXX")
  archive_path="$bootstrap_tmp/$archive"
  echo "Downloading Go ${go_version} for ${platform}/${arch} from go.dev..." >&2
  download_file "https://go.dev/dl/$archive" "$archive_path"
  actual_sha256=$(sha256_file "$archive_path")
  [ "$actual_sha256" = "$expected_sha256" ] || die "Go archive checksum mismatch for $archive"
  tar -xzf "$archive_path" -C "$bootstrap_tmp"
  [ -x "$bootstrap_tmp/go/bin/go" ] || die "Go archive did not contain the expected toolchain"

  toolchain_parent=$(dirname "$toolchain_dir")
  mkdir -p "$toolchain_parent"
  if [ -e "$toolchain_dir" ] || [ -L "$toolchain_dir" ]; then
    die "toolchain directory appeared during installation: $toolchain_dir"
  fi
  mv "$bootstrap_tmp/go" "$toolchain_dir"
  echo "Installed Go ${go_version} at $toolchain_dir (user-local)." >&2
}

if [ ! -f "$source_binary" ]; then
  if [ "$source_binary" != "./undo" ] || [ ! -f ./go.mod ]; then
    die "UndoLang binary not found: $source_binary"
  fi

  go_command=$(command -v go 2>/dev/null || true)
  if [ -z "$go_command" ] || ! go_is_compatible "$go_command"; then
    if [ "$allow_go_bootstrap" -eq 0 ]; then
      die "Go 1.27.x is required to build the source tree; rerun without --no-install-go to install Go ${go_version} locally"
    fi
    install_pinned_go
  fi

  temporary_binary=$(mktemp "${TMPDIR:-/tmp}/undolang-install.XXXXXX")
  echo "Building UndoLang from the local source tree with $go_command..."
  GOPROXY=off GOTOOLCHAIN=local CGO_ENABLED=0 "$go_command" build -trimpath -buildvcs=false -o "$temporary_binary" ./cmd/undo
  source_binary=$temporary_binary
fi

mkdir -p "$install_dir"
cp "$source_binary" "$install_dir/undo"
chmod 0755 "$install_dir/undo"
echo "Installed UndoLang at $install_dir/undo"

case ":${PATH}:" in
  *":${install_dir}:"*) ;;
  *) echo "Add $install_dir to PATH to invoke 'undo' directly." ;;
esac
