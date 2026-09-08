#!/usr/bin/env python3
"""
httpc — Zero-dependency HTTP/1.1 client
Built on raw socket + ssl. No requests, no urllib.request, no http.client.
Track C — Web & Network | Zero Dependency Hackathon 2026
"""

# stdlib only
import argparse
import socket
import ssl
import sys
import os

# 1. URL PARSING

def parse_url(url: str) -> tuple[str, str, int, str]:
    """
    Split a URL into (scheme, host, port, path).
    """
    if "://" not in url:
        raise ValueError(f"Missing scheme in URL: {url!r}")

    scheme, rest = url.split("://", 1)
    scheme = scheme.lower()
    if scheme not in ("http", "https"):
        raise ValueError(f"Unsupported scheme {scheme!r}; only http/https supported")

    # Split host[:port] from path
    if "/" in rest:
        host_part, path = rest.split("/", 1)
        path = "/" + path
    else:
        host_part = rest
        path = "/"

    # Separate host and optional port
    if ":" in host_part:
        host, port_str = host_part.rsplit(":", 1)
        port = int(port_str)
    else:
        host = host_part
        port = 443 if scheme == "https" else 80

    if not host:
        raise ValueError(f"Empty host in URL: {url!r}")

    return scheme, host, port, path


# 2. CONNECTION — raw socket

def open_connection(scheme: str, host: str, port: int) -> socket.socket:
    """
    Open a TCP connection and, for HTTPS, wrap it with a verified TLS context.
    Note: ssl.create_default_context() is required to load OS trust store.
    """
    try:
        sock = socket.create_connection((host, port), timeout=15)
    except OSError as exc:
        sys.exit(f"[httpc] Connection failed ({host}:{port}): {exc}")

    if scheme == "https":
        ctx = ssl.create_default_context()          # loads OS trust store + verifies hostname
        try:
            sock = ctx.wrap_socket(sock, server_hostname=host)
        except ssl.SSLError as exc:
            sock.close()
            sys.exit(f"[httpc] TLS handshake failed for {host}: {exc}")

    return sock


# 3. REQUEST BUILDER — manual \r\n-joined header block

def build_request(
    method: str,
    host: str,
    path: str,
    extra_headers: list,
    body,
) -> bytes:
    """
    Serialize an HTTP/1.1 request to raw bytes.
    We build the request by hand: request-line, then CRLF-separated headers,
    then a blank line, then the optional body.
    """
    lines = [
        f"{method} {path} HTTP/1.1",
        f"Host: {host}",
        "Connection: close",
        "Accept-Encoding: identity",   # disable gzip — we read raw bytes
        "User-Agent: httpc/1.0 (zero-dep; socket+ssl)",
    ]

    # Fold in caller-supplied headers
    for h in extra_headers:
        if ":" not in h:
            sys.exit(f"[httpc] Malformed header (missing colon): {h!r}")
        lines.append(h)

    # Body bookkeeping for POST
    if body is not None:
        lines.append(f"Content-Length: {len(body)}")
        # Add Content-Type only if the caller didn't provide one
        has_ct = any(h.lower().startswith("content-type") for h in extra_headers)
        if not has_ct:
            lines.append("Content-Type: application/octet-stream")

    # Blank line terminates headers; body follows
    lines.append("")
    lines.append("")
    raw_headers = "\r\n".join(lines).encode("latin-1")

    return raw_headers + (body if body is not None else b"")


# 4. RESPONSE PARSER — status line + header block + body dispatch

def _recv_until_blank_line(sock: socket.socket):
    """
    Read bytes from *sock* until the blank line that terminates HTTP headers.
    Returns (status_line, headers_dict, body_start_bytes).
    """
    buf = b""
    while b"\r\n\r\n" not in buf:
        chunk = sock.recv(4096)
        if not chunk:
            break
        buf += chunk
        if len(buf) > 65536:
            raise RuntimeError("[httpc] Header block exceeds 64 KiB — aborting")

    if b"\r\n\r\n" not in buf:
        raise RuntimeError("[httpc] Malformed response: no header terminator found")

    header_block, body_start = buf.split(b"\r\n\r\n", 1)
    lines = header_block.decode("latin-1").split("\r\n")

    if not lines:
        raise RuntimeError("[httpc] Empty response from server")

    status_line = lines[0]

    headers = {}
    for line in lines[1:]:
        if ":" in line:
            k, _, v = line.partition(":")
            headers[k.strip().lower()] = v.strip()

    return status_line, headers, body_start


def _read_body_chunked(sock: socket.socket, body_start: bytes) -> bytes:
    """
    Decode a Transfer-Encoding: chunked response body.
    We accumulate a raw byte buffer and parse chunk-sizes by hand.
    """
    buf = body_start
    # Keep reading until we have the terminating "0\r\n"
    while b"\r\n0\r\n" not in buf and not buf.startswith(b"0\r\n"):
        chunk = sock.recv(8192)
        if not chunk:
            break
        buf += chunk

    decoded = bytearray()
    pos = 0
    while pos < len(buf):
        # Find chunk-size line
        crlf = buf.find(b"\r\n", pos)
        if crlf == -1:
            break
        size_str = buf[pos:crlf].split(b";")[0].strip()  # strip chunk-extensions
        if not size_str:
            break
        try:
            chunk_size = int(size_str, 16)
        except ValueError:
            raise RuntimeError(
                f"[httpc] Bad chunk-size {size_str!r} at offset {pos}"
            )

        if chunk_size == 0:
            break  # last-chunk

        data_start = crlf + 2
        data_end = data_start + chunk_size

        # If we don't have enough data yet, keep reading
        while data_end + 2 > len(buf):
            more = sock.recv(8192)
            if not more:
                raise RuntimeError("[httpc] Connection closed mid-chunk")
            buf += more

        decoded.extend(buf[data_start:data_end])
        pos = data_end + 2  # skip trailing CRLF

    return bytes(decoded)


def _read_body_content_length(
    sock: socket.socket, body_start: bytes, length: int
) -> bytes:
    """Read exactly *length* bytes for the body."""
    buf = body_start
    while len(buf) < length:
        chunk = sock.recv(8192)
        if not chunk:
            break
        buf += chunk
    return buf[:length]


def _read_body_until_close(sock: socket.socket, body_start: bytes) -> bytes:
    """Read until the server closes the connection (Connection: close)."""
    buf = body_start
    while True:
        chunk = sock.recv(8192)
        if not chunk:
            break
        buf += chunk
    return buf


def parse_response(sock: socket.socket):
    """
    Read and parse a full HTTP/1.1 response from *sock*.
    Returns (status_code, headers, body_bytes).
    """
    status_line, headers, body_start = _recv_until_blank_line(sock)

    # Parse status code
    parts = status_line.split(" ", 2)
    if len(parts) < 2:
        raise RuntimeError(f"[httpc] Malformed status line: {status_line!r}")
    try:
        status_code = int(parts[1])
    except ValueError:
        raise RuntimeError(f"[httpc] Non-integer status code in: {status_line!r}")

    # Dispatch body reading strategy
    te = headers.get("transfer-encoding", "")
    cl = headers.get("content-length", "")

    if "chunked" in te.lower():
        body = _read_body_chunked(sock, body_start)
    elif cl:
        try:
            length = int(cl)
        except ValueError:
            raise RuntimeError(f"[httpc] Non-integer Content-Length: {cl!r}")
        body = _read_body_content_length(sock, body_start, length)
    else:
        body = _read_body_until_close(sock, body_start)

    return status_code, headers, body


# 5. REDIRECT FOLLOWER — manual Location header check (FR-6)

MAX_REDIRECTS = 5

def do_request(
    method: str,
    url: str,
    extra_headers: list,
    body,
    _hops: int = 0,
):
    """
    Perform one HTTP/1.1 request, following up to MAX_REDIRECTS redirects.
    """
    if _hops > MAX_REDIRECTS:
        raise RuntimeError(
            f"[httpc] Too many redirects (>{MAX_REDIRECTS}) — aborting to avoid loop"
        )

    scheme, host, port, path = parse_url(url)
    sock = open_connection(scheme, host, port)

    try:
        req = build_request(method, host, path, extra_headers, body)
        sock.sendall(req)
        status_code, headers, resp_body = parse_response(sock)
    finally:
        sock.close()

    # Following 3xx redirects
    if status_code in (301, 302, 303, 307, 308):
        location = headers.get("location", "").strip()
        if not location:
            raise RuntimeError(
                f"[httpc] Server returned {status_code} but no Location header"
            )

        # Resolve relative Location
        if location.startswith("http://") or location.startswith("https://"):
            next_url = location
        elif location.startswith("/"):
            next_url = f"{scheme}://{host}:{port}{location}"
        else:
            # Relative path — resolve against current path's directory
            base = path.rsplit("/", 1)[0]
            next_url = f"{scheme}://{host}:{port}{base}/{location}"

        # RFC 7231 section 6.4: 301/302/303 downgrade to GET, drop body
        redirect_method = method
        redirect_body = body
        if status_code in (301, 302, 303):
            redirect_method = "GET"
            redirect_body = None

        return do_request(
            redirect_method,
            next_url,
            extra_headers,
            redirect_body,
            _hops=_hops + 1,
        )

    return status_code, headers, resp_body


# 6. CLI — argparse (stdlib; not what we're replacing)

def main() -> None:
    parser = argparse.ArgumentParser(
        prog="httpc",
        description="Zero-dependency HTTP/1.1 client (socket + ssl only)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  httpc GET  https://api.github.com/zen
  httpc POST http://httpbin.org/post --data '{"key":"val"}' --header "Content-Type: application/json"
  httpc GET  http://127.0.0.1:8765/redirect          # follow 302 to /landed
""",
    )
    parser.add_argument("method", metavar="METHOD", help="HTTP method: GET, POST, ...")
    parser.add_argument("url",    metavar="URL",    help="Target URL (http or https)")
    parser.add_argument(
        "--data", "-d",
        metavar="BODY",
        help="Request body (string). Implies POST if method not given.",
    )
    parser.add_argument(
        "--header", "-H",
        metavar="KEY:VALUE",
        action="append",
        default=[],
        dest="headers",
        help="Extra header(s), repeatable. Example: --header 'Accept: application/json'",
    )
    parser.add_argument(
        "--no-follow",
        action="store_true",
        help="Disable automatic redirect following",
    )
    parser.add_argument(
        "--file", "-F",
        metavar="KEY=FILEPATH",
        help="Upload a file as multipart/form-data. Example: --file upload=image.png. Implies POST.",
    )
    args = parser.parse_args()

    method = args.method.upper()
    body = args.data.encode("utf-8") if args.data else None

    # Handle multipart/form-data file upload
    if args.file:
        if "=" not in args.file:
            sys.exit("[httpc] Malformed --file argument. Expected fieldname=filepath")
        fieldname, filepath = args.file.split("=", 1)
        
        try:
            with open(filepath, "rb") as f:
                file_bytes = f.read()
        except OSError as e:
            sys.exit(f"[httpc] Could not read file {filepath!r}: {e}")
        
        filename = os.path.basename(filepath)
        boundary = os.urandom(16).hex()
        
        # Construct multipart body manually
        lines = [
            f"--{boundary}".encode("utf-8"),
            f'Content-Disposition: form-data; name="{fieldname}"; filename="{filename}"'.encode("utf-8"),
            b"Content-Type: application/octet-stream",
            b"",
            file_bytes,
            f"--{boundary}--".encode("utf-8"),
            b"",
        ]
        body = b"\r\n".join(lines)
        args.headers.append(f"Content-Type: multipart/form-data; boundary={boundary}")
        if method == "GET": # Default to POST if method is just inferred/missing (though our CLI requires METHOD usually)
            method = "POST"

    try:
        if args.no_follow:
            scheme, host, port, path = parse_url(args.url)
            sock = open_connection(scheme, host, port)
            try:
                req = build_request(method, host, path, args.headers, body)
                sock.sendall(req)
                status_code, headers, resp_body = parse_response(sock)
            finally:
                sock.close()
        else:
            status_code, headers, resp_body = do_request(
                method, args.url, args.headers, body
            )
    except RuntimeError as exc:
        sys.exit(str(exc))

    # Output
    # Status line
    print(f"HTTP/1.1 {status_code}")

    # Headers
    for k, v in headers.items():
        print(f"{k}: {v}")

    print()  # blank line between headers and body

    # Body — try UTF-8, fall back to repr for binary content
    try:
        print(resp_body.decode("utf-8"))
    except UnicodeDecodeError:
        print(f"<binary body: {len(resp_body)} bytes>")


if __name__ == "__main__":
    main()