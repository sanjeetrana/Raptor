# httpc

Zero-dependency HTTP/1.1 client built on raw `socket` + `ssl`.  
No `requests`, no `urllib.request`, no `http.client`.  
Every byte of the request is assembled by hand. Every byte of the response is parsed by hand.

**Track C — Web & Network | Zero Dependency Hackathon 2026**  
**Package Killer target:** `requests` / `httpx`

---

## What it does

| Feature | Detail |
|---|---|
| `GET` | Connect, send request line + headers, read status / headers / body |
| `POST` | Same, plus `Content-Length` + body |
| Custom headers | `--header "Key: Value"` (repeatable) |
| HTTPS / TLS | `ssl.create_default_context()` wrapping the raw socket |
| Chunked decoding | Manual hex-length chunk loop (RFC 7230 §4.1) |
| Redirect following | Auto-follow 301/302/303/307/308, up to 5 hops |
| Multipart Uploads | Hand-rolled boundaries using `os.urandom(16)` |

---

## Quick start

### Zero-Install Quick Start (Mac/Linux/WSL)
```bash
# Download the raw file directly (no pip, no package managers!)
curl -O https://raw.githubusercontent.com/YOUR_GITHUB_USERNAME/httpc/main/src/httpc.py

# Make it executable
chmod +x httpc.py

# Run it!
./httpc.py GET https://api.github.com/zen
```

### Standard Usage
```bash
# GET a real HTTPS endpoint
python3 src/httpc.py GET https://api.github.com/zen

# POST with a body and a custom header
python3 src/httpc.py POST https://httpbin.org/post \
    --data '{"hello":"world"}' \
    --header "Content-Type: application/json"

# Test redirect locally (run test server first — see below)
python3 src/httpc.py GET http://127.0.0.1:8765/redirect

# Skip redirect following
python3 src/httpc.py GET http://127.0.0.1:8765/redirect --no-follow

# Upload a file as multipart/form-data
python3 src/httpc.py POST http://127.0.0.1:8765/upload --file document=test.txt

# Makefile shortcut
make run ARGS="GET https://api.github.com/zen"
```

---

## Testing redirects locally

Terminal 1:
```bash
python3 tests/test_server.py
```

Terminal 2:
```bash
python3 src/httpc.py GET http://127.0.0.1:8765/redirect   # → 200 "You landed!"
python3 src/httpc.py GET http://127.0.0.1:8765/chunked     # → chunked body
python3 src/httpc.py POST http://127.0.0.1:8765/echo --data "ping"  # → "ping"
python3 src/httpc.py POST http://127.0.0.1:8765/upload --file doc=README.md # → 200 OK
```

---

## File layout

```
httpc/
├── README.md          ← this file
├── STDLIB.md          ← substitution log (10+ entries)
├── requirements.txt   ← empty (zero deps)
├── deps-proof.txt     ← pip freeze output (empty)
├── .zero-dep.toml     ← track + pitch
├── Makefile           ← one command to run
├── LICENSE            ← MIT
├── src/
│   └── httpc.py       ← entire tool, ONE file
└── tests/
    └── test_server.py ← local fixture server (stdlib only)
```

---

## Verified behaviour

| Test | Result |
|---|---|
| `GET https://api.github.com/zen` | TLS works; status + headers + body all correct |
| `POST http://127.0.0.1:8765/echo --data hello` | Body echoed back correctly |
| `GET http://127.0.0.1:8765/chunked` | Chunked body decoded correctly |
| `GET http://127.0.0.1:8765/redirect` | 302 followed to `/landed`, 200 returned |

---

## Honest limits

- HTTP/1.1 only (no HTTP/2)
- No connection pooling / keep-alive (one socket per request, `Connection: close`)
- No gzip/deflate decompression (disabled via `Accept-Encoding: identity`)
- Redirect loop cap: 5 hops

---

## One gotcha worth knowing

`ssl.SSLContext()` alone loads **no** trusted certificates — every HTTPS site fails
with an unknown-CA error. You must call `ssl.create_default_context()` (which loads
the OS trust store) or call `.load_default_certs()` explicitly. This bit me during
development; it's fixed and flagged with a comment in the source so it doesn't sneak
back in.
