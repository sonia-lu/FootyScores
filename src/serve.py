"""Step 3, SERVE: a small local API that answers each endpoint with its expected response."""

import html
import json
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from config import FAVICON_PNG, HTML_CONTENT_TYPE, JSON_CONTENT_TYPE


def endpoint_links(endpoints: list) -> bytes:
    """HTML page that lists every endpoint as a link (shown when a browser opens /match)."""
    rows = []
    for item in endpoints:
        path = html.escape(item["endpoint"])
        kickoff = html.escape(item["kickoff"])
        home = html.escape(item["teams"]["home"])
        away = html.escape(item["teams"]["away"])
        rows.append(f'<li><a href="{path}">{path}</a> {kickoff} &middot; {home} v {away}</li>')
    rows_html = "\n".join(rows)

    page = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Match endpoints</title>
<style>
  body {{ font-family: system-ui, sans-serif; margin: 2rem; line-height: 1.6; }}
  a {{ font-family: ui-monospace, monospace; margin-right: 0.5rem; }}
</style>
</head>
<body>
<h1>Match endpoints ({len(endpoints)})</h1>
<ol>
{rows_html}
</ol>
</body>
</html>
"""
    return page.encode()


def make_server(endpoints: list, reference_dir: Path, host: str, port: int) -> ThreadingHTTPServer:
    """Create the API server (it starts answering once serve_forever() is called).

    GET /match            list of all endpoints (JSON, or HTML links in a browser)
    GET /match/<id>       expected response of that match
    GET /favicon.ico      small football icon for the browser tab
    anything else         404 with {"error": "..."}
    """
    # Which file answers which path, e.g. "/match/<id>" -> <reference_dir>/match/<id>.json
    response_files = {}
    for item in endpoints:
        response_files[item["endpoint"]] = reference_dir / item["response"]

    class Handler(BaseHTTPRequestHandler):
        """Called by the web server once for every incoming request."""

        def do_GET(self) -> None:
            # Request path without "?query", URL escapes or a trailing "/".
            path = urllib.parse.urlsplit(self.path).path
            path = urllib.parse.unquote(path).rstrip("/")
            browser_asks_for_html = "text/html" in self.headers.get("Accept", "")

            if path == "/match" and browser_asks_for_html:
                self.reply(200, endpoint_links(endpoints), HTML_CONTENT_TYPE)
            elif path == "/match":
                all_paths = [item["endpoint"] for item in endpoints]
                self.reply(200, json.dumps(all_paths, indent=2).encode())
            elif path in response_files:
                self.reply(200, response_files[path].read_bytes())
            elif path == "/favicon.ico":
                self.reply(200, FAVICON_PNG, "image/png")
            else:
                self.reply(404, json.dumps({"error": f"no match at {path}"}).encode())

        def reply(self, status: int, body: bytes, content_type: str = JSON_CONTENT_TYPE) -> None:
            """Send an HTTP response with this status code, body and content type."""
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return ThreadingHTTPServer((host, port), Handler)


def serve(endpoints: list, reference_dir: Path, host: str, port: int) -> None:
    """Run the API until Ctrl+C is pressed."""
    try:
        server = make_server(endpoints, reference_dir, host, port)
    except OSError as error:
        sys.exit(f"Cannot start the API on {host}:{port}: {error.strerror or error}")

    base_url = f"http://{host}:{port}"
    for item in endpoints:
        print(f"{item['method']} {base_url}{item['endpoint']}")
    print(f"\nServing {len(endpoints)} endpoints on {base_url} (Ctrl+C to stop)", flush=True)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass  # Ctrl+C: stop quietly
    finally:
        server.server_close()
