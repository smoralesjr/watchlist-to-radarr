import threading
import json
import sys
import time
from http.server import BaseHTTPRequestHandler, HTTPServer


class RadarrHandler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, data):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def do_GET(self):
        if self.path.startswith("/api/v3/qualityprofile"):
            self._send(200, [{"id": 1, "name": "HD-1080p"}])
        elif self.path.startswith("/api/v3/rootfolder"):
            self._send(200, [{"id": 1, "path": "/movies"}])
        elif self.path.startswith("/api/v3/movie/lookup"):
            self._send(200, [
                {"tmdbId": 438631, "title": "Dune: Part Two", "year": 2024, "isAvailable": True},
                {"tmdbId": 693134, "title": "Dune: Part Two", "year": 2023, "isAvailable": True},
            ])
        elif self.path.startswith("/api/v3/movie"):
            self._send(200, [])
        else:
            self._send(404, {})

    def do_POST(self):
        self._send(201, {"tmdbId": 438631, "title": "Dune: Part Two", "year": 2024})


class LetterboxdHandler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        feed = (
            '<?xml version="1.0"?>'
            '<feed xmlns="http://www.w3.org/2005/Atom">'
            "<entry><title>Dune: Part Two, 2024</title>"
            '<link href="https://letterboxd.com/film/dune-part-two/"/></entry>'
            "<entry><title>Some Obscure Film, 1987</title>"
            '<link href="https://letterboxd.com/film/some-obscure-film/"/></entry>'
            "</feed>"
        )
        self.send_response(200)
        self.send_header("Content-Type", "application/atom+xml")
        self.end_headers()
        self.wfile.write(feed.encode())


HTTPServer.allow_reuse_address = True
for port, handler in ((7878, RadarrHandler), (8899, LetterboxdHandler)):
    srv = HTTPServer(("127.0.0.1", port), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()

sys.path.insert(0, "/workspace/watchlist-to-radarr")
import app as watchlist_app  # noqa: E402

watchlist_app.CONFIG_PATH = watchlist_app.APP_DIR / "config.test.json"
watchlist_app.app.run(host="127.0.0.1", port=5001)
