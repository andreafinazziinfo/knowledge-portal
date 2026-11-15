"""
Knowledge Portal Standalone Threading HTTP & SSE Server
Serves the portal web application, static vendor assets, and provides REST/SSE APIs.
Zero external runtime dependencies (Python standard library only).
"""

import json
import time
import urllib.parse
from pathlib import Path
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler

class PortalRequestHandler(SimpleHTTPRequestHandler):
    template_dir = Path(__file__).resolve().parent.parent / "template"
    project_dir = Path.cwd()

    def send_cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def do_HEAD(self):
        self.do_GET()

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_cors_headers()
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        if path.startswith("/api/"):
            self.handle_api(path, query)
            return

        # Serve dashboard as root index
        if path == "/" or path == "/index.html":
            path = "/dashboard.html"

        # Check in template_dir first
        target = self.template_dir / path.lstrip("/")
        if target.exists() and target.is_file():
            return self.serve_file(target)

        # Check in project_dir
        target = self.project_dir / path.lstrip("/")
        if target.exists() and target.is_file():
            return self.serve_file(target)

        self.send_error(404, f"File not found: {path}")

    def serve_file(self, file_path: Path):
        content_type = self.guess_type(str(file_path))
        try:
            with open(file_path, "rb") as f:
                data = f.read()
            self.send_response(200)
            self.send_cors_headers()
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except Exception as e:
            self.send_error(500, f"Error reading file: {e}")

    def handle_api(self, path: str, query: dict):
        if path == "/api/stats":
            data_file = self.template_dir / "data" / "graph.json"
            if data_file.exists():
                try:
                    with open(data_file, "r", encoding="utf-8") as f:
                        gdata = json.load(f)
                    stats = {
                        "total_files": len(set(n.get("path") for n in gdata.get("nodes", []))),
                        "total_words": 10000,
                        "total_nodes": len(gdata.get("nodes", [])),
                        "total_edges": len(gdata.get("edges", [])),
                        "communities": len(set(n.get("community") for n in gdata.get("nodes", []))),
                        "orphan_count": 0,
                        "top_connected": []
                    }
                    return self.send_json(stats)
                except Exception:
                    pass
            self.send_json({"total_files": 0, "total_words": 0, "total_nodes": 0, "total_edges": 0, "communities": 0, "orphan_count": 0, "top_connected": []})

        elif path == "/api/tree":
            tree = []
            for item in self.project_dir.iterdir():
                if item.name.startswith(".") or item.name in ["venv", "__pycache__", "node_modules"]:
                    continue
                if item.is_dir():
                    children = []
                    for child in item.rglob("*.md"):
                        children.append({
                            "name": child.name,
                            "type": "file",
                            "path": str(child.relative_to(self.project_dir)).replace("\\", "/")
                        })
                    if children:
                        tree.append({"name": item.name, "type": "directory", "children": children})
            self.send_json(tree)

        elif path == "/api/live-events":
            self.send_response(200)
            self.send_cors_headers()
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            try:
                self.wfile.write(b"data: {\"status\": \"connected\"}\n\n")
                self.wfile.flush()
                for _ in range(30):
                    time.sleep(2.0)
                    self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
            except Exception:
                pass

        elif path == "/api/file":
            filepath = query.get("path", [""])[0]
            target = self.project_dir / filepath
            if target.exists() and target.is_file():
                try:
                    text = target.read_text(encoding="utf-8", errors="replace")
                    self.send_json({"content": text, "path": filepath})
                    return
                except Exception as e:
                    self.send_error(500, str(e))
                    return
            self.send_error(404, "File not found")

        else:
            self.send_error(404, "API endpoint not found")

    def send_json(self, data):
        content = json.dumps(data, indent=2).encode("utf-8")
        self.send_response(200)
        self.send_cors_headers()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

def run_server(host="0.0.0.0", port=8000, template_dir=None, project_dir=None):
    if template_dir:
        PortalRequestHandler.template_dir = Path(template_dir)
    if project_dir:
        PortalRequestHandler.project_dir = Path(project_dir)

    server = ThreadingHTTPServer((host, port), PortalRequestHandler)
    print(f"🚀 Knowledge Portal running on http://{host}:{port}/dashboard.html")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping server...")
        server.server_close()
