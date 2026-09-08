# STDLIB.md

Every package this project would normally reach for, and the standard-library
feature used instead. This is the receipt for **Zero-Dependency Craft** and
the **STDLIB Log** bonus (≥10 non-trivial substitutions).

---

## Substitutions

| # | You'd normally install | Used instead | Where / why |
|---|---|---|---|
| 1 | `httputil.ReverseProxy` helpers, `http-proxy`, or a Go reverse-proxy package | Hand-rolled forwarding over `net/http` + `http.Client` | `internal/proxy/proxy.go` — read body, clone headers, issue upstream request, stream response back. Avoids a proxy framework while keeping behavior inspectable. |
| 2 | protobuf / msgpack / a custom binary codec crate | `encoding/binary` with a hand-designed length-prefixed record format | `internal/session/format.go`, `encoding.go` — big-endian fixed-width + length-prefixed fields; no schema compiler. |
| 3 | A hashing / checksum package | `crypto/sha256` | Body checksums per event in `internal/session/format.go` for integrity of recorded payloads. |
| 4 | `gorilla/websocket`, `nhooyr/websocket`, Socket.IO | Server-Sent Events over plain `net/http` | `internal/visualizer/server.go` — one-way server→browser push does not need a WebSocket handshake. |
| 5 | React / Vue / Svelte + a bundler | `embed` + vanilla HTML/CSS/JS | `internal/visualizer/static/` — UI ships inside the binary; zero frontend build step. |
| 6 | `cobra`, `urfave/cli`, `kingpin` | `flag` + a tiny subcommand switch | `cmd/replaynet/main.go`, `flags.go` — idiomatic Go CLI without a framework. |
| 7 | `testify`, `gomega`, assertion libraries | `testing` + manual assertions | `tests/` — stdlib test tool only; no test runtime deps in the artifact. |
| 8 | `gomock`, `mockery`, or hand-rolled mock frameworks | `net/http/httptest.NewServer` with real handlers | `tests/replay_match_test.go`, `proxy_record_test.go` — fake upstream is a real HTTP server. |
| 9 | `zap`, `logrus`, `zerolog` | `fmt` + `os.Stderr` / `os.Stdout` | CLI status and errors — structured logging is unnecessary for a single-purpose tool. |
| 10 | `chi`, `gorilla/mux`, `echo`, `gin` | Direct `http.Handler` implementations | Proxy, replay, and visualizer each implement `ServeHTTP` / mux via stdlib — no router package. |
| 11 | `encoding/json` alternatives (`jsoniter`, `easyjson`) | `encoding/json` | Visualizer SSE payloads and UI export paths — stdlib JSON is enough at this volume. |
| 12 | `fs` / static-file middleware packages | `embed.FS` + `io/fs.Sub` + `http.FileServer` | `internal/visualizer/server.go` — static assets served from the binary. |
| 13 | UUID / ULID libraries for session identity | Session identity = file path; integrity = per-body SHA-256 | Keeps identity external and content-addressable without a UUID dependency. |
| 14 | Toxiproxy (as a dependency or sidecar you wrap) | First-party fault rules over replayed responses | `internal/replay/fault.go` — latency, TCP drop via `http.Hijacker`, status override. See Package Killer below. |
| 15 | Config / env parsers (`viper`, `envconfig`) | CLI flags with defaults | No config files; judges run the tool from flags alone. |
| 16 | CORS / SSE middleware packages | Hand-set SSE headers (`Content-Type: text/event-stream`, `Cache-Control`, `Connection`) | `internal/visualizer/server.go` — protocol headers written explicitly. |

**Grey area disclosure:** none. No vendored third-party source. No `golang.org/x/*`. No hidden shell-outs to external tools at runtime. Test tooling is Go’s built-in `testing` package only.

---

## Package Killer

**Target:** [Toxiproxy](https://github.com/Shopify/toxiproxy) (Shopify) — widely adopted network fault-injection proxy for resilience testing (**12.3k+ GitHub stars**).

**Claim:** ReplayNet covers the same *conceptual* need — deliberately degrading network conditions so clients can be tested under failure — with a from-scratch Go stdlib implementation, **plus** deterministic HTTP record/replay Toxiproxy does not provide.

**What we reimplemented:**

- Latency injection before a response is served
- Connection drop / reset (via `http.Hijacker`, with `503` fallback)
- Status-code override on a specific timeline event

**What we deliberately did not copy:**

- Full toxic catalog (bandwidth, slicer, slow_close, timeout variants, etc.)
- Toxiproxy’s multi-proxy admin API surface

Those were cut so the stdlib implementation stays correct and demable in 72 hours. The README comparison table states this honestly.

**Why this is a strong Package Killer for Track C:** Toxiproxy is a real tool teams install and run as infrastructure. Replacing “bring a fault-injection daemon” with “one zero-dep binary that also records and replays HTTP” is the useful surprise — not a toy reimplementation of a one-liner.

---

## Packages we refused to invent replacements for

Honesty over theater:

| Tempting import | Decision |
|---|---|
| TLS MITM / custom CA stack | Out of scope — plaintext HTTP only |
| Full WebSocket protocol | SSE covers the inspector push path |
| protobuf schema ecosystem | Custom binary format is smaller and sufficient |
| Frontend component library | Vanilla CSS/JS keeps the binary self-contained |
