#!/usr/bin/env python3
"""Servidor único (frontend + /api/ → httpserver proxy) pra rodar TUDO numa porta só, sem Docker.
Usa stdlib only: serve o frontend e repassa /api/* pro uvicorn 8891."""
import http.server
import urllib.request
import os

FRONTEND = os.path.join(os.path.dirname(__file__), 'frontend')
API_HOST = 'http://127.0.0.1:8891'

class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=FRONTEND, **kw)

    def do_GET(self):
        if self.path.startswith('/api/'):
            url = API_HOST + self.path
            try:
                r = urllib.request.urlopen(url, timeout=25)
                body = r.read()
                self.send_response(r.status)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except Exception as e:
                self.send_error(502, str(e))
        else:
            super().do_GET()

if __name__ == '__main__':
    import sys
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8892
    http.server.ThreadingHTTPServer(('0.0.0.0', port), Handler).serve_forever()