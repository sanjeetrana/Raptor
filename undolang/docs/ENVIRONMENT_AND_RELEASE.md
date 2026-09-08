# UndoLang Environment, Build, Installation, and Release Specification

## 1. Required development environment

Required:

- Go **1.27.x**
- Git for source control is allowed as development tooling, but UndoLang runtime must never require or invoke Git.
- A shell/PowerShell is convenient for scripts but not required by the runtime binary.

No database, Node.js, Python, Docker, Redis, package manager, API key, cloud account, or external service is required to build or run UndoLang.

## 2. Runtime environment variables

**Required runtime environment variables: none.**

Optional conventions:

- `NO_COLOR`: disable ANSI decoration if implemented.

Do not introduce `.env` files or secret configuration requirements.

## 3. Build environment variables

Canonical build:

```bash
CGO_ENABLED=0 go build -trimpath -buildvcs=false -o dist/undo ./cmd/undo
```

Useful release variables provided by Go toolchain:

- `GOOS`
- `GOARCH`
- `CGO_ENABLED=0`

Do not require `SOURCE_DATE_EPOCH` unless the final implementation genuinely needs it. Prefer a build that is deterministic without time injection.

## 4. Canonical one-command judge build

The README should present the simplest direct command prominently:

```bash
go build -trimpath -buildvcs=false -o undo ./cmd/undo
```

This satisfies the one-command-build expectation and makes the dependency model obvious.

`Makefile`/scripts may be provided as convenience but must not hide the actual build.

## 5. Reproducible build

Target bonus: +5.

Use pinned Go 1.27 toolchain and the same exact command for two builds on the same machine.

Recommended script behavior:

```text
1. clean/create temp output directory
2. CGO_ENABLED=0 go build -trimpath -buildvcs=false -o build-a/undo ./cmd/undo
3. CGO_ENABLED=0 go build -trimpath -buildvcs=false -o build-b/undo ./cmd/undo
4. compute SHA-256 of each with a Go stdlib helper/test
5. assert hashes equal
6. write reproducible-build.txt with go version, GOOS/GOARCH, command, both hashes
```

Do not embed:

- current build timestamp;
- random build ID chosen by our own code;
- absolute repository path;
- volatile VCS dirty information;
- host name/user name.

If Go linker metadata still creates differences, diagnose with official Go tooling and only then adjust linker flags. Do not cargo-cult `-buildid=` without testing.

## 6. Dependency proof

Evidence should include:

```bash
go list -m all
GOPROXY=off go test ./...
GOPROXY=off go build -trimpath -buildvcs=false -o undo ./cmd/undo
```

Expected module list: one line, the main module.

Write actual output to `deps-proof.txt` close to submission.

## 7. Release targets

Build artifacts:

```text
undo_<version>_linux_amd64
undo_<version>_linux_arm64
undo_<version>_darwin_amd64
undo_<version>_darwin_arm64
undo_<version>_windows_amd64.exe
```

Cross-compilation command shape:

```bash
CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -trimpath -buildvcs=false -o dist/undo_linux_amd64 ./cmd/undo
```

Cross-compilation proves buildability, not behavioral support. README support matrix must distinguish:

- tested on real OS;
- cross-built only;
- unsupported/unverified.

## 8. End-user installation model

UndoLang is fundamentally portable/no-install:

```bash
./undo version
```

A prebuilt native binary does not require Go installed.

### macOS/Linux convenience

Ship `install.sh` that operates on a local binary/source tree and copies the binary to a user path such as:

```text
~/.local/bin/undo
```

It should:

- not require a package manager;
- not install dependencies for the runtime;
- not start a daemon;
- verify any optional compiler archive before extraction;
- clearly print if `~/.local/bin` is not in PATH.

When a source build is requested and no Go 1.27.x is available, the installer
may download the pinned official Go 1.27.0 archive from `go.dev`, verify its
SHA-256 checksum, and place it under the user's UndoLang toolchain directory.
This is an opt-out convenience for source builds, not a runtime dependency;
`--no-install-go` keeps the path entirely offline. Avoid making `curl | sh` the
canonical hackathon instruction.

### Windows convenience

`install.ps1` may copy `undo.exe` to a user directory such as:

```text
%LOCALAPPDATA%\UndoLang\bin\undo.exe
```

It may print PATH instructions. Do not require administrative installation for basic use.
For source builds it follows the same policy as `install.sh`; use
`-NoInstallGo` to disable the verified user-local Go bootstrap.

## 9. Optional self-install command

Only implement `undo install` if core correctness is complete and the behavior is simple/portable. It can use `os.Executable`, `os.UserHomeDir`, and normal file-copy primitives.

It is not required for hackathon success.

## 10. State location

Default transaction state:

```text
<transaction-root>/.undo/
```

This keeps recovery data near the root it protects and avoids a runtime database/config dependency.

The state path is reserved from DSL mutations.

## 11. Release checksums

Generate a `SHA256SUMS` equivalent with a tiny Go stdlib release helper if desired, or publish hashes from the release script. Do not make user verification require a third-party package.

## 12. Versioning

Binary semantic version may begin at `0.1.0`.

DSL schema version remains explicit (`undo-dsl/1`). CLI JSON API remains explicit (`undo-cli/1`).

Do not inject build date into version output if chasing reproducible builds.

Example:

```text
UndoLang 0.1.0
dsl undo-dsl/1
api undo-cli/1
go go1.27.x
```

Go toolchain version can be discovered from build info/runtime where deterministic.

## 13. Required final environment explanation to user

Codex must explicitly state at handoff:

- required Go version for source build;
- no runtime env vars/API keys;
- optional `NO_COLOR`;
- build/release variables (`GOOS`, `GOARCH`, `CGO_ENABLED`);
- exact build command;
- exact test command;
- exact dependency proof;
- exact install/run path;
- state directory behavior;
- platform caveats.
