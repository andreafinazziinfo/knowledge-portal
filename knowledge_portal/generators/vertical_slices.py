"""
ADR-082 Wave 2 (AI-3): Cross-Stack 6-Layer Vertical Slice Generator (100% Python stdlib).

Builds deterministic end-to-end chains across:
  1. UI View / Component (.vue, .tsx, .jsx)
  2. State Store / Composable (Pinia, Redux, Zustand, composables)
  3. Frontend API Client Call (fetch, axios, custom fetch wrappers)
  4. Backend HTTP Route (FastAPI / Flask / Express via api-catalog.json)
  5. Service / Async Task (call-graph.json + AST task triggers)
  6. Storage Layer (Redis keys + SQL / ORM tables via db-schema.json)

Writes:
  - <data_dir>/vertical-slices.json
  - <data_dir>/vertical_slices.js (window.VERTICAL_SLICES_DATA)
"""

from __future__ import annotations

import ast
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    "dist",
    "dev-dist",
    "build",
    "coverage",
    "vendor",
    "graphify-out",
    "knowledge_portal",
    ".next",
    ".nuxt",
    "out",
    "htmlcov",
}

FE_EXTENSIONS = {".vue", ".ts", ".tsx", ".js", ".jsx"}
COMPONENT_EXTENSIONS = {".vue", ".tsx", ".jsx"}

# Patterns for store definitions (Pinia, Redux Toolkit, Zustand)
_DEFINE_STORE_RE = re.compile(
    r"""(?:export\s+const\s+(?P<export>\w+)\s*=\s*)?defineStore\s*\(\s*['"](?P<id>[^'"]+)['"]""",
    re.MULTILINE,
)
_REDUX_SLICE_RE = re.compile(
    r"""(?:export\s+const\s+(?P<export>\w+)\s*=\s*)?createSlice\s*\(\s*\{\s*name\s*:\s*['"](?P<id>[^'"]+)['"]""",
    re.MULTILINE,
)
_ZUSTAND_STORE_RE = re.compile(
    r"""export\s+const\s+(?P<export>use\w+Store)\s*=\s*create\s*(?:<[^>]+>)?\s*\(""",
    re.MULTILINE,
)

# Local API prefix helper: const api = (p: string) => `${baseUrl}/api/v1/dataops${p}`
_API_HELPER_RE = re.compile(
    r"""const\s+(?P<fn>\w+)\s*=\s*\([^)]*\)\s*=>\s*`[^`]*?(?P<prefix>/api(?:/v\d+)?/[a-zA-Z0-9_\-/]+)\$\{[^}]+\}""",
)

# Direct URL literals in TS/JS/Vue
_API_URL_LITERAL_RE = re.compile(
    r"""(?P<quote>['"`])(?P<url>(?:https?://[^'"`\s]+|\$\{[^}]+\})?/api(?:/v\d+)?/[^'"`\s?#]+(?:\?[^'"`\s]*)?)(?P=quote)"""
)
_WS_URL_LITERAL_RE = re.compile(
    r"""(?P<quote>['"`])(?P<url>(?:wss?://[^'"`\s]+|\$\{[^}]+\})?(?:/api(?:/v\d+)?)?/ws/[^'"`\s?#]+)(?P=quote)"""
)
_AXIOS_CALL_RE = re.compile(
    r"""\b(?:axios|api|apiClient|http|client)\.(?P<method>get|post|put|patch|delete)\s*(?:<[^>]+>)?\s*\(\s*(?P<quote>['"`])(?P<url>[^'"`\s]+)(?P=quote)""",
    re.IGNORECASE,
)
_METHOD_OPT_RE = re.compile(r"""method\s*:\s*['"](GET|POST|PUT|PATCH|DELETE)['"]""", re.IGNORECASE)
_IMPORT_RE = re.compile(r"""import\s+(?P<spec>[\s\S]{1,300}?)\s+from\s+['"](?P<mod>[^'"]+)['"]""")

# Backend SQL / Redis / Celery lightweight extractors
_SQL_TABLE_RE = re.compile(
    r"""\b(?:FROM|JOIN|INTO|UPDATE)\s+(?:ONLY\s+)?(?:public\.)?([a-z_][a-z0-9_]{2,})\b""",
    re.IGNORECASE,
)
_SQL_STOPWORDS = {
    "select", "where", "values", "set", "table", "index", "view", "dual",
    "lateral", "unnest", "generate_series", "json_each", "jsonb_each",
    "excluded", "information_schema", "pg_catalog", "pg_class",
}
_REDIS_KEY_RE = re.compile(
    r"""\b(?:redis|redis_client|cache|rc|r)\.(?:get|set|setex|setnx|hget|hset|hgetall|delete|expire|lock|publish)\s*\(\s*(?:f)?['"]([^'"]{2,80})['"]"""
)
_CELERY_CALL_RE = re.compile(
    r"""\b([a-zA-Z_][a-zA-Z0-9_]*)\.(?:delay|apply_async)\s*\("""
)
_SEND_TASK_RE = re.compile(
    r"""\.send_task\s*\(\s*['"]([^'"]+)['"]"""
)


def normalize_api_path(raw: str) -> str:
    """Normalize dynamic frontend/backend URLs into a canonical `{param}` template."""
    s = raw.strip()
    s = re.sub(r"""^(?:https?|wss?)://[^/]+""", "", s)
    s = re.sub(r"""^\$\{[^}]+\}""", "", s)
    s = s.split("?", 1)[0].split("#", 1)[0]
    s = re.sub(r"""\$\{[^}]+\}""", "{param}", s)
    s = re.sub(r"""\{[^}]+\}""", "{param}", s)
    s = re.sub(r"""/:[a-zA-Z_][a-zA-Z0-9_]*""", "/{param}", s)
    s = re.sub(r"""<[^>]+>""", "{param}", s)
    s = re.sub(r"""/{2,}""", "/", s)
    if not s.startswith("/"):
        s = "/" + s
    if len(s) > 1 and s.endswith("/"):
        s = s[:-1]
    return s


def strip_api_prefix(norm_path: str) -> str:
    """Strip common `/api/v1` or `/api` prefixes so mounted routers match cleanly."""
    stripped = re.sub(r"""^/api(?:/v\d+)?(?=/|$)""", "", norm_path)
    return stripped if stripped else "/"


def _should_skip_file(rel: str) -> bool:
    low = rel.lower()
    if any(
        low.endswith(suf)
        for suf in (
            ".d.ts",
            ".generated.ts",
            ".min.js",
            ".spec.ts",
            ".spec.js",
            ".test.ts",
            ".test.js",
            ".test.tsx",
            ".spec.tsx",
        )
    ):
        return True
    parts = set(Path(rel).parts)
    if parts & SKIP_DIRS:
        return True
    return False


def _walk_files(project_dir: Path, extensions: set[str]) -> list[Path]:
    results: list[Path] = []
    for root, dirs, files in os.walk(project_dir):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
        for fname in files:
            p = Path(root) / fname
            if p.suffix.lower() not in extensions:
                continue
            rel = p.relative_to(project_dir).as_posix()
            if _should_skip_file(rel):
                continue
            results.append(p)
    return sorted(results)


def _extract_fe_calls(content: str, rel_path: str) -> list[dict[str, Any]]:
    """Extract normalized HTTP/WS calls from a single frontend file."""
    calls: list[dict[str, Any]] = []
    seen: set[tuple[str, str, int]] = set()

    # 1. Detect helper functions like `const api = (p: string) => `${base}/api/v1/dataops${p}``
    helper_prefixes: dict[str, str] = {}
    for m in _API_HELPER_RE.finditer(content):
        helper_prefixes[m.group("fn")] = m.group("prefix").rstrip("/")

    for fn_name, prefix in helper_prefixes.items():
        call_re = re.compile(
            rf"""\b{re.escape(fn_name)}\s*\(\s*(?P<q>['"`])(?P<subpath>/[^'"`]*)(?P=q)"""
        )
        for m in call_re.finditer(content):
            line = content.count("\n", 0, m.start()) + 1
            raw_url = prefix + m.group("subpath")
            norm = normalize_api_path(raw_url)
            window = content[max(0, m.start() - 40) : min(len(content), m.end() + 180)]
            mm = _METHOD_OPT_RE.search(window)
            method = mm.group(1).upper() if mm else "ANY"
            key = (method, norm, line)
            if key not in seen:
                seen.add(key)
                calls.append(
                    {
                        "file": rel_path,
                        "line": line,
                        "method": method,
                        "raw_url": raw_url,
                        "norm_path": norm,
                        "kind": "http",
                    }
                )

    # 2. Explicit axios/api.get/post/put/patch/delete calls
    for m in _AXIOS_CALL_RE.finditer(content):
        raw_url = m.group("url")
        if not raw_url.startswith("/") and "/api" not in raw_url:
            continue
        line = content.count("\n", 0, m.start()) + 1
        norm = normalize_api_path(raw_url)
        method = m.group("method").upper()
        key = (method, norm, line)
        if key not in seen:
            seen.add(key)
            calls.append(
                {
                    "file": rel_path,
                    "line": line,
                    "method": method,
                    "raw_url": raw_url,
                    "norm_path": norm,
                    "kind": "http",
                }
            )

    # 3. Any string/template literal containing `/api/...`
    for m in _API_URL_LITERAL_RE.finditer(content):
        raw_url = m.group("url")
        tail = content[m.end() : m.end() + 30]
        if re.match(r"""^\s*\+\s*[a-zA-Z_]""", tail):
            raw_url = raw_url.rstrip("/") + "/{param}"
        line = content.count("\n", 0, m.start()) + 1
        norm = normalize_api_path(raw_url)
        line_start = content.rfind("\n", 0, m.start()) + 1
        line_prefix = content[line_start : m.start()].lstrip()
        if line_prefix.startswith("//") or line_prefix.startswith("*"):
            continue
        window = content[max(0, m.start() - 60) : min(len(content), m.end() + 200)]
        mm = _METHOD_OPT_RE.search(window)
        method = mm.group(1).upper() if mm else "ANY"
        key = (method, norm, line)
        if key not in seen:
            seen.add(key)
            calls.append(
                {
                    "file": rel_path,
                    "line": line,
                    "method": method,
                    "raw_url": raw_url,
                    "norm_path": norm,
                    "kind": "http",
                }
            )

    # 4. WebSocket literals
    for m in _WS_URL_LITERAL_RE.finditer(content):
        raw_url = m.group("url")
        line = content.count("\n", 0, m.start()) + 1
        norm = normalize_api_path(raw_url)
        key = ("WS", norm, line)
        if key not in seen:
            seen.add(key)
            calls.append(
                {
                    "file": rel_path,
                    "line": line,
                    "method": "WS",
                    "raw_url": raw_url,
                    "norm_path": norm,
                    "kind": "ws",
                }
            )

    return calls


def _extract_store_info(content: str, rel_path: str, calls: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Detect Pinia, Redux Toolkit, or Zustand store definitions and compute hygiene metrics."""
    store_id = ""
    export_name = ""
    framework = ""

    m = _DEFINE_STORE_RE.search(content)
    if m:
        store_id = m.group("id")
        export_name = m.group("export") or Path(rel_path).stem
        framework = "pinia"
    else:
        m = _REDUX_SLICE_RE.search(content)
        if m:
            store_id = m.group("id")
            export_name = m.group("export") or Path(rel_path).stem
            framework = "redux"
        else:
            m = _ZUSTAND_STORE_RE.search(content)
            if m:
                export_name = m.group("export")
                store_id = export_name
                framework = "zustand"

    if not store_id:
        return None

    loc = content.count("\n") + 1
    state_refs = len(re.findall(r"""\b(?:ref|shallowRef|reactive|computed)\s*(?:<[^>]+>)?\s*\(""", content))
    actions = len(
        re.findall(
            r"""\b(?:async\s+)?function\s+\w+\s*\(|\bconst\s+\w+\s*=\s*(?:async\s*)?\([^)]*\)\s*=>""",
            content,
        )
    )
    cross_store_deps: list[str] = []
    for im in _IMPORT_RE.finditer(content):
        mod = im.group("mod")
        if "/stores/" in mod or (mod.startswith("./") and "store" in mod.lower()):
            cross_store_deps.append(Path(mod).stem)

    is_god_store = loc >= 300 or state_refs >= 15 or actions >= 15
    return {
        "id": store_id,
        "name": export_name,
        "framework": framework,
        "file": rel_path,
        "loc": loc,
        "state_refs": state_refs,
        "actions": actions,
        "cross_store_deps": sorted(set(cross_store_deps)),
        "api_calls_count": len(calls),
        "endpoints": sorted({c["norm_path"] for c in calls}),
        "consumers": [],
        "is_god_store": is_god_store,
    }


def _extract_backend_downstream(
    project_dir: Path,
    handler_file: str,
    handler_name: str,
    call_graph_chains: dict[str, dict[str, Any]],
    db_tables_by_file: dict[str, set[str]],
    known_tables: set[str],
    backend_cache: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Resolve Layer 5 (services & Celery tasks) and Layer 6 (Redis keys & DB tables)."""
    if handler_file in backend_cache:
        base = backend_cache[handler_file]
    else:
        services: set[str] = set()
        celery_tasks: set[str] = set()
        redis_keys: set[str] = set()
        db_tables: set[str] = set(db_tables_by_file.get(handler_file, set()))

        fpath = project_dir / handler_file
        if fpath.exists() and fpath.suffix == ".py":
            try:
                text = fpath.read_text(encoding="utf-8", errors="replace")
            except OSError:
                text = ""
            for tm in _CELERY_CALL_RE.finditer(text):
                celery_tasks.add(tm.group(1))
            for sm in _SEND_TASK_RE.finditer(text):
                celery_tasks.add(sm.group(1))
            for rm in _REDIS_KEY_RE.finditer(text):
                redis_keys.add(rm.group(1))
            for qm in _SQL_TABLE_RE.finditer(text):
                tbl = qm.group(1).lower()
                if tbl not in _SQL_STOPWORDS and (not known_tables or tbl in known_tables):
                    db_tables.add(tbl)
            try:
                tree = ast.parse(text)
                for node in ast.walk(tree):
                    if isinstance(node, ast.ImportFrom) and node.module:
                        mod = node.module
                        if any(
                            k in mod
                            for k in (".services", ".workers", ".repositories", ".db", ".domain", ".ingestion")
                        ):
                            services.add(mod)
            except SyntaxError:
                pass

        base = {
            "services": sorted(services)[:12],
            "celery_tasks": sorted(celery_tasks)[:10],
            "redis_keys": sorted(redis_keys)[:10],
            "db_tables": sorted(db_tables)[:12],
        }
        backend_cache[handler_file] = base

    chain_key = f"{handler_file}::{handler_name}"
    chain = call_graph_chains.get(chain_key)
    if not chain:
        return base

    services_set = set(base["services"])
    tables_set = set(base["db_tables"])
    for t in chain.get("db_tables", []) or []:
        tables_set.add(str(t))
    for step in chain.get("steps", []) or []:
        if not isinstance(step, dict):
            continue
        sfile = str(step.get("file", ""))
        if sfile and sfile != handler_file:
            services_set.add(sfile)
            tables_set.update(db_tables_by_file.get(sfile, set()))
        for t in step.get("db_tables", []) or []:
            tables_set.add(str(t))

    return {
        "services": sorted(services_set)[:12],
        "celery_tasks": base["celery_tasks"],
        "redis_keys": base["redis_keys"],
        "db_tables": sorted(tables_set)[:12],
    }


def _match_endpoint(
    fe_call: dict[str, Any],
    exact_index: dict[tuple[str, str], dict[str, Any]],
    stripped_index: dict[tuple[str, str], dict[str, Any]],
    path_only_index: dict[str, list[dict[str, Any]]],
    stripped_path_only_index: dict[str, list[dict[str, Any]]],
) -> tuple[dict[str, Any] | None, float]:
    """Match a normalized frontend call against indexed backend endpoints."""
    method = fe_call["method"]
    norm = fe_call["norm_path"]
    stripped = strip_api_prefix(norm)
    is_param = "{param}" in norm

    if (method, norm) in exact_index:
        return exact_index[(method, norm)], (0.85 if is_param else 1.0)
    if (method, stripped) in stripped_index:
        return stripped_index[(method, stripped)], (0.85 if is_param else 1.0)
    if norm in path_only_index:
        eps = path_only_index[norm]
        chosen = next((e for e in eps if e.get("method") == "GET"), eps[0])
        return chosen, (0.85 if is_param else 1.0)
    if stripped in stripped_path_only_index:
        eps = stripped_path_only_index[stripped]
        chosen_exact: dict[str, Any] | None = next((e for e in eps if e.get("method") == method), None)
        if chosen_exact is not None:
            return chosen_exact, (0.85 if is_param else 1.0)
        chosen = next((e for e in eps if e.get("method") == "GET"), eps[0])
        if method == "ANY":
            return chosen, (0.85 if is_param else 1.0)
        return chosen, 0.85

    return None, 0.0


def _infer_feature(endpoint_path: str, tag: str) -> str:
    if tag and tag.lower() not in ("default", "api", "general"):
        return tag.lower().replace(" ", "-")
    stripped = strip_api_prefix(endpoint_path).strip("/")
    if not stripped:
        return "root"
    return stripped.split("/", 1)[0].lower()


def generate_vertical_slices(project_dir: Path, data_dir: Path) -> dict[str, Any]:
    """Generate cross-stack 6-layer vertical slices and write JSON + JS artifacts."""
    project_dir = Path(project_dir).resolve()
    data_dir = Path(data_dir).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)

    # 1. Load api-catalog.json
    api_endpoints: list[dict[str, Any]] = []
    api_file = data_dir / "api-catalog.json"
    if api_file.exists():
        try:
            api_data = json.loads(api_file.read_text(encoding="utf-8"))
            api_endpoints = api_data.get("endpoints", []) or []
        except (OSError, json.JSONDecodeError):
            api_endpoints = []

    exact_index: dict[tuple[str, str], dict[str, Any]] = {}
    stripped_index: dict[tuple[str, str], dict[str, Any]] = {}
    path_only_index: dict[str, list[dict[str, Any]]] = {}
    stripped_path_only_index: dict[str, list[dict[str, Any]]] = {}

    for ep in api_endpoints:
        if not isinstance(ep, dict) or not ep.get("path"):
            continue
        method = str(ep.get("method", "GET")).upper()
        norm = normalize_api_path(str(ep["path"]))
        stripped = strip_api_prefix(norm)
        exact_index.setdefault((method, norm), ep)
        stripped_index.setdefault((method, stripped), ep)
        path_only_index.setdefault(norm, []).append(ep)
        stripped_path_only_index.setdefault(stripped, []).append(ep)

    # 2. Load call-graph.json
    call_graph_chains: dict[str, dict[str, Any]] = {}
    cg_file = data_dir / "call-graph.json"
    if cg_file.exists():
        try:
            cg_data = json.loads(cg_file.read_text(encoding="utf-8"))
            for ch in cg_data.get("chains", []) or []:
                if isinstance(ch, dict) and ch.get("entry_id"):
                    call_graph_chains[str(ch["entry_id"])] = ch
        except (OSError, json.JSONDecodeError):
            pass

    # 3. Load db-schema.json
    db_tables_by_file: dict[str, set[str]] = {}
    known_tables: set[str] = set()
    db_file = data_dir / "db-schema.json"
    if db_file.exists():
        try:
            db_data = json.loads(db_file.read_text(encoding="utf-8"))
            tables = db_data.get("tables", [])
            if isinstance(tables, dict):
                tables_iter = list(tables.values())
            elif isinstance(tables, list):
                tables_iter = tables
            else:
                tables_iter = []
            for tbl in tables_iter:
                if not isinstance(tbl, dict) or not tbl.get("name"):
                    continue
                tname = str(tbl["name"]).lower()
                known_tables.add(tname)
                for rw_key in ("readers", "writers"):
                    for ref in tbl.get(rw_key, []) or []:
                        ref_str = str(ref.get("file", "") if isinstance(ref, dict) else ref)
                        if ref_str:
                            db_tables_by_file.setdefault(ref_str.split(":", 1)[0], set()).add(tname)
        except (OSError, json.JSONDecodeError):
            pass

    # 4. Scan frontend files
    fe_files = _walk_files(project_dir, FE_EXTENSIONS)
    stores_by_file: dict[str, dict[str, Any]] = {}
    stores_by_symbol: dict[str, str] = {}
    stores_by_stem: dict[str, str] = {}
    all_fe_calls: list[dict[str, Any]] = []
    file_imports: dict[str, list[tuple[str, str]]] = {}
    component_files: set[str] = set()

    for fpath in fe_files:
        rel = fpath.relative_to(project_dir).as_posix()
        try:
            content = fpath.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        if fpath.suffix.lower() in COMPONENT_EXTENSIONS:
            component_files.add(rel)

        calls = _extract_fe_calls(content, rel)
        all_fe_calls.extend(calls)

        imps: list[tuple[str, str]] = []
        for im in _IMPORT_RE.finditer(content):
            imps.append((im.group("spec"), im.group("mod")))
        file_imports[rel] = imps

        if fpath.suffix.lower() in {".ts", ".js"}:
            sinfo = _extract_store_info(content, rel, calls)
            if sinfo:
                stores_by_file[rel] = sinfo
                stores_by_symbol[sinfo["name"]] = rel
                stores_by_stem[fpath.stem] = rel

    # 5. Map components -> stores & API client files
    consumers_by_file: dict[str, set[str]] = {}
    for fe_file, imps in file_imports.items():
        for spec, mod in imps:
            stem = Path(mod).stem
            target_store_file = stores_by_stem.get(stem)
            if not target_store_file:
                for sym, sfile in stores_by_symbol.items():
                    if sym in spec:
                        target_store_file = sfile
                        break
            if target_store_file and target_store_file != fe_file:
                if fe_file in component_files:
                    stores_by_file[target_store_file]["consumers"].append(fe_file)
                consumers_by_file.setdefault(target_store_file, set()).add(fe_file)
            elif stem:
                consumers_by_file.setdefault(stem, set()).add(fe_file)

    for sinfo in stores_by_file.values():
        sinfo["consumers"] = sorted(set(sinfo["consumers"]))

    # 6. Match frontend calls to backend endpoints -> cross_stack_edges & 6-layer slices
    cross_stack_edges: list[dict[str, Any]] = []
    seen_edges: set[tuple[str, str, str, str]] = set()
    slices_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    unmatched_calls: list[dict[str, Any]] = []
    backend_cache: dict[str, dict[str, Any]] = {}
    exact_matches = 0
    param_matches = 0

    for call in all_fe_calls:
        matched_ep, conf = _match_endpoint(
            call,
            exact_index,
            stripped_index,
            path_only_index,
            stripped_path_only_index,
        )
        if matched_ep is None:
            unmatched_calls.append(
                {
                    "file": call["file"],
                    "line": call["line"],
                    "method": call["method"],
                    "norm_path": call["norm_path"],
                }
            )
            continue

        ep_method = str(matched_ep.get("method", "GET")).upper()
        ep_path = str(matched_ep.get("path", ""))
        ep_file = str(matched_ep.get("file", ""))
        ep_handler = str(matched_ep.get("handler", ""))
        ep_line = int(matched_ep.get("line", 0) or 0)

        edge_key = (call["file"], ep_file, ep_method, ep_path)
        if edge_key not in seen_edges:
            seen_edges.add(edge_key)
            if conf >= 1.0:
                exact_matches += 1
            else:
                param_matches += 1
            cross_stack_edges.append(
                {
                    "source": call["file"],
                    "target": ep_file,
                    "type": "FE_CALLS_API",
                    "method": ep_method,
                    "path": ep_path,
                    "frontend_url": call["norm_path"],
                    "handler": ep_handler,
                    "confidence": conf,
                    "line": call["line"],
                }
            )

        slice_key = (ep_method, ep_path)
        if slice_key not in slices_by_key:
            downstream = _extract_backend_downstream(
                project_dir=project_dir,
                handler_file=ep_file,
                handler_name=ep_handler,
                call_graph_chains=call_graph_chains,
                db_tables_by_file=db_tables_by_file,
                known_tables=known_tables,
                backend_cache=backend_cache,
            )
            feature = _infer_feature(ep_path, str(matched_ep.get("tag", "")))
            slices_by_key[slice_key] = {
                "id": f"{ep_method} {ep_path}",
                "feature": feature,
                "method": ep_method,
                "endpoint": ep_path,
                "confidence": conf,
                "layers": {
                    "components": [],
                    "stores": [],
                    "api_clients": [],
                    "backend_route": {
                        "file": ep_file,
                        "handler": ep_handler,
                        "line": ep_line,
                        "auth": str(matched_ep.get("auth", "Unknown")),
                    },
                    "services_and_tasks": {
                        "services": downstream["services"],
                        "celery_tasks": downstream["celery_tasks"],
                    },
                    "storage": {
                        "redis_keys": downstream["redis_keys"],
                        "db_tables": downstream["db_tables"],
                    },
                },
            }

        sl = slices_by_key[slice_key]
        if conf > sl["confidence"]:
            sl["confidence"] = conf
        fe_file = call["file"]
        client_ref = f"{fe_file}:{call['line']}"
        if client_ref not in sl["layers"]["api_clients"]:
            sl["layers"]["api_clients"].append(client_ref)

        if fe_file in stores_by_file:
            sinfo = stores_by_file[fe_file]
            store_label = f"{sinfo['name']} ({fe_file})"
            if store_label not in sl["layers"]["stores"]:
                sl["layers"]["stores"].append(store_label)
            for comp in sinfo["consumers"]:
                if comp not in sl["layers"]["components"]:
                    sl["layers"]["components"].append(comp)
        elif fe_file in component_files:
            if fe_file not in sl["layers"]["components"]:
                sl["layers"]["components"].append(fe_file)
        else:
            stem = Path(fe_file).stem
            for consumer in sorted(consumers_by_file.get(stem, set())):
                if consumer in stores_by_file:
                    sinfo = stores_by_file[consumer]
                    store_label = f"{sinfo['name']} ({consumer})"
                    if store_label not in sl["layers"]["stores"]:
                        sl["layers"]["stores"].append(store_label)
                    for comp in sinfo["consumers"]:
                        if comp not in sl["layers"]["components"]:
                            sl["layers"]["components"].append(comp)
                elif consumer in component_files:
                    if consumer not in sl["layers"]["components"]:
                        sl["layers"]["components"].append(consumer)

    slices = sorted(
        slices_by_key.values(),
        key=lambda s: (s["feature"], s["endpoint"], s["method"]),
    )
    for sl in slices:
        sl["layers"]["components"] = sorted(sl["layers"]["components"])[:15]
        sl["layers"]["stores"] = sorted(sl["layers"]["stores"])[:10]
        sl["layers"]["api_clients"] = sl["layers"]["api_clients"][:10]

    by_feature: dict[str, int] = {}
    for sl in slices:
        by_feature[sl["feature"]] = by_feature.get(sl["feature"], 0) + 1

    stores_list = sorted(stores_by_file.values(), key=lambda s: (-s["loc"], s["name"]))
    god_stores_count = sum(1 for s in stores_list if s["is_god_store"])

    payload: dict[str, Any] = {
        "schema_version": "1.0",
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "summary": {
            "total_slices": len(slices),
            "cross_stack_edges_count": len(cross_stack_edges),
            "exact_matches": exact_matches,
            "parameterized_matches": param_matches,
            "stores_count": len(stores_list),
            "god_stores_count": god_stores_count,
            "components_count": len(component_files),
            "matched_endpoints_count": len(slices),
            "unmatched_fe_calls_count": len(unmatched_calls),
            "features_count": len(by_feature),
            "by_feature": dict(sorted(by_feature.items(), key=lambda kv: -kv[1])[:20]),
        },
        "slices": slices,
        "cross_stack_edges": cross_stack_edges,
        "stores": stores_list,
        "unmatched_calls": unmatched_calls[:100],
    }

    json_path = data_dir / "vertical-slices.json"
    js_path = data_dir / "vertical_slices.js"
    json_text = json.dumps(payload, indent=2)
    json_path.write_text(json_text, encoding="utf-8")
    js_path.write_text(f"window.VERTICAL_SLICES_DATA = {json_text};\n", encoding="utf-8")
    return payload
