# MiniKV

*A tiny storage engine built from the ground up.*

MiniKV is a lightweight, embedded key-value storage engine implemented
entirely with the Go standard library — no SQLite, no third-party
database, no external packages of any kind. It was built for
**Zero Dependency | 72-Hour Hackathon 2026** (Track D — Data & Storage).

## Problem

Almost every "storage engine" project reaches for something that already
does the hard part: SQLite, BoltDB, Badger, Redis. That's the right call
in production — but it also means the actual mechanics of durable storage
(append-only logs, checksums, crash recovery, indexing) stay hidden
behind a driver. This project builds those mechanics explicitly, using
nothing but `os`, `encoding/binary`, `hash/crc32`, and `sync`.

## Why Zero Dependency?

Building the engine ourselves — rather than wrapping an existing one — is
the entire point of Track D. It forces real engineering decisions about
binary formats, fsync semantics, and lock granularity that a database
driver would otherwise make invisible.

## Features

- Persistent, append-only storage engine (no SQLite, no external DB)
- In-memory index for O(1) key lookup — `Get` never scans the log
- Crash recovery: detects and safely discards torn writes and corrupted
  records on startup
- Two durability modes: buffered (fast) and `--sync` (fsync per write)
- Thread-safe concurrent access (`go test -race` clean)
- Per-key CRC-32 checksums on every record
- TTL / key expiration, persisted across restarts
- Backup (`minikv backup`) and restore (`minikv restore`)
- Compaction (`minikv compact`) to reclaim space from dead records
- Professional CLI with clean exit codes, plus an interactive shell
- Comprehensive standard-library-only test suite, including recovery,
  concurrency, TTL, backup/restore, and compaction tests

## Quick Start

```bash
go build -o minikv ./cmd/minikv
./minikv set name Shraddha
./minikv get name
./minikv list
./minikv stats
```

## Installation

Requires Go (developed against Go 1.22 in the build/test environment
used for this submission; `go.mod` targets `go 1.22` and the code uses no
syntax or stdlib API newer than that, so it builds unchanged on Go 1.27).

```bash
git clone <this repository>
cd ZeroDependency-MiniKV
go build -o minikv ./cmd/minikv
```

## Commands

```
minikv [--db PATH] [--sync] <command> [args]

set <key> <value> [--ttl SECONDS]   Store a value, optionally with expiry
get <key>                           Retrieve a value
delete <key>                        Remove a key
exists <key>                        Check whether a key is present
list                                List all live keys
stats                               Show database statistics
backup <destination>                Copy the database log to a new file
restore <backup>                    Restore the database from a backup
compact                             Rewrite the log, dropping dead data
shell                               Start an interactive MiniKV shell
help                                Show this help text
version                             Show the MiniKV version
```

Global flags: `--db PATH` (default `minikv.db`), `--sync` (fsync every
write).

### Exit codes

| Code | Meaning                                  |
|------|-------------------------------------------|
| 0    | Success                                    |
| 1    | Runtime error (I/O failure, etc.)          |
| 2    | Usage error (bad arguments)                |
| 3    | Key not found / does not exist             |

### Interactive shell

```
$ ./minikv shell
MiniKV shell — type 'help' for commands, 'exit' to quit.
> set name Shraddha
OK
> get name
Shraddha
> list
name
> exit
```

## Architecture

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the full
layer-by-layer breakdown (CLI → command layer → engine → index → log →
disk) with startup and write-path diagrams.

## Storage Format

Each record: a 22-byte header (magic, version, operation, key length,
value length, expiration), the key, the value, and a trailing 4-byte
CRC-32 checksum. Full field layout is documented at the top of
`internal/engine/record.go`.

## In-Memory Index

A plain `map[string]indexEntry` recording, per live key, the byte offset
and length of its current record. Rebuilt from scratch by replaying the
log on every `Open`. `Get` uses it to perform a single `ReadAt` instead of
scanning the file.

## WAL (Append-Only Log)

Every `Set` and `Delete` is represented as an appended record — updates
and deletes never rewrite existing bytes. This is what makes crash
recovery tractable: everything before the last complete, checksummed
record is guaranteed intact.

## Crash Recovery

On `Open`, MiniKV scans the log from the start and replays every valid
record. It stops at the **first** record that is either incomplete (fewer
bytes remain than the header claims — a torn write) or fails checksum
validation (corruption), and discards everything from that point forward
by truncating the file. It does not attempt to skip a bad record and keep
scanning, because once one record's length fields are wrong, there is no
reliable way to know where the next record begins. See
`internal/engine/recovery.go` for the implementation and
`docs/ARCHITECTURE.md` for the reasoning.

## Durability

- **Default mode**: writes go through `WriteAt`, reaching the OS page
  cache. Survives process crashes; does **not** guarantee survival of a
  power loss or kernel panic before the OS flushes dirty pages.
- **`--sync` mode**: every write is followed by `File.Sync()` (fsync),
  which blocks until the write is durable on the storage medium. Survives
  power loss, at the cost of one fsync per write (no batching / group
  commit is implemented).

## Concurrency

A single `sync.RWMutex` serializes writers against each other and against
readers, while allowing multiple concurrent readers. `Get`/`Exists`/`List`
take the read lock; `Set`/`Delete`/`Compact` take the write lock. Verified
with `go test -race ./...`.

## TTL

`minikv set session abc --ttl 60` expires the key 60 seconds after it's
set. Expiration is stored as an absolute unix-second timestamp inside the
record itself, so it survives restarts. **Granularity is one second** —
sub-second TTLs are not meaningfully supported, since the on-disk format
stores whole seconds.

## Backup & Restore

`minikv backup <dest>` takes a consistent point-in-time copy of the log
under a read lock; it refuses to overwrite an existing file at the
destination. `minikv restore <backup>` validates the backup (it must
replay as a well-formed MiniKV log with at least one valid record) before
restoring, and if a database already exists at the target path, it is
preserved as `<path>.preRestore.<timestamp>` rather than being silently
discarded.

## Compaction

`minikv compact` rewrites the log to contain exactly one record per live,
non-expired key, dropping tombstones and superseded old versions. The
rewrite happens in a temp file that is fsynced and atomically renamed
over the original, so a crash mid-compaction leaves the original log
untouched.

## Testing

```bash
gofmt -w .
go vet ./...
go test ./...
go test -race ./...
```

The suite (`internal/engine/engine_test.go`, `tests/integration_test.go`)
covers core CRUD, persistence across reopen, repeated updates, edge cases
(empty key, long key, large value, Unicode, special characters), crash
recovery (truncated and corrupted records), concurrent access, TTL
(including restart survival), backup/restore (including invalid-backup
rejection and overwrite protection), and compaction (including restart
after compaction).

## Dependency Proof

```bash
$ go list -m all
minikv

$ go mod graph
minikv go@1.22
go@1.22 toolchain@go1.22
```

Both commands show only the `minikv` module itself and the Go toolchain
directive — no third-party modules appear anywhere in the graph.

**Third-party runtime dependencies: 0.**

## Standard Library Decisions

See [`STDLIB.md`](STDLIB.md) for a package-by-package breakdown of every
place a third-party library would normally be used, and what standard
library functionality replaced it.

## Performance Notes

`Get` is O(1) in the number of keys (a map lookup plus one `ReadAt`).
`Set`/`Delete` are O(1) amortized (an append). No benchmarking was
performed for this submission beyond confirming the above complexity
characteristics hold in the test suite; no throughput numbers are
claimed.

## Limitations

- Single-process only: MiniKV is an embedded engine, not a server. There
  is no network protocol and no multi-process coordination — concurrent
  access from two separate OS processes to the same file is not
  supported and will corrupt the index (though the on-disk log itself,
  being append-only, would likely still be recoverable).
- TTL granularity is one second (see above).
- No group-commit/batched fsync — `--sync` mode pays a full fsync per
  write.
- No range scans or secondary indexes; the only lookup is by exact key.
- The log is a single file with no sharding; very large datasets will
  produce a very large single file until compacted.

## Design Trade-offs

- **Stop-at-first-error recovery** instead of skip-and-resume: simpler
  and strictly safer, at the cost of discarding everything after a single
  corrupted record rather than trying to salvage later, still-intact
  records.
- **Hold the read lock for the duration of `Get`** (including the disk
  read) instead of a more fine-grained scheme: fewer moving parts, easier
  to verify race-free, at some cost to read parallelism under heavy
  concurrent write load.
- **No compiler-generated parser**: the CLI's argument handling is a
  ~40-line hand-written scanner rather than the standard `flag` package
  bent into a subcommand shape, because it was more readable for this
  project's small, fixed set of commands.

## Demo

See [`DEMO_SCRIPT.md`](DEMO_SCRIPT.md) for the 5-minute demo video plan.

## Team

1. [Member 1]
2. [Member 2]
3. [Member 3]

*(placeholders — to be filled in with actual team details)*

## License

See [`LICENSE`](LICENSE).
