# Testing UndoLang yourself

This is the simple, copy/paste guide for trying the language. It uses temporary
folders, so the examples do not change the UndoLang source checkout.

## What you need

- macOS or Linux with a shell;
- Go 1.27.x if you are building from source;
- no API key, account, database, Node.js, Python, or other package is needed.

On Windows, use the checked-in PowerShell installer to get a binary, then run
the same `undo` commands from PowerShell. The command examples below use a
POSIX shell because it is the shortest copy/paste path.

## 1. Build it

From the repository directory:

```sh
make help
make build
./dist/undo version
```

If `make` is unavailable, the exact direct build is:

```sh
GOTOOLCHAIN=go1.27.0 GOPROXY=off CGO_ENABLED=0 \
  go build -trimpath -buildvcs=false -o undo ./cmd/undo
./undo version
```

## 2. Run the automatic checks

These commands do not edit your application files:

```sh
make test
make vet
make race
make examples
make modules
```

For the complete local release check, run:

```sh
make verify
```

That also checks the empty dependency graph, reproducible build, and release
cross-builds. Longer safety checks are separate:

```sh
make fuzz
make stress
make crash-test
```

For the focused reproducible-build bonus proof (with labeled Build A/Build B
hashes), run:

```sh
make reproducible-build
```

The proof reuses the Go 1.27.0 toolchain installed by `install.sh` when the
system `go` command is older. You can override it explicitly with
`make reproducible-build GO=/path/to/go`.

## 3. Make a tiny language program

Create a temporary application root and a `.undo` program:

```sh
ROOT=$(mktemp -d /tmp/undolang-test.XXXXXX)
mkdir -p "$ROOT/release" "$ROOT/bin" "$ROOT/legacy"
printf '%s\n' 'app version 2' > "$ROOT/release/app-v2"
printf '%s\n' 'app version 1' > "$ROOT/bin/app"
printf '%s\n' '1' > "$ROOT/VERSION"
printf '%s\n' 'old file' > "$ROOT/legacy/old.txt"

cat > "$ROOT/migration.undo" <<'EOF'
transaction "stage" {
  require is_file "release/app-v2"
  mkdir "staging/v2"
  copy "release/app-v2" -> "staging/v2/app"
  assert is_file "staging/v2/app"
}

transaction "activate" {
  require is_file "staging/v2/app"
  copy "staging/v2/app" -> "bin/app" overwrite
  write "VERSION" = "2"
  assert contains "VERSION" "2"
}

transaction "cleanup" {
  require is_dir "legacy"
  delete "legacy"
  assert not_exists "legacy"
}
EOF
```

The file contains three named transactions. `require` checks the starting
state, operations change files, and `assert` checks the result.

## 4. Check and preview the program

`check` reads and validates the whole source. `plan` shows what would happen.
Neither command changes the target root.

```sh
make check FILE="$ROOT/migration.undo" ROOT="$ROOT"
make plan FILE="$ROOT/migration.undo" ROOT="$ROOT"
make plan FILE="$ROOT/migration.undo" ROOT="$ROOT" JSON=1
```

Review the plan before approving a real mutation. JSON output is for scripts or
agents; it is still only a preview.

## 5. Run it and inspect the result

`YES=1` is the explicit approval needed for a noninteractive Make command.

```sh
make run FILE="$ROOT/migration.undo" ROOT="$ROOT" YES=1 JSON=1
cat "$ROOT/VERSION"
cat "$ROOT/bin/app"
test ! -e "$ROOT/legacy"
make history ROOT="$ROOT" JSON=1
```

You should see version `2`, the new application contents, and no `legacy`
directory. A run executes transactions in source order. If a later transaction
fails, earlier committed transactions stay committed and only the current
transaction is rolled back.

To run one named transaction instead, prepare its inputs and select it:

```sh
SELECTED=$(mktemp -d /tmp/undolang-selected.XXXXXX)
mkdir -p "$SELECTED/staging/v2" "$SELECTED/bin"
printf '%s\n' 'app version 2' > "$SELECTED/staging/v2/app"
printf '%s\n' 'app version 1' > "$SELECTED/bin/app"
printf '%s\n' '1' > "$SELECTED/VERSION"
make run FILE="$ROOT/migration.undo" ROOT="$SELECTED" \
  TRANSACTION=activate YES=1 JSON=1
```

The source file is still fully parsed and validated, but only `activate` runs.

## 6. See rollback after a real failed assertion

This test intentionally fails an assertion. The original file should be
restored by the runtime:

```sh
ROLLBACK=$(mktemp -d /tmp/undolang-rollback.XXXXXX)
printf '%s\n' 'original' > "$ROLLBACK/file.txt"
cat > "$ROLLBACK/failure.undo" <<'EOF'
transaction "rollback-demo" {
  write "file.txt" = "changed"
  assert contains "file.txt" "text that is not there"
}
EOF

if make run FILE="$ROLLBACK/failure.undo" ROOT="$ROLLBACK" YES=1; then
  echo "unexpected success" >&2
  exit 1
fi
test "$(cat "$ROLLBACK/file.txt")" = original
echo "rollback restored the original file"
```

The command is expected to return a non-zero status. That is a real failed
postcondition, not a simulated failure.

## 7. Use the agent-facing JSON commands

These commands show the machine-readable workflow:

```sh
make capabilities
make schema
make agent-guide
make check FILE="$ROOT/migration.undo" ROOT="$ROOT" JSON=1
make plan FILE="$ROOT/migration.undo" ROOT="$ROOT" JSON=1
```

An agent should discover capabilities and schema, check the source, inspect the
plan, obtain approval from its controlling human or policy, and only then run:

```sh
make run FILE="$ROOT/migration.undo" ROOT="$ROOT" YES=1 JSON=1
```

`JSON=1` never grants permission by itself. If JSON says recovery is required,
stop new work and run:

```sh
make recover ROOT="$ROOT" YES=1 JSON=1
```

## 8. Try crash recovery

The automated crash test kills real child processes and starts a fresh process
to recover them:

```sh
make crash-test
```

For a narrated five-minute demonstration, follow the real process-kill
runbook in [`docs/DEMO_RUNBOOK.md`](docs/DEMO_RUNBOOK.md). It tells you exactly
when to send `kill -TERM`, how to wait for the durable marker, and how to run a
fresh `recover` process. Do not claim a crash demo succeeded unless the process
was actually killed while the transaction was unresolved.

## Useful command meanings

| Command | Meaning |
|---|---|
| `make check FILE=...` | Parse and validate; makes no target changes. |
| `make plan FILE=...` | Show effects, readiness, and rollback estimate. |
| `make run FILE=... YES=1` | Execute after explicit approval. |
| `make recover ROOT=... YES=1` | Resolve an interrupted transaction from its journal. |
| `make history ROOT=...` | List local transaction audit records. |
| `make inspect TXID=... ROOT=...` | Inspect one validated journal and metadata record. |
| `make capabilities` / `make schema` | Print the stable agent/language contracts as JSON. |

Relative paths in a `.undo` file resolve from `ROOT`, not from the directory
containing the script. The `.undo/` directory under the root is reserved for
runtime state; never delete it to bypass recovery.
