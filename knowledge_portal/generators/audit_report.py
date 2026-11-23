"""
Knowledge Portal — Executive Audit Report & CI Quality Gate (ADR-076).
100% Python stdlib zero-dependency renderer producing:
- Executive Markdown Summary (for PR comments, Slack, leadership)
- SARIF 2.1.0 JSON (for GitHub Code Scanning / GitLab / VS Code)
- Deterministic CI Quality Gate evaluator (`knowledge-portal gate`)
"""

from __future__ import annotations

import time
from typing import Any


def render_markdown_report(report: dict[str, Any], project_name: str = "Repository") -> str:
    """Render an Executive Markdown Audit Summary from arch-health.json."""
    s = report.get("summary") or {}
    radar = report.get("radar") or {}
    hv4 = report.get("health_v4") or {}
    ow = hv4.get("owasp_audit") or {}
    rel = hv4.get("reliability_ast") or {}
    api = hv4.get("api_governance") or {}
    dbg = hv4.get("db_governance") or {}
    obs = hv4.get("observability") or {}
    tq = hv4.get("test_quality") or {}
    sc = hv4.get("supply_chain_and_ai") or {}
    fq = report.get("fix_queue") or []

    ts = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())
    lines = [
        f"# Architectural & Security Health Report — {project_name}",
        "",
        f"- **Generated**: {ts}",
        f"- **Health Score**: **{s.get('health_score', 0)} / 100** (Grade **{s.get('grade', '-')}**)",
        f"- **Modules**: `{s.get('total_modules', 0)}` · **Edges**: `{s.get('total_edges', 0)}` · **Cycles (SCC)**: `{s.get('cycle_count', 0)}` · **Layer Violations**: `{s.get('layer_violation_count', 0)}`",
        "",
        "## 1. 6-Axis Architecture Radar",
        "",
        "| Axis | Score |",
        "| :--- | ---: |",
    ]
    for k, v in radar.items():
        lines.append(f"| {k} | {v}/100 |")

    lines.extend([
        "",
        "## 2. Health Engine 4.0 Summary (16 Zero-Dep Pillars)",
        "",
        "| Category | Findings / Status |",
        "| :--- | :--- |",
        f"| **OWASP Quick-Audit** | `{ow.get('findings_count', 0)}` total (`CRITICAL: {(ow.get('by_severity') or {}).get('CRITICAL', 0)}`, `HIGH: {(ow.get('by_severity') or {}).get('HIGH', 0)}`) |",
        f"| **Reliability AST** | `{rel.get('total_issues', 0)}` (`async: {rel.get('async_blocking_count', 0)}`, `timeout: {rel.get('missing_timeout_count', 0)}`, `silent except: {rel.get('silent_except_count', 0)}`) |",
        f"| **API Governance** | `{api.get('unprotected_count', 0)}` unprotected / `{api.get('mutating_routes_scanned', 0)}` mutating routes (`no response_model: {api.get('missing_response_model_count', 0)}`) |",
        f"| **DB Governance** | `{dbg.get('n_plus_one_count', 0)}` N+1 loops · `{dbg.get('unbounded_select_count', 0)}` unbounded SELECT · `{dbg.get('unreferenced_tables_count', 0)}` unused tables |",
        f"| **Observability** | `/health`: `{obs.get('has_health_probe', False)}` · `/ready`: `{obs.get('has_ready_probe', False)}` · prod `print()`: `{obs.get('prod_print_count', 0)}` · `console.log()`: `{obs.get('prod_console_log_count', 0)}` |",
        f"| **Test Quality** | `{tq.get('test_smells_count', 0)}` test smells across `{len(tq.get('by_domain') or [])}` profiled domains |",
        f"| **Supply Chain & AI** | `{sc.get('pyproject_unpinned_count', 0)}` unpinned pyproject deps · lockfiles: `{len(sc.get('lockfiles_present') or [])}` · Context Bombs (>800 LOC): `{sc.get('context_bombs_count', 0)}` |",
        "",
        "## 3. Top Prioritized ROI Fix Queue",
        "",
    ])
    if fq:
        for item in fq:
            lines.append(f"- **[{item.get('priority', 'P2')}] [{item.get('category', 'General')}]** `{item.get('target', '')}` — {item.get('action', '')}")
    else:
        lines.append("- Zero critical engineering actions queued.")

    lines.append("")
    return "\n".join(lines)


def render_sarif_report(report: dict[str, Any]) -> dict[str, Any]:
    """Render a standards-compliant SARIF 2.1.0 JSON dict from arch-health.json."""
    hv4 = report.get("health_v4") or {}
    results: list[dict[str, Any]] = []

    def _add(rule_id: str, level: str, message: str, path: str, line: int = 1) -> None:
        results.append({
            "ruleId": rule_id,
            "level": level,
            "message": {"text": message},
            "locations": [{
                "physicalLocation": {
                    "artifactLocation": {"uri": path},
                    "region": {"startLine": max(1, int(line or 1))},
                }
            }],
        })

    for f in (hv4.get("owasp_audit") or {}).get("findings") or []:
        sev = str(f.get("severity", "MEDIUM")).upper()
        lvl = "error" if sev in ("CRITICAL", "HIGH") else "warning"
        _add(f"KP-OWASP-{f.get('rule', 'SEC')}", lvl, str(f.get("detail", "")), str(f.get("path", "")), int(f.get("line", 1)))

    rel = hv4.get("reliability_ast") or {}
    for x in rel.get("async_blocking") or []:
        _add("KP-SRE-ASYNC-BLOCKING", "error", f"Blocking {x.get('call')} inside async {x.get('func')}()", str(x.get("path", "")), int(x.get("line", 1)))
    for x in rel.get("missing_timeout") or []:
        _add("KP-SRE-MISSING-TIMEOUT", "warning", f"{x.get('call')}() called without timeout=", str(x.get("path", "")), int(x.get("line", 1)))

    for rt in (hv4.get("api_governance") or {}).get("unprotected_mutating_routes") or []:
        _add("KP-API-UNPROTECTED", "warning", f"Mutating route {rt.get('method')} {rt.get('route')} missing auth dependency", str(rt.get("path", "")), int(rt.get("line", 1)))

    for n1 in (hv4.get("db_governance") or {}).get("n_plus_one_loops") or []:
        _add("KP-DB-N-PLUS-ONE", "warning", f"DB query {n1.get('call')} inside loop (N+1 risk)", str(n1.get("path", "")), int(n1.get("line", 1)))

    for idx, cyc in enumerate(report.get("cycles") or [], 1):
        if cyc:
            _add("KP-ARCH-CYCLE", "error", f"Circular dependency #{idx}: {' -> '.join(cyc[:5])}", str(cyc[0]), 1)

    return {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [{
            "tool": {
                "driver": {
                    "name": "Knowledge Portal Health Engine 4.0",
                    "version": "4.0.0",
                    "informationUri": "https://github.com/andreafinazziinfo/knowledge-portal",
                }
            },
            "results": results,
        }],
    }


def evaluate_quality_gate(
    report: dict[str, Any],
    min_score: int = 0,
    max_cycles: int | None = None,
    max_critical: int | None = None,
) -> tuple[bool, list[str]]:
    """Evaluate CI quality gate thresholds against arch-health.json."""
    s = report.get("summary") or {}
    hv4 = report.get("health_v4") or {}
    score = int(s.get("health_score", 0))
    cycles = int(s.get("cycle_count", 0))
    ow_crit = int(((hv4.get("owasp_audit") or {}).get("by_severity") or {}).get("CRITICAL", 0))
    async_crit = int((hv4.get("reliability_ast") or {}).get("async_blocking_count", 0))
    total_crit = ow_crit + async_crit

    failures: list[str] = []
    if score < min_score:
        failures.append(f"Health score {score} < required min_score {min_score}")
    if max_cycles is not None and cycles > max_cycles:
        failures.append(f"Dependency cycles {cycles} > allowed max_cycles {max_cycles}")
    if max_critical is not None and total_crit > max_critical:
        failures.append(f"Critical security/SRE findings {total_crit} > allowed max_critical {max_critical}")

    return len(failures) == 0, failures
