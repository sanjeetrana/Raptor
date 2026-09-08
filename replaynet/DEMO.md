# Demo video script (≤5 minutes)

Required for Zero Dependency Hackathon submission. Record this exactly — judges need to see the tool work **and** the empty manifest.

**Suggested title:** `ReplayNet — Zero-Dep HTTP Record / Replay / Fault Injection`

**Suggested length:** 4:00–4:45

---

## Shot list

### 0:00–0:25 · Cold open + claim

On camera or voiceover:

> “ReplayNet records a real HTTP conversation, kills the backend, then replays it deterministically — with fault injection and a live inspector — using zero third-party dependencies.”

Show the GitHub repo root for 2 seconds.

### 0:25–0:55 · Empty manifest proof

Terminal:

```bash
cat go.mod
# module replaynet
# go 1.22.2
# (no require block)

make deps-proof && cat deps-proof.txt
# replaynet
```

Say: “That single line is the entire module graph.”

Optional: flash `STDLIB.md` header for one second.

### 0:55–2:10 · Automated demo

```bash
make demo
```

Let the script run. Narrate the five steps as they print:

1. Mock backend starts on `:8080`
2. Recording proxy on `:9000` (inspector `:9001`)
3. Client traffic: login → profile → permissions fail → retry success
4. Backend killed — connection refused proved
5. Replay on `:9002` reproduces the same sequence with **no backend**
6. Fault inject event `#7` → retry becomes `503`

Pause briefly on the fault-injection status line so judges see `503`.

### 2:10–3:20 · Live inspector

Restart a short interactive path (or leave inspect running from a manual run):

```bash
# Terminal A — mock backend
go run ./scripts/mock_server.go

# Terminal B — proxy + inspect
./bin/replaynet proxy \
  --listen :9000 \
  --upstream http://localhost:8080 \
  --session demo.rnet \
  --inspect :9001
```

Browser: open `http://localhost:9001`

- Show topology animation while curling a few requests
- Click an event → drawer opens (headers / JSON / cURL)
- Toggle a theme once
- Mention: “This UI is `embed.FS` + vanilla JS — no React, no npm”

### 3:20–4:10 · Offline replay punchline

```bash
# kill backend first
./bin/replaynet replay demo.rnet --listen :9002 --inspect :9003
curl -s http://localhost:9002/login
curl -s -w "\n%{http_code}\n" http://localhost:9002/permissions
curl -s -w "\n%{http_code}\n" http://localhost:9002/permissions
```

Say: “Same conversation. Zero upstream. Stdlib only.”

### 4:10–4:45 · Close

Show briefly:

```bash
make repro
make test
```

End card:

- Track C · Web & Network
- Bonuses: Reproducible Build · Package Killer (Toxiproxy) · STDLIB Log
- Repo URL
- “Every dependency is a stranger. This time, invite none.”

---

## Recording tips

- Use a 1280×720 or 1920×1080 terminal with large font (16–18pt).
- Prefer a light terminal theme for readability on compressed video.
- Do not scroll the README for more than 5 seconds — show commands, not prose.
- If time is tight, skip the interactive inspector restart and use screenshots captured during `make demo` with `--inspect` left open in a prior take.
- Upload unlisted to YouTube/Loom and paste the link in the submission form + repo README (optional badge).

---

## After you record

Add the link here for judges and your submission form:

```
Demo video: <URL>
```
