# STDLIB.md — Standard-Library Substitution Log

**httpc** · Track C (Web & Network) · Zero Dependency Hackathon 2026  
Package Killer target: `requests` / `httpx`

Every entry below names what `requests` / `httpx` normally does for you, the
stdlib feature used instead, and a one-line rationale explaining the craft.

---

| # | What `requests` does for you | Stdlib feature used | Rationale |
|---|---|---|---|
| 1 | `requests.get(url)` — opens a TCP connection for you | `socket.create_connection((host, port), timeout=15)` | DNS + TCP in one call; the exact socket `requests` wraps but never shows you |
| 2 | Transparent TLS via the `certifi` CA bundle | `ssl.create_default_context()` | Loads the OS trust store; no third-party CA bundle needed; hostname verification on by default |
| 3 | Request serialisation (method line, headers, CRLF) | Manual `"\r\n".join(lines).encode("latin-1")` | HTTP/1.1 wire format is just ASCII; building it by hand makes the protocol visible |
| 4 | Response status-line parsing | `status_line.split(" ", 2)[1]` — parse the integer by hand | `requests` hides `response.status_code` extraction; here it's one `int()` call |
| 5 | Response header parsing into a dict | Loop over `header_block.split("\r\n")`, `line.partition(":")` | Lower-cased keys mirror `requests.headers`; no regex, no library |
| 6 | Chunked transfer-encoding decoding | Manual hex-size loop (RFC 7230 §4.1): `int(size_str, 16)` per chunk | `requests` silently decodes chunked bodies; this loop makes the protocol step visible |
| 7 | `Content-Length`-bounded body reads | `sock.recv(8192)` loop until `len(buf) >= length` | Exact byte count instead of "read until close" — correct for keep-alive-capable servers |
| 8 | Redirect following (`allow_redirects=True`) | Manual `Location` header check + recursive `do_request()` | `requests` auto-follows; here the 3xx → GET downgrade (RFC 7231 §6.4) is explicit |
| 9 | URL parsing (`urllib.parse.urlsplit`) | Hand-rolled `parse_url()`: split on `://`, then on first `/` | Makes scheme/host/port/path visible; avoids importing urllib |
| 10 | Per-request timeout | `socket.create_connection(..., timeout=15)` | Single `timeout` arg covers both connect and read on the same socket |
| 11 | `Content-Length` injection on POST | `f"Content-Length: {len(body)}"` appended to header list | `requests` computes this silently; explicit here so the body length is always traceable |
| 12 | CLI argument parsing | `argparse` (stdlib) — `--data`, `--header`, `--no-follow`, `--file` | `argparse` is the one stdlib piece that *is* the right tool; flagged so judges know it's intentional |
| 13 | Multipart file uploads (`requests.post(url, files=...)`) | `os.urandom(16).hex()` for the boundary, string formatting for headers | Removes the need for complex multipart encoding libraries; boundary generation relies purely on standard OS entropy |

---

## Test tooling note

No third-party test framework is used.  
`tests/test_server.py` is a plain stdlib (`socket` + `threading`) fixture server
used only for local validation; it ships in `tests/`, not in the artifact, and
carries no runtime dependency.
