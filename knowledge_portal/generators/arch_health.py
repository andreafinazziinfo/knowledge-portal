"""
Knowledge Portal — Architectural Health Auditor 2.0 (ADR-070).
File-level module aggregation + Tarjan SCC dependency cycles + orphan files +
god-files / hubs + UI->DB layer violations + Robert C. Martin metrics
(Ca, Ce, Instability I, Abstractness A, Distance from Main Sequence D) +
Domain-level DSM (Dependency Structure Matrix) + 6-axis Health Radar.
100% Python stdlib zero-dependency; respects P4 Gate (excludes frozen/).
"""

from __future__ import annotations

import json
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

_ENTRY_HINTS = (
    "main", "index", "app", "cli", "server", "dashboard", "__init__",
    "manage", "wsgi", "asgi", "conftest", "setup", "vite.config",
)
_TEST_HINTS = ("/tests/", "/test/", "test_", ".spec.", ".test.")
_UI_HINTS = ("ui/", "frontend/", "views/", "components/", "template/", "pages/")
_DB_HINTS = ("db/", "database/", "migrations/", "storage/", "models/", "repository/", "sql")
_DENY_SEGMENTS = ("frozen", ".git", "node_modules", "__pycache__")


def _is_denied(path_str: str) -> bool:
    parts = [p.lower() for p in path_str.replace("\\", "/").split("/")]
    return any(seg in _DENY_SEGMENTS for seg in parts)


def _domain_of(path_str: str) -> str:
    parts = [p for p in str(path_str or "").replace("\\", "/").split("/") if p]
    if len(parts) >= 3 and parts[0] in ("backend", "frontend", "src", "packages"):
        return f"{parts[0]}/{parts[1]}/{parts[2]}" if parts[1] in ("app", "src") else f"{parts[0]}/{parts[1]}"
    if len(parts) >= 2:
        return f"{parts[0]}/{parts[1]}"
    return parts[0] if parts else "root"


def _tarjan_scc(adj: dict[str, set[str]]) -> list[list[str]]:
    """Iterative Tarjan Strongly Connected Components (returns cycles of size >= 2)."""
    index_counter = 0
    stack: list[str] = []
    on_stack: set[str] = set()
    indices: dict[str, int] = {}
    lowlink: dict[str, int] = {}
    cycles: list[list[str]] = []

    for start in list(adj.keys()):
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
    """Compute file-level architectural health, Martin metrics, DSM, and 6-axis radar."""
    raw_nodes = graph_data.get("nodes") or []
    raw_edges = graph_data.get("edges") or graph_data.get("links") or []

    # Collapse symbol nodes into file-level modules while keeping ID/path/stem lookup tables
    modules: dict[str, dict[str, Any]] = {}
    id_to_mod: dict[str, str] = {}
    path_to_mod: dict[str, str] = {}
    stem_to_mod: dict[str, str] = {}
    label_to_mod: dict[str, str] = {}

    symbol_count_total = 0
    for n in raw_nodes:
        if not isinstance(n, dict) or n.get("id") is None:
            continue
        nid = str(n["id"])
        raw_path = str(n.get("path") or n.get("label") or nid).replace("\\", "/")
        if _is_denied(raw_path) or _is_denied(nid):
            continue
        symbol_count_total += 1
        # Use file path as canonical module key when present, else node ID
        mod_key = raw_path if ("/" in raw_path or "." in raw_path) else nid
        if mod_key not in modules:
            modules[mod_key] = {
                "id": nid,
                "path": raw_path,
                "label": n.get("label") or Path(raw_path).name or nid,
                "domain": _domain_of(raw_path),
                "loc": 0,
                "symbols": 0,
                "abstract_types": 0,
                "total_types": 0,
            }
        m = modules[mod_key]
        m["symbols"] += 1
        m["loc"] = max(m["loc"], int(n.get("loc") or n.get("lines") or n.get("size") or 0))
        ntype = str(n.get("type") or "").lower()
        lbl_low = str(n.get("label") or "").lower()
        if ntype in ("interface", "protocol", "abstract", "type") or lbl_low.startswith(("base", "abstract", "i_")):
            m["abstract_types"] += 1
            m["total_types"] += 1
        elif ntype in ("class", "struct", "table"):
            m["total_types"] += 1

        id_to_mod[nid] = mod_key
        p_low = raw_path.lower()
        path_to_mod.setdefault(p_low, mod_key)
        stem = p_low.rsplit(".", 1)[0] if "." in p_low.rsplit("/", 1)[-1] else p_low
        stem_to_mod.setdefault(stem, mod_key)
        parts = stem.split("/")
        if len(parts) >= 2 and parts[0] in ("backend", "frontend", "src"):
            stem_to_mod.setdefault("/".join(parts[1:]), mod_key)
        if lbl_low:
            label_to_mod.setdefault(lbl_low.rstrip("()"), mod_key)

    def _resolve_mod(ref: str) -> str | None:
        if ref in modules:
            return ref
        if ref in id_to_mod:
            return id_to_mod[ref]
        norm = ref.replace("\\", "/").lower()
        if norm in path_to_mod:
            return path_to_mod[norm]
        stem = norm.rsplit(".", 1)[0] if "." in norm.rsplit("/", 1)[-1] else norm
        if stem in stem_to_mod:
            return stem_to_mod[stem]
        return label_to_mod.get(norm)

    adj: dict[str, set[str]] = {mk: set() for mk in modules}
    in_deg: dict[str, int] = defaultdict(int)
    out_deg: dict[str, int] = defaultdict(int)
    layer_violations: list[dict[str, str]] = []
    domain_edges: dict[tuple[str, str], int] = defaultdict(int)

    for e in raw_edges:
        if not isinstance(e, dict):
            continue
        s = _resolve_mod(str(e.get("source", "")))
        t = _resolve_mod(str(e.get("target", "")))
        if not s or not t or s == t:
            continue
        if t not in adj[s]:
            adj[s].add(t)
            out_deg[s] += 1
            in_deg[t] += 1
            sd = modules[s]["domain"]
            td = modules[t]["domain"]
            domain_edges[(sd, td)] += 1

            s_path = modules[s]["path"].lower()
            t_path = modules[t]["path"].lower()
            if any(h in s_path for h in _UI_HINTS) and any(h in t_path for h in _DB_HINTS):
                layer_violations.append({
                    "source": modules[s]["id"],
                    "target": modules[t]["id"],
                    "rule": "UI_TO_DB_DIRECT_DEPENDENCY",
                    "detail": f"{s_path} -> {t_path}",
                })

    cycles_mod = _tarjan_scc(adj)
    # Map cycle entries back to node id when single-node module, or path for file-level clarity
    cycles = [
        [modules[mk]["id"] if modules[mk]["symbols"] == 1 and "/" not in mk else mk for mk in comp]
        for comp in cycles_mod
    ]

    orphans: list[dict[str, Any]] = []
    hubs: list[dict[str, Any]] = []
    domain_files: dict[str, list[str]] = defaultdict(list)

    for mk, m in modules.items():
        domain_files[m["domain"]].append(mk)
        ind = in_deg.get(mk, 0)
        outd = out_deg.get(mk, 0)
        total_deg = ind + outd
        p_low = f"/{m['path'].lower()}"
        stem = Path(m["path"]).stem.lower()
        is_entry = any(h in stem for h in _ENTRY_HINTS) or any(h in p_low for h in _TEST_HINTS)

        if total_deg == 0 and not is_entry:
            orphans.append({"id": m["id"], "label": m["label"], "path": m["path"]})
        if total_deg >= 5 or m["loc"] >= 500 or m["symbols"] >= 25:
            hubs.append({
                "id": m["id"],
                "label": m["label"],
                "path": m["path"],
                "domain": m["domain"],
                "in_degree": ind,
                "out_degree": outd,
                "total_degree": total_deg,
                "symbols": m["symbols"],
                "loc": m["loc"],
            })

    hubs.sort(key=lambda h: (-h["total_degree"], -h["symbols"], -h["loc"], h["path"]))
    orphans.sort(key=lambda o: o["path"])
    layer_violations.sort(key=lambda v: (v["source"], v["target"]))

    # Robert C. Martin Metrics per Domain (top 20 domains)
    top_domains = sorted(domain_files.keys(), key=lambda d: (-len(domain_files[d]), d))[:20]
    martin_metrics: list[dict[str, Any]] = []
    for dom in top_domains:
        fkeys = domain_files[dom]
        ca = sum(cnt for (sd, td), cnt in domain_edges.items() if td == dom and sd != dom)
        ce = sum(cnt for (sd, td), cnt in domain_edges.items() if sd == dom and td != dom)
        instability = round(ce / (ca + ce), 3) if (ca + ce) > 0 else 0.5
        abs_t = sum(modules[k]["abstract_types"] for k in fkeys)
        tot_t = sum(modules[k]["total_types"] for k in fkeys)
        abstractness = round(abs_t / tot_t, 3) if tot_t > 0 else 0.0
        distance = round(abs(abstractness + instability - 1.0), 3)
        if distance <= 0.35:
            zone = "Balanced"
        elif instability < 0.5 and abstractness < 0.5:
            zone = "Zone of Pain"
        else:
            zone = "Zone of Uselessness"
        martin_metrics.append({
            "domain": dom,
            "files": len(fkeys),
            "ca": ca,
            "ce": ce,
            "instability": instability,
            "abstractness": abstractness,
            "distance": distance,
            "zone": zone,
        })

    # Domain-level DSM (Dependency Structure Matrix) for top 15 domains
    dsm_domains = top_domains[:15]
    dsm_matrix = [
        [domain_edges.get((sd, td), 0) for td in dsm_domains]
        for sd in dsm_domains
    ]

    total_modules = len(modules)
    orphan_ratio = (len(orphans) / total_modules) if total_modules > 0 else 0.0
    avg_dist = (sum(m["distance"] for m in martin_metrics) / len(martin_metrics)) if martin_metrics else 0.0

    # 6-Axis Radar Scores (0..100)
    s_cycles = max(0, 100 - len(cycles) * 15)
    s_layers = max(0, 100 - len(layer_violations) * 12)
    s_orphans = max(0, round(100 * (1.0 - min(1.0, orphan_ratio))))
    s_main_seq = max(0, round(100 * (1.0 - min(1.0, avg_dist))))
    s_modularity = max(0, min(100, round(100 - max(0, len(hubs) - 10) * 1.5)))
    s_coupling = max(0, min(100, round(100 - (sum(1 for h in hubs if h["total_degree"] >= 20) * 6))))

    score = round(
        s_cycles * 0.28 + s_layers * 0.22 + s_orphans * 0.15 + s_main_seq * 0.15 + s_modularity * 0.10 + s_coupling * 0.10
    )
    grade = "A" if score >= 88 else ("B" if score >= 74 else ("C" if score >= 58 else "D"))

    return {
        "generated_at": time.time(),
        "summary": {
            "health_score": score,
            "grade": grade,
            "total_nodes": symbol_count_total,
            "total_modules": total_modules,
            "total_edges": sum(out_deg.values()),
            "cycle_count": len(cycles),
            "orphan_count": len(orphans),
            "god_file_count": len(hubs[:25]),
            "layer_violation_count": len(layer_violations),
            "avg_main_sequence_distance": round(avg_dist, 3),
        },
        "radar": {
            "Zero Cycles": s_cycles,
            "Layer Purity": s_layers,
            "Low Orphans": s_orphans,
            "Main Sequence": s_main_seq,
            "Modularity": s_modularity,
            "Coupling Balance": s_coupling,
        },
        "martin_metrics": martin_metrics,
        "dsm": {"domains": dsm_domains, "matrix": dsm_matrix},
        "cycles": cycles[:30],
        "orphans": orphans[:50],
        "god_files": hubs[:25],
        "layer_violations": layer_violations[:30],
    }


def generate_arch_health(data_dir: Path, project_dir: Path | None = None) -> dict[str, Any]:
    """Read graph.json from data_dir, run 8-pillar audit analyzers, and write arch-health.json."""
    from knowledge_portal.generators.audit_analyzers import (
        analyze_code_complexity_and_ai_readiness,
        analyze_coverage_reports,
        analyze_db_health,
        analyze_git_crime_scene,
        build_actionable_fix_queue,
        record_health_history,
    )

    data_dir = Path(data_dir)
    graph_file = data_dir / "graph.json"
    graph_data: dict[str, Any] = {}
    if graph_file.exists():
        try:
            graph_data = json.loads(graph_file.read_text(encoding="utf-8"))
        except Exception:
            graph_data = {}

    report = compute_arch_health(graph_data)
    if project_dir is not None and Path(project_dir).exists():
        pdir = Path(project_dir).resolve()
        report["complexity"] = analyze_code_complexity_and_ai_readiness(pdir)
        report["git_crime_scene"] = analyze_git_crime_scene(pdir, days=90)
        report["coverage"] = analyze_coverage_reports(pdir)
    else:
        report["complexity"] = {"files_analyzed": 0, "avg_maintainability_index": None, "avg_mccabe": None, "top_complex_files": [], "perf_bloat": {"large_files_count": 0, "large_files": [], "sql_select_star_files": 0, "sql_smells": []}, "ai_readiness": {"score": None, "docstring_coverage_pct": 0.0, "type_hint_coverage_pct": 0.0, "python_functions_analyzed": 0}}
        report["git_crime_scene"] = {"available": False, "hotspots": [], "temporal_coupling": [], "bus_factor_risks": []}
        report["coverage"] = {"available": False, "overall_pct": None, "files_measured": 0, "lowest_covered": []}

    report["db_health"] = analyze_db_health(data_dir)
    report["history"] = record_health_history(data_dir, report["summary"])
    report["fix_queue"] = build_actionable_fix_queue(report)

    data_dir.mkdir(parents=True, exist_ok=True)
    out_file = data_dir / "arch-health.json"
    out_file.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report
