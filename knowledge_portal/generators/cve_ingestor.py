"""
Knowledge Portal — Air-Gapped CVE Vulnerability Ingestor (ADR-080 P0.3).
100% Python stdlib zero-dependency parser for optional local CVE audit reports:
- pip-audit.json   (`pip-audit -f json`)
- npm-audit.json   (`npm audit --json`)
- osv-scanner.json (`osv-scanner --format json`)
- trivy.json       (`trivy fs --format json`)

Zero outbound network calls. Correlates discovered CVEs against `sbom.cdx.json`
components (enriching CycloneDX 1.5 `vulnerabilities[]`) and outputs:
- `data/cve-report.json`
- `data/cve_report.js` (`window.CVE_REPORT`)
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

_SEVERITY_NORM = {
    "CRITICAL": "CRITICAL",
    "HIGH": "HIGH",
    "MODERATE": "MEDIUM",
    "MEDIUM": "MEDIUM",
    "LOW": "LOW",
    "INFO": "LOW",
    "UNKNOWN": "MEDIUM",
}
_SEV_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}

_REPORT_CANDIDATES: list[tuple[str, str]] = [
    ("pip-audit.json", "pip-audit"),
    ("npm-audit.json", "npm-audit"),
    ("osv-scanner.json", "osv-scanner"),
    ("trivy.json", "trivy"),
]


def _norm_sev(raw: Any) -> str:
    s = str(raw or "MEDIUM").strip().upper()
    return _SEVERITY_NORM.get(s, "MEDIUM")


def _parse_pip_audit(data: Any, source_rel: str) -> list[dict[str, Any]]:
    vulns: list[dict[str, Any]] = []
    deps = data.get("dependencies") if isinstance(data, dict) else (data if isinstance(data, list) else [])
    for dep in deps or []:
        if not isinstance(dep, dict):
            continue
        pkg = str(dep.get("name", ""))
        ver = str(dep.get("version", ""))
        for v in dep.get("vulns") or []:
            if not isinstance(v, dict):
                continue
            vid = str(v.get("id") or "PYSEC-UNKNOWN")
            aliases = v.get("aliases") or []
            cve_id = next((str(a) for a in aliases if str(a).startswith("CVE-")), vid)
            fixes = [str(f) for f in (v.get("fix_versions") or []) if f]
            desc = str(v.get("description") or "")[:240]
            sev = _norm_sev(v.get("severity") or ("HIGH" if cve_id.startswith("CVE-") else "MEDIUM"))
            vulns.append({
                "id": cve_id,
                "advisory_id": vid,
                "package": pkg,
                "installed_version": ver,
                "fixed_version": fixes[0] if fixes else None,
                "severity": sev,
                "ecosystem": "pypi",
                "source": "pip-audit",
                "source_file": source_rel,
                "summary": desc or f"Vulnerability {cve_id} in {pkg}=={ver}",
            })
    return vulns


def _parse_npm_audit(data: Any, source_rel: str) -> list[dict[str, Any]]:
    vulns: list[dict[str, Any]] = []
    if not isinstance(data, dict):
        return vulns
    raw_vulns = data.get("vulnerabilities")
    if isinstance(raw_vulns, dict):
        for pkg, info in raw_vulns.items():
            if not isinstance(info, dict):
                continue
            sev = _norm_sev(info.get("severity"))
            via = info.get("via") or []
            fix_avail = info.get("fixAvailable")
            fixed = fix_avail.get("version") if isinstance(fix_avail, dict) else ("available" if fix_avail is True else None)
            added = False
            for item in via:
                if isinstance(item, dict):
                    adv_id = str(item.get("source") or item.get("url") or f"NPM-{pkg}")
                    title = str(item.get("title") or f"Vulnerability in {pkg}")[:240]
                    vulns.append({
                        "id": adv_id,
                        "advisory_id": adv_id,
                        "package": str(pkg),
                        "installed_version": str(info.get("range") or ""),
                        "fixed_version": fixed,
                        "severity": _norm_sev(item.get("severity") or sev),
                        "ecosystem": "npm",
                        "source": "npm-audit",
                        "source_file": source_rel,
                        "summary": title,
                    })
                    added = True
            if not added:
                vulns.append({
                    "id": f"NPM-{pkg}",
                    "advisory_id": f"NPM-{pkg}",
                    "package": str(pkg),
                    "installed_version": str(info.get("range") or ""),
                    "fixed_version": fixed,
                    "severity": sev,
                    "ecosystem": "npm",
                    "source": "npm-audit",
                    "source_file": source_rel,
                    "summary": f"Transitive vulnerability in {pkg}",
                })
    return vulns


def _parse_osv_scanner(data: Any, source_rel: str) -> list[dict[str, Any]]:
    vulns: list[dict[str, Any]] = []
    if not isinstance(data, dict):
        return vulns
    for res in data.get("results") or []:
        if not isinstance(res, dict):
            continue
        for pkg_entry in res.get("packages") or []:
            if not isinstance(pkg_entry, dict):
                continue
            pinfo = pkg_entry.get("package") or {}
            pkg = str(pinfo.get("name", ""))
            ver = str(pinfo.get("version", ""))
            eco = str(pinfo.get("ecosystem", "unknown")).lower()
            for v in pkg_entry.get("vulnerabilities") or []:
                if not isinstance(v, dict):
                    continue
                vid = str(v.get("id") or "OSV-UNKNOWN")
                aliases = v.get("aliases") or []
                cve_id = next((str(a) for a in aliases if str(a).startswith("CVE-")), vid)
                db_spec = v.get("database_specific") or {}
                sev = _norm_sev(db_spec.get("severity") or "MEDIUM")
                vulns.append({
                    "id": cve_id,
                    "advisory_id": vid,
                    "package": pkg,
                    "installed_version": ver,
                    "fixed_version": None,
                    "severity": sev,
                    "ecosystem": eco,
                    "source": "osv-scanner",
                    "source_file": source_rel,
                    "summary": str(v.get("summary") or f"OSV {cve_id} in {pkg}")[:240],
                })
    return vulns


def _parse_trivy(data: Any, source_rel: str) -> list[dict[str, Any]]:
    vulns: list[dict[str, Any]] = []
    if not isinstance(data, dict):
        return vulns
    for res in data.get("Results") or []:
        if not isinstance(res, dict):
            continue
        eco = str(res.get("Type") or "unknown").lower()
        for v in res.get("Vulnerabilities") or []:
            if not isinstance(v, dict):
                continue
            vid = str(v.get("VulnerabilityID") or "TRIVY-UNKNOWN")
            pkg = str(v.get("PkgName") or "")
            ver = str(v.get("InstalledVersion") or "")
            fixed = str(v.get("FixedVersion") or "") or None
            sev = _norm_sev(v.get("Severity"))
            vulns.append({
                "id": vid,
                "advisory_id": vid,
                "package": pkg,
                "installed_version": ver,
                "fixed_version": fixed,
                "severity": sev,
                "ecosystem": eco,
                "source": "trivy",
                "source_file": source_rel,
                "summary": str(v.get("Title") or v.get("Description") or f"{vid} in {pkg}")[:240],
            })
    return vulns


def _enrich_sbom(data_dir: Path, vulns: list[dict[str, Any]]) -> int:
    """Correlate CVEs with sbom.cdx.json components and populate CycloneDX 1.5 vulnerabilities[]."""
    sbom_path = data_dir / "sbom.cdx.json"
    if not sbom_path.is_file():
        return 0
    try:
        sbom = json.loads(sbom_path.read_text(encoding="utf-8"))
    except Exception:
        return 0
    if not isinstance(sbom, dict):
        return 0

    comp_map: dict[str, str] = {}
    for comp in sbom.get("components") or []:
        if isinstance(comp, dict) and comp.get("name"):
            cname = str(comp["name"]).lower()
            ref = str(comp.get("purl") or comp.get("bom-ref") or comp["name"])
            comp_map[cname] = ref

    correlated = 0
    cdx_vulns: list[dict[str, Any]] = []
    for v in vulns:
        pkg_low = str(v.get("package", "")).lower()
        matched_ref = comp_map.get(pkg_low)
        v["in_sbom"] = matched_ref is not None
        if matched_ref is not None:
            v["sbom_ref"] = matched_ref
            correlated += 1
        cdx_vulns.append({
            "id": v["id"],
            "source": {"name": v["source"]},
            "ratings": [{"severity": str(v["severity"]).lower()}],
            "description": v["summary"],
            "affects": [{"ref": matched_ref or v["package"]}],
        })

    if cdx_vulns:
        sbom["vulnerabilities"] = cdx_vulns[:200]
        try:
            sbom_path.write_text(json.dumps(sbom, indent=2), encoding="utf-8")
        except OSError:
            pass
    return correlated


def generate_cve_report(project_dir: Path, data_dir: Path) -> dict[str, Any]:
    """Ingest optional local CVE JSON reports (pip-audit, npm-audit, osv-scanner, trivy) and correlate with SBOM."""
    project_dir = Path(project_dir).resolve()
    data_dir = Path(data_dir)

    search_dirs = [
        project_dir,
        project_dir / "reports",
        project_dir / "security",
        project_dir / "backend",
        project_dir / "frontend",
        data_dir,
    ]
    parsers = {
        "pip-audit": _parse_pip_audit,
        "npm-audit": _parse_npm_audit,
        "osv-scanner": _parse_osv_scanner,
        "trivy": _parse_trivy,
    }

    sources_found: list[dict[str, str]] = []
    seen_files: set[Path] = set()
    vulns: list[dict[str, Any]] = []

    for sdir in search_dirs:
        if not sdir.is_dir():
            continue
        for fname, kind in _REPORT_CANDIDATES:
            cand = (sdir / fname).resolve()
            if not cand.is_file() or cand in seen_files:
                continue
            seen_files.add(cand)
            try:
                raw = json.loads(cand.read_text(encoding="utf-8"))
            except Exception:
                continue
            try:
                rel = str(cand.relative_to(project_dir)).replace("\\", "/")
            except ValueError:
                rel = cand.name
            parsed = parsers[kind](raw, rel)
            sources_found.append({"tool": kind, "file": rel, "count": str(len(parsed))})
            vulns.extend(parsed)

    # Deduplicate by (id, package, installed_version)
    dedup: dict[tuple[str, str, str], dict[str, Any]] = {}
    for v in vulns:
        key = (str(v["id"]), str(v["package"]).lower(), str(v["installed_version"]))
        if key not in dedup:
            dedup[key] = v
    unique_vulns = list(dedup.values())
    unique_vulns.sort(key=lambda v: (_SEV_ORDER.get(str(v["severity"]), 4), str(v["package"]).lower(), str(v["id"])))

    correlated_count = _enrich_sbom(data_dir, unique_vulns)

    crit = sum(1 for v in unique_vulns if v["severity"] == "CRITICAL")
    high = sum(1 for v in unique_vulns if v["severity"] == "HIGH")
    med = sum(1 for v in unique_vulns if v["severity"] == "MEDIUM")
    low = sum(1 for v in unique_vulns if v["severity"] == "LOW")

    payload: dict[str, Any] = {
        "generated_at": time.time(),
        "available": len(sources_found) > 0,
        "sources": sources_found,
        "summary": {
            "total": len(unique_vulns),
            "critical": crit,
            "high": high,
            "medium": med,
            "low": low,
            "sbom_correlated": correlated_count,
        },
        "vulnerabilities": unique_vulns[:200],
    }

    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "cve-report.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    (data_dir / "cve_report.js").write_text(f"window.CVE_REPORT = {json.dumps(payload)};\n", encoding="utf-8")
    return payload
