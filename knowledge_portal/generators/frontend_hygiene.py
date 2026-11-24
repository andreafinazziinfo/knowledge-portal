"""
Knowledge Portal — Frontend Architecture, Bundle & a11y Hygiene Auditor (ADR-080 P2.1).
100% Python stdlib zero-dependency static auditor for Vue/TS/React frontends:
- Route Lazy-Loading coverage (`() => import(...)` vs static eager view imports)
- Pinia / Vuex God-Store detection (LOC, ref/reactive/computed/actions, cross-store coupling)
- Error Boundary coverage (`onErrorCaptured`, `app.config.errorHandler`, `componentDidCatch`)
- Static a11y checks (`<img>` without `alt`, `<div @click>` / `<span @click>` without `role`/`@keydown`, `<input>` without label/aria-label)
- Optional bundle weight analysis from `dist/` or `frontend/dist/` (`assets/*.js`, `assets/*.css`, `stats.json`)
"""

from __future__ import annotations

import json
import os
import re
from collections import Counter
from pathlib import Path
from typing import Any

_IGNORE_DIRS = frozenset({
    ".git", "node_modules", "dist", "dev-dist", "build", ".venv", "venv",
    "__pycache__", ".idea", ".vscode", "target", "vendor", "frozen", "coverage",
})

_STATIC_VIEW_IMPORT_RE = re.compile(
    r"import\s+(\w+)\s+from\s+['\"]([^'\"]*(?:views|pages)/[^'\"]+\.(?:vue|tsx|jsx))['\"]",
)
_LAZY_ROUTE_RE = re.compile(r"\(\s*\)\s*=>\s*import\s*\(\s*['\"]([^'\"]+)['\"]\s*\)")
_ERROR_BOUNDARY_RE = re.compile(
    r"\b(onErrorCaptured|errorHandler|componentDidCatch|getDerivedStateFromError|ErrorBoundary)\b",
)
_STORE_STATE_RE = re.compile(r"\b(ref|reactive|computed|shallowRef|defineStore)\s*(?:<[^>]+>)?\s*\(")
_STORE_ACTION_RE = re.compile(r"(?:async\s+)?function\s+\w+\s*\(|\bconst\s+\w+\s*=\s*(?:async\s*)?\([^)]*\)\s*=>")
_CROSS_STORE_RE = re.compile(r"\buse[A-Z]\w*Store\s*\(")

_TEMPLATE_BLOCK_RE = re.compile(r"<template\b[^>]*>(.*?)</template>", re.DOTALL | re.IGNORECASE)
_IMG_TAG_RE = re.compile(r"<img\b([^>]*)/?>", re.IGNORECASE | re.DOTALL)
_CLICK_DIV_RE = re.compile(r"<(div|span)\b([^>]*?(?:@click|v-on:click|onClick)[^>]*)>", re.IGNORECASE | re.DOTALL)
_INPUT_TAG_RE = re.compile(r"<input\b([^>]*)/?>", re.IGNORECASE | re.DOTALL)


def _is_test_file(rel: str) -> bool:
    low = f"/{rel.lower()}"
    return any(h in low for h in ("/tests/", "/test/", "/__tests__/", ".spec.", ".test."))


def _line_of_offset(text: str, offset: int) -> int:
    return text.count("\n", 0, max(0, offset)) + 1


def _scan_bundle_stats(project_dir: Path) -> dict[str, Any]:
    dist_cands = [
        project_dir / "frontend" / "dist",
        project_dir / "dist",
        project_dir / "web" / "dist",
    ]
    chunks: list[dict[str, Any]] = []
    js_bytes = 0
    css_bytes = 0
    dist_rel = None

    for d in dist_cands:
        if not d.exists() or not d.is_dir():
            continue
        assets = d / "assets"
        scan_root = assets if assets.exists() and assets.is_dir() else d
        found_any = False
        for fp in scan_root.rglob("*"):
            if not fp.is_file():
                continue
            ext = fp.suffix.lower()
            if ext not in (".js", ".mjs", ".css"):
                continue
            try:
                sz = fp.stat().st_size
            except OSError:
                continue
            found_any = True
            if ext in (".js", ".mjs"):
                js_bytes += sz
            else:
                css_bytes += sz
            chunks.append({
                "file": str(fp.relative_to(project_dir)).replace("\\", "/"),
                "type": "js" if ext in (".js", ".mjs") else "css",
                "size_kb": round(sz / 1024.0, 1),
            })
        if found_any:
            dist_rel = str(d.relative_to(project_dir)).replace("\\", "/")
            break

    for sc in (project_dir / "frontend" / "dist" / "stats.json", project_dir / "dist" / "stats.json", project_dir / "bundle-stats.json"):
        if sc.is_file() and not chunks:
            try:
                raw = json.loads(sc.read_text(encoding="utf-8", errors="replace"))
                for asset in (raw.get("assets") or []):
                    if isinstance(asset, dict) and asset.get("name"):
                        sz = int(asset.get("size", 0) or 0)
                        name = str(asset["name"])
                        if name.endswith(".js"):
                            js_bytes += sz
                        elif name.endswith(".css"):
                            css_bytes += sz
                        chunks.append({"file": name, "type": "js" if name.endswith(".js") else "other", "size_kb": round(sz / 1024.0, 1)})
                dist_rel = str(sc.relative_to(project_dir)).replace("\\", "/")
            except Exception:
                pass

    if not chunks:
        return {
            "available": False,
            "dist_path": None,
            "total_kb": 0.0,
            "js_kb": 0.0,
            "css_kb": 0.0,
            "oversized_chunks_count": 0,
            "largest_chunks": [],
        }

    chunks.sort(key=lambda c: -float(c["size_kb"]))
    oversized = [c for c in chunks if c["type"] == "js" and float(c["size_kb"]) > 500.0]
    return {
        "available": True,
        "dist_path": dist_rel,
        "total_kb": round((js_bytes + css_bytes) / 1024.0, 1),
        "js_kb": round(js_bytes / 1024.0, 1),
        "css_kb": round(css_bytes / 1024.0, 1),
        "oversized_chunks_count": len(oversized),
        "largest_chunks": chunks[:10],
    }


def analyze_frontend_hygiene(project_dir: Path, max_files: int = 2000) -> dict[str, Any]:
    """Scan frontend source tree for route lazy-loading, god-stores, error boundaries, a11y, and bundle size."""
    project_dir = Path(project_dir).resolve()
    fe_files_scanned = 0

    lazy_routes_count = 0
    eager_routes: list[dict[str, Any]] = []
    god_stores: list[dict[str, Any]] = []
    stores_scanned = 0
    error_boundary_files: list[str] = []
    a11y_findings: list[dict[str, Any]] = []

    for root, dirs, files in os.walk(project_dir):
        dirs[:] = [d for d in dirs if d not in _IGNORE_DIRS and not d.startswith(".")]
        for fname in sorted(files):
            if fe_files_scanned >= max_files:
                break
            ext = os.path.splitext(fname)[1].lower()
            if ext not in (".vue", ".ts", ".tsx", ".js", ".jsx"):
                continue
            fpath = Path(root) / fname
            rel = str(fpath.relative_to(project_dir)).replace("\\", "/")
            if _is_test_file(rel) or "frozen/" in rel.lower():
                continue
            try:
                if fpath.stat().st_size > 400_000:
                    continue
                src = fpath.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            fe_files_scanned += 1
            low_rel = rel.lower()

            if _ERROR_BOUNDARY_RE.search(src):
                if len(error_boundary_files) < 15:
                    error_boundary_files.append(rel)

            if "/router/" in f"/{low_rel}" or low_rel.endswith(("router.ts", "router.js", "routes.ts", "routes.js")):
                lazy_routes_count += len(_LAZY_ROUTE_RE.findall(src))
                for m in _STATIC_VIEW_IMPORT_RE.finditer(src):
                    comp_name, imp_path = m.group(1), m.group(2)
                    lineno = _line_of_offset(src, m.start())
                    eager_routes.append({
                        "rule": "FE_EAGER_ROUTE_IMPORT",
                        "severity": "MEDIUM",
                        "category": "frontend",
                        "path": rel,
                        "line": lineno,
                        "component": comp_name,
                        "detail": f"Eager static route import `{comp_name}` from `{imp_path}` inflates initial bundle",
                        "remediation": f"Switch to lazy route loading: `component: () => import('{imp_path}')`.",
                    })

            if ("/stores/" in f"/{low_rel}" or "/store/" in f"/{low_rel}") and ext in (".ts", ".js"):
                stores_scanned += 1
                loc = len(src.splitlines())
                state_refs = len(_STORE_STATE_RE.findall(src))
                actions = len(_STORE_ACTION_RE.findall(src))
                cross_stores = sorted(set(_CROSS_STORE_RE.findall(src)))
                complexity_units = state_refs + actions
                if loc > 350 or complexity_units > 20 or len(cross_stores) >= 5:
                    sev = "HIGH" if (loc > 500 or complexity_units > 32) else "MEDIUM"
                    god_stores.append({
                        "rule": "FE_GOD_STORE",
                        "severity": sev,
                        "category": "frontend",
                        "path": rel,
                        "line": 1,
                        "loc": loc,
                        "state_refs": state_refs,
                        "actions": actions,
                        "cross_store_coupling": len(cross_stores),
                        "detail": f"God-Store `{fname}`: {loc} LOC, {state_refs} reactive refs, {actions} actions, {len(cross_stores)} cross-store dependencies",
                        "remediation": "Split store by domain concern and extract pure API/computation helpers into composables.",
                    })

            if ext in (".vue", ".tsx", ".jsx"):
                scan_chunks: list[tuple[str, int]] = []
                if ext == ".vue":
                    tm = _TEMPLATE_BLOCK_RE.search(src)
                    if tm:
                        base_line = _line_of_offset(src, tm.start(1)) - 1
                        scan_chunks.append((tm.group(1), base_line))
                else:
                    scan_chunks.append((src, 0))

                for chunk, base_line in scan_chunks:
                    has_label_tag = "<label" in chunk.lower()
                    for m in _IMG_TAG_RE.finditer(chunk):
                        attrs = m.group(1)
                        if not re.search(r"(?:^|\s)(?::|v-bind:)?alt\s*=", attrs, re.IGNORECASE):
                            lineno = base_line + _line_of_offset(chunk, m.start())
                            a11y_findings.append({
                                "rule": "A11Y_IMG_MISSING_ALT",
                                "severity": "MEDIUM",
                                "category": "a11y",
                                "path": rel,
                                "line": lineno,
                                "detail": "`<img>` element missing `alt` attribute",
                                "remediation": "Add descriptive `alt=\"...\"` (or `alt=\"\"` for purely decorative images).",
                            })

                    for m in _CLICK_DIV_RE.finditer(chunk):
                        tag, attrs = m.group(1).lower(), m.group(2)
                        has_role = bool(re.search(r"\brole\s*=", attrs, re.IGNORECASE))
                        has_key = bool(re.search(r"(?:@keydown|@keyup|v-on:key|onKeyDown|onKeyUp)", attrs, re.IGNORECASE))
                        if not has_role and not has_key:
                            lineno = base_line + _line_of_offset(chunk, m.start())
                            a11y_findings.append({
                                "rule": "A11Y_CLICKABLE_DIV_NO_ROLE",
                                "severity": "MEDIUM",
                                "category": "a11y",
                                "path": rel,
                                "line": lineno,
                                "detail": f"Clickable `<{tag} @click>` lacks `role=\"button\"` and keyboard handler (`@keydown`)",
                                "remediation": "Use semantic `<button>` or add `role=\"button\" tabindex=\"0\" @keydown.enter=\"...\"`.",
                            })

                    for m in _INPUT_TAG_RE.finditer(chunk):
                        attrs = m.group(1)
                        if re.search(r"\btype\s*=\s*['\"](?:hidden|submit|button|reset)['\"]", attrs, re.IGNORECASE):
                            continue
                        has_aria = bool(re.search(r"(?:aria-label|aria-labelledby|title)\s*=", attrs, re.IGNORECASE))
                        has_id_with_label = has_label_tag and bool(re.search(r"\bid\s*=", attrs, re.IGNORECASE))
                        if not has_aria and not has_id_with_label:
                            lineno = base_line + _line_of_offset(chunk, m.start())
                            a11y_findings.append({
                                "rule": "A11Y_INPUT_MISSING_LABEL",
                                "severity": "LOW",
                                "category": "a11y",
                                "path": rel,
                                "line": lineno,
                                "detail": "`<input>` element lacks `aria-label`, `aria-labelledby`, or associated `<label>`",
                                "remediation": "Add `aria-label=\"...\"` or bind a `<label for=\"...\">` to the input `id`.",
                            })

    bundle_stats = _scan_bundle_stats(project_dir)
    bundle_findings: list[dict[str, Any]] = []
    for ch in bundle_stats.get("largest_chunks") or []:
        if ch.get("type") == "js" and float(ch.get("size_kb", 0)) > 500.0:
            bundle_findings.append({
                "rule": "FE_LARGE_BUNDLE_CHUNK",
                "severity": "MEDIUM",
                "category": "frontend",
                "path": str(ch["file"]),
                "line": 1,
                "detail": f"JS bundle chunk `{ch['file']}` is {ch['size_kb']} KB (> 500 KB threshold)",
                "remediation": "Split vendor/feature chunks via Vite `manualChunks` or dynamic `import()`.",
            })

    extra_findings: list[dict[str, Any]] = []
    if fe_files_scanned >= 5 and not error_boundary_files:
        extra_findings.append({
            "rule": "FE_MISSING_ERROR_BOUNDARY",
            "severity": "MEDIUM",
            "category": "frontend",
            "path": "frontend/src",
            "line": 1,
            "detail": "No global error boundary (`onErrorCaptured`, `app.config.errorHandler`, or `componentDidCatch`) found",
            "remediation": "Register `app.config.errorHandler` and/or an `onErrorCaptured` root boundary component.",
        })

    total_routes = lazy_routes_count + len(eager_routes)
    lazy_cov_pct = round(100.0 * lazy_routes_count / total_routes, 1) if total_routes > 0 else 100.0

    all_findings = god_stores + eager_routes + extra_findings + bundle_findings + a11y_findings[:80]
    sev_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
    all_findings.sort(key=lambda f: (sev_order.get(str(f.get("severity", "MEDIUM")), 4), str(f.get("path", "")), int(f.get("line", 1))))
    by_rule = dict(Counter(f["rule"] for f in all_findings))

    return {
        "summary": {
            "fe_files_scanned": fe_files_scanned,
            "lazy_routes_count": lazy_routes_count,
            "eager_routes_count": len(eager_routes),
            "lazy_route_coverage_pct": lazy_cov_pct,
            "stores_scanned": stores_scanned,
            "god_stores_count": len(god_stores),
            "has_error_boundary": bool(error_boundary_files),
            "a11y_issues_count": len(a11y_findings),
            "bundle_total_kb": bundle_stats["total_kb"],
            "total_issues": len(god_stores) + len(eager_routes) + len(extra_findings) + len(bundle_findings) + len(a11y_findings),
        },
        "by_rule": by_rule,
        "eager_routes": eager_routes[:30],
        "god_stores": god_stores[:20],
        "has_error_boundary": bool(error_boundary_files),
        "error_boundary_files": error_boundary_files,
        "a11y_findings": a11y_findings[:80],
        "bundle_stats": bundle_stats,
        "findings": all_findings[:120],
    }
