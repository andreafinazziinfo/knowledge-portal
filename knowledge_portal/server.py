"""
Knowledge Portal Standalone Threading HTTP & SSE Server
Serves the portal web application, static vendor assets, and provides REST/SSE APIs.
Zero external runtime dependencies (Python standard library only).
"""

import hmac
import json
import mimetypes
import os
import shutil
import time
import urllib.parse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

mimetypes.add_type("application/wasm", ".wasm")

_DENY_PARTS = {".git", ".hg", ".svn", "__pycache__", "frozen"}
_DENY_SUFFIXES = (".key", ".pem", ".p12", ".pfx", ".sqlite", ".db")
_PREV_CPU_SAMPLE: tuple[int, int] | None = None


def safe_resolve_under(base_dir: Path, rel_path: str) -> Path | None:
    """Resolve rel_path strictly inside base_dir, rejecting traversal and sensitive files."""
    if not rel_path or "\x00" in rel_path:
        return None
    cleaned = urllib.parse.unquote(rel_path).lstrip("/\\")
    if not cleaned:
        return None
    parts = Path(cleaned).parts
    for part in parts:
        if part in ("..", "") or part in _DENY_PARTS or part.startswith(".env"):
            return None
    if cleaned.lower().endswith(_DENY_SUFFIXES):
        return None
    try:
        base_resolved = base_dir.resolve()
        candidate = (base_resolved / cleaned).resolve()
        if not candidate.is_relative_to(base_resolved):
            return None
        return candidate
    except (OSError, ValueError):
        return None


def _sample_cpu_pct() -> float:
    global _PREV_CPU_SAMPLE
    cpu_pct = 0.0
    try:
        with open("/proc/stat", "r", encoding="utf-8") as f:
            parts = [int(x) for x in f.readline().split()[1:8]]
        idle = parts[3] + parts[4]
        total = sum(parts)
        if _PREV_CPU_SAMPLE is not None:
            prev_idle, prev_total = _PREV_CPU_SAMPLE
            dt = total - prev_total
            di = idle - prev_idle
            if dt > 0:
                cpu_pct = round(100.0 * (1.0 - di / dt), 1)
        _PREV_CPU_SAMPLE = (idle, total)
    except OSError:
        pass
    return cpu_pct


def get_template_dir() -> Path:
    candidates = [
        Path(__file__).resolve().parent.parent / "template",
        Path.cwd() / "template",
        Path("/app/template"),
        Path(__file__).resolve().parent / "template",
    ]
    for c in candidates:
        if c.exists() and (c / "dashboard.html").exists():
            return c
    return candidates[0]


class PortalRequestHandler(SimpleHTTPRequestHandler):
    extensions_map = {**SimpleHTTPRequestHandler.extensions_map, ".wasm": "application/wasm"}
    template_dir = get_template_dir()
    project_dir = Path.cwd()

    def log_message(self, format: str, *args) -> None:
        if os.environ.get("PORTAL_ACCESS_LOG", "1") == "1":
            entry = {
                "ts": round(time.time(), 3),
                "client": self.client_address[0] if self.client_address else "-",
                "method": getattr(self, "command", "-"),
                "path": getattr(self, "path", "-"),
                "msg": format % args if args else format,
            }
            print(json.dumps(entry), flush=True)

    def send_security_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "SAMEORIGIN")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")

    def send_cors_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Portal-Token")
        self.send_security_headers()

    def is_mutation_authorized(self) -> tuple[bool, int, str]:
        if os.environ.get("PORTAL_READ_ONLY", "0") == "1":
            return False, 403, "Portal is running in read-only mode"
        expected = os.environ.get("PORTAL_API_TOKEN", "")
        if expected:
            token = self.headers.get("X-Portal-Token", "")
            if not token:
                auth = self.headers.get("Authorization", "")
                if auth.startswith("Bearer "):
                    token = auth[7:].strip()
            if not token or not hmac.compare_digest(token, expected):
                return False, 401, "Unauthorized"
        return True, 200, "OK"

    def do_HEAD(self) -> None:
        self.do_GET()

    def do_OPTIONS(self) -> None:
        self.send_response(200)
        self.send_cors_headers()
        self.end_headers()

    def do_POST(self) -> None:
        ok, code, msg = self.is_mutation_authorized()
        if not ok:
            self.send_error(code, msg)
            return
        self.send_error(404, "POST endpoint not supported in standalone mode")

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        if path.startswith("/api/"):
            self.handle_api(path, query)
            return

        if path in ("/llms.txt", "/llms-full.txt"):
            fname = path.lstrip("/")
            candidate = self.template_dir / fname
            if not candidate.exists():
                from knowledge_portal.generators.llms_txt import generate_llms_manifests
                generate_llms_manifests(self.project_dir, self.template_dir / "data", self.template_dir)
            if candidate.exists() and candidate.is_file():
                data = candidate.read_bytes()
                self.send_response(200)
                self.send_cors_headers()
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return

        if path == "/" or path == "/index.html":
            path = "/dashboard.html"

        target = safe_resolve_under(self.template_dir, path)
        if target and target.exists() and target.is_file():
            self.serve_file(target)
            return

        self.send_error(404, f"File not found: {path}")

    def serve_file(self, file_path: Path) -> None:
        content_type = self.guess_type(str(file_path))
        try:
            data = file_path.read_bytes()
            self.send_response(200)
            self.send_cors_headers()
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except Exception as e:
            self.send_error(500, f"Error reading file: {e}")

    def handle_api(self, path: str, query: dict) -> None:
        if path == "/api/stats":
            data_file = self.template_dir / "data" / "graph.json"
            if data_file.exists():
                try:
                    gdata = json.loads(data_file.read_text(encoding="utf-8"))
                    stats = {
                        "total_files": len({n.get("path") for n in gdata.get("nodes", [])}),
                        "total_words": 10000,
                        "total_nodes": len(gdata.get("nodes", [])),
                        "total_edges": len(gdata.get("edges", [])),
                        "communities": len({n.get("community") for n in gdata.get("nodes", [])}),
                        "orphan_count": 0,
                        "top_connected": [],
                    }
                    self.send_json(stats)
                    return
                except Exception:
                    pass
            self.send_json({
                "total_files": 0, "total_words": 0, "total_nodes": 0, "total_edges": 0,
                "communities": 0, "orphan_count": 0, "top_connected": [],
            })

        elif path == "/api/tree":
            scope = query.get("scope", ["docs"])[0]
            allowed_exts = {".py", ".ts", ".tsx", ".js", ".jsx", ".vue", ".sql", ".yml", ".yaml", ".json", ".md"} if scope == "code" else {".md"}
            tree = []
            for item in sorted(self.project_dir.iterdir(), key=lambda x: x.name):
                if item.name.startswith(".") or item.name in ("venv", "__pycache__", "node_modules", "dist", "build", "frozen"):
                    continue
                if item.is_dir():
                    children = []
                    for child in sorted(item.rglob("*")):
                        if not child.is_file() or child.suffix.lower() not in allowed_exts:
                            continue
                        if any(p in _DENY_PARTS or p.startswith(".") for p in child.parts):
                            continue
                        children.append({
                            "name": str(child.relative_to(item)).replace("\\", "/") if scope == "code" else child.name,
                            "type": "file",
                            "path": str(child.relative_to(self.project_dir)).replace("\\", "/"),
                        })
                        if len(children) >= 300:
                            break
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
                self.wfile.write(b'data: {"status": "connected"}\n\n')
                self.wfile.flush()
                for _ in range(30):
                    time.sleep(2.0)
                    self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
            except Exception:
                pass

        elif path == "/api/telemetry":
            disk_pct, disk_free_gb = 0.0, 0.0
            try:
                du = shutil.disk_usage(str(self.project_dir))
                if du.total > 0:
                    disk_pct = round(100.0 * du.used / du.total, 1)
                    disk_free_gb = round(du.free / (1024 ** 3), 1)
            except Exception:
                pass
            mem_total_mb, mem_used_mb, mem_pct = 0, 0, 0.0
            try:
                info: dict[str, int] = {}
                with open("/proc/meminfo", "r", encoding="utf-8") as f:
                    for line in f:
                        k, v = line.split(":", 1)
                        info[k.strip()] = int(v.strip().split()[0])
                tk = info.get("MemTotal", 0)
                ak = info.get("MemAvailable", info.get("MemFree", 0))
                if tk > 0:
                    mem_total_mb = round(tk / 1024)
                    mem_used_mb = round((tk - ak) / 1024)
                    mem_pct = round(100.0 * (tk - ak) / tk, 1)
            except Exception:
                pass
            self.send_json({
                "timestamp": time.time(),
                "mode": "standalone",
                "host": {
                    "cpu_pct": _sample_cpu_pct(),
                    "mem_pct": mem_pct,
                    "mem_used_mb": mem_used_mb,
                    "mem_total_mb": mem_total_mb,
                    "disk_pct": disk_pct,
                    "disk_free_gb": disk_free_gb,
                    "uptime_sec": 0,
                },
                "watcher": {"active": False, "last_sync": 0.0, "domains": {}},
                "rebuild": {"rebuilding": False, "phase": "idle", "processed": 0, "total": 4, "percent": 0, "message": "Idle"},
                "scan": {"ast_scan": "Static", "llm_scan": "Static"},
                "backend": {"reachable": False},
            })

        elif path == "/api/rebuild/status":
            self.send_json({"rebuilding": False, "phase": "idle", "processed": 0, "total": 4, "percent": 0, "message": "Idle"})

        elif path == "/api/search":
            from knowledge_portal.indexer.fts_engine import FtsSearchEngine
            q = query.get("q", [""])[0]
            engine = FtsSearchEngine(self.template_dir / "data")
            self.send_json(engine.search(q, limit=30))

        elif path == "/api/context-pack":
            from knowledge_portal.mcp_server import PortalMcpEngine
            q = query.get("q", [""])[0]
            max_tok = int(query.get("max_tokens", ["4000"])[0] or 4000)
            eng = PortalMcpEngine(self.project_dir, self.template_dir / "data")
            self.send_json(eng.context_pack(q, max_tokens=max_tok))

        elif path == "/api/impact":
            from knowledge_portal.mcp_server import PortalMcpEngine
            target = query.get("target", [""])[0]
            depth = int(query.get("depth", ["3"])[0] or 3)
            eng = PortalMcpEngine(self.project_dir, self.template_dir / "data")
            self.send_json(eng.impact(target, max_depth=depth))

        elif path == "/api/health-audit":
            from knowledge_portal.mcp_server import PortalMcpEngine
            eng = PortalMcpEngine(self.project_dir, self.template_dir / "data")
            self.send_json(eng.health_audit())

        elif path == "/api/arch-diff":
            from knowledge_portal.generators.arch_health import generate_arch_diff
            diff_file = self.template_dir / "data" / "arch-diff.json"
            if diff_file.exists():
                self.send_json(json.loads(diff_file.read_text(encoding="utf-8")))
            else:
                self.send_json(generate_arch_diff(self.template_dir / "data"))

        elif path == "/api/file":
            filepath = query.get("path", [""])[0]
            target = safe_resolve_under(self.project_dir, filepath)
            if target and target.exists() and target.is_file():
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

    def send_json(self, data: object) -> None:
        content = json.dumps(data, indent=2).encode("utf-8")
        self.send_response(200)
        self.send_cors_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)


def run_server(host: str = "0.0.0.0", port: int = 8000, template_dir: str | None = None, project_dir: str | None = None) -> None:
    PortalRequestHandler.template_dir = Path(template_dir) if template_dir else get_template_dir()
    if project_dir:
        PortalRequestHandler.project_dir = Path(project_dir)

    _sample_cpu_pct()
    server = ThreadingHTTPServer((host, port), PortalRequestHandler)
    print(f"🚀 Knowledge Portal running on http://{host}:{port}/dashboard.html", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping server...")
        server.server_close()
