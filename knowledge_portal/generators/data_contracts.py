"""
ADR-082 Wave 3 (AI-6): Data Contracts Generator (100% Python stdlib).

Extracts:
  1. Pydantic <-> TypeScript Schema Registry & Drift Detector
     - Python Pydantic BaseModel / SQLModel classes (fields, types, optional, defaults)
     - TypeScript interfaces & type aliases (.ts, .tsx, .vue <script>)
     - Cross-stack name matching (exact + snake_case <-> camelCase) & schema_drift
     - Untyped API routes returning generic dict / Any or missing response_model
  2. Error Taxonomy
     - HTTPException calls (status_code, detail, file, line, function)
     - Custom exception classes (class *Error / *Exception)
     - Frontend HTTP error status handlers
  3. DB Table -> Readers / Writers / Migrations Matrix
     - Maps tables from db-schema.json + ORM __tablename__ to SQL/ORM readers, writers, migrations

Writes:
  - <data_dir>/data-contracts.json
  - <data_dir>/data_contracts.js (window.DATA_CONTRACTS_DATA)
"""

from __future__ import annotations

import ast
import json
import os
import re
from collections import Counter, defaultdict
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

TS_EXTENSIONS = {".ts", ".tsx", ".vue"}

_HTTP_STATUS_NAME_MAP: dict[str, int] = {
    "HTTP_400_BAD_REQUEST": 400,
    "HTTP_401_UNAUTHORIZED": 401,
    "HTTP_402_PAYMENT_REQUIRED": 402,
    "HTTP_403_FORBIDDEN": 403,
    "HTTP_404_NOT_FOUND": 404,
    "HTTP_405_METHOD_NOT_ALLOWED": 405,
    "HTTP_408_REQUEST_TIMEOUT": 408,
    "HTTP_409_CONFLICT": 409,
    "HTTP_410_GONE": 410,
    "HTTP_413_REQUEST_ENTITY_TOO_LARGE": 413,
    "HTTP_415_UNSUPPORTED_MEDIA_TYPE": 415,
    "HTTP_422_UNPROCESSABLE_ENTITY": 422,
    "HTTP_422_UNPROCESSABLE_CONTENT": 422,
    "HTTP_429_TOO_MANY_REQUESTS": 429,
    "HTTP_500_INTERNAL_SERVER_ERROR": 500,
    "HTTP_501_NOT_IMPLEMENTED": 501,
    "HTTP_502_BAD_GATEWAY": 502,
    "HTTP_503_SERVICE_UNAVAILABLE": 503,
    "HTTP_504_GATEWAY_TIMEOUT": 504,
}

# SQL table extraction regexes
_SQL_READ_RE = re.compile(
    r"\b(?:FROM|JOIN)\s+([a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)?)",
    re.IGNORECASE,
)
_SQL_WRITE_RE = re.compile(
    r"\b(?:INSERT\s+INTO|UPDATE|DELETE\s+FROM|TRUNCATE\s+(?:TABLE\s+)?)\s+([a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)?)",
    re.IGNORECASE,
)
_SQL_MIGRATION_TABLE_RE = re.compile(
    r"\b(?:CREATE\s+TABLE(?:\s+IF\s+NOT\s+EXISTS)?|ALTER\s+TABLE(?:\s+IF\s+EXISTS)?)\s+([a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)?)",
    re.IGNORECASE,
)

# TypeScript interface / object type declaration header
_TS_INTERFACE_RE = re.compile(
    r"(?:export\s+)?interface\s+(?P<name>[A-Za-z_]\w*)(?:\s*<[^>]*>)?(?:\s+extends\s+[^{]+)?\s*\{",
    re.MULTILINE,
)
_TS_TYPE_OBJ_RE = re.compile(
    r"(?:export\s+)?type\s+(?P<name>[A-Za-z_]\w*)(?:\s*<[^>]*>)?\s*=\s*\{",
    re.MULTILINE,
)
_TS_TYPE_ALIAS_RE = re.compile(
    r"export\s+type\s+(?P<name>[A-Za-z_]\w*)(?:\s*<[^>]*>)?\s*=\s*(?P<body>[^;{\n]+);",
    re.MULTILINE,
)
_TS_FIELD_RE = re.compile(
    r"^\s*(?:readonly\s+)?(?P<name>[A-Za-z_]\w*)(?P<opt>\?)?\s*:\s*(?P<type>[^;,\n]+)",
)
_FE_STATUS_RE = re.compile(
    r"(?:status(?:Code)?\s*===?\s*|case\s+)(?P<code>400|401|403|404|409|422|429|500|502|503|504)\b"
)
_SCRIPT_TAG_RE = re.compile(r"<script\b[^>]*>(.*?)</script>", re.DOTALL | re.IGNORECASE)


def _iter_source_files(project_dir: Path, extensions: set[str]) -> list[Path]:
    out: list[Path] = []
    for root, dirs, files in os.walk(project_dir):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not d.startswith("."))
        for fname in sorted(files):
            if fname.startswith(".env"):
                continue
            p = Path(root) / fname
            if p.suffix.lower() in extensions:
                out.append(p)
    return out


def _is_test_path(rel_path: str) -> bool:
    low = rel_path.lower()
    parts = low.split("/")
    name = parts[-1]
    return (
        "tests" in parts
        or "__tests__" in parts
        or name.startswith("test_")
        or name.endswith("_test.py")
        or ".spec." in name
        or ".test." in name
    )


def _is_migration_path(rel_path: str) -> bool:
    low = rel_path.lower()
    return "migrations/" in low or "alembic/" in low or low.endswith(".sql")


def _to_snake(name: str) -> str:
    s1 = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s1).lower()


def _normalize_model_key(name: str) -> str:
    low = re.sub(r"[^a-z0-9]", "", name.lower())
    for suffix in ("schema", "dto", "model"):
        if len(low) > len(suffix) + 3 and low.endswith(suffix):
            low = low[: -len(suffix)]
            break
    return low


def _canonical_py_type(py_type: str) -> str:
    t = py_type.strip()
    t = re.sub(r"\bOptional\[(.*)\]", r"\1", t)
    t = re.sub(r"\s*\|\s*None\b", "", t)
    t = re.sub(r"\bNone\s*\|\s*", "", t)
    t = re.sub(r"\bAnnotated\[([^,\]]+),.*\]", r"\1", t).strip()
    low = t.lower()
    if low in ("str", "string", "uuid", "emailstr", "anyurl", "httpurl", "datetime", "date", "time", "path"):
        return "string"
    if low in ("int", "float", "decimal", "number"):
        return "number"
    if low in ("bool", "boolean"):
        return "boolean"
    if low.startswith(("list[", "sequence[", "tuple[", "set[", "frozenset[")) or low in ("list", "tuple", "set"):
        return "array"
    if low.startswith(("dict[", "mapping[")) or low in ("dict", "mapping", "json"):
        return "object"
    if low in ("any", "object"):
        return "any"
    if low.startswith("literal["):
        return "string"
    return "custom"


def _canonical_ts_type(ts_type: str) -> str:
    t = ts_type.strip()
    t = re.sub(r"\s*\|\s*(?:null|undefined)\b", "", t)
    t = re.sub(r"\b(?:null|undefined)\s*\|\s*", "", t).strip()
    low = t.lower()
    if low in ("string", "date") or (t.startswith(("'", '"')) and t.endswith(("'", '"'))):
        return "string"
    if low in ("number", "bigint"):
        return "number"
    if low == "boolean":
        return "boolean"
    if low.endswith("[]") or low.startswith(("array<", "readonlyarray<", "[")):
        return "array"
    if low.startswith(("record<", "{")) or low in ("object",):
        return "object"
    if low in ("any", "unknown"):
        return "any"
    if "|" in t and ("'" in t or '"' in t):
        return "string"
    return "custom"


def _types_compatible(py_type: str, ts_type: str) -> bool:
    cp = _canonical_py_type(py_type)
    ct = _canonical_ts_type(ts_type)
    if cp == ct or cp == "any" or ct == "any" or cp == "custom" or ct == "custom":
        return True
    return False


def _extract_brace_block(text: str, open_brace_idx: int) -> str:
    depth = 0
    end_idx = open_brace_idx
    n = len(text)
    while end_idx < n:
        ch = text[end_idx]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[open_brace_idx + 1 : end_idx]
        end_idx += 1
    return ""


def _parse_ts_fields(body: str) -> list[dict[str, Any]]:
    fields: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw_line in body.splitlines():
        line = raw_line.split("//", 1)[0].strip()
        if not line or line.startswith(("/*", "*", "}", "{", "[")):
            continue
        m = _TS_FIELD_RE.match(line)
        if not m:
            continue
        fname = m.group("name")
        if fname in seen or fname in ("return", "const", "let", "var", "if", "else"):
            continue
        seen.add(fname)
        ftype = m.group("type").strip().rstrip(";,").strip()
        opt = bool(m.group("opt")) or ("| null" in ftype) or ("| undefined" in ftype)
        fields.append({
            "name": fname,
            "type": ftype[:80],
            "optional": opt,
        })
    return fields


def _scan_typescript_types(project_dir: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    ts_types: list[dict[str, Any]] = []
    fe_error_handlers: list[dict[str, Any]] = []

    for fpath in _iter_source_files(project_dir, TS_EXTENSIONS):
        rel = fpath.relative_to(project_dir).as_posix()
        if _is_test_path(rel):
            continue
        try:
            raw = fpath.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        if fpath.suffix.lower() == ".vue":
            scripts = _SCRIPT_TAG_RE.findall(raw)
            content = "\n".join(scripts)
        else:
            content = raw

        if not content.strip():
            continue

        # Detect frontend HTTP status code handling
        codes = sorted({int(m.group("code")) for m in _FE_STATUS_RE.finditer(content)})
        if codes:
            fe_error_handlers.append({"file": rel, "status_codes": codes})

        seen_in_file: set[str] = set()
        for kind, pattern in (("interface", _TS_INTERFACE_RE), ("type", _TS_TYPE_OBJ_RE)):
            for m in pattern.finditer(content):
                name = m.group("name")
                if name in seen_in_file:
                    continue
                seen_in_file.add(name)
                line_no = content.count("\n", 0, m.start()) + 1
                block = _extract_brace_block(content, m.end() - 1)
                fields = _parse_ts_fields(block)
                ts_types.append({
                    "name": name,
                    "kind": kind,
                    "file": rel,
                    "line": line_no,
                    "fields": fields,
                    "field_count": len(fields),
                })

        for m in _TS_TYPE_ALIAS_RE.finditer(content):
            name = m.group("name")
            if name in seen_in_file:
                continue
            seen_in_file.add(name)
            line_no = content.count("\n", 0, m.start()) + 1
            body = m.group("body").strip()[:100]
            ts_types.append({
                "name": name,
                "kind": "type_alias",
                "file": rel,
                "line": line_no,
                "definition": body,
                "fields": [],
                "field_count": 0,
            })

    return ts_types, fe_error_handlers


def _safe_unparse(node: ast.AST | None) -> str:
    if node is None:
        return "Any"
    try:
        return ast.unparse(node)
    except Exception:
        return "Any"


def _extract_base_names(cls: ast.ClassDef) -> list[str]:
    names: list[str] = []
    for base in cls.bases:
        if isinstance(base, ast.Name):
            names.append(base.id)
        elif isinstance(base, ast.Attribute):
            names.append(base.attr)
        elif isinstance(base, ast.Subscript):
            names.append(_safe_unparse(base.value).split(".")[-1])
    return names


def _resolve_status_code(node: ast.AST | None) -> int | None:
    if node is None:
        return None
    if isinstance(node, ast.Constant) and isinstance(node.value, int):
        return int(node.value)
    if isinstance(node, ast.Attribute):
        return _HTTP_STATUS_NAME_MAP.get(node.attr)
    if isinstance(node, ast.Name):
        return _HTTP_STATUS_NAME_MAP.get(node.id)
    return None


def _scan_python_contracts(
    project_dir: Path,
    known_tables: set[str],
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    dict[str, str],
    dict[str, set[str]],
    dict[str, set[str]],
]:
    py_files = _iter_source_files(project_dir, {".py"})
    parsed_files: list[tuple[str, str, ast.Module]] = []
    for fpath in py_files:
        rel = fpath.relative_to(project_dir).as_posix()
        if _is_test_path(rel) or _is_migration_path(rel):
            continue
        try:
            text = fpath.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(text, filename=rel)
        except (OSError, SyntaxError):
            continue
        parsed_files.append((rel, text, tree))

    # Pass 1: discover Pydantic subclasses & ORM __tablename__
    pydantic_roots = {"BaseModel", "SQLModel", "BaseSettings", "RootModel"}
    discovered_pydantic: set[str] = set(pydantic_roots)
    orm_class_to_table: dict[str, str] = {}

    for _ in range(3):
        changed = False
        for _rel, _text, tree in parsed_files:
            for node in ast.walk(tree):
                if not isinstance(node, ast.ClassDef):
                    continue
                bases = _extract_base_names(node)
                if any(b in discovered_pydantic for b in bases) and node.name not in discovered_pydantic:
                    discovered_pydantic.add(node.name)
                    changed = True
                for stmt in node.body:
                    if isinstance(stmt, ast.Assign):
                        for tgt in stmt.targets:
                            if isinstance(tgt, ast.Name) and tgt.id == "__tablename__":
                                if isinstance(stmt.value, ast.Constant) and isinstance(stmt.value.value, str):
                                    orm_class_to_table[node.name] = stmt.value.value.strip().lower()
        if not changed:
            break

    all_tables = set(known_tables) | set(orm_class_to_table.values())

    pydantic_models: list[dict[str, Any]] = []
    http_exceptions: list[dict[str, Any]] = []
    custom_exceptions: list[dict[str, Any]] = []
    untyped_routes: list[dict[str, Any]] = []
    readers_by_table: dict[str, set[str]] = defaultdict(set)
    writers_by_table: dict[str, set[str]] = defaultdict(set)

    # Pass 2: extract models, exceptions, untyped routes, and DB R/W
    for rel, text, tree in parsed_files:
        # 2a. Classes (Pydantic + Custom Exceptions)
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            bases = _extract_base_names(node)

            if any(b in discovered_pydantic for b in bases):
                fields: list[dict[str, Any]] = []
                for stmt in node.body:
                    if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                        fname = stmt.target.id
                        if fname.startswith("_") or fname == "model_config":
                            continue
                        ftype = _safe_unparse(stmt.annotation)
                        has_default = stmt.value is not None
                        is_opt = (
                            "Optional[" in ftype
                            or "| None" in ftype
                            or "None |" in ftype
                            or has_default
                        )
                        default_preview = ""
                        if isinstance(stmt.value, ast.Constant):
                            default_preview = repr(stmt.value.value)[:40]
                        fields.append({
                            "name": fname,
                            "type": ftype[:80],
                            "optional": is_opt,
                            "has_default": has_default,
                            "default": default_preview,
                        })
                pydantic_models.append({
                    "name": node.name,
                    "file": rel,
                    "line": node.lineno,
                    "bases": bases,
                    "fields": fields,
                    "field_count": len(fields),
                })

            if any(
                b in ("Exception", "BaseException", "RuntimeError", "ValueError", "KeyError")
                or b.endswith(("Error", "Exception"))
                for b in bases
            ):
                doc = (ast.get_docstring(node) or "").splitlines()[0].strip()[:120] if ast.get_docstring(node) else ""
                custom_exceptions.append({
                    "name": node.name,
                    "bases": bases,
                    "file": rel,
                    "line": node.lineno,
                    "docstring": doc,
                })

        # 2b. Functions: HTTPException, untyped API routes, DB R/W per function
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            fn_name = node.name

            # Check FastAPI / Flask route decorator for response_model & return annotation
            for dec in node.decorator_list:
                if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute):
                    method = dec.func.attr.lower()
                    if method in ("get", "post", "put", "patch", "delete"):
                        route_path = ""
                        if dec.args and isinstance(dec.args[0], ast.Constant) and isinstance(dec.args[0].value, str):
                            route_path = dec.args[0].value
                        resp_model = None
                        for kw in dec.keywords:
                            if kw.arg == "response_model":
                                resp_model = _safe_unparse(kw.value)
                        ret_ann = _safe_unparse(node.returns) if node.returns is not None else ""
                        is_generic = False
                        reason = ""
                        if resp_model is None:
                            if not ret_ann or ret_ann in ("dict", "Dict", "Any", "dict[str, Any]", "Dict[str, Any]", "list[dict]", "List[dict]"):
                                is_generic = True
                                reason = "missing_response_model" if not ret_ann else f"generic_return:{ret_ann}"
                        elif resp_model in ("dict", "Dict", "Any", "dict[str, Any]", "Dict[str, Any]"):
                            is_generic = True
                            reason = f"generic_response_model:{resp_model}"
                        if is_generic and route_path:
                            untyped_routes.append({
                                "method": method.upper(),
                                "path": route_path,
                                "handler": fn_name,
                                "file": rel,
                                "line": node.lineno,
                                "reason": reason,
                            })

            # Walk function body for HTTPException & SQL / ORM table touches
            fn_strings: list[str] = []
            for sub in ast.walk(node):
                if isinstance(sub, ast.Call):
                    callee = ""
                    if isinstance(sub.func, ast.Name):
                        callee = sub.func.id
                    elif isinstance(sub.func, ast.Attribute):
                        callee = sub.func.attr
                    if callee == "HTTPException":
                        sc: int | None = None
                        detail_str = ""
                        if sub.args:
                            sc = _resolve_status_code(sub.args[0])
                        if len(sub.args) >= 2:
                            detail_str = _safe_unparse(sub.args[1])[:100]
                        for kw in sub.keywords:
                            if kw.arg == "status_code":
                                sc = _resolve_status_code(kw.value)
                            elif kw.arg == "detail":
                                detail_str = _safe_unparse(kw.value)[:100]
                        http_exceptions.append({
                            "status_code": sc or 500,
                            "detail": detail_str.strip("'\""),
                            "file": rel,
                            "line": sub.lineno,
                            "function": fn_name,
                        })

                    # ORM read/write detection
                    if callee in ("select", "query") and sub.args:
                        arg_name = _safe_unparse(sub.args[0]).split(".")[-1]
                        if arg_name in orm_class_to_table:
                            readers_by_table[orm_class_to_table[arg_name]].add(f"{rel}:{fn_name}")
                    elif callee in ("insert", "update", "delete") and sub.args:
                        arg_name = _safe_unparse(sub.args[0]).split(".")[-1]
                        if arg_name in orm_class_to_table:
                            writers_by_table[orm_class_to_table[arg_name]].add(f"{rel}:{fn_name}")
                    elif callee in ("add", "add_all", "merge") and sub.args:
                        arg_src = _safe_unparse(sub.args[0])
                        for cls_name, tbl in orm_class_to_table.items():
                            if cls_name in arg_src:
                                writers_by_table[tbl].add(f"{rel}:{fn_name}")

                elif isinstance(sub, ast.Constant) and isinstance(sub.value, str) and len(sub.value) > 10:
                    fn_strings.append(sub.value)

            if fn_strings and all_tables:
                joined = "\n".join(fn_strings)
                for m in _SQL_READ_RE.finditer(joined):
                    tbl = m.group(1).split(".")[-1].lower()
                    if tbl in all_tables:
                        readers_by_table[tbl].add(f"{rel}:{fn_name}")
                for m in _SQL_WRITE_RE.finditer(joined):
                    tbl = m.group(1).split(".")[-1].lower()
                    if tbl in all_tables:
                        writers_by_table[tbl].add(f"{rel}:{fn_name}")

        # 2c. Module-level SQL strings (e.g. module constants)
        if all_tables:
            for m in _SQL_READ_RE.finditer(text):
                tbl = m.group(1).split(".")[-1].lower()
                if tbl in all_tables and not any(r.startswith(f"{rel}:") for r in readers_by_table[tbl]):
                    readers_by_table[tbl].add(rel)
            for m in _SQL_WRITE_RE.finditer(text):
                tbl = m.group(1).split(".")[-1].lower()
                if tbl in all_tables and not any(w.startswith(f"{rel}:") for w in writers_by_table[tbl]):
                    writers_by_table[tbl].add(rel)

    return (
        pydantic_models,
        http_exceptions,
        custom_exceptions,
        untyped_routes,
        orm_class_to_table,
        readers_by_table,
        writers_by_table,
    )


def _scan_migrations(project_dir: Path, all_tables: set[str]) -> dict[str, set[str]]:
    migrations_by_table: dict[str, set[str]] = defaultdict(set)
    for fpath in _iter_source_files(project_dir, {".sql", ".py"}):
        rel = fpath.relative_to(project_dir).as_posix()
        if not _is_migration_path(rel):
            continue
        try:
            text = fpath.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for m in _SQL_MIGRATION_TABLE_RE.finditer(text):
            tbl = m.group(1).split(".")[-1].lower()
            if tbl in all_tables:
                migrations_by_table[tbl].add(rel)
        # Alembic op.create_table("table_name", ...)
        for m in re.finditer(r"""op\.(?:create_table|alter_column|add_column|drop_table)\s*\(\s*['"](?P<t>[a-zA-Z_]\w*)['"]""", text):
            tbl = m.group("t").lower()
            if tbl in all_tables:
                migrations_by_table[tbl].add(rel)
    return migrations_by_table


def _compute_schema_drift(
    pydantic_models: list[dict[str, Any]],
    ts_types: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    ts_by_key: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for t in ts_types:
        if t.get("fields"):
            ts_by_key[_normalize_model_key(t["name"])].append(t)

    matched_pairs: list[dict[str, Any]] = []
    drift_items: list[dict[str, Any]] = []

    for pm in pydantic_models:
        if not pm.get("fields"):
            continue
        key = _normalize_model_key(pm["name"])
        candidates = ts_by_key.get(key) or []
        if not candidates:
            continue
        # Prefer exact name match
        best = next((c for c in candidates if c["name"] == pm["name"]), candidates[0])

        py_fields = {_to_snake(f["name"]): f for f in pm["fields"]}
        ts_fields = {_to_snake(f["name"]): f for f in best["fields"]}

        missing_in_ts = sorted(set(py_fields) - set(ts_fields))
        missing_in_py = sorted(set(ts_fields) - set(py_fields))
        type_mismatches: list[dict[str, str]] = []
        for fname in sorted(set(py_fields) & set(ts_fields)):
            pf = py_fields[fname]
            tf = ts_fields[fname]
            if not _types_compatible(pf["type"], tf["type"]):
                type_mismatches.append({
                    "field": fname,
                    "py_type": pf["type"],
                    "ts_type": tf["type"],
                })

        has_drift = bool(missing_in_ts or missing_in_py or type_mismatches)
        pair_entry = {
            "pydantic_model": pm["name"],
            "pydantic_file": pm["file"],
            "ts_type": best["name"],
            "ts_file": best["file"],
            "status": "DRIFT" if has_drift else "SYNCED",
            "missing_in_ts": missing_in_ts,
            "missing_in_py": missing_in_py,
            "type_mismatches": type_mismatches,
        }
        matched_pairs.append(pair_entry)
        if has_drift:
            drift_items.append(pair_entry)

    return matched_pairs, drift_items


def generate_data_contracts(project_dir: Path, data_dir: Path) -> dict[str, Any]:
    """Scan repository for Pydantic<->TS contracts, Error Taxonomy, and DB R/W Matrix."""
    project_dir = Path(project_dir).resolve()
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)

    # Load known tables from db-schema.json if present
    known_tables: set[str] = set()
    db_schema_path = data_dir / "db-schema.json"
    if db_schema_path.is_file():
        try:
            raw_db = json.loads(db_schema_path.read_text(encoding="utf-8"))
            for t in raw_db.get("tables") or []:
                if isinstance(t, dict) and t.get("name"):
                    known_tables.add(str(t["name"]).strip().lower())
        except (OSError, json.JSONDecodeError):
            pass

    # Load total API route count from api-catalog.json if present
    total_api_routes = 0
    api_cat_path = data_dir / "api-catalog.json"
    if api_cat_path.is_file():
        try:
            raw_api = json.loads(api_cat_path.read_text(encoding="utf-8"))
            total_api_routes = len(raw_api.get("endpoints") or [])
        except (OSError, json.JSONDecodeError):
            pass

    (
        pydantic_models,
        http_exceptions,
        custom_exceptions,
        untyped_routes,
        orm_class_to_table,
        readers_by_table,
        writers_by_table,
    ) = _scan_python_contracts(project_dir, known_tables)

    ts_types, fe_error_handlers = _scan_typescript_types(project_dir)
    matched_pairs, schema_drift = _compute_schema_drift(pydantic_models, ts_types)

    all_tables = sorted(known_tables | set(orm_class_to_table.values()))
    migrations_by_table = _scan_migrations(project_dir, set(all_tables))

    db_rw_matrix: list[dict[str, Any]] = []
    for tbl in all_tables:
        readers = sorted(readers_by_table.get(tbl) or [])
        writers = sorted(writers_by_table.get(tbl) or [])
        migs = sorted(migrations_by_table.get(tbl) or [])
        db_rw_matrix.append({
            "table": tbl,
            "readers": readers[:25],
            "writers": writers[:25],
            "migrations": migs[:15],
            "readers_count": len(readers),
            "writers_count": len(writers),
            "migrations_count": len(migs),
            "is_orphan": len(readers) == 0 and len(writers) == 0,
        })

    status_counts = Counter(str(e["status_code"]) for e in http_exceptions)
    denom_routes = max(total_api_routes, len(untyped_routes), 1)
    untyped_pct = round((len(untyped_routes) / denom_routes) * 100.0, 1) if untyped_routes else 0.0

    summary = {
        "pydantic_models_count": len(pydantic_models),
        "ts_types_count": len(ts_types),
        "matched_schemas_count": len(matched_pairs),
        "schema_drift_count": len(schema_drift),
        "untyped_routes_count": len(untyped_routes),
        "untyped_routes_pct": untyped_pct,
        "http_exceptions_count": len(http_exceptions),
        "custom_exceptions_count": len(custom_exceptions),
        "fe_error_handlers_count": len(fe_error_handlers),
        "db_rw_tables_count": len(db_rw_matrix),
        "orphan_tables_count": sum(1 for r in db_rw_matrix if r["is_orphan"]),
        "http_status_breakdown": dict(status_counts.most_common(12)),
    }

    payload: dict[str, Any] = {
        "schema_version": "1.0",
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "summary": summary,
        "pydantic_models": pydantic_models,
        "ts_types": ts_types,
        "matched_schemas": matched_pairs,
        "schema_drift": schema_drift,
        "untyped_routes": untyped_routes,
        "error_taxonomy": {
            "by_status_code": dict(status_counts.most_common(20)),
            "http_exceptions": http_exceptions,
            "custom_exceptions": custom_exceptions,
            "frontend_handlers": fe_error_handlers,
        },
        "db_rw_matrix": db_rw_matrix,
    }

    json_path = data_dir / "data-contracts.json"
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    js_path = data_dir / "data_contracts.js"
    js_path.write_text(
        f"window.DATA_CONTRACTS_DATA = {json.dumps(payload, ensure_ascii=False)};\n",
        encoding="utf-8",
    )
    return payload
