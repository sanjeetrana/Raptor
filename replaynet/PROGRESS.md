# Submission status

ReplayNet · [Zero Dependency Hackathon](https://zerodepshack.com/) · Track C (Web & Network)

## Checklist

| Requirement | Status |
|---|---|
| Working, useful program | Done — record / offline replay / fault inject / inspector |
| One-command build (`make build`) | Done |
| Empty dependency manifest (`go.mod` has no `require`) | Done |
| Dependency proof (`deps-proof.txt` / `make deps-proof`) | Done |
| `README.md` — what / how / limits | Done |
| `STDLIB.md` — stdlib-for-package substitutions | Done (≥10) |
| `.zero-dep.toml` track metadata | Done |
| Tests covering edge cases | Done — 15 tests across session, proxy, replay, faults, visualizer |
| Reproducible Build bonus (+5) | Done — `make repro` |
| Package Killer bonus (+3) | Done — Toxiproxy |
| STDLIB Log bonus (+3) | Done |
| 5-minute demo video | **Record using [`DEMO.md`](DEMO.md), then paste URL in submission form** |

## Verified locally

- `go build ./...` and `go test ./...` pass
- `make demo` end-to-end workflow passes
- `make repro` produces matching SHA-256 hashes
- `go list -m all` prints only `replaynet`

## Deliberate non-goals

TLS MITM, semantic request matching, bandwidth toxics, session diff CLI — see README *Known limitations*.
