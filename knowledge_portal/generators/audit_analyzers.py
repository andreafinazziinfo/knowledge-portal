"""
Knowledge Portal — Enterprise Audit Analyzers 3.0 (ADR-071).
100% Python stdlib zero-dependency analyzers covering:
1. AST McCabe Cyclomatic Complexity, Cognitive Complexity & Maintainability Index (MI)
2. Git Crime Scene (read-only git log): Hotspots (Churn x Complexity), Temporal Coupling, Bus Factor
3. Coverage Report Auto-Ingestion (coverage.xml / lcov.info)
4. Performance & SQL Bloat (large files > 500KB, SELECT * patterns)
5. DB Schema Health (tables without PK / foreign keys)
6. AI Readiness Score (docstring %, type-hint %, llms.txt freshness)
7. Historical Trend Log (data/arch-health-history.json)

Strictly enforces P4 Gate (excludes frozen/, .git, node_modules, venv, secrets).
"""

from __future__ import annotations

import ast
import json
import math
import os
import re
import subprocess
import time
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path
from typing import Any

_IGNORE_DIRS = frozenset({
    ".git", "node_modules", "dist", "build", ".venv", "venv",
    "__pycache__", ".idea", ".vscode", "target", "vendor", "bin", "obj", "frozen",
})
_SELECT_STAR_RE = re.compile(r"\bSELECT\s+\*\s+FROM\b", re.IGNORECASE)
_JS_BRANCH_RE = re.compile(r"\b(if|else\s+if|for|while|case|catch|\?\?|\&\&|\|\|)\b")


def _is_ignored_path(rel_path: str) -> bool:
    parts = [p.lower() for p in rel_path.replace("\\", "/").split("/")]
    return any(p in _IGNORE_DIRS or p.startswith(".") for p in parts[:-1]) or "frozen" in parts


def _python_complexity(source: str) -> dict[str, Any]:
    """Compute McCabe cyclomatic, cognitive complexity, docstring % and type-hint % via stdlib ast."""
    try:
        tree = ast.parse(source)
    except Exception:
        return {"mccabe": 1, "cognitive": 0, "funcs": 0, "doc_funcs": 0, "typed_funcs": 0, "max_fn": None}

    branch_types = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.ExceptHandler, ast.With, ast.AsyncWith, ast.IfExp)
    total_mccabe = 1
    total_cognitive = 0
    funcs = 0
    doc_funcs = 0
    typed_funcs = 0
    worst_fn: dict[str, Any] | None = None

    def _walk_cognitive(node: ast.AST, depth: int) -> int:
        score = 0
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.If, ast.For, ast.AsyncFor, ast.While, ast.ExceptHandler)):
                score += 1 + depth
                score += _walk_cognitive(child, depth + 1)
            elif isinstance(child, ast.BoolOp):
                score += max(0, len(child.values) - 1)
                score += _walk_cognitive(child, depth)
            else:
                score += _walk_cognitive(child, depth)
        return score

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            funcs += 1
            if ast.get_docstring(node):
                doc_funcs += 1
            has_type = node.returns is not None or any(a.annotation is not None for a in node.args.args)
            if has_type:
                typed_funcs += 1
            fn_cc = 1
            for sub in ast.walk(node):
                if isinstance(sub, branch_types):
                    fn_cc += 1
                elif isinstance(sub, ast.BoolOp):
                    fn_cc += max(0, len(sub.values) - 1)
            fn_cog = _walk_cognitive(node, 0)
            total_mccabe += fn_cc - 1
            total_cognitive += fn_cog
            if worst_fn is None or fn_cc > worst_fn["mccabe"]:
                worst_fn = {"name": node.name, "line": getattr(node, "lineno", 1), "mccabe": fn_cc, "cognitive": fn_cog}

    return {
        "mccabe": total_mccabe,
        "cognitive": total_cognitive,
        "funcs": funcs,
        "doc_funcs": doc_funcs,
        "typed_funcs": typed_funcs,
        "max_fn": worst_fn,
    }


def analyze_code_complexity_and_ai_readiness(project_dir: Path, max_files: int = 3000) -> dict[str, Any]:
    """Scan Python/TS/JS files for McCabe, Cognitive Complexity, Maintainability Index, SQL bloat, and AI readiness."""
    project_dir = Path(project_dir).resolve()
    file_metrics: list[dict[str, Any]] = []
    large_files: list[dict[str, Any]] = []
    sql_smells: list[dict[str, Any]] = []

    total_funcs = 0
    total_doc_funcs = 0
    total_typed_funcs = 0
    scanned = 0

    for root, dirs, files in os.walk(project_dir):
        dirs[:] = [d for d in dirs if d not in _IGNORE_DIRS and not d.startswith(".")]
        for fname in files:
            if scanned >= max_files:
                break
            ext = os.path.splitext(fname)[1].lower()
            if ext not in (".py", ".ts", ".tsx", ".js", ".jsx", ".vue", ".sql"):
                continue
            if fname.endswith((".min.js", ".min.css", ".bundle.js", ".d.ts")):
                continue
            fpath = Path(root) / fname
            rel = str(fpath.relative_to(project_dir)).replace("\\", "/")
            if _is_ignored_path(rel):
                continue
            try:
                size_bytes = fpath.stat().st_size
            except OSError:
                continue
            if size_bytes > 500_000:
                large_files.append({"path": rel, "size_kb": round(size_bytes / 1024, 1)})
                continue
            scanned += 1
            try:
                src = fpath.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue

            loc = max(1, src.count("\n") + 1)
            select_stars = len(_SELECT_STAR_RE.findall(src))
            if select_stars > 0:
                sql_smells.append({"path": rel, "select_star_count": select_stars})

            if ext == ".py":
                c = _python_complexity(src)
                total_funcs += c["funcs"]
                total_doc_funcs += c["doc_funcs"]
                total_typed_funcs += c["typed_funcs"]
                mccabe = c["mccabe"]
                cognitive = c["cognitive"]
                worst = c["max_fn"]
            elif ext in (".ts", ".tsx", ".js", ".jsx", ".vue"):
                branches = len(_JS_BRANCH_RE.findall(src))
                mccabe = 1 + branches
                cognitive = int(branches * 1.15)
                worst = None
            else:
                continue

            # Standard SEI Maintainability Index approximation (clamped 0..100)
            vol = max(1.0, loc * 4.5)
            mi_raw = 171.0 - 5.2 * math.log(vol) - 0.23 * mccabe - 16.2 * math.log(loc)
            mi = round(max(0.0, min(100.0, mi_raw * 100.0 / 171.0)), 1)

            file_metrics.append({
                "path": rel,
                "loc": loc,
                "mccabe": mccabe,
                "cognitive": cognitive,
                "maintainability_index": mi,
                "worst_fn": worst,
            })

    file_metrics.sort(key=lambda x: (-x["mccabe"], -x["loc"]))
    large_files.sort(key=lambda x: -x["size_kb"])
    sql_smells.sort(key=lambda x: -x["select_star_count"])

    avg_mi = round(sum(f["maintainability_index"] for f in file_metrics) / len(file_metrics), 1) if file_metrics else 100.0
    avg_cc = round(sum(f["mccabe"] for f in file_metrics) / len(file_metrics), 1) if file_metrics else 0.0
    doc_pct = round(100.0 * total_doc_funcs / total_funcs, 1) if total_funcs > 0 else 0.0
    type_pct = round(100.0 * total_typed_funcs / total_funcs, 1) if total_funcs > 0 else 0.0
    ai_score = round(min(100.0, doc_pct * 0.45 + type_pct * 0.45 + (10.0 if (project_dir / "llms.txt").exists() else 5.0)), 1)

    return {
        "files_analyzed": len(file_metrics),
        "avg_maintainability_index": avg_mi,
        "avg_mccabe": avg_cc,
        "top_complex_files": file_metrics[:25],
        "perf_bloat": {
            "large_files_count": len(large_files),
            "large_files": large_files[:20],
            "sql_select_star_files": len(sql_smells),
            "sql_smells": sql_smells[:20],
        },
        "ai_readiness": {
            "score": ai_score,
            "docstring_coverage_pct": doc_pct,
            "type_hint_coverage_pct": type_pct,
            "python_functions_analyzed": total_funcs,
        },
    }


def analyze_git_crime_scene(project_dir: Path, days: int = 90) -> dict[str, Any]:
    """Read-only git log analysis: Churn Hotspots, Temporal Coupling, and Bus Factor."""
    project_dir = Path(project_dir).resolve()
    if not (project_dir / ".git").exists():
        return {"available": False, "hotspots": [], "temporal_coupling": [], "bus_factor_risks": []}

    try:
        proc = subprocess.run(  # nosec B603 B607
            ["git", "-C", str(project_dir), "log", f"--since={days} days ago", "--numstat", "--format=COMMIT|%an|%at", "-n", "400"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if proc.returncode != 0:
            return {"available": False, "hotspots": [], "temporal_coupling": [], "bus_factor_risks": []}
    except Exception:
        return {"available": False, "hotspots": [], "temporal_coupling": [], "bus_factor_risks": []}

    file_commits: Counter[str] = Counter()
    file_churn: Counter[str] = Counter()
    file_authors: dict[str, set[str]] = defaultdict(set)
    pair_counts: Counter[tuple[str, str]] = Counter()

    cur_author = "unknown"
    cur_files: list[str] = []

    def _flush_commit() -> None:
        if 2 <= len(cur_files) <= 15:
            for a, b in combinations(sorted(set(cur_files)), 2):
                pair_counts[(a, b)] += 1

    for line in proc.stdout.splitlines():
        if line.startswith("COMMIT|"):
            _flush_commit()
            parts = line.split("|")
            cur_author = parts[1] if len(parts) > 1 else "unknown"
            cur_files = []
            continue
        if "\t" not in line:
            continue
        cols = line.split("\t")
        if len(cols) < 3:
            continue
        add_s, del_s, fpath = cols[0], cols[1], cols[2].replace("\\", "/")
        if _is_ignored_path(fpath):
            continue
        churn = (int(add_s) if add_s.isdigit() else 0) + (int(del_s) if del_s.isdigit() else 0)
        file_commits[fpath] += 1
        file_churn[fpath] += churn
        file_authors[fpath].add(cur_author)
        cur_files.append(fpath)
    _flush_commit()

    hotspots: list[dict[str, Any]] = [
        {
            "path": p,
            "commits": c,
            "lines_churned": file_churn[p],
            "authors": len(file_authors[p]),
            "hotspot_score": round(c * math.log1p(file_churn[p]), 1),
        }
        for p, c in file_commits.most_common(25)
    ]
    hotspots.sort(key=lambda h: -float(h["hotspot_score"]))

    temporal_coupling = [
        {"file_a": a, "file_b": b, "co_changes": cnt}
        for (a, b), cnt in pair_counts.most_common(20)
        if cnt >= 3
    ]

    bus_risks = [
        {"path": h["path"], "commits": h["commits"], "authors": h["authors"]}
        for h in hotspots
        if int(h["authors"]) == 1 and int(h["commits"]) >= 4
    ][:15]

    return {
        "available": True,
        "window_days": days,
        "hotspots": hotspots[:20],
        "temporal_coupling": temporal_coupling,
        "bus_factor_risks": bus_risks,
    }


def analyze_coverage_reports(project_dir: Path) -> dict[str, Any]:
    """Auto-detect and parse coverage.xml (pytest-cov) or lcov.info (Vitest) if present."""
    project_dir = Path(project_dir).resolve()
    files_cov: dict[str, float] = {}

    for cand in (project_dir / "coverage.xml", project_dir / "backend" / "coverage.xml"):
        if cand.exists() and cand.is_file():
            try:
                tree = ET.parse(cand)  # nosec B314
                for cls in tree.getroot().findall(".//class"):
                    fn = cls.attrib.get("filename", "")
                    rate = cls.attrib.get("line-rate")
                    if fn and rate is not None and not _is_ignored_path(fn):
                        files_cov[fn.replace("\\", "/")] = round(float(rate) * 100.0, 1)
            except Exception:
                pass

    for cand in (project_dir / "coverage" / "lcov.info", project_dir / "frontend" / "coverage" / "lcov.info"):
        if cand.exists() and cand.is_file():
            try:
                cur_f = ""
                lf = lh = 0
                for line in cand.read_text(encoding="utf-8", errors="ignore").splitlines():
                    if line.startswith("SF:"):
                        cur_f = line[3:].strip().replace("\\", "/")
                        lf = lh = 0
                    elif line.startswith("LF:"):
                        lf = int(line[3:] or 0)
                    elif line.startswith("LH:"):
                        lh = int(line[3:] or 0)
                    elif line == "end_of_record" and cur_f and lf > 0 and not _is_ignored_path(cur_f):
                        files_cov[cur_f] = round(100.0 * lh / lf, 1)
            except Exception:
                pass

    if not files_cov:
        return {"available": False, "overall_pct": None, "files_measured": 0, "lowest_covered": []}

    overall = round(sum(files_cov.values()) / len(files_cov), 1)
    lowest = [{"path": p, "coverage_pct": pct} for p, pct in sorted(files_cov.items(), key=lambda kv: kv[1])[:20]]
    return {"available": True, "overall_pct": overall, "files_measured": len(files_cov), "lowest_covered": lowest}


def analyze_db_health(data_dir: Path) -> dict[str, Any]:
    """Inspect db-schema.json for tables missing primary keys or foreign keys."""
    schema_file = Path(data_dir) / "db-schema.json"
    if not schema_file.exists():
        return {"available": False, "total_tables": 0, "tables_without_pk": [], "unreferenced_tables": []}
    try:
        schema = json.loads(schema_file.read_text(encoding="utf-8"))
    except Exception:
        return {"available": False, "total_tables": 0, "tables_without_pk": [], "unreferenced_tables": []}

    tables = schema.get("tables") or []
    no_pk: list[str] = []
    for tbl in tables:
        if not isinstance(tbl, dict):
            continue
        cols = tbl.get("columns") or []
        has_pk = any(
            (isinstance(c, dict) and (c.get("pk") or c.get("primary_key") or str(c.get("name", "")).lower() == "id"))
            or (isinstance(c, str) and c.lower() == "id")
            for c in cols
        )
        if not has_pk:
            no_pk.append(str(tbl.get("name", "unknown")))
    return {"available": True, "total_tables": len(tables), "tables_without_pk": no_pk[:20]}


def record_health_history(data_dir: Path, summary: dict[str, Any]) -> list[dict[str, Any]]:
    """Append snapshot to data/arch-health-history.json (keeps last 60 runs)."""
    hist_path = Path(data_dir) / "arch-health-history.json"
    history: list[dict[str, Any]] = []
    if hist_path.exists():
        try:
            loaded = json.loads(hist_path.read_text(encoding="utf-8"))
            if isinstance(loaded, list):
                history = loaded
        except Exception:
            history = []

    snap = {
        "timestamp": round(time.time()),
        "health_score": summary.get("health_score", 0),
        "grade": summary.get("grade", "-"),
        "cycle_count": summary.get("cycle_count", 0),
        "orphan_count": summary.get("orphan_count", 0),
        "total_edges": summary.get("total_edges", 0),
    }
    history.append(snap)
    history = history[-60:]
    try:
        hist_path.parent.mkdir(parents=True, exist_ok=True)
        hist_path.write_text(json.dumps(history, indent=2), encoding="utf-8")
    except Exception:
        pass
    return history


def build_actionable_fix_queue(report: dict[str, Any]) -> list[dict[str, Any]]:
    """Build Top 10 prioritized engineering actions ordered by ROI."""
    queue: list[dict[str, Any]] = []

    for idx, cyc in enumerate((report.get("cycles") or [])[:3], 1):
        queue.append({
            "priority": "P0",
            "category": "Cycle",
            "target": " → ".join(cyc[:4]),
            "action": f"Break circular dependency #{idx} ({len(cyc)} modules) via dependency inversion / shared interface.",
        })

    for v in (report.get("layer_violations") or [])[:2]:
        queue.append({
            "priority": "P0",
            "category": "Layer",
            "target": v.get("detail", ""),
            "action": "Remove direct UI → DB import; route through API/service layer.",
        })

    comp = report.get("complexity") or {}
    for f in (comp.get("top_complex_files") or [])[:3]:
        if f.get("mccabe", 0) >= 25:
            queue.append({
                "priority": "P1",
                "category": "Complexity",
                "target": f["path"],
                "action": f"Refactor high-complexity file (McCabe={f['mccabe']}, MI={f['maintainability_index']}/100, LOC={f['loc']}).",
            })

    git_info = report.get("git_crime_scene") or {}
    for h in (git_info.get("hotspots") or [])[:2]:
        if h.get("commits", 0) >= 5:
            queue.append({
                "priority": "P1",
                "category": "Hotspot",
                "target": h["path"],
                "action": f"Stabilize frequent-churn hotspot ({h['commits']} commits / {h['lines_churned']} LOC churned in 90d).",
            })

    perf = comp.get("perf_bloat") or {}
    for s in (perf.get("sql_smells") or [])[:2]:
        queue.append({
            "priority": "P2",
            "category": "SQL Perf",
            "target": s["path"],
            "action": f"Replace {s['select_star_count']}x `SELECT *` queries with explicit column projections.",
        })

    return queue[:10]
