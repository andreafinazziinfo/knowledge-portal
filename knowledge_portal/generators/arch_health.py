"""
Knowledge Portal — Architectural Health Auditor (ADR-069).
Computes dependency cycles (Tarjan SCC), orphan nodes, god-files / hubs,
and cross-layer violations from graph.json using Python stdlib only.
"""

from __future__ import annotations

import json
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

_ENTRY_HINTS = ("main", "index", "app", "cli", "server", "dashboard", "__init__", "manage", "wsgi", "asgi")
_UI_HINTS = ("ui/", "frontend/", "views/", "components/", "template/", "pages/")
_DB_HINTS = ("db/", "database/", "migrations/", "storage/", "models/", "repository/", "sql")
_DENY_SEGMENTS = ("frozen", ".git", "node_modules", "__pycache__")


def _is_denied(path_str: str) -> bool:
    parts = [p.lower() for p in path_str.replace("\\", "/").split("/")]
    return any(seg in _DENY_SEGMENTS for seg in parts)


def _tarjan_scc(adj: dict[str, set[str]]) -> list[list[str]]:
    """Iterative Tarjan Strongly Connected Components (returns cycles of size >= 2)."""
    index_counter = 0
    stack: list[str] = []
    on_stack: set[str] = set()
    indices: dict[str, int] = {}
    lowlink: dict[str, int] = {}
    cycles: list[list[str]] = []

    nodes = list(adj.keys())
    for start in nodes:
        if start in indices:
            continue
        call_stack: list[tuple[str, list[str], int]] = [(start, sorted(adj.get(start, ())), 0)]
        indices[start] = lowlink[start] = index_counter
        index_counter += 1
        stack.append(start)
        on_stack.add(start)

        while call_stack:
            v, neighbors, idx = call_stack[-1]
            if idx < len(neighbors):
                call_stack[-1] = (v, neighbors, idx + 1)
                w = neighbors[idx]
                if w not in indices:
                    indices[w] = lowlink[w] = index_counter
                    index_counter += 1
                    stack.append(w)
                    on_stack.add(w)
                    call_stack.append((w, sorted(adj.get(w, ())), 0))
                elif w in on_stack:
                    if indices[w] < lowlink[v]:
                        lowlink[v] = indices[w]
            else:
                call_stack.pop()
                if call_stack:
                    parent = call_stack[-1][0]
                    if lowlink[v] < lowlink[parent]:
                        lowlink[parent] = lowlink[v]
                if lowlink[v] == indices[v]:
                    comp: list[str] = []
                    while True:
                        w = stack.pop()
                        on_stack.remove(w)
                        comp.append(w)
                        if w == v:
                            break
                    if len(comp) >= 2:
                        cycles.append(sorted(comp))

    cycles.sort(key=lambda c: (-len(c), c[0]))
    return cycles


def compute_arch_health(graph_data: dict[str, Any]) -> dict[str, Any]:
    """Compute architectural health metrics from a parsed graph.json dict."""
    raw_nodes = graph_data.get("nodes") or []
    raw_edges = graph_data.get("edges") or graph_data.get("links") or []

    nodes: dict[str, dict[str, Any]] = {}
    for n in raw_nodes:
        if not isinstance(n, dict) or n.get("id") is None:
            continue
        nid = str(n["id"])
        p = str(n.get("path") or n.get("label") or nid)
        if _is_denied(p) or _is_denied(nid):
            continue
        nodes[nid] = n

    adj: dict[str, set[str]] = {nid: set() for nid in nodes}
    in_deg: dict[str, int] = defaultdict(int)
    out_deg: dict[str, int] = defaultdict(int)
    layer_violations: list[dict[str, str]] = []

    for e in raw_edges:
        if not isinstance(e, dict):
            continue
        s = str(e.get("source", ""))
        t = str(e.get("target", ""))
        if s not in nodes or t not in nodes or s == t:
            continue
        if t not in adj[s]:
            adj[s].add(t)
            out_deg[s] += 1
            in_deg[t] += 1

        s_path = str(nodes[s].get("path") or nodes[s].get("label") or s).lower().replace("\\", "/")
        t_path = str(nodes[t].get("path") or nodes[t].get("label") or t).lower().replace("\\", "/")
        if any(h in s_path for h in _UI_HINTS) and any(h in t_path for h in _DB_HINTS):
            layer_violations.append({
                "source": s,
                "target": t,
                "rule": "UI_TO_DB_DIRECT_DEPENDENCY",
                "detail": f"{s_path} -> {t_path}",
            })

    cycles = _tarjan_scc(adj)

    orphans: list[dict[str, Any]] = []
    hubs: list[dict[str, Any]] = []
    for nid, n in nodes.items():
        ind = in_deg.get(nid, 0)
        outd = out_deg.get(nid, 0)
        total_deg = ind + outd
        path_str = str(n.get("path") or n.get("label") or nid)
        stem = Path(path_str).stem.lower()
        loc = int(n.get("loc") or n.get("lines") or n.get("size") or 0)

        if total_deg == 0 and not any(h in stem for h in _ENTRY_HINTS):
            orphans.append({"id": nid, "label": n.get("label") or nid, "path": path_str})
        if total_deg >= 6 or loc >= 500:
            hubs.append({
                "id": nid,
                "label": n.get("label") or nid,
                "path": path_str,
                "in_degree": ind,
                "out_degree": outd,
                "total_degree": total_deg,
                "loc": loc,
            })

    hubs.sort(key=lambda h: (-h["total_degree"], -h["loc"], h["id"]))
    orphans.sort(key=lambda o: o["path"])
    layer_violations.sort(key=lambda v: (v["source"], v["target"]))

    total_nodes = len(nodes)
    penalty = min(40, len(cycles) * 10) + min(25, len(layer_violations) * 5) + min(20, int(len(orphans) * 0.5))
    score = max(0, 100 - penalty)
    grade = "A" if score >= 90 else ("B" if score >= 75 else ("C" if score >= 60 else "D"))

    return {
        "generated_at": time.time(),
        "summary": {
            "health_score": score,
            "grade": grade,
            "total_nodes": total_nodes,
            "total_edges": sum(out_deg.values()),
            "cycle_count": len(cycles),
            "orphan_count": len(orphans),
            "god_file_count": len(hubs[:25]),
            "layer_violation_count": len(layer_violations),
        },
        "cycles": cycles[:30],
        "orphans": orphans[:50],
        "god_files": hubs[:25],
        "layer_violations": layer_violations[:30],
    }


def generate_arch_health(data_dir: Path) -> dict[str, Any]:
    """Read graph.json from data_dir and write arch-health.json."""
    data_dir = Path(data_dir)
    graph_file = data_dir / "graph.json"
    graph_data: dict[str, Any] = {}
    if graph_file.exists():
        try:
            graph_data = json.loads(graph_file.read_text(encoding="utf-8"))
        except Exception:
            graph_data = {}

    report = compute_arch_health(graph_data)
    data_dir.mkdir(parents=True, exist_ok=True)
    out_file = data_dir / "arch-health.json"
    out_file.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report
