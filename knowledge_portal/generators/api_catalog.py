"""
Knowledge Portal — Polyglot API & Endpoint Catalog Generator (ADR-076).
100% Python stdlib zero-dependency route extractor supporting:
- Python AST: FastAPI, Starlette, Flask (incl. APIRouter prefix, auth Depends, response_model)
- JS/TS: Express, Fastify, Koa, Hono
- Go: net/http HandleFunc, Gin, Echo, Fiber
- OpenAPI JSON auto-ingestion (openapi.json / swagger.json)

Outputs OpenAPI 3.1-compatible `data/api-catalog.json` and `data/api_catalog.js`.
Strictly enforces P4 Gate (excludes frozen/, .git, node_modules, venv, tests).
"""

from __future__ import annotations

import ast
import json
import os
import re
import time
from collections import Counter
from pathlib import Path
from typing import Any

_IGNORE_DIRS = frozenset({
    ".git", "node_modules", "dist", "build", ".venv", "venv",
    "__pycache__", ".idea", ".vscode", "target", "vendor", "bin", "obj", "frozen",
})
_HTTP_METHODS = frozenset({"get", "post", "put", "patch", "delete", "options", "head", "websocket"})
_ROUTER_RECEIVERS = frozenset({"app", "router", "api_router", "bp", "blueprint", "v1_router", "api"})
_AUTH_HINTS = ("depends", "security", "auth", "current_user", "require_admin", "user", "token", "api_key", "guard", "permission")

_JS_ROUTE_RE = re.compile(
    r"""\b(?:app|router|server|fastify)\.(get|post|put|patch|delete)\s*\(\s*["'`]([^"'`\n]+)["'`]""",
    re.IGNORECASE,
)
_GO_ROUTE_RE = re.compile(
    r"""\.(?:HandleFunc|(GET|POST|PUT|PATCH|DELETE))\s*\(\s*"([^"\n]+)"\s*,""",
)


def _is_ignored(rel: str) -> bool:
    parts = [p.lower() for p in rel.replace("\\", "/").split("/")]
    if any(p in _IGNORE_DIRS or p.startswith(".") for p in parts[:-1]) or "frozen" in parts:
        return True
    low = f"/{rel.lower()}"
    return any(h in low for h in ("/tests/", "/test/", "/test_", "_test.py", ".spec.", ".test.", "conftest.py"))


def _call_parts(call: ast.Call) -> tuple[str, str]:
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


def _tag_from_path(rel: str, route_path: str) -> str:
    segs = [s for s in route_path.split("/") if s and not s.startswith("{") and s not in ("api", "v1", "v2")]
    if segs:
        return segs[0].replace("-", " ").replace("_", " ").title()
    stem = Path(rel).stem
    return stem.replace("_", " ").replace("-", " ").title()


def _extract_python_routes(rel: str, src: str) -> list[dict[str, Any]]:
    try:
        tree = ast.parse(src)
    except Exception:
        return []

    # Detect file-level APIRouter(prefix="...") or Blueprint(..., url_prefix="...")
    router_prefix = ""
    router_tags: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            _, fname = _call_parts(node)
            if fname in ("apirouter", "blueprint"):
                for kw in node.keywords:
                    if kw.arg in ("prefix", "url_prefix") and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                        router_prefix = kw.value.value.rstrip("/")
                    elif kw.arg == "tags" and isinstance(kw.value, (ast.List, ast.Tuple)):
                        for elt in kw.value.elts:
                            if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                                router_tags.append(elt.value)

    endpoints: list[dict[str, Any]] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        doc = (ast.get_docstring(node) or "").strip()
        summary = doc.splitlines()[0][:140] if doc else node.name.replace("_", " ").title()
        lineno = getattr(node, "lineno", 1)

        for dec in node.decorator_list:
            if not isinstance(dec, ast.Call):
                continue
            recv, attr = _call_parts(dec)
            if recv and recv not in _ROUTER_RECEIVERS and not recv.endswith("_router"):
                continue

            methods: list[str] = []
            if attr in _HTTP_METHODS:
                methods = ["WS" if attr == "websocket" else attr.upper()]
            elif attr == "route":
                for kw in dec.keywords:
                    if kw.arg == "methods" and isinstance(kw.value, (ast.List, ast.Tuple)):
                        for elt in kw.value.elts:
                            if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                                methods.append(elt.value.upper())
                if not methods:
                    methods = ["GET"]
            else:
                continue

            raw_route = ""
            if dec.args and isinstance(dec.args[0], ast.Constant) and isinstance(dec.args[0].value, str):
                raw_route = dec.args[0].value
            else:
                for kw in dec.keywords:
                    if kw.arg in ("path", "rule") and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                        raw_route = kw.value.value
                        break
            if not raw_route:
                continue

            full_path = f"{router_prefix}/{raw_route.lstrip('/')}" if router_prefix else raw_route
            if not full_path.startswith("/"):
                full_path = "/" + full_path
            full_path = re.sub(r"//+", "/", full_path)

            dec_kw = {kw.arg: kw.value for kw in dec.keywords if kw.arg}
            # Auth detection
            auth = "Public"
            if "dependencies" in dec_kw:
                auth = "Protected"
            else:
                arg_names = [a.arg.lower() for a in node.args.args + node.args.kwonlyargs]
                if any(any(h in an for h in _AUTH_HINTS) for an in arg_names):
                    auth = "Protected"
                else:
                    defaults = list(node.args.defaults) + [d for d in node.args.kw_defaults if d is not None]
                    for d in defaults:
                        if isinstance(d, ast.Call):
                            _, dn = _call_parts(d)
                            if dn in ("depends", "security"):
                                auth = "Protected"
                                break

            resp_model = None
            if "response_model" in dec_kw:
                resp_model = ast.unparse(dec_kw["response_model"]) if hasattr(ast, "unparse") else "Model"
            elif node.returns is not None:
                resp_model = ast.unparse(node.returns) if hasattr(ast, "unparse") else "Typed"

            tag = router_tags[0] if router_tags else _tag_from_path(rel, full_path)
            if "tags" in dec_kw and isinstance(dec_kw["tags"], (ast.List, ast.Tuple)) and dec_kw["tags"].elts:
                first_t = dec_kw["tags"].elts[0]
                if isinstance(first_t, ast.Constant) and isinstance(first_t.value, str):
                    tag = first_t.value

            for m in methods:
                endpoints.append({
                    "method": m,
                    "path": full_path,
                    "tag": tag,
                    "summary": summary,
                    "handler": node.name,
                    "file": rel,
                    "line": lineno,
                    "auth": auth,
                    "response_model": resp_model,
                    "framework": "Python",
                })
    return endpoints


def _extract_js_go_routes(rel: str, src: str, ext: str) -> list[dict[str, Any]]:
    endpoints: list[dict[str, Any]] = []
    if ext in (".js", ".ts", ".jsx", ".tsx", ".mjs"):
        for lineno, line in enumerate(src.splitlines(), 1):
            m = _JS_ROUTE_RE.search(line)
            if m:
                method = m.group(1).upper()
                path = m.group(2)
                endpoints.append({
                    "method": method,
                    "path": path,
                    "tag": _tag_from_path(rel, path),
                    "summary": f"{method} {path}",
                    "handler": Path(rel).stem,
                    "file": rel,
                    "line": lineno,
                    "auth": "Protected" if any(h in line.lower() for h in ("auth", "guard", "jwt", "verify")) else "Public",
                    "response_model": None,
                    "framework": "Node/TS",
                })
    elif ext == ".go":
        for lineno, line in enumerate(src.splitlines(), 1):
            m = _GO_ROUTE_RE.search(line)
            if m:
                method = (m.group(1) or "GET").upper()
                path = m.group(2)
                endpoints.append({
                    "method": method,
                    "path": path,
                    "tag": _tag_from_path(rel, path),
                    "summary": f"{method} {path}",
                    "handler": Path(rel).stem,
                    "file": rel,
                    "line": lineno,
                    "auth": "Public",
                    "response_model": None,
                    "framework": "Go",
                })
    return endpoints


def _build_openapi_spec(project_name: str, endpoints: list[dict[str, Any]]) -> dict[str, Any]:
    paths: dict[str, dict[str, Any]] = {}
    for ep in endpoints:
        m_low = ep["method"].lower()
        if m_low not in ("get", "post", "put", "patch", "delete", "options", "head"):
            continue
        p = ep["path"]
        paths.setdefault(p, {})[m_low] = {
            "tags": [ep["tag"]],
            "summary": ep["summary"],
            "description": f"Handler: `{ep['file']}:{ep['line']}` (`{ep['handler']}`)",
            "responses": {"200": {"description": ep.get("response_model") or "OK"}},
        }
    return {
        "openapi": "3.1.0",
        "info": {"title": f"{project_name} API", "version": "1.0.0"},
        "paths": paths,
    }


def generate_api_catalog(project_dir: Path, data_dir: Path, max_files: int = 2500) -> dict[str, Any]:
    """Scan project_dir for HTTP/WebSocket routes and write data/api-catalog.json + api_catalog.js."""
    project_dir = Path(project_dir).resolve()
    data_dir = Path(data_dir)
    endpoints: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    scanned = 0

    for root, dirs, files in os.walk(project_dir):
        dirs[:] = [d for d in dirs if d not in _IGNORE_DIRS and not d.startswith(".")]
        for fname in files:
            if scanned >= max_files:
                break
            ext = os.path.splitext(fname)[1].lower()
            if ext not in (".py", ".js", ".ts", ".jsx", ".tsx", ".mjs", ".go"):
                continue
            if fname.endswith((".min.js", ".bundle.js", ".d.ts")):
                continue
            fpath = Path(root) / fname
            rel = str(fpath.relative_to(project_dir)).replace("\\", "/")
            if _is_ignored(rel):
                continue
            try:
                if fpath.stat().st_size > 400_000:
                    continue
                src = fpath.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            scanned += 1
            found = _extract_python_routes(rel, src) if ext == ".py" else _extract_js_go_routes(rel, src, ext)
            for ep in found:
                key = (ep["method"], ep["path"], ep["file"])
                if key not in seen:
                    seen.add(key)
                    endpoints.append(ep)

    # Optional OpenAPI JSON auto-ingestion if no routes found or to enrich
    openapi_loaded: dict[str, Any] | None = None
    for cand in ("openapi.json", "swagger.json", "backend/openapi.json", "docs/openapi.json"):
        cp = project_dir / cand
        if cp.is_file():
            try:
                spec = json.loads(cp.read_text(encoding="utf-8"))
                if isinstance(spec, dict) and isinstance(spec.get("paths"), dict):
                    openapi_loaded = spec
                    for path_str, methods_obj in spec["paths"].items():
                        if not isinstance(methods_obj, dict):
                            continue
                        for m_name, op in methods_obj.items():
                            if m_name.lower() not in _HTTP_METHODS or not isinstance(op, dict):
                                continue
                            key = (m_name.upper(), path_str, cand)
                            if not any(e["method"] == m_name.upper() and e["path"] == path_str for e in endpoints):
                                seen.add(key)
                                tags = op.get("tags") or [_tag_from_path(cand, path_str)]
                                endpoints.append({
                                    "method": m_name.upper(),
                                    "path": path_str,
                                    "tag": str(tags[0]),
                                    "summary": str(op.get("summary") or f"{m_name.upper()} {path_str}"),
                                    "handler": str(op.get("operationId") or "openapi"),
                                    "file": cand,
                                    "line": 1,
                                    "auth": "Protected" if op.get("security") else "Public",
                                    "response_model": None,
                                    "framework": "OpenAPI",
                                })
                    break
            except Exception:
                pass

    endpoints.sort(key=lambda e: (e["tag"], e["path"], e["method"]))
    tag_counts = Counter(e["tag"] for e in endpoints)
    method_counts = Counter(e["method"] for e in endpoints)
    protected_cnt = sum(1 for e in endpoints if e["auth"] == "Protected")

    payload: dict[str, Any] = {
        "generated_at": time.time(),
        "project": project_dir.name,
        "summary": {
            "total_endpoints": len(endpoints),
            "total_tags": len(tag_counts),
            "protected_endpoints": protected_cnt,
            "public_endpoints": len(endpoints) - protected_cnt,
            "by_method": dict(sorted(method_counts.items())),
        },
        "tags": [{"name": k, "count": v} for k, v in sorted(tag_counts.items())],
        "endpoints": endpoints,
        "openapi": openapi_loaded or _build_openapi_spec(project_dir.name, endpoints),
    }

    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "api-catalog.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    (data_dir / "api_catalog.js").write_text(f"window.API_CATALOG = {json.dumps(payload)};\n", encoding="utf-8")
    return payload
