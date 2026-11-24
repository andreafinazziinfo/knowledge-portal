"""
Knowledge Portal — Test-to-Code Reverse Oracle Generator (ADR-082 AI-2).
100% Python stdlib zero-dependency static AST + regex reverse mapper:
- Parses Python pytest suites (imports, monkeypatch/patch targets, HTTP routes, fixtures, markers)
- Parses JS/TS Vitest/Jest suites (relative & alias imports, describe/it/test counts)
- Classifies runtime tier (fast / medium / slow) with optional JUnit timing fusion
- Produces inverse maps `source_to_tests`, `symbol_to_tests`, and `blind_spots`

Outputs `data/test-oracle.json` and `data/test_oracle.js`.
"""

from __future__ import annotations

import ast
import json
import os
import re
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

_IGNORE_DIRS = frozenset({
    ".git", "node_modules", "dist", "dev-dist", "build", ".venv", "venv",
    "__pycache__", ".idea", ".vscode", "target", "vendor", "frozen",
    "graphify-out", "coverage", ".pytest_cache", ".mypy_cache", ".ruff_cache",
})

_CONFIDENCE_RANK = {
    "direct_import": 0,
    "symbol_patch": 1,
    "route_match": 2,
    "module_sibling": 3,
}
_TIER_RANK = {"fast": 0, "medium": 1, "slow": 2}

_SLOW_FIXTURES = frozenset({
    "db_session", "postgres", "timescale", "async_db", "live_server",
    "browser", "page", "playwright", "selenium", "redis_client", "celery_worker",
})
_MEDIUM_FIXTURES = frozenset({
    "client", "test_client", "async_client", "api_client", "sqlite_db",
    "app_client", "http_client",
})
_BUILTIN_ARGS = frozenset({
    "self", "cls", "tmp_path", "tmpdir", "monkeypatch", "capsys",
    "capfd", "caplog", "request", "pytestconfig", "mocker", "recwarn",
})

_HTTP_CALL_RE = re.compile(
    r"""\b(?:client|ac|async_client|test_client|api_client|http|session)\s*\.\s*(get|post|put|patch|delete)\s*\(\s*["'](/[^"']+)["']""",
    re.IGNORECASE,
)
_JS_IMPORT_RE = re.compile(
    r"""(?:import\s+(?:[\s\S]*?\s+from\s+)?|require\s*\(\s*|vi\.mock\s*\(\s*|jest\.mock\s*\(\s*)["']([^"']+)["']""",
)
_JS_TEST_RE = re.compile(r"""\b(?:it|test)\s*\(""")
_PY_PATCH_FUNCS = frozenset({"patch", "setattr", "patch_object"})


def _is_test_file(rel: str) -> tuple[bool, str]:
    low = rel.lower()
    name = low.rsplit("/", 1)[-1]
    if name.endswith(".py"):
        if name.startswith("test_") or name.endswith("_test.py"):
            return True, "python"
        if ("/tests/" in f"/{low}" or low.startswith("tests/")) and name != "__init__.py" and name != "conftest.py":
            if "test" in name:
                return True, "python"
    elif name.endswith((".spec.ts", ".test.ts", ".spec.tsx", ".test.tsx", ".spec.js", ".test.js")):
        return True, "javascript" if name.endswith(".js") else "typescript"
    return False, ""


def _build_source_index(project_dir: Path) -> tuple[dict[str, str], dict[str, str], set[str]]:
    """Map dotted python module names and normalized relative paths to repo source files."""
    mod_to_file: dict[str, str] = {}
    stem_to_file: dict[str, str] = {}
    all_sources: set[str] = set()

    for root, dirs, files in os.walk(project_dir):
        dirs[:] = [d for d in dirs if d not in _IGNORE_DIRS and not d.startswith(".")]
        for fname in files:
            fpath = Path(root) / fname
            rel = str(fpath.relative_to(project_dir)).replace("\\", "/")
            if "frozen/" in rel.lower():
                continue
            ext = fpath.suffix.lower()
            if ext not in (".py", ".ts", ".tsx", ".js", ".jsx", ".vue"):
                continue
            is_test, _ = _is_test_file(rel)
            if is_test or fname == "conftest.py":
                continue
            if rel.startswith("template/data/") or "/data/" in rel and ext == ".js":
                continue
            all_sources.add(rel)
            no_ext = rel.rsplit(".", 1)[0]
            stem_to_file[no_ext] = rel
            if ext == ".py":
                dotted = no_ext.replace("/", ".")
                if dotted.endswith(".__init__"):
                    dotted = dotted[:-9]
                mod_to_file[dotted] = rel
                # Also index without leading backend/ or src/
                for prefix in ("backend.", "src."):
                    if dotted.startswith(prefix):
                        mod_to_file.setdefault(dotted[len(prefix):], rel)
            else:
                for prefix in ("frontend/src/", "src/"):
                    if no_ext.startswith(prefix):
                        stem_to_file.setdefault("@/" + no_ext[len(prefix):], rel)
                        stem_to_file.setdefault(no_ext[len(prefix):], rel)
    return mod_to_file, stem_to_file, all_sources


def _load_route_map(data_dir: Path) -> dict[str, str]:
    """Map normalized route paths from api-catalog.json to handler source files."""
    route_map: dict[str, str] = {}
    cat_file = data_dir / "api-catalog.json"
    if not cat_file.is_file():
        return route_map
    try:
        raw = json.loads(cat_file.read_text(encoding="utf-8"))
        for ep in raw.get("endpoints") or []:
            if not isinstance(ep, dict):
                continue
            rpath = str(ep.get("path") or "").strip()
            rfile = str(ep.get("file") or "").replace("\\", "/").lstrip("./")
            if rpath and rfile:
                norm = re.sub(r"\{[^}]+\}", "{p}", rpath.rstrip("/")) or "/"
                route_map[norm] = rfile
    except Exception:
        pass
    return route_map


def _load_junit_timings(data_dir: Path) -> dict[str, int]:
    """Optional runtime_ms per test file from quality-telemetry.json."""
    timings: dict[str, int] = {}
    qt_file = data_dir / "quality-telemetry.json"
    if not qt_file.is_file():
        return timings
    try:
        raw = json.loads(qt_file.read_text(encoding="utf-8"))
        junit = raw.get("junit") or {}
        for tc in junit.get("slowest_tests") or []:
            if isinstance(tc, dict) and tc.get("file"):
                f = str(tc["file"]).replace("\\", "/")
                ms = int(float(tc.get("time_sec", 0.0) or 0.0) * 1000)
                timings[f] = max(timings.get(f, 0), ms)
    except Exception:
        pass
    return timings


def _resolve_py_module(mod_name: str, mod_to_file: dict[str, str]) -> str | None:
    if not mod_name:
        return None
    parts = mod_name.split(".")
    for i in range(len(parts), 0, -1):
        cand = ".".join(parts[:i])
        if cand in mod_to_file:
            return mod_to_file[cand]
    return None


def _analyze_python_test(
    fpath: Path,
    rel: str,
    mod_to_file: dict[str, str],
    route_map: dict[str, str],
) -> dict[str, Any]:
    text = fpath.read_text(encoding="utf-8", errors="replace")
    imports: list[tuple[str, str]] = []  # (source_file, confidence)
    symbols: set[str] = set()
    fixtures: set[str] = set()
    markers: set[str] = set()
    test_count = 0

    try:
        tree = ast.parse(text, filename=rel)
    except SyntaxError:
        tree = None

    if tree is not None:
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    resolved = _resolve_py_module(alias.name, mod_to_file)
                    if resolved:
                        imports.append((resolved, "direct_import"))
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                resolved = _resolve_py_module(mod, mod_to_file)
                if resolved:
                    imports.append((resolved, "direct_import"))
                for alias in node.names:
                    if alias.name != "*":
                        if resolved:
                            symbols.add(alias.name)
                        sub_resolved = _resolve_py_module(f"{mod}.{alias.name}" if mod else alias.name, mod_to_file)
                        if sub_resolved:
                            imports.append((sub_resolved, "direct_import"))
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name.startswith("test_"):
                    test_count += 1
                    for arg in node.args.args:
                        if arg.arg not in _BUILTIN_ARGS:
                            fixtures.add(arg.arg)
                for dec in node.decorator_list:
                    dec_str = ast.unparse(dec) if hasattr(ast, "unparse") else ""
                    for mk in ("slow", "integration", "e2e", "unit", "asyncio"):
                        if f"mark.{mk}" in dec_str:
                            markers.add(mk)
            elif isinstance(node, ast.Call):
                fn_name = ""
                if isinstance(node.func, ast.Name):
                    fn_name = node.func.id
                elif isinstance(node.func, ast.Attribute):
                    fn_name = node.func.attr
                if fn_name in _PY_PATCH_FUNCS and node.args:
                    first = node.args[0]
                    if isinstance(first, ast.Constant) and isinstance(first.value, str) and "." in first.value:
                        target_str = first.value
                        resolved = _resolve_py_module(target_str, mod_to_file)
                        if resolved:
                            imports.append((resolved, "symbol_patch"))
                        symbols.add(target_str.rsplit(".", 1)[-1])

    # Route calls
    for _method, raw_route in _HTTP_CALL_RE.findall(text):
        clean_r = raw_route.split("?", 1)[0].rstrip("/") or "/"
        matched_file = route_map.get(clean_r)
        if not matched_file:
            # Try prefix/parameter match
            segs = clean_r.split("/")
            for rpat, rfile in route_map.items():
                psegs = rpat.split("/")
                if len(segs) == len(psegs) and all(ps == "{p}" or ps == s for ps, s in zip(psegs, segs)):
                    matched_file = rfile
                    break
        if matched_file:
            imports.append((matched_file, "route_match"))

    # Module-level pytestmark check
    for mk in ("slow", "integration", "e2e"):
        if f"pytest.mark.{mk}" in text:
            markers.add(mk)

    # Runtime tier
    low_rel = rel.lower()
    if (
        "slow" in markers
        or "e2e" in markers
        or "integration" in markers
        or "/e2e/" in low_rel
        or "/integration/" in low_rel
        or any(f in _SLOW_FIXTURES for f in fixtures)
    ):
        tier = "slow"
    elif (
        any(f in _MEDIUM_FIXTURES for f in fixtures)
        or "TestClient" in text
        or "AsyncClient" in text
    ):
        tier = "medium"
    else:
        tier = "fast"

    return {
        "lang": "python",
        "tier": tier,
        "test_count": max(test_count, 1) if "def test_" in text else test_count,
        "fixtures": sorted(fixtures)[:12],
        "markers": sorted(markers),
        "imports": imports,
        "symbols": sorted(symbols)[:25],
    }


def _analyze_js_test(
    fpath: Path,
    rel: str,
    stem_to_file: dict[str, str],
) -> dict[str, Any]:
    text = fpath.read_text(encoding="utf-8", errors="replace")
    imports: list[tuple[str, str]] = []
    parent = rel.rsplit("/", 1)[0] if "/" in rel else ""

    for spec in _JS_IMPORT_RE.findall(text):
        resolved: str | None = None
        if spec.startswith("@/"):
            clean = spec.rsplit(".", 1)[0] if spec.endswith((".ts", ".tsx", ".js", ".vue")) else spec
            resolved = stem_to_file.get(clean)
        elif spec.startswith("."):
            joined = os.path.normpath(os.path.join(parent, spec)).replace("\\", "/")
            clean = joined.rsplit(".", 1)[0] if joined.endswith((".ts", ".tsx", ".js", ".vue")) else joined
            resolved = stem_to_file.get(clean) or stem_to_file.get(f"{clean}/index")
        if resolved:
            imports.append((resolved, "direct_import"))

    test_count = len(_JS_TEST_RE.findall(text))
    low_rel = rel.lower()
    tier = "slow" if ("e2e" in low_rel or "playwright" in text.lower()) else "fast"
    return {
        "lang": "typescript" if rel.endswith((".ts", ".tsx")) else "javascript",
        "tier": tier,
        "test_count": test_count,
        "fixtures": [],
        "markers": [],
        "imports": imports,
        "symbols": [],
    }


def generate_test_oracle(project_dir: Path, data_dir: Path) -> dict[str, Any]:
    """Build AST/regex reverse test-to-code map and blind-spot inventory."""
    project_dir = Path(project_dir).resolve()
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)

    mod_to_file, stem_to_file, all_sources = _build_source_index(project_dir)
    route_map = _load_route_map(data_dir)
    junit_timings = _load_junit_timings(data_dir)

    tests_meta: dict[str, dict[str, Any]] = {}
    source_to_tests_raw: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    symbol_to_tests_raw: dict[str, list[str]] = defaultdict(list)

    for root, dirs, files in os.walk(project_dir):
        dirs[:] = [d for d in dirs if d not in _IGNORE_DIRS and not d.startswith(".")]
        for fname in sorted(files):
            fpath = Path(root) / fname
            rel = str(fpath.relative_to(project_dir)).replace("\\", "/")
            if "frozen/" in rel.lower():
                continue
            is_test, lang = _is_test_file(rel)
            if not is_test:
                continue
            try:
                info = (
                    _analyze_python_test(fpath, rel, mod_to_file, route_map)
                    if lang == "python"
                    else _analyze_js_test(fpath, rel, stem_to_file)
                )
            except Exception:
                continue

            runtime_ms = junit_timings.get(rel, 200 if info["tier"] == "fast" else (1800 if info["tier"] == "medium" else 6500))
            if runtime_ms >= 5000:
                info["tier"] = "slow"
            elif runtime_ms >= 1000 and info["tier"] == "fast":
                info["tier"] = "medium"

            targets_seen: set[str] = set()
            for src_file, conf in info["imports"]:
                targets_seen.add(src_file)
                prev = source_to_tests_raw[src_file].get(rel)
                if prev is None or _CONFIDENCE_RANK[conf] < _CONFIDENCE_RANK[prev["confidence"]]:
                    source_to_tests_raw[src_file][rel] = {
                        "test": rel,
                        "confidence": conf,
                        "tier": info["tier"],
                        "runtime_ms": runtime_ms,
                        "fixtures": info["fixtures"][:6],
                    }

            # Sibling fallback: test_foo.py -> foo.py if no direct match yet
            base_stem = Path(rel).stem
            for pref in ("test_",):
                if base_stem.startswith(pref):
                    cand_stem = base_stem[len(pref):]
                    for src in all_sources:
                        if Path(src).stem == cand_stem and rel not in source_to_tests_raw[src]:
                            source_to_tests_raw[src][rel] = {
                                "test": rel,
                                "confidence": "module_sibling",
                                "tier": info["tier"],
                                "runtime_ms": runtime_ms,
                                "fixtures": info["fixtures"][:6],
                            }
                            targets_seen.add(src)
                            break

            for sym in info["symbols"]:
                if rel not in symbol_to_tests_raw[sym] and len(symbol_to_tests_raw[sym]) < 8:
                    symbol_to_tests_raw[sym].append(rel)

            tests_meta[rel] = {
                "lang": info["lang"],
                "tier": info["tier"],
                "runtime_ms": runtime_ms,
                "test_count": info["test_count"],
                "fixtures": info["fixtures"],
                "markers": info["markers"],
                "targets": sorted(targets_seen)[:15],
            }

    source_to_tests: dict[str, list[dict[str, Any]]] = {}
    for src, tmap in sorted(source_to_tests_raw.items()):
        ordered = sorted(
            tmap.values(),
            key=lambda x: (_CONFIDENCE_RANK.get(x["confidence"], 9), _TIER_RANK.get(x["tier"], 9), int(x["runtime_ms"]), x["test"]),
        )
        source_to_tests[src] = ordered[:10]

    # Blind spots: high-LOC or mutating-route source files with 0 mapped tests
    mutating_files: set[str] = set()
    cat_file = data_dir / "api-catalog.json"
    if cat_file.is_file():
        try:
            raw_cat = json.loads(cat_file.read_text(encoding="utf-8"))
            for ep in raw_cat.get("endpoints") or []:
                if isinstance(ep, dict) and str(ep.get("method", "")).upper() in ("POST", "PUT", "PATCH", "DELETE"):
                    rf = str(ep.get("file") or "").replace("\\", "/").lstrip("./")
                    if rf:
                        mutating_files.add(rf)
        except Exception:
            pass

    blind_spots: list[dict[str, Any]] = []
    for src in sorted(all_sources):
        if src in source_to_tests:
            continue
        p = project_dir / src
        try:
            loc = sum(1 for _ in p.open("r", encoding="utf-8", errors="ignore"))
        except OSError:
            continue
        is_mut = src in mutating_files
        if is_mut or loc >= 200:
            blind_spots.append({
                "path": src,
                "loc": loc,
                "reason": "mutating_route_untested" if is_mut else "high_loc_untested",
            })
    blind_spots.sort(key=lambda b: (0 if b["reason"] == "mutating_route_untested" else 1, -int(b["loc"]), b["path"]))

    by_tier = {"fast": 0, "medium": 0, "slow": 0}
    total_cases = 0
    for tm in tests_meta.values():
        t_key = str(tm.get("tier", "fast"))
        by_tier[t_key] = by_tier.get(t_key, 0) + 1
        total_cases += int(tm.get("test_count", 0))

    payload: dict[str, Any] = {
        "schema_version": "1.0",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "summary": {
            "total_test_files": len(tests_meta),
            "total_test_cases": total_cases,
            "total_source_files": len(all_sources),
            "mapped_sources": len(source_to_tests),
            "mapped_symbols": len(symbol_to_tests_raw),
            "blind_spots_count": len(blind_spots),
            "by_tier": by_tier,
        },
        "source_to_tests": source_to_tests,
        "symbol_to_tests": dict(sorted(symbol_to_tests_raw.items())),
        "tests": tests_meta,
        "blind_spots": blind_spots[:100],
    }

    (data_dir / "test-oracle.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    (data_dir / "test_oracle.js").write_text(
        f"window.TEST_ORACLE = {json.dumps(payload)};\n",
        encoding="utf-8",
    )
    return payload
