"""
Knowledge Portal — AI-Native Token-Budget Engine, Slicer, Diff/Slop Guard & Handoff (ADR-082 Wave 1).
100% Python stdlib zero-dependency engine shared across MCP servers and HTTP APIs:
- Conservative token estimation (`ceil(len(json) / 3.8)`)
- Universal `detail: "summary" | "compact" | "full"` payload budgeting (summary <= 800 tok target, <= 1200 hard cap)
- Centralized `_validate_args` with alias normalization and zero silent-empty errors
- Deterministic PageRank (15 LOC) + BM25-lite `slice_for_task` with active ADR filtering
- `check_diff` with `_ai_slop_and_cheat_guard` and Change Risk Score (`churn x complexity x blast_radius`)
- `build_handoff_pack` portable cross-agent snapshot (<= 1500 tok)
- `query_test_oracle` fast test selector (<= 500 tok)
"""

from __future__ import annotations

import ast
import json
import math
import re
import subprocess
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

_STOPWORDS = frozenset({
    "the", "and", "for", "with", "that", "this", "from", "into", "when", "where",
    "what", "how", "fix", "add", "update", "make", "need", "use", "using", "file",
    "code", "check", "run", "all", "are", "was", "were", "will", "can", "not",
})

_SYNC_IO_FUNCS = frozenset({"sleep", "urlopen", "get", "post", "put", "delete", "run", "call", "check_output"})
_SYNC_IO_MODS = frozenset({"time", "requests", "urllib", "subprocess"})

_STDLIB_MODULES: frozenset[str] = getattr(sys, "stdlib_module_names", frozenset({
    "os", "sys", "re", "json", "math", "time", "pathlib", "typing", "ast",
    "collections", "itertools", "functools", "subprocess", "threading",
    "http", "urllib", "sqlite3", "argparse", "shutil", "hmac", "hashlib",
    "datetime", "logging", "dataclasses", "enum", "io", "csv", "xml",
    "asyncio", "contextlib", "copy", "tempfile", "unittest", "uuid", "fcntl",
}))


def estimate_tokens(obj: Any) -> int:
    """Conservative token estimate: ceil(len(json_str) / 3.8)."""
    text = obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False, indent=2)
    return math.ceil(len(text) / 3.8) if text else 0


def validate_args(
    tool_name: str,
    raw_args: Any,
    required: tuple[str, ...] = (),
    allowed: tuple[str, ...] = (),
    aliases: dict[str, str] | None = None,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Centralized MCP argument validator with alias normalization and zero silent-empty."""
    if not isinstance(raw_args, dict):
        return {}, {
            "ok": False,
            "error": "invalid_arguments",
            "tool": tool_name,
            "message": "Arguments must be a JSON object.",
            "expected_required": list(required),
            "expected_allowed": list(allowed),
        }

    normalized: dict[str, Any] = {}
    mapped_aliases: dict[str, str] = {}
    alias_map = aliases or {}

    for k, v in raw_args.items():
        if k in alias_map and alias_map[k] not in raw_args:
            canon = alias_map[k]
            normalized[canon] = v
            mapped_aliases[k] = canon
        else:
            normalized[k] = v

    allowed_set = set(allowed) | set(required) | {"detail", "section", "path_prefix", "limit", "offset"}
    unknown = sorted(k for k in normalized if k not in allowed_set)
    missing: list[str] = []
    for req_k in required:
        val = normalized.get(req_k)
        if val is None or (isinstance(val, str) and not val.strip()) or (isinstance(val, list) and len(val) == 0):
            missing.append(req_k)

    if missing or unknown:
        return normalized, {
            "ok": False,
            "error": "invalid_arguments",
            "tool": tool_name,
            "missing": missing,
            "unknown": unknown,
            "expected_schema": {
                "required": list(required),
                "allowed": sorted(allowed_set),
                "aliases": alias_map,
            },
            "hint": f"Provide required parameters {list(required)} and only allowed keys.",
        }

    if mapped_aliases:
        normalized["_normalized_args"] = mapped_aliases
    return normalized, None


def _truncate_to_token_cap(payload: dict[str, Any], cap: int = 1100) -> dict[str, Any]:
    """Hard-cap safeguard guaranteeing summary responses never exceed CI ceiling."""
    if estimate_tokens(payload) <= cap:
        return payload
    out = dict(payload)
    # Trim list fields progressively
    for _ in range(8):
        if estimate_tokens(out) <= cap:
            return out
        trimmed_any = False
        for k, v in list(out.items()):
            if isinstance(v, list) and len(v) > 3:
                out[k] = v[: max(3, len(v) // 2)]
                trimmed_any = True
            elif isinstance(v, str) and len(v) > 300 and k != "_drilldown_hint":
                out[k] = v[:240] + "..."
                trimmed_any = True
        if not trimmed_any:
            break
    if estimate_tokens(out) > cap:
        for k, v in list(out.items()):
            if isinstance(v, list) and len(v) > 1:
                out[k] = v[:1]
                if estimate_tokens(out) <= cap:
                    break
    return out


def apply_detail_budget(
    tool_name: str,
    data: dict[str, Any],
    detail: str = "summary",
    section: str = "",
    path_prefix: str = "",
    limit: int = 25,
    offset: int = 0,
) -> dict[str, Any]:
    """Apply universal detail='summary'|'compact'|'full' token budget to tool output."""
    mode = (detail or "summary").strip().lower()
    if mode not in ("summary", "compact", "full"):
        mode = "summary"

    if mode == "full":
        tok = estimate_tokens(data)
        if tok > 10000:
            return {**data, "_detail": "full", "_estimated_tokens": tok, "_warning": f"Large payload (~{tok} tokens). Prefer detail='summary' or detail='compact'."}
        return {**data, "_detail": "full"}

    lim = max(1, min(int(limit or 25), 100))
    off = max(0, int(offset or 0))
    pfx = (path_prefix or "").strip().lower()
    sec = (section or "").strip().lower()

    if mode == "compact":
        return _build_compact_view(tool_name, data, section=sec, path_prefix=pfx, limit=lim, offset=off)

    # mode == "summary" (target <= 800 tok, hard cap <= 1100 tok)
    summary_payload = _build_summary_view(tool_name, data)
    if "schema_version" in data and "schema_version" not in summary_payload:
        summary_payload = {"schema_version": data["schema_version"], **summary_payload}
    return _truncate_to_token_cap(summary_payload, cap=1100)


def _filter_items(items: list[Any], path_prefix: str, limit: int, offset: int) -> tuple[list[Any], int]:
    if path_prefix:
        filtered = [x for x in items if path_prefix in json.dumps(x, ensure_ascii=False).lower()]
    else:
        filtered = list(items)
    return filtered[offset : offset + limit], len(filtered)


def _build_compact_view(
    tool_name: str,
    data: dict[str, Any],
    section: str,
    path_prefix: str,
    limit: int,
    offset: int,
) -> dict[str, Any]:
    out: dict[str, Any] = {"tool": tool_name, "_detail": "compact"}
    if "summary" in data and isinstance(data["summary"], dict):
        out["summary"] = data["summary"]
    if section and section in data:
        val = data[section]
        if isinstance(val, list):
            page, total = _filter_items(val, path_prefix, limit, offset)
            out[section] = page
            out["total_matching"] = total
            out["pagination"] = {"limit": limit, "offset": offset}
        else:
            out[section] = val
        return _truncate_to_token_cap(out, cap=2500)

    # Generic compact slice of top list keys
    for k, v in data.items():
        if k == "summary":
            continue
        if isinstance(v, list):
            page, total = _filter_items(v, path_prefix, min(limit, 15), offset)
            out[k] = page
            out[f"{k}_total"] = total
        elif isinstance(v, dict) and len(v) <= 12:
            out[k] = v
    return _truncate_to_token_cap(out, cap=2500)


def _build_summary_view(tool_name: str, data: dict[str, Any]) -> dict[str, Any]:
    """Tool-specific summary extractors keeping default responses <= 800 tokens."""
    if tool_name == "portal_health_audit":
        hv4 = data.get("health_v4") or {}
        fix_q = data.get("fix_queue") or []
        return {
            "_detail": "summary",
            "summary": data.get("summary") or {},
            "severity_summary": (hv4.get("severity_summary") or [])[:8],
            "top_fix_queue": [
                {"priority": f.get("priority"), "category": f.get("category"), "title": str(f.get("title", ""))[:90], "path": f.get("path", "")}
                for f in fix_q[:5] if isinstance(f, dict)
            ],
            "cve_summary": (data.get("cve_report") or {}).get("summary") or {},
            "sarif_summary": (data.get("sarif_findings") or {}).get("summary") or {},
            "_drilldown_hint": "Pass detail='compact', section='fix_queue'|'cycles'|'god_files'|'health_v4' or detail='full'.",
        }

    if tool_name == "portal_git_dag":
        wts = data.get("worktrees") or []
        anoms = [w for w in wts if isinstance(w, dict) and w.get("status") not in ("clean", "main")]
        return {
            "_detail": "summary",
            "summary": data.get("summary") or {},
            "anomalous_worktrees": [
                {"branch": w.get("branch"), "status": w.get("status"), "dirty_files": w.get("dirty_files", 0)}
                for w in anoms[:6]
            ],
            "merge_order": (data.get("merge_order") or [])[:6],
            "_drilldown_hint": "Pass detail='compact', section='worktrees'|'branches'|'prs' for paginated list.",
        }

    if tool_name == "portal_dead_code":
        return {
            "_detail": "summary",
            "summary": data.get("summary") or {},
            "top_python_dead": [
                {"name": d.get("name"), "path": d.get("path"), "line": d.get("line")}
                for d in (data.get("python_dead_symbols") or [])[:5] if isinstance(d, dict)
            ],
            "top_js_unused": [
                {"name": d.get("name"), "path": d.get("path")}
                for d in (data.get("js_unused_exports") or [])[:5] if isinstance(d, dict)
            ],
            "top_vue_unused": [
                {"name": d.get("name"), "path": d.get("path")}
                for d in (data.get("vue_unused_components") or [])[:5] if isinstance(d, dict)
            ],
            "_drilldown_hint": "Pass detail='compact', path_prefix='backend/app/' or section='python_dead_symbols' for details.",
        }

    if tool_name == "portal_adr_graph":
        nodes = data.get("nodes") or []
        by_status: Counter[str] = Counter()
        by_domain: Counter[str] = Counter()
        for n in nodes:
            if isinstance(n, dict):
                by_status[str(n.get("status") or "Unknown")] += 1
                by_domain[str(n.get("domain") or "General")] += 1
        return {
            "_detail": "summary",
            "total_adrs": data.get("total_adrs", len(nodes)),
            "by_status": dict(by_status),
            "by_domain": dict(by_domain.most_common(10)),
            "latest_adrs": [
                {"id": n.get("id"), "title": str(n.get("title", ""))[:70], "status": n.get("status"), "domain": n.get("domain")}
                for n in nodes[-8:] if isinstance(n, dict)
            ],
            "runbooks_count": len(data.get("runbooks") or []),
            "_drilldown_hint": "Pass domain='...', status='Accepted', or detail='compact' to inspect ADR nodes & runbooks.",
        }

    if tool_name == "portal_config_matrix":
        vars_list = data.get("variables") or []
        drifts = [v for v in vars_list if isinstance(v, dict) and v.get("status") != "OK"]
        return {
            "_detail": "summary",
            "summary": data.get("summary") or {"total_vars": len(vars_list), "drift_count": len(drifts)},
            "top_drift_variables": [
                {"name": v.get("name"), "status": v.get("status"), "in_code": v.get("in_code"), "in_example": v.get("in_example")}
                for v in drifts[:8]
            ],
            "_drilldown_hint": "Pass drift_only=True, detail='compact', or path_prefix='...' for full variable matrix.",
        }

    if tool_name == "portal_api_catalog":
        eps = data.get("endpoints") or []
        return {
            "_detail": "summary",
            "summary": data.get("summary") or {"total_endpoints": len(eps)},
            "tags": (data.get("tags") or [])[:15],
            "sample_endpoints": [
                {"method": e.get("method"), "path": e.get("path"), "handler": e.get("handler"), "auth": e.get("auth_required")}
                for e in eps[:10] if isinstance(e, dict)
            ],
            "_drilldown_hint": "Pass query='<route-or-tag>' or detail='compact' to list matching endpoints.",
        }

    if tool_name == "portal_db_schema":
        tables = data.get("tables") or []
        return {
            "_detail": "summary",
            "filter": data.get("filter", ""),
            "count": data.get("count", len(tables)),
            "tables_index": [
                {
                    "name": t.get("name"),
                    "columns": len(t.get("columns") or []),
                    "fks": len(t.get("foreign_keys") or []),
                    "hypertable": bool(t.get("is_hypertable")),
                }
                for t in tables[:15] if isinstance(t, dict)
            ],
            "_drilldown_hint": "Pass table='<table_name>' or detail='compact' to inspect columns & foreign keys.",
        }

    if tool_name == "portal_stack":
        items = data.get("items") or []
        return {
            "_detail": "summary",
            "query": data.get("query", ""),
            "summary": data.get("summary") or {},
            "count": data.get("count", len(items)),
            "top_items": [
                {"name": i.get("name"), "version": i.get("version"), "ecosystem": i.get("ecosystem") or i.get("category")}
                for i in items[:12] if isinstance(i, dict)
            ],
            "_drilldown_hint": "Pass query='<pkg>' or detail='compact' for full dependency inventory.",
        }

    if tool_name == "portal_iac_topology":
        misconfigs = data.get("misconfigurations") or data.get("findings") or []
        return {
            "_detail": "summary",
            "summary": data.get("summary") or {},
            "top_misconfigurations": [
                {"severity": m.get("severity"), "rule": m.get("rule") or m.get("id"), "file": m.get("file") or m.get("path"), "message": str(m.get("message", ""))[:80]}
                for m in misconfigs[:6] if isinstance(m, dict)
            ],
            "_drilldown_hint": "Pass detail='compact', section='services'|'misconfigurations' for full IaC details.",
        }

    if tool_name == "portal_ai_registry":
        findings = data.get("guardrail_findings") or data.get("findings") or []
        return {
            "_detail": "summary",
            "summary": data.get("summary") or {},
            "models": (data.get("models") or [])[:8],
            "top_guardrail_findings": [
                {"severity": f.get("severity"), "rule": f.get("rule"), "path": f.get("path")}
                for f in findings[:6] if isinstance(f, dict)
            ],
            "_drilldown_hint": "Pass detail='compact' to inspect LLM SDK calls, prompts, and guardrails.",
        }

    if tool_name == "portal_call_chain":
        if "matches" in data:
            return {
                "_detail": "summary",
                "query": data.get("query", ""),
                "count": data.get("count", 0),
                "matches": [
                    {"id": m.get("id"), "signature": str(m.get("signature", ""))[:80], "callees_count": len(m.get("callees") or []), "db_tables": (m.get("db_tables") or [])[:4]}
                    for m in (data.get("matches") or [])[:8] if isinstance(m, dict)
                ],
                "_drilldown_hint": "Pass detail='compact' or detail='full' for full callees list.",
            }
        return {
            "_detail": "summary",
            "summary": data.get("summary") or {},
            "top_chains": [
                {
                    "entry": c.get("entry") or c.get("route") or c.get("id"),
                    "method": c.get("method"),
                    "steps_count": len(c.get("steps") or c.get("chain") or []),
                    "db_tables": (c.get("db_tables") or [])[:4],
                }
                if isinstance(c, dict) else c
                for c in (data.get("chains") or [])[:6]
            ],
            "_drilldown_hint": "Pass symbol='<name>' or detail='compact' to trace a specific symbol.",
        }

    if tool_name == "portal_deep_audit":
        dc = data.get("dead_code_symbols") or {}
        qt = data.get("quality_telemetry") or {}
        ms = data.get("migration_sre") or {}
        fh = data.get("frontend_hygiene") or {}
        sc = data.get("semantic_clones") or {}
        return {
            "_detail": "summary",
            "dead_code": dc.get("summary") or {},
            "quality_telemetry": qt.get("summary") or {},
            "migration_safety": (ms.get("migration_safety") or {}).get("by_severity") or {},
            "sre_score_pct": (ms.get("sre_resilience") or {}).get("score_pct"),
            "frontend_hygiene": fh.get("summary") or {},
            "semantic_clones": {"clone_groups": sc.get("clone_groups_count", 0), "duplicated_fns": sc.get("duplicated_functions_count", 0)},
            "_drilldown_hint": "Pass detail='compact', section='dead_code_symbols'|'quality_telemetry'|'migration_sre'|'frontend_hygiene'|'semantic_clones'.",
        }

    if tool_name == "portal_mission_control":
        return {
            "_detail": "summary",
            "kpis": data.get("kpis") or {},
            "subsystems": [
                {"id": s.get("id"), "status": s.get("status"), "metric": s.get("metric")}
                for s in (data.get("subsystems") or [])[:8] if isinstance(s, dict)
            ],
            "top_anomalies": [
                {"severity": a.get("severity"), "title": str(a.get("title", ""))[:80]}
                for a in (data.get("anomalies") or [])[:5] if isinstance(a, dict)
            ],
            "_drilldown_hint": "Pass detail='full' for full Mission Control bento payload.",
        }

    if tool_name == "portal_sarif_findings":
        findings = data.get("findings") or []
        return {
            "_detail": "summary",
            "summary": data.get("summary") or {},
            "top_findings": [
                {"tool": f.get("tool"), "severity": f.get("severity"), "rule_id": f.get("rule_id"), "path": f.get("path"), "line": f.get("line")}
                for f in findings[:8] if isinstance(f, dict)
            ],
            "_drilldown_hint": "Pass tool='semgrep'|'gitleaks'|'trivy'|'codeql', severity='HIGH', or detail='compact' for more.",
        }

    if tool_name == "portal_agent_instructions_audit":
        return {
            "_detail": "summary",
            "summary": data.get("summary") or {},
            "files": [
                {"path": f.get("path"), "tokens": f.get("estimated_tokens"), "bloat": f.get("bloat_level"), "dead_paths": f.get("dead_paths_count")}
                for f in (data.get("files") or [])[:8] if isinstance(f, dict)
            ],
            "sample_dead_paths": (data.get("dead_paths") or [])[:6],
            "contradictions": (data.get("contradictions") or [])[:3],
            "_drilldown_hint": "Pass detail='compact' or detail='full' for all dead paths, duplications, and suggestions.",
        }

    if tool_name == "portal_vertical_slice":
        slices = data.get("slices") or []
        return {
            "_detail": "summary",
            "summary": data.get("summary") or {},
            "matched_count": len(slices),
            "top_slices": [
                {
                    "id": s.get("id"),
                    "feature": s.get("feature"),
                    "confidence": s.get("confidence"),
                    "stores": len((s.get("layers") or {}).get("stores") or []),
                    "components": len((s.get("layers") or {}).get("components") or []),
                    "backend": ((s.get("layers") or {}).get("backend_route") or {}).get("file"),
                    "tables": (((s.get("layers") or {}).get("storage") or {}).get("db_tables") or [])[:3],
                }
                for s in slices[:6] if isinstance(s, dict)
            ],
            "top_stores": [
                {"name": st.get("name"), "loc": st.get("loc"), "god": st.get("is_god_store"), "api_calls": st.get("api_calls_count")}
                for st in (data.get("stores") or [])[:5] if isinstance(st, dict)
            ],
            "_drilldown_hint": "Pass query='<feature|route|store>', layer='frontend|api|backend|storage', or detail='compact' for full 6-layer chains.",
        }

    if tool_name == "portal_async_topology":
        kind = str(data.get("kind") or "all").lower()
        redis_items = [r for r in (data.get("redis_keys") or []) if isinstance(r, dict)]
        out_async: dict[str, Any] = {
            "_detail": "summary",
            "summary": data.get("summary") or {},
            "sample_tasks": [
                {"name": t.get("function") or t.get("name"), "queue": t.get("queue"), "producers": len(t.get("producers") or []), "retries": t.get("max_retries")}
                for t in (data.get("celery_tasks") or [])[:6] if isinstance(t, dict)
            ],
            "sample_beat": [
                {"name": b.get("name"), "schedule": b.get("schedule"), "queue": b.get("queue")}
                for b in (data.get("beat_schedules") or [])[:4] if isinstance(b, dict)
            ],
            "pubsub_channels": [
                {"channel": c.get("channel"), "pubs": len(c.get("publishers") or []), "subs": len(c.get("subscribers") or [])}
                for c in (data.get("pubsub_channels") or [])[:5] if isinstance(c, dict)
            ],
            "streams": [
                {"protocol": s.get("protocol"), "path": s.get("path"), "consumers": len(s.get("consumers") or [])}
                for s in ((data.get("ws_streams") or []) + (data.get("sse_streams") or []))[:5] if isinstance(s, dict)
            ],
            "_drilldown_hint": "Pass kind='celery'|'beat'|'redis'|'pubsub'|'ws'|'sse', query='<term>', or detail='compact' for details.",
        }
        if kind in ("all", "redis"):
            out_async["sample_redis_keys"] = [
                {"key": r.get("key_pattern") or r.get("key") or r.get("name"), "ttl": r.get("ttl"), "ops": (r.get("operations") or [])[:4]}
                for r in redis_items if str(r.get("kind", "")).lower() != "lock"
            ][:8]
            out_async["sample_redis_locks"] = [
                {"key": r.get("key_pattern") or r.get("key") or r.get("name"), "ttl": r.get("ttl"), "ops": (r.get("operations") or [])[:4]}
                for r in redis_items if str(r.get("kind", "")).lower() == "lock"
            ][:6]
        return out_async

    if tool_name == "portal_pr_context":
        changed = data.get("changed_files") or []
        stale_docs = data.get("stale_docs") or data.get("doc_drift") or []
        impacted_tests = data.get("impacted_tests") or []
        return {
            "_detail": "summary",
            "base": data.get("base", "main"),
            "changed_files_count": len(changed) if isinstance(changed, list) else 0,
            "sample_changed_files": changed[:12] if isinstance(changed, list) else [],
            "stale_docs_count": len(stale_docs) if isinstance(stale_docs, list) else 0,
            "sample_stale_docs": stale_docs[:6] if isinstance(stale_docs, list) else [],
            "impacted_tests_count": len(impacted_tests) if isinstance(impacted_tests, list) else 0,
            "sample_impacted_tests": impacted_tests[:8] if isinstance(impacted_tests, list) else [],
            "_drilldown_hint": "Pass detail='compact' or detail='full' for complete PR context.",
        }

    if tool_name == "portal_hub_runtime":
        units = data.get("units") or []
        return {
            "_detail": "summary",
            "generated_at": data.get("generated_at", ""),
            "systemd_available": data.get("systemd_available", False),
            "git_head": data.get("git_head") or {},
            "summary": data.get("summary") or {},
            "host": data.get("host") or {},
            "units_brief": [
                {"unit": u.get("unit"), "state": u.get("active_state"), "mem_mb": u.get("memory_mb")}
                for u in units[:12] if isinstance(u, dict)
            ],
            "_drilldown_hint": "Pass detail='compact' or detail='full' for all unit details and topology edges.",
        }

    if tool_name == "portal_hub_dataops":
        tsdb = data.get("timescaledb") or {}
        return {
            "_detail": "summary",
            "generated_at": data.get("generated_at", ""),
            "summary": data.get("summary") or {},
            "hypertables": [h.get("name") for h in (tsdb.get("hypertables") or [])[:12] if isinstance(h, dict)],
            "caggs": [c.get("name") for c in (tsdb.get("caggs") or [])[:12] if isinstance(c, dict)],
            "sample_feeds": [
                {"id": f.get("id"), "provider": f.get("provider")}
                for f in (data.get("feeds") or [])[:10] if isinstance(f, dict)
            ],
            "backup_status": (data.get("backup_321") or {}).get("pgbackrest", {}).get("status", "unknown"),
            "_drilldown_hint": "Pass detail='compact' or detail='full' for complete feeds, pipelines & 3-2-1 tiers.",
        }

    if tool_name == "portal_hub_quant_factory":
        return {
            "_detail": "summary",
            "generated_at": data.get("generated_at", ""),
            "summary": data.get("summary") or {},
            "swimlane": data.get("swimlane") or [],
            "p4_frozen_seal": {
                k: (data.get("p4_frozen_seal") or {}).get(k)
                for k in ("status", "files_count", "total_bytes")
            },
            "sample_adapters": [
                {"name": a.get("name") or a.get("id"), "family": a.get("family")}
                for a in (data.get("adapters") or [])[:10] if isinstance(a, dict)
            ],
            "_drilldown_hint": "Pass detail='compact' or detail='full' for full adapter catalog & registry.",
        }

    if tool_name == "portal_impact":
        d1 = data.get("d1") or data.get("direct") or []
        d2 = data.get("d2") or data.get("indirect") or []
        d3 = data.get("d3") or []
        return {
            "_detail": "summary",
            "target": data.get("target", ""),
            "matched": (data.get("matched") or [])[:5],
            "counts": {
                "d1": len(d1) if isinstance(d1, list) else 0,
                "d2": len(d2) if isinstance(d2, list) else 0,
                "d3": len(d3) if isinstance(d3, list) else 0,
                "total_impacted": data.get("total_impacted", 0),
            },
            "sample_d1": d1[:10] if isinstance(d1, list) else [],
            "sample_d2": d2[:8] if isinstance(d2, list) else [],
            "_drilldown_hint": "Pass detail='compact' or detail='full' for complete blast-radius tree.",
        }

    if tool_name == "portal_search":
        res_items = data.get("results") or []
        return {
            "_detail": "summary",
            "query": data.get("query", ""),
            "engine": data.get("engine", ""),
            "count": data.get("count", len(res_items) if isinstance(res_items, list) else 0),
            "results": [
                {
                    "name": r.get("name") or r.get("title") or "",
                    "category": r.get("category", ""),
                    "path": r.get("path", ""),
                }
                for r in (res_items[:12] if isinstance(res_items, list) else [])
                if isinstance(r, dict)
            ],
            "_drilldown_hint": "Pass detail='full' for full subtitles/snippets.",
        }

    if tool_name == "portal_process_flow":
        flows = data.get("flows") or []
        return {
            "_detail": "summary",
            "query": data.get("query", ""),
            "count": data.get("count", len(flows) if isinstance(flows, list) else 0),
            "flows": [
                {
                    "id": f.get("id", ""),
                    "name": f.get("name") or f.get("title") or "",
                    "steps_count": len(f.get("steps") or []),
                    "sample_steps": (f.get("steps") or [])[:4],
                }
                for f in (flows[:8] if isinstance(flows, list) else [])
                if isinstance(f, dict)
            ],
            "_drilldown_hint": "Pass detail='full' for full process flow traces.",
        }

    if tool_name == "portal_contract":
        kind = str(data.get("kind") or "schemas")
        base_out: dict[str, Any] = {
            "_detail": "summary",
            "kind": kind,
            "query": data.get("query", ""),
            "summary": data.get("summary") or {},
        }
        if kind == "schemas":
            base_out["top_pydantic_models"] = [
                {"name": m.get("name"), "file": m.get("file"), "fields": m.get("field_count")}
                for m in (data.get("pydantic_models") or [])[:6] if isinstance(m, dict)
            ]
            base_out["top_ts_types"] = [
                {"name": t.get("name"), "file": t.get("file"), "fields": t.get("field_count")}
                for t in (data.get("ts_types") or [])[:6] if isinstance(t, dict)
            ]
        elif kind == "drift":
            base_out["top_drift"] = [
                {
                    "pydantic": d.get("pydantic_model"),
                    "ts": d.get("ts_type"),
                    "missing_ts": (d.get("missing_in_ts") or [])[:4],
                    "missing_py": (d.get("missing_in_py") or [])[:4],
                    "mismatches": len(d.get("type_mismatches") or []),
                }
                for d in (data.get("schema_drift") or [])[:6] if isinstance(d, dict)
            ]
            base_out["sample_untyped_routes"] = [
                {"method": r.get("method"), "path": r.get("path"), "reason": r.get("reason")}
                for r in (data.get("untyped_routes") or [])[:5] if isinstance(r, dict)
            ]
        elif kind == "errors":
            err = data.get("error_taxonomy") or {}
            base_out["by_status_code"] = err.get("by_status_code") or {}
            base_out["sample_http_exceptions"] = [
                {"status": e.get("status_code"), "file": e.get("file"), "fn": e.get("function"), "detail": str(e.get("detail", ""))[:50]}
                for e in (err.get("http_exceptions") or [])[:6] if isinstance(e, dict)
            ]
            base_out["custom_exceptions"] = [
                {"name": c.get("name"), "file": c.get("file")}
                for c in (err.get("custom_exceptions") or [])[:6] if isinstance(c, dict)
            ]
        elif kind == "db_rw":
            base_out["top_tables"] = [
                {
                    "table": t.get("table"),
                    "readers": t.get("readers_count"),
                    "writers": t.get("writers_count"),
                    "migrations": t.get("migrations_count"),
                    "orphan": t.get("is_orphan"),
                }
                for t in (data.get("db_rw_matrix") or [])[:10] if isinstance(t, dict)
            ]
        elif kind == "proto":
            base_out["proto_contracts"] = [
                {
                    "file": p.get("file"),
                    "syntax": p.get("syntax"),
                    "package": p.get("package"),
                    "messages_count": p.get("messages_count", 0),
                    "enums_count": p.get("enums_count", 0),
                    "rpcs_count": p.get("rpcs_count", 0),
                    "messages": p.get("messages") or p.get("sample_messages") or [],
                    "enums": p.get("enums") or p.get("sample_enums") or [],
                }
                for p in (data.get("proto_contracts") or [])[:8] if isinstance(p, dict)
            ]
        elif kind == "runtime_modes":
            base_out["modes"] = [
                {
                    "mode": m.get("mode"),
                    "risk": m.get("risk_level"),
                    "detected": m.get("detected_in_code"),
                    "services": (m.get("required_services") or [])[:5],
                    "guards_active": m.get("active_guards_detected_count"),
                    "env_vars": len(m.get("controlling_env_vars") or []),
                }
                for m in (data.get("modes") or [])[:6] if isinstance(m, dict)
            ]
            base_out["top_feature_flags"] = [
                {"name": f.get("name"), "default": f.get("default")}
                for f in (data.get("feature_flags") or [])[:8] if isinstance(f, dict)
            ]
        base_out["_drilldown_hint"] = "Pass kind='schemas'|'drift'|'errors'|'db_rw'|'runtime_modes', query='<term>', or detail='compact' for details."
        return base_out

    # Generic summary fallback
    out: dict[str, Any] = {"_detail": "summary"}
    for k, v in data.items():
        if isinstance(v, list):
            out[f"{k}_count"] = len(v)
            out[k] = v[:5]
        elif isinstance(v, dict) and len(v) > 15:
            out[f"{k}_keys_count"] = len(v)
        else:
            out[k] = v
    out["_drilldown_hint"] = "Pass detail='compact' or detail='full' for complete data."
    return out


# ── Deterministic PageRank (15 LOC, Aider RepoMap inspired) ──────────────────

def compute_pagerank(adj: dict[str, set[str]], iterations: int = 12, damping: float = 0.85) -> dict[str, float]:
    """Deterministic 15-LOC PageRank over module dependency graph."""
    nodes = sorted(set(adj.keys()) | {t for targets in adj.values() for t in targets})
    n = len(nodes)
    if n == 0:
        return {}
    ranks: dict[str, float] = {u: 1.0 / n for u in nodes}
    in_edges: dict[str, list[str]] = defaultdict(list)
    out_deg: dict[str, int] = {}
    for u, targets in adj.items():
        out_deg[u] = len(targets)
        for v in targets:
            in_edges[v].append(u)
    base = (1.0 - damping) / n
    for _ in range(iterations):
        nxt: dict[str, float] = {}
        for v in nodes:
            s = sum(ranks[u] / out_deg[u] for u in in_edges.get(v, ()) if out_deg.get(u, 0) > 0)
            nxt[v] = base + damping * s
        ranks = nxt
    return ranks


def _tokenize(text: str) -> list[str]:
    raw = re.findall(r"[a-zA-Z0-9_]{2,}", (text or "").lower())
    tokens: list[str] = []
    for tok in raw:
        parts = [p for p in tok.split("_") if len(p) >= 2 and p not in _STOPWORDS]
        tokens.extend(parts)
        if tok not in _STOPWORDS and tok not in parts:
            tokens.append(tok)
    return tokens


def _load_or_generate(engine: Any, filename: str, generator_fn: Any) -> dict[str, Any]:
    fpath = engine.data_dir / filename
    if fpath.is_file():
        try:
            loaded = json.loads(fpath.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                return loaded
        except Exception:
            pass
    return generator_fn(engine.project_dir, engine.data_dir)


def slice_for_task(
    engine: Any,
    task: str,
    max_tokens: int = 2000,
    focus_paths: list[str] | None = None,
    module_cards_gen: Any = None,
    test_oracle_gen: Any = None,
) -> dict[str, Any]:
    """Deterministic BM25-lite + PageRank + Active-ADR + 1-hop + Greedy Token-Budget Slicer."""
    budget = max(400, min(int(max_tokens or 2000), 12000))
    focus = [str(p).replace("\\", "/").strip() for p in (focus_paths or []) if str(p).strip()]

    cards_data = _load_or_generate(engine, "module-cards.json", module_cards_gen) if module_cards_gen else (engine._load_json("module-cards.json") or {})
    oracle_data = _load_or_generate(engine, "test-oracle.json", test_oracle_gen) if test_oracle_gen else (engine._load_json("test-oracle.json") or {})
    raw_cards = cards_data.get("cards") if isinstance(cards_data, dict) else None
    cards: dict[str, dict[str, Any]] = raw_cards if isinstance(raw_cards, dict) else {}

    # Build dependency graph & PageRank (+ cross-stack edges from vertical-slices.json)
    graph = engine._load_json("graph.json") or {}
    vs_data = engine._load_json("vertical-slices.json") or {}
    async_data = engine._load_json("async-topology.json") or {}
    adj: dict[str, set[str]] = defaultdict(set)
    rev_adj: dict[str, set[str]] = defaultdict(set)
    for e in (graph.get("edges") or graph.get("links") or []) if isinstance(graph, dict) else []:
        if isinstance(e, dict) and e.get("source") and e.get("target"):
            s = str(e["source"]).replace("\\", "/")
            t = str(e["target"]).replace("\\", "/")
            if s != t:
                adj[s].add(t)
                rev_adj[t].add(s)
    for e in (vs_data.get("cross_stack_edges") or []) if isinstance(vs_data, dict) else []:
        if isinstance(e, dict) and e.get("source") and e.get("target"):
            s = str(e["source"]).replace("\\", "/")
            t = str(e["target"]).replace("\\", "/")
            if s != t:
                adj[s].add(t)
                rev_adj[t].add(s)
    pr = compute_pagerank(adj)
    max_pr = max(pr.values()) if pr else 1.0

    # BM25-lite scoring over module cards
    q_tokens = _tokenize(task)
    q_bigrams = [f"{q_tokens[i]}_{q_tokens[i + 1]}" for i in range(len(q_tokens) - 1)]
    df: Counter[str] = Counter()
    doc_blobs: dict[str, str] = {}
    for path, card in cards.items():
        blob = " ".join([
            path,
            str(card.get("role", "")),
            str(card.get("purpose", "")),
            " ".join(card.get("exports") or []),
            " ".join(card.get("routes") or []),
            " ".join(card.get("tables_touched") or []),
        ]).lower()
        doc_blobs[path] = blob
        seen_t = set(_tokenize(blob))
        for t in q_tokens:
            if t in seen_t:
                df[t] += 1

    n_docs = max(1, len(cards))
    scored: list[tuple[float, str]] = []
    for path, blob in doc_blobs.items():
        score = 0.0
        for fp in focus:
            if fp.lower() in path.lower():
                score += 12.0
        for t in q_tokens:
            if t in blob:
                idf = math.log(1.0 + (n_docs - df[t] + 0.5) / (df[t] + 0.5))
                tf = blob.count(t)
                score += idf * (1.0 + math.log(1.0 + tf))
                if t in path.lower():
                    score += 1.5
        for bg in q_bigrams:
            if bg in blob:
                score += 2.0
        if score > 0 or focus:
            pr_norm = (pr.get(path, 0.0) / max_pr) if max_pr > 0 else 0.0
            score += pr_norm * 2.5
            scored.append((round(score, 3), path))

    scored.sort(key=lambda x: (-x[0], x[1]))

    # 1-hop neighbor boost for top 3 seeds
    top_seeds = [p for _, p in scored[:3]]
    neighbors_1hop: list[str] = []
    for seed in top_seeds:
        for nb in sorted(adj.get(seed, set()) | rev_adj.get(seed, set())):
            if nb in cards and nb not in top_seeds and nb not in neighbors_1hop:
                neighbors_1hop.append(nb)
            if len(neighbors_1hop) >= 6:
                break

    # Active ADR filter (exclude SUPERSEDED / DEPRECATED)
    adr_raw = engine._load_json("adr-graph.json") or {}
    active_adrs: list[dict[str, str]] = []
    for n in (adr_raw.get("nodes") or []) if isinstance(adr_raw, dict) else []:
        if not isinstance(n, dict):
            continue
        st = str(n.get("status") or "").strip().upper()
        if st in ("SUPERSEDED", "DEPRECATED"):
            continue
        adr_blob = f"{n.get('id', '')} {n.get('title', '')} {n.get('domain', '')}".lower()
        if any(t in adr_blob for t in q_tokens):
            active_adrs.append({
                "id": str(n.get("id", "")),
                "title": str(n.get("title", ""))[:75],
                "status": str(n.get("status", "Accepted")),
            })
            if len(active_adrs) >= 4:
                break

    # Match top vertical slices & async hooks relevant to the task
    matched_slices: list[dict[str, Any]] = []
    for sl in (vs_data.get("slices") or []) if isinstance(vs_data, dict) else []:
        if not isinstance(sl, dict):
            continue
        sl_blob = f"{sl.get('id', '')} {sl.get('feature', '')} {((sl.get('layers') or {}).get('backend_route') or {}).get('file', '')}".lower()
        if any(t in sl_blob for t in q_tokens) or any(fp.lower() in sl_blob for fp in focus):
            matched_slices.append({
                "id": sl.get("id"),
                "backend": ((sl.get("layers") or {}).get("backend_route") or {}).get("file"),
                "stores": ((sl.get("layers") or {}).get("stores") or [])[:2],
                "tables": (((sl.get("layers") or {}).get("storage") or {}).get("db_tables") or [])[:3],
            })
            if len(matched_slices) >= 3:
                break

    matched_async: list[dict[str, Any]] = []
    if isinstance(async_data, dict):
        for t_item in (async_data.get("celery_tasks") or []):
            if not isinstance(t_item, dict):
                continue
            tb = f"{t_item.get('name', '')} {t_item.get('function', '')} {t_item.get('queue', '')} {t_item.get('file', '')}".lower()
            if any(t in tb for t in q_tokens):
                matched_async.append({"kind": "celery_task", "name": t_item.get("function") or t_item.get("name"), "queue": t_item.get("queue")})
                if len(matched_async) >= 3:
                    break
        for ps in (async_data.get("pubsub_channels") or []):
            if not isinstance(ps, dict):
                continue
            if any(t in str(ps.get("channel", "")).lower() for t in q_tokens):
                matched_async.append({"kind": "pubsub", "channel": ps.get("channel")})
                if len(matched_async) >= 5:
                    break

    # Match relevant data contracts (schema drift & DB R/W)
    dc_data = engine._load_json("data-contracts.json") or {}
    matched_contracts: list[dict[str, Any]] = []
    if isinstance(dc_data, dict):
        for dr in (dc_data.get("schema_drift") or []):
            if not isinstance(dr, dict):
                continue
            dr_blob = f"{dr.get('pydantic_model', '')} {dr.get('pydantic_file', '')} {dr.get('ts_type', '')} {dr.get('ts_file', '')}".lower()
            if any(t in dr_blob for t in q_tokens) or any(fp.lower() in dr_blob for fp in focus):
                matched_contracts.append({
                    "kind": "schema_drift",
                    "pydantic": dr.get("pydantic_model"),
                    "ts": dr.get("ts_type"),
                    "missing_in_ts": (dr.get("missing_in_ts") or [])[:3],
                })
                if len(matched_contracts) >= 3:
                    break
        for tbl in (dc_data.get("db_rw_matrix") or []):
            if not isinstance(tbl, dict):
                continue
            t_blob = f"{tbl.get('table', '')} {' '.join(tbl.get('readers') or [])} {' '.join(tbl.get('writers') or [])}".lower()
            if any(t in t_blob for t in q_tokens) or any(fp.lower() in t_blob for fp in focus):
                matched_contracts.append({
                    "kind": "db_rw",
                    "table": tbl.get("table"),
                    "readers": tbl.get("readers_count"),
                    "writers": tbl.get("writers_count"),
                })
                if len(matched_contracts) >= 5:
                    break

    # Greedy Token-Budget Packing
    s2t = oracle_data.get("source_to_tests") if isinstance(oracle_data, dict) else {}
    packed_cards: list[dict[str, Any]] = []
    fast_tests: list[str] = []
    risk_flags: list[str] = []
    truncated_count = 0

    result: dict[str, Any] = {
        "task": task,
        "budget_limit_tokens": budget,
        "budget_used_tokens": 0,
        "active_adrs": active_adrs,
        "vertical_slices": matched_slices,
        "async_hooks": matched_async,
        "data_contracts": matched_contracts,
        "selected_modules": packed_cards,
        "neighbors_1hop": neighbors_1hop[:5],
        "fast_tests": fast_tests,
        "risk_flags": risk_flags,
        "invariants": ["P4_FROZEN_GATE", "NO_UI_TO_DB", "ZERO_CIRCULAR_DEPS", "AUTH_ON_MUTATING_API"],
        "truncated_candidates_count": 0,
    }

    for score, path in scored[:40]:
        entry = {"path": path, "score": score, **cards[path]}
        packed_cards.append(entry)
        for t_item in (s2t.get(path) or []) if isinstance(s2t, dict) else []:
            t_path = str(t_item.get("test", "")) if isinstance(t_item, dict) else ""
            if t_path and t_path not in fast_tests and len(fast_tests) < 5:
                fast_tests.append(t_path)
        for rf in cards[path].get("risk_flags") or []:
            tag = f"{Path(path).name}:{rf}"
            if tag not in risk_flags and len(risk_flags) < 6:
                risk_flags.append(tag)
        if estimate_tokens(result) > budget:
            packed_cards.pop()
            truncated_count += 1
            if len(packed_cards) >= 1:
                break

    result["truncated_candidates_count"] = truncated_count + max(0, len(scored) - 40)
    result["budget_used_tokens"] = estimate_tokens(result)
    if result["budget_used_tokens"] > budget:
        result = _truncate_to_token_cap(result, cap=budget)
        result["budget_used_tokens"] = estimate_tokens(result)
    return result


# ── Diff & AI Slop / Cheat Guard + Change Risk Score ─────────────────────────

def _load_known_packages(data_dir: Path) -> set[str]:
    pkgs: set[str] = set()
    for fname in ("stack-ecosystem.json", "stack-inventory.json"):
        f = data_dir / fname
        if f.is_file():
            try:
                raw = json.loads(f.read_text(encoding="utf-8"))
                for item in raw.get("items") or raw.get("dependencies") or raw.get("packages") or []:
                    if isinstance(item, dict) and item.get("name"):
                        n = str(item["name"]).lower().replace("-", "_")
                        pkgs.add(n)
                        pkgs.add(n.split("[", 1)[0])
            except Exception:
                pass
    return pkgs


def ai_slop_and_cheat_guard(project_dir: Path, files: list[str], base: str, data_dir: Path) -> list[dict[str, Any]]:
    """Detect phantom imports, sync I/O in async def, removed asserts, and noqa/type:ignore spam."""
    alerts: list[dict[str, Any]] = []
    known_pkgs = _load_known_packages(data_dir)
    # Local top-level packages in repo
    local_tops = {
        p.name for p in project_dir.iterdir()
        if p.is_dir() and not p.name.startswith(".")
    } | {"app", "backend", "frontend", "scripts", "tests", "knowledge_portal", "src"}

    for rel in files[:25]:
        norm = rel.replace("\\", "/").lstrip("./")
        if "frozen/" in norm.lower():
            continue
        fpath = project_dir / norm
        if not fpath.is_file() or fpath.suffix.lower() != ".py":
            continue
        try:
            text = fpath.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        # 1. noqa / type: ignore spam
        noqa_cnt = len(re.findall(r"#\s*(?:noqa|type:\s*ignore)", text))
        if noqa_cnt >= 6:
            alerts.append({"rule": "SUPPRESSION_SPAM", "severity": "WARN", "path": norm, "detail": f"{noqa_cnt} `# noqa`/`# type: ignore` suppressions"})

        # 2. AST checks: phantom imports + sync I/O in async def
        try:
            tree = ast.parse(text, filename=norm)
        except SyntaxError:
            alerts.append({"rule": "SYNTAX_ERROR", "severity": "BLOCK", "path": norm, "detail": "Python syntax error"})
            continue

        for node in ast.walk(tree):
            if known_pkgs and isinstance(node, (ast.Import, ast.ImportFrom)):
                if isinstance(node, ast.Import):
                    mods = [a.name.split(".")[0] for a in node.names]
                else:
                    mods = [] if node.level > 0 or not node.module else [node.module.split(".")[0]]
                for mod in mods:
                    m_low = mod.lower()
                    if m_low in _STDLIB_MODULES or m_low in local_tops or m_low in known_pkgs:
                        continue
                    # Common pip distribution → import alias mapping (QA-5)
                    _PIP_IMPORT_ALIASES: dict[str, tuple[str, ...]] = {
                        "jose": ("python_jose", "jose"),
                        "yaml": ("pyyaml", "yaml"),
                        "dotenv": ("python_dotenv", "dotenv"),
                        "cv2": ("opencv_python", "opencv_python_headless", "cv2"),
                        "pil": ("pillow", "pil"),
                        "bs4": ("beautifulsoup4", "bs4"),
                        "sklearn": ("scikit_learn", "sklearn"),
                        "dateutil": ("python_dateutil", "dateutil"),
                        "jwt": ("pyjwt", "python_jose", "jwt"),
                        "psycopg2": ("psycopg2_binary", "psycopg2"),
                        "psycopg": ("psycopg_binary", "psycopg"),
                        "multipart": ("python_multipart", "multipart"),
                        "git": ("gitpython", "git"),
                        "websocket": ("websocket_client", "websocket"),
                        "attr": ("attrs", "attr"),
                        "google": ("google_genai", "google_generativeai", "google_auth", "protobuf"),
                        "nautilus_trader": ("nautilus_trader",),
                        "pydantic_settings": ("pydantic_settings",),
                        "starlette": ("starlette", "fastapi"),
                    }
                    if m_low in _PIP_IMPORT_ALIASES:
                        continue
                    alerts.append({
                        "rule": "PHANTOM_IMPORT",
                        "severity": "WARN",
                        "path": norm,
                        "detail": f"Import `{mod}` not found in stdlib, local packages, or stack inventory.",
                    })
                    break
            elif isinstance(node, ast.AsyncFunctionDef):
                for sub in ast.walk(node):
                    if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute):
                        if sub.func.attr in _SYNC_IO_FUNCS and isinstance(sub.func.value, ast.Name) and sub.func.value.id in _SYNC_IO_MODS:
                            alerts.append({
                                "rule": "SYNC_IO_IN_ASYNC",
                                "severity": "WARN",
                                "path": norm,
                                "detail": f"Blocking `{sub.func.value.id}.{sub.func.attr}()` inside `async def {node.name}`",
                            })
                            break

    # 3. Check git diff for removed asserts
    try:
        proc = subprocess.run(
            ["git", "diff", "-U0", base, "--", *files[:15]] if files else ["git", "diff", "-U0", base],
            cwd=str(project_dir),
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if proc.returncode == 0:
            removed_asserts = sum(1 for ln in proc.stdout.splitlines() if ln.startswith("-") and not ln.startswith("---") and re.match(r"-\s*assert\b", ln))
            if removed_asserts > 0:
                alerts.append({
                    "rule": "ASSERT_REMOVAL",
                    "severity": "WARN",
                    "path": "git_diff",
                    "detail": f"{removed_asserts} `assert` statement(s) removed in diff against `{base}`.",
                })
    except Exception:
        pass

    return alerts[:20]


def check_diff(
    engine: Any,
    files: list[str] | None = None,
    base: str = "HEAD",
    max_tokens: int = 1500,
    test_oracle_gen: Any = None,
) -> dict[str, Any]:
    """Pre-commit / pre-PR diff guard with AI slop/cheat guard, Change Risk Score, and exact tests."""
    budget = max(400, min(int(max_tokens or 1500), 6000))
    target_files = [str(f).replace("\\", "/").lstrip("./") for f in (files or []) if str(f).strip()]

    if not target_files:
        try:
            proc = subprocess.run(
                ["git", "diff", "--name-only", base],
                cwd=str(engine.project_dir),
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            if proc.returncode == 0:
                target_files = [ln.strip().replace("\\", "/") for ln in proc.stdout.splitlines() if ln.strip()]
        except Exception:
            target_files = []

    violations: list[dict[str, str]] = []
    blast_d1_total = 0
    for f in target_files[:20]:
        if "frozen/" in f.lower() or f.lower().startswith("frozen/"):
            violations.append({"rule": "P4_FROZEN_GATE", "path": f, "detail": "Modification inside frozen/ is strictly forbidden."})
            continue
        imp = engine.impact(f, max_depth=1)
        blast_d1_total += int((imp.get("counts") or {}).get("d1", 0))

    slop_alerts = ai_slop_and_cheat_guard(engine.project_dir, target_files, base, engine.data_dir)
    oracle_res = query_test_oracle(engine, files=target_files, max_tests=6, include_slow=False, test_oracle_gen=test_oracle_gen)

    # Check data-contracts.json for Pydantic<->TS drift on touched files
    contract_alerts: list[dict[str, Any]] = []
    dc_data = engine._load_json("data-contracts.json") or {}
    if isinstance(dc_data, dict) and target_files:
        norm_targets = {f.lower() for f in target_files}
        for dr in (dc_data.get("schema_drift") or []):
            if not isinstance(dr, dict):
                continue
            pf = str(dr.get("pydantic_file", "")).lower()
            tf = str(dr.get("ts_file", "")).lower()
            if pf in norm_targets or tf in norm_targets:
                contract_alerts.append({
                    "rule": "SCHEMA_DRIFT",
                    "severity": "WARN",
                    "pydantic_model": dr.get("pydantic_model"),
                    "ts_type": dr.get("ts_type"),
                    "missing_in_ts": (dr.get("missing_in_ts") or [])[:4],
                })
                if len(contract_alerts) >= 6:
                    break

    # Change Risk Score: churn x complexity x blast_radius (normalized 0-100)
    churn_factor = min(3.0, 1.0 + len(target_files) * 0.25)
    loc_sum = 0
    for f in target_files[:15]:
        p = engine.project_dir / f
        if p.is_file():
            try:
                loc_sum += sum(1 for _ in p.open("r", encoding="utf-8", errors="ignore"))
            except OSError:
                pass
    complexity_factor = min(3.5, 1.0 + (loc_sum / 500.0))
    blast_factor = min(4.0, 1.0 + blast_d1_total * 0.3)
    risk_score = min(100, round(churn_factor * complexity_factor * blast_factor * 4.5)) if target_files else 0

    has_block = bool(violations) or any(a.get("severity") == "BLOCK" for a in slop_alerts)
    status = "BLOCK" if has_block else ("WARN" if (slop_alerts or contract_alerts or risk_score >= 45) else "PASS")

    payload: dict[str, Any] = {
        "status": status,
        "base": base,
        "files_checked": target_files[:20],
        "change_risk_score": risk_score,
        "blast_radius_d1": blast_d1_total,
        "violations": violations,
        "slop_and_cheat_alerts": slop_alerts,
        "contract_alerts": contract_alerts,
        "recommended_tests": oracle_res.get("tests") or [],
        "test_command": oracle_res.get("command", ""),
    }
    return _truncate_to_token_cap(payload, cap=budget)


def build_handoff_pack(
    engine: Any,
    task: str = "",
    files: list[str] | None = None,
    max_tokens: int = 1500,
    test_oracle_gen: Any = None,
) -> dict[str, Any]:
    """Generate a portable, verifiable cross-agent handoff snapshot (<= 1500 tok)."""
    budget = max(400, min(int(max_tokens or 1500), 4000))
    diff_res = check_diff(engine, files=files, base="HEAD", max_tokens=budget // 2, test_oracle_gen=test_oracle_gen)
    health = engine.health_audit()
    h_sum = (health.get("summary") or {}) if isinstance(health, dict) else {}

    branch = ""
    head_sha = ""
    try:
        b = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=str(engine.project_dir), capture_output=True, text=True, timeout=3, check=False)
        h = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=str(engine.project_dir), capture_output=True, text=True, timeout=3, check=False)
        branch = b.stdout.strip() if b.returncode == 0 else ""
        head_sha = h.stdout.strip() if h.returncode == 0 else ""
    except Exception:
        pass

    payload: dict[str, Any] = {
        "schema_version": "1.0",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "task": task or "Current workspace handoff",
        "git": {"branch": branch, "head": head_sha},
        "files_touched": diff_res.get("files_checked") or [],
        "diff_status": diff_res.get("status", "PASS"),
        "change_risk_score": diff_res.get("change_risk_score", 0),
        "health_snapshot": {"score": h_sum.get("health_score"), "grade": h_sum.get("grade"), "cycles": h_sum.get("cycle_count", 0)},
        "active_invariants": ["P4_FROZEN_GATE", "NO_UI_TO_DB", "ZERO_CIRCULAR_DEPS", "AUTH_ON_MUTATING_API"],
        "verification_command": diff_res.get("test_command") or "pytest -q",
        "slop_alerts": (diff_res.get("slop_and_cheat_alerts") or [])[:5],
        "next_steps": [
            "Review files_touched and active_invariants before editing.",
            f"Run `{diff_res.get('test_command') or 'pytest -q'}` after changes.",
        ],
    }
    payload = _truncate_to_token_cap(payload, cap=budget)
    payload["estimated_tokens"] = estimate_tokens(payload)
    return payload


def query_test_oracle(
    engine: Any,
    files: list[str] | None = None,
    symbols: list[str] | None = None,
    max_tests: int = 8,
    include_slow: bool = False,
    test_oracle_gen: Any = None,
) -> dict[str, Any]:
    """Select 3-8 fastest pertinent tests and ready-to-run command in <= 500 tokens."""
    cap = max(1, min(int(max_tests or 8), 15))
    oracle = _load_or_generate(engine, "test-oracle.json", test_oracle_gen) if test_oracle_gen else (engine._load_json("test-oracle.json") or {})
    s2t: dict[str, list[dict[str, Any]]] = oracle.get("source_to_tests") or {}
    sym2t: dict[str, list[str]] = oracle.get("symbol_to_tests") or {}
    raw_tests_meta = oracle.get("tests")
    tests_meta: dict[str, dict[str, Any]] = raw_tests_meta if isinstance(raw_tests_meta, dict) else {}

    selected: dict[str, dict[str, Any]] = {}
    blind_spots: list[str] = []

    for raw_f in files or []:
        f = str(raw_f).replace("\\", "/").lstrip("./")
        if not f:
            continue
        matches = s2t.get(f)
        if not matches:
            # suffix match
            for k, v in s2t.items():
                if k.endswith(f) or f.endswith(k):
                    matches = v
                    break
        if not matches:
            blind_spots.append(f)
            continue
        for m in matches:
            tier = str(m.get("tier", "fast"))
            if not include_slow and tier == "slow":
                continue
            tpath = str(m.get("test", ""))
            if tpath and tpath not in selected:
                selected[tpath] = m

    for sym in symbols or []:
        s = str(sym).strip()
        if not s:
            continue
        for tpath in sym2t.get(s) or []:
            meta = tests_meta.get(tpath) or {}
            tier = str(meta.get("tier", "fast"))
            if not include_slow and tier == "slow":
                continue
            if tpath not in selected:
                selected[tpath] = {
                    "test": tpath,
                    "confidence": "symbol_patch",
                    "tier": tier,
                    "runtime_ms": meta.get("runtime_ms", 200),
                    "fixtures": (meta.get("fixtures") or [])[:4],
                }

    ordered = sorted(
        selected.values(),
        key=lambda x: ({"fast": 0, "medium": 1, "slow": 2}.get(str(x.get("tier", "fast")), 9), int(x.get("runtime_ms", 200)), str(x.get("test", ""))),
    )[:cap]

    py_tests = [str(x["test"]) for x in ordered if str(x.get("test", "")).endswith(".py")]
    js_tests = [str(x["test"]) for x in ordered if not str(x.get("test", "")).endswith(".py")]
    cmds: list[str] = []
    if py_tests:
        cmds.append("pytest -q " + " ".join(py_tests))
    if js_tests:
        cmds.append("npx vitest run " + " ".join(js_tests))

    fixtures = sorted({fx for x in ordered for fx in (x.get("fixtures") or [])})[:8]

    return _truncate_to_token_cap({
        "summary": oracle.get("summary") or {},
        "matched_count": len(ordered),
        "tests": ordered,
        "command": " && ".join(cmds),
        "fixtures_required": fixtures,
        "blind_spot": bool(blind_spots and not ordered),
        "blind_spot_files": blind_spots[:8],
    }, cap=500)


# ── Vertical Slice & Async Topology Query Helpers (Wave 2) ──────────────────

def query_vertical_slice(
    engine: Any,
    query: str = "",
    layer: str = "all",
    detail: str = "summary",
    vertical_slices_gen: Any = None,
) -> dict[str, Any]:
    """Query cross-stack 6-layer vertical slices with strict detail budget."""
    data = (
        _load_or_generate(engine, "vertical-slices.json", vertical_slices_gen)
        if vertical_slices_gen
        else (engine._load_json("vertical-slices.json") or {})
    )
    if not isinstance(data, dict):
        data = {}

    q = (query or "").strip().lower()
    lyr = (layer or "all").strip().lower()
    allowed_layers = ("all", "frontend", "api", "backend", "storage")
    if lyr not in allowed_layers:
        return {
            "ok": False,
            "error": "invalid_layer",
            "layer": layer,
            "allowed": list(allowed_layers),
        }
    slices = list(data.get("slices") or [])
    stores = list(data.get("stores") or [])

    if q:
        filtered: list[dict[str, Any]] = []
        for s in slices:
            if not isinstance(s, dict):
                continue
            layers = s.get("layers") or {}
            blob = " ".join([
                str(s.get("id", "")),
                str(s.get("feature", "")),
                str(s.get("endpoint", "")),
                " ".join(str(x) for x in (layers.get("components") or [])),
                " ".join(str(x) for x in (layers.get("stores") or [])),
                " ".join(str(x) for x in (layers.get("api_clients") or [])),
                str((layers.get("backend_route") or {}).get("file", "")),
                str((layers.get("backend_route") or {}).get("handler", "")),
                " ".join(str(x) for x in ((layers.get("services_and_tasks") or {}).get("celery_tasks") or [])),
                " ".join(str(x) for x in ((layers.get("storage") or {}).get("db_tables") or [])),
            ]).lower()
            if q in blob:
                filtered.append(s)
        slices = filtered
        stores = [
            st for st in stores
            if isinstance(st, dict) and q in f"{st.get('name', '')} {st.get('id', '')} {st.get('file', '')}".lower()
        ]

    if lyr != "all":
        projected: list[dict[str, Any]] = []
        for s in slices:
            layers = s.get("layers") or {}
            if lyr == "frontend":
                sub = {"components": layers.get("components"), "stores": layers.get("stores"), "api_clients": layers.get("api_clients")}
            elif lyr == "api":
                sub = {"api_clients": layers.get("api_clients"), "backend_route": layers.get("backend_route")}
            elif lyr == "backend":
                sub = {"backend_route": layers.get("backend_route"), "services_and_tasks": layers.get("services_and_tasks")}
            elif lyr == "storage":
                sub = {"storage": layers.get("storage")}
            else:
                sub = layers
            projected.append({**s, "layers": sub})
        slices = projected

    scoped = {**data, "slices": slices, "stores": stores, "query": query, "layer": lyr}
    res = apply_detail_budget("portal_vertical_slice", scoped, detail=detail)
    if (detail or "summary").strip().lower() == "summary":
        res = _truncate_to_token_cap(res, cap=800)
    return res


def query_async_topology(
    engine: Any,
    kind: str = "all",
    query: str = "",
    detail: str = "summary",
    async_topology_gen: Any = None,
) -> dict[str, Any]:
    """Query Celery tasks, Beat schedules, Redis keys/locks, Pub/Sub & WS/SSE topology."""
    data = (
        _load_or_generate(engine, "async-topology.json", async_topology_gen)
        if async_topology_gen
        else (engine._load_json("async-topology.json") or {})
    )
    if not isinstance(data, dict):
        data = {}

    k = (kind or "all").strip().lower()
    allowed_kinds = ("all", "celery", "beat", "redis", "pubsub", "ws", "sse")
    if k not in allowed_kinds:
        return {
            "ok": False,
            "error": "invalid_kind",
            "kind": kind,
            "allowed": list(allowed_kinds),
        }
    q = (query or "").strip().lower()

    def _matches(item: Any) -> bool:
        if not q:
            return True
        return q in json.dumps(item, ensure_ascii=False).lower()

    scoped: dict[str, Any] = {
        "schema_version": data.get("schema_version", "1.0"),
        "generated_at": data.get("generated_at", ""),
        "summary": data.get("summary") or {},
        "kind": k,
        "query": query,
    }
    section_map = {
        "celery": "celery_tasks",
        "beat": "beat_schedules",
        "redis": "redis_keys",
        "pubsub": "pubsub_channels",
        "ws": "ws_streams",
        "sse": "sse_streams",
    }
    if k in section_map:
        key = section_map[k]
        scoped[key] = [x for x in (data.get(key) or []) if _matches(x)]
    else:
        for key in section_map.values():
            scoped[key] = [x for x in (data.get(key) or []) if _matches(x)]
        if (detail or "summary").strip().lower() == "full":
            scoped["graph"] = data.get("graph") or {"nodes": [], "edges": []}
            scoped["frontend_consumers"] = data.get("frontend_consumers") or {}

    res = apply_detail_budget("portal_async_topology", scoped, detail=detail)
    if (detail or "summary").strip().lower() == "summary":
        res = _truncate_to_token_cap(res, cap=700)
    return res



def query_contract(
    engine: Any,
    kind: str = "schemas",
    query: str = "",
    detail: str = "summary",
    data_contracts_gen: Any = None,
    runtime_modes_gen: Any = None,
) -> dict[str, Any]:
    """Query Pydantic<->TS schemas, drift, error taxonomy, DB R/W matrix, or runtime modes."""
    k = (kind or "schemas").strip().lower()
    valid_kinds = ("schemas", "drift", "errors", "db_rw", "runtime_modes", "proto")
    if k not in valid_kinds:
        return {
            "ok": False,
            "error": "invalid_kind",
            "kind": k,
            "allowed_kinds": list(valid_kinds),
        }

    q = (query or "").strip().lower()

    def _matches(item: Any) -> bool:
        if not q:
            return True
        return q in json.dumps(item, ensure_ascii=False).lower()

    if k == "runtime_modes":
        data = (
            _load_or_generate(engine, "runtime-modes.json", runtime_modes_gen)
            if runtime_modes_gen
            else (engine._load_json("runtime-modes.json") or {})
        )
        if not isinstance(data, dict):
            data = {}
        scoped: dict[str, Any] = {
            "schema_version": data.get("schema_version", "1.0"),
            "generated_at": data.get("generated_at", ""),
            "kind": k,
            "query": query,
            "summary": data.get("summary") or {},
            "modes": [m for m in (data.get("modes") or []) if _matches(m)],
            "feature_flags": [f for f in (data.get("feature_flags") or []) if _matches(f)],
        }
    else:
        data = (
            _load_or_generate(engine, "data-contracts.json", data_contracts_gen)
            if data_contracts_gen
            else (engine._load_json("data-contracts.json") or {})
        )
        if not isinstance(data, dict):
            data = {}
        scoped = {
            "schema_version": data.get("schema_version", "1.0"),
            "generated_at": data.get("generated_at", ""),
            "kind": k,
            "query": query,
            "summary": data.get("summary") or {},
        }
        if k == "schemas":
            scoped["pydantic_models"] = [m for m in (data.get("pydantic_models") or []) if _matches(m)]
            scoped["ts_types"] = [t for t in (data.get("ts_types") or []) if _matches(t)]
            scoped["matched_schemas"] = [p for p in (data.get("matched_schemas") or []) if _matches(p)]
        elif k == "drift":
            scoped["schema_drift"] = [d for d in (data.get("schema_drift") or []) if _matches(d)]
            scoped["untyped_routes"] = [r for r in (data.get("untyped_routes") or []) if _matches(r)]
        elif k == "errors":
            err = data.get("error_taxonomy") or {}
            scoped["error_taxonomy"] = {
                "by_status_code": err.get("by_status_code") or {},
                "http_exceptions": [e for e in (err.get("http_exceptions") or []) if _matches(e)],
                "custom_exceptions": [c for c in (err.get("custom_exceptions") or []) if _matches(c)],
                "frontend_handlers": [h for h in (err.get("frontend_handlers") or []) if _matches(h)],
            }
        elif k == "db_rw":
            scoped["db_rw_matrix"] = [r for r in (data.get("db_rw_matrix") or []) if _matches(r)]
        elif k == "proto":
            protos = data.get("proto_contracts") or []
            filtered_protos: list[dict[str, Any]] = []
            for p in protos:
                if not isinstance(p, dict):
                    continue
                if not q:
                    filtered_protos.append({
                        "file": p.get("file"),
                        "syntax": p.get("syntax"),
                        "package": p.get("package"),
                        "messages_count": p.get("messages_count", 0),
                        "enums_count": p.get("enums_count", 0),
                        "rpcs_count": p.get("rpcs_count", 0),
                        "sample_messages": [m.get("name") for m in (p.get("messages") or [])[:8]],
                        "sample_enums": [e.get("name") for e in (p.get("enums") or [])[:6]],
                    })
                elif _matches(p):
                    matched_msgs = [m for m in (p.get("messages") or []) if _matches(m)][:12]
                    matched_enums = [e for e in (p.get("enums") or []) if _matches(e)][:8]
                    matched_rpcs = [r for r in (p.get("rpcs") or []) if _matches(r)][:8]
                    filtered_protos.append({
                        "file": p.get("file"),
                        "syntax": p.get("syntax"),
                        "package": p.get("package"),
                        "messages_count": p.get("messages_count", 0),
                        "enums_count": p.get("enums_count", 0),
                        "rpcs_count": p.get("rpcs_count", 0),
                        "messages": matched_msgs,
                        "enums": matched_enums,
                        "rpcs": matched_rpcs,
                    })
            scoped["proto_contracts"] = filtered_protos

    res = apply_detail_budget("portal_contract", scoped, detail=detail)
    if (detail or "summary").strip().lower() == "summary":
        res = _truncate_to_token_cap(res, cap=800)
    return res
