# UndoLang Zero-Dependency / STDLIB Plan

This document is a planning precursor to the final hackathon `STDLIB.md`. The implemented repository must replace claims with exact package/file references and honest notes.

## Non-negotiable dependency invariant

- Go 1.27 standard library only.
- `go.mod` has no `require` block.
- No `golang.org/x/...`.
- No vendored third-party source.
- No C library/CGO dependency required by runtime.
- No runtime shell-out to installed tools.
- Static marketing site has no third-party JS/CSS/font runtime requirement.

## Planned stdlib substitutions

At least these are meaningful candidates for final `STDLIB.md`:

| Typical dependency/tool | UndoLang stdlib implementation | Why it is non-trivial |
|---|---|---|
| Cobra / urfave/cli | `flag`, `os.Args`, custom subcommand dispatch and repeatable `flag.Value` | clean multi-command CLI without framework |
| parser generator / participle-style library | handwritten lexer + recursive-descent parser using `bufio`, `unicode/utf8`, `strings` | source positions, escapes, grammar, diagnostics |
| filesystem helper packages | `os`, `io`, `io/fs`, `path/filepath` | copy/move/delete/write implemented directly |
| path sandbox library | `os.OpenRoot`, `os.Root` | traversal-resistant capability roots |
| transaction/rollback library | custom journal + transaction state machine | core product behavior written from primitives |
| WAL/checksum helper | `encoding/binary`, `hash/crc32` | framed append-only crash-detection journal |
| UUID package | Go 1.27 `uuid` | transaction IDs without `google/uuid` |
| JSON library | Go 1.27 `encoding/json/v2` | machine API + journal payload encoding |
| hashing package | `crypto/sha256`, `encoding/hex` | preconditions, content verification, build proof |
| large-file copy library | `io.CopyBuffer`, `io.MultiWriter`, `bufio` | bounded-memory copy and hash |
| regex replace package | custom literal streaming replacement using `bufio`/`bytes` | chunk-boundary-correct bounded memory replace |
| search utility | custom streaming substring scan | large-file `contains` without loading whole file |
| logging framework | `log/slog` or minimal `fmt`/structured result layer | no zap/logrus dependency |
| assertion/test framework | `testing` | no testify |
| temp-file/atomic-write package | `os.CreateTemp`, `File.Sync`, `os.Rename`/`os.Root.Rename` with platform caveats | safe write/replace protocol |
| archive/backup package | direct directory traversal + streaming copy, no archive required | backups stay inspectable and reversible |
| configuration/env package | no config dependency; explicit CLI flags | avoids dotenv/viper entirely |

Final `STDLIB.md` should have at least 10 implemented items with links to source packages/files in repository and one-line rationale each.

## Dependency proof

Create `scripts/deps-proof.sh` that fails if the module graph contains anything other than the main module.

Suggested checks:

```bash
set -eu

go list -m all
COUNT="$(go list -m all | wc -l | tr -d ' ')"
[ "$COUNT" = "1" ] || {
  echo "third-party module detected"
  exit 1
}

GOPROXY=off go test ./...
GOPROXY=off go build -trimpath -buildvcs=false -o /tmp/undo-deps-proof ./cmd/undo
```

If avoiding `wc` for purity/Windows portability matters, write a tiny Go stdlib proof helper under `scripts/` or use a Go test to inspect `go list -m all` output. Build scripts are not runtime, but judge clarity matters.

## CGO

Target `CGO_ENABLED=0` for canonical release/reproducible builds unless a concrete standard-library feature requires CGO. This avoids hidden native runtime requirements.

## Network-disabled verification

`GOPROXY=off` must be used in final test/build proof. With no third-party modules, the project should build entirely from the installed Go toolchain and repository source.

## Package Killer

Do not claim this bonus by saying “we replace shell scripting” or “we replace a transaction package” unless the implementation is intentionally API/behavior compatible with a specific named package people install.

The core project already has a stronger +8 strategy:

- Reproducible Build +5
- STDLIB Log +3

Package Killer is optional and must not distort product architecture.
