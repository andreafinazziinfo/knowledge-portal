"""
Knowledge Portal — Symbol-Level Call Graph, Sequence Chains & Dead Code Engine (ADR-077 + ADR-080 P1.1).
100% Python stdlib zero-dependency AST & JS/TS/Vue analyzer extracting:
- Top-level functions and class methods with typed signatures & line numbers
- Import-aware internal caller -> callee edges (excluding Python builtins)
- DB table touches & exceptions raised per symbol
- End-to-end Route -> Handler -> Callees (depth 3) -> DB Table chains
- Symbol-level Dead Code:
  * Unreferenced Python functions/methods/classes (excluding routes, tests, dunders, __all__, CLI main, callbacks)
  * Unused JS/TS named exports
  * Unimported `.vue` components

Outputs `data/call-graph.json`, `data/call_graph.js`, and `data/dead-code.json`.
Strictly enforces P4 Gate (excludes frozen/, .git, node_modules, venv).
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
    ".git", "node_modules", "dist", "dev-dist", "build", ".venv", "venv",
    "__pycache__", ".idea", ".vscode", "target", "vendor", "bin", "obj", "frozen", "coverage",
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

_ENTRY_NAMES = frozenset({
    "main", "cli", "run", "app", "create_app", "lifespan", "setup", "teardown",
    "setUp", "tearDown", "do_GET", "do_POST", "do_PUT", "do_DELETE", "do_PATCH",
    "do_OPTIONS", "do_HEAD", "log_message", "generic_visit", "default", "format",
    "emit", "filter", "handle", "to_dict", "from_dict", "model_dump",
})
_FRAMEWORK_DECORATORS = frozenset({
    "get", "post", "put", "patch", "delete", "websocket", "route", "api_route",
    "middleware", "exception_handler", "on_event", "lifespan", "task", "shared_task",
    "fixture", "mark", "parametrize", "validator", "field_validator", "model_validator",
    "computed_field", "property", "classmethod", "staticmethod", "abstractmethod",
    "overload", "contextmanager", "asynccontextmanager", "cached_property", "lru_cache",
    "command", "option", "argument", "group", "tool", "resource", "prompt", "receiver",
    "hookimpl", "singledispatch", "register", "wraps", "dataclass",
})
_FRAMEWORK_BASES = frozenset({
    "BaseModel", "BaseSettings", "Enum", "IntEnum", "StrEnum", "Exception", "Protocol",
    "ABC", "BaseHTTPRequestHandler", "SimpleHTTPRequestHandler", "NodeVisitor",
    "NodeTransformer", "TestCase", "TypedDict", "NamedTuple",
})

# JS/TS/Vue export & import regexes
_JS_EXPORT_DECL_RE = re.compile(
    r"^\s*export\s+(?:declare\s+)?(?:async\s+)?(?:function|const|let|var|class|type|interface|enum)\s+([A-Za-z_$][A-Za-z0-9_$]*)",
    re.MULTILINE,
)
_JS_NAMED_IMPORT_RE = re.compile(r"import\s+(?:type\s+)?\{([^}]+)\}\s+from\s+['\"]([^'\"]+)['\"]", re.DOTALL)
_JS_REEXPORT_RE = re.compile(r"export\s+(?:type\s+)?\{([^}]+)\}\s+from\s+['\"]([^'\"]+)['\"]", re.DOTALL)
_JS_DEFAULT_IMPORT_RE = re.compile(r"import\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*(?:,\s*\{[^}]*\})?\s+from\s+['\"]([^'\"]+)['\"]")
_JS_NS_IMPORT_RE = re.compile(r"import\s+\*\s+as\s+([A-Za-z_$][A-Za-z0-9_$]*)\s+from\s+['\"]([^'\"]+)['\"]")
_JS_DYNAMIC_IMPORT_RE = re.compile(r"import\s*\(\s*['\"]([^'\"]+)['\"]\s*\)")
_JS_VUE_TAG_RE = re.compile(r"<([A-Z][A-Za-z0-9]+|[a-z]+-[a-z0-9-]+)[\s/>]")


def _is_test_or_ignored_py(rel: str) -> bool:
    parts = [p.lower() for p in rel.replace("\\", "/").split("/")]
    if any(p in _IGNORE_DIRS or p.startswith(".") for p in parts[:-1]) or "frozen" in parts:
        return True
    low = f"/{rel.lower()}"
    return any(h in low for h in ("/tests/", "/test/", "/test_", "_test.py", "conftest.py"))


def _is_ignored_dir_only(rel: str) -> bool:
    parts = [p.lower() for p in rel.replace("\\", "/").split("/")]
    return any(p in _IGNORE_DIRS or p.startswith(".") for p in parts[:-1]) or "frozen" in parts


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


def _has_framework_decorator(node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) -> bool:
    for dec in node.decorator_list:
        name = ""
        if isinstance(dec, ast.Name):
            name = dec.id
        elif isinstance(dec, ast.Attribute):
            name = dec.attr
        elif isinstance(dec, ast.Call):
            if isinstance(dec.func, ast.Name):
                name = dec.func.id
            elif isinstance(dec.func, ast.Attribute):
                name = dec.func.attr
        if name.lower() in _FRAMEWORK_DECORATORS:
            return True
    return False


def _extract_dunder_all(tree: ast.Module) -> set[str]:
    exported: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and tgt.id == "__all__" and isinstance(node.value, (ast.List, ast.Tuple, ast.Set)):
                    for elt in node.value.elts:
                        if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                            exported.add(elt.value)
    return exported


def _module_candidates(rel: str) -> list[str]:
    no_ext = rel[:-3] if rel.endswith(".py") else rel
    parts = [p for p in no_ext.split("/") if p]
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    cands: list[str] = []
    for i in range(len(parts)):
        cands.append(".".join(parts[i:]))
    return cands


def _extract_imports(tree: ast.Module, rel: str) -> dict[str, tuple[str, str]]:
    """Return local_alias -> (module_dotted, original_name) for import-aware call resolution."""
    imp_map: dict[str, tuple[str, str]] = {}
    pkg_parts = rel.replace("\\", "/").split("/")[:-1]

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                local = alias.asname or alias.name.split(".")[0]
                imp_map[local] = (alias.name, "")
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if node.level and node.level > 0:
                base = pkg_parts[: max(0, len(pkg_parts) - (node.level - 1))]
                full_mod = ".".join(base + ([mod] if mod else []))
            else:
                full_mod = mod
            for alias in node.names:
                if alias.name == "*":
                    continue
                local = alias.asname or alias.name
                imp_map[local] = (full_mod, alias.name)
    return imp_map


def _kebab_to_pascal(name: str) -> str:
    return "".join(p.capitalize() for p in name.split("-") if p)


def _scan_js_ts_vue_dead_code(project_dir: Path, max_files: int = 2000) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Build JS/TS/Vue export/import graph and detect unused exports & unimported .vue components."""
    exported_symbols: list[dict[str, Any]] = []
    vue_components: list[dict[str, Any]] = []
    imported_names_by_other: dict[str, set[str]] = defaultdict(set)  # symbol_name -> set of importing files
    imported_paths_by_other: dict[str, set[str]] = defaultdict(set)  # normalized stem -> set of importing files
    scanned = 0

    for root, dirs, files in os.walk(project_dir):
        dirs[:] = [d for d in dirs if d not in _IGNORE_DIRS and not d.startswith(".")]
        for fname in sorted(files):
            if scanned >= max_files:
                break
            ext = os.path.splitext(fname)[1].lower()
            if ext not in (".ts", ".tsx", ".js", ".jsx", ".vue"):
                continue
            if fname.endswith(".d.ts") or fname.endswith(".min.js"):
                continue
            fpath = Path(root) / fname
            rel = str(fpath.relative_to(project_dir)).replace("\\", "/")
            if _is_ignored_dir_only(rel):
                continue
            try:
                if fpath.stat().st_size > 400_000:
                    continue
                src = fpath.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            scanned += 1
            low_rel = rel.lower()

            # Collect imports from ALL files (including tests, views, router, main.ts)
            for m in _JS_NAMED_IMPORT_RE.finditer(src):
                for part in m.group(1).split(","):
                    tok = part.strip().split(" as ")[0].strip()
                    tok = re.sub(r"^type\s+", "", tok)
                    if tok:
                        imported_names_by_other[tok].add(rel)
                imp_stem = Path(m.group(2)).stem
                if imp_stem:
                    imported_paths_by_other[imp_stem.lower()].add(rel)

            for m in _JS_REEXPORT_RE.finditer(src):
                for part in m.group(1).split(","):
                    tok = part.strip().split(" as ")[0].strip()
                    tok = re.sub(r"^type\s+", "", tok)
                    if tok:
                        imported_names_by_other[tok].add(rel)
                imp_stem = Path(m.group(2)).stem
                if imp_stem:
                    imported_paths_by_other[imp_stem.lower()].add(rel)

            for m in _JS_DEFAULT_IMPORT_RE.finditer(src):
                imported_names_by_other[m.group(1)].add(rel)
                imp_stem = Path(m.group(2)).stem
                if imp_stem:
                    imported_paths_by_other[imp_stem.lower()].add(rel)

            for m in _JS_NS_IMPORT_RE.finditer(src):
                imp_stem = Path(m.group(2)).stem
                if imp_stem:
                    imported_paths_by_other[imp_stem.lower()].add(rel)

            for m in _JS_DYNAMIC_IMPORT_RE.finditer(src):
                imp_stem = Path(m.group(1)).stem
                if imp_stem:
                    imported_paths_by_other[imp_stem.lower()].add(rel)

            if ext == ".vue":
                for tm in _JS_VUE_TAG_RE.finditer(src):
                    tag = tm.group(1)
                    if "-" in tag:
                        imported_paths_by_other[_kebab_to_pascal(tag).lower()].add(rel)
                        imported_paths_by_other[tag.lower()].add(rel)
                    else:
                        imported_paths_by_other[tag.lower()].add(rel)

            # Skip entrypoints & tests when registering candidate dead exports/components
            is_test = any(h in f"/{low_rel}" for h in ("/tests/", "/test/", "/__tests__/", ".spec.", ".test."))
            is_entry = (
                is_test
                or fname.lower() in ("main.ts", "main.js", "index.ts", "index.js", "app.vue")
                or ".config." in fname.lower()
                or any(h in f"/{low_rel}" for h in ("/router/", "/views/", "/pages/", "/layouts/", "/public/"))
            )
            if is_entry:
                continue

            if ext == ".vue":
                stem = Path(fname).stem
                vue_components.append({
                    "symbol": stem,
                    "kind": "vue_component",
                    "language": "vue",
                    "file": rel,
                    "line": 1,
                    "stem_lower": stem.lower(),
                })
            elif ext in (".ts", ".tsx", ".js", ".jsx"):
                for m in _JS_EXPORT_DECL_RE.finditer(src):
                    sym = m.group(1)
                    lineno = src.count("\n", 0, m.start()) + 1
                    exported_symbols.append({
                        "symbol": sym,
                        "kind": "js_export",
                        "language": "typescript" if ext in (".ts", ".tsx") else "javascript",
                        "file": rel,
                        "line": lineno,
                    })

    unused_exports: list[dict[str, Any]] = []
    for item in exported_symbols:
        importers = imported_names_by_other.get(item["symbol"], set()) - {item["file"]}
        if not importers:
            unused_exports.append({
                "rule": "DEAD_JS_EXPORT",
                "severity": "LOW",
                "symbol": item["symbol"],
                "kind": item["kind"],
                "language": item["language"],
                "file": item["file"],
                "line": item["line"],
                "detail": f"Exported symbol `{item['symbol']}` is never imported by any other module",
                "remediation": "Remove `export` keyword or delete dead symbol if no longer required.",
            })

    unused_vue: list[dict[str, Any]] = []
    for comp in vue_components:
        importers = imported_paths_by_other.get(comp["stem_lower"], set()) - {comp["file"]}
        if not importers:
            unused_vue.append({
                "rule": "DEAD_VUE_COMPONENT",
                "severity": "MEDIUM",
                "symbol": comp["symbol"],
                "kind": comp["kind"],
                "language": "vue",
                "file": comp["file"],
                "line": 1,
                "detail": f"Vue component `{comp['symbol']}.vue` is never imported or referenced in templates",
                "remediation": "Wire into parent view/router or archive unused component.",
            })

    unused_exports.sort(key=lambda x: (x["file"], x["line"]))
    unused_vue.sort(key=lambda x: x["file"])
    return unused_exports, unused_vue


def generate_call_graph(
    project_dir: Path,
    data_dir: Path,
    max_files: int = 2000,
    max_symbols: int = 8000,
    max_edges: int = 20000,
) -> dict[str, Any]:
    """Scan Python & JS/TS/Vue codebase to build import-aware call graph, sequence chains, and dead code report."""
    project_dir = Path(project_dir).resolve()
    data_dir = Path(data_dir)

    symbols: dict[str, dict[str, Any]] = {}
    by_name: dict[str, list[str]] = defaultdict(list)
    raw_calls: dict[str, list[tuple[str, str]]] = {}  # sid -> [(obj_or_empty, callee_name)]
    file_imports: dict[str, dict[str, tuple[str, str]]] = {}
    mod_to_rel: dict[str, str] = {}
    file_dunder_all: dict[str, set[str]] = {}
    external_refs: dict[str, set[str]] = defaultdict(set)  # name -> set of files referencing it
    symbol_meta: dict[str, dict[str, Any]] = {}  # sid -> extra metadata for dead-code filtering
    scanned = 0

    for root, dirs, files in os.walk(project_dir):
        dirs[:] = [d for d in dirs if d not in _IGNORE_DIRS and not d.startswith(".")]
        for fname in sorted(files):
            if not fname.endswith(".py"):
                continue
            fpath = Path(root) / fname
            rel = str(fpath.relative_to(project_dir)).replace("\\", "/")
            if _is_ignored_dir_only(rel):
                continue
            try:
                if fpath.stat().st_size > 400_000:
                    continue
                src = fpath.read_text(encoding="utf-8", errors="replace")
                tree = ast.parse(src)
            except Exception:
                continue

            # Track all name/attribute references across ALL Python files (including tests & __init__.py)
            for node in ast.walk(tree):
                if isinstance(node, ast.Name):
                    external_refs[node.id].add(rel)
                elif isinstance(node, ast.Attribute):
                    external_refs[node.attr].add(rel)
                elif isinstance(node, ast.ImportFrom):
                    for alias in node.names:
                        external_refs[alias.name].add(rel)

            if _is_test_or_ignored_py(rel):
                continue
            if scanned >= max_files or len(symbols) >= max_symbols:
                continue
            scanned += 1

            for mc in _module_candidates(rel):
                mod_to_rel.setdefault(mc, rel)
            file_imports[rel] = _extract_imports(tree, rel)
            file_dunder_all[rel] = _extract_dunder_all(tree)

            def _register_fn(
                fn: ast.FunctionDef | ast.AsyncFunctionDef,
                cls_name: str | None,
                cls_is_framework: bool = False,
            ) -> None:
                if len(symbols) >= max_symbols:
                    return
                qname = f"{cls_name}.{fn.name}" if cls_name else fn.name
                sid = f"{rel}::{qname}"
                callees_raw: list[tuple[str, str]] = []
                tables: set[str] = set()
                raises: set[str] = set()

                for sub in ast.walk(fn):
                    if isinstance(sub, ast.Call):
                        cname = ""
                        obj_name = ""
                        if isinstance(sub.func, ast.Name):
                            cname = sub.func.id
                        elif isinstance(sub.func, ast.Attribute):
                            cname = sub.func.attr
                            if isinstance(sub.func.value, ast.Name):
                                obj_name = sub.func.value.id
                        if cname and cname not in _BUILTINS and not cname.startswith("__"):
                            callees_raw.append((obj_name, cname))
                    elif isinstance(sub, ast.Raise) and sub.exc is not None:
                        if isinstance(sub.exc, ast.Call) and isinstance(sub.exc.func, ast.Name):
                            raises.add(sub.exc.func.id)
                        elif isinstance(sub.exc, ast.Name):
                            raises.add(sub.exc.id)
                    elif isinstance(sub, ast.Constant) and isinstance(sub.value, str) and len(sub.value) > 10:
                        low_s = sub.value.lower()
                        if "select " in low_s or "insert " in low_s or "update " in low_s or "delete " in low_s:
                            for tm in _SQL_TABLE_RE.findall(sub.value):
                                if tm.lower() not in _SQL_NOISE:
                                    tables.add(tm)

                route = _extract_route_decorator(fn)
                symbols[sid] = {
                    "id": sid,
                    "name": fn.name,
                    "qname": qname,
                    "file": rel,
                    "line": getattr(fn, "lineno", 1),
                    "signature": _format_sig(fn),
                    "route": route,
                    "db_tables": sorted(tables)[:10],
                    "raises": sorted(raises)[:8],
                    "callees": [],
                    "callers": [],
                }
                symbol_meta[sid] = {
                    "cls_name": cls_name,
                    "cls_is_framework": cls_is_framework,
                    "has_framework_dec": _has_framework_decorator(fn),
                }
                by_name[fn.name].append(sid)
                raw_calls[sid] = list(dict.fromkeys(callees_raw))

            for top in tree.body:
                if isinstance(top, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    _register_fn(top, None, False)
                elif isinstance(top, ast.ClassDef):
                    base_names = set()
                    for b in top.bases:
                        if isinstance(b, ast.Name):
                            base_names.add(b.id)
                        elif isinstance(b, ast.Attribute):
                            base_names.add(b.attr)
                    is_fw_cls = bool(base_names & _FRAMEWORK_BASES) or _has_framework_decorator(top)
                    for item in top.body:
                        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and not item.name.startswith("__"):
                            _register_fn(item, top.name, is_fw_cls)

    # Import-aware internal symbol -> symbol edge resolution (ADR-080 P1.1)
    edges: list[dict[str, str]] = []
    for sid, callee_pairs in raw_calls.items():
        if len(edges) >= max_edges:
            break
        src_file = symbols[sid]["file"]
        src_cls = (symbol_meta.get(sid) or {}).get("cls_name")
        imports = file_imports.get(src_file) or {}

        for obj_name, cname in callee_pairs:
            target_id: str | None = None

            # 1. Explicit import resolution (`from mod import fn as alias` or `mod.fn()`)
            if not obj_name and cname in imports:
                imp_mod, orig_name = imports[cname]
                imp_rel = mod_to_rel.get(imp_mod)
                lookup = orig_name or cname
                cands = by_name.get(lookup) or []
                if imp_rel:
                    target_id = next((c for c in cands if symbols[c]["file"] == imp_rel), None)
            elif obj_name and obj_name in imports:
                imp_mod, _ = imports[obj_name]
                imp_rel = mod_to_rel.get(imp_mod)
                cands = by_name.get(cname) or []
                if imp_rel:
                    target_id = next((c for c in cands if symbols[c]["file"] == imp_rel), None)

            # 2. Same class (`self.method()` / `cls.method()`) or same file match
            if target_id is None:
                cands = by_name.get(cname) or []
                if not cands:
                    continue
                if obj_name in ("self", "cls") and src_cls:
                    target_id = next(
                        (c for c in cands if symbols[c]["file"] == src_file and (symbol_meta.get(c) or {}).get("cls_name") == src_cls),
                        None,
                    )
                if target_id is None:
                    target_id = next((c for c in cands if symbols[c]["file"] == src_file), cands[0])

            if target_id is None or target_id == sid:
                continue
            if target_id not in symbols[sid]["callees"]:
                symbols[sid]["callees"].append(target_id)
                symbols[target_id]["callers"].append(sid)
                edges.append({"source": sid, "target": target_id})
                if len(edges) >= max_edges:
                    break

    # Dead Python symbols detection (ADR-080 P1.1)
    python_dead_symbols: list[dict[str, Any]] = []
    for sid, sym in symbols.items():
        if sym["callers"] or sym.get("route"):
            continue
        name = sym["name"]
        rel = sym["file"]
        meta = symbol_meta.get(sid) or {}
        if (
            name in _ENTRY_NAMES
            or name.startswith("test_")
            or name.startswith("visit_")
            or (name.startswith("__") and name.endswith("__"))
            or meta.get("has_framework_dec")
            or meta.get("cls_is_framework")
            or name in (file_dunder_all.get(rel) or set())
        ):
            continue
        # If referenced in any OTHER file (e.g. callback, dict registry, __init__.py re-export, test)
        other_refs = external_refs.get(name, set()) - {rel}
        if other_refs:
            continue
        python_dead_symbols.append({
            "rule": "DEAD_PYTHON_SYMBOL",
            "severity": "LOW",
            "symbol": sym["qname"],
            "kind": "method" if meta.get("cls_name") else "function",
            "language": "python",
            "file": rel,
            "line": sym["line"],
            "signature": sym["signature"],
            "detail": f"Python {('method' if meta.get('cls_name') else 'function')} `{sym['qname']}` has 0 callers and 0 cross-file references",
            "remediation": "Verify if invoked dynamically; otherwise remove dead code to reduce maintenance surface.",
        })
    python_dead_symbols.sort(key=lambda x: (x["file"], x["line"]))

    # JS/TS/Vue Dead Exports & Components (ADR-080 P1.1)
    js_unused_exports, vue_unused_components = _scan_js_ts_vue_dead_code(project_dir, max_files=max_files)

    dead_code_payload: dict[str, Any] = {
        "generated_at": time.time(),
        "summary": {
            "python_count": len(python_dead_symbols),
            "js_export_count": len(js_unused_exports),
            "vue_component_count": len(vue_unused_components),
            "js_count": len(js_unused_exports) + len(vue_unused_components),
            "total": len(python_dead_symbols) + len(js_unused_exports) + len(vue_unused_components),
        },
        "python_dead_symbols": python_dead_symbols[:120],
        "js_unused_exports": js_unused_exports[:120],
        "vue_unused_components": vue_unused_components[:80],
    }

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
            "dead_python_symbols": len(python_dead_symbols),
            "dead_js_exports": len(js_unused_exports),
            "dead_vue_components": len(vue_unused_components),
            "dead_code_total": dead_code_payload["summary"]["total"],
        },
        "chains": chains,
        "symbols": {k: v for k, v in list(symbols.items())[:max_symbols]},
        "dead_code": dead_code_payload,
    }

    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "call-graph.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    (data_dir / "call_graph.js").write_text(
        f"window.CALL_GRAPH = {json.dumps({'summary': payload['summary'], 'chains': chains})};\n",
        encoding="utf-8",
    )
    (data_dir / "dead-code.json").write_text(json.dumps(dead_code_payload, indent=2), encoding="utf-8")
    return payload
