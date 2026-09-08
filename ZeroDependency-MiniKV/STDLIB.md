# Standard Library Decisions

Zero-Dependency Craft is worth a significant share of the score for this
track, so this document is explicit about every point where a real-world
Go project would normally reach for a third-party package, and exactly
what MiniKV uses instead.

> **Go's standard library has no SQLite driver and no embedded database
> package**, so MiniKV implements its own append-only storage engine and
> in-memory index from scratch rather than wrapping SQLite, BoltDB, or
> any other existing engine. This is the central substitution the whole
> project is built around; everything below is in service of it.

---

### 1. Storage engine

| | |
|---|---|
| Normally | `badger`, `bbolt` (`boltdb`), a SQLite driver, or Redis |
| Why tempting | Battle-tested, handles B-trees/LSM-trees, transactions, and recovery for you |
| Replaced with | A hand-written append-only log (`internal/engine/storage.go`, `record.go`) plus a `map[string]indexEntry` index rebuilt on startup |
| Limitations | No B-tree/LSM structure, so range scans are not supported — only exact-key lookup. No MVCC/transactions across multiple keys. |
| Why appropriate | This *is* the assignment: demonstrate the mechanics a database driver normally hides. |

### 2. CLI framework

| | |
|---|---|
| Normally | `spf13/cobra` + `spf13/pflag` |
| Why tempting | Automatic subcommand routing, flag parsing, help text generation |
| Replaced with | `internal/cli/parser.go` (a small hand-written scanner for `--db`/`--sync`/`--ttl`) plus a plain `switch` in `commands.go` |
| Limitations | No auto-generated shell completion, no nested subcommands, no automatic `--help` per-subcommand (help is one static block) |
| Why appropriate | MiniKV has ~10 flat commands and two global flags — a full CLI framework would add far more machinery than the surface area justifies |

### 3. Testing framework

| | |
|---|---|
| Normally | `stretchr/testify` (`assert`/`require`) |
| Why tempting | Fluent assertions, less boilerplate per check |
| Replaced with | Go's built-in `testing` package, plain `if ... { t.Fatalf(...) }` checks |
| Limitations | More verbose per-assertion; no built-in mocking or fixture helpers |
| Why appropriate | `testing` is fully sufficient for this project's needs, and keeping it stdlib-only removes any ambiguity about the "zero dependency" claim in the test code itself |

### 4. Structured logging

| | |
|---|---|
| Normally | `uber-go/zap`, `sirupsen/logrus` |
| Why tempting | Structured fields, log levels, fast formatting |
| Replaced with | `log/slog` (stdlib as of Go 1.21), used for recovery/compaction diagnostics (`Options.Logger` in `database.go`) |
| Limitations | Fewer output formatters/sinks out of the box than the third-party options |
| Why appropriate | `log/slog` covers exactly what MiniKV needs: leveled, structured, injectable logging |

### 5. Integrity / checksums

| | |
|---|---|
| Normally | A general-purpose hashing library, or a checksum crate |
| Why tempting | Convenience wrappers around common hash functions |
| Replaced with | `hash/crc32` (stdlib), used per-record in `record.go`/`checksum.go` |
| Limitations | CRC-32 detects accidental corruption (bit flips, torn writes) but is not cryptographically secure — it will not detect a deliberate, crafted tampering of a record. See `SECURITY.md`. |
| Why appropriate | CRC-32 is the right tool for the actual threat model here (disk/media corruption, not adversarial tampering) and is directly in the standard library |

### 6. File and path utilities

| | |
|---|---|
| Normally | Assorted filesystem helper packages (atomic-write helpers, etc.) |
| Why tempting | Ready-made "atomic file replace" helpers |
| Replaced with | `os` + `path/filepath` directly: `os.OpenFile` with `O_EXCL` for safe creation, `os.Rename` for atomic replace (used in `compaction.go` and `backup.go`) |
| Limitations | Atomicity of `os.Rename` is a same-filesystem, same-OS guarantee, not a network-filesystem guarantee |
| Why appropriate | The stdlib primitives are exactly the ones any "atomic write" helper package would call internally |

### 7. Concurrency primitives

| | |
|---|---|
| Normally | Occasionally, higher-level concurrency helper packages (e.g. for read-write caches or worker pools) |
| Why tempting | Pre-built concurrent map / cache types |
| Replaced with | `sync.RWMutex` guarding a plain `map[string]indexEntry` (`database.go`, `index.go`) |
| Limitations | A single coarse-grained lock, not a sharded/striped map — see the "Design Trade-offs" section of README.md |
| Why appropriate | At the scale of a single embedded log file, one `RWMutex` is simple to reason about and was verified race-free with `go test -race` |

### 8. Configuration / flag parsing

| | |
|---|---|
| Normally | `spf13/viper`, or a dedicated env/config-file parser |
| Why tempting | Multi-source config (flags + env + file) with precedence rules |
| Replaced with | Plain command-line flags only (`--db`, `--sync`, `--ttl`), parsed by the same hand-written scanner as the CLI framework substitution above |
| Limitations | No config file support, no environment variable overrides |
| Why appropriate | MiniKV has exactly two global settings; a config-layering library would be pure overhead |

### 9. Binary encoding

| | |
|---|---|
| Normally | A schema-based serialization library (protobuf-style) for the record format |
| Why tempting | Schema evolution, generated encode/decode code |
| Replaced with | `encoding/binary` with an explicit, hand-documented fixed-width header (`record.go`) |
| Limitations | No automatic schema evolution — the `VERSION` byte exists precisely so future format changes can be handled explicitly in code, not automatically |
| Why appropriate | A single, stable, simple record shape doesn't need a schema compiler; `encoding/binary` plus a documented layout is easier to audit byte-for-byte |

### 10. HTTP layer (only if the optional dashboard is built)

| | |
|---|---|
| Normally | `gin-gonic/gin`, `labstack/echo`, or a frontend framework (React/npm/Tailwind) for the UI |
| Why tempting | Routing helpers, middleware, component-based UI |
| Replaced with | `net/http` + `html/template` for routing and server-rendered HTML, with plain CSS — no JavaScript framework, no npm |
| Limitations | No client-side interactivity beyond what plain HTML/CSS/minimal inline JS provides |
| Why appropriate | The dashboard (if included) is explicitly a secondary, "nice to have" view onto the engine — it doesn't need a full framework, and using one would undercut the zero-dependency premise of the whole submission |

---

Only substitutions actually reflected in the codebase are listed above;
nothing here was added just to reach a round number.
