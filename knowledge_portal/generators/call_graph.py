"""
Knowledge Portal — Symbol-Level Call Graph & Sequence Chain Engine (ADR-077).
100% Python stdlib zero-dependency AST analyzer extracting:
- Top-level functions and class methods with typed signatures & line numbers
- Resolved internal caller -> callee edges (excluding Python builtins)
- DB table touches & exceptions raised per symbol
- End-to-end Route -> Handler -> Callees (depth 3) -> DB Table chains

Outputs `data/call-graph.json` and `data/call_graph.js`.
Strictly enforces P4 Gate (excludes frozen/, .git, node_modules, venv, tests).
"""

from __future__ import annotations

import ast
import builtins
import json
import os
import re
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

_IGNORE_DIRS = frozenset({
    ".git", "node_modules", "dist", "build", ".venv", "venv",
    "__pycache__", ".idea", ".vscode", "target", "vendor", "bin", "obj", "frozen",
})
_BUILTINS = frozenset(dir(builtins)) | frozenset({
    "append", "extend", "get", "items", "keys", "values", "update", "pop", "strip",
    "split", "join", "replace", "lower", "upper", "startswith", "endswith", "format",
    "encode", "decode", "read", "write", "close", "info", "debug", "warning", "error",
    "exception", "add", "remove", "sort", "copy", "clear", "mkdir", "exists", "is_file",
    "read_text", "write_text", "loads", "dumps", "match", "search", "findall", "sub",
})
_SQL_TABLE_RE = re.compile(r"\b(?:FROM|INTO|UPDATE|JOIN)\s+([a-zA-Z_][a-zA-Z0-9_]{2,})", re.IGNORECASE)
_SQL_NOISE = frozenset({"select", "where", "values", "set", "table", "index", "dual", "each"})


def _is_ignored(rel: str) -> bool:
    parts = [p.lower() for p in rel.replace("\\", "/").split("/")]
    if any(p in _IGNORE_DIRS or p.startswith(".") for p in parts[:-1]) or "frozen" in parts:
        return True
    low = f"/{rel.lower()}"
    return any(h in low for h in ("/tests/", "/test/", "/test_", "_test.py", "conftest.py"))


def _format_sig(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    args = [a.arg for a in node.args.args[:6]]
    if len(node.args.args) > 6:
        args.append("...")
    ret = ""
    if node.returns is not None and hasattr(ast, "unparse"):
        try:
            ret = f" -> {ast.unparse(node.returns)[:40]}"
        except Exception:
            ret = ""
    prefix = "async def " if isinstance(node, ast.AsyncFunctionDef) else "def "
    return f"{prefix}{node.name}({', '.join(args)}){ret}"


def _extract_route_decorator(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str | None:
    for dec in node.decorator_list:
        if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute):
            attr = dec.func.attr.lower()
            if attr in ("get", "post", "put", "patch", "delete", "websocket", "route"):
                if dec.args and isinstance(dec.args[0], ast.Constant) and isinstance(dec.args[0].value, str):
                    m = "WS" if attr == "websocket" else ("ROUTE" if attr == "route" else attr.upper())
                    return f"{m} {dec.args[0].value}"
    return None


def generate_call_graph(
    project_dir: Path,
    data_dir: Path,
    max_files: int = 2000,
    max_symbols: int = 8000,
    max_edges: int = 20000,
) -> dict[str, Any]:
    """Scan Python codebase AST and build symbol-level call graph & end-to-end chains."""
    project_dir = Path(project_dir).resolve()
    data_dir = Path(data_dir)

    symbols: dict[str, dict[str, Any]] = {}
    by_name: dict[str, list[str]] = defaultdict(list)
    raw_calls: dict[str, list[str]] = {}
    scanned = 0

    for root, dirs, files in os.walk(project_dir):
        dirs[:] = [d for d in dirs if d not in _IGNORE_DIRS and not d.startswith(".")]
        for fname in files:
            if scanned >= max_files or len(symbols) >= max_symbols:
                break
            if not fname.endswith(".py"):
                continue
            fpath = Path(root) / fname
            rel = str(fpath.relative_to(project_dir)).replace("\\", "/")
            if _is_ignored(rel):
                continue
            try:
                if fpath.stat().st_size > 400_000:
                    continue
                src = fpath.read_text(encoding="utf-8", errors="replace")
                tree = ast.parse(src)
            except Exception:
                continue
            scanned += 1

            def _register_fn(fn: ast.FunctionDef | ast.AsyncFunctionDef, cls_name: str | None) -> None:
                if len(symbols) >= max_symbols:
                    return
                qname = f"{cls_name}.{fn.name}" if cls_name else fn.name
                sid = f"{rel}::{qname}"
                callees_raw: list[str] = []
                tables: set[str] = set()
                raises: set[str] = set()

                for sub in ast.walk(fn):
                    if isinstance(sub, ast.Call):
                        cname = ""
                        if isinstance(sub.func, ast.Name):
                            cname = sub.func.id
                        elif isinstance(sub.func, ast.Attribute):
                            cname = sub.func.attr
                        if cname and cname not in _BUILTINS and not cname.startswith("__"):
                            callees_raw.append(cname)
                    elif isinstance(sub, ast.Raise) and sub.exc is not None:
                        if isinstance(sub.exc, ast.Call) and isinstance(sub.exc.func, ast.Name):
                            raises.add(sub.exc.func.id)
                        elif isinstance(sub.exc, ast.Name):
                            raises.add(sub.exc.id)
                    elif isinstance(sub, ast.Constant) and isinstance(sub.value, str) and len(sub.value) > 10:
                        if "select " in sub.value.lower() or "insert " in sub.value.lower() or "update " in sub.value.lower() or "delete " in sub.value.lower():
                            for tm in _SQL_TABLE_RE.findall(sub.value):
                                if tm.lower() not in _SQL_NOISE:
                                    tables.add(tm)

                symbols[sid] = {
                    "id": sid,
                    "name": fn.name,
                    "qname": qname,
                    "file": rel,
                    "line": getattr(fn, "lineno", 1),
                    "signature": _format_sig(fn),
                    "route": _extract_route_decorator(fn),
                    "db_tables": sorted(tables)[:10],
                    "raises": sorted(raises)[:8],
                    "callees": [],
                    "callers": [],
                }
                by_name[fn.name].append(sid)
                raw_calls[sid] = list(dict.fromkeys(callees_raw))

            for top in tree.body:
                if isinstance(top, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    _register_fn(top, None)
                elif isinstance(top, ast.ClassDef):
                    for item in top.body:
                        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and not item.name.startswith("__"):
                            _register_fn(item, top.name)

    # Resolve internal symbol -> symbol edges
    edges: list[dict[str, str]] = []
    for sid, callee_names in raw_calls.items():
        if len(edges) >= max_edges:
            break
        src_file = symbols[sid]["file"]
        for cname in callee_names:
            cands = by_name.get(cname)
            if not cands:
                continue
            # Prefer same-file match, else first unique/top candidate
            target_id = next((c for c in cands if symbols[c]["file"] == src_file), cands[0])
            if target_id == sid:
                continue
            if target_id not in symbols[sid]["callees"]:
                symbols[sid]["callees"].append(target_id)
                symbols[target_id]["callers"].append(sid)
                edges.append({"source": sid, "target": target_id})
                if len(edges) >= max_edges:
                    break

    # Build end-to-end sequence chains starting from routes (or top callers)
    entries = [s for s in symbols.values() if s.get("route")]
    if not entries:
        entries = sorted(
            [s for s in symbols.values() if s["callees"]],
            key=lambda s: (-len(s["callees"]), s["id"]),
        )[:40]

    chains: list[dict[str, Any]] = []
    for entry in entries[:80]:
        steps: list[dict[str, Any]] = []
        visited: set[str] = {entry["id"]}
        frontier = [(entry["id"], 0)]
        tables_all: set[str] = set(entry["db_tables"])
        while frontier and len(steps) < 18:
            cur_id, depth = frontier.pop(0)
            cur = symbols[cur_id]
            steps.append({
                "depth": depth,
                "id": cur["id"],
                "qname": cur["qname"],
                "file": cur["file"],
                "line": cur["line"],
                "signature": cur["signature"],
                "db_tables": cur["db_tables"],
            })
            tables_all.update(cur["db_tables"])
            if depth < 3:
                for nxt in cur["callees"][:5]:
                    if nxt not in visited:
                        visited.add(nxt)
                        frontier.append((nxt, depth + 1))
        chains.append({
            "entry_id": entry["id"],
            "label": entry["route"] or entry["qname"],
            "file": entry["file"],
            "line": entry["line"],
            "db_tables": sorted(tables_all),
            "steps": steps,
        })

    payload: dict[str, Any] = {
        "generated_at": time.time(),
        "summary": {
            "files_scanned": scanned,
            "total_symbols": len(symbols),
            "total_call_edges": len(edges),
            "route_entries": sum(1 for s in symbols.values() if s.get("route")),
            "sequence_chains": len(chains),
        },
        "chains": chains,
        "symbols": {k: v for k, v in list(symbols.items())[:max_symbols]},
    }

    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "call-graph.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    (data_dir / "call_graph.js").write_text(f"window.CALL_GRAPH = {json.dumps({'summary': payload['summary'], 'chains': chains})};\n", encoding="utf-8")
    return payload
