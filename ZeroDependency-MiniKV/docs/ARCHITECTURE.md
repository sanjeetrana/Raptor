# MiniKV Architecture

## Layers

```
CLI (internal/cli)
  ↓
Command dispatch (Run → runSet/runGet/...)
  ↓
Database engine (internal/engine.Database)
  ↓
In-memory index (internal/engine.index)
  ↓
Append-only log (internal/engine.storage)
  ↓
Disk (a single *.db file)
```

Every CLI invocation opens the database, performs one operation, and
closes it again — matching typical CLI/embedded-database usage. The
`shell` subcommand keeps one `Database` open for the life of the REPL
instead.

## Startup sequence

```
Open(path)
  → os.OpenFile (create if missing)
  → recoverIndex(): scan the log from byte 0
      → for each record: validate header, validate length, validate checksum
      → SET  → index[key] = location
      → DELETE → delete(index, key)
      → stop at the first incomplete or corrupt record
  → if the scan stopped before EOF, truncate the file to the last valid
    byte (discard the torn/corrupt tail)
  → Database ready
```

See `recovery.go` for the full implementation and `SECURITY.md` /
README.md's "Crash Recovery" section for the reasoning behind stopping at
the first bad record instead of trying to skip past it.

## Write path

```
Set(key, value, ttl)
  → validate key is non-empty
  → build record{op: SET, key, value, expiresAt}
  → encode() → header + key + value + CRC32 checksum
  → mu.Lock()
  → WriteAt(buf, currentSize)     — append, never overwrite
  → Sync() if opts.Sync           — see "Durability" below
  → index[key] = {offset, keyLen, valueLen, expiresAt}
  → mu.Unlock()
```

Delete follows the same path but appends a tombstone record (op = DELETE,
empty value) and removes the key from the index.

## Read path

```
Get(key)
  → mu.RLock()
  → entry, ok := index[key]
  → if !ok or expired: return ErrNotFound
  → ReadAt(entry.valueOffset(), entry.valueLen)   — one seek, no scan
  → mu.RUnlock()
  → return value
```

Because the index tracks the exact byte offset and length of each key's
current value, `Get` never scans the log — it performs a single `ReadAt`
at a known offset, regardless of how large the log has grown.

## On-disk record format

See the detailed field-by-field layout at the top of `record.go`. In
summary: a 22-byte fixed header (magic, version, operation, key length,
value length, expiration), followed by the key bytes, the value bytes,
and a trailing 4-byte CRC-32 checksum covering everything before it.

## Durability

See the comment block at the top of `database.go` for the exact
guarantees of default (buffered) mode versus `--sync` (fsync-per-write)
mode. In short: default mode survives process crashes but not power loss
before the OS flushes its page cache; `--sync` mode survives power loss
at the cost of one fsync per write.

## Concurrency model

A single `sync.RWMutex` guards both the index map and the log's logical
size counter. Writes (`Set`, `Delete`, `Compact`) take the write lock;
reads (`Get`, `Exists`, `List`, `Stats`, `Backup`) take the read lock.
Holding the read lock for the full duration of a `Get` — including the
`ReadAt` call — is a deliberate simplicity/safety trade-off: it costs
some read parallelism under heavy write load, but it means there is
exactly one lock to reason about and no window where a concurrent
compaction could swap the underlying file out from under an in-flight
read. `go test -race ./...` is part of the CI-equivalent checklist in
SUBMISSION_CHECKLIST.md.

## Compaction

Compaction rewrites the log to a temporary file containing exactly one
SET record per live key (using the value + TTL already known from the
index — it never has to guess), fsyncs that file, and atomically renames
it over the original. A crash at any point before the rename leaves the
original, uncompacted log completely intact.
