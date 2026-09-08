# ReplayNet — Full Technical Specification
**Go 1.22+ · stdlib only · solo build, AI-assisted**

This document is written to be handed directly to a coding assistant as context. Structs and function signatures are fixed — implement against them rather than inventing alternatives, so output stays consistent across sessions/tools.

---

## 1. Repository layout

```
replaynet/
├── cmd/replaynet/main.go        CLI entry, subcommand dispatch
├── internal/session/
│   ├── format.go                 Event struct, binary encode/decode
│   └── session.go                Session struct, file read/write
├── internal/proxy/
│   └── proxy.go                  Recording reverse proxy
├── internal/replay/
│   ├── replay.go                 Replay engine, request matching
│   └── fault.go                  Fault injection
├── internal/visualizer/
│   ├── server.go                 SSE + static file server
│   └── static/                   index.html, app.js, style.css (embedded)
├── go.mod                        empty require block
├── Makefile
├── README.md
├── STDLIB.md
├── deps-proof.txt
├── .zero-dep.toml
├── scripts/reproducible-build.sh
└── tests/
    ├── session_roundtrip_test.go
    ├── proxy_record_test.go
    ├── replay_match_test.go
    └── fault_injection_test.go
```

---

## 2. Session format (`internal/session`)

### 2.1 Data structures

```go
package session

import (
    "net/http"
    "time"
)

type EventType uint8

const (
    EventRequest EventType = iota
    EventResponse
)

type Event struct {
    Index      int           // sequence number within session, assigned on write
    Offset     time.Duration // time since session start
    Type       EventType
    Method     string        // empty for response events
    Path       string        // empty for response events
    StatusCode int           // 0 for request events
    Headers    http.Header
    Body       []byte
    BodyHash   [32]byte      // sha256, always computed
}

type Session struct {
    ID        string
    StartTime time.Time
    Events    []Event
}
```

### 2.2 Binary record format (append-only file, one record per event)

Big-endian throughout.

```
[4 bytes]  record length (everything after this field)
[8 bytes]  offset nanoseconds (int64)
[1 byte]   event type (0=request, 1=response)
[2 bytes]  method length      | [N bytes] method        (0 length if response)
[2 bytes]  path length        | [N bytes] path           (0 length if response)
[4 bytes]  status code (int32, 0 if request)
[4 bytes]  header block length | [N bytes] header block  (see 2.3)
[4 bytes]  body length        | [N bytes] body
[32 bytes] sha256 of body
```

### 2.3 Header block encoding
Repeated: `[2 bytes key length][key bytes][2 bytes value length][value bytes]`, terminated by reaching the declared header block length. Multi-value headers: repeat the key.

### 2.4 Required functions

```go
package session

func WriteEvent(w io.Writer, e Event) error
func ReadEvent(r io.Reader) (Event, error, bool /* ok=false at clean EOF */)

func NewWriter(path string) (*Writer, error)          // creates/truncates file, writes nothing until first event
func (w *Writer) Append(e Event) error                 // encodes + writes + flushes
func (w *Writer) Close() error

func Load(path string) (*Session, error)                // reads entire file into memory (sessions are bounded, no need to stream on read)
```

### 2.5 Test requirement (write this first, before proxy/replay code)
`tests/session_roundtrip_test.go`: for a table of Event values (empty body, large body >1MB, empty headers, multi-value headers, unicode in path), `WriteEvent` then `ReadEvent` and assert deep equality. This is the foundation everything else depends on — do not proceed to proxy/replay work until this passes.

---

## 3. Recording proxy (`internal/proxy`)

### 3.1 Data structures

```go
package proxy

type RecordingProxy struct {
    upstream    *url.URL
    sessionW    *session.Writer
    startTime   time.Time
    nextIndex   int
    client      *http.Client
    mu          sync.Mutex   // guards nextIndex + sessionW writes
    onEvent     func(session.Event) // optional hook for visualizer SSE feed; nil if not in --inspect mode
}

func New(upstream string, sessionPath string, onEvent func(session.Event)) (*RecordingProxy, error)
func (p *RecordingProxy) ServeHTTP(w http.ResponseWriter, r *http.Request)
```

### 3.2 `ServeHTTP` algorithm

1. Read the full request body into memory (`io.ReadAll`), close original body. Cap at a configurable max (default 50MB) — reject with 413 above that, document the limit in README.
2. Build outbound request to `p.upstream` with same method/path/headers/body.
3. Record request event: `Type=EventRequest`, `Offset=time.Since(p.startTime)`, method, path, headers, body, body hash. Assign `Index`, increment under `p.mu`. Write via `p.sessionW.Append`. If `p.onEvent != nil`, call it (non-blocking — see visualizer section for how this must not stall the proxy path).
4. Execute the outbound request via `p.client.Do`.
5. On upstream error (connection refused, timeout): record a synthetic response event with `StatusCode=0` and a body containing the error string, still write it to the session (this is a legitimate recorded outcome — a failed upstream call is data, not something to discard), then write `502` to the real client.
6. On success: read upstream response body fully, record response event, write status+headers+body through to the real client, in that order (record before or concurrently with writing through — don't let recording block the client write for more than the time to compute the hash).

### 3.3 Concurrency
Each incoming request is handled on its own goroutine (Go's `net/http` default). The only shared mutable state is `nextIndex` and the session file writer — both guarded by `p.mu`. Document this plainly in README: **recording is safe under concurrent requests; event `Index` order reflects write-completion order, not necessarily request-arrival order** — this is an honest, stated limitation, not a bug to chase.

---

## 4. Replay engine (`internal/replay`)

### 4.1 Data structures

```go
package replay

type ReplayServer struct {
    session   *session.Session
    index     map[string][]session.Event // key = "METHOD PATH", values = response events in original order, in request-response pairs (see 4.2)
    cursor    map[string]int
    faults    []FaultRule
    startTime time.Time
    mu        sync.Mutex
    onEvent   func(session.Event) // visualizer hook, same as proxy
}

func New(sess *session.Session, faults []FaultRule) *ReplayServer
func (r *ReplayServer) ServeHTTP(w http.ResponseWriter, req *http.Request)
```

### 4.2 Index construction (in `New`)
Walk `sess.Events` in order. Pair each `EventRequest` with the immediately following `EventResponse` for the same logical exchange (in a single-upstream recording, requests and their responses are adjacent in the event log by construction — request at index *i*, its response at index *i+1*, since the proxy writes them in that order per 3.2). Build `index["METHOD PATH"] = []Event{response1, response2, ...}` in recorded order.

**Document explicitly in README**: this pairing assumes non-interleaved recording, which holds for the trimmed scope (proxy handles concurrent requests, but pairing assumes response N follows request N in the write log for that path — true because each request/response pair is written by the same goroutine sequentially before that goroutine's next event). If wall-clock interleaving across different goroutines ever produces same-path pairs out of order, that's the documented "sequential matching, not semantic" limitation from the main spec.

### 4.3 `ServeHTTP` algorithm

```go
func (r *ReplayServer) ServeHTTP(w http.ResponseWriter, req *http.Request) {
    key := req.Method + " " + req.URL.Path
    r.mu.Lock()
    idx := r.cursor[key]
    events := r.index[key]
    if idx >= len(events) {
        r.mu.Unlock()
        http.Error(w, "no more recorded responses for "+key, 404)
        return
    }
    ev := events[idx]
    r.cursor[key]++
    r.mu.Unlock()

    if fault, ok := r.faultFor(ev.Index); ok {
        applyFault(w, ev, fault)
        if r.onEvent != nil { r.onEvent(ev) }
        return
    }

    for k, vs := range ev.Headers {
        for _, v := range vs { w.Header().Add(k, v) }
    }
    w.WriteHeader(ev.StatusCode)
    w.Write(ev.Body)
    if r.onEvent != nil { r.onEvent(ev) }
}
```

### 4.4 Fault injection (`internal/replay/fault.go`)

```go
type FaultType int

const (
    FaultLatency FaultType = iota
    FaultDrop
    FaultStatus
)

type FaultRule struct {
    AtEventIndex   int
    Type           FaultType
    LatencyMs      int  // used if Type == FaultLatency
    StatusOverride int  // used if Type == FaultStatus
}

func applyFault(w http.ResponseWriter, ev session.Event, f FaultRule) {
    switch f.Type {
    case FaultLatency:
        time.Sleep(time.Duration(f.LatencyMs) * time.Millisecond)
        writeNormal(w, ev)
    case FaultDrop:
        // Do not write anything. Hijack the connection and close it if possible,
        // so the client sees a connection reset rather than hanging until its own timeout.
        if hj, ok := w.(http.Hijacker); ok {
            conn, _, err := hj.Hijack()
            if err == nil { conn.Close(); return }
        }
        // fallback: let it hang — document this fallback explicitly in README
    case FaultStatus:
        for k, vs := range ev.Headers {
            for _, v := range vs { w.Header().Add(k, v) }
        }
        w.WriteHeader(f.StatusOverride)
        w.Write(ev.Body)
    }
}
```

### 4.5 Test requirement
`tests/replay_match_test.go`: record a session against an `httptest.NewServer` fake upstream with a known sequence of requests (including repeated hits to the same path), shut the fake upstream down, replay, and assert every response matches byte-for-byte what was recorded, in the correct order. Use `testing/synctest` for the latency fault test so it's deterministic (virtualized clock) rather than a real `time.Sleep` in CI.

---

## 5. Visualizer (`internal/visualizer`)

### 5.1 Design constraint — event volume
Do **not** push a browser event per byte or per header line. Push one compact JSON message per request/response event:

```json
{"index":17,"offsetMs":812,"type":"response","method":"GET","path":"/permissions","status":500}
```

### 5.2 Server

```go
package visualizer

//go:embed static/*
var staticFS embed.FS

type Server struct {
    subscribers map[chan session.Event]bool
    mu          sync.Mutex
}

func New() *Server
func (s *Server) Broadcast(e session.Event)              // non-blocking send to all subscriber channels (buffered, size 64; drop if full rather than block the proxy/replay path)
func (s *Server) HandleEvents(w http.ResponseWriter, r *http.Request) // SSE endpoint
func (s *Server) HandleStatic(w http.ResponseWriter, r *http.Request) // serves embedded static files
```

**Critical constraint**: `Broadcast` must never block the proxy or replay request path. Use a buffered channel per subscriber and drop events if the buffer is full (a slow browser tab should never slow down the actual proxy/replay under test) — document this drop behavior in README.

### 5.3 Static UI (`internal/visualizer/static/`)
- `index.html` — swimlane layout (client / proxy / upstream), a scrolling event list below
- `app.js` — vanilla JS, `EventSource('/events')`, appends rows to the DOM as messages arrive, no framework, no build step
- `style.css` — plain CSS

---

## 6. CLI (`cmd/replaynet/main.go`)

```
replaynet proxy   --listen :9000 --upstream http://localhost:3000 --session out.rnet [--inspect :9001]
replaynet replay  session.rnet --listen :9002 [--fault at=12,type=latency,ms=4000] [--fault at=12,type=drop] [--fault at=12,type=status,code=503] [--inspect :9003]
```

- Use `flag.NewFlagSet` per subcommand.
- `--fault` may be repeated; parse each into a `replay.FaultRule`.
- `--inspect PORT` starts the visualizer server on that port and wires its `Broadcast` as the `onEvent` hook for the proxy/replay server.

---

## 7. Build & test

```makefile
build:
	go build -trimpath -o bin/replaynet ./cmd/replaynet

test:
	go test ./...

deps-proof:
	go list -m all > deps-proof.txt   # must show only the module itself, no requires

repro:
	./scripts/reproducible-build.sh
```

`scripts/reproducible-build.sh`: build twice with `-trimpath`, `sha256sum` both binaries, assert equal, print both hashes for the README.

---

## 8. Notes for AI-assisted implementation (Grok CLI / Codex)

- Feed this document as context and implement **section by section, in this order**: session format + its test (§2) → proxy (§3) → replay (§4) → visualizer (§5) → CLI (§6). Each section's test should pass before moving to the next — don't let an assistant generate the whole tree at once, since crash-safety and matching-order correctness are the parts that need verification, not just plausible-looking code.
- When asking an assistant to implement `applyFault`'s `FaultDrop` case, explicitly flag the hijack fallback behavior — assistants will sometimes "helpfully" add a timeout/error write that defeats the point of simulating a dropped connection. Review that function by hand.
- Ask the assistant to write the `session_roundtrip_test.go` table (§2.5) *before* generating the encode/decode implementation, and require the implementation to satisfy it — this catches an assistant silently reordering struct fields or getting endianness wrong, which is otherwise easy to miss on casual review.
- Keep the two AI tools from working on the same file simultaneously if you're time-slicing between them — merge conflicts on hand-tuned binary framing code are worse to untangle than normal application code.
