# Demo Script — MiniKV (max 5:00)

All commands below are real and should be run live/on-screen, not
narrated over fake output. Build once at the top of the recording with
`go build -o minikv ./cmd/minikv` so every subsequent command is fast.

## 0:00–0:30 — Problem

- State the hackathon constraint: zero third-party runtime dependencies,
  standard library only.
- Note that most "storage engine" projects actually wrap SQLite or an
  existing embedded DB — this one doesn't.

## 0:30–1:00 — MiniKV introduction

- One sentence: "MiniKV is an append-only key-value storage engine, built
  from `os`, `encoding/binary`, `hash/crc32`, and `sync` — nothing else."
- Show the project structure (`internal/engine`, `internal/cli`).

## 1:00–2:00 — CLI live demo

```bash
./minikv set name Shraddha
./minikv get name
./minikv set city Pune
./minikv exists city
./minikv list
./minikv stats
./minikv delete city
./minikv list
```

Narrate exit codes briefly (`echo $?` after a `get` on a missing key ->
3).

## 2:00–3:00 — Persistence

```bash
./minikv set counter 1
./minikv get counter
# close the "session" — just run each command as a fresh process, which
# is how the CLI always works: every invocation opens and closes the DB
./minikv stats
```

Point out in the terminal that data survives because each command is a
fresh process reopening the same log file — there's no daemon, no
in-memory-only server.

## 3:00–3:45 — Crash recovery

Pre-stage a script (or do it live) that truncates the last few bytes of
the `.db` file to simulate a torn write, then reopen:

```bash
./minikv set will-survive 1
./minikv set will-be-torn 2
SIZE=$(stat -c%s minikv.db)
head -c $((SIZE-4)) minikv.db > minikv.db.tmp && mv minikv.db.tmp minikv.db
./minikv stats     # shows TruncatedBytes > 0
./minikv list      # shows "will-survive" but not "will-be-torn"
```

## 3:45–4:20 — Concurrency + tests

```bash
go test -race ./...
```

Show it passing. Briefly mention the concurrent-access test
(`TestConcurrentReadsAndWrites` in `internal/engine/engine_test.go`)
running dozens of goroutines against `Set`/`Get`/`List` simultaneously.

## 4:20–5:00 — Architecture + zero-dependency proof

```bash
go list -m all
go mod graph
cat go.mod
```

Show the output is just `minikv` and the Go toolchain — no third-party
module anywhere. Close by pointing at `STDLIB.md` on screen for a couple
of seconds as the concrete "what would normally be a dependency, and what
replaced it" reference.

---

**Rule for the actual recording:** every command shown above must be run
for real during capture. No staged/faked terminal output.
