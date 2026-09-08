# ReplayNet

[![Zero Dependency](https://img.shields.io/badge/dependencies-0-brightgreen.svg?style=flat-square)](https://zerodepshack.com/)
[![Track](https://img.shields.io/badge/track-C%20(Web%20%26%20Network)-blue.svg?style=flat-square)](https://zerodepshack.com/#tracks)
[![Go Version](https://img.shields.io/badge/go-1.22%2B-00ADD8.svg?style=flat-square&logo=go)](https://go.dev/)
[![License: MIT](https://img.shields.io/badge/license-MIT-purple.svg?style=flat-square)](LICENSE)
[![Reproducible](https://img.shields.io/badge/build-reproducible%20%E2%9C%93-success.svg?style=flat-square)](scripts/reproducible-build.sh)
[![Package Killer](https://img.shields.io/badge/package%20killer-Toxiproxy-orange.svg?style=flat-square)](STDLIB.md#package-killer)

> **Record a real HTTP conversation once. Kill the backend. Replay the exact conversation deterministically — with timeline fault injection and a live SSE inspector.**
>
> Built for the [Zero Dependency Hackathon](https://zerodepshack.com/) · **Track C — Web & Network** · Go standard library only · `go.mod` has no `require` block.

---

## Why this exists

Resilience testing usually means either:

1. **Keeping a real backend online** while you poke network conditions (Toxiproxy-style), or
2. **Mocking responses by hand** and hoping they still match production shape.

ReplayNet takes a third path: **capture the real conversation once**, then **impersonate the upstream forever** from a crash-resilient `.rnet` session file. No database. No containers. No third-party packages. One binary.

That is the product judges can actually use — and the zero-dep constraint is the engineering receipt.

---

## Quick start

```bash
git clone https://github.com/benjaminnkem/replaynet.git
cd replaynet
make build          # → bin/replaynet
make demo           # full automated record → kill backend → replay → fault inject
```

Or install from source:

```bash
curl -sSL https://raw.githubusercontent.com/benjaminnkem/replaynet/main/install.sh | bash
```

**Requirements:** Go 1.22+ toolchain. Nothing else.

---

## What it does

### 1. Transparent recording proxy

```bash
replaynet proxy \
  --listen :9000 \
  --upstream http://localhost:3000 \
  --session out.rnet \
  --inspect :9001
```

Point your client at ReplayNet instead of the backend. Every request and response is timed, SHA-256 hashed, and appended to a binary `.rnet` session while traffic still reaches upstream.

Open `http://localhost:9001` for the live inspector while you record.

### 2. Deterministic replay (backend optional — usually off)

```bash
replaynet replay out.rnet --listen :9002 --inspect :9003
```

ReplayNet **is** the upstream. Incoming requests match recorded responses by `(method, path)` in sequential order, so multi-step flows stay faithful:

`login → profile → permissions failure → retry → success`

### 3. Timeline fault injection

```bash
replaynet replay out.rnet --listen :9002 --fault "at=7,type=status,code=503"
replaynet replay out.rnet --listen :9002 --fault "at=3,type=latency,ms=2500"
replaynet replay out.rnet --listen :9002 --fault "at=5,type=drop"
```

| Fault | Effect |
|---|---|
| `status` | Override the recorded status code at a timeline index |
| `latency` | Sleep before serving the recorded response |
| `drop` | Hijack and close the TCP connection (falls back to `503` if hijack is unavailable) |

Repeat `--fault` to stack rules. History changes; application code does not.

### 4. Embedded live inspector

`--inspect PORT` serves a zero-build UI via `embed.FS` and streams events over Server-Sent Events:

- Animated client ↔ engine ↔ upstream topology
- Slide-over drawer: headers, syntax-highlighted JSON, raw bytes, request/response pairing
- One-click cURL generator per event
- Themes: Cyber Dark, Slate Studio, Clean Light
- Session JSON export and live metrics (2xx / 3xx / 4xx / 5xx)

No React. No bundler. No npm.

---

## Architecture

```
┌──────────┐   HTTP    ┌─────────────────────┐   HTTP    ┌──────────┐
│  Client  │ ────────► │  ReplayNet (proxy)  │ ────────► │ Upstream │
└──────────┘           │  + session writer   │           └──────────┘
                       │  + optional inspect │
                       └──────────┬──────────┘
                                  │ append-only .rnet
                                  ▼
                       ┌─────────────────────┐
                       │  ReplayNet (replay) │  ◄── no upstream required
                       │  + fault rules      │
                       │  + optional inspect │
                       └─────────────────────┘
```

| Package | Responsibility |
|---|---|
| `internal/session` | Append-only binary event format, SHA-256 body checksums, partial-write recovery |
| `internal/proxy` | Recording reverse proxy over `net/http` |
| `internal/replay` | Sequential `(method, path)` playback + fault injection |
| `internal/visualizer` | SSE broadcaster + embedded static UI |
| `cmd/replaynet` | `flag`-based CLI (`proxy`, `replay`, `version`) |

### Concurrency model (Track C)

Honest, not aspirational:

- **HTTP servers** use Go’s standard `net/http` goroutine-per-request model.
- **Session writes** are serialized behind a `sync.Mutex` so concurrent requests cannot interleave binary frames.
- **Replay cursors** (`method+path → next index`) are mutex-guarded; matching is intentionally sequential, not parallel-speculative.
- **Visualizer fan-out** uses buffered subscriber channels. A full channel **drops** the event instead of blocking the proxy/replay hot path. Slow browser tabs never stall traffic.
- **Inspector** runs on its own `ListenAndServe` goroutine when `--inspect` is set.

There is no worker pool library, no channel framework, and no async runtime beyond the stdlib.

---

## Performance

Micro-benchmarks on this machine (`make bench`, Go `testing.B`):

| Benchmark | Latency | Approx throughput | Allocs |
|---|---|---|---|
| `BenchmarkSessionWriteRead` | ~4.4 μs/op | ~226k ops/s | 30 allocs/op |
| `BenchmarkProxyThroughput` | ~285 μs/op | ~3.5k req/s | 186 allocs/op |
| `BenchmarkReplayThroughput` | ~110 μs/op | ~9.1k req/s | 74 allocs/op |

These are **local micro-benchmarks**, not production SLOs. Replay is faster than proxy because there is no upstream round-trip — which is the point.

Single binary footprint: **~9.4 MB** (includes embedded inspector UI), built with `-trimpath`.

---

## Package Killer: Toxiproxy

ReplayNet targets the same problem space as **[Toxiproxy](https://github.com/Shopify/toxiproxy)** (Shopify; 12.3k+ GitHub stars): inject network faults so clients and services can be tested under failure.

| Capability | Toxiproxy | ReplayNet |
|---|---|---|
| Third-party runtime deps | Many (client libs, CLI stack) | **0 — Go stdlib only** |
| Fault injection | Latency, drop, bandwidth, etc. | Latency, TCP drop, status override |
| Deterministic HTTP record/replay | No (needs live upstream) | **Yes — offline playback** |
| Live browser inspector | No | **Yes — embedded SSE UI** |
| Artifact | ~25 MB daemon-oriented | **~9.4 MB single CLI binary** |
| Config surface | Toxics + API/CLI | Flags only; no config files |

ReplayNet does **not** claim feature parity on every Toxiproxy toxic. It claims a **stdlib-only alternative** that adds offline deterministic replay Toxiproxy was never designed to do. Full substitution notes live in [`STDLIB.md`](STDLIB.md).

---

## Zero-dependency verification

```bash
make deps-proof   # go list -m all → deps-proof.txt
cat deps-proof.txt
# replaynet
```

That single line is the entire module graph. No `require` block in [`go.mod`](go.mod). CI also asserts this on every push (`.github/workflows/ci.yml`).

### Bonus challenges claimed

| Bonus | Status | Evidence |
|---|---|---|
| **Reproducible Build** (+5) | Claimed | `make repro` — byte-identical `-trimpath` builds |
| **Package Killer** (+3) | Claimed | Toxiproxy — see table above + `STDLIB.md` |
| **STDLIB Log** (+3) | Claimed | ≥10 real substitutions in [`STDLIB.md`](STDLIB.md) |

Reproducible build (same machine, same toolchain):

```
build 1: 253d9ba879cc4e2df8008a88e499f846830aa0865b2534e2cb1cf725362d4cb4
build 2: 253d9ba879cc4e2df8008a88e499f846830aa0865b2534e2cb1cf725362d4cb4
MATCH: reproducible build confirmed
```

---

## Build & test

```bash
make build       # bin/replaynet
make test        # unit + integration suite
make bench       # micro-benchmarks
make deps-proof  # empty third-party graph
make repro       # byte-identical rebuild check
make demo        # automated end-to-end workflow
```

One-command build. One-command demo. Empty manifest. That is the submission bar.

---

## Project layout

```
replaynet/
├── cmd/replaynet/          CLI entrypoint
├── internal/
│   ├── session/            Binary .rnet format
│   ├── proxy/              Recording proxy
│   ├── replay/             Playback + faults
│   └── visualizer/         SSE + embedded UI
├── tests/                  Edge cases, e2e, benches
├── scripts/                Demo, mock upstream, repro build
├── docs/TECHNICAL_SPEC.md  Design contract
├── STDLIB.md               Stdlib-for-package substitutions
├── DEMO.md                 5-minute demo video script
├── deps-proof.txt          go list -m all output
├── .zero-dep.toml          Track metadata
├── go.mod                  no require block
├── Makefile
└── LICENSE                 MIT
```

---

## Known limitations

Documented deliberately — not left for judges to discover:

1. **Plaintext HTTP only.** No TLS interception / MITM. That would need a CA and certificate machinery outside this weekend’s useful scope.
2. **Matching is `(method, path)` + sequential order.** The *n*th `GET /permissions` returns the *n*th recorded response for that key. Bodies and headers are not part of the match key.
3. **Three fault modes.** Latency, drop, status override. Bandwidth throttling and half-closes were cut to keep the stdlib path reliable.
4. **Visualizer samples per HTTP frame**, not per byte. Non-blocking channel drops protect throughput when the browser lags.
5. **Drop fallback.** If `http.Hijacker` is unavailable, drop faults degrade to `503` instead of pretending the TCP reset happened.

---

## Demo video

Judges need a ≤5-minute walkthrough. Use the shot list in [`DEMO.md`](DEMO.md) — it covers empty-manifest proof, `make demo`, live inspector, offline replay, and fault injection.

---

## License

MIT — see [LICENSE](LICENSE).
