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
    rt2 = hv4.get("runtime_bugs_v2") or {}
    dc = (hv4.get("dead_code_symbols") or {}).get("summary") or {}
    qt = (hv4.get("quality_telemetry") or {}).get("summary") or {}
    ms_mig = (hv4.get("migration_sre") or {}).get("migration_safety") or {}
    ms_sre = (hv4.get("migration_sre") or {}).get("sre_resilience") or {}
    feh = (hv4.get("frontend_hygiene") or {}).get("summary") or {}
    scl = hv4.get("semantic_clones") or {}
    cve = report.get("cve_report") or {}
    cve_s = cve.get("summary") or {}
    dbh = report.get("db_health") or {}
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

    cov_raw = qt.get("coverage_pct")
    cov_display = f"{cov_raw}%" if cov_raw is not None else "N/A"
    lines.extend([
        "",
        "## 2. Health Engine 4.0 Summary (16 Zero-Dep Pillars)",
        "",
        "| Category | Findings / Status |",
        "| :--- | :--- |",
        f"| **OWASP Quick-Audit** | `{ow.get('findings_count', 0)}` total (`CRITICAL: {(ow.get('by_severity') or {}).get('CRITICAL', 0)}`, `HIGH: {(ow.get('by_severity') or {}).get('HIGH', 0)}`) |",
        f"| **Reliability AST** | `{rel.get('total_issues', 0)}` (`async: {rel.get('async_blocking_count', 0)}`, `timeout: {rel.get('missing_timeout_count', 0)}`, `silent except: {rel.get('silent_except_count', 0)}`, `mutable default: {rel.get('mutable_default_count', 0)}`, `unclosed: {rel.get('unclosed_resource_count', 0)}`) |",
        f"| **Runtime Bugs v2 (Py + Vue/TS)** | `{rt2.get('total_issues', 0)}` (`Python: {rt2.get('python_count', 0)}`, `Vue/TS: {rt2.get('frontend_count', 0)}`) |",
        f"| **CVE & SBOM** | `{cve_s.get('total', 0)}` CVEs (`CRITICAL: {cve_s.get('critical', 0)}`, `HIGH: {cve_s.get('high', 0)}`, `SBOM correlated: {cve_s.get('sbom_correlated', 0)}`) |",
        f"| **API Governance** | `{api.get('unprotected_count', 0)}` unprotected / `{api.get('mutating_routes_scanned', 0)}` mutating routes (`router-protected: {api.get('router_protected_count', 0)}`, `no response_model: {api.get('missing_response_model_count', 0)}`) |",
        f"| **DB Governance** | `{dbg.get('n_plus_one_count', 0)}` N+1 loops · `{dbg.get('unbounded_select_count', 0)}` unbounded SELECT · `{dbh.get('hypertables_count', 0)}` Hypertables · `{dbh.get('caggs_count', 0)}` CAGGs |",
        f"| **Observability** | `/health`: `{obs.get('has_health_probe', False)}` · `/ready`: `{obs.get('has_ready_probe', False)}` · prod `print()`: `{obs.get('prod_print_count', 0)}` · `console.log()`: `{obs.get('prod_console_log_count', 0)}` |",
        f"| **Test Quality** | `{tq.get('test_smells_count', 0)}` test smells across `{len(tq.get('by_domain') or [])}` profiled domains |",
        f"| **Supply Chain & AI** | `{sc.get('pyproject_unpinned_count', 0)}` unpinned pyproject deps · lockfiles: `{len(sc.get('lockfiles_present') or [])}` · Context Bombs (>800 LOC): `{sc.get('context_bombs_count', 0)}` |",
        f"| **Dead Code (Py + JS/Vue)** | `{dc.get('total', 0)}` total (`Python: {dc.get('python_count', 0)}`, `JS/TS exports: {dc.get('js_export_count', 0)}`, `Vue components: {dc.get('vue_component_count', 0)}`) |",
        f"| **Migration Safety & SRE** | `{ms_mig.get('total_issues', 0)}` migration issues · SRE score: `{ms_sre.get('score_pct', 0)}/100` · f-string logs: `{ms_sre.get('fstring_logging_count', 0)}` |",
        f"| **Frontend & a11y Hygiene** | `{feh.get('total_issues', 0)}` issues (`lazy routes: {feh.get('lazy_route_coverage_pct', 100.0)}%`, `god-stores: {feh.get('god_stores_count', 0)}`, `a11y: {feh.get('a11y_issues_count', 0)}`) |",
        f"| **Quality Telemetry** | `{qt.get('sources_count', 0)}` local CI sources (`coverage: {cov_display}`, `JUnit: {qt.get('junit_total', 0)}`, `ruff: {qt.get('ruff_issues', 0)}`, `mypy/tsc: {int(qt.get('mypy_errors', 0)) + int(qt.get('tsc_errors', 0))}`) |",
        f"| **AST Semantic Clones** | `{scl.get('clone_groups_count', 0)}` groups (`{scl.get('duplicated_functions_count', 0)}` duplicated functions out of `{scl.get('functions_analyzed', 0)}`) |",
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


def render_sarif_report(
    report: dict[str, Any],
    iac_topology: dict[str, Any] | None = None,
    cve_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Render a standards-compliant SARIF 2.1.0 JSON dict from arch-health.json (+ optional IaC & CVE reports)."""
    hv4 = report.get("health_v4") or {}
    results: list[dict[str, Any]] = []

    def _add(rule_id: str, level: str, message: str, path: str, line: int = 1) -> None:
        results.append({
            "ruleId": rule_id,
            "level": level,
            "message": {"text": message},
            "locations": [{
                "physicalLocation": {
                    "artifactLocation": {"uri": path or "repository"},
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

    # ADR-080 P0.2: Runtime Bugs v2 (Python AST + Vue/TS) — skip ASYNC_BLOCKING_IO already emitted above
    for f in (hv4.get("runtime_bugs_v2") or {}).get("findings") or []:
        rule = str(f.get("rule", "BUG"))
        if rule == "ASYNC_BLOCKING_IO":
            continue
        sev = str(f.get("severity", "MEDIUM")).upper()
        lvl = "error" if sev in ("CRITICAL", "HIGH") else "warning"
        _add(f"KP-RUNTIME-{rule}", lvl, str(f.get("detail", "")), str(f.get("path", "")), int(f.get("line", 1)))

    # ADR-080 P0.3: IaC & CI/CD Hardening misconfigs
    if isinstance(iac_topology, dict):
        for m in iac_topology.get("misconfigs") or []:
            sev = str(m.get("severity", "MEDIUM")).upper()
            lvl = "error" if sev in ("CRITICAL", "HIGH") else ("warning" if sev == "MEDIUM" else "note")
            _add(f"KP-IAC-{m.get('rule', 'MISCONFIG')}", lvl, str(m.get("detail", "")), str(m.get("file", "")), int(m.get("line", 1)))

    # ADR-080 P0.3: CVE Vulnerabilities
    eff_cve = cve_report if isinstance(cve_report, dict) else (report.get("cve_report") if isinstance(report.get("cve_report"), dict) else None)
    if isinstance(eff_cve, dict):
        for v in eff_cve.get("vulnerabilities") or []:
            sev = str(v.get("severity", "MEDIUM")).upper()
            lvl = "error" if sev in ("CRITICAL", "HIGH") else "warning"
            _add(f"KP-CVE-{v.get('id', 'VULN')}", lvl, f"[{v.get('package')}@{v.get('installed_version')}] {v.get('summary', '')}", str(v.get("source_file", "sbom.cdx.json")), 1)

    for rt in (hv4.get("api_governance") or {}).get("unprotected_mutating_routes") or []:
        _add("KP-API-UNPROTECTED", "warning", f"Mutating route {rt.get('method')} {rt.get('route')} missing auth dependency", str(rt.get("path", "")), int(rt.get("line", 1)))

    for n1 in (hv4.get("db_governance") or {}).get("n_plus_one_loops") or []:
        _add("KP-DB-N-PLUS-ONE", "warning", f"DB query {n1.get('call')} inside loop (N+1 risk)", str(n1.get("path", "")), int(n1.get("line", 1)))

    # ADR-080 P1.3: Migration Safety & SRE Resilience
    for mf in (hv4.get("migration_sre") or {}).get("findings") or []:
        sev = str(mf.get("severity", "MEDIUM")).upper()
        lvl = "error" if sev in ("CRITICAL", "HIGH") else ("warning" if sev == "MEDIUM" else "note")
        _add(f"KP-MIGSRE-{mf.get('rule', 'RULE')}", lvl, str(mf.get("detail", "")), str(mf.get("path", "")), int(mf.get("line", 1)))

    # ADR-080 P2.1: Frontend Architecture & a11y Hygiene
    for ff in (hv4.get("frontend_hygiene") or {}).get("findings") or []:
        sev = str(ff.get("severity", "MEDIUM")).upper()
        lvl = "error" if sev in ("CRITICAL", "HIGH") else ("warning" if sev == "MEDIUM" else "note")
        _add(f"KP-FE-{ff.get('rule', 'RULE')}", lvl, str(ff.get("detail", "")), str(ff.get("path", "")), int(ff.get("line", 1)))

    # ADR-080 P1.1: Dead Code (Python + JS/TS/Vue)
    dc_block = hv4.get("dead_code_symbols") or {}
    for dlist in (dc_block.get("vue_unused_components") or [], dc_block.get("python_dead_symbols") or [], dc_block.get("js_unused_exports") or []):
        for df in dlist[:30]:
            _add(f"KP-DEAD-{df.get('rule', 'SYMBOL')}", "note", str(df.get("detail", "")), str(df.get("file", "")), int(df.get("line", 1)))

    # ADR-080 P2.2: AST Semantic Clones
    for cg in (hv4.get("semantic_clones") or {}).get("top_clones") or []:
        fns = cg.get("functions") or []
        if fns:
            first = fns[0]
            _add(
                "KP-CLONE-AST",
                "warning",
                f"AST semantic clone ({cg.get('occurrences', 2)} functions, {cg.get('statements', 0)} statements): {', '.join(f.get('name', '') for f in fns[:4])}",
                str(first.get("file", "")),
                int(first.get("line", 1)),
            )

    for idx, cyc in enumerate(report.get("cycles") or [], 1):
        if cyc:
            _add("KP-ARCH-CYCLE", "error", f"Circular dependency #{idx}: {' -> '.join(cyc[:5])}", str(cyc[0]), 1)

    return {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [{
            "tool": {
                "driver": {
                    "name": "Knowledge Portal Health Engine 5.0",
                    "version": "5.0.0",
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
    enforce_fitness_gate: bool = True,
) -> tuple[bool, list[str]]:
    """Evaluate CI quality gate thresholds and `.arch-rules.json` fitness gate against arch-health.json."""
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

    if enforce_fitness_gate:
        fg = report.get("fitness_gate") or {}
        if isinstance(fg, dict) and fg.get("available"):
            err_violations = [
                v for v in (fg.get("violations") or [])
                if isinstance(v, dict) and str(v.get("severity", "ERROR")).upper() == "ERROR"
            ]
            err_cnt = int(fg.get("errors_count", len(err_violations)))
            if err_cnt > 0 or fg.get("passed") is False:
                sample = ""
                if err_violations:
                    v0 = err_violations[0]
                    sample = f" (e.g. {v0.get('rule_id')}: {v0.get('source')} -> {v0.get('target')})"
                failures.append(
                    f"Architecture fitness gate failed: {err_cnt} ERROR violation(s) in .arch-rules.json{sample}"
                )

    return len(failures) == 0, failures
