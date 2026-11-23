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

from knowledge_portal.indexer.fts_engine import FtsSearchEngine
from knowledge_portal.codemode_sandbox import (
    CodeModeLimitError,
    CodeModeSecurityError,
    execute_codemode,
    get_codemode_sdk_reference,
)
from knowledge_portal.generators.arch_health import compute_arch_health
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
        self._fts = FtsSearchEngine(self.data_dir)

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
        q = (query or "").strip()
        lim = max(1, min(int(limit or 15), 50))
        if q:
            results = self._fts.search(q, limit=lim)
            return {"query": query, "engine": "sqlite-fts5-bm25", "count": len(results), "results": results}

        omni = self._load_json("omni-search-index.json")
        items = (omni.get("entities") or omni.get("items") or []) if isinstance(omni, dict) else (omni if isinstance(omni, list) else [])
        results = [
            {
                "name": e.get("title") or e.get("name") or "",
                "category": e.get("category", "item"),
                "path": e.get("path", ""),
                "tab": e.get("tab", ""),
                "subtitle": e.get("subtitle", ""),
            }
            for e in items[:lim]
            if isinstance(e, dict)
        ]
        return {"query": query, "engine": "snapshot", "count": len(results), "results": results}

    def graph_neighbors(self, node_id: str, depth: int = 1) -> dict[str, Any]:
        target_q = (node_id or "").strip().lower()
        hops = max(1, min(int(depth or 1), 2))
        graph = self._load_json("graph.json")
        if not isinstance(graph, dict):
            return {"node_id": node_id, "matches": [], "neighbors": []}
        nodes = {str(n.get("id")): n for n in graph.get("nodes", []) if isinstance(n, dict) and n.get("id") is not None}
        edges = graph.get("edges") or graph.get("links") or []

        matched_ids = [
            nid for nid, n in nodes.items()
            if target_q in nid.lower() or target_q in str(n.get("label") or n.get("name") or "").lower()
        ][:5]
        frontier = set(matched_ids)
        visited = set(matched_ids)
        rel_edges = []
        for _ in range(hops):
            next_frontier: set[str] = set()
            for e in edges:
                if not isinstance(e, dict):
                    continue
                s = str(e.get("source", ""))
                t = str(e.get("target", ""))
                if s in frontier or t in frontier:
                    rel_edges.append({"source": s, "target": t, "relation": e.get("relation") or e.get("type") or "edge"})
                    if s not in visited:
                        next_frontier.add(s)
                    if t not in visited:
                        next_frontier.add(t)
            visited.update(next_frontier)
            frontier = next_frontier
            if not frontier:
                break

        neighbor_ids = [nid for nid in visited if nid not in matched_ids][:40]
        return {
            "query": node_id,
            "depth": hops,
            "matched_nodes": [nodes[i] for i in matched_ids],
            "neighbors": [nodes[i] for i in neighbor_ids if i in nodes],
            "edges": rel_edges[:60],
        }

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


    def impact(self, target: str, max_depth: int = 3) -> dict[str, Any]:
        """Compute reverse-dependency blast radius (d=1, d=2, d=3) and affected process flows."""
        q = (target or "").strip().lower()
        hops = max(1, min(int(max_depth or 3), 5))
        if not q:
            return {"error": "Missing target symbol or file path"}

        graph = self._load_json("graph.json")
        if not isinstance(graph, dict):
            return {"target": target, "risk": "UNKNOWN", "counts": {"d1": 0, "d2": 0, "d3": 0, "total": 0}, "by_depth": {}, "affected_flows": []}

        # Collapse to file-level modules + path/stem/label resolver so file-level edges match accurately
        edges = graph.get("edges") or graph.get("links") or []
        modules: dict[str, dict[str, Any]] = {}
        id_to_mod: dict[str, str] = {}
        path_to_mod: dict[str, str] = {}
        stem_to_mod: dict[str, str] = {}
        for n in graph.get("nodes", []):
            if not isinstance(n, dict) or n.get("id") is None:
                continue
            nid = str(n["id"])
            raw_p = str(n.get("path") or n.get("label") or nid).replace("\\", "/")
            if any(seg.startswith(".") or seg == "frozen" for seg in raw_p.split("/") if seg):
                continue
            mk = raw_p if ("/" in raw_p or "." in raw_p) else nid
            if mk not in modules:
                modules[mk] = {"id": nid, "label": n.get("label") or Path(raw_p).name or nid, "path": raw_p, "type": n.get("type") or "file"}
            id_to_mod[nid] = mk
            p_low = raw_p.lower()
            path_to_mod.setdefault(p_low, mk)
            stem = p_low.rsplit(".", 1)[0] if "." in p_low.rsplit("/", 1)[-1] else p_low
            stem_to_mod.setdefault(stem, mk)
            parts = stem.split("/")
            if len(parts) >= 2 and parts[0] in ("backend", "frontend", "src"):
                stem_to_mod.setdefault("/".join(parts[1:]), mk)

        def _res(ref: str) -> str | None:
            if ref in modules:
                return ref
            if ref in id_to_mod:
                return id_to_mod[ref]
            norm = ref.replace("\\", "/").lower()
            if norm in path_to_mod:
                return path_to_mod[norm]
            stem = norm.rsplit(".", 1)[0] if "." in norm.rsplit("/", 1)[-1] else norm
            return stem_to_mod.get(stem)

        rev_adj: dict[str, set[str]] = {}
        for e in edges:
            if not isinstance(e, dict):
                continue
            s = _res(str(e.get("source", "")))
            t = _res(str(e.get("target", "")))
            if s and t and s != t:
                rev_adj.setdefault(t, set()).add(s)

        matched_ids = [
            mk for mk, m in modules.items()
            if q in mk.lower() or q in m["id"].lower() or q in m["path"].lower() or q in str(m["label"]).lower()
        ][:5]

        visited = set(matched_ids)
        frontier = set(matched_ids)
        by_depth: dict[str, list[dict[str, Any]]] = {}
        for d in range(1, hops + 1):
            next_frontier: set[str] = set()
            for mk in frontier:
                for caller in rev_adj.get(mk, ()):
                    if caller not in visited:
                        visited.add(caller)
                        next_frontier.add(caller)
            by_depth[f"d{d}"] = [
                {"id": modules[cid]["id"], "label": modules[cid]["label"], "path": modules[cid]["path"], "type": modules[cid]["type"]}
                for cid in sorted(next_frontier)[:40]
            ]
            frontier = next_frontier
            if not frontier:
                break

        d1 = len(by_depth.get("d1", []))
        d2 = len(by_depth.get("d2", []))
        d3 = len(by_depth.get("d3", []))
        total = sum(len(v) for v in by_depth.values())

        if not matched_ids:
            risk = "UNKNOWN"
        elif d1 >= 10 or total >= 25:
            risk = "CRITICAL"
        elif d1 >= 5 or total >= 12:
            risk = "HIGH"
        elif d1 >= 2 or total >= 4:
            risk = "MEDIUM"
        else:
            risk = "LOW"

        flows_res = self.process_flow(query=target, limit=10)
        affected_flows = flows_res.get("flows", []) if isinstance(flows_res, dict) else []

        return {
            "target": target,
            "matched_nodes": [{"id": modules[i]["id"], "label": modules[i]["label"], "path": modules[i]["path"]} for i in matched_ids],
            "risk": risk,
            "counts": {"d1": d1, "d2": d2, "d3": d3, "total": total},
            "by_depth": by_depth,
            "affected_flows": affected_flows,
        }

    def health_audit(self) -> dict[str, Any]:
        """Return architectural health audit (cycles, orphans, god-files, layer violations)."""
        cached = self._load_json("arch-health.json")
        if isinstance(cached, dict) and "summary" in cached:
            return cached
        graph = self._load_json("graph.json")
        if isinstance(graph, dict):
            return compute_arch_health(graph)
        return compute_arch_health({})

    def context_pack(self, topic: str, max_tokens: int = 4000) -> dict[str, Any]:
        """Single-call compressed Markdown briefing fusing search, impact, flows, schema, and health."""
        q = (topic or "").strip()
        budget_tokens = max(400, min(int(max_tokens or 4000), 16000))
        budget_chars = budget_tokens * 4

        search_res = self.search(q, limit=8)
        impact_res = self.impact(q, max_depth=2) if q else {}
        flows_res = self.process_flow(q, limit=5) if q else {}
        health_res = self.health_audit()

        sections: list[str] = [f"# Context Pack: {q or 'Repository Overview'}", ""]

        # 1. Top Search Hits
        hits = search_res.get("results") or []
        sections.append("## Top Matches (FTS5 BM25)")
        if hits:
            for h in hits[:8]:
                sections.append(f"- `{h.get('path') or h.get('name')}` [{h.get('category', 'item')}]: {h.get('subtitle', '')}")
        else:
            sections.append("- No direct index matches.")
        sections.append("")

        # 2. Blast Radius
        if impact_res and impact_res.get("matched_nodes"):
            c = impact_res.get("counts") or {}
            sections.append(f"## Blast Radius (Risk: {impact_res.get('risk', 'UNKNOWN')})")
            sections.append(f"- Direct callers (d=1): {c.get('d1', 0)} | Indirect (d=2): {c.get('d2', 0)} | Total: {c.get('total', 0)}")
            for item in (impact_res.get("by_depth") or {}).get("d1", [])[:10]:
                sections.append(f"  - d=1 `{item.get('path') or item.get('id')}`")
            sections.append("")

        # 3. Process Flows
        fls = flows_res.get("flows") or [] if isinstance(flows_res, dict) else []
        if fls:
            sections.append("## Related Execution Flows")
            for fl in fls[:5]:
                if isinstance(fl, dict):
                    sections.append(f"- **{fl.get('name') or fl.get('id', 'Flow')}**: {fl.get('description', '')}")
            sections.append("")

        # 4. Architectural Health Snapshot
        h_sum = health_res.get("summary") or {}
        sections.append("## Architectural Health")
        sections.append(
            f"- Score: {h_sum.get('health_score', 'N/A')}/100 (Grade {h_sum.get('grade', 'N/A')}) | "
            f"Cycles: {h_sum.get('cycle_count', 0)} | Orphans: {h_sum.get('orphan_count', 0)} | "
            f"Layer Violations: {h_sum.get('layer_violation_count', 0)}"
        )

        markdown = "\n".join(sections)
        truncated = len(markdown) > budget_chars
        if truncated:
            markdown = markdown[:budget_chars] + "\n... [TRUNCATED TO TOKEN BUDGET]"

        return {
            "topic": q,
            "max_tokens": budget_tokens,
            "estimated_tokens": max(1, len(markdown) // 4),
            "truncated": truncated,
            "markdown": markdown,
        }

    def api_catalog(self, query: str = "") -> dict[str, Any]:
        from knowledge_portal.generators.api_catalog import generate_api_catalog
        ep_file = self.data_dir / "api-catalog.json"
        if ep_file.exists():
            data = json.loads(ep_file.read_text(encoding="utf-8"))
        else:
            data = generate_api_catalog(self.project_dir, self.data_dir)
        q = (query or "").strip().lower()
        if q:
            eps = [
                e for e in (data.get("endpoints") or [])
                if q in f"{e.get('method', '')} {e.get('path', '')} {e.get('tag', '')} {e.get('handler', '')} {e.get('file', '')}".lower()
            ]
            return {"query": query, "count": len(eps), "endpoints": eps[:50]}
        return {"summary": data.get("summary", {}), "tags": data.get("tags", []), "endpoints": (data.get("endpoints") or [])[:50]}

    def arch_diff(self) -> dict[str, Any]:
        from knowledge_portal.generators.arch_health import generate_arch_diff
        diff_file = self.data_dir / "arch-diff.json"
        if diff_file.exists():
            return json.loads(diff_file.read_text(encoding="utf-8"))
        return generate_arch_diff(self.data_dir)

    def call_graph(self, symbol: str = "", max_depth: int = 3) -> dict[str, Any]:
        from knowledge_portal.generators.call_graph import generate_call_graph
        cg_file = self.data_dir / "call-graph.json"
        data = json.loads(cg_file.read_text(encoding="utf-8")) if cg_file.exists() else generate_call_graph(self.project_dir, self.data_dir)
        q = (symbol or "").strip().lower()
        if not q:
            return {"summary": data.get("summary", {}), "chains": (data.get("chains") or [])[:25]}
        syms = data.get("symbols") or {}
        matches = [v for k, v in syms.items() if q in k.lower() or q in str(v.get("name", "")).lower() or q in str(v.get("route") or "").lower()][:15]
        return {"query": symbol, "count": len(matches), "matches": matches}

    def ownership(self) -> dict[str, Any]:
        from knowledge_portal.generators.ownership import generate_ownership_map
        ow_file = self.data_dir / "ownership.json"
        if ow_file.exists():
            return json.loads(ow_file.read_text(encoding="utf-8"))
        return generate_ownership_map(self.project_dir, self.data_dir)

    def invariants(self) -> dict[str, Any]:
        rules_file = self.project_dir / "portal-rules.yaml"
        custom_raw = rules_file.read_text(encoding="utf-8", errors="ignore")[:4000] if rules_file.is_file() else None
        return {
            "schema_version": "1.0",
            "rules_file": "portal-rules.yaml" if custom_raw else None,
            "custom_yaml": custom_raw,
            "builtin_invariants": [
                {"id": "P4_FROZEN_GATE", "severity": "CRITICAL", "rule": "Never modify or index files under any `frozen/` directory."},
                {"id": "NO_UI_TO_DB", "severity": "HIGH", "rule": "Frontend/UI layers must not import database/storage repositories directly."},
                {"id": "ZERO_CIRCULAR_DEPS", "severity": "HIGH", "rule": "No circular dependency cycles (Tarjan SCC) across modules."},
                {"id": "AUTH_ON_MUTATING_API", "severity": "HIGH", "rule": "Mutating HTTP routes (POST/PUT/PATCH/DELETE) require explicit auth dependencies unless explicitly public."},
            ],
        }

    def validate_change(self, paths: list[str]) -> dict[str, Any]:
        violations: list[dict[str, str]] = []
        warnings: list[dict[str, Any]] = []
        for raw_p in paths:
            p = str(raw_p).replace("\\", "/")
            if "frozen/" in p.lower() or p.lower().startswith("frozen/"):
                violations.append({"rule": "P4_FROZEN_GATE", "path": p, "detail": "Blocked: modifications inside frozen/ are forbidden."})
                continue
            imp = self.impact(p, max_depth=2)
            if imp.get("risk") in ("HIGH", "CRITICAL"):
                warnings.append({"rule": "HIGH_BLAST_RADIUS", "path": p, "risk": imp.get("risk"), "impacted": (imp.get("counts") or {}).get("total", 0)})
        return {"allowed": len(violations) == 0, "violations": violations, "warnings": warnings}

    def mission_pack(self, task: str, max_tokens: int = 6000) -> dict[str, Any]:
        q = (task or "").strip()
        budget_tokens = max(600, min(int(max_tokens or 6000), 16000))
        budget_chars = budget_tokens * 4
        from knowledge_portal.indexer.fts_engine import FtsSearchEngine
        fts = FtsSearchEngine(self.data_dir)
        hits = fts.search(q, limit=8, expand_graph=True)
        top_paths = [str(h.get("path") or "") for h in hits if h.get("path")][:5]
        primary = top_paths[0] if top_paths else q
        imp = self.impact(primary, max_depth=2)
        cg = self.call_graph(primary)
        health = self.health_audit()
        inv = self.invariants()
        validation = self.validate_change(top_paths)

        lines = [
            f"# AI Mission Pack: {q}",
            "",
            "## 1. Key Target Files (Hybrid FTS5 + 1-Hop Graph)",
            *[f"- `{h.get('path') or h.get('name')}` ({h.get('category', 'item')}){' [1-hop]' if h.get('graph_expanded') else ''}" for h in hits[:8]],
            "",
            f"## 2. Blast Radius for `{primary}` (Risk: {imp.get('risk', 'LOW')})",
            f"- Direct callers (d=1): `{(imp.get('counts') or {}).get('d1', 0)}` · Indirect (d=2): `{(imp.get('counts') or {}).get('d2', 0)}`",
            "",
            "## 3. Symbol Call-Graph Matches",
            *[f"- `{m.get('id')}` (`{m.get('signature')}`) → callees: `{len(m.get('callees') or [])}`, db: `{m.get('db_tables') or []}`" for m in (cg.get("matches") or [])[:5]],
            "",
            "## 4. Invariants & Pre-Flight Validation",
            f"- Pre-flight allowed: `{validation['allowed']}` · Violations: `{len(validation['violations'])}` · High-Risk Warnings: `{len(validation['warnings'])}`",
            *[f"- **{r['id']}**: {r['rule']}" for r in inv["builtin_invariants"]],
            "",
            "## 5. Architecture Health Snapshot",
            f"- Score: `{(health.get('summary') or {}).get('health_score', 'N/A')}/100` (Grade `{(health.get('summary') or {}).get('grade', '-')}`)",
        ]
        md = "\n".join(lines)
        truncated = len(md) > budget_chars
        if truncated:
            md = md[:budget_chars] + "\n... [TRUNCATED TO TOKEN BUDGET]"
        return {
            "task": q,
            "target_files": top_paths,
            "estimated_tokens": max(1, len(md) // 4),
            "truncated": truncated,
            "validation": validation,
            "markdown": md,
        }

    def pr_context(self, base: str = "main") -> dict[str, Any]:
        from knowledge_portal.generators.doc_drift import detect_doc_drift, render_pr_comment_markdown
        drift = detect_doc_drift(self.project_dir, base=base)
        health = self.health_audit()
        return {**drift, "pr_comment_markdown": render_pr_comment_markdown(drift, health_report=health)}

    def codemode_discover(self, topic: str = "") -> dict[str, Any]:
        return get_codemode_sdk_reference(topic=topic)

    def codemode_execute(self, code: str) -> dict[str, Any]:
        try:
            return execute_codemode(self, code)
        except (CodeModeSecurityError, CodeModeLimitError) as exc:
            return {"error": str(exc), "ok": False}


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
    {
        "name": "portal_graph_neighbors",
        "description": "Inspect 1-hop or 2-hop neighbors and edges of a node in graph.json.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "node_id": {"type": "string", "description": "Node ID or label substring"},
                "depth": {"type": "integer", "default": 1},
            },
            "required": ["node_id"],
        },
    },
    {
        "name": "portal_context_pack",
        "description": "Generate a single-call compressed Markdown briefing fusing FTS5 search, blast radius, process flows, and architectural health within a token budget.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "topic": {"type": "string", "description": "Topic, symbol, or file path"},
                "max_tokens": {"type": "integer", "default": 4000},
            },
            "required": ["topic"],
        },
    },
    {
        "name": "portal_impact",
        "description": "Compute reverse-dependency blast radius (d=1/d=2/d=3 callers & affected process flows) for a symbol or file.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "target": {"type": "string", "description": "Symbol name, node ID, or file path"},
                "max_depth": {"type": "integer", "default": 3},
            },
            "required": ["target"],
        },
    },
    {
        "name": "portal_health_audit",
        "description": "Inspect architectural health metrics: dependency cycles (Tarjan SCC), orphan modules, god-files, and cross-layer violations.",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "portal_api_catalog",
        "description": "Query auto-discovered HTTP/WebSocket API endpoints, auth guards, handlers, and response models.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "default": "", "description": "Optional path, method, tag, or handler filter"},
            },
        },
    },
    {
        "name": "portal_arch_diff",
        "description": "Compare current architecture snapshot against previous graph-prev.json and historical health trend.",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "portal_call_chain",
        "description": "Inspect AST symbol-level callers, callees, typed signatures, and Route -> DB call chains.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "default": "", "description": "Function/method name, route, or file filter"},
                "max_depth": {"type": "integer", "default": 3},
            },
        },
    },
    {
        "name": "portal_mission_pack",
        "description": "Generate a single-call task-scoped AI Mission Pack combining hybrid graph search, blast radius, symbol call-graph, invariants, and health snapshot within a token budget.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "task": {"type": "string", "description": "Engineering task or target feature"},
                "max_tokens": {"type": "integer", "default": 6000},
            },
            "required": ["task"],
        },
    },
    {
        "name": "portal_validate_change",
        "description": "Validate proposed file modifications against machine-readable architectural invariants (P4 frozen gate, blast radius).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "paths": {"type": "array", "items": {"type": "string"}, "description": "Relative file paths to modify"},
            },
            "required": ["paths"],
        },
    },
    {
        "name": "portal_pr_context",
        "description": "Analyze git diff against base ref to detect stale docs/ADRs (Doc-Drift), impacted tests, and generate a PR review summary.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "base": {"type": "string", "default": "main"},
            },
        },
    },
    {
        "name": "portal_discover",
        "description": "Code Mode SDK discovery: returns the compact typed read-only `portal.*` API reference for writing multi-step query pipelines.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "topic": {"type": "string", "default": ""},
            },
        },
    },
    {
        "name": "portal_codemode",
        "description": "Execute a read-only, AST-sandboxed Python query pipeline against `portal.*` SDK in a single round-trip (no imports, no I/O, no mutations).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "Python snippet using `portal.<method>(...)` assigning final value to `result`"},
            },
            "required": ["code"],
        },
    },
]

CODE_MODE_TOOLS_SPEC: list[dict[str, Any]] = [
    t for t in TOOLS_SPEC if t["name"] in ("portal_discover", "portal_codemode")
]


def handle_jsonrpc_request(engine: PortalMcpEngine, req: dict[str, Any], code_mode: bool = False) -> dict[str, Any] | None:
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
                "capabilities": {"tools": {}, "resources": {}, "prompts": {}},
                "serverInfo": SERVER_INFO,
            },
        }

    if method == "ping":
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}

    if method == "resources/list":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "resources": [
                    {"uri": "portal://llms.txt", "name": "llms.txt", "description": "AI-ready project manifest", "mimeType": "text/markdown"},
                    {"uri": "portal://health", "name": "Health Engine 4.0 Report", "description": "16-pillar architectural & security health audit", "mimeType": "application/json"},
                    {"uri": "portal://api-catalog", "name": "Live API Catalog", "description": "Auto-discovered HTTP/WS endpoints & OpenAPI 3.1", "mimeType": "application/json"},
                    {"uri": "portal://arch-diff", "name": "Architecture Diff", "description": "Snapshot delta & historical trend", "mimeType": "application/json"},
                    {"uri": "portal://sbom", "name": "CycloneDX 1.5 SBOM", "description": "Software Bill of Materials & licenses", "mimeType": "application/json"},
                    {"uri": "portal://invariants", "name": "Architecture Invariants", "description": "Machine-readable architectural rules & P4 gates", "mimeType": "application/json"},
                    {"uri": "portal://ownership", "name": "Ownership & Conway Map", "description": "CODEOWNERS and contributor bus-factor map", "mimeType": "application/json"},
                ]
            },
        }

    if method == "resources/read":
        uri = str(params.get("uri", ""))
        if uri == "portal://llms.txt":
            cand = engine.data_dir.parent / "llms.txt"
            txt = cand.read_text(encoding="utf-8") if cand.exists() else "# llms.txt not generated yet"
            return {"jsonrpc": "2.0", "id": req_id, "result": {"contents": [{"uri": uri, "mimeType": "text/markdown", "text": txt}]}}
        if uri == "portal://health":
            return {"jsonrpc": "2.0", "id": req_id, "result": {"contents": [{"uri": uri, "mimeType": "application/json", "text": json.dumps(engine.health_audit(), indent=2)}]}}
        if uri == "portal://api-catalog":
            return {"jsonrpc": "2.0", "id": req_id, "result": {"contents": [{"uri": uri, "mimeType": "application/json", "text": json.dumps(engine.api_catalog(), indent=2)}]}}
        if uri == "portal://arch-diff":
            return {"jsonrpc": "2.0", "id": req_id, "result": {"contents": [{"uri": uri, "mimeType": "application/json", "text": json.dumps(engine.arch_diff(), indent=2)}]}}
        if uri == "portal://sbom":
            sb = engine.data_dir / "sbom.cdx.json"
            txt = sb.read_text(encoding="utf-8") if sb.exists() else json.dumps({"bomFormat": "CycloneDX", "specVersion": "1.5", "components": []})
            return {"jsonrpc": "2.0", "id": req_id, "result": {"contents": [{"uri": uri, "mimeType": "application/json", "text": txt}]}}
        if uri == "portal://invariants":
            return {"jsonrpc": "2.0", "id": req_id, "result": {"contents": [{"uri": uri, "mimeType": "application/json", "text": json.dumps(engine.invariants(), indent=2)}]}}
        if uri == "portal://ownership":
            return {"jsonrpc": "2.0", "id": req_id, "result": {"contents": [{"uri": uri, "mimeType": "application/json", "text": json.dumps(engine.ownership(), indent=2)}]}}
        return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32602, "message": f"Unknown resource URI: {uri}"}}

    if method == "prompts/list":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "prompts": [
                    {"name": "audit_pr_impact", "description": "Analyze blast radius, cycles, and OWASP/SRE findings for a target module.", "arguments": [{"name": "target", "required": True}]},
                    {"name": "onboard_module", "description": "Generate an onboarding briefing for a module using context-pack and API catalog.", "arguments": [{"name": "module", "required": True}]},
                ]
            },
        }

    if method == "prompts/get":
        pname = str(params.get("name", ""))
        pargs = params.get("arguments") or {}
        if pname == "audit_pr_impact":
            tgt = str(pargs.get("target", "main"))
            return {"jsonrpc": "2.0", "id": req_id, "result": {"messages": [{"role": "user", "content": {"type": "text", "text": f"Run portal_impact('{tgt}'), portal_health_audit(), and portal_arch_diff() to assess blast radius and regression risk before merging."}}]}}
        if pname == "onboard_module":
            mod = str(pargs.get("module", "core"))
            return {"jsonrpc": "2.0", "id": req_id, "result": {"messages": [{"role": "user", "content": {"type": "text", "text": f"Use portal_context_pack('{mod}') and portal_api_catalog('{mod}') to summarize architecture, dependencies, and public routes."}}]}}
        return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32602, "message": f"Unknown prompt: {pname}"}}

    if method == "tools/list":
        tools = CODE_MODE_TOOLS_SPEC if code_mode else TOOLS_SPEC
        return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": tools}}

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
            "portal_graph_neighbors": lambda a: engine.graph_neighbors(a.get("node_id", ""), a.get("depth", 1)),
            "portal_context_pack": lambda a: engine.context_pack(a.get("topic", ""), a.get("max_tokens", 4000)),
            "portal_impact": lambda a: engine.impact(a.get("target", ""), a.get("max_depth", 3)),
            "portal_health_audit": lambda _a: engine.health_audit(),
            "portal_api_catalog": lambda a: engine.api_catalog(a.get("query", "")),
            "portal_arch_diff": lambda _a: engine.arch_diff(),
            "portal_call_chain": lambda a: engine.call_graph(a.get("symbol", ""), a.get("max_depth", 3)),
            "portal_mission_pack": lambda a: engine.mission_pack(a.get("task", ""), a.get("max_tokens", 6000)),
            "portal_validate_change": lambda a: engine.validate_change(a.get("paths") or []),
            "portal_pr_context": lambda a: engine.pr_context(a.get("base", "main")),
            "portal_discover": lambda a: engine.codemode_discover(a.get("topic", "")),
            "portal_codemode": lambda a: engine.codemode_execute(a.get("code", "")),
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


def run_mcp_stdio(project_dir: Path, data_dir: Path, portal_url: str = "http://127.0.0.1:8000", code_mode: bool = False) -> None:
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
        resp = handle_jsonrpc_request(engine, req, code_mode=code_mode)
        if resp is not None:
            sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            sys.stdout.flush()
