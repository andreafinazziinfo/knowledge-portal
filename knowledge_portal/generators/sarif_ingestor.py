"""
Knowledge Portal — Universal SARIF 2.1.0 Ingestor (ADR-082 Wave 1.5 / Track B).
100% Python stdlib zero-dependency ingestor for local SARIF reports produced by
Semgrep, Gitleaks, CodeQL, Trivy, Ruff SARIF, Hadolint SARIF, or any SARIF 2.1.0 tool.
Zero-crash if no SARIF files are present.

Outputs `data/sarif-findings.json` and `data/sarif_findings.js`.
"""

from __future__ import annotations

import json
import time
from collections import Counter
from pathlib import Path
from typing import Any

_SEV_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "INFO": 4}

_TOOL_ALIASES = {
    "semgrep": "semgrep",
    "gitleaks": "gitleaks",
    "codeql": "codeql",
    "trivy": "trivy",
    "ruff": "ruff",
    "hadolint": "hadolint",
}


def _find_sarif_files(project_dir: Path) -> list[Path]:
    found: list[Path] = []
    seen: set[Path] = set()
    search_dirs = (
        project_dir,
        project_dir / "reports",
        project_dir / "backend" / "reports",
        project_dir / "frontend" / "reports",
    )
    for sdir in search_dirs:
        if not sdir.is_dir():
            continue
        for pat in ("*.sarif", "*.sarif.json"):
            for p in sorted(sdir.glob(pat)):
                if p.is_file() and p not in seen:
                    seen.add(p)
                    found.append(p)
    return found


def _norm_tool(raw_name: str, filename: str) -> str:
    low = (raw_name or filename).lower()
    for key, norm in _TOOL_ALIASES.items():
        if key in low:
            return norm
    return (raw_name or Path(filename).stem).strip().lower()[:32] or "sarif"


def _norm_severity(level: str, props: dict[str, Any]) -> str:
    sec_sev = props.get("security-severity")
    if sec_sev is not None:
        try:
            score = float(sec_sev)
            if score >= 9.0:
                return "CRITICAL"
            if score >= 7.0:
                return "HIGH"
            if score >= 4.0:
                return "MEDIUM"
            return "LOW"
        except (TypeError, ValueError):
            pass
    lv = (level or "").strip().lower()
    if lv in ("critical",):
        return "CRITICAL"
    if lv in ("error", "high"):
        return "HIGH"
    if lv in ("warning", "medium"):
        return "MEDIUM"
    if lv in ("note", "low"):
        return "LOW"
    return "INFO"


def generate_sarif_findings(project_dir: Path, data_dir: Path) -> dict[str, Any]:
    """Ingest all local SARIF 2.1.0 files into a unified normalized findings catalog."""
    project_dir = Path(project_dir).resolve()
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)

    cands = _find_sarif_files(project_dir)
    sources: list[str] = []
    by_tool: Counter[str] = Counter()
    by_severity: Counter[str] = Counter()
    findings: list[dict[str, Any]] = []

    for cand in cands:
        try:
            raw = json.loads(cand.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            continue
        if not isinstance(raw, dict) or not isinstance(raw.get("runs"), list):
            continue
        rel = str(cand.relative_to(project_dir)).replace("\\", "/")
        sources.append(rel)

        for run in raw.get("runs") or []:
            if not isinstance(run, dict):
                continue
            driver = ((run.get("tool") or {}).get("driver") or {}) if isinstance(run.get("tool"), dict) else {}
            tool_name = _norm_tool(str(driver.get("name") or ""), cand.name)
            rules_props: dict[str, dict[str, Any]] = {}
            for rule in driver.get("rules") or []:
                if isinstance(rule, dict) and rule.get("id"):
                    rp = rule.get("properties")
                    rules_props[str(rule["id"])] = rp if isinstance(rp, dict) else {}

            for res in run.get("results") or []:
                if not isinstance(res, dict):
                    continue
                rule_id = str(res.get("ruleId") or "SARIF")
                msg_obj = res.get("message")
                msg = str(msg_obj.get("text") if isinstance(msg_obj, dict) else (msg_obj or ""))[:200].strip()
                raw_rp = res.get("properties")
                res_props: dict[str, Any] = raw_rp if isinstance(raw_rp, dict) else {}
                merged_props: dict[str, Any] = {**rules_props.get(rule_id, {}), **res_props}
                sev = _norm_severity(str(res.get("level") or ""), merged_props)

                fpath = ""
                line = 1
                locs = res.get("locations") or []
                if isinstance(locs, list) and locs and isinstance(locs[0], dict):
                    phys = locs[0].get("physicalLocation") or {}
                    if isinstance(phys, dict):
                        art = phys.get("artifactLocation") or {}
                        if isinstance(art, dict):
                            fpath = str(art.get("uri") or "").replace("\\", "/").lstrip("./")
                        reg = phys.get("region") or {}
                        if isinstance(reg, dict) and reg.get("startLine"):
                            try:
                                line = int(reg["startLine"])
                            except (TypeError, ValueError):
                                line = 1

                by_tool[tool_name] += 1
                by_severity[sev] += 1
                findings.append({
                    "tool": tool_name,
                    "rule_id": rule_id,
                    "severity": sev,
                    "path": fpath,
                    "line": line,
                    "message": msg,
                    "source": rel,
                })

    findings.sort(key=lambda f: (_SEV_ORDER.get(str(f["severity"]), 9), str(f["tool"]), str(f["path"]), int(f["line"])))

    payload: dict[str, Any] = {
        "schema_version": "1.0",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "available": bool(sources),
        "summary": {
            "available": bool(sources),
            "sources_count": len(sources),
            "sources": sources,
            "total": len(findings),
            "critical": int(by_severity.get("CRITICAL", 0)),
            "high": int(by_severity.get("HIGH", 0)),
            "medium": int(by_severity.get("MEDIUM", 0)),
            "low": int(by_severity.get("LOW", 0)),
            "by_tool": dict(by_tool.most_common()),
            "by_severity": dict(by_severity),
        },
        "findings": findings[:300],
    }

    (data_dir / "sarif-findings.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    (data_dir / "sarif_findings.js").write_text(
        f"window.SARIF_FINDINGS = {json.dumps(payload)};\n",
        encoding="utf-8",
    )
    return payload
