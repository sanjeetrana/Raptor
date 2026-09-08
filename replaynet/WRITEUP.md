# Write-Up side quest — draft & structure

**Deadline:** September 8, 2026  
**Prize:** Top 3 × $100 (insight, not followers)  
**Required vibe:** what you reimplemented, what stdlib made painful, the package you made look unnecessary, the edge case that ate an afternoon. **Tag Hackathon Raptors.**

Publish anywhere public (Dev.to / Hashnode / Medium / personal blog). Judges want **insight**, not a README paste.

---

## Recommended title options (pick one)

1. **I killed Toxiproxy’s job with zero Go dependencies — then the backend died on purpose**
2. **Record once, kill the server, replay forever: building ReplayNet on Go’s stdlib**
3. **What Toxiproxy doesn’t do: deterministic HTTP replay with an empty `go.mod`**

Suggested: **#2** (clear + technical) or **#1** (Package Killer punch).

---

## Suggested length & shape

**1,200–1,800 words.** Five sections. One diagram. Two code snippets max. One failure story. One honest limitation.

Do **not** walk through every CLI flag. Do **not** list all 16 STDLIB substitutions. Pick the three that hurt.

---

## Outline (write to this)

### 1. Hook (120–150 words)

Open on the *problem*, not the hackathon rules.

> I needed a failing `/permissions` call to happen twice the same way — once for a retry bug, once for a status-code regression — without keeping a flaky staging backend online. Toxiproxy can hurt the network. It cannot *become* the upstream after the upstream is gone.

Then one sentence on the constraint:

> Zero Dependency Hackathon, Track C: Go stdlib only. Empty `go.mod`. No `golang.org/x`.

End the hook with the claim:

> So I built ReplayNet: record a real HTTP conversation, kill the backend, replay it deterministically, inject faults on a timeline, and watch it live over SSE — in one ~9 MB binary.

### 2. The package I made look unnecessary (250–300 words)

**Centerpiece for Package Killer + Write-Up.**

Explain Toxiproxy fairly first (don’t strawman):

- Great at latency / bandwidth / connection toxics in front of a *live* service
- Teams already run it in chaos / resilience setups
- 12k+ stars for a reason

Then the gap:

| What you want | Toxiproxy | ReplayNet |
|---|---|---|
| Degrade live network | Yes | Partially (3 fault modes) |
| Replay without upstream | No | Yes |
| Capture production-shaped multi-step flows | Manual mocks | Record once |
| Empty dependency graph | No | Yes |

**Insight line to land:**

> Fault injection against a live service tests *your network assumptions*. Deterministic replay tests *your client’s conversation assumptions*. Those are different bugs. Most stacks only buy the first.

### 3. What the stdlib made painful (300–400 words) — **this wins the side quest**

Pick **exactly three** scars. Suggested set (all true for this repo):

#### Pain 1 — Binary session format without protobuf
- Temptation: protobuf / msgpack
- Reality: `encoding/binary`, length-prefixed frames, big-endian everywhere
- Scar: partial writes. A crash mid-frame must not poison `Load`.
- Payoff: append-only `.rnet` + truncate-on-corrupt-tail recovery

*One short snippet ok:* record length prefix idea, not the whole codec.

#### Pain 2 — Live UI without React or WebSockets
- Temptation: React + ws library
- Reality: `embed.FS` + vanilla JS + SSE
- Scar: backpressure. A slow browser tab must not stall the proxy.
- Payoff: buffered subscriber channels that **drop** instead of block

**Insight line:**

> The zero-dep rule didn’t make the UI hard. Protecting the hot path from the UI did.

#### Pain 3 — “Drop connection” without a chaos framework
- Temptation: Toxiproxy-style toxic API
- Reality: `http.Hijacker`, close the TCP conn, fall back to `503` if hijack fails
- Scar: honesty in failure modes — pretend reset vs real reset
- Payoff: documented fallback in README limitations

Optional fourth scar if you have room: CLI with `flag` instead of Cobra (subcommand parsing quirks).

### 4. The edge case that ate an afternoon (200–250 words)

**Best candidate from this project:** sequential `(method, path)` matching.

Tell the story:

1. Recorded `GET /permissions` → 500, then `GET /permissions` → 200
2. Replay worked… until concurrent clients or out-of-order calls shuffled the cursor
3. Realized: matching is not “smart HTTP”, it’s a **tape**
4. Chose tape-over-magic deliberately for 72h reliability
5. Documented it as a limitation instead of papering over it with fuzzy matching

**Insight line:**

> The dangerous part of zero-dep isn’t missing packages. It’s the urge to invent a half-correct protocol feature because a library would have hidden the complexity.

Alternate afternoon-eater if you prefer: 50MB body cap + `413`, or VCS buildinfo breaking “reproducible” hashes until `-buildvcs=false`.

### 5. What I’d ship next / close (150–200 words)

Keep it short and confident:

- Not TLS MITM (certificate theater vs useful weekend tool)
- Maybe: session diff, request-body-aware matching, one more toxic (bandwidth)
- Close on the hackathon thesis without preaching:

> Every dependency is a stranger. For one weekend I invited none — and the surprising part wasn’t that Go’s stdlib was enough. It was how many “must-have” packages were just habits.

CTA:

- Repo: https://github.com/benjaminnkem/replaynet
- `make demo`
- Tag: **Hackathon Raptors** · Zero Dependency · Track C

---

## Voice checklist (judges notice)

| Do | Don’t |
|---|---|
| Admit what Toxiproxy still does better | Claim “Toxiproxy is obsolete” |
| Show one real scar with a concrete fix | Dump the whole STDLIB table |
| Use “we chose X because Y” | Use “AI helped me build…” as the plot |
| Include one limitation proudly | Hide sequential matching |
| Link the repo once at the end | Paste install docs mid-article |

---

## Publish checklist

- [ ] Draft in your voice (edit this outline; don’t publish the meta instructions)
- [ ] Add 1 architecture ASCII or screenshot of the inspector
- [ ] Tag **Hackathon Raptors** (and Zero Dependency if the platform allows)
- [ ] Post before **Sep 8, 2026**
- [ ] Paste the article URL into your hackathon submission / Discord if they ask
- [ ] Optional: add link under README “Demo video” / write-up section after publish

---

## Starter opening paragraph (steal & rewrite)

> Staging lied to me twice in one week. The first time, a permissions endpoint returned 500 once and recovered; the second time it didn’t, and my client’s retry logic “passed” against a mock that never failed. I didn’t need another mock framework. I needed the *real conversation* on disk, and a way to play it back after the server was gone. Under the Zero Dependency Hackathon rules — Go standard library only, empty `go.mod` — that constraint stopped being a gimmick and became the design. The result is ReplayNet: a recording proxy, an offline replay engine, timeline fault injection, and an embedded SSE inspector, with `go list -m all` printing a single line.

---

## Optional tweet / Discord blurb (after publish)

> Wrote up building ReplayNet for @HackathonRaptors Zero Dependency: record real HTTP, kill the backend, replay + fault-inject it with an empty go.mod. Package killer target: Toxiproxy — but for conversation determinism, not just live toxics.  
> Repo: https://github.com/benjaminnkem/replaynet  
> Post: &lt;URL&gt;
