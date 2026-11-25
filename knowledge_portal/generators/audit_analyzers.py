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
import hashlib
import json
import math
import os
import re
import subprocess
import time
import warnings
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path
from typing import Any

try:
    import tomllib  # Python 3.11+
except ImportError:  # pragma: no cover
    tomllib = None  # type: ignore[assignment]

_IGNORE_DIRS = frozenset({
    ".git", "node_modules", "dist", "dev-dist", "build", ".venv", "venv",
    "__pycache__", ".idea", ".vscode", "target", "vendor", "bin", "obj", "frozen",
})
_SELECT_STAR_RE = re.compile(r"\bSELECT\s+\*\s+FROM\b", re.IGNORECASE)
_JS_BRANCH_RE = re.compile(r"\b(if|else\s+if|for|while|case|catch|\?\?|\&\&|\|\|)\b")


def _is_ignored_path(rel_path: str) -> bool:
    parts = [p.lower() for p in rel_path.replace("\\", "/").split("/")]
    return any(p in _IGNORE_DIRS or p.startswith(".") for p in parts[:-1]) or "frozen" in parts


def _is_generated_asset(fname: str) -> bool:
    low = fname.lower()
    return low.endswith((".min.js", ".min.css", ".bundle.js", ".d.ts")) or (
        low.startswith("workbox-") and low.endswith(".js")
    )


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
            if _is_generated_asset(fname):
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


def _is_src_test_pair(path_a: str, path_b: str) -> bool:
    """Return True if (path_a, path_b) is an obvious production<->test file pair."""
    na = path_a.replace("\\", "/").lower()
    nb = path_b.replace("\\", "/").lower()
    test_tokens = ("/tests/", "/test/", "test_", ".test.", ".spec.", "_test.")
    a_is_test = any(t in na for t in test_tokens)
    b_is_test = any(t in nb for t in test_tokens)
    if a_is_test == b_is_test:
        return False
    src_p, tst_p = (nb, na) if a_is_test else (na, nb)
    src_stem = Path(src_p).stem
    tst_stem = Path(tst_p).stem
    if not src_stem:
        return False
    if tst_stem in (f"test_{src_stem}", f"{src_stem}_test", f"{src_stem}.test", f"{src_stem}.spec"):
        return True
    return len(src_stem) >= 3 and src_stem in tst_stem


def _build_direct_import_pairs(graph_data: dict[str, Any] | None) -> set[tuple[str, str]]:
    """Build undirected set of normalized file-path pairs directly connected in graph.json."""
    if not isinstance(graph_data, dict):
        return set()
    id_to_path: dict[str, str] = {}
    for n in graph_data.get("nodes") or []:
        if isinstance(n, dict) and n.get("id") is not None:
            nid = str(n["id"])
            raw = str(n.get("path") or n.get("label") or nid).replace("\\", "/").lstrip("./").lower()
            id_to_path[nid] = raw
    pairs: set[tuple[str, str]] = set()
    for e in graph_data.get("edges") or graph_data.get("links") or []:
        if not isinstance(e, dict):
            continue
        s_raw = str(e.get("source", ""))
        t_raw = str(e.get("target", ""))
        sp = id_to_path.get(s_raw, s_raw.replace("\\", "/").lstrip("./").lower())
        tp = id_to_path.get(t_raw, t_raw.replace("\\", "/").lstrip("./").lower())
        if sp and tp and sp != tp:
            a, b = (sp, tp) if sp < tp else (tp, sp)
            pairs.add((a, b))
    return pairs


def _fast_file_max_mccabe(project_dir: Path, rel_path: str) -> int:
    """Compute max function McCabe complexity for a Python file (fallback 1)."""
    if not rel_path.endswith(".py"):
        return 1
    fpath = project_dir / rel_path
    if not fpath.is_file():
        return 1
    try:
        tree = ast.parse(fpath.read_text(encoding="utf-8", errors="ignore"))
    except (OSError, SyntaxError, ValueError):
        return 1
    max_cc = 1
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            cc = 1
            for sub in ast.walk(node):
                if isinstance(sub, (ast.If, ast.For, ast.AsyncFor, ast.While, ast.ExceptHandler, ast.IfExp, ast.comprehension)):
                    cc += 1
                elif isinstance(sub, ast.BoolOp):
                    cc += max(0, len(sub.values) - 1)
            if cc > max_cc:
                max_cc = cc
    return max_cc


def analyze_git_crime_scene(
    project_dir: Path,
    days: int = 90,
    *,
    complexity: dict[str, Any] | None = None,
    graph_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Read-only git log analysis: Churn Hotspots, CodeScene Risk (churn x max_mccabe), Hidden Temporal Coupling, and Bus Factor."""
    project_dir = Path(project_dir).resolve()
    empty_res: dict[str, Any] = {
        "available": False,
        "hotspots": [],
        "temporal_coupling": [],
        "hidden_temporal_coupling": [],
        "hidden_temporal_coupling_count": 0,
        "max_codescene_risk": 0.0,
        "top_codescene_hotspots": [],
        "bus_factor_risks": [],
    }
    if not (project_dir / ".git").exists():
        return empty_res

    try:
        proc = subprocess.run(  # nosec B603 B607
            ["git", "-C", str(project_dir), "log", f"--since={days} days ago", "--numstat", "--format=COMMIT|%an|%at", "-n", "400"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if proc.returncode != 0:
            return empty_res
    except Exception:
        return empty_res

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

    # Build path -> max_mccabe lookup from complexity report
    mccabe_by_path: dict[str, int] = {}
    for cf in (complexity or {}).get("top_complex_files") or []:
        if isinstance(cf, dict) and cf.get("path"):
            cpath = str(cf["path"]).replace("\\", "/").lstrip("./")
            worst = cf.get("worst_fn") or {}
            mc_val = int(worst.get("mccabe") or cf.get("mccabe") or 1)
            mccabe_by_path[cpath] = max(1, mc_val)

    hotspots: list[dict[str, Any]] = []
    for p, c in file_commits.most_common(25):
        p_norm = p.replace("\\", "/").lstrip("./")
        churn_90d = int(file_churn[p])
        max_mc = mccabe_by_path.get(p_norm)
        if max_mc is None:
            max_mc = _fast_file_max_mccabe(project_dir, p_norm)
        cs_risk = round(float(churn_90d * max_mc), 1)
        hotspots.append({
            "path": p,
            "commits": c,
            "lines_churned": churn_90d,
            "authors": len(file_authors[p]),
            "max_mccabe": max_mc,
            "codescene_risk": cs_risk,
            "hotspot_score": round(c * math.log1p(churn_90d), 1),
        })
    hotspots.sort(key=lambda h: -float(h["hotspot_score"]))

    temporal_coupling = [
        {"file_a": a, "file_b": b, "co_changes": cnt}
        for (a, b), cnt in pair_counts.most_common(20)
        if cnt >= 3
    ]

    direct_edges = _build_direct_import_pairs(graph_data)
    hidden_temporal_coupling: list[dict[str, Any]] = []
    for (a, b), cnt in pair_counts.most_common(40):
        if cnt < 3:
            continue
        an = a.replace("\\", "/").lstrip("./").lower()
        bn = b.replace("\\", "/").lstrip("./").lower()
        pair_key = (an, bn) if an < bn else (bn, an)
        if pair_key in direct_edges:
            continue
        if _is_src_test_pair(an, bn):
            continue
        denom = max(1, min(file_commits.get(a, cnt), file_commits.get(b, cnt)))
        strength = round(min(1.0, cnt / denom), 2)
        hidden_temporal_coupling.append({
            "file_a": a,
            "file_b": b,
            "co_changes": cnt,
            "coupling_strength": strength,
            "coupling_ratio_pct": round(strength * 100.0, 1),
            "has_direct_import": False,
        })
        if len(hidden_temporal_coupling) >= 20:
            break

    bus_risks = [
        {"path": h["path"], "commits": h["commits"], "authors": h["authors"]}
        for h in hotspots
        if int(h["authors"]) == 1 and int(h["commits"]) >= 4
    ][:15]

    top_cs_hotspots = sorted(hotspots, key=lambda h: -float(h["codescene_risk"]))[:10]
    max_cs_risk = float(top_cs_hotspots[0]["codescene_risk"]) if top_cs_hotspots else 0.0

    return {
        "available": True,
        "window_days": days,
        "hotspots": hotspots[:20],
        "temporal_coupling": temporal_coupling,
        "hidden_temporal_coupling": hidden_temporal_coupling,
        "hidden_temporal_coupling_count": len(hidden_temporal_coupling),
        "max_codescene_risk": max_cs_risk,
        "top_codescene_hotspots": top_cs_hotspots,
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
        return {"available": False, "overall_pct": None, "files_measured": 0, "by_domain": [], "lowest_covered": []}

    dom_vals: dict[str, list[float]] = defaultdict(list)
    for fp, pct in files_cov.items():
        dom_vals[_domain_bucket(fp)].append(pct)
    by_domain = [
        {"domain": dom, "coverage_pct": round(sum(vals) / len(vals), 1), "files_measured": len(vals)}
        for dom, vals in sorted(dom_vals.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    ]
    overall = round(sum(files_cov.values()) / len(files_cov), 1)
    lowest = [{"path": p, "coverage_pct": pct} for p, pct in sorted(files_cov.items(), key=lambda kv: kv[1])[:20]]
    return {
        "available": True,
        "overall_pct": overall,
        "files_measured": len(files_cov),
        "by_domain": by_domain[:30],
        "lowest_covered": lowest,
    }


def analyze_db_health(data_dir: Path) -> dict[str, Any]:
    """Inspect db-schema.json for tables missing primary keys, hypertables, and CAGGs."""
    schema_file = Path(data_dir) / "db-schema.json"
    if not schema_file.exists():
        return {
            "available": False,
            "total_tables": 0,
            "tables_without_pk": [],
            "unreferenced_tables": [],
            "hypertables_count": 0,
            "caggs_count": 0,
            "compressed_count": 0,
            "hypertables": [],
            "caggs": [],
        }
    try:
        schema = json.loads(schema_file.read_text(encoding="utf-8"))
    except Exception:
        return {
            "available": False,
            "total_tables": 0,
            "tables_without_pk": [],
            "unreferenced_tables": [],
            "hypertables_count": 0,
            "caggs_count": 0,
            "compressed_count": 0,
            "hypertables": [],
            "caggs": [],
        }

    tables = schema.get("tables") or []
    no_pk: list[str] = []
    hypertables: list[dict[str, Any]] = []
    caggs: list[dict[str, Any]] = []
    compressed_count = 0
    for tbl in tables:
        if not isinstance(tbl, dict):
            continue
        tname = str(tbl.get("name", "unknown"))
        is_cagg = bool(tbl.get("is_cagg"))
        is_ht = bool(tbl.get("is_hypertable"))
        is_view = bool(tbl.get("is_view"))
        if tbl.get("compression_enabled"):
            compressed_count += 1
        if is_cagg:
            caggs.append({
                "name": tname,
                "source_table": tbl.get("source_table"),
            })
        elif is_ht:
            hypertables.append({
                "name": tname,
                "time_column": tbl.get("hypertable_time_column"),
                "chunk_interval": tbl.get("chunk_interval"),
                "compression_enabled": bool(tbl.get("compression_enabled")),
            })
        if is_view or is_cagg:
            continue
        cols = tbl.get("columns") or []
        has_pk = any(
            (isinstance(c, dict) and (c.get("pk") or c.get("primary_key") or str(c.get("name", "")).lower() == "id"))
            or (isinstance(c, str) and c.lower() == "id")
            for c in cols
        )
        if not has_pk:
            no_pk.append(tname)
    return {
        "available": True,
        "total_tables": len(tables),
        "tables_without_pk": no_pk[:20],
        "hypertables_count": len(hypertables),
        "caggs_count": len(caggs),
        "compressed_count": compressed_count,
        "hypertables": hypertables[:30],
        "caggs": caggs[:30],
    }


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
    """Build Top 12 prioritized engineering actions ordered by ROI (Health Engine 4.0)."""
    queue: list[dict[str, Any]] = []
    hv4 = report.get("health_v4") or {}

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

    owasp = hv4.get("owasp_audit") or {}
    for finding in (owasp.get("findings") or [])[:3]:
        if finding.get("severity") in ("CRITICAL", "HIGH"):
            queue.append({
                "priority": "P0",
                "category": "OWASP",
                "target": f"{finding.get('path', '')}:{finding.get('line', 1)}",
                "action": f"[{finding.get('rule', 'SEC')}] {finding.get('detail', 'Remediate security vulnerability.')}",
            })

    rel_ast = hv4.get("reliability_ast") or {}
    for ab in (rel_ast.get("async_blocking") or [])[:2]:
        queue.append({
            "priority": "P0",
            "category": "Reliability",
            "target": f"{ab.get('path', '')}:{ab.get('line', 1)}",
            "action": f"Replace blocking `{ab.get('call', 'io')}` inside async function `{ab.get('func', '')}` with async equivalent.",
        })

    cs_risk = hv4.get("codescene_risk") or {}
    for r in (cs_risk.get("top_risks") or [])[:3]:
        if float(r.get("risk_score", 0)) >= 10.0:
            queue.append({
                "priority": "P1",
                "category": "CodeScene Risk",
                "target": r["path"],
                "action": f"De-risk high-churn complex file (Risk={r['risk_score']}, McCabe={r['mccabe']}, Commits={r['commits']}, Cov={r['coverage_pct']}%).",
            })

    api_gov = hv4.get("api_governance") or {}
    for rt in (api_gov.get("unprotected_mutating_routes") or [])[:2]:
        queue.append({
            "priority": "P1",
            "category": "API Auth",
            "target": f"{rt.get('path', '')}:{rt.get('line', 1)}",
            "action": f"Add authentication dependency (`Depends`) to mutating route `{rt.get('method', 'POST')} {rt.get('route', '')}`.",
        })

    db_gov = hv4.get("db_governance") or {}
    for n1 in (db_gov.get("n_plus_one_loops") or [])[:2]:
        queue.append({
            "priority": "P1",
            "category": "DB N+1",
            "target": f"{n1.get('path', '')}:{n1.get('line', 1)}",
            "action": f"Batch query `{n1.get('call', 'execute')}` executed inside loop to eliminate N+1 DB round-trips.",
        })

    comp = report.get("complexity") or {}
    for f in (comp.get("top_complex_files") or [])[:2]:
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

    sc_ai = hv4.get("supply_chain_and_ai") or {}
    for bomb in (sc_ai.get("context_bombs") or [])[:2]:
        queue.append({
            "priority": "P2",
            "category": "AI Context",
            "target": bomb["path"],
            "action": f"Split oversized file ({bomb['loc']} LOC / {bomb['size_kb']} KB) for better modularity & LLM context fit.",
        })

    return queue[:12]


_PY_EVAL_EXEC_FALLBACK_RE = re.compile(r"(?<![.\w])(?:(?:builtins|__builtins__)\.)?(?:eval|exec)\s*\(")
_JS_EVAL_RE = re.compile(r"(?<![.\w$])(?:(?:window|globalThis)\.)?eval\s*\(")
_SEC_PATTERNS = [
    ("PICKLE_LOADS", re.compile(r"\bpickle\.loads?\s*\(")),
    ("SHELL_TRUE", re.compile(r"shell\s*=\s*True")),
    ("UNSAFE_YAML", re.compile(r"\byaml\.load\s*\([^)]*\)(?!.*SafeLoader)")),
]


def _python_docstring_lines(tree: ast.AST) -> set[int]:
    """Return 1-based line numbers belonging to module, class, or function docstrings."""
    doc_lines: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.body and isinstance(node.body[0], ast.Expr):
                val = node.body[0].value
                if isinstance(val, ast.Constant) and isinstance(val.value, str):
                    start = getattr(node.body[0], "lineno", 0)
                    end = getattr(node.body[0], "end_lineno", start) or start
                    if start > 0:
                        doc_lines.update(range(start, end + 1))
    return doc_lines


def _strip_python_comment(line: str) -> str:
    """Strip trailing # comment outside string literals on a single Python line."""
    in_quote: str | None = None
    escaped = False
    for idx, ch in enumerate(line):
        if escaped:
            escaped = False
            continue
        if in_quote is not None:
            if ch == "\\":
                escaped = True
            elif ch == in_quote:
                in_quote = None
            continue
        if ch in ("'", '"'):
            in_quote = ch
        elif ch == "#":
            return line[:idx]
    return line


def _strip_js_comments(src: str) -> list[tuple[int, str]]:
    """Strip /* ... */ block comments and // line comments from JS/TS/Vue source, preserving 1-based line numbers."""
    out: list[tuple[int, str]] = []
    in_block = False
    in_template = False
    for lineno, line in enumerate(src.splitlines(), 1):
        buf: list[str] = []
        in_quote: str | None = None
        escaped = False
        i = 0
        n = len(line)
        while i < n:
            ch = line[i]
            nxt = line[i + 1] if i + 1 < n else ""
            if in_block:
                if ch == "*" and nxt == "/":
                    in_block = False
                    i += 2
                else:
                    i += 1
                continue
            if escaped:
                buf.append(ch)
                escaped = False
                i += 1
                continue
            if in_template:
                buf.append(ch)
                if ch == "\\":
                    escaped = True
                elif ch == "`":
                    in_template = False
                i += 1
                continue
            if in_quote is not None:
                buf.append(ch)
                if ch == "\\":
                    escaped = True
                elif ch == in_quote:
                    in_quote = None
                i += 1
                continue
            if ch == "/" and nxt == "*":
                in_block = True
                i += 2
                continue
            if ch == "/" and nxt == "/":
                break
            if ch == "`":
                in_template = True
                buf.append(ch)
                i += 1
                continue
            if ch in ("'", '"'):
                in_quote = ch
                buf.append(ch)
                i += 1
                continue
            buf.append(ch)
            i += 1
        out.append((lineno, "".join(buf)))
    return out


def _scan_security_hygiene(src: str, ext: str, rel: str) -> list[dict[str, Any]]:
    """Language-aware security quick-scan avoiding false positives on docstrings, comments, and .exec()/.eval() method calls."""
    findings: list[dict[str, Any]] = []
    raw_lines = src.splitlines()
    if ext == ".py":
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", SyntaxWarning)
                tree = ast.parse(src)
        except SyntaxError:
            for lineno, line in enumerate(raw_lines, 1):
                if "nosec" in line:
                    continue
                code = _strip_python_comment(line).strip()
                if not code:
                    continue
                if _PY_EVAL_EXEC_FALLBACK_RE.search(code):
                    findings.append({"rule": "EVAL_EXEC", "path": rel, "line": lineno})
                    continue
                for rule_name, rx in _SEC_PATTERNS:
                    if rx.search(code):
                        findings.append({"rule": rule_name, "path": rel, "line": lineno})
                        break
            return findings

        doc_lines = _python_docstring_lines(tree)
        eval_lines: set[int] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                is_eval_exec = (
                    isinstance(node.func, ast.Name) and node.func.id in ("eval", "exec")
                ) or (
                    isinstance(node.func, ast.Attribute)
                    and node.func.attr in ("eval", "exec")
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id in ("builtins", "__builtins__")
                )
                if is_eval_exec:
                    ln = getattr(node, "lineno", 0)
                    if 1 <= ln <= len(raw_lines) and "nosec" not in raw_lines[ln - 1]:
                        eval_lines.add(ln)

        for ln in sorted(eval_lines):
            findings.append({"rule": "EVAL_EXEC", "path": rel, "line": ln})

        for lineno, line in enumerate(raw_lines, 1):
            if lineno in doc_lines or lineno in eval_lines or "nosec" in line:
                continue
            code = _strip_python_comment(line).strip()
            if not code:
                continue
            for rule_name, rx in _SEC_PATTERNS:
                if rx.search(code):
                    findings.append({"rule": rule_name, "path": rel, "line": lineno})
                    break
        return findings

    # JS / TS / JSX / TSX / Vue
    for lineno, code in _strip_js_comments(src):
        raw = raw_lines[lineno - 1] if lineno <= len(raw_lines) else ""
        s = code.strip()
        if not s or "nosec" in raw:
            continue
        if _JS_EVAL_RE.search(s):
            findings.append({"rule": "EVAL_EXEC", "path": rel, "line": lineno})
            continue
        for rule_name, rx in _SEC_PATTERNS:
            if rx.search(s):
                findings.append({"rule": rule_name, "path": rel, "line": lineno})
                break
    return findings


def analyze_extended_health_checks(project_dir: Path, max_files: int = 2000) -> dict[str, Any]:
    """ADR-075: 4 additional zero-dep health checks:
    1. Code Clones (6-line normalized block hashes)
    2. Dependency Hygiene (unpinned deps in requirements/pyproject/package.json)
    3. Security Hygiene Quick-Scan (eval/exec/pickle/shell=True/unsafe yaml in non-test code)
    4. Test-to-Code Ratio by Domain
    """
    project_dir = Path(project_dir).resolve()
    block_hashes: dict[str, list[str]] = defaultdict(list)
    sec_findings: list[dict[str, Any]] = []
    prod_by_domain: Counter[str] = Counter()
    test_by_domain: Counter[str] = Counter()
    scanned = 0

    for root, dirs, files in os.walk(project_dir):
        dirs[:] = [d for d in dirs if d not in _IGNORE_DIRS and not d.startswith(".")]
        for fname in files:
            if scanned >= max_files:
                break
            ext = os.path.splitext(fname)[1].lower()
            if ext not in (".py", ".ts", ".tsx", ".js", ".jsx", ".vue"):
                continue
            if _is_generated_asset(fname):
                continue
            fpath = Path(root) / fname
            rel = str(fpath.relative_to(project_dir)).replace("\\", "/")
            if _is_ignored_path(rel):
                continue
            scanned += 1
            parts = rel.split("/")
            dom = f"{parts[0]}/{parts[1]}" if len(parts) >= 2 else parts[0]
            is_test = any(h in f"/{rel.lower()}" for h in ("/tests/", "/test/", "test_", ".spec.", ".test."))
            if is_test:
                test_by_domain[dom] += 1
            else:
                prod_by_domain[dom] += 1

            try:
                if fpath.stat().st_size > 400_000:
                    continue
                src = fpath.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue

            # 1. Security quick-scan (production code only)
            if not is_test:
                sec_findings.extend(_scan_security_hygiene(src, ext, rel))

            # 2. 6-line normalized clone detection
            norm_lines = [
                re.sub(r"\s+", " ", ln.strip())
                for ln in src.splitlines()
                if len(ln.strip()) >= 18 and not ln.strip().startswith(("#", "//", "import ", "from ", "*"))
            ]
            seen_in_file: set[str] = set()
            for i in range(0, max(0, len(norm_lines) - 5), 3):
                sig = "\n".join(norm_lines[i : i + 6])
                if sig not in seen_in_file:
                    seen_in_file.add(sig)
                    block_hashes[sig].append(rel)

    clones: list[dict[str, Any]] = [
        {"files": sorted(set(flist))[:5], "occurrences": len(set(flist)), "preview": sig.splitlines()[0][:90]}
        for sig, flist in block_hashes.items()
        if len(set(flist)) >= 2
    ]
    clones.sort(key=lambda c: -int(c["occurrences"]))

    # 3. Dependency hygiene (unpinned deps)
    unpinned: list[dict[str, str]] = []
    for req_file in list(project_dir.glob("requirements*.txt")) + list(project_dir.glob("backend/requirements*.txt")):
        if req_file.is_file():
            for ln in req_file.read_text(encoding="utf-8", errors="ignore").splitlines():
                s = ln.strip()
                if not s or s.startswith(("#", "-")):
                    continue
                if "==" not in s:
                    unpinned.append({"file": str(req_file.relative_to(project_dir)).replace("\\", "/"), "dep": s[:60]})
    for pkg_file in (project_dir / "package.json", project_dir / "frontend" / "package.json"):
        if pkg_file.is_file():
            try:
                pj = json.loads(pkg_file.read_text(encoding="utf-8"))
                for sec in ("dependencies", "devDependencies"):
                    for k, v in (pj.get(sec) or {}).items():
                        if str(v).strip() in ("*", "latest"):
                            unpinned.append({"file": str(pkg_file.relative_to(project_dir)).replace("\\", "/"), "dep": f"{k}:{v}"})
            except Exception:
                pass

    # 4. Test-to-code ratio
    total_prod = sum(prod_by_domain.values())
    total_test = sum(test_by_domain.values())
    ratio_pct = round(100.0 * total_test / total_prod, 1) if total_prod > 0 else 0.0

    return {
        "code_clones": {"count": len(clones), "top_clones": clones[:15]},
        "dependency_hygiene": {"unpinned_count": len(unpinned), "unpinned": unpinned[:20]},
        "security_hygiene": {"findings_count": len(sec_findings), "findings": sec_findings[:25]},
        "test_ratio": {"prod_files": total_prod, "test_files": total_test, "ratio_pct": ratio_pct},
    }


# ═══════════════════════════════════════════════════════════════════════════
# ADR-075 — Health Engine 4.0 (8 Zero-Dependency Python Stdlib Checks)
# ═══════════════════════════════════════════════════════════════════════════

_SECRET_REGEXES: list[tuple[str, re.Pattern[str], str]] = [
    ("AWS_ACCESS_KEY", re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "CRITICAL"),
    ("GITHUB_TOKEN", re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{30,}\b"), "CRITICAL"),
    ("PRIVATE_KEY_PEM", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"), "CRITICAL"),
    ("HARDCODED_JWT", re.compile(r"\beyJ[A-Za-z0-9_-]{18,}\.eyJ[A-Za-z0-9_-]{18,}\.[A-Za-z0-9_-]{10,}\b"), "HIGH"),
]
_SECRET_VAR_RE = re.compile(r"(?:secret|token|api_?key|passwd|password|private_?key)", re.IGNORECASE)
_SECRET_PLACEHOLDER_HINTS = ("example", "changeme", "your_", "dummy", "placeholder", "xxxx", "test_", "fake", "sample", "localhost")
_VERIFY_FALSE_RE = re.compile(r"\bverify\s*=\s*False\b")
_CORS_WILDCARD_RE = re.compile(r"""allow_origins\s*=\s*\[\s*["']\*["']\s*\]|Access-Control-Allow-Origin["']?\s*[:,]\s*["']\*["']""", re.IGNORECASE)
_XSS_HTML_RE = re.compile(r"\b(?:v-html\s*=|dangerouslySetInnerHTML|\.innerHTML\s*=)")
_CONSOLE_LOG_RE = re.compile(r"\bconsole\.log\s*\(")
_PROBE_HEALTH_RE = re.compile(r"""["'](?:/api(?:/v\d+)?)?/healthz?["']""")
_PROBE_READY_RE = re.compile(r"""["'](?:/api(?:/v\d+)?)?/readyz?["']""")
_UNBOUNDED_SELECT_RE = re.compile(r"""["']\s*SELECT\s+(?!COUNT\s*\(|SUM\s*\(|MAX\s*\(|MIN\s*\(|AVG\s*\(|1\b)[^"'\n]{4,140}\bFROM\s+[a-zA-Z_][a-zA-Z0-9_]*[^"'\n]*["']""", re.IGNORECASE)
_CLI_PATH_HINTS = ("cli", "script", "scripts/", "tools/", "manage.py", "__main__.py", "bin/")
_PUBLIC_ROUTE_HINTS = ("/login", "/logout", "/auth", "/token", "/register", "/signup", "/health", "/ready", "/webhook", "/metrics", "/docs", "/openapi")
_AUTH_PARAM_HINTS = ("depends", "security", "auth", "current_user", "user", "token", "api_key", "session", "permission", "guard")
_HTTP_TIMEOUT_CALLS = frozenset({"get", "post", "put", "delete", "patch", "request", "head", "options"})
_HTTP_CLIENTS = frozenset({"requests", "httpx"})
_SUBPROCESS_CALLS = frozenset({"run", "call", "check_output", "check_call"})
_DB_QUERY_METHODS = frozenset({"execute", "executemany", "fetchall", "fetchone", "fetchmany", "query", "exec"})
_DB_RECEIVER_HINTS = ("db", "conn", "cursor", "cur", "session", "sess", "engine", "pool", "tx", "repo")
_LOCKFILE_NAMES = ("poetry.lock", "uv.lock", "package-lock.json", "pnpm-lock.yaml", "yarn.lock", "Pipfile.lock", "requirements.lock")


def _shannon_entropy(s: str) -> float:
    if not s:
        return 0.0
    counts = Counter(s)
    n = len(s)
    return -sum((c / n) * math.log2(c / n) for c in counts.values())


def _is_test_rel(rel: str) -> bool:
    low = f"/{rel.lower()}"
    return any(h in low for h in ("/tests/", "/test/", "/test_", "test_", "_test.py", ".spec.", ".test.", "conftest.py"))


_TEST_SUBDIR_SKIP = frozenset({"unit", "integration", "e2e", "functional", "fixtures", "helpers", "mocks", "__tests__"})
_ASYNC_BLOCKING_PATH_METHODS = frozenset({"read_text", "write_text", "read_bytes", "write_bytes"})
_ASYNC_BLOCKING_SUBPROCESS = frozenset({"run", "call", "check_output", "check_call", "popen"})
_ASYNC_BLOCKING_OS = frozenset({"system", "popen"})
_ASYNC_BLOCKING_SHUTIL = frozenset({"copy", "copy2", "copytree", "rmtree", "move"})
_UNCLOSED_RESOURCE_RECVS = frozenset({"sqlite3", "psycopg2", "httpx", "tempfile"})

# JS / TS / Vue Runtime Antipatterns (ADR-080 P0.2, 100% stdlib)
_VUE_TEMPLATE_RE = re.compile(r"<template[^>]*>(.*?)</template>", re.IGNORECASE | re.DOTALL)
_VUE_VFOR_TAG_RE = re.compile(r"<[a-zA-Z][a-zA-Z0-9_-]*\b[^>]*\bv-for\s*=[^>]*>", re.DOTALL)
_VUE_KEY_ATTR_RE = re.compile(r"(?::key|v-bind:key)\s*=", re.IGNORECASE)
_VUE_PROP_MUTATION_RE = re.compile(r"\bprops\.[a-zA-Z_$][a-zA-Z0-9_$]*(?:\s*(?:=(?!=)|\+=|-=|\*=|/=)|\.(?:push|pop|splice|shift|unshift|sort|reverse)\s*\()")
_JS_SET_INTERVAL_RE = re.compile(r"\bsetInterval\s*\(")
_JS_ADD_LISTENER_RE = re.compile(r"\b(?:window|document)\.addEventListener\s*\(")
_TS_FLOATING_PROMISE_RE = re.compile(r"^\s*(?:fetch|axios\.(?:get|post|put|patch|delete|request)|api\.(?:get|post|put|patch|delete|request))\s*\(")


def _domain_bucket(rel: str) -> str:
    parts = [p for p in rel.replace("\\", "/").split("/") if p]
    if not parts:
        return "root"
    # ADR-080 P0.1: Map centralized test folders to production domain structure
    if len(parts) >= 3 and parts[0] == "backend" and parts[1] in ("tests", "test"):
        sub = [p for p in parts[2:-1] if p.lower() not in _TEST_SUBDIR_SKIP]
        if sub:
            return f"backend/app/{sub[0]}"
        return "backend/app"
    if len(parts) >= 3 and parts[0] == "frontend" and parts[1] in ("tests", "test", "__tests__"):
        sub = [p for p in parts[2:-1] if p.lower() not in _TEST_SUBDIR_SKIP]
        if sub:
            return f"frontend/src/{sub[0]}"
        return "frontend/src"
    if len(parts) >= 3 and parts[0] in ("backend", "frontend", "src", "packages"):
        return f"{parts[0]}/{parts[1]}/{parts[2]}" if parts[1] in ("app", "src") else f"{parts[0]}/{parts[1]}"
    if len(parts) >= 2:
        return f"{parts[0]}/{parts[1]}"
    return parts[0]


def _resolve_test_domain(rel: str, prod_domains: set[str]) -> str:
    """Resolve a test file path to the best matching production domain bucket (ADR-080 P0.1)."""
    base = _domain_bucket(rel)
    if base in prod_domains:
        return base

    low_rel = rel.replace("\\", "/").lower()
    parts = [p for p in low_rel.split("/") if p]
    stem = Path(parts[-1]).stem if parts else ""
    stem_clean = re.sub(r"^(?:test_)|(?:_test|\.spec|\.test)$", "", stem)
    stem_tokens = [t for t in re.split(r"[_\-.]+", stem_clean) if len(t) >= 2]

    # Prefer domains sharing the same top-level root (backend/frontend/etc.)
    root_prefix = parts[0] if parts else ""
    scoped = [d for d in prod_domains if d.startswith(f"{root_prefix}/")] or list(prod_domains)

    # 1. Exact folder token match in test path against prod domain leaf
    folder_tokens = [p for p in parts[:-1] if p not in _TEST_SUBDIR_SKIP and p not in ("tests", "test", "backend", "frontend")]
    for tok in folder_tokens:
        for d in sorted(scoped):
            leaf = d.rsplit("/", 1)[-1].lower()
            if tok == leaf or tok == leaf.rstrip("s") or leaf == f"{tok}s":
                return d

    # 2. Filename stem token match against prod domain leaf
    for tok in stem_tokens:
        for d in sorted(scoped):
            leaf = d.rsplit("/", 1)[-1].lower()
            if tok == leaf or tok == leaf.rstrip("s") or leaf == f"{tok}s":
                return d

    # 3. Domain-specific prefix heuristics (e.g., backend/tests/test_x.py -> backend/app/services or backend/app)
    if root_prefix == "backend":
        for fallback in ("backend/app/services", "backend/app/api", "backend/app/core", "backend/app"):
            if fallback in prod_domains:
                if "api" in stem_tokens or "route" in stem_tokens or "endpoint" in stem_tokens:
                    if "backend/app/api" in prod_domains:
                        return "backend/app/api"
                if "core" in stem_tokens or "config" in stem_tokens or "auth" in stem_tokens:
                    if "backend/app/core" in prod_domains:
                        return "backend/app/core"
                return fallback
    elif root_prefix == "frontend":
        for fallback in ("frontend/src/components", "frontend/src/stores", "frontend/src/views", "frontend/src"):
            if fallback in prod_domains:
                return fallback
    elif scoped:
        # Generic repo (e.g. tests/unit/test_foo.py -> pkg/generators etc.)
        for tok in stem_tokens:
            for d in sorted(prod_domains):
                if tok in d.lower():
                    return d
        return sorted(prod_domains)[0]

    return base


def _scan_js_vue_antipatterns(rel: str, src: str, ext: str) -> list[dict[str, Any]]:
    """Stdlib regex/structural detector for JS/TS/Vue runtime bugs (ADR-080 P0.2)."""
    findings: list[dict[str, Any]] = []
    lines = src.splitlines()

    def _has_ignore(lineno: int) -> bool:
        if 1 <= lineno <= len(lines):
            ln = lines[lineno - 1]
            return "nosec" in ln or "eslint-disable" in ln
        return False

    # 1. Vue template: v-for without :key / v-bind:key
    if ext == ".vue":
        for tmpl_m in _VUE_TEMPLATE_RE.finditer(src):
            tmpl_start_line = src[: tmpl_m.start()].count("\n") + 1
            tmpl_body = tmpl_m.group(1)
            for tag_m in _VUE_VFOR_TAG_RE.finditer(tmpl_body):
                tag_txt = tag_m.group(0)
                if not _VUE_KEY_ATTR_RE.search(tag_txt):
                    lineno = tmpl_start_line + tmpl_body[: tag_m.start()].count("\n")
                    if not _has_ignore(lineno):
                        findings.append({
                            "language": "vue",
                            "severity": "HIGH",
                            "rule": "VUE_VFOR_NO_KEY",
                            "path": rel,
                            "line": lineno,
                            "detail": "`v-for` directive used without `:key` attribute.",
                            "remediation": "Add a stable `:key=\"item.id\"` to the `v-for` element to prevent DOM patching bugs.",
                        })

    # 2. Direct prop mutation & floating promises (line-level)
    for lineno, line in enumerate(lines, 1):
        s = line.strip()
        if not s or s.startswith(("//", "/*", "*")) or _has_ignore(lineno):
            continue
        if _VUE_PROP_MUTATION_RE.search(s):
            findings.append({
                "language": "vue" if ext == ".vue" else "ts",
                "severity": "HIGH",
                "rule": "VUE_PROP_MUTATION",
                "path": rel,
                "line": lineno,
                "detail": "Direct mutation of `props.*` detected.",
                "remediation": "Emit an event (`emit('update:...')`) or clone into local reactive state instead of mutating props.",
            })
        if _TS_FLOATING_PROMISE_RE.search(line):
            # Check if chained with .then / .catch on this or next line
            next_ln = lines[lineno].strip() if lineno < len(lines) else ""
            if not any(tok in s for tok in (".then(", ".catch(", ".finally(", "await ", "return ", "void ")) and not next_ln.startswith((".then(", ".catch(")):
                findings.append({
                    "language": "vue" if ext == ".vue" else "ts",
                    "severity": "MEDIUM",
                    "rule": "TS_FLOATING_PROMISE",
                    "path": rel,
                    "line": lineno,
                    "detail": f"Unhandled async call without `await` or `.catch()`: `{s[:65]}`",
                    "remediation": "Await the Promise inside `try/catch` or attach `.catch(...)` to prevent unhandled rejections.",
                })

    # 3. Leaked timers / global event listeners without cleanup
    has_unmount = any(k in src for k in ("onUnmounted", "onBeforeUnmount", "beforeUnmount", "unmounted", "componentWillUnmount"))
    if _JS_SET_INTERVAL_RE.search(src) and "clearInterval" not in src and not has_unmount:
        for lineno, line in enumerate(lines, 1):
            if _JS_SET_INTERVAL_RE.search(line) and not line.strip().startswith("//") and not _has_ignore(lineno):
                findings.append({
                    "language": "vue" if ext == ".vue" else "ts",
                    "severity": "HIGH",
                    "rule": "JS_LEAKED_LISTENER_OR_TIMER",
                    "path": rel,
                    "line": lineno,
                    "detail": "`setInterval()` registered without `clearInterval()` or unmount cleanup.",
                    "remediation": "Store the timer ID and call `clearInterval(id)` inside `onUnmounted()`.",
                })
                break

    if _JS_ADD_LISTENER_RE.search(src) and "removeEventListener" not in src and not has_unmount:
        for lineno, line in enumerate(lines, 1):
            if _JS_ADD_LISTENER_RE.search(line) and not line.strip().startswith("//") and not _has_ignore(lineno):
                findings.append({
                    "language": "vue" if ext == ".vue" else "ts",
                    "severity": "HIGH",
                    "rule": "JS_LEAKED_LISTENER_OR_TIMER",
                    "path": rel,
                    "line": lineno,
                    "detail": "Global `addEventListener()` registered without `removeEventListener()` or unmount cleanup.",
                    "remediation": "Remove the listener in `onUnmounted()` to prevent memory leaks across route transitions.",
                })
                break

    return findings


def _call_name_parts(call: ast.Call) -> tuple[str, str]:
    """Return (receiver_lower, attr_or_func_lower) for an AST Call."""
    fn = call.func
    if isinstance(fn, ast.Name):
        return "", fn.id.lower()
    if isinstance(fn, ast.Attribute):
        attr = fn.attr.lower()
        if isinstance(fn.value, ast.Name):
            return fn.value.id.lower(), attr
        if isinstance(fn.value, ast.Attribute):
            return fn.value.attr.lower(), attr
        return "", attr
    return "", ""


def _is_dynamic_sql_arg(arg: ast.AST) -> bool:
    if isinstance(arg, ast.JoinedStr):
        return True
    if isinstance(arg, ast.BinOp) and isinstance(arg.op, (ast.Add, ast.Mod)):
        return True
    if isinstance(arg, ast.Call) and isinstance(arg.func, ast.Attribute) and arg.func.attr == "format":
        return True
    return False


def _scan_python_ast_v4(
    rel: str,
    src: str,
    is_test: bool,
    is_cli: bool,
    owasp_findings: list[dict[str, Any]],
    silent_except: list[dict[str, Any]],
    missing_timeout: list[dict[str, Any]],
    async_blocking: list[dict[str, Any]],
    obs_samples: list[dict[str, Any]],
    n_plus_one: list[dict[str, Any]],
    unprotected_routes: list[dict[str, Any]],
    missing_resp_model: list[dict[str, Any]],
    test_smells: list[dict[str, Any]],
    counters: Counter[str],
    py_runtime_v2: list[dict[str, Any]] | None = None,
) -> None:
    """Single-pass Python AST scanner for all ADR-075 + ADR-080 P0.1/P0.2 checks."""
    try:
        tree = ast.parse(src)
    except Exception:
        return

    lines = src.splitlines()
    if py_runtime_v2 is None:
        py_runtime_v2 = []

    def _has_nosec(lineno: int) -> bool:
        if 1 <= lineno <= len(lines):
            return "nosec" in lines[lineno - 1]
        return False

    # 1. Test-file smells (only on test files)
    if is_test:
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_"):
                lineno = getattr(node, "lineno", 1)
                for dec in node.decorator_list:
                    dec_src = ast.unparse(dec) if hasattr(ast, "unparse") else ""
                    if "skip" in dec_src.lower():
                        test_smells.append({"rule": "SKIPPED_TEST", "path": rel, "line": lineno, "detail": f"{node.name} is skipped"})
                        break
                has_assertion = False
                for sub in ast.walk(node):
                    if isinstance(sub, ast.Assert):
                        has_assertion = True
                    elif isinstance(sub, ast.Call):
                        recv, fname = _call_name_parts(sub)
                        if fname in ("raises", "warns", "fail") or fname.startswith("assert"):
                            has_assertion = True
                        if recv == "time" and fname == "sleep":
                            test_smells.append({"rule": "SLEEP_IN_TEST", "path": rel, "line": getattr(sub, "lineno", lineno), "detail": f"time.sleep() inside {node.name}"})
                if not has_assertion:
                    test_smells.append({"rule": "ASSERT_LESS_TEST", "path": rel, "line": lineno, "detail": f"{node.name} has no assert / pytest.raises"})
        return

    # 1b. ADR-080 P0.1: Pre-scan module for APIRouter/FastAPI instances & router-level dependencies
    declared_routers: set[str] = set()
    protected_routers: set[str] = set()
    for stmt in tree.body:
        if isinstance(stmt, ast.Assign) and isinstance(stmt.value, ast.Call):
            _, cname = _call_name_parts(stmt.value)
            if cname in ("apirouter", "fastapi"):
                has_deps = any(kw.arg == "dependencies" for kw in stmt.value.keywords)
                for tgt in stmt.targets:
                    if isinstance(tgt, ast.Name):
                        rname = tgt.id.lower()
                        declared_routers.add(rname)
                        if has_deps:
                            protected_routers.add(rname)
        elif isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
            _, cname = _call_name_parts(stmt.value)
            if cname == "include_router" and stmt.value.args:
                if any(kw.arg == "dependencies" for kw in stmt.value.keywords):
                    arg0 = stmt.value.args[0]
                    if isinstance(arg0, ast.Name):
                        rname = arg0.id.lower()
                        declared_routers.add(rname)
                        protected_routers.add(rname)

    def _is_mutable_default(d: ast.AST) -> bool:
        if isinstance(d, (ast.List, ast.Dict, ast.Set)):
            return True
        if isinstance(d, ast.Call) and isinstance(d.func, ast.Name) and d.func.id in ("list", "dict", "set"):
            return True
        return False

    def _extract_target_names(target: ast.AST) -> set[str]:
        names: set[str] = set()
        if isinstance(target, ast.Name):
            names.add(target.id)
        elif isinstance(target, (ast.Tuple, ast.List)):
            for elt in target.elts:
                names.update(_extract_target_names(elt))
        return names

    def _has_close_call(fn_node: ast.AST) -> bool:
        for sub in ast.walk(fn_node):
            if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute) and sub.func.attr == "close":
                return True
        return False

    def _is_resource_open_call(call: ast.Call) -> str | None:
        recv, fname = _call_name_parts(call)
        if recv == "" and fname == "open":
            return "open()"
        if recv == "sqlite3" and fname == "connect":
            return "sqlite3.connect()"
        if recv == "httpx" and fname in ("client", "asyncclient"):
            return f"httpx.{call.func.attr}()" if isinstance(call.func, ast.Attribute) else "httpx.Client()"
        if recv == "tempfile" and fname == "namedtemporaryfile":
            return "tempfile.NamedTemporaryFile()"
        return None

    # 2. Production Python AST single-pass walk with parent/loop/async/with/thread-offload context
    def _visit(
        node: ast.AST,
        in_async_fn: str | None,
        in_loop: bool,
        loop_vars: frozenset[str],
        in_with_item: bool,
        in_thread_offload: bool,
        enclosing_fn_has_close: bool,
    ) -> None:
        # High-entropy secret assignment check
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            val = node.value.value.strip()
            lineno = getattr(node, "lineno", 1)
            if len(val) >= 20 and " " not in val and not _has_nosec(lineno):
                low_val = val.lower()
                if not any(h in low_val for h in _SECRET_PLACEHOLDER_HINTS):
                    for tgt in node.targets:
                        tname = tgt.id if isinstance(tgt, ast.Name) else (tgt.attr if isinstance(tgt, ast.Attribute) else "")
                        if tname and _SECRET_VAR_RE.search(tname) and _shannon_entropy(val) >= 4.3:
                            owasp_findings.append({
                                "severity": "CRITICAL",
                                "rule": "HIGH_ENTROPY_SECRET",
                                "path": rel,
                                "line": lineno,
                                "detail": f"High-entropy literal assigned to `{tname}` (H={_shannon_entropy(val):.2f})",
                            })
                            break

        # Reliability: Silent except: pass / bare except: + Swallowed Exception (ADR-080 P0.2)
        if isinstance(node, ast.ExceptHandler):
            lineno = getattr(node, "lineno", 1)
            if not _has_nosec(lineno):
                is_bare = node.type is None
                is_broad = is_bare or (isinstance(node.type, ast.Name) and node.type.id in ("Exception", "BaseException"))
                is_pass_only = len(node.body) == 1 and (
                    isinstance(node.body[0], ast.Pass)
                    or (isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant) and node.body[0].value.value is Ellipsis)
                )
                if is_bare or is_pass_only:
                    silent_except.append({
                        "path": rel,
                        "line": lineno,
                        "kind": "bare_except" if is_bare else "except_pass",
                    })
                if is_broad and len(node.body) == 1 and isinstance(node.body[0], ast.Return):
                    has_log_or_raise = False
                    for sub in ast.walk(node):
                        if isinstance(sub, ast.Raise):
                            has_log_or_raise = True
                            break
                        if isinstance(sub, ast.Call):
                            r_sub, f_sub = _call_name_parts(sub)
                            if any(h in r_sub for h in ("log", "logger", "logging", "sentry")) or f_sub in ("exception", "error", "warning", "warn"):
                                has_log_or_raise = True
                                break
                    if not has_log_or_raise:
                        py_runtime_v2.append({
                            "language": "python",
                            "severity": "HIGH",
                            "rule": "SWALLOWED_EXCEPTION",
                            "path": rel,
                            "line": lineno,
                            "detail": "Broad `except Exception:` silently returns without logging or re-raising.",
                            "remediation": "Log the exception (`logger.warning`/`logger.exception`) or catch a specific exception type.",
                        })

        # Mutable default arguments (ADR-080 P0.2) + API Contract Governance on route decorators
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            fn_lineno = getattr(node, "lineno", 1)
            if not _has_nosec(fn_lineno):
                all_defaults = list(node.args.defaults) + [d for d in node.args.kw_defaults if d is not None]
                for d_node in all_defaults:
                    if _is_mutable_default(d_node):
                        py_runtime_v2.append({
                            "language": "python",
                            "severity": "MEDIUM",
                            "rule": "MUTABLE_DEFAULT_ARG",
                            "path": rel,
                            "line": fn_lineno,
                            "detail": f"Mutable default argument in `{node.name}()` (shared across calls).",
                            "remediation": "Use `None` as default and initialize inside the function body (`if arg is None: arg = []`).",
                        })
                        break

            # Late-binding closure in loop for inner def
            if in_loop and loop_vars and not _has_nosec(fn_lineno):
                bound_args = {a.arg for a in node.args.args + node.args.kwonlyargs + node.args.posonlyargs}
                used_names = {n.id for n in ast.walk(node) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}
                leaked = sorted((used_names & loop_vars) - bound_args)
                if leaked:
                    py_runtime_v2.append({
                        "language": "python",
                        "severity": "MEDIUM",
                        "rule": "LATE_BINDING_CLOSURE",
                        "path": rel,
                        "line": fn_lineno,
                        "detail": f"Inner function `{node.name}` captures loop variable `{leaked[0]}` by reference.",
                        "remediation": f"Bind it as a default argument (`{leaked[0]}={leaked[0]}`) or use `functools.partial`.",
                    })

            for dec in node.decorator_list:
                if isinstance(dec, ast.Call):
                    recv, method = _call_name_parts(dec)
                    if method in ("post", "put", "patch", "delete") and (recv in ("app", "router", "api_router", "bp", "blueprint") or recv in declared_routers):
                        route_str = ""
                        if dec.args and isinstance(dec.args[0], ast.Constant) and isinstance(dec.args[0].value, str):
                            route_str = dec.args[0].value
                        if any(h in route_str.lower() for h in _PUBLIC_ROUTE_HINTS):
                            continue
                        counters["mutating_routes_scanned"] += 1
                        lineno = getattr(node, "lineno", 1)
                        # Check auth dependency: router-level, decorator kwargs, or function args/defaults
                        dec_kw_names = {kw.arg for kw in dec.keywords if kw.arg}
                        has_auth = False
                        if recv in protected_routers:
                            has_auth = True
                            counters["router_protected_routes"] += 1
                        if not has_auth and "dependencies" in dec_kw_names:
                            has_auth = True
                        if not has_auth:
                            arg_names = [a.arg.lower() for a in node.args.args + node.args.kwonlyargs]
                            if any(any(h in an for h in _AUTH_PARAM_HINTS) for an in arg_names):
                                has_auth = True
                        if not has_auth:
                            defaults = list(node.args.defaults) + [d for d in node.args.kw_defaults if d is not None]
                            for d in defaults:
                                if isinstance(d, ast.Call):
                                    _, dn = _call_name_parts(d)
                                    if dn in ("depends", "security"):
                                        has_auth = True
                                        break
                        if not has_auth:
                            unprotected_routes.append({
                                "path": rel,
                                "line": lineno,
                                "method": method.upper(),
                                "route": route_str or node.name,
                                "func": node.name,
                            })
                        if "response_model" not in dec_kw_names and node.returns is None:
                            missing_resp_model.append({
                                "path": rel,
                                "line": lineno,
                                "method": method.upper(),
                                "route": route_str or node.name,
                                "func": node.name,
                            })

        # Late-binding closure in loop for lambda (ADR-080 P0.2)
        if isinstance(node, ast.Lambda) and in_loop and loop_vars:
            lineno = getattr(node, "lineno", 1)
            if not _has_nosec(lineno):
                bound_args = {a.arg for a in node.args.args + node.args.kwonlyargs + node.args.posonlyargs}
                used_names = {n.id for n in ast.walk(node.body) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}
                leaked = sorted((used_names & loop_vars) - bound_args)
                if leaked:
                    py_runtime_v2.append({
                        "language": "python",
                        "severity": "MEDIUM",
                        "rule": "LATE_BINDING_CLOSURE",
                        "path": rel,
                        "line": lineno,
                        "detail": f"`lambda` inside loop captures variable `{leaked[0]}` by late binding.",
                        "remediation": f"Capture loop variable eagerly: `lambda {leaked[0]}={leaked[0]}: ...`.",
                    })

        # Resource leak: open() / httpx.Client() / sqlite3.connect() assigned outside `with` (ADR-080 P0.2)
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call) and not in_with_item and not enclosing_fn_has_close:
            lineno = getattr(node, "lineno", 1)
            if not _has_nosec(lineno):
                res_call = _is_resource_open_call(node.value)
                if res_call:
                    py_runtime_v2.append({
                        "language": "python",
                        "severity": "MEDIUM",
                        "rule": "UNCLOSED_RESOURCE",
                        "path": rel,
                        "line": lineno,
                        "detail": f"`{res_call}` assigned outside a `with` context manager without `.close()`.",
                        "remediation": f"Use `with {res_call} as ...:` to guarantee deterministic cleanup.",
                    })

        # Calls: SQLi AST, Missing timeout=, Async blocking I/O (extended), Observability print(), DB N+1 in loops
        if isinstance(node, ast.Call):
            lineno = getattr(node, "lineno", 1)
            recv, fname = _call_name_parts(node)
            kw_names = {kw.arg for kw in node.keywords if kw.arg}

            # SQLi AST: .execute(f"...") / + / % / .format()
            if fname in ("execute", "executemany", "raw") and node.args and not _has_nosec(lineno):
                if _is_dynamic_sql_arg(node.args[0]):
                    owasp_findings.append({
                        "severity": "CRITICAL",
                        "rule": "SQL_INJECTION_AST",
                        "path": rel,
                        "line": lineno,
                        "detail": f"Dynamic string interpolation in `.{fname}()` — use parameterized queries.",
                    })

            # Reliability: Missing timeout=
            if not _has_nosec(lineno):
                if (recv in _HTTP_CLIENTS and fname in _HTTP_TIMEOUT_CALLS) or (recv == "subprocess" and fname in _SUBPROCESS_CALLS) or fname == "urlopen":
                    if "timeout" not in kw_names:
                        missing_timeout.append({
                            "path": rel,
                            "line": lineno,
                            "call": f"{recv}.{fname}" if recv else fname,
                        })

            # Reliability: Blocking I/O inside async def (ADR-080 P0.2 extended, excludes to_thread/run_in_executor)
            if in_async_fn and not in_thread_offload and not _has_nosec(lineno):
                blocking_call: str | None = None
                if recv == "time" and fname == "sleep":
                    blocking_call = "time.sleep"
                elif recv == "requests" and fname in _HTTP_TIMEOUT_CALLS:
                    blocking_call = f"requests.{fname}"
                elif recv == "httpx" and fname in _HTTP_TIMEOUT_CALLS:
                    blocking_call = f"httpx.{fname}"
                elif recv == "" and fname == "open":
                    blocking_call = "open"
                elif recv == "subprocess" and fname in _ASYNC_BLOCKING_SUBPROCESS:
                    blocking_call = f"subprocess.{fname}"
                elif recv == "os" and fname in _ASYNC_BLOCKING_OS:
                    blocking_call = f"os.{fname}"
                elif fname == "urlopen":
                    blocking_call = f"{recv}.urlopen" if recv else "urlopen"
                elif recv in ("psycopg2", "sqlite3") and fname == "connect":
                    blocking_call = f"{recv}.connect"
                elif recv == "shutil" and fname in _ASYNC_BLOCKING_SHUTIL:
                    blocking_call = f"shutil.{fname}"
                elif fname in _ASYNC_BLOCKING_PATH_METHODS:
                    blocking_call = f"Path.{fname}"
                if blocking_call:
                    async_blocking.append({
                        "path": rel,
                        "line": lineno,
                        "func": in_async_fn,
                        "call": blocking_call,
                    })
                    py_runtime_v2.append({
                        "language": "python",
                        "severity": "CRITICAL",
                        "rule": "ASYNC_BLOCKING_IO",
                        "path": rel,
                        "line": lineno,
                        "detail": f"Blocking `{blocking_call}()` called directly inside `async def {in_async_fn}()`.",
                        "remediation": "Offload via `await asyncio.to_thread(...)` or use an async client (`aiofiles`/`httpx.AsyncClient`).",
                    })

            # Observability: print() in production code
            if not is_cli and recv == "" and fname == "print" and not _has_nosec(lineno):
                counters["prod_print_count"] += 1
                if len(obs_samples) < 20:
                    obs_samples.append({"kind": "print()", "path": rel, "line": lineno})

            # DB Governance: N+1 query inside loop
            if in_loop and fname in _DB_QUERY_METHODS and not _has_nosec(lineno):
                if recv and any(h in recv for h in _DB_RECEIVER_HINTS):
                    n_plus_one.append({
                        "path": rel,
                        "line": lineno,
                        "call": f"{recv}.{fname}()",
                    })

        # Recurse with updated context
        next_async = in_async_fn
        next_fn_close = enclosing_fn_has_close
        if isinstance(node, ast.AsyncFunctionDef):
            next_async = node.name
            next_fn_close = _has_close_call(node)
        elif isinstance(node, ast.FunctionDef):
            next_async = None
            next_fn_close = _has_close_call(node)

        next_loop = in_loop or isinstance(node, (ast.For, ast.AsyncFor, ast.While))
        next_loop_vars = loop_vars
        if isinstance(node, (ast.For, ast.AsyncFor)):
            next_loop_vars = loop_vars | _extract_target_names(node.target)

        next_offload = in_thread_offload
        if isinstance(node, ast.Call):
            _, call_fn = _call_name_parts(node)
            if call_fn in ("to_thread", "run_in_executor"):
                next_offload = True

        if isinstance(node, (ast.With, ast.AsyncWith)):
            for item in node.items:
                _visit(item, next_async, next_loop, next_loop_vars, True, next_offload, next_fn_close)
            for stmt in node.body:
                _visit(stmt, next_async, next_loop, next_loop_vars, False, next_offload, next_fn_close)
            return

        for child in ast.iter_child_nodes(node):
            _visit(child, next_async, next_loop, next_loop_vars, in_with_item, next_offload, next_fn_close)

    _visit(tree, None, False, frozenset(), False, False, False)


def _check_pyproject_and_lockfiles(project_dir: Path) -> dict[str, Any]:
    """Check pyproject.toml dependency pinning (via tomllib or regex fallback) and lockfile presence."""
    unpinned: list[dict[str, str]] = []
    for cand in (project_dir / "pyproject.toml", project_dir / "backend" / "pyproject.toml"):
        if not cand.is_file():
            continue
        rel_f = str(cand.relative_to(project_dir)).replace("\\", "/")
        raw_deps: list[str] = []
        if tomllib is not None:
            try:
                parsed = tomllib.loads(cand.read_text(encoding="utf-8", errors="ignore"))
                proj = parsed.get("project") or {}
                for d in proj.get("dependencies") or []:
                    if isinstance(d, str):
                        raw_deps.append(d)
                for grp_deps in (proj.get("optional-dependencies") or {}).values():
                    if isinstance(grp_deps, list):
                        raw_deps.extend(d for d in grp_deps if isinstance(d, str))
            except Exception:
                pass
        else:
            text = cand.read_text(encoding="utf-8", errors="ignore")
            for m_blk in re.finditer(r"(?m)^\s*dependencies\s*=\s*\[(.*?)\]", text, re.DOTALL):
                for m_dep in re.finditer(r"""["']([^"']+)["']""", m_blk.group(1)):
                    raw_deps.append(m_dep.group(1))
        for dep in raw_deps:
            clean = dep.strip()
            if clean and "==" not in clean and "@ " not in clean:
                unpinned.append({"file": rel_f, "dep": clean[:70]})

    lockfiles: list[str] = []
    for base in (project_dir, project_dir / "backend", project_dir / "frontend"):
        if not base.is_dir():
            continue
        for lf in _LOCKFILE_NAMES:
            p = base / lf
            if p.is_file():
                lockfiles.append(str(p.relative_to(project_dir)).replace("\\", "/"))

    return {
        "pyproject_unpinned_count": len(unpinned),
        "pyproject_unpinned": unpinned[:25],
        "lockfiles_present": sorted(set(lockfiles)),
        "has_lockfile": len(lockfiles) > 0,
    }


def _check_llms_txt_drift(project_dir: Path, data_dir: Path | None) -> dict[str, Any]:
    """Compare llms.txt mtime vs latest git commit timestamp."""
    candidates: list[Path] = [project_dir / "llms.txt"]
    if data_dir is not None:
        candidates.append(Path(data_dir).parent / "llms.txt")
        candidates.append(Path(data_dir) / "llms.txt")
    found: Path | None = next((p for p in candidates if p.is_file()), None)
    if found is None:
        return {"status": "missing", "path": None, "drift_hours": None}

    rel_p = str(found.relative_to(project_dir)).replace("\\", "/") if str(found).startswith(str(project_dir)) else found.name
    llms_mtime = found.stat().st_mtime
    latest_commit_ts: float | None = None
    if (project_dir / ".git").exists():
        try:
            proc = subprocess.run(  # nosec B603 B607
                ["git", "-C", str(project_dir), "log", "-1", "--format=%ct"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            if proc.returncode == 0 and proc.stdout.strip().isdigit():
                latest_commit_ts = float(proc.stdout.strip())
        except Exception:
            latest_commit_ts = None

    if latest_commit_ts is None:
        return {"status": "fresh", "path": rel_p, "drift_hours": 0.0}
    drift_h = round(max(0.0, (latest_commit_ts - llms_mtime) / 3600.0), 1)
    status = "stale" if drift_h >= 24.0 else "fresh"
    return {"status": status, "path": rel_p, "drift_hours": drift_h}




class _AstNormalizer(ast.NodeTransformer):
    """Normalize variable names and literals in a Python function AST for semantic clone detection (ADR-080 P2.2)."""

    def __init__(self) -> None:
        self._var_map: dict[str, str] = {}
        self._counter = 0

    def _norm_var(self, name: str) -> str:
        if name in ("self", "cls", "True", "False", "None"):
            return name
        if name not in self._var_map:
            self._var_map[name] = f"$V{self._counter}"
            self._counter += 1
        return self._var_map[name]

    def visit_Name(self, node: ast.Name) -> ast.AST:
        return ast.copy_location(ast.Name(id=self._norm_var(node.id), ctx=type(node.ctx)()), node)

    def visit_arg(self, node: ast.arg) -> ast.AST:
        return ast.copy_location(ast.arg(arg=self._norm_var(node.arg), annotation=None), node)

    def visit_Constant(self, node: ast.Constant) -> ast.AST:
        val = node.value
        if isinstance(val, bool):
            tok = "$BOOL"
        elif isinstance(val, (int, float, complex)):
            tok = "$NUM"
        elif isinstance(val, str):
            tok = "$STR"
        elif val is None:
            tok = "$NONE"
        else:
            tok = "$CONST"
        return ast.copy_location(ast.Constant(value=tok), node)


def _strip_docstring(body: list[ast.stmt]) -> list[ast.stmt]:
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        return body[1:]
    return body


def _count_statements(stmts: list[ast.stmt]) -> int:
    total = 0
    for s in stmts:
        total += 1
        for child_list_name in ("body", "orelse", "finalbody"):
            sub = getattr(s, child_list_name, None)
            if isinstance(sub, list):
                total += _count_statements(sub)
        handlers = getattr(s, "handlers", None)
        if isinstance(handlers, list):
            for h in handlers:
                if hasattr(h, "body"):
                    total += _count_statements(h.body)
    return total


def analyze_semantic_clones(
    project_dir: Path,
    max_files: int = 2000,
    min_statements: int = 8,
) -> dict[str, Any]:
    """Detect AST-normalized semantic code clones across Python functions >= min_statements (ADR-080 P2.2)."""
    project_dir = Path(project_dir).resolve()
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    funcs_analyzed = 0
    scanned = 0

    for root, dirs, files in os.walk(project_dir):
        dirs[:] = [d for d in dirs if d not in _IGNORE_DIRS and not d.startswith(".")]
        for fname in sorted(files):
            if scanned >= max_files:
                break
            if not fname.endswith(".py"):
                continue
            fpath = Path(root) / fname
            rel = str(fpath.relative_to(project_dir)).replace("\\", "/")
            if _is_ignored_path(rel):
                continue
            if any(h in f"/{rel.lower()}" for h in ("/tests/", "/test/", "/test_", "_test.py", "conftest.py")):
                continue
            try:
                if fpath.stat().st_size > 400_000:
                    continue
                src = fpath.read_text(encoding="utf-8", errors="replace")
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", SyntaxWarning)
                    tree = ast.parse(src)
            except Exception:
                continue
            scanned += 1

            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                if node.name.startswith("__") and node.name.endswith("__"):
                    continue
                body = _strip_docstring(list(node.body))
                stmt_cnt = _count_statements(body)
                if stmt_cnt < min_statements:
                    continue
                funcs_analyzed += 1
                try:
                    cloned = ast.Module(body=body, type_ignores=[])
                    norm = _AstNormalizer().visit(cloned)
                    dumped = ast.dump(norm, annotate_fields=False, include_attributes=False)
                    fp = hashlib.sha256(dumped.encode("utf-8")).hexdigest()[:16]
                except Exception:
                    continue
                buckets[fp].append({
                    "file": rel,
                    "line": getattr(node, "lineno", 1),
                    "name": node.name,
                    "statements": stmt_cnt,
                })

    clone_groups: list[dict[str, Any]] = []
    for fp, items in buckets.items():
        if len(items) < 2:
            continue
        unique_locs = {(i["file"], i["line"]) for i in items}
        if len(unique_locs) < 2:
            continue
        clone_groups.append({
            "fingerprint": fp,
            "statements": items[0]["statements"],
            "occurrences": len(items),
            "files_involved": len({i["file"] for i in items}),
            "functions": items[:8],
        })

    clone_groups.sort(key=lambda g: (-int(g["occurrences"]), -int(g["statements"]), g["fingerprint"]))
    dup_funcs = sum(int(g["occurrences"]) for g in clone_groups)
    return {
        "method": "python_ast_normalized_v1",
        "min_statements": min_statements,
        "functions_analyzed": funcs_analyzed,
        "clone_groups_count": len(clone_groups),
        "duplicated_functions_count": dup_funcs,
        "top_clones": clone_groups[:30],
    }


def analyze_health_v4(
    project_dir: Path,
    data_dir: Path | None = None,
    complexity: dict[str, Any] | None = None,
    git_crime_scene: dict[str, Any] | None = None,
    coverage: dict[str, Any] | None = None,
    max_files: int = 2500,
) -> dict[str, Any]:
    """ADR-075 Health Engine 4.0: 8 zero-dependency Python stdlib checks in a single pass."""
    project_dir = Path(project_dir).resolve()

    owasp_findings: list[dict[str, Any]] = []
    silent_except: list[dict[str, Any]] = []
    missing_timeout: list[dict[str, Any]] = []
    async_blocking: list[dict[str, Any]] = []
    obs_samples: list[dict[str, Any]] = []
    probe_files: list[str] = []
    has_health_probe = False
    has_ready_probe = False
    n_plus_one: list[dict[str, Any]] = []
    unbounded_selects: list[dict[str, Any]] = []
    unprotected_routes: list[dict[str, Any]] = []
    missing_resp_model: list[dict[str, Any]] = []
    test_smells: list[dict[str, Any]] = []
    context_bombs: list[dict[str, Any]] = []
    py_runtime_v2: list[dict[str, Any]] = []
    fe_runtime_bugs: list[dict[str, Any]] = []
    prod_by_domain: Counter[str] = Counter()
    test_by_domain: Counter[str] = Counter()
    test_file_rels: list[str] = []
    counters: Counter[str] = Counter()

    # Load DB schema table names (if available) to check unreferenced tables in the same walk
    schema_tables: list[str] = []
    referenced_tables: set[str] = set()
    if data_dir is not None:
        schema_file = Path(data_dir) / "db-schema.json"
        if schema_file.is_file():
            try:
                sc = json.loads(schema_file.read_text(encoding="utf-8"))
                schema_tables = [
                    str(t.get("name", ""))
                    for t in (sc.get("tables") or [])
                    if isinstance(t, dict) and t.get("name")
                ]
            except Exception:
                schema_tables = []

    scanned = 0
    for root, dirs, files in os.walk(project_dir):
        dirs[:] = [d for d in dirs if d not in _IGNORE_DIRS and not d.startswith(".")]
        for fname in files:
            if scanned >= max_files:
                break
            ext = os.path.splitext(fname)[1].lower()
            if ext not in (".py", ".ts", ".tsx", ".js", ".jsx", ".vue", ".sql"):
                continue
            if _is_generated_asset(fname):
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
                continue
            scanned += 1

            is_test = _is_test_rel(rel)
            is_cli = any(h in rel.lower() for h in _CLI_PATH_HINTS)
            if ext != ".sql":
                if is_test:
                    test_file_rels.append(rel)
                else:
                    prod_by_domain[_domain_bucket(rel)] += 1

            try:
                src = fpath.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue

            loc = max(1, src.count("\n") + 1)
            size_kb = round(size_bytes / 1024.0, 1)
            if not is_test and ext != ".sql" and (loc > 800 or size_kb > 30.0):
                context_bombs.append({"path": rel, "loc": loc, "size_kb": size_kb})

            # Track referenced DB tables in production code
            if schema_tables and not is_test:
                for tname in schema_tables:
                    if tname not in referenced_tables and tname in src:
                        referenced_tables.add(tname)

            # Probes check
            if not is_test and ext in (".py", ".ts", ".js"):
                if _PROBE_HEALTH_RE.search(src):
                    has_health_probe = True
                    if rel not in probe_files and len(probe_files) < 10:
                        probe_files.append(rel)
                if _PROBE_READY_RE.search(src):
                    has_ready_probe = True
                    if rel not in probe_files and len(probe_files) < 10:
                        probe_files.append(rel)

            # Line-level security / observability / unbounded SELECT (non-test code)
            if not is_test:
                for lineno, line in enumerate(src.splitlines(), 1):
                    s = line.strip()
                    if not s or s.startswith(("#", "//", "*")) or "nosec" in s:
                        continue
                    for rule_name, rx, sev in _SECRET_REGEXES:
                        if rx.search(s):
                            owasp_findings.append({"severity": sev, "rule": rule_name, "path": rel, "line": lineno, "detail": f"Potential {rule_name} literal detected."})
                            break
                    if _VERIFY_FALSE_RE.search(s):
                        owasp_findings.append({"severity": "HIGH", "rule": "TLS_VERIFY_FALSE", "path": rel, "line": lineno, "detail": "TLS certificate verification disabled (`verify=False`)."})
                    if _CORS_WILDCARD_RE.search(s):
                        owasp_findings.append({"severity": "MEDIUM", "rule": "CORS_WILDCARD", "path": rel, "line": lineno, "detail": "Permissive CORS wildcard (`*`) configured."})
                    if ext in (".ts", ".tsx", ".js", ".jsx", ".vue") and _XSS_HTML_RE.search(s):
                        owasp_findings.append({"severity": "HIGH", "rule": "XSS_UNSAFE_HTML", "path": rel, "line": lineno, "detail": "Unsafe HTML injection sink (`v-html` / `innerHTML`)."})
                    if ext in (".ts", ".tsx", ".js", ".jsx", ".vue") and not is_cli and _CONSOLE_LOG_RE.search(s):
                        counters["prod_console_log_count"] += 1
                        if len(obs_samples) < 20:
                            obs_samples.append({"kind": "console.log()", "path": rel, "line": lineno})
                    if ext in (".py", ".ts", ".js"):
                        m_sel = _UNBOUNDED_SELECT_RE.search(s)
                        if m_sel:
                            frag = m_sel.group(0).upper()
                            if "LIMIT" not in frag and "WHERE" not in frag:
                                unbounded_selects.append({"path": rel, "line": lineno, "snippet": m_sel.group(0)[:85]})

            # Single-pass Python AST checks
            if ext == ".py":
                _scan_python_ast_v4(
                    rel=rel,
                    src=src,
                    is_test=is_test,
                    is_cli=is_cli,
                    owasp_findings=owasp_findings,
                    silent_except=silent_except,
                    missing_timeout=missing_timeout,
                    async_blocking=async_blocking,
                    obs_samples=obs_samples,
                    n_plus_one=n_plus_one,
                    unprotected_routes=unprotected_routes,
                    missing_resp_model=missing_resp_model,
                    test_smells=test_smells,
                    counters=counters,
                    py_runtime_v2=py_runtime_v2,
                )
            elif not is_test and ext in (".ts", ".tsx", ".js", ".jsx", ".vue"):
                fe_runtime_bugs.extend(_scan_js_vue_antipatterns(rel, src, ext))

    # Check #1: CodeScene Risk Matrix cross-join (Churn x McCabe x Low Coverage)
    comp_map: dict[str, dict[str, Any]] = {}
    for f in (complexity or {}).get("top_complex_files") or []:
        if isinstance(f, dict) and f.get("path"):
            comp_map[str(f["path"])] = f
    cov_map: dict[str, float] = {}
    for c in (coverage or {}).get("lowest_covered") or []:
        if isinstance(c, dict) and c.get("path"):
            cov_map[str(c["path"])] = float(c.get("coverage_pct", 0.0))
    default_cov = float((coverage or {}).get("overall_pct") or 50.0)

    hotspot_commits: dict[str, int] = {}
    top_risks: list[dict[str, Any]] = []
    bus_by_dom: dict[str, dict[str, Any]] = {}
    for h in (git_crime_scene or {}).get("hotspots") or []:
        if not isinstance(h, dict) or not h.get("path"):
            continue
        p = str(h["path"])
        commits = int(h.get("commits", 0))
        churn = int(h.get("lines_churned", 0))
        authors = int(h.get("authors", 1))
        hotspot_commits[p] = commits
        dom = _domain_bucket(p)
        if authors == 1 and commits >= 3:
            b = bus_by_dom.setdefault(dom, {"domain": dom, "single_author_hotspots": 0, "max_commits": 0})
            b["single_author_hotspots"] += 1
            b["max_commits"] = max(b["max_commits"], commits)
        mc = int(comp_map.get(p, {}).get("mccabe", 10))
        cov_pct = cov_map.get(p, default_cov)
        cov_factor = 1.0 - (min(100.0, max(0.0, cov_pct)) / 100.0) * 0.7
        risk_score = round(commits * math.log1p(churn) * (max(1, mc) / 10.0) * cov_factor, 1)
        top_risks.append({
            "path": p,
            "domain": dom,
            "commits": commits,
            "lines_churned": churn,
            "mccabe": mc,
            "coverage_pct": round(cov_pct, 1),
            "risk_score": risk_score,
        })
    top_risks.sort(key=lambda r: -float(r["risk_score"]))

    coupling_enriched: list[dict[str, Any]] = []
    for tc in (git_crime_scene or {}).get("temporal_coupling") or []:
        if isinstance(tc, dict):
            fa = str(tc.get("file_a", ""))
            fb = str(tc.get("file_b", ""))
            co = int(tc.get("co_changes", 0))
            denom = max(1, min(hotspot_commits.get(fa, co), hotspot_commits.get(fb, co)))
            ratio = round(min(100.0, 100.0 * co / denom), 1)
            coupling_enriched.append({"file_a": fa, "file_b": fb, "co_changes": co, "coupling_ratio_pct": ratio})

    # Check #6: OpenAPI spec freshness
    openapi_info: dict[str, Any] = {"present": False, "path": None, "age_days": None}
    for cand_name in ("openapi.json", "openapi.yaml", "swagger.json", "backend/openapi.json", "docs/openapi.json"):
        cp = project_dir / cand_name
        if cp.is_file():
            age_d = round(max(0.0, (time.time() - cp.stat().st_mtime) / 86400.0), 1)
            openapi_info = {"present": True, "path": cand_name, "age_days": age_d}
            break

    # Check #7: Per-domain test-to-code ratio (ADR-080 P0.1: map centralized tests to real prod domains)
    prod_domain_set = set(prod_by_domain.keys())
    for trel in test_file_rels:
        resolved_dom = _resolve_test_domain(trel, prod_domain_set)
        test_by_domain[resolved_dom] += 1

    all_doms = sorted(set(prod_by_domain.keys()) | set(test_by_domain.keys()))
    by_domain: list[dict[str, Any]] = []
    cov_by_dom = {
        str(c.get("domain")): c.get("coverage_pct")
        for c in ((coverage or {}).get("by_domain") or [])
        if isinstance(c, dict) and c.get("domain")
    }
    for d in all_doms:
        pf = prod_by_domain[d]
        tf = test_by_domain[d]
        if pf == 0 and tf == 0:
            continue
        rp = round(100.0 * tf / pf, 1) if pf > 0 else 100.0
        entry: dict[str, Any] = {"domain": d, "prod_files": pf, "test_files": tf, "ratio_pct": rp}
        if d in cov_by_dom:
            entry["coverage_pct"] = cov_by_dom[d]
        by_domain.append(entry)
    by_domain.sort(key=lambda x: (-x["prod_files"], x["ratio_pct"]))

    # Check #8: Supply chain + Context bombs + llms.txt drift
    sc_info = _check_pyproject_and_lockfiles(project_dir)
    context_bombs.sort(key=lambda b: (-int(b["loc"]), -float(b["size_kb"])))
    llms_drift = _check_llms_txt_drift(project_dir, data_dir)

    # OWASP severity counts
    sev_counts = Counter(f["severity"] for f in owasp_findings)
    sev_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
    owasp_findings.sort(key=lambda f: (sev_order.get(f["severity"], 4), f["path"], f["line"]))

    # ADR-080 P0.2: Unified Runtime Bugs v2 (Python AST + JS/TS/Vue)
    all_runtime_v2 = py_runtime_v2 + fe_runtime_bugs
    all_runtime_v2.sort(key=lambda f: (sev_order.get(str(f.get("severity", "MEDIUM")), 4), str(f.get("path", "")), int(f.get("line", 1))))
    rt_sev = Counter(str(f.get("severity", "MEDIUM")) for f in all_runtime_v2)
    rt_by_rule = dict(Counter(str(f.get("rule", "UNKNOWN")) for f in all_runtime_v2))
    fe_by_rule = dict(Counter(str(f.get("rule", "UNKNOWN")) for f in fe_runtime_bugs))
    fe_sev = Counter(str(f.get("severity", "MEDIUM")) for f in fe_runtime_bugs)

    mutable_defaults = [f for f in py_runtime_v2 if f["rule"] == "MUTABLE_DEFAULT_ARG"]
    unclosed_resources = [f for f in py_runtime_v2 if f["rule"] == "UNCLOSED_RESOURCE"]
    swallowed_exceptions = [f for f in py_runtime_v2 if f["rule"] == "SWALLOWED_EXCEPTION"]
    late_binding_closures = [f for f in py_runtime_v2 if f["rule"] == "LATE_BINDING_CLOSURE"]

    unreferenced_tables = sorted(t for t in schema_tables if t not in referenced_tables)

    severity_summary = [
        {"category": "OWASP", "critical": sev_counts["CRITICAL"], "high": sev_counts["HIGH"], "medium": sev_counts["MEDIUM"]},
        {"category": "Reliability", "critical": len(async_blocking), "high": len(missing_timeout) + len(swallowed_exceptions), "medium": len(silent_except) + len(mutable_defaults) + len(unclosed_resources) + len(late_binding_closures)},
        {"category": "Frontend Runtime", "critical": fe_sev["CRITICAL"], "high": fe_sev["HIGH"], "medium": fe_sev["MEDIUM"]},
        {"category": "DB & SQL", "critical": 0, "high": len(n_plus_one), "medium": len(unbounded_selects) + len(unreferenced_tables)},
        {"category": "API Contract", "critical": 0, "high": len(unprotected_routes), "medium": len(missing_resp_model)},
        {"category": "Observability", "critical": 0, "high": 0 if has_health_probe else 1, "medium": counters["prod_print_count"] + counters["prod_console_log_count"]},
        {"category": "Test Smells", "critical": 0, "high": sum(1 for s in test_smells if s["rule"] == "ASSERT_LESS_TEST"), "medium": sum(1 for s in test_smells if s["rule"] != "ASSERT_LESS_TEST")},
    ]

    hidden_tc = list((git_crime_scene or {}).get("hidden_temporal_coupling") or [])
    max_cs_risk = float((git_crime_scene or {}).get("max_codescene_risk") or (top_risks[0]["risk_score"] if top_risks else 0.0))

    return {
        "codescene_risk": {
            "top_risks": top_risks[:25],
            "temporal_coupling_enriched": coupling_enriched[:15],
            "hidden_temporal_coupling": hidden_tc[:15],
            "hidden_temporal_coupling_count": len(hidden_tc),
            "max_codescene_risk": max_cs_risk,
            "bus_factor_by_domain": sorted(bus_by_dom.values(), key=lambda b: -int(b["single_author_hotspots"]))[:12],
        },
        "owasp_audit": {
            "findings_count": len(owasp_findings),
            "by_severity": {"CRITICAL": sev_counts["CRITICAL"], "HIGH": sev_counts["HIGH"], "MEDIUM": sev_counts["MEDIUM"]},
            "findings": owasp_findings[:40],
        },
        "reliability_ast": {
            "total_issues": len(silent_except) + len(missing_timeout) + len(async_blocking) + len(mutable_defaults) + len(unclosed_resources) + len(swallowed_exceptions) + len(late_binding_closures),
            "silent_except_count": len(silent_except),
            "missing_timeout_count": len(missing_timeout),
            "async_blocking_count": len(async_blocking),
            "mutable_default_count": len(mutable_defaults),
            "unclosed_resource_count": len(unclosed_resources),
            "swallowed_exception_count": len(swallowed_exceptions),
            "late_binding_closure_count": len(late_binding_closures),
            "silent_except": silent_except[:25],
            "missing_timeout": missing_timeout[:25],
            "async_blocking": async_blocking[:25],
            "mutable_defaults": mutable_defaults[:25],
            "unclosed_resources": unclosed_resources[:25],
            "swallowed_exceptions": swallowed_exceptions[:25],
            "late_binding_closures": late_binding_closures[:25],
        },
        "frontend_runtime_bugs": {
            "total_issues": len(fe_runtime_bugs),
            "by_rule": fe_by_rule,
            "by_severity": {"CRITICAL": fe_sev["CRITICAL"], "HIGH": fe_sev["HIGH"], "MEDIUM": fe_sev["MEDIUM"]},
            "findings": fe_runtime_bugs[:60],
        },
        "runtime_bugs_v2": {
            "total_issues": len(all_runtime_v2),
            "python_count": len(py_runtime_v2),
            "frontend_count": len(fe_runtime_bugs),
            "by_rule": rt_by_rule,
            "by_severity": {
                "CRITICAL": rt_sev["CRITICAL"],
                "HIGH": rt_sev["HIGH"],
                "MEDIUM": rt_sev["MEDIUM"],
                "LOW": rt_sev["LOW"],
            },
            "findings": all_runtime_v2[:120],
        },
        "observability": {
            "prod_print_count": counters["prod_print_count"],
            "prod_console_log_count": counters["prod_console_log_count"],
            "has_health_probe": has_health_probe,
            "has_ready_probe": has_ready_probe,
            "probe_files": probe_files,
            "samples": obs_samples[:20],
        },
        "db_governance": {
            "n_plus_one_count": len(n_plus_one),
            "n_plus_one_loops": n_plus_one[:25],
            "unbounded_select_count": len(unbounded_selects),
            "unbounded_selects": unbounded_selects[:20],
            "unreferenced_tables_count": len(unreferenced_tables),
            "unreferenced_tables": unreferenced_tables[:20],
        },
        "api_governance": {
            "mutating_routes_scanned": counters["mutating_routes_scanned"],
            "router_protected_count": counters["router_protected_routes"],
            "unprotected_count": len(unprotected_routes),
            "unprotected_mutating_routes": unprotected_routes[:25],
            "missing_response_model_count": len(missing_resp_model),
            "missing_response_model": missing_resp_model[:25],
            "openapi_spec": openapi_info,
        },
        "test_quality": {
            "by_domain": by_domain[:20],
            "test_smells_count": len(test_smells),
            "test_smells": test_smells[:30],
        },
        "supply_chain_and_ai": {
            **sc_info,
            "context_bombs_count": len(context_bombs),
            "context_bombs": context_bombs[:20],
            "llms_txt_drift": llms_drift,
        },
        "semantic_clones": analyze_semantic_clones(project_dir),
        "severity_summary": severity_summary,
    }
