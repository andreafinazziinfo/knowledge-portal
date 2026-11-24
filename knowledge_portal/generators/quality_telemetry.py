"""
Knowledge Portal — Unified Quality Telemetry Ingestor (ADR-080 P1.2).
100% Python stdlib zero-dependency, 100% air-gapped local artifact ingestor:
- Coverage aggregation per domain from coverage.xml (pytest-cov) and lcov.info (Vitest/Jest)
- Optional local CI artifact ingestion (zero-crash if absent):
  * JUnit XML (junit*.xml, test-results*.xml, pytest-junit*.xml)
  * Ruff JSON (ruff-report.json, ruff.json)
  * Mypy JSON / text (mypy-report.json, mypy.txt)
  * Vue-TSC / TSC output (tsc-report.txt, typecheck.log, vue-tsc.log)

Outputs `data/quality-telemetry.json` and embeds into `arch-health.json` (`health_v4.quality_telemetry`).
"""

from __future__ import annotations

import json
import re
import time
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

_IGNORE_PARTS = frozenset({
    ".git", "node_modules", "dist", "dev-dist", "build", ".venv", "venv",
    "__pycache__", ".idea", ".vscode", "target", "vendor", "frozen",
})

_MYPY_LINE_RE = re.compile(r"^([^:\s][^:]*):(\d+)(?::(\d+))?:\s*(error|warning|note):\s*(.+?)(?:\s+\[([^\]]+)\])?$")
_TSC_PAREN_RE = re.compile(r"^([^\s(][^(]*)\((\d+),(\d+)\):\s*(error|warning)\s+(TS\d+):\s*(.+)$")
_TSC_COLON_RE = re.compile(r"^([^\s:][^:]*):(\d+):(\d+)\s*-\s*(error|warning)\s+(TS\d+):\s*(.+)$")


def _is_ignored(rel: str) -> bool:
    parts = [p.lower() for p in rel.replace("\\", "/").split("/") if p]
    return any(p in _IGNORE_PARTS for p in parts)


def _domain_bucket(rel: str) -> str:
    parts = [p for p in rel.replace("\\", "/").lstrip("./").split("/") if p]
    if not parts:
        return "root"
    if len(parts) >= 3 and parts[0] in ("backend", "frontend", "src", "packages"):
        return f"{parts[0]}/{parts[1]}/{parts[2]}" if parts[1] in ("app", "src") else f"{parts[0]}/{parts[1]}"
    if len(parts) >= 2:
        return f"{parts[0]}/{parts[1]}"
    return parts[0]


def _parse_coverage_by_domain(project_dir: Path) -> dict[str, Any]:
    files_cov: dict[str, float] = {}
    sources: list[str] = []

    cov_xml_cands = [
        project_dir / "coverage.xml",
        project_dir / "backend" / "coverage.xml",
        project_dir / "reports" / "coverage.xml",
    ]
    for cand in cov_xml_cands:
        if cand.exists() and cand.is_file():
            try:
                tree = ET.parse(cand)  # nosec B314
                matched = 0
                for cls in tree.getroot().findall(".//class"):
                    fn = cls.attrib.get("filename", "")
                    rate = cls.attrib.get("line-rate")
                    if fn and rate is not None and not _is_ignored(fn):
                        norm_fn = fn.replace("\\", "/").lstrip("./")
                        if cand.parent.name == "backend" and not norm_fn.startswith("backend/"):
                            norm_fn = f"backend/{norm_fn}"
                        files_cov[norm_fn] = round(float(rate) * 100.0, 1)
                        matched += 1
                if matched > 0:
                    sources.append(str(cand.relative_to(project_dir)).replace("\\", "/"))
            except Exception:
                pass

    lcov_cands = [
        project_dir / "coverage" / "lcov.info",
        project_dir / "frontend" / "coverage" / "lcov.info",
        project_dir / "reports" / "lcov.info",
    ]
    for cand in lcov_cands:
        if cand.exists() and cand.is_file():
            try:
                cur_f = ""
                lf = lh = 0
                matched = 0
                for line in cand.read_text(encoding="utf-8", errors="ignore").splitlines():
                    if line.startswith("SF:"):
                        cur_f = line[3:].strip().replace("\\", "/").lstrip("./")
                        lf = lh = 0
                    elif line.startswith("LF:"):
                        lf = int(line[3:] or 0)
                    elif line.startswith("LH:"):
                        lh = int(line[3:] or 0)
                    elif line == "end_of_record" and cur_f and lf > 0 and not _is_ignored(cur_f):
                        norm_fn = cur_f
                        if "frontend" in cand.parts and not norm_fn.startswith("frontend/"):
                            norm_fn = f"frontend/{norm_fn}"
                        files_cov[norm_fn] = round(100.0 * lh / lf, 1)
                        matched += 1
                if matched > 0:
                    sources.append(str(cand.relative_to(project_dir)).replace("\\", "/"))
            except Exception:
                pass

    if not files_cov:
        return {
            "available": False,
            "overall_pct": None,
            "files_measured": 0,
            "sources": [],
            "by_domain": [],
            "lowest_covered": [],
        }

    dom_vals: dict[str, list[float]] = defaultdict(list)
    for fpath, pct in files_cov.items():
        dom_vals[_domain_bucket(fpath)].append(pct)

    by_domain = [
        {
            "domain": dom,
            "coverage_pct": round(sum(vals) / len(vals), 1),
            "files_measured": len(vals),
        }
        for dom, vals in sorted(dom_vals.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    ]
    overall = round(sum(files_cov.values()) / len(files_cov), 1)
    lowest = [{"path": p, "coverage_pct": pct} for p, pct in sorted(files_cov.items(), key=lambda kv: kv[1])[:20]]
    return {
        "available": True,
        "overall_pct": overall,
        "files_measured": len(files_cov),
        "sources": sorted(set(sources)),
        "by_domain": by_domain[:30],
        "lowest_covered": lowest,
    }


def _find_candidate_files(project_dir: Path, patterns: tuple[str, ...]) -> list[Path]:
    found: list[Path] = []
    seen: set[Path] = set()
    search_dirs = [
        project_dir,
        project_dir / "reports",
        project_dir / "test-results",
        project_dir / "backend",
        project_dir / "backend" / "reports",
        project_dir / "frontend",
        project_dir / "frontend" / "reports",
    ]
    for sdir in search_dirs:
        if not sdir.exists() or not sdir.is_dir():
            continue
        for pat in patterns:
            for p in sorted(sdir.glob(pat)):
                if p.is_file() and p not in seen:
                    seen.add(p)
                    found.append(p)
    return found


def _parse_junit_reports(project_dir: Path) -> dict[str, Any]:
    cands = _find_candidate_files(project_dir, ("junit*.xml", "test-results*.xml", "pytest-junit*.xml"))
    sources: list[str] = []
    tests_total = 0
    failures = 0
    errors = 0
    skipped = 0
    duration_sec = 0.0
    all_cases: list[dict[str, Any]] = []
    failed_cases: list[dict[str, Any]] = []

    for cand in cands:
        try:
            tree = ET.parse(cand)  # nosec B314
            root = tree.getroot()
        except Exception:
            continue
        testcases = root.findall(".//testcase")
        if not testcases and root.tag not in ("testsuite", "testsuites"):
            continue
        rel = str(cand.relative_to(project_dir)).replace("\\", "/")
        sources.append(rel)

        for tc in testcases:
            tests_total += 1
            t_sec = 0.0
            try:
                t_sec = float(tc.attrib.get("time", "0") or 0.0)
            except ValueError:
                t_sec = 0.0
            duration_sec += t_sec
            name = tc.attrib.get("name", "unknown")
            cls = tc.attrib.get("classname", "")
            tfile = tc.attrib.get("file", "") or cls.replace(".", "/")
            all_cases.append({
                "name": name,
                "classname": cls,
                "file": tfile,
                "time_sec": round(t_sec, 3),
                "source": rel,
            })
            fail_el = tc.find("failure")
            err_el = tc.find("error")
            skip_el = tc.find("skipped")
            if fail_el is not None:
                failures += 1
                failed_cases.append({
                    "name": name,
                    "classname": cls,
                    "file": tfile,
                    "kind": "failure",
                    "message": (fail_el.attrib.get("message") or (fail_el.text or ""))[:180].strip(),
                })
            elif err_el is not None:
                errors += 1
                failed_cases.append({
                    "name": name,
                    "classname": cls,
                    "file": tfile,
                    "kind": "error",
                    "message": (err_el.attrib.get("message") or (err_el.text or ""))[:180].strip(),
                })
            elif skip_el is not None:
                skipped += 1

    if not sources:
        return {
            "available": False,
            "sources": [],
            "tests_total": 0,
            "passed": 0,
            "failures": 0,
            "errors": 0,
            "skipped": 0,
            "pass_rate_pct": None,
            "duration_sec": 0.0,
            "slowest_tests": [],
            "failed_tests": [],
        }

    passed = max(0, tests_total - failures - errors - skipped)
    pass_rate = round(100.0 * passed / tests_total, 1) if tests_total > 0 else 100.0
    all_cases.sort(key=lambda c: -float(c["time_sec"]))
    return {
        "available": True,
        "sources": sources,
        "tests_total": tests_total,
        "passed": passed,
        "failures": failures,
        "errors": errors,
        "skipped": skipped,
        "pass_rate_pct": pass_rate,
        "duration_sec": round(duration_sec, 2),
        "slowest_tests": all_cases[:10],
        "failed_tests": failed_cases[:25],
    }


def _parse_ruff_reports(project_dir: Path) -> dict[str, Any]:
    cands = _find_candidate_files(project_dir, ("ruff-report.json", "ruff.json"))
    sources: list[str] = []
    by_code: Counter[str] = Counter()
    by_file: Counter[str] = Counter()
    findings: list[dict[str, Any]] = []

    for cand in cands:
        try:
            raw = json.loads(cand.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            continue
        if not isinstance(raw, list):
            continue
        sources.append(str(cand.relative_to(project_dir)).replace("\\", "/"))
        for item in raw:
            if not isinstance(item, dict):
                continue
            code = str(item.get("code") or "RUFF")
            fname = str(item.get("filename") or "").replace("\\", "/")
            if str(project_dir).replace("\\", "/") in fname:
                fname = fname.split(str(project_dir).replace("\\", "/"), 1)[-1].lstrip("/")
            loc = item.get("location") or {}
            line = int(loc.get("row", 1) or 1)
            msg = str(item.get("message") or "")[:180]
            prefix = re.match(r"([A-Z]+)", code)
            by_code[prefix.group(1) if prefix else code] += 1
            if fname:
                by_file[fname] += 1
            if len(findings) < 50:
                findings.append({
                    "code": code,
                    "path": fname,
                    "line": line,
                    "message": msg,
                })

    if not sources:
        return {"available": False, "sources": [], "total": 0, "by_code": {}, "top_files": [], "findings": []}
    return {
        "available": True,
        "sources": sources,
        "total": sum(by_code.values()),
        "by_code": dict(by_code.most_common(15)),
        "top_files": [{"path": p, "count": c} for p, c in by_file.most_common(10)],
        "findings": findings,
    }


def _parse_mypy_reports(project_dir: Path) -> dict[str, Any]:
    cands = _find_candidate_files(project_dir, ("mypy-report.json", "mypy.json", "mypy-report.txt", "mypy.txt"))
    sources: list[str] = []
    by_domain: Counter[str] = Counter()
    by_code: Counter[str] = Counter()
    findings: list[dict[str, Any]] = []
    total = 0

    for cand in cands:
        try:
            text = cand.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        rel = str(cand.relative_to(project_dir)).replace("\\", "/")
        parsed_any = False
        if cand.suffix == ".json":
            items: list[dict[str, Any]] = []
            try:
                loaded = json.loads(text)
                if isinstance(loaded, list):
                    items = [x for x in loaded if isinstance(x, dict)]
            except Exception:
                for ln in text.splitlines():
                    ln = ln.strip()
                    if ln.startswith("{"):
                        try:
                            obj = json.loads(ln)
                            if isinstance(obj, dict):
                                items.append(obj)
                        except Exception:
                            pass
            for item in items:
                sev = str(item.get("severity", "error")).lower()
                if sev != "error":
                    continue
                parsed_any = True
                total += 1
                fp = str(item.get("file", "")).replace("\\", "/")
                code = str(item.get("code") or "mypy")
                by_domain[_domain_bucket(fp)] += 1
                by_code[code] += 1
                if len(findings) < 50:
                    findings.append({
                        "path": fp,
                        "line": int(item.get("line", 1) or 1),
                        "code": code,
                        "message": str(item.get("message", ""))[:180],
                    })
            if items or text.strip() in ("[]", ""):
                parsed_any = True
        else:
            for ln in text.splitlines():
                m = _MYPY_LINE_RE.match(ln.strip())
                if not m:
                    continue
                fp, line_s, _col, sev, msg, code = m.groups()
                if sev != "error":
                    continue
                parsed_any = True
                total += 1
                fp_norm = fp.replace("\\", "/")
                by_domain[_domain_bucket(fp_norm)] += 1
                by_code[code or "mypy"] += 1
                if len(findings) < 50:
                    findings.append({
                        "path": fp_norm,
                        "line": int(line_s),
                        "code": code or "mypy",
                        "message": msg.strip()[:180],
                    })
            if "Success: no issues found" in text:
                parsed_any = True
        if parsed_any:
            sources.append(rel)

    if not sources:
        return {"available": False, "sources": [], "total": 0, "by_domain": {}, "by_code": {}, "findings": []}
    return {
        "available": True,
        "sources": sources,
        "total": total,
        "by_domain": dict(by_domain.most_common(15)),
        "by_code": dict(by_code.most_common(15)),
        "findings": findings,
    }


def _parse_tsc_reports(project_dir: Path) -> dict[str, Any]:
    cands = _find_candidate_files(project_dir, ("tsc-report.txt", "typecheck.log", "vue-tsc.log", "vue-tsc-report.txt"))
    sources: list[str] = []
    by_code: Counter[str] = Counter()
    by_domain: Counter[str] = Counter()
    findings: list[dict[str, Any]] = []
    total = 0

    for cand in cands:
        try:
            text = cand.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        rel = str(cand.relative_to(project_dir)).replace("\\", "/")
        sources.append(rel)
        for ln in text.splitlines():
            s = ln.strip()
            m = _TSC_PAREN_RE.match(s) or _TSC_COLON_RE.match(s)
            if not m:
                continue
            fp, line_s, _col, sev, code, msg = m.groups()
            if sev != "error":
                continue
            total += 1
            fp_norm = fp.replace("\\", "/")
            by_code[code] += 1
            by_domain[_domain_bucket(fp_norm)] += 1
            if len(findings) < 50:
                findings.append({
                    "path": fp_norm,
                    "line": int(line_s),
                    "code": code,
                    "message": msg.strip()[:180],
                })

    if not sources:
        return {"available": False, "sources": [], "total": 0, "by_domain": {}, "by_code": {}, "findings": []}
    return {
        "available": True,
        "sources": sources,
        "total": total,
        "by_domain": dict(by_domain.most_common(15)),
        "by_code": dict(by_code.most_common(15)),
        "findings": findings,
    }


def analyze_quality_telemetry(
    project_dir: Path,
    data_dir: Path | None = None,
) -> dict[str, Any]:
    """Ingest local air-gapped coverage, JUnit, Ruff, Mypy, and Vue-TSC/TSC telemetry artifacts."""
    project_dir = Path(project_dir).resolve()
    cov = _parse_coverage_by_domain(project_dir)
    junit = _parse_junit_reports(project_dir)
    ruff = _parse_ruff_reports(project_dir)
    mypy = _parse_mypy_reports(project_dir)
    tsc = _parse_tsc_reports(project_dir)

    sources_found = (
        cov["sources"]
        + junit["sources"]
        + ruff["sources"]
        + mypy["sources"]
        + tsc["sources"]
    )
    payload: dict[str, Any] = {
        "generated_at": time.time(),
        "available": bool(sources_found),
        "sources_found": sorted(set(sources_found)),
        "coverage": cov,
        "junit": junit,
        "ruff": ruff,
        "typecheck": {
            "mypy": mypy,
            "tsc": tsc,
            "total_errors": int(mypy["total"]) + int(tsc["total"]),
        },
        "summary": {
            "sources_count": len(set(sources_found)),
            "coverage_pct": cov["overall_pct"],
            "coverage_domains": len(cov["by_domain"]),
            "junit_total": junit["tests_total"],
            "junit_failed": int(junit["failures"]) + int(junit["errors"]),
            "ruff_issues": ruff["total"],
            "mypy_errors": mypy["total"],
            "tsc_errors": tsc["total"],
        },
    }

    if data_dir is not None:
        d = Path(data_dir)
        d.mkdir(parents=True, exist_ok=True)
        (d / "quality-telemetry.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload
