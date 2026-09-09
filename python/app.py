#!/usr/bin/env python3
"""
Tiny stdlib-only demo server. Serves the shared frontend from ../shared/public and
proxies /api/ask, /api/upload, /api/corpus, /api/document to the deployed AWS backend
(API_URL). No Flask, no deps.

Usage:
    API_URL=https://<api-id>.execute-api.<region>.amazonaws.com python3 app.py
(or put API_URL=... in a .env file next to this script)
"""
import json
import mimetypes
import os
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(os.environ.get("PORT", 5001))
HERE = os.path.dirname(os.path.abspath(__file__))
PUBLIC_DIR = os.path.abspath(os.path.join(HERE, "..", "shared", "public"))

# The dashboard's Backend selector calls whichever port you didn't load the page
# from, so CORS has to allow that cross-port request - but allowing it from *any*
# origin would let any website open in your browser silently call this server (which
# holds your API_KEY) while it's running. Scope it to just the two demo ports.
ALLOWED_ORIGINS = {
    "http://localhost:5001", "http://localhost:5002",
    "http://127.0.0.1:5001", "http://127.0.0.1:5002",
}

# routes proxied 1:1 to the AWS API Gateway backend
PROXY_ROUTES = {
    ("POST", "/api/ask"): ("POST", "/ask"),
    ("POST", "/api/upload"): ("POST", "/upload"),
    ("GET", "/api/corpus"): ("GET", "/corpus"),
    ("GET", "/api/document"): ("GET", "/document"),
}


def load_dotenv():
    path = os.path.join(HERE, ".env")
    if not os.path.exists(path):
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


load_dotenv()
API_URL = os.environ.get("API_URL", "").rstrip("/")
API_KEY = os.environ.get("API_KEY", "")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f"[python:{PORT}] {self.address_string()} - {fmt % args}")

    def _send_json(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self._send_cors_headers()
        self.end_headers()
        self.wfile.write(body)

    def _send_cors_headers(self):
        origin = self.headers.get("Origin", "")
        if origin in ALLOWED_ORIGINS:
            self.send_header("Access-Control-Allow-Origin", origin)
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def do_OPTIONS(self):
        self.send_response(204)
        self._send_cors_headers()
        self.end_headers()

    def do_GET(self):
        path, _, query = self.path.partition("?")
        if path == "/api/info":
            self._send_json(200, {"runtime": "python", "port": PORT})
            return
        if ("GET", path) in PROXY_ROUTES:
            self._proxy("GET", path, query)
            return
        self._serve_static()

    def do_POST(self):
        if ("POST", self.path) in PROXY_ROUTES:
            self._proxy("POST", self.path)
            return
        self._send_json(404, {"error": "not found"})

    def _serve_static(self):
        rel_path = self.path.split("?", 1)[0]
        if rel_path == "/":
            rel_path = "/index.html"
        full_path = os.path.abspath(os.path.join(PUBLIC_DIR, rel_path.lstrip("/")))
        if not full_path.startswith(PUBLIC_DIR) or not os.path.isfile(full_path):
            self._send_json(404, {"error": "not found"})
            return
        content_type = mimetypes.guess_type(full_path)[0] or "application/octet-stream"
        with open(full_path, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _proxy(self, method, local_path, query=""):
        if not API_URL:
            self._send_json(500, {"error": "API_URL is not set. See .env.example."})
            return
        _, upstream_path = PROXY_ROUTES[(method, local_path)]
        if query:
            upstream_path += "?" + query
        body = None
        if method == "POST":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)

        req = urllib.request.Request(
            API_URL + upstream_path, data=body, method=method,
            headers={"Content-Type": "application/json", "X-API-Key": API_KEY},
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                self._send_json(resp.status, json.loads(resp.read()))
        except urllib.error.HTTPError as e:
            self._send_json(e.code, json.loads(e.read() or b"{}"))
        except urllib.error.URLError as e:
            self._send_json(502, {"error": f"could not reach API_URL: {e.reason}"})


if __name__ == "__main__":
    if not API_URL:
        print("Warning: API_URL is not set. Copy .env.example to .env and set it after deploying.")
    if not API_KEY:
        print("Warning: API_KEY is not set. AWS will reject every request with 401 until it matches what deploy.py provisioned.")
    print(f"Python demo app on http://localhost:{PORT}")
    ThreadingHTTPServer(("", PORT), Handler).serve_forever()
