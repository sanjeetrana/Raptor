"""
test_server.py — Local fixture server for httpc redirect testing.

Runs on 127.0.0.1:8765.  Endpoints:
  GET /redirect  → 302 Location: /landed
  GET /landed    → 200 "You landed!\n"
  POST /echo     → 200, echoes the request body back
  GET /chunked   → 200, Transfer-Encoding: chunked body (3 chunks)

Usage (two terminals):
  terminal 1:  python3 tests/test_server.py
  terminal 2:  python3 src/httpc.py GET http://127.0.0.1:8765/redirect

stdlib only: socket, threading — no http.server, no frameworks.
"""

import socket
import threading
import sys

HOST = "127.0.0.1"
PORT = 8765


# Raw response helpers 

def _response(status: str, headers: dict, body: bytes) -> bytes:
    header_lines = "\r\n".join(f"{k}: {v}" for k, v in headers.items())
    head = f"HTTP/1.1 {status}\r\n{header_lines}\r\nConnection: close\r\n\r\n"
    return head.encode("latin-1") + body


def _chunked_response(status: str, extra_headers: dict, chunks: list) -> bytes:
    """Build a Transfer-Encoding: chunked response from a list of byte strings."""
    headers = {"Transfer-Encoding": "chunked", "Connection": "close"}
    headers.update(extra_headers)
    header_lines = "\r\n".join(f"{k}: {v}" for k, v in headers.items())
    head = f"HTTP/1.1 {status}\r\n{header_lines}\r\n\r\n".encode("latin-1")

    body = b""
    for chunk in chunks:
        data = chunk if isinstance(chunk, bytes) else chunk.encode()
        body += f"{len(data):x}\r\n".encode() + data + b"\r\n"
    body += b"0\r\n\r\n"   # terminating chunk

    return head + body


# Request parser 

def _parse_request(raw: bytes):
    """
    Parse raw HTTP request bytes into (method, path, headers, body).
    Returns None if the request is incomplete / malformed.
    """
    if b"\r\n\r\n" not in raw:
        return None, None, {}, b""

    header_block, body = raw.split(b"\r\n\r\n", 1)
    lines = header_block.decode("latin-1").split("\r\n")
    request_line = lines[0]
    parts = request_line.split(" ")
    if len(parts) < 2:
        return None, None, {}, b""

    method, path = parts[0], parts[1]
    headers = {}
    for line in lines[1:]:
        if ":" in line:
            k, _, v = line.partition(":")
            headers[k.strip().lower()] = v.strip()

    # Read body up to Content-Length
    cl = headers.get("content-length", "0")
    try:
        length = int(cl)
    except ValueError:
        length = 0
    return method, path, headers, body[:length]


# Route handlers

def handle_redirect(_method, _path, _headers, _body):
    return _response(
        "302 Found",
        {"Location": "/landed", "Content-Length": "0"},
        b"",
    )


def handle_landed(_method, _path, _headers, _body):
    body = b"You landed!\n"
    return _response(
        "200 OK",
        {"Content-Type": "text/plain", "Content-Length": str(len(body))},
        body,
    )


def handle_echo(method, _path, _headers, body):
    if method != "POST":
        err = b"POST only\n"
        return _response(
            "405 Method Not Allowed",
            {"Content-Length": str(len(err))},
            err,
        )
    return _response(
        "200 OK",
        {"Content-Type": "text/plain", "Content-Length": str(len(body))},
        body,
    )


def handle_chunked(_method, _path, _headers, _body):
    return _chunked_response(
        "200 OK",
        {"Content-Type": "text/plain"},
        ["Hello, ", "chunked ", "world!\n"],
    )


def handle_not_found(_method, path, _headers, _body):
    body = f"404 Not Found: {path}\n".encode()
    return _response(
        "404 Not Found",
        {"Content-Type": "text/plain", "Content-Length": str(len(body))},
        body,
    )


def handle_upload(method, _path, headers, body):
    if method != "POST":
        err = b"POST only\n"
        return _response("405 Method Not Allowed", {"Content-Length": str(len(err))}, err)
    
    content_type = headers.get("content-type", "")
    if "multipart/form-data" not in content_type:
        err = b"Expected multipart/form-data\n"
        return _response("400 Bad Request", {"Content-Length": str(len(err))}, err)

    resp_body = f"200 OK: Received {len(body)} bytes of multipart data\n".encode()
    return _response(
        "200 OK",
        {"Content-Type": "text/plain", "Content-Length": str(len(resp_body))},
        resp_body,
    )


ROUTES = {
    "/redirect": handle_redirect,
    "/landed":   handle_landed,
    "/echo":     handle_echo,
    "/chunked":  handle_chunked,
    "/upload":   handle_upload,
}


# Connection handler 

def handle_connection(conn: socket.socket, addr):
    try:
        raw = b""
        while b"\r\n\r\n" not in raw:
            chunk = conn.recv(4096)
            if not chunk:
                break
            raw += chunk

        method, path, headers, body = _parse_request(raw)

        if method is None:
            conn.close()
            return

        handler = ROUTES.get(path, handle_not_found)
        resp = handler(method, path, headers, body)
        conn.sendall(resp)
        print(f"  {method} {path} — served to {addr[0]}:{addr[1]}")
    except Exception as exc:
        print(f"  [error] {exc}", file=sys.stderr)
    finally:
        conn.close()


# Main server loop 

def serve():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((HOST, PORT))
    server.listen(10)
    print(f"httpc test server listening on http://{HOST}:{PORT}")
    print("  Routes:")
    print("    GET  /redirect -> 302 -> /landed")
    print("    GET  /landed   -> 200 'You landed!'")
    print("    POST /echo     -> 200 echoes body")
    print("    GET  /chunked  -> 200 chunked response")
    print("Press Ctrl+C to stop.\n")

    try:
        while True:
            conn, addr = server.accept()
            t = threading.Thread(target=handle_connection, args=(conn, addr), daemon=True)
            t.start()
    except KeyboardInterrupt:
        print("\nShutting down.")
    finally:
        server.close()


if __name__ == "__main__":
    serve()
