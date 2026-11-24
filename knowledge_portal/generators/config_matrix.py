"""
Knowledge Portal — Config, Environment & Feature Flag Matrix (ADR-078).
100% Python stdlib zero-dependency scanner.

SECURITY INVARIANT (ABSOLUTE):
NEVER opens or reads real `.env`, `.env.local`, `.env.prod`, or secret files.
Reads ONLY `.env.example` / `.env.sample` / `.env.template`, `docker-compose*.yml`,
and variable NAMES referenced in source code (Python AST + JS/TS regex).
Strictly enforces P4 Gate (excludes frozen/).
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
    ".git", "node_modules", "dist", "build", ".venv", "venv",
    "__pycache__", ".idea", ".vscode", "target", "vendor", "bin", "obj", "frozen",
})
_ENV_EXAMPLE_NAMES = frozenset({".env.example", ".env.sample", ".env.template", "env.example"})
_JS_ENV_RE = re.compile(r"\b(?:process\.env|import\.meta\.env)\.([A-Z][A-Z0-9_]{2,})\b")
_COMPOSE_ENV_RE = re.compile(r"^\s*-?\s*([A-Z][A-Z0-9_]{2,})\s*[:=]")
_FLAG_PREFIXES = ("FEATURE_", "ENABLE_", "FF_", "FLAG_", "USE_", "BETA_")
_FLAG_SDK_RE = re.compile(r"""(?:is_enabled|variation|bool_variation|get_flag|feature_enabled)\s*\(\s*["']([a-zA-Z0-9_.-]{3,60})["']""")

# ADR-080 P0.1: Runtime built-in env vars (Vite, Node, CI, POSIX/Python) excluded from UNDOCUMENTED drift
_BUILTIN_ENV_ALLOWLIST = frozenset({
    # Vite / Bundler built-ins
    "DEV", "PROD", "MODE", "BASE_URL", "SSR",
    # Node / Runtime / CI built-ins
    "NODE_ENV", "TZ", "PORT", "DEBUG", "CI",
    "GITHUB_ACTIONS", "GITHUB_SHA", "GITHUB_REF", "GITHUB_WORKSPACE", "GITHUB_REPOSITORY",
    # POSIX / OS / Python runtime built-ins
    "PATH", "HOME", "USER", "USERNAME", "PWD", "SHELL", "HOSTNAME", "TERM",
    "LANG", "LC_ALL", "TMPDIR", "TEMP", "TMP",
    "PYTHONPATH", "PYTHONUNBUFFERED", "VIRTUAL_ENV", "PYTEST_CURRENT_TEST",
})


def _is_ignored(rel: str) -> bool:
    parts = [p.lower() for p in rel.replace("\\", "/").split("/")]
    return any(p in _IGNORE_DIRS or p.startswith(".") for p in parts[:-1]) or "frozen" in parts


def _extract_py_env_vars(src: str) -> tuple[list[tuple[str, int, str | None]], list[tuple[str, int]]]:
    """Extract (var_name, lineno, default_hint) and SDK feature flags via Python AST."""
    found: list[tuple[str, int, str | None]] = []
    flags: list[tuple[str, int]] = []
    try:
        tree = ast.parse(src)
    except Exception:
        return found, flags

    for node in ast.walk(tree):
        # os.getenv("VAR", "default") or os.environ.get("VAR", ...)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            attr = node.func.attr
            if attr in ("getenv", "get") and node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                recv_src = ast.unparse(node.func.value) if hasattr(ast, "unparse") else ""
                if (attr == "getenv" and "os" in recv_src) or (attr == "get" and "environ" in recv_src):
                    vname = node.args[0].value.strip()
                    if re.match(r"^[A-Z][A-Z0-9_]{1,}$", vname):
                        default_v: str | None = None
                        if len(node.args) >= 2 and isinstance(node.args[1], ast.Constant):
                            default_v = str(node.args[1].value)[:32]
                        found.append((vname, getattr(node, "lineno", 1), default_v))
        # os.environ["VAR"]
        elif isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str):
            val_src = ast.unparse(node.value) if hasattr(ast, "unparse") else ""
            if "environ" in val_src:
                vname = node.slice.value.strip()
                if re.match(r"^[A-Z][A-Z0-9_]{1,}$", vname):
                    found.append((vname, getattr(node, "lineno", 1), None))
        # Pydantic BaseSettings class fields (with env_prefix & Field validation_alias support)
        elif isinstance(node, ast.ClassDef):
            bases = [ast.unparse(b) if hasattr(ast, "unparse") else "" for b in node.bases]
            if any("BaseSettings" in b for b in bases):
                env_prefix = ""
                for item in node.body:
                    # model_config = SettingsConfigDict(env_prefix="...") or {"env_prefix": "..."}
                    if isinstance(item, ast.Assign):
                        for tgt in item.targets:
                            if isinstance(tgt, ast.Name) and tgt.id == "model_config":
                                if isinstance(item.value, ast.Call):
                                    for kw in item.value.keywords:
                                        if kw.arg == "env_prefix" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                                            env_prefix = kw.value.value.strip().upper()
                                elif isinstance(item.value, ast.Dict):
                                    for dk, dv in zip(item.value.keys, item.value.values):
                                        if isinstance(dk, ast.Constant) and dk.value == "env_prefix" and isinstance(dv, ast.Constant) and isinstance(dv.value, str):
                                            env_prefix = dv.value.strip().upper()
                    # class Config: env_prefix = "..."
                    elif isinstance(item, ast.ClassDef) and item.name == "Config":
                        for c_item in item.body:
                            if isinstance(c_item, ast.Assign) and isinstance(c_item.value, ast.Constant) and isinstance(c_item.value.value, str):
                                for tgt in c_item.targets:
                                    if isinstance(tgt, ast.Name) and tgt.id == "env_prefix":
                                        env_prefix = c_item.value.value.strip().upper()

                for item in node.body:
                    if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                        nm = item.target.id
                        if not nm.startswith("_") and nm != "model_config":
                            alias_name: str | None = None
                            if isinstance(item.value, ast.Call):
                                for kw in item.value.keywords:
                                    if kw.arg in ("validation_alias", "alias") and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                                        alias_name = kw.value.value.strip().upper()
                                        break
                            full_name = alias_name if alias_name else f"{env_prefix}{nm.upper()}"
                            found.append((full_name, getattr(item, "lineno", 1), "settings"))

    for lineno, line in enumerate(src.splitlines(), 1):
        for m in _FLAG_SDK_RE.finditer(line):
            flags.append((m.group(1), lineno))
    return found, flags


def generate_config_matrix(project_dir: Path, data_dir: Path, max_files: int = 2500) -> dict[str, Any]:
    """Build Config, Environment & Feature Flag Matrix (never reads real .env files)."""
    project_dir = Path(project_dir).resolve()
    data_dir = Path(data_dir)

    code_refs: dict[str, list[dict[str, Any]]] = defaultdict(list)
    example_vars: dict[str, list[str]] = defaultdict(list)
    compose_vars: dict[str, list[str]] = defaultdict(list)
    sdk_flags: list[dict[str, Any]] = []
    scanned = 0

    for root, dirs, files in os.walk(project_dir):
        dirs[:] = [d for d in dirs if d not in _IGNORE_DIRS and not d.startswith(".")]
        for fname in files:
            if scanned >= max_files:
                break
            fpath = Path(root) / fname
            rel = str(fpath.relative_to(project_dir)).replace("\\", "/")
            if _is_ignored(rel):
                continue

            low_name = fname.lower()
            # NEVER read real .env files! Only explicit example/sample/template files
            if low_name in _ENV_EXAMPLE_NAMES:
                try:
                    for line in fpath.read_text(encoding="utf-8", errors="ignore").splitlines():
                        s = line.strip()
                        if not s or s.startswith("#") or "=" not in s:
                            continue
                        k = s.split("=", 1)[0].strip().removeprefix("export ").strip()
                        if re.match(r"^[A-Z][A-Z0-9_]{1,}$", k):
                            example_vars[k].append(rel)
                except OSError:
                    pass
                continue

            if low_name.startswith("docker-compose") and low_name.endswith((".yml", ".yaml")):
                try:
                    for line in fpath.read_text(encoding="utf-8", errors="ignore").splitlines():
                        m = _COMPOSE_ENV_RE.match(line)
                        if m:
                            compose_vars[m.group(1)].append(rel)
                except OSError:
                    pass
                continue

            ext = os.path.splitext(fname)[1].lower()
            if ext not in (".py", ".ts", ".tsx", ".js", ".jsx", ".vue"):
                continue
            if fname.endswith((".min.js", ".bundle.js", ".d.ts")):
                continue
            if any(h in f"/{rel.lower()}" for h in ("/tests/", "/test/", "/test_", "_test.py", ".spec.", ".test.")):
                continue
            try:
                if fpath.stat().st_size > 400_000:
                    continue
                src = fpath.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            scanned += 1

            if ext == ".py":
                py_vars, py_flags = _extract_py_env_vars(src)
                for vname, ln, dflt in py_vars:
                    code_refs[vname].append({"file": rel, "line": ln, "default": dflt})
                for fl, ln in py_flags:
                    sdk_flags.append({"flag": fl, "file": rel, "line": ln, "kind": "sdk"})
            else:
                for lineno, line in enumerate(src.splitlines(), 1):
                    for m in _JS_ENV_RE.finditer(line):
                        code_refs[m.group(1)].append({"file": rel, "line": lineno, "default": None})
                    for m in _FLAG_SDK_RE.finditer(line):
                        sdk_flags.append({"flag": m.group(1), "file": rel, "line": lineno, "kind": "sdk"})

    all_names = sorted(set(code_refs.keys()) | set(example_vars.keys()) | set(compose_vars.keys()))
    variables: list[dict[str, Any]] = []
    undocumented = 0
    unused = 0
    builtin_count = 0
    flag_count = 0

    for name in all_names:
        in_code = name in code_refs
        in_example = name in example_vars
        in_compose = name in compose_vars
        is_flag = name.startswith(_FLAG_PREFIXES)
        if is_flag:
            flag_count += 1
        if name in _BUILTIN_ENV_ALLOWLIST and not in_example and not in_compose:
            status = "BUILTIN"
            builtin_count += 1
        elif in_code and not in_example:
            status = "UNDOCUMENTED"
            undocumented += 1
        elif in_example and not in_code and not in_compose:
            status = "UNUSED"
            unused += 1
        else:
            status = "OK"
        refs = code_refs.get(name, [])
        variables.append({
            "name": name,
            "in_code": in_code,
            "in_example": in_example,
            "in_compose": in_compose,
            "is_feature_flag": is_flag,
            "status": status,
            "usage_count": len(refs),
            "files": sorted({r["file"] for r in refs})[:8],
            "example_files": sorted(set(example_vars.get(name, []))),
            "compose_files": sorted(set(compose_vars.get(name, []))),
        })

    # Sort drift issues first
    order = {"UNDOCUMENTED": 0, "UNUSED": 1, "OK": 2, "BUILTIN": 3}
    variables.sort(key=lambda v: (order.get(v["status"], 4), -int(v["usage_count"]), v["name"]))

    payload: dict[str, Any] = {
        "generated_at": time.time(),
        "summary": {
            "total_variables": len(variables),
            "undocumented_count": undocumented,
            "unused_count": unused,
            "builtin_count": builtin_count,
            "feature_flags_count": flag_count + len({f["flag"] for f in sdk_flags}),
            "files_scanned": scanned,
        },
        "variables": variables[:400],
        "sdk_feature_flags": sdk_flags[:100],
    }

    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "config-matrix.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    (data_dir / "config_matrix.js").write_text(f"window.CONFIG_MATRIX = {json.dumps(payload)};\n", encoding="utf-8")
    return payload
