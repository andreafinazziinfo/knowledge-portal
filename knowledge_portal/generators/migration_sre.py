"""
Knowledge Portal — DB Migration Safety & SRE Resilience Auditor (ADR-080 P1.3).
100% Python stdlib zero-dependency static auditor:
- DB Migration Safety (SQL & Alembic):
  * SQL_DESTRUCTIVE_DDL (CRITICAL): DROP TABLE / DROP COLUMN / TRUNCATE without -- migration-safe
  * SQL_INDEX_WITHOUT_CONCURRENTLY (HIGH): CREATE [UNIQUE] INDEX without CONCURRENTLY
  * SQL_NOT_NULL_NO_DEFAULT (HIGH): ALTER TABLE ... ADD COLUMN ... NOT NULL without DEFAULT
  * SQL_LOCK_TIMEOUT_MISSING (MEDIUM): migration with ALTER TABLE / CREATE INDEX lacking lock_timeout / statement_timeout
- SRE Resilience Auditor (Python backend):
  * Retry / backoff / circuit-breaker coverage on HTTP & LLM clients
  * Unstructured f-string logging (logger.info(f"...")) vs lazy %s / extra / structlog
  * Graceful shutdown verification (FastAPI lifespan, on_event("shutdown"), SIGTERM handler)
  * Structured logging & rate limiting signals
"""

from __future__ import annotations

import ast
import os
import re
from collections import Counter
from pathlib import Path
from typing import Any

_IGNORE_DIRS = frozenset({
    ".git", "node_modules", "dist", "dev-dist", "build", ".venv", "venv",
    "__pycache__", ".idea", ".vscode", "target", "vendor", "bin", "obj", "frozen", "archive",
})

_SQL_DESTRUCTIVE_RE = re.compile(
    r"\b(DROP\s+TABLE|DROP\s+COLUMN|TRUNCATE\s+(?:TABLE\s+)?[a-zA-Z_\"`])",
    re.IGNORECASE,
)
_SQL_CREATE_INDEX_RE = re.compile(
    r"\bCREATE\s+(?:UNIQUE\s+)?INDEX\b(?![^\n;]*\bCONCURRENTLY\b)",
    re.IGNORECASE,
)
_SQL_ADD_COL_NOT_NULL_RE = re.compile(
    r"\bALTER\s+TABLE\b[^;]*\bADD\s+(?:COLUMN\s+)?(?:IF\s+NOT\s+EXISTS\s+)?[a-zA-Z_\"`][a-zA-Z0-9_\"`]*\s+[^;]*\bNOT\s+NULL\b[^;]*",
    re.IGNORECASE | re.DOTALL,
)
_SQL_LOCK_TIMEOUT_RE = re.compile(r"\bSET\s+(?:LOCAL\s+)?(?:lock_timeout|statement_timeout)\b", re.IGNORECASE)
_SQL_ALTER_OR_IDX_RE = re.compile(r"\b(?:ALTER\s+TABLE|CREATE\s+(?:UNIQUE\s+)?INDEX)\b", re.IGNORECASE)

_HTTP_LLM_IMPORTS = frozenset({
    "httpx", "aiohttp", "requests", "urllib3", "openai", "anthropic", "google", "litellm",
})
_RETRY_HINTS_RE = re.compile(
    r"\b(tenacity|@retry|backoff|Retry|max_retries|retry_policy|CircuitBreaker|circuit_breaker|exponential_backoff)\b",
    re.IGNORECASE,
)
_STRUCTLOG_HINTS_RE = re.compile(
    r"\b(structlog|JsonFormatter|pythonjsonlogger|JSONFormatter|extra\s*=\s*\{)\b",
)
_GRACEFUL_SHUTDOWN_RE = re.compile(
    r"(lifespan\s*=|def\s+lifespan\b|on_event\(\s*['\"]shutdown['\"]|signal\.SIGTERM|add_signal_handler\(\s*signal\.SIGTERM)",
)
_RATE_LIMIT_RE = re.compile(
    r"\b(slowapi|RateLimiter|rate_limit|Limiter\(|TokenBucket|SlidingWindow)\b",
)
_LOG_METHODS = frozenset({"debug", "info", "warning", "warn", "error", "exception", "critical"})


def _is_test_path(rel: str) -> bool:
    low = f"/{rel.lower()}"
    return any(h in low for h in ("/tests/", "/test/", "/test_", "_test.py", "conftest.py"))


def _is_migration_file(rel: str) -> bool:
    low = rel.lower()
    if low.endswith(".sql"):
        return any(h in f"/{low}" for h in ("/migration/", "/migrations/", "/migrate/", "/alembic/", "/db/")) or "migration" in low
    if low.endswith(".py"):
        return "alembic/versions/" in low or "/migrations/" in low
    return False


def _line_of_offset(text: str, offset: int) -> int:
    return text.count("\n", 0, max(0, offset)) + 1


def _scan_sql_migration(src: str, rel: str) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    lines = src.splitlines()

    cleaned_lines = ["" if ln.strip().startswith("--") else ln for ln in lines]
    cleaned = "\n".join(cleaned_lines)

    for m in _SQL_DESTRUCTIVE_RE.finditer(cleaned):
        lineno = _line_of_offset(cleaned, m.start())
        raw_line = lines[lineno - 1] if lineno <= len(lines) else ""
        prev_line = lines[lineno - 2] if lineno >= 2 else ""
        if "migration-safe" in raw_line.lower() or "migration-safe" in prev_line.lower():
            continue
        findings.append({
            "rule": "SQL_DESTRUCTIVE_DDL",
            "severity": "CRITICAL",
            "category": "migration",
            "path": rel,
            "line": lineno,
            "detail": f"Destructive DDL `{m.group(1).strip()}` without `-- migration-safe` guard",
            "remediation": "Verify zero-downtime rollout (expand-contract) or annotate intentionally safe cleanup with `-- migration-safe`.",
        })

    for m in _SQL_CREATE_INDEX_RE.finditer(cleaned):
        lineno = _line_of_offset(cleaned, m.start())
        raw_line = lines[lineno - 1] if lineno <= len(lines) else ""
        prev_line = lines[lineno - 2] if lineno >= 2 else ""
        if "migration-safe" in raw_line.lower() or "migration-safe" in prev_line.lower():
            continue
        findings.append({
            "rule": "SQL_INDEX_WITHOUT_CONCURRENTLY",
            "severity": "HIGH",
            "category": "migration",
            "path": rel,
            "line": lineno,
            "detail": "`CREATE INDEX` without `CONCURRENTLY` acquires a table write lock on Postgres/TimescaleDB",
            "remediation": "Use `CREATE INDEX CONCURRENTLY IF NOT EXISTS ...` outside a transaction block.",
        })

    for m in _SQL_ADD_COL_NOT_NULL_RE.finditer(cleaned):
        stmt = m.group(0)
        if re.search(r"\bDEFAULT\b", stmt, re.IGNORECASE):
            continue
        lineno = _line_of_offset(cleaned, m.start())
        raw_line = lines[lineno - 1] if lineno <= len(lines) else ""
        if "migration-safe" in raw_line.lower():
            continue
        findings.append({
            "rule": "SQL_NOT_NULL_NO_DEFAULT",
            "severity": "HIGH",
            "category": "migration",
            "path": rel,
            "line": lineno,
            "detail": "`ALTER TABLE ... ADD COLUMN ... NOT NULL` without `DEFAULT` fails on populated tables or forces table rewrite",
            "remediation": "Add a `DEFAULT` value, or add nullable first, backfill in batches, then `SET NOT NULL`.",
        })

    if _SQL_ALTER_OR_IDX_RE.search(cleaned) and not _SQL_LOCK_TIMEOUT_RE.search(cleaned):
        first_m = _SQL_ALTER_OR_IDX_RE.search(cleaned)
        lineno = _line_of_offset(cleaned, first_m.start()) if first_m else 1
        findings.append({
            "rule": "SQL_LOCK_TIMEOUT_MISSING",
            "severity": "MEDIUM",
            "category": "migration",
            "path": rel,
            "line": lineno,
            "detail": "Migration performs `ALTER TABLE`/`CREATE INDEX` without `SET lock_timeout` or `SET statement_timeout`",
            "remediation": "Add `SET lock_timeout = '5s'; SET statement_timeout = '30s';` at top of migration to prevent lock queue pileups.",
        })

    return findings


def _scan_alembic_migration(src: str, rel: str) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    lines = src.splitlines()
    try:
        tree = ast.parse(src)
    except Exception:
        return findings

    has_alter_or_index = False
    has_lock_timeout = "lock_timeout" in src.lower() or "statement_timeout" in src.lower()
    first_alter_line = 1

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name) and node.func.value.id == "op":
            op_name = node.func.attr
            lineno = getattr(node, "lineno", 1)
            raw_line = lines[lineno - 1] if lineno <= len(lines) else ""
            if "migration-safe" in raw_line.lower():
                continue
            if op_name in ("drop_table", "drop_column"):
                findings.append({
                    "rule": "SQL_DESTRUCTIVE_DDL",
                    "severity": "CRITICAL",
                    "category": "migration",
                    "path": rel,
                    "line": lineno,
                    "detail": f"Alembic `op.{op_name}()` is destructive without `# migration-safe` guard",
                    "remediation": "Use expand-contract rollout or annotate with `# migration-safe` after verification.",
                })
            elif op_name == "create_index":
                has_alter_or_index = True
                if first_alter_line == 1:
                    first_alter_line = lineno
                kw = {k.arg: k.value for k in node.keywords if k.arg}
                conc = kw.get("postgresql_concurrently")
                if not (isinstance(conc, ast.Constant) and conc.value is True):
                    findings.append({
                        "rule": "SQL_INDEX_WITHOUT_CONCURRENTLY",
                        "severity": "HIGH",
                        "category": "migration",
                        "path": rel,
                        "line": lineno,
                        "detail": "Alembic `op.create_index()` missing `postgresql_concurrently=True`",
                        "remediation": "Pass `postgresql_concurrently=True` inside `with op.get_context().autocommit_block():`.",
                    })
            elif op_name == "add_column":
                has_alter_or_index = True
                if first_alter_line == 1:
                    first_alter_line = lineno
                call_src = ast.unparse(node) if hasattr(ast, "unparse") else raw_line
                if "nullable=False" in call_src and "server_default=" not in call_src:
                    findings.append({
                        "rule": "SQL_NOT_NULL_NO_DEFAULT",
                        "severity": "HIGH",
                        "category": "migration",
                        "path": rel,
                        "line": lineno,
                        "detail": "Alembic `op.add_column(..., nullable=False)` without `server_default=`",
                        "remediation": "Provide `server_default=...` or backfill before enforcing `nullable=False`.",
                    })
            elif op_name in ("alter_column", "create_foreign_key", "create_unique_constraint"):
                has_alter_or_index = True
                if first_alter_line == 1:
                    first_alter_line = lineno

    if has_alter_or_index and not has_lock_timeout:
        findings.append({
            "rule": "SQL_LOCK_TIMEOUT_MISSING",
            "severity": "MEDIUM",
            "category": "migration",
            "path": rel,
            "line": first_alter_line,
            "detail": "Alembic migration alters schema without `SET lock_timeout` / `SET statement_timeout`",
            "remediation": "Run `op.execute(\"SET lock_timeout = '5s'\")` before DDL operations.",
        })
    return findings


def analyze_migration_and_sre(project_dir: Path, max_files: int = 2000) -> dict[str, Any]:
    """Audit SQL/Alembic migration safety and Python backend SRE resilience patterns."""
    project_dir = Path(project_dir).resolve()
    migration_files_scanned = 0
    migration_findings: list[dict[str, Any]] = []

    py_files_scanned = 0
    has_graceful_shutdown = False
    graceful_shutdown_files: list[str] = []
    has_structured_logging = False
    has_retry_policy = False
    has_rate_limiting = False
    has_circuit_breaker = False

    http_llm_client_files: list[str] = []
    http_llm_with_retry_files: list[str] = []
    fstring_logs: list[dict[str, Any]] = []

    for root, dirs, files in os.walk(project_dir):
        dirs[:] = [d for d in dirs if d not in _IGNORE_DIRS and not d.startswith(".")]
        for fname in sorted(files):
            fpath = Path(root) / fname
            rel = str(fpath.relative_to(project_dir)).replace("\\", "/")
            if "frozen/" in rel.lower():
                continue

            if _is_migration_file(rel):
                try:
                    if fpath.stat().st_size > 500_000:
                        continue
                    src = fpath.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                migration_files_scanned += 1
                if rel.lower().endswith(".sql"):
                    migration_findings.extend(_scan_sql_migration(src, rel))
                elif rel.lower().endswith(".py"):
                    migration_findings.extend(_scan_alembic_migration(src, rel))
                continue

            if not fname.endswith(".py") or _is_test_path(rel) or py_files_scanned >= max_files:
                continue
            try:
                if fpath.stat().st_size > 400_000:
                    continue
                src = fpath.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            py_files_scanned += 1

            if _GRACEFUL_SHUTDOWN_RE.search(src):
                has_graceful_shutdown = True
                if len(graceful_shutdown_files) < 10:
                    graceful_shutdown_files.append(rel)
            if _STRUCTLOG_HINTS_RE.search(src):
                has_structured_logging = True
            if _RATE_LIMIT_RE.search(src):
                has_rate_limiting = True
            file_has_retry = bool(_RETRY_HINTS_RE.search(src))
            if file_has_retry:
                has_retry_policy = True
            if "circuitbreaker" in src.lower() or "circuit_breaker" in src.lower():
                has_circuit_breaker = True

            try:
                tree = ast.parse(src)
            except Exception:
                continue

            uses_http_llm = False
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name.split(".")[0] in _HTTP_LLM_IMPORTS:
                            uses_http_llm = True
                elif isinstance(node, ast.ImportFrom) and node.module:
                    if node.module.split(".")[0] in _HTTP_LLM_IMPORTS:
                        uses_http_llm = True
                elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                    if node.func.attr in _LOG_METHODS:
                        owner = ""
                        if isinstance(node.func.value, ast.Name):
                            owner = node.func.value.id.lower()
                        elif isinstance(node.func.value, ast.Attribute):
                            owner = node.func.value.attr.lower()
                        if owner in ("logger", "log", "logging") and node.args and isinstance(node.args[0], ast.JoinedStr):
                            fstring_logs.append({
                                "rule": "SRE_FSTRING_LOGGING",
                                "severity": "LOW",
                                "category": "sre",
                                "path": rel,
                                "line": getattr(node, "lineno", 1),
                                "detail": f"Unstructured f-string in `{owner}.{node.func.attr}(f\"...\")` eagerly formats message and breaks structured log aggregation",
                                "remediation": "Use lazy `%s` placeholders (`logger.info('msg %s', val)`) or structured `extra={...}` / `structlog`.",
                            })

            if uses_http_llm:
                http_llm_client_files.append(rel)
                if file_has_retry:
                    http_llm_with_retry_files.append(rel)

    sev_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
    migration_findings.sort(key=lambda f: (sev_order.get(f["severity"], 4), f["path"], f["line"]))
    mig_by_rule = dict(Counter(f["rule"] for f in migration_findings))
    mig_by_sev = Counter(f["severity"] for f in migration_findings)

    http_without_retry = [f for f in http_llm_client_files if f not in set(http_llm_with_retry_files)]
    retry_cov_pct = (
        round(100.0 * len(http_llm_with_retry_files) / len(http_llm_client_files), 1)
        if http_llm_client_files
        else 100.0
    )

    gaps: list[dict[str, Any]] = []
    if py_files_scanned > 0 and not has_graceful_shutdown:
        gaps.append({
            "rule": "SRE_MISSING_GRACEFUL_SHUTDOWN",
            "severity": "HIGH",
            "category": "sre",
            "path": "backend",
            "line": 1,
            "detail": "No FastAPI `lifespan`, `on_event('shutdown')`, or `SIGTERM` handler detected",
            "remediation": "Add a FastAPI `lifespan` context manager or `SIGTERM` signal handler to drain connections cleanly.",
        })
    if py_files_scanned > 0 and not has_structured_logging:
        gaps.append({
            "rule": "SRE_MISSING_STRUCTURED_LOGGING",
            "severity": "MEDIUM",
            "category": "sre",
            "path": "backend",
            "line": 1,
            "detail": "No structured logging (`structlog`, `JsonFormatter`, or `extra={...}`) detected",
            "remediation": "Adopt JSON structured logging or pass contextual fields via `extra={...}`.",
        })
    if http_llm_client_files and not has_retry_policy:
        gaps.append({
            "rule": "SRE_MISSING_RETRY_BACKOFF",
            "severity": "HIGH",
            "category": "sre",
            "path": http_without_retry[0] if http_without_retry else "backend",
            "line": 1,
            "detail": f"{len(http_without_retry)}/{len(http_llm_client_files)} HTTP/LLM client files lack retry/backoff or circuit-breaker policy",
            "remediation": "Wrap outbound HTTP/LLM calls with exponential backoff (`tenacity` / retry helper) and circuit breaker.",
        })
    if py_files_scanned > 0 and not has_rate_limiting:
        gaps.append({
            "rule": "SRE_MISSING_RATE_LIMITING",
            "severity": "LOW",
            "category": "sre",
            "path": "backend",
            "line": 1,
            "detail": "No API rate limiting (`slowapi` / `RateLimiter` / `TokenBucket`) detected",
            "remediation": "Protect public/mutating endpoints with rate limiting middleware.",
        })

    score = 0
    if has_graceful_shutdown:
        score += 30
    if has_structured_logging:
        score += 25
    if has_retry_policy or not http_llm_client_files:
        score += 25
    if has_rate_limiting:
        score += 10
    if has_circuit_breaker:
        score += 10

    combined_findings = migration_findings[:80] + gaps + fstring_logs[:40]
    combined_findings.sort(key=lambda f: (sev_order.get(f["severity"], 4), f["path"], f["line"]))

    return {
        "migration_safety": {
            "files_scanned": migration_files_scanned,
            "total_issues": len(migration_findings),
            "by_rule": mig_by_rule,
            "by_severity": {
                "CRITICAL": mig_by_sev["CRITICAL"],
                "HIGH": mig_by_sev["HIGH"],
                "MEDIUM": mig_by_sev["MEDIUM"],
            },
            "findings": migration_findings[:80],
        },
        "sre_resilience": {
            "score_pct": score,
            "py_files_scanned": py_files_scanned,
            "has_graceful_shutdown": has_graceful_shutdown,
            "graceful_shutdown_files": graceful_shutdown_files,
            "has_structured_logging": has_structured_logging,
            "has_retry_policy": has_retry_policy,
            "has_circuit_breaker": has_circuit_breaker,
            "has_rate_limiting": has_rate_limiting,
            "http_llm_client_files_count": len(http_llm_client_files),
            "http_llm_retry_coverage_pct": retry_cov_pct,
            "http_clients_without_retry": http_without_retry[:25],
            "fstring_logging_count": len(fstring_logs),
            "fstring_logging_samples": fstring_logs[:40],
            "gaps": gaps,
        },
        "findings": combined_findings[:120],
    }
