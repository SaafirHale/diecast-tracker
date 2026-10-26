"""Local dashboard: a stdlib HTTP server bound to 127.0.0.1.

JSON endpoints feed one static page (static/index.html). It is a private
tool, so it never listens beyond localhost.
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from . import db
from .tracker import Tracker

STATIC = Path(__file__).resolve().parent / "static"


class Handler(SimpleHTTPRequestHandler):
    tracker: Tracker = None  # set by serve()
    lock = threading.Lock()  # one sqlite connection, one request at a time

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC), **kwargs)

    def log_message(self, fmt, *args):  # quiet
        pass

    def _json(self, payload, status=200):
        body = json.dumps(payload, default=str).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path
        if not path.startswith("/api/"):
            return super().do_GET()
        with self.lock:
            return self._api_get(path)

    def _api_get(self, path):
        t = self.tracker
        if path == "/api/overview":
            return self._json(t.overview())
        if path == "/api/alerts":
            return self._json(t.alerts())
        if path == "/api/review":
            return self._json(t.review_queue())
        if path == "/api/meta":
            return self._json({
                "demo": db.get_meta(t.conn, "demo") == "1",
                "models": len(t.models),
                "rules": t.rules.__dict__,
                "sources": {k: v.__dict__ for k, v in db.SOURCES.items()},
            })
        m = re.fullmatch(r"/api/model/([A-Za-z0-9._-]+)", path)
        if m:
            mid = m.group(1).upper()
            if mid not in t.by_id:
                return self._json({"error": "unknown model"}, 404)
            row = next(r for r in t.overview() if r["id"] == mid)
            return self._json({"model": row, "history": t.history(mid)})
        return self._json({"error": "not found"}, 404)

    def do_POST(self):
        m = re.fullmatch(r"/api/alerts/(\d+)/dismiss", urlparse(self.path).path)
        if not m:
            return self._json({"error": "not found"}, 404)
        with self.lock:
            self.tracker.dismiss_alert(int(m.group(1)))
        return self._json({"ok": True})


def serve(db_path, port=8064):
    tracker = Tracker(db_path)
    removed = tracker.purge()
    tracker.conn.close()
    # Threaded so an idle browser pre-connect cannot block the server; the
    # handler lock serialises every use of the single connection.
    tracker.conn = sqlite3.connect(str(db_path), check_same_thread=False)
    tracker.conn.row_factory = sqlite3.Row
    tracker.conn.execute("PRAGMA foreign_keys = ON")
    Handler.tracker = tracker
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"Dashboard on http://127.0.0.1:{port}  (db: {db_path}; purged {removed} expired rows)", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
