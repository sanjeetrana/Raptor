"""
server.py — Zero-dependency REST API & Visual Dashboard Server for Proofline.
Python standard library only (http.server, json, socketserver).
"""
from __future__ import annotations

import http.server
import json
import os
import socketserver
import urllib.parse
import webbrowser
from pathlib import Path
from typing import Optional


class ProoflineAPIHandler(http.server.BaseHTTPRequestHandler):
    """REST API Handler providing programmatic verification endpoints."""
    
    server_version = "Proofline-ZeroDep/12.0.0"
    
    def _send_json(self, data: dict, status_code: int = 200) -> None:
        payload = json.dumps(data, indent=2, default=str).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(payload)

    def _send_html(self, html_content: str, status_code: int = 200) -> None:
        payload = html_content.encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self) -> None:
        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path

        if path == "/api/health":
            self._send_json({
                "status": "healthy",
                "service": "Proofline Verification Gate",
                "version": "12.0.0",
                "zero_dependency": True,
                "engine": "Python AST Heuristic Gate"
            })
            return

        if path == "/api/rules":
            rules = [
                {"id": 1, "name": "Public function signature changed", "severity": "HIGH"},
                {"id": 2, "name": "Exception behavior modified", "severity": "MEDIUM"},
                {"id": 3, "name": "Broad exception handler added", "severity": "HIGH"},
                {"id": 4, "name": "Security-sensitive boundary modified", "severity": "HIGH"},
                {"id": 5, "name": "HTTP public route changed/affected", "severity": "MEDIUM"},
                {"id": 6, "name": "No statically associated test found", "severity": "MEDIUM"},
                {"id": 7, "name": "Associated test unchanged despite logic change", "severity": "MEDIUM"},
                {"id": 8, "name": "Import/dependency graph edge changed", "severity": "MEDIUM"},
                {"id": 9, "name": "Docstring not updated despite logic change (Doc Rot)", "severity": "MEDIUM"},
                {"id": 10, "name": "High cyclomatic complexity with insufficient tests", "severity": "HIGH"},
                {"id": 11, "name": "Orphan code added (0 static callers)", "severity": "MEDIUM"},
            ]
            self._send_json({"rules": rules, "total": len(rules)})
            return

        # Serve static report file if requested or root
        if path in ("/", "/index.html", "/report.html", "/proofline_audit_report.html"):
            for candidate in ("report.html", "public/index.html", "proofline_audit_report.html"):
                p = Path(candidate)
                if p.exists():
                    self._send_html(p.read_text(encoding="utf-8"))
                    return
            
            welcome_html = "<html><body><h1>Proofline REST API Server</h1><p>Running.</p></body></html>"
            self._send_html(welcome_html)
            return

        self._send_json({"error": "Endpoint not found", "path": path}, 404)

    def do_POST(self) -> None:
        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path

        if path == "/api/analyze":
            try:
                content_length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(content_length).decode("utf-8")
                req_data = json.loads(body) if body else {}
            except Exception as e:
                self._send_json({"error": f"Invalid JSON body: {str(e)}"}, 400)
                return

            before_dir = req_data.get("before_dir")
            after_dir = req_data.get("after_dir")

            if not before_dir or not after_dir:
                self._send_json({"error": "Missing required fields: 'before_dir' and 'after_dir'"}, 400)
                return

            if not Path(before_dir).exists() or not Path(after_dir).exists():
                self._send_json({"error": "Specified before_dir or after_dir does not exist on server"}, 404)
                return

            try:
                from .core import analyze_directories
                eg = analyze_directories(before_dir, after_dir)
                self._send_json(eg.to_dict(), 200)
            except Exception as e:
                self._send_json({"error": f"Analysis failed: {str(e)}"}, 500)
            return

        self._send_json({"error": "Endpoint not found", "path": path}, 404)

    def log_message(self, format: str, *args) -> None:
        pass


def serve_dashboard(port: int = 8080) -> bool:
    """Serves proofline_audit_report.html natively using http.server (compatible with test F29)."""
    report_file = "proofline_audit_report.html"
    if not Path(report_file).exists():
        print(f"Error: {report_file} not found. Please run 'proofline analyze' first.")
        return False

    Handler = http.server.SimpleHTTPRequestHandler

    try:
        with socketserver.TCPServer(("", port), Handler) as httpd:
            print(f"Proofline Dashboard serving at http://localhost:{port}/{report_file}")
            print("Press Ctrl+C to stop the server.")
            webbrowser.open_new_tab(f"http://localhost:{port}/{report_file}")
            try:
                httpd.serve_forever()
            except KeyboardInterrupt:
                return True
    except OSError as e:
        if e.errno in (98, 10048):
            return serve_dashboard(port + 1)
        return False
    return True


def serve_api_server(port: int = 8080, host: str = "127.0.0.1", open_browser: bool = True) -> bool:
    """Start the Proofline REST API and dashboard server."""
    Handler = ProoflineAPIHandler
    try:
        with socketserver.TCPServer((host, port), Handler) as httpd:
            url = f"http://{host}:{port}/"
            print(f"  [Proofline Server] running at: {url}")
            if open_browser:
                try:
                    webbrowser.open(url)
                except Exception:
                    pass
            try:
                httpd.serve_forever()
            except KeyboardInterrupt:
                return True
    except OSError as e:
        if e.errno in (98, 10048):
            return serve_api_server(port + 1, host, open_browser)
        return False
    return True
