"""
Knowledge Portal — Executive Bento Mission Control Aggregator (ADR-081).
100% Python stdlib zero-dependency executive aggregator fusing:
- Architectural Health Score, Grade, Runtime Bugs v2, Dead Code, Quality Telemetry
- CI/CD & CVE vulnerability posture
- Compliance Readiness (SOC2 / ISO 27001 / EU AI Act)
- Git Worktree Hygiene & Stacked-PR DAG summary
- ADR Governance & Interactive Runbook Hub counts
- AI / LLM Registry & Mission Readiness
- Optional Hub Extension plugin summary slot (`hub_extension`)

Outputs `data/mission-control.json` and `data/mission_control.js`.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _load_json_safe(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _status_from_score(score: float | int, green: float = 80.0, amber: float = 60.0) -> str:
    if score >= green:
        return "green"
    if score >= amber:
        return "amber"
    return "red"


def generate_mission_control(
    project_dir: Path,
    data_dir: Path,
    *,
    hub_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Aggregate all OSS portal telemetry into an executive Mission Control payload."""
    project_dir = Path(project_dir).resolve()
    data_dir = Path(data_dir)
    generated_at = datetime.now(tz=timezone.utc).isoformat()

    health = _load_json_safe(data_dir / "arch-health.json")
    cve = _load_json_safe(data_dir / "cve-report.json")
    compliance = _load_json_safe(data_dir / "compliance-evidence.json")
    git_dag = _load_json_safe(data_dir / "git-dag.json")
    adr_graph = _load_json_safe(data_dir / "adr-graph.json")
    ai_reg = _load_json_safe(data_dir / "ai-registry.json")
    graph = _load_json_safe(data_dir / "graph.json")

    h_sum = health.get("summary") or {}
    health_score = int(h_sum.get("health_score", 0) or 0)
    grade = str(h_sum.get("grade", "N/A"))
    cycle_count = int(h_sum.get("cycle_count", 0) or 0)
    orphan_count = int(h_sum.get("orphan_count", 0) or 0)

    # Runtime Bugs v2 (from arch-health runtime_bugs / sre_findings / security_findings)
    runtime_bugs = health.get("runtime_bugs") or []
    sre_findings = health.get("sre_findings") or []
    sec_findings = health.get("security_findings") or []
    runtime_bugs_count = len(runtime_bugs) if isinstance(runtime_bugs, list) else int(h_sum.get("runtime_bugs_count", 0) or 0)
    critical_findings = sum(
        1
        for f in (list(runtime_bugs) + list(sre_findings) + list(sec_findings))
        if isinstance(f, dict) and str(f.get("severity", "")).upper() == "CRITICAL"
    )

    # Dead code (ADR-080 P1)
    hv4 = health.get("health_v4") or {}
    dc_block = hv4.get("dead_code_symbols") or _load_json_safe(data_dir / "dead-code.json")
    dc_sum = dc_block.get("summary") or {} if isinstance(dc_block, dict) else {}
    dead_code_count = int(dc_sum.get("total_dead_symbols", dc_sum.get("total", 0)) or 0)

    # CVE / Supply Chain
    cve_sum = cve.get("summary") or {}
    cve_critical = int(cve_sum.get("critical", 0) or 0)
    cve_high = int(cve_sum.get("high", 0) or 0)
    cve_total = int(cve_sum.get("total_vulnerabilities", cve_sum.get("total", 0)) or 0)

    # Compliance Readiness
    comp_sum = compliance.get("summary") or {}
    compliance_score = round(float(comp_sum.get("readiness_pct", comp_sum.get("overall_score", 0.0)) or 0.0), 1)
    controls_passed = int(comp_sum.get("passed", 0) or 0)
    controls_total = int(comp_sum.get("total_controls", comp_sum.get("total", 0)) or 0)

    # Git / PR DAG
    git_sum = git_dag.get("summary") or {}
    active_worktrees = int(git_sum.get("total_worktrees", 0) or 0)
    dirty_worktrees = int(git_sum.get("dirty_worktrees", 0) or 0)
    stale_worktrees = int(git_sum.get("stale_worktrees", 0) or 0)
    open_prs = int(git_sum.get("open_prs_count", 0) or 0)
    stacked_chains = int(git_sum.get("stacked_chains_count", 0) or 0)
    workflows_count = int(git_sum.get("workflows_count", 0) or 0)

    # ADR & Runbooks
    adr_sum = adr_graph.get("summary") or {}
    total_adrs = int(adr_sum.get("total_adrs", adr_graph.get("total_adrs", 0)) or 0)
    proposed_adrs = int(adr_sum.get("proposed_count", 0) or 0)
    total_runbooks = int(adr_sum.get("total_runbooks", 0) or 0)

    # AI Mission Readiness
    ai_sum = ai_reg.get("summary") or {}
    ai_sdks = len(ai_sum.get("sdks_detected") or {}) if isinstance(ai_sum.get("sdks_detected"), dict) else 0
    ai_guardrails = int(ai_sum.get("guardrail_findings_count", 0) or 0)
    ai_prompts = int(ai_sum.get("prompts_cataloged", 0) or 0)
    ai_ready = True  # OSS MCP + CodeMode + Mission Pack always available

    # Graph scale
    total_nodes = len(graph.get("nodes") or []) if isinstance(graph.get("nodes"), list) else 0
    total_edges = len(graph.get("edges") or graph.get("links") or []) if isinstance(graph.get("edges") or graph.get("links"), list) else 0

    kpis = {
        "health_score": health_score,
        "grade": grade,
        "cycle_count": cycle_count,
        "orphan_count": orphan_count,
        "runtime_bugs_count": runtime_bugs_count,
        "critical_findings": critical_findings,
        "cve_total": cve_total,
        "cve_critical_high": cve_critical + cve_high,
        "dead_code_count": dead_code_count,
        "compliance_score": compliance_score,
        "controls_passed": controls_passed,
        "controls_total": controls_total,
        "active_worktrees": active_worktrees,
        "dirty_worktrees": dirty_worktrees,
        "stale_worktrees": stale_worktrees,
        "open_prs": open_prs,
        "stacked_chains": stacked_chains,
        "workflows_count": workflows_count,
        "total_adrs": total_adrs,
        "proposed_adrs": proposed_adrs,
        "total_runbooks": total_runbooks,
        "ai_sdks": ai_sdks,
        "ai_prompts": ai_prompts,
        "ai_guardrails": ai_guardrails,
        "ai_readiness": "READY" if ai_ready else "OFFLINE",
        "total_nodes": total_nodes,
        "total_edges": total_edges,
    }

    # 6 Subsystem Traffic-Light Matrix
    subsystems = [
        {
            "id": "architecture",
            "title": "Architecture & Health",
            "status": _status_from_score(health_score, 80, 60) if health else "amber",
            "metric": f"{health_score}/100 ({grade})" if health else "Not scanned",
            "detail": f"{cycle_count} cycles · {orphan_count} orphans · {dead_code_count} dead symbols",
            "view": "arch-health",
        },
        {
            "id": "runtime_bugs",
            "title": "Runtime Bugs & SRE",
            "status": "red" if critical_findings > 0 else ("amber" if runtime_bugs_count > 5 else "green"),
            "metric": f"{runtime_bugs_count} findings",
            "detail": f"{critical_findings} CRITICAL · {len(sre_findings)} SRE · {len(sec_findings)} OWASP",
            "view": "arch-health",
        },
        {
            "id": "ci_cve",
            "title": "CI/CD & CVE Supply Chain",
            "status": "red" if cve_critical > 0 else ("amber" if cve_high > 0 else "green"),
            "metric": f"{cve_total} CVEs",
            "detail": f"{cve_critical} critical · {cve_high} high · {workflows_count} CI workflows",
            "view": "iac-topology",
        },
        {
            "id": "compliance",
            "title": "Compliance Readiness",
            "status": _status_from_score(compliance_score, 80, 50) if controls_total > 0 else "amber",
            "metric": f"{compliance_score}%" if controls_total > 0 else "N/A",
            "detail": f"{controls_passed}/{controls_total} controls verified (SOC2 / ISO / EU AI)",
            "view": "arch-health",
        },
        {
            "id": "git_worktrees",
            "title": "Git, Worktrees & PR DAG",
            "status": "red" if stale_worktrees > 15 else ("amber" if dirty_worktrees > 0 or stale_worktrees > 5 else "green"),
            "metric": f"{open_prs} PRs · {active_worktrees} WTs",
            "detail": f"{stacked_chains} stacked chains · {dirty_worktrees} dirty · {stale_worktrees} stale",
            "view": "git-pr-dag",
        },
        {
            "id": "adr_ai_ops",
            "title": "ADR, Runbooks & AI Copilot",
            "status": "amber" if ai_guardrails > 0 else "green",
            "metric": f"{total_adrs} ADRs · {total_runbooks} Runbooks",
            "detail": f"{proposed_adrs} proposed · {ai_sdks} AI SDKs · {ai_guardrails} guardrail alerts",
            "view": "adr-runbook-hub",
        },
    ]

    # Prioritized Anomaly & Action Feed (P0 / P1 / P2)
    anomalies: list[dict[str, str]] = []
    if cve_critical > 0:
        anomalies.append({
            "severity": "P0",
            "category": "Security",
            "title": f"{cve_critical} Critical CVE vulnerabilities detected",
            "detail": "Upgrade affected dependencies and re-run SBOM / CVE audit.",
            "view": "stack-ecosystem",
            "action_label": "Inspect SBOM & CVEs",
        })
    if critical_findings > 0:
        anomalies.append({
            "severity": "P0",
            "category": "Runtime",
            "title": f"{critical_findings} CRITICAL runtime/security findings",
            "detail": "Review Health Engine 4.0 report and resolve high-severity defects before release.",
            "view": "arch-health",
            "action_label": "Open Health Audit",
        })
    if health and health_score < 70:
        anomalies.append({
            "severity": "P1",
            "category": "Architecture",
            "title": f"Architecture Health Score below target ({health_score}/100)",
            "detail": f"Detected {cycle_count} dependency cycles and {orphan_count} orphan modules.",
            "view": "arch-health",
            "action_label": "Analyze Architecture",
        })
    if stale_worktrees > 10:
        anomalies.append({
            "severity": "P1",
            "category": "Git Hygiene",
            "title": f"{stale_worktrees} stale Git worktrees detected (total: {active_worktrees})",
            "detail": "Prune merged or abandoned worktrees to prevent drift and disk bloat.",
            "view": "git-pr-dag",
            "action_label": "Open Worktree Matrix",
        })
    if stacked_chains > 0:
        anomalies.append({
            "severity": "P2",
            "category": "PR Stack",
            "title": f"{stacked_chains} stacked PR chain(s) awaiting ordered merge",
            "detail": "Follow the topological Merge Order in Git & PR DAG to avoid rebase conflicts.",
            "view": "git-pr-dag",
            "action_label": "View Merge Order",
        })
    if ai_guardrails > 0:
        anomalies.append({
            "severity": "P1",
            "category": "LLMOps",
            "title": f"{ai_guardrails} AI/LLM guardrail or prompt-injection risk(s)",
            "detail": "Review AI Registry findings and enforce strict prompt sanitization.",
            "view": "ai-registry",
            "action_label": "Inspect AI Registry",
        })
    if proposed_adrs > 0:
        anomalies.append({
            "severity": "P2",
            "category": "Governance",
            "title": f"{proposed_adrs} ADR(s) still in Proposed/Draft status",
            "detail": "Review pending Architecture Decision Records in the ADR & Runbook Hub.",
            "view": "adr-runbook-hub",
            "action_label": "Open ADR Hub",
        })

    if hub_summary and isinstance(hub_summary.get("anomalies"), list):
        for item in hub_summary["anomalies"]:
            if isinstance(item, dict):
                anomalies.append({
                    "severity": str(item.get("severity", "P2")),
                    "category": str(item.get("category", "Hub")),
                    "title": str(item.get("title", "")),
                    "detail": str(item.get("detail", "")),
                    "view": str(item.get("view", "mission-control")),
                    "action_label": str(item.get("action_label", "Inspect")),
                })

    sev_rank = {"P0": 0, "P1": 1, "P2": 2}
    anomalies.sort(key=lambda a: sev_rank.get(a.get("severity", "P2"), 9))

    quick_jumps = [
        {"id": "git-pr-dag", "title": "Git & Stacked-PR DAG", "desc": f"{open_prs} PRs · {active_worktrees} worktrees", "icon": "🌿"},
        {"id": "adr-runbook-hub", "title": "ADR & Runbook Hub", "desc": f"{total_adrs} ADRs · {total_runbooks} runbooks", "icon": "📘"},
        {"id": "ai-mission-launcher", "title": "AI Mission Launcher", "desc": "Mission Pack & CodeMode Workbench", "icon": "🚀"},
        {"id": "arch-health", "title": "Health & Audit 4.0", "desc": f"Score {health_score}/100 ({grade})", "icon": "🩺"},
        {"id": "graph-studio", "title": "Graph Studio", "desc": f"{total_nodes} nodes · {total_edges} edges", "icon": "🕸️"},
        {"id": "api-catalog", "title": "API Catalog", "desc": "HTTP/WS endpoints & OpenAPI", "icon": "🔌"},
        {"id": "iac-topology", "title": "IaC & CI/CD", "desc": f"{workflows_count} workflows · infra map", "icon": "🐳"},
        {"id": "ai-registry", "title": "AI / LLM Registry", "desc": f"{ai_sdks} SDKs · {ai_prompts} prompts", "icon": "🤖"},
    ]

    payload: dict[str, Any] = {
        "schema_version": "1.0",
        "generated_at": generated_at,
        "project_name": project_dir.name,
        "kpis": kpis,
        "subsystems": subsystems,
        "anomalies": anomalies,
        "quick_jumps": quick_jumps,
        "hub_extension": hub_summary,
    }

    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "mission-control.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    (data_dir / "mission_control.js").write_text(
        f"window.MISSION_CONTROL = {json.dumps(payload, ensure_ascii=False)};\n",
        encoding="utf-8",
    )

    return payload
