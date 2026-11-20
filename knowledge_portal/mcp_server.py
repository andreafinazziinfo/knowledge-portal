"""
Knowledge Portal Zero-Dependency MCP (Model Context Protocol) Server & Query Engine.
Implements JSON-RPC 2.0 over stdio (protocolVersion 2024-11-05) using Python stdlib only.
"""

from __future__ import annotations

import http.client
import json
import sys
import urllib.parse
from pathlib import Path
from typing import Any

from knowledge_portal.server import safe_resolve_under

PROTOCOL_VERSION = "2024-11-05"
SERVER_INFO = {"name": "knowledge-portal-mcp", "version": "1.0.0"}


class PortalMcpEngine:
    """Shared read-only query engine over portal JSON artifacts and live /api/telemetry."""

    def __init__(
        self,
        project_dir: Path,
        data_dir: Path,
        portal_url: str = "http://127.0.0.1:8000",
    ) -> None:
        self.project_dir = project_dir.resolve()
        self.data_dir = data_dir.resolve()
        self.portal_url = portal_url.rstrip("/")
        self._cache: dict[str, Any] = {}

    def _load_json(self, filename: str) -> Any:
        if filename in self._cache:
            return self._cache[filename]
        candidates = [
            self.data_dir / filename,
            self.data_dir.parent / "views" / "data" / filename,
        ]
        for path in candidates:
            if path.exists() and path.is_file():
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    self._cache[filename] = data
                    return data
                except Exception:
                    return None
        return None

    def search(self, query: str, limit: int = 15) -> dict[str, Any]:
        q = (query or "").strip().lower()
        lim = max(1, min(int(limit or 15), 50))
        results: list[dict[str, Any]] = []

        omni = self._load_json("omni-search-index.json")
        items = omni.get("items", omni) if isinstance(omni, dict) else omni
        if isinstance(items, list):
            for entry in items:
                if not isinstance(entry, dict):
                    continue
                hay = " ".join(
                    str(entry.get(k, ""))
                    for k in ("name", "title", "subtitle", "path", "category", "tags", "summary")
                ).lower()
                if not q or q in hay:
                    results.append({
                        "name": entry.get("name") or entry.get("title") or "",
                        "category": entry.get("category", "item"),
                        "path": entry.get("path", ""),
                        "tab": entry.get("tab", ""),
                        "subtitle": entry.get("subtitle", ""),
                    })
                    if len(results) >= lim:
                        break

        if len(results) < lim:
            graph = self._load_json("graph.json")
            nodes = graph.get("nodes", []) if isinstance(graph, dict) else []
            seen = {r.get("name") for r in results}
            for node in nodes:
                if not isinstance(node, dict):
                    continue
                name = str(node.get("label") or node.get("name") or node.get("id") or "")
                path = str(node.get("path") or "")
                if name in seen:
                    continue
                if not q or q in name.lower() or q in path.lower():
                    results.append({
                        "name": name,
                        "category": node.get("type", "node"),
                        "path": path,
                        "community": node.get("community"),
                    })
                    seen.add(name)
                    if len(results) >= lim:
                        break

        return {"query": query, "count": len(results), "results": results}

    def process_flow(self, query: str = "", limit: int = 10) -> dict[str, Any]:
        q = (query or "").strip().lower()
        lim = max(1, min(int(limit or 10), 30))
        raw = self._load_json("process-flows.json")
        flows = raw.get("flows", raw) if isinstance(raw, dict) else raw
        if not isinstance(flows, list):
            return {"query": query, "count": 0, "flows": []}

        matched = []
        for f in flows:
            if not isinstance(f, dict):
                continue
            blob = json.dumps(f, ensure_ascii=False).lower()
            if not q or q in blob:
                matched.append(f)
                if len(matched) >= lim:
                    break
        return {"query": query, "count": len(matched), "flows": matched}

    def db_schema(self, table: str = "") -> dict[str, Any]:
        q = (table or "").strip().lower()
        raw = self._load_json("db-schema.json")
        tables = raw.get("tables", raw) if isinstance(raw, dict) else raw
        if isinstance(tables, dict):
            table_list = [{"name": k, **(v if isinstance(v, dict) else {"raw": v})} for k, v in tables.items()]
        elif isinstance(tables, list):
            table_list = tables
        else:
            table_list = []

        if q:
            table_list = [t for t in table_list if q in json.dumps(t, ensure_ascii=False).lower()]
        return {"filter": table, "count": len(table_list), "tables": table_list[:30]}

    def stack(self, query: str = "") -> dict[str, Any]:
        q = (query or "").strip().lower()
        raw = self._load_json("stack-ecosystem.json")
        if not isinstance(raw, dict):
            return {"query": query, "count": 0, "items": []}
        items = raw.get("items") or raw.get("dependencies") or raw.get("packages") or []
        if not isinstance(items, list):
            items = []
        if q:
            items = [i for i in items if q in json.dumps(i, ensure_ascii=False).lower()]
        return {
            "query": query,
            "summary": raw.get("summary", {}),
            "count": len(items),
            "items": items[:40],
        }

    def telemetry(self, url: str = "") -> dict[str, Any]:
        target = (url or self.portal_url).rstrip("/")
        if target:
            try:
                parsed = urllib.parse.urlparse(target)
                if parsed.scheme in ("http", "https") and parsed.netloc:
                    conn_cls = http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection
                    conn = conn_cls(parsed.netloc, timeout=1.5)
                    try:
                        conn.request("GET", f"{parsed.path.rstrip('/')}/api/telemetry", headers={"Accept": "application/json"})
                        resp = conn.getresponse()
                        if resp.status == 200:
                            data = json.loads(resp.read().decode("utf-8"))
                            return {"live": True, "url": target, "telemetry": data}
                    finally:
                        conn.close()
            except Exception:
                pass

        graph = self._load_json("graph.json")
        manifest = self._load_json("views-manifest.json")
        return {
            "live": False,
            "url": target,
            "static_snapshot": {
                "data_dir": str(self.data_dir),
                "total_nodes": len(graph.get("nodes", [])) if isinstance(graph, dict) else 0,
                "total_edges": len(graph.get("edges", [])) if isinstance(graph, dict) else 0,
                "views": manifest if isinstance(manifest, (dict, list)) else {},
            },
        }

    def read_doc(self, rel_path: str, max_bytes: int = 65536) -> dict[str, Any]:
        target = safe_resolve_under(self.project_dir, rel_path)
        if not target or not target.exists() or not target.is_file():
            return {"error": f"File not found or forbidden: {rel_path}"}
        raw = target.read_bytes()
        truncated = len(raw) > max_bytes
        text = raw[:max_bytes].decode("utf-8", errors="replace")
        return {"path": rel_path, "truncated": truncated, "content": text}


TOOLS_SPEC: list[dict[str, Any]] = [
    {
        "name": "portal_search",
        "description": "Search the federated Knowledge Portal index (code symbols, API routes, ADRs, UI stores, docs).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search term"},
                "limit": {"type": "integer", "default": 15},
            },
            "required": ["query"],
        },
    },
    {
        "name": "portal_process_flow",
        "description": "Inspect end-to-end execution traces (entrypoint -> call chain -> database tables) from process-flows.json.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "default": ""},
                "limit": {"type": "integer", "default": 10},
            },
        },
    },
    {
        "name": "portal_db_schema",
        "description": "Inspect database tables, columns, primary keys, and foreign keys from db-schema.json.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "table": {"type": "string", "default": ""},
            },
        },
    },
    {
        "name": "portal_stack",
        "description": "Inspect project dependencies, containers, and tooling from stack-ecosystem.json.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "default": ""},
            },
        },
    },
    {
        "name": "portal_telemetry",
        "description": "Fetch live /api/telemetry (CPU, RAM, disk, watcher, backend latency) or static snapshot stats.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "default": ""},
            },
        },
    },
    {
        "name": "portal_read_doc",
        "description": "Safely read a Markdown doc, ADR, or source file inside the workspace (enforces path jail and denies .env/.git/frozen).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Relative path inside project directory"},
            },
            "required": ["path"],
        },
    },
]


def handle_jsonrpc_request(engine: PortalMcpEngine, req: dict[str, Any]) -> dict[str, Any] | None:
    method = req.get("method", "")
    req_id = req.get("id")
    params = req.get("params") or {}

    if method == "notifications/initialized" or req_id is None:
        return None

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": SERVER_INFO,
            },
        }

    if method == "ping":
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}

    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": TOOLS_SPEC}}

    if method == "tools/call":
        name = params.get("name", "")
        args = params.get("arguments") or {}
        dispatch = {
            "portal_search": lambda a: engine.search(a.get("query", ""), a.get("limit", 15)),
            "portal_process_flow": lambda a: engine.process_flow(a.get("query", ""), a.get("limit", 10)),
            "portal_db_schema": lambda a: engine.db_schema(a.get("table", "")),
            "portal_stack": lambda a: engine.stack(a.get("query", "")),
            "portal_telemetry": lambda a: engine.telemetry(a.get("url", "")),
            "portal_read_doc": lambda a: engine.read_doc(a.get("path", "")),
        }
        fn = dispatch.get(name)
        if fn is None:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": f"Unknown tool: {name}"},
            }
        payload = fn(args)
        is_err = isinstance(payload, dict) and "error" in payload
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "content": [{"type": "text", "text": json.dumps(payload, indent=2, ensure_ascii=False)}],
                "isError": is_err,
            },
        }

    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": -32601, "message": f"Method not found: {method}"},
    }


def run_mcp_stdio(project_dir: Path, data_dir: Path, portal_url: str = "http://127.0.0.1:8000") -> None:
    engine = PortalMcpEngine(project_dir=project_dir, data_dir=data_dir, portal_url=portal_url)
    for raw_line in sys.stdin:
        line = raw_line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError as exc:
            err_resp = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": str(exc)}}
            sys.stdout.write(json.dumps(err_resp) + "\n")
            sys.stdout.flush()
            continue
        resp = handle_jsonrpc_request(engine, req)
        if resp is not None:
            sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            sys.stdout.flush()
