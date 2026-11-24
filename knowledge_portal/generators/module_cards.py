"""
Knowledge Portal — Compact Module Cards Generator (ADR-082 AI-1).
100% Python stdlib zero-dependency generator producing <= 180 token/file cards for
Python (.py via AST), TypeScript/JS (.ts/.tsx/.js/.jsx), and Vue (.vue) source files.

Outputs `data/module-cards.json` and `data/module_cards.js`.
"""

from __future__ import annotations

import ast
import json
import math
import os
import re
import time
from collections import Counter
from pathlib import Path
from typing import Any

_IGNORE_DIRS = frozenset({
    ".git", "node_modules", "dist", "dev-dist", "build", ".venv", "venv",
    "__pycache__", ".idea", ".vscode", "target", "vendor", "frozen",
    "graphify-out", "coverage", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    "archive",
})

_MAX_CARD_TOKENS = 180

_ROUTE_DEC_RE = re.compile(
    r"""@\w+\.(get|post|put|patch|delete|websocket)\s*\(\s*["']([^"']+)["']""",
    re.IGNORECASE,
)
_SQL_TABLE_RE = re.compile(
    r"""\b(?:FROM|JOIN|INTO|UPDATE)\s+["'`]?([a-zA-Z_][a-zA-Z0-9_]{2,40})["'`]?""",
    re.IGNORECASE,
)
_SQL_NOISE = frozenset({
    "select", "where", "values", "set", "table", "index", "view", "dual",
    "information_schema", "pg_catalog", "this", "that", "self", "none",
    "true", "false", "null", "import", "from", "return", "async", "await",
})
_JS_EXPORT_RE = re.compile(
    r"""export\s+(?:default\s+)?(?:async\s+)?(?:function|class|const|let|interface|type)\s+([A-Za-z_][A-Za-z0-9_]*)"""
)
_JS_IMPORT_RE = re.compile(r"""import\s+[\s\S]*?\s+from\s+["']([^"']+)["']""")
_SYNC_IO_IN_ASYNC = frozenset({"sleep", "urlopen", "get", "post", "put", "delete", "run"})


def estimate_tokens(obj: Any) -> int:
    text = obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    return math.ceil(len(text) / 3.8) if text else 0


def _is_test_or_generated(rel: str) -> bool:
    low = rel.lower()
    name = low.rsplit("/", 1)[-1]
    if name.startswith("test_") or name.endswith(("_test.py", ".spec.ts", ".test.ts", ".spec.js", ".test.js", ".min.js", ".d.ts")):
        return True
    if "/tests/" in f"/{low}" or low.startswith("tests/"):
        return True
    if ("/data/" in f"/{low}" or low.startswith("template/data/")) and name.endswith(".js"):
        return True
    return False


def _infer_role(rel: str, lang: str, text: str, routes: list[str]) -> str:
    low = rel.lower()
    if lang == "vue":
        return "vue_view" if ("/views/" in low or "/pages/" in low) else "vue_component"
    if lang in ("typescript", "javascript"):
        if "defineStore(" in text or "/stores/" in low:
            return "pinia_store"
        if "/composables/" in low or Path(rel).stem.startswith("use"):
            return "composable"
        if "/api/" in low or "fetch(" in text or "axios" in text:
            return "api_client"
        return "ts_module" if lang == "typescript" else "js_module"
    if routes or "APIRouter(" in text or "@router." in text:
        return "fastapi_router"
    if "Blueprint(" in text or "@app.route" in text:
        return "flask_router"
    if "@celery_app.task" in text or "@shared_task" in text or "/workers/" in low:
        return "worker"
    if "/generators/" in low:
        return "generator"
    if "/repo" in low or "/db/" in low or "BaseModel" in text and "/models" in low:
        return "repository" if ("/repo" in low or "/db/" in low) else "model"
    if "/services/" in low:
        return "service"
    if "argparse" in text or low.endswith("cli.py"):
        return "cli"
    return "python_module"


def _extract_tables(text: str) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    if not any(k in text.upper() for k in ("SELECT ", "INSERT ", "UPDATE ", "DELETE ", "CREATE TABLE", "__TABLENAME__")):
        return []
    for m in re.finditer(r"""__tablename__\s*=\s*["']([a-zA-Z_][a-zA-Z0-9_]*)["']""", text):
        t = m.group(1).lower()
        if t not in seen:
            seen.add(t)
            found.append(t)
    for m in _SQL_TABLE_RE.finditer(text):
        t = m.group(1).lower()
        if t not in _SQL_NOISE and t not in seen and "_" in t or (t not in _SQL_NOISE and t not in seen and len(t) >= 4):
            # Only capture when near SQL keyword context
            start = max(0, m.start() - 40)
            ctx = text[start:m.end()].upper()
            if any(k in ctx for k in ("SELECT", "INSERT", "UPDATE", "DELETE", "JOIN", "FROM ")):
                seen.add(t)
                found.append(t)
                if len(found) >= 5:
                    break
    return found[:5]


def _extract_python_card(fpath: Path, rel: str) -> dict[str, Any]:
    text = fpath.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    loc = len(lines)
    exports: list[str] = []
    imports_internal: list[str] = []
    routes: list[str] = []
    risk_flags: list[str] = []
    purpose = ""
    swallowed = 0
    sync_in_async = 0

    for m in _ROUTE_DEC_RE.finditer(text):
        routes.append(f"{m.group(1).upper()} {m.group(2)}")
        if len(routes) >= 5:
            break

    try:
        tree = ast.parse(text, filename=rel)
        doc = ast.get_docstring(tree)
        if doc:
            purpose = doc.strip().splitlines()[0].strip()[:120]

        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if not node.name.startswith("_"):
                    exports.append(node.name)
            elif isinstance(node, ast.ImportFrom) and node.module:
                if node.level > 0 or node.module.split(".")[0] in ("app", "knowledge_portal", "scripts", "src", "core", "services"):
                    if node.module not in imports_internal:
                        imports_internal.append(node.module)

        for walked in ast.walk(tree):
            if isinstance(walked, ast.ExceptHandler):
                if len(walked.body) == 1 and isinstance(walked.body[0], ast.Pass):
                    swallowed += 1
            elif isinstance(walked, ast.AsyncFunctionDef):
                for sub in ast.walk(walked):
                    if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute):
                        if sub.func.attr in _SYNC_IO_IN_ASYNC and isinstance(sub.func.value, ast.Name):
                            if sub.func.value.id in ("time", "requests", "subprocess"):
                                sync_in_async += 1
    except SyntaxError:
        risk_flags.append("SYNTAX_ERROR")

    if loc > 500:
        risk_flags.append(f"LARGE_FILE:{loc}")
    if swallowed > 0:
        risk_flags.append(f"SWALLOWED_EXCEPT:{swallowed}")
    if sync_in_async > 0:
        risk_flags.append(f"SYNC_IO_IN_ASYNC:{sync_in_async}")

    role = _infer_role(rel, "python", text, routes)
    if not purpose:
        purpose = f"{role.replace('_', ' ')} ({', '.join(exports[:3]) or Path(rel).stem})"[:120]

    return {
        "lang": "python",
        "loc": loc,
        "role": role,
        "purpose": purpose,
        "exports": exports[:6],
        "imports_internal": imports_internal[:6],
        "routes": routes[:5],
        "tables_touched": _extract_tables(text),
        "risk_flags": risk_flags[:4],
    }


def _extract_js_vue_card(fpath: Path, rel: str, lang: str) -> dict[str, Any]:
    text = fpath.read_text(encoding="utf-8", errors="replace")
    loc = len(text.splitlines())
    exports = list(dict.fromkeys(_JS_EXPORT_RE.findall(text)))[:6]
    imports_internal = [
        imp for imp in dict.fromkeys(_JS_IMPORT_RE.findall(text))
        if imp.startswith((".", "@/", "~/"))
    ][:6]
    routes: list[str] = []
    for m in re.finditer(r"""["'](/api/[a-zA-Z0-9_/\-${}]+)["']""", text):
        r = m.group(1)
        if r not in routes:
            routes.append(r)
            if len(routes) >= 5:
                break

    purpose = ""
    for ln in text.splitlines()[:10]:
        s = ln.strip()
        if s.startswith("//") and len(s) > 5:
            purpose = s.lstrip("/ ").strip()[:120]
            break
    role = _infer_role(rel, lang, text, routes)
    if not purpose:
        purpose = f"{role.replace('_', ' ')} ({', '.join(exports[:3]) or Path(rel).stem})"[:120]

    risk_flags: list[str] = []
    if loc > 500:
        risk_flags.append(f"LARGE_FILE:{loc}")
    if "v-html=" in text:
        risk_flags.append("V_HTML_XSS")

    return {
        "lang": lang,
        "loc": loc,
        "role": role,
        "purpose": purpose,
        "exports": exports,
        "imports_internal": imports_internal,
        "routes": routes,
        "tables_touched": [],
        "risk_flags": risk_flags[:4],
    }


def _enforce_token_cap(card: dict[str, Any], limit: int = _MAX_CARD_TOKENS) -> dict[str, Any]:
    """Deterministically trim card fields so every card stays <= limit tokens."""
    if estimate_tokens(card) <= limit:
        return card
    trimmed = dict(card)
    trimmed["purpose"] = str(trimmed.get("purpose", ""))[:80]
    for key, max_len in (("imports_internal", 4), ("exports", 4), ("routes", 3), ("tables_touched", 3), ("fast_tests", 2)):
        if isinstance(trimmed.get(key), list) and len(trimmed[key]) > max_len:
            trimmed[key] = trimmed[key][:max_len]
    if estimate_tokens(trimmed) <= limit:
        return trimmed
    for key in ("routes", "tables_touched", "imports_internal", "exports", "fast_tests"):
        while isinstance(trimmed.get(key), list) and trimmed[key] and estimate_tokens(trimmed) > limit:
            trimmed[key] = trimmed[key][:-1]
    if estimate_tokens(trimmed) > limit:
        trimmed["purpose"] = str(trimmed.get("purpose", ""))[:40]
    return trimmed


def generate_module_cards(project_dir: Path, data_dir: Path) -> dict[str, Any]:
    """Generate compact <= 180 token/file module cards for Python/TS/JS/Vue sources."""
    project_dir = Path(project_dir).resolve()
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)

    # Optionally enrich fast_tests from test-oracle.json
    oracle_map: dict[str, list[dict[str, Any]]] = {}
    oracle_file = data_dir / "test-oracle.json"
    if oracle_file.is_file():
        try:
            raw_o = json.loads(oracle_file.read_text(encoding="utf-8"))
            if isinstance(raw_o.get("source_to_tests"), dict):
                oracle_map = raw_o["source_to_tests"]
        except Exception:
            pass

    cards: dict[str, dict[str, Any]] = {}
    by_lang: Counter[str] = Counter()
    token_counts: list[int] = []

    for root, dirs, files in os.walk(project_dir):
        dirs[:] = [d for d in dirs if d not in _IGNORE_DIRS and not d.startswith(".")]
        for fname in sorted(files):
            fpath = Path(root) / fname
            ext = fpath.suffix.lower()
            if ext not in (".py", ".ts", ".tsx", ".js", ".jsx", ".vue"):
                continue
            rel = str(fpath.relative_to(project_dir)).replace("\\", "/")
            if "frozen/" in rel.lower() or _is_test_or_generated(rel):
                continue
            try:
                if ext == ".py":
                    card = _extract_python_card(fpath, rel)
                elif ext == ".vue":
                    card = _extract_js_vue_card(fpath, rel, "vue")
                elif ext in (".ts", ".tsx"):
                    card = _extract_js_vue_card(fpath, rel, "typescript")
                else:
                    card = _extract_js_vue_card(fpath, rel, "javascript")
            except Exception:
                continue

            fast_tests = [
                str(t["test"]) for t in oracle_map.get(rel, [])
                if isinstance(t, dict) and t.get("test")
            ][:3]
            card["fast_tests"] = fast_tests
            card = _enforce_token_cap(card, _MAX_CARD_TOKENS)
            cards[rel] = card
            by_lang[str(card["lang"])] += 1
            token_counts.append(estimate_tokens(card))

    avg_tok = round(sum(token_counts) / len(token_counts), 1) if token_counts else 0.0
    max_tok = max(token_counts) if token_counts else 0

    payload: dict[str, Any] = {
        "schema_version": "1.0",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "summary": {
            "total_files": len(cards),
            "by_lang": dict(by_lang),
            "avg_card_tokens": avg_tok,
            "max_card_tokens": max_tok,
            "token_cap_per_card": _MAX_CARD_TOKENS,
        },
        "cards": cards,
    }

    (data_dir / "module-cards.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    (data_dir / "module_cards.js").write_text(
        f"window.MODULE_CARDS = {json.dumps(payload)};\n",
        encoding="utf-8",
    )
    return payload
