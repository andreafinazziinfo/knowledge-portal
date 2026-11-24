"""
Knowledge Portal — Compliance & Audit Evidence Pack Engine (ADR-078).
100% Python stdlib zero-dependency control mapper reusing existing portal artifacts:
- Health Engine 4.0 (`arch-health.json`)
- CycloneDX 1.5 SBOM (`sbom.cdx.json`)
- Ownership Map (`ownership.json`)
- IaC Topology (`iac-topology.json`)
- AI Registry (`ai-registry.json`)
- Repository governance files (`SECURITY.md`, `LICENSE`, `CODEOWNERS`, CI workflows)

Maps technical evidence deterministically to:
- SOC2 Type II (CC6 Logical Access, CC7 System Ops, CC8 Change Management)
- ISO 27001:2022 (Annex A.8 Technological Controls)
- EU AI Act (Annex IV Technical Documentation & Transparency)

Outputs `data/compliance-evidence.json` and `data/compliance_evidence.js`.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


def _load_json(path: Path) -> dict[str, Any]:
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                return loaded
        except Exception:
            pass
    return {}


def generate_compliance_evidence(project_dir: Path, data_dir: Path) -> dict[str, Any]:
    """Build deterministic SOC2 / ISO 27001 / EU AI Act readiness report from portal artifacts."""
    project_dir = Path(project_dir).resolve()
    data_dir = Path(data_dir)

    health = _load_json(data_dir / "arch-health.json")
    sbom = _load_json(data_dir / "sbom.cdx.json")
    iac = _load_json(data_dir / "iac-topology.json")
    ai_reg = _load_json(data_dir / "ai-registry.json")
    cve = _load_json(data_dir / "cve-report.json")
    sarif = _load_json(data_dir / "sarif-findings.json")

    hv4 = health.get("health_v4") or {}
    owasp = hv4.get("owasp_audit") or {}
    rel = hv4.get("reliability_ast") or {}
    api = hv4.get("api_governance") or {}
    obs = hv4.get("observability") or {}
    sc = hv4.get("supply_chain_and_ai") or {}
    h_sum = health.get("summary") or {}
    cve_available = bool(cve.get("available", False))
    cve_sum = cve.get("summary") or {}
    cve_crit = int(cve_sum.get("critical", 0))
    cve_high = int(cve_sum.get("high", 0))
    cve_total = int(cve_sum.get("total", 0))
    rel_issues = int(rel.get("total_issues", 0) or 0)
    sarif_sum = sarif.get("summary") or {}
    sarif_crit = int(sarif_sum.get("critical", 0))
    sarif_total = int(sarif_sum.get("total", 0))

    has_license = any((project_dir / f).is_file() for f in ("LICENSE", "LICENSE.md", "LICENSE.txt"))
    has_security_md = any((project_dir / f).is_file() for f in ("SECURITY.md", ".github/SECURITY.md"))
    has_codeowners = any((project_dir / f).is_file() for f in (".github/CODEOWNERS", "CODEOWNERS", "docs/CODEOWNERS"))
    has_ci = (project_dir / ".github" / "workflows").is_dir() and any((project_dir / ".github" / "workflows").glob("*.y*ml"))
    has_sbom = bool(sbom.get("bomFormat") == "CycloneDX")
    ow_crit = int((owasp.get("by_severity") or {}).get("CRITICAL", 0))
    unauth_routes = int(api.get("unprotected_count", 0))
    cycles = int(h_sum.get("cycle_count", 0))
    has_probes = bool(obs.get("has_health_probe"))
    has_lockfile = bool(sc.get("has_lockfile"))
    iac_misconfigs = int((iac.get("summary") or {}).get("misconfigs_count", 0))
    ai_guardrails = int((ai_reg.get("summary") or {}).get("guardrail_findings_count", 0))
    ai_models = int((ai_reg.get("summary") or {}).get("unique_models_count", 0))
    has_llms = (project_dir / "llms.txt").is_file() or (data_dir.parent / "llms.txt").is_file()

    def _ctrl(fw: str, cid: str, title: str, status: str, evidence: str) -> dict[str, str]:
        return {"framework": fw, "control_id": cid, "title": title, "status": status, "evidence": evidence}

    controls: list[dict[str, str]] = [
        # SOC2 Type II
        _ctrl("SOC2", "CC6.1", "Logical Access & Auth on Mutating APIs",
              "PASS" if unauth_routes == 0 else ("WARN" if unauth_routes <= 2 else "FAIL"),
              f"{unauth_routes} unprotected mutating routes scanned (arch-health.json)"),
        _ctrl("SOC2", "CC6.6", "Zero Critical OWASP / CVE / SARIF Vulnerabilities",
              "PASS" if (ow_crit == 0 and cve_crit == 0 and sarif_crit == 0) else "FAIL",
              f"{ow_crit} CRITICAL OWASP, {cve_crit} CRITICAL CVEs ({cve_total} total), {sarif_crit} CRITICAL SARIF ({sarif_total} total)"),
        _ctrl("SOC2", "CC7.1", "System Monitoring & Health Probes",
              "PASS" if (has_probes and rel_issues == 0) else ("WARN" if (has_probes and rel_issues <= 25) else "FAIL"),
              f"/health probe present={has_probes}, Reliability AST issues={rel_issues}"),
        _ctrl("SOC2", "CC8.1", "Change Management (CI Gates & Ownership)",
              "PASS" if (has_ci and has_codeowners) else ("WARN" if has_ci else "FAIL"),
              f"CI workflows={has_ci}, CODEOWNERS={has_codeowners}, Cycles={cycles}"),

        # ISO 27001:2022
        _ctrl("ISO27001", "A.8.8", "Software Supply Chain, SBOM & CVE Management",
              "FAIL" if cve_crit > 0 else ("WARN" if (not cve_available or cve_high > 0 or not (has_sbom and has_lockfile)) else "PASS"),
              f"CycloneDX SBOM={has_sbom} ({len(sbom.get('components') or [])} components), lockfile={has_lockfile}, cve_available={cve_available}, CVEs={cve_total} (CRITICAL={cve_crit}, HIGH={cve_high})"),
        _ctrl("ISO27001", "A.8.9", "Infrastructure & Container Hardening",
              "PASS" if iac_misconfigs == 0 else ("WARN" if iac_misconfigs <= 3 else "FAIL"),
              f"{iac_misconfigs} IaC/Docker/GHA misconfigurations (iac-topology.json)"),
        _ctrl("ISO27001", "A.8.25", "Secure Development Policy & Licensing",
              "PASS" if (has_security_md and has_license) else "WARN",
              f"SECURITY.md={has_security_md}, LICENSE={has_license}"),

        # EU AI Act (Annex IV)
        _ctrl("EU_AI_ACT", "ART.11", "Technical Documentation & AI Manifests",
              "PASS" if has_llms else "WARN",
              f"llms.txt present={has_llms}, AI Models cataloged={ai_models}"),
        _ctrl("EU_AI_ACT", "ART.15", "AI Robustness & Prompt-Injection Guardrails",
              "PASS" if ai_guardrails == 0 else "WARN",
              f"{ai_guardrails} LLM guardrail / prompt-injection findings (ai-registry.json)"),
    ]

    by_fw: dict[str, dict[str, Any]] = {}
    for fw in ("SOC2", "ISO27001", "EU_AI_ACT"):
        f_ctrls = [c for c in controls if c["framework"] == fw]
        passed = sum(1 for c in f_ctrls if c["status"] == "PASS")
        warned = sum(1 for c in f_ctrls if c["status"] == "WARN")
        failed = sum(1 for c in f_ctrls if c["status"] == "FAIL")
        score = round(100.0 * (passed + warned * 0.5) / max(1, len(f_ctrls)))
        by_fw[fw] = {"readiness_pct": score, "pass": passed, "warn": warned, "fail": failed, "total": len(f_ctrls)}

    overall_pct = round(sum(v["readiness_pct"] for v in by_fw.values()) / len(by_fw))
    payload: dict[str, Any] = {
        "generated_at": time.time(),
        "project": project_dir.name,
        "summary": {
            "overall_readiness_pct": overall_pct,
            "total_controls": len(controls),
            "pass_count": sum(1 for c in controls if c["status"] == "PASS"),
            "warn_count": sum(1 for c in controls if c["status"] == "WARN"),
            "fail_count": sum(1 for c in controls if c["status"] == "FAIL"),
        },
        "frameworks": by_fw,
        "controls": controls,
    }

    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "compliance-evidence.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    (data_dir / "compliance_evidence.js").write_text(f"window.COMPLIANCE_EVIDENCE = {json.dumps(payload)};\n", encoding="utf-8")
    return payload
