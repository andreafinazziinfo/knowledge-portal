"""
ADR-082 Wave 3 (AI-6): Runtime Modes & Feature Flag Matrix Generator (100% Python stdlib).

Scans source code, docker-compose files, and safe .env.example templates (NEVER real .env files!)
to build the operational mode matrix:
  - offline
  - dev
  - paper
  - shadow
  - live

For each mode: required services, active safety guards, controlling env vars (names + safe defaults only),
and code references.

Writes:
  - <data_dir>/runtime-modes.json
  - <data_dir>/runtime_modes.js (window.RUNTIME_MODES_DATA)
"""

from __future__ import annotations

import json
import os
import re
from collections import defaultdict
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

SCAN_EXTENSIONS = {".py", ".ts", ".tsx", ".js", ".vue", ".yml", ".yaml"}

_SECRET_NAME_RE = re.compile(
    r"(?:SECRET|PASSWORD|PASSWD|TOKEN|API_?KEY|PRIVATE_?KEY|CREDENTIAL|AUTH_?KEY|DSN|DATABASE_URL|REDIS_URL|JWT)",
    re.IGNORECASE,
)

# Env var extraction in code: os.getenv("X", "default"), os.environ.get("X", ...), import.meta.env.VITE_X
_PY_ENV_RE = re.compile(
    r"""os\.(?:getenv|environ\.get)\s*\(\s*['"](?P<name>[A-Z][A-Z0-9_]{2,})['"](?:\s*,\s*['"]?(?P<default>[^'",)\n]{0,40})['"]?)?"""
)
_JS_ENV_RE = re.compile(
    r"""(?:import\.meta\.env|process\.env)\.(?P<name>[A-Z][A-Z0-9_]{2,})"""
)
_FEATURE_FLAG_RE = re.compile(
    r"^(?:ENABLE_|FEATURE_|USE_|ALLOW_|DISABLE_|MOCK_|DRY_RUN|PAPER_|LIVE_|SHADOW_|OFFLINE_|KILL_SWITCH|READ_ONLY|.+_ENABLED$|.+_MODE$|.+_ENV$)"
)

_MODE_SPECS: list[dict[str, Any]] = [
    {
        "mode": "offline",
        "label": "Offline / Air-Gapped",
        "risk_level": "LOW",
        "default_services": ["local_storage"],
        "keywords": ("offline", "airgap", "air_gap", "local_only", "no_network"),
        "env_hints": ("OFFLINE_MODE", "LOCAL_ONLY", "NO_NETWORK", "APP_ENV"),
    },
    {
        "mode": "dev",
        "label": "Development / Local",
        "risk_level": "LOW",
        "default_services": ["database", "redis"],
        "keywords": ("development", "dev_mode", "debug", "local_dev", "reload"),
        "env_hints": ("APP_ENV", "ENVIRONMENT", "NODE_ENV", "DEBUG", "DEV_MODE", "MOCK_"),
    },
    {
        "mode": "paper",
        "label": "Paper / Simulated Execution",
        "risk_level": "MEDIUM",
        "default_services": ["database", "redis", "worker", "paper_broker"],
        "keywords": ("paper", "paper_trading", "paper_mode", "simulated", "sandbox", "dry_run"),
        "env_hints": ("PAPER_MODE", "TRADING_MODE", "EXECUTION_MODE", "DRY_RUN", "SANDBOX"),
    },
    {
        "mode": "shadow",
        "label": "Shadow / Canary Observation",
        "risk_level": "HIGH",
        "default_services": ["database", "redis", "worker", "live_feed"],
        "keywords": ("shadow", "shadow_mode", "canary", "mirror", "read_only"),
        "env_hints": ("SHADOW_MODE", "CANARY_MODE", "READ_ONLY", "TRADING_MODE", "EXECUTION_MODE"),
    },
    {
        "mode": "live",
        "label": "Live / Production Execution",
        "risk_level": "CRITICAL",
        "default_services": ["database", "redis", "worker", "live_node", "external_api"],
        "keywords": ("live_mode", "live_trading", "production", "prod", "real_money"),
        "env_hints": ("LIVE_MODE", "LIVE_TRADING", "TRADING_MODE", "EXECUTION_MODE", "APP_ENV", "ENVIRONMENT", "KILL_SWITCH"),
    },
]

_GUARD_PATTERNS: list[tuple[str, re.Pattern[str], tuple[str, ...]]] = [
    ("kill_switch", re.compile(r"\bkill[_-]?switch\b", re.IGNORECASE), ("paper", "shadow", "live")),
    ("paper_broker", re.compile(r"\bpaper[_-]?(?:broker|adapter|mode|trading)\b", re.IGNORECASE), ("dev", "paper")),
    ("dry_run_guard", re.compile(r"\bdry[_-]?run\b", re.IGNORECASE), ("offline", "dev", "paper", "shadow")),
    ("read_only_guard", re.compile(r"\bread[_-]?only\b", re.IGNORECASE), ("offline", "shadow")),
    ("auth_middleware", re.compile(r"\b(?:require_auth|get_current_user|verify_token|jwt_auth|api_key_auth)\b", re.IGNORECASE), ("paper", "shadow", "live")),
    ("rate_limiter", re.compile(r"\b(?:rate_limit|limiter|slowapi|throttle)\b", re.IGNORECASE), ("shadow", "live")),
    ("circuit_breaker", re.compile(r"\bcircuit[_-]?breaker\b", re.IGNORECASE), ("paper", "shadow", "live")),
    ("drawdown_guard", re.compile(r"\b(?:max_drawdown|daily_loss_limit|risk_guard|position_limit)\b", re.IGNORECASE), ("paper", "shadow", "live")),
]

_SERVICE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("database", re.compile(r"\b(?:postgres|timescale|sqlalchemy|asyncpg|sqlite)\b", re.IGNORECASE)),
    ("redis", re.compile(r"\b(?:redis|aioredis)\b", re.IGNORECASE)),
    ("worker", re.compile(r"\b(?:celery|rq|dramatiq|bullmq)\b", re.IGNORECASE)),
    ("live_node", re.compile(r"\b(?:live_node|nautilus|ctrader|websocket_feed)\b", re.IGNORECASE)),
    ("external_api", re.compile(r"\b(?:ccxt|binance|bybit|exchange_api|broker_api)\b", re.IGNORECASE)),
]


def _sanitize_default(name: str, raw_default: str) -> str:
    val = (raw_default or "").strip()
    if not val:
        return ""
    if _SECRET_NAME_RE.search(name):
        return "<redacted>"
    if "://" in val and "@" in val:
        return "<redacted-uri>"
    return val[:40]


def _is_safe_env_template(filename: str) -> bool:
    low = filename.lower()
    return low in (".env.example", ".env.sample", ".env.template") or low.endswith((".env.example", ".env.sample", ".env.template"))


def _is_forbidden_env_file(filename: str) -> bool:
    low = filename.lower()
    if _is_safe_env_template(low):
        return False
    return low == ".env" or low.startswith(".env.")


def _scan_env_templates(project_dir: Path) -> dict[str, dict[str, str]]:
    """Read ONLY .env.example/.env.sample/.env.template files (NEVER real .env)."""
    env_vars: dict[str, dict[str, str]] = {}
    for root, dirs, files in os.walk(project_dir):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not d.startswith("."))
        for fname in sorted(files):
            if not _is_safe_env_template(fname):
                continue
            fpath = Path(root) / fname
            rel = fpath.relative_to(project_dir).as_posix()
            try:
                text = fpath.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for line in text.splitlines():
                stripped = line.strip()
                if not stripped or stripped.startswith("#") or "=" not in stripped:
                    continue
                k, v = stripped.split("=", 1)
                k = k.strip()
                if not re.match(r"^[A-Z][A-Z0-9_]{1,}$", k):
                    continue
                env_vars[k] = {
                    "name": k,
                    "default": _sanitize_default(k, v),
                    "source": rel,
                }
    return env_vars


def generate_runtime_modes(project_dir: Path, data_dir: Path) -> dict[str, Any]:
    """Generate operational runtime mode matrix & feature flag catalog (zero .env reads)."""
    project_dir = Path(project_dir).resolve()
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)

    template_envs = _scan_env_templates(project_dir)
    discovered_envs: dict[str, dict[str, Any]] = {}
    for k, info in template_envs.items():
        discovered_envs[k] = {
            "name": k,
            "default": info["default"],
            "files": [info["source"]],
            "is_feature_flag": bool(_FEATURE_FLAG_RE.match(k)),
        }

    detected_services: set[str] = set()
    guard_hits: dict[str, set[str]] = defaultdict(set)
    mode_refs: dict[str, list[dict[str, Any]]] = defaultdict(list)

    # Compile mode conditional regexes
    mode_cond_res: dict[str, re.Pattern[str]] = {}
    for spec in _MODE_SPECS:
        kw_alt = "|".join(re.escape(k) for k in spec["keywords"])
        mode_cond_res[spec["mode"]] = re.compile(
            rf"""(?:==|!=|in\s*\(|['"])\s*(?:{kw_alt})\b|\b(?:{kw_alt})\s*(?:==|!=)""",
            re.IGNORECASE,
        )

    for root, dirs, files in os.walk(project_dir):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not d.startswith("."))
        for fname in sorted(files):
            if _is_forbidden_env_file(fname):
                continue
            fpath = Path(root) / fname
            if fpath.suffix.lower() not in SCAN_EXTENSIONS:
                continue
            rel = fpath.relative_to(project_dir).as_posix()
            if "tests/" in rel.lower() or Path(rel).name.startswith("test_"):
                continue
            try:
                text = fpath.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue

            # Env vars in code
            for m in _PY_ENV_RE.finditer(text):
                name = m.group("name")
                default = _sanitize_default(name, m.group("default") or "")
                entry = discovered_envs.setdefault(name, {
                    "name": name,
                    "default": default,
                    "files": [],
                    "is_feature_flag": bool(_FEATURE_FLAG_RE.match(name)),
                })
                if not entry["default"] and default:
                    entry["default"] = default
                if rel not in entry["files"] and len(entry["files"]) < 10:
                    entry["files"].append(rel)

            for m in _JS_ENV_RE.finditer(text):
                name = m.group("name")
                entry = discovered_envs.setdefault(name, {
                    "name": name,
                    "default": "",
                    "files": [],
                    "is_feature_flag": bool(_FEATURE_FLAG_RE.match(name)),
                })
                if rel not in entry["files"] and len(entry["files"]) < 10:
                    entry["files"].append(rel)

            # Services detected in codebase
            for svc_name, svc_re in _SERVICE_PATTERNS:
                if svc_name not in detected_services and svc_re.search(text):
                    detected_services.add(svc_name)

            # Safety guards detected
            for guard_name, guard_re, _modes in _GUARD_PATTERNS:
                if guard_re.search(text):
                    guard_hits[guard_name].add(rel)

            # Mode references
            for mode_name, m_re in mode_cond_res.items():
                if len(mode_refs[mode_name]) >= 15:
                    continue
                hit = m_re.search(text)
                if hit:
                    line_no = text.count("\n", 0, hit.start()) + 1
                    mode_refs[mode_name].append({
                        "file": rel,
                        "line": line_no,
                        "match": hit.group(0).strip()[:60],
                    })

    # Build the 5 operational modes
    modes_list: list[dict[str, Any]] = []
    for spec in _MODE_SPECS:
        m_name = spec["mode"]
        req_services = [
            s for s in spec["default_services"]
            if s in detected_services or s in ("local_storage", "paper_broker", "live_feed")
        ]
        if not req_services:
            req_services = list(spec["default_services"])

        active_guards = [
            {
                "guard": g_name,
                "detected_in_code": bool(guard_hits.get(g_name)),
                "files": sorted(guard_hits.get(g_name) or [])[:5],
            }
            for g_name, _gre, g_modes in _GUARD_PATTERNS
            if m_name in g_modes
        ]

        controlling_vars: list[dict[str, Any]] = []
        for env_name, env_info in sorted(discovered_envs.items()):
            if any(env_name.startswith(h) or h in env_name for h in spec["env_hints"]):
                controlling_vars.append({
                    "name": env_name,
                    "default": env_info["default"],
                    "files": env_info["files"][:3],
                })

        refs = mode_refs.get(m_name) or []
        modes_list.append({
            "mode": m_name,
            "label": spec["label"],
            "risk_level": spec["risk_level"],
            "detected_in_code": len(refs) > 0 or len(controlling_vars) > 0,
            "required_services": req_services,
            "active_guards": active_guards,
            "active_guards_detected_count": sum(1 for g in active_guards if g["detected_in_code"]),
            "controlling_env_vars": controlling_vars[:20],
            "code_references": refs[:12],
        })

    feature_flags = sorted(
        [v for v in discovered_envs.values() if v["is_feature_flag"]],
        key=lambda x: x["name"],
    )

    summary = {
        "modes_count": len(modes_list),
        "modes_detected_count": sum(1 for m in modes_list if m["detected_in_code"]),
        "feature_flags_count": len(feature_flags),
        "total_env_vars_scanned": len(discovered_envs),
        "detected_services": sorted(detected_services),
        "detected_guards": sorted(guard_hits.keys()),
        "env_files_read": "templates_only_never_dotenv",
    }

    payload: dict[str, Any] = {
        "schema_version": "1.0",
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "summary": summary,
        "modes": modes_list,
        "feature_flags": feature_flags,
    }

    json_path = data_dir / "runtime-modes.json"
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    js_path = data_dir / "runtime_modes.js"
    js_path.write_text(
        f"window.RUNTIME_MODES_DATA = {json.dumps(payload, ensure_ascii=False)};\n",
        encoding="utf-8",
    )
    return payload
