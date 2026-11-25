"""
Universal Tech Stack, Dependencies, Infrastructure & Repository Ecosystem Scanner.
Zero external dependencies (Python stdlib only).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

_PERMISSIVE_LICENSES = ("mit", "apache", "bsd", "isc", "unlicense", "cc0", "0bsd", "psf", "python")
_WEAK_COPYLEFT = ("lgpl", "mpl", "epl", "cddl")
_STRONG_COPYLEFT = ("gpl", "agpl", "sspl")


def _classify_license(lic: str) -> str:
    low = (lic or "").strip().lower()
    if not low or low in ("unknown", "none"):
        return "Unknown"
    if any(k in low for k in _STRONG_COPYLEFT) and "lgpl" not in low:
        return "Copyleft"
    if any(k in low for k in _WEAK_COPYLEFT):
        return "Weak-Copyleft"
    if any(k in low for k in _PERMISSIVE_LICENSES):
        return "Permissive"
    return "Other"


def _detect_project_license(root: Path) -> str:
    for cand in ("LICENSE", "LICENSE.md", "LICENSE.txt"):
        p = root / cand
        if p.is_file():
            head = p.read_text(encoding="utf-8", errors="ignore")[:800].lower()
            if "mit license" in head or "permission is hereby granted, free of charge" in head:
                return "MIT"
            if "apache license" in head:
                return "Apache-2.0"
            if "affero general public license" in head:
                return "AGPL-3.0"
            if "gnu general public license" in head:
                return "GPL-3.0"
            if "bsd" in head:
                return "BSD"
    pp = root / "pyproject.toml"
    if pp.is_file():
        m = re.search(r"""license\s*=\s*(?:\{[^}]*text\s*=\s*)?["']([^"']+)["']""", pp.read_text(encoding="utf-8", errors="ignore"))
        if m:
            return m.group(1)
    pj = root / "package.json"
    if pj.is_file():
        try:
            lic = json.loads(pj.read_text(encoding="utf-8", errors="ignore")).get("license")
            if isinstance(lic, str) and lic.strip():
                return lic.strip()
        except Exception:
            pass
    return "Unknown"


def _resolve_node_license(root: Path, pkg_name: str) -> str:
    for base in (root / "node_modules", root / "frontend" / "node_modules"):
        p = base / pkg_name / "package.json"
        if p.is_file():
            try:
                data = json.loads(p.read_text(encoding="utf-8", errors="ignore"))
                lic = data.get("license")
                if isinstance(lic, str) and lic.strip():
                    return lic.strip()
                if isinstance(lic, dict) and lic.get("type"):
                    return str(lic["type"])
            except Exception:
                pass
    return "Unknown"


def _build_cyclonedx_sbom(project_name: str, project_license: str, deps: list[dict[str, Any]]) -> dict[str, Any]:
    components: list[dict[str, Any]] = []
    for d in deps:
        eco = "pypi" if "python" in str(d.get("ecosystem", "")).lower() else "npm"
        ver = str(d.get("version", "*")).lstrip("^~>=< ")
        name = str(d.get("name", "unknown"))
        comp: dict[str, Any] = {
            "type": "library",
            "name": name,
            "version": ver or "*",
            "purl": f"pkg:{eco}/{name}@{ver}" if ver and ver != "*" else f"pkg:{eco}/{name}",
            "scope": "required" if d.get("scope") != "dev" else "optional",
        }
        lic = str(d.get("license") or "")
        if lic and lic != "Unknown":
            comp["licenses"] = [{"license": {"id": lic}}]
        components.append(comp)
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "serialNumber": f"urn:uuid:{uuid.uuid5(uuid.NAMESPACE_DNS, f'knowledge-portal:{project_name}')}",
        "version": 1,
        "metadata": {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "component": {
                "type": "application",
                "name": project_name,
                "licenses": [{"license": {"id": project_license}}] if project_license != "Unknown" else [],
            },
        },
        "components": components,
    }


def _parse_req_line(line: str) -> dict[str, str] | None:
    clean = line.split("#", 1)[0].strip()
    if not clean or clean.startswith(("-", "--", "git+", "http://", "https://")):
        return None
    m = re.match(r"^([A-Za-z0-9_.\-\[\]]+)\s*([><=!~].*)?$", clean)
    if not m:
        return None
    name = m.group(1).strip()
    spec = (m.group(2) or "*").strip()
    return {"name": name, "version": spec}


def _scan_python_deps(root: Path) -> list[dict[str, Any]]:
    deps: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    req_files = sorted(
        p for p in root.rglob("requirements*.txt")
        if not any(part in p.parts for part in (".git", "node_modules", ".venv", "venv", ".claude", "dist"))
    )
    for rf in req_files:
        rel = str(rf.relative_to(root)).replace("\\", "/")
        scope = "dev" if "dev" in rf.name or "test" in rf.name else ("live" if "live" in rf.name else "runtime")
        try:
            for raw_line in rf.read_text(encoding="utf-8", errors="ignore").splitlines():
                parsed = _parse_req_line(raw_line)
                if parsed:
                    key = (parsed["name"].lower(), scope)
                    if key not in seen:
                        seen.add(key)
                        deps.append({
                            "name": parsed["name"],
                            "version": parsed["version"],
                            "ecosystem": "Python / PyPI",
                            "scope": scope,
                            "source": rel,
                        })
        except OSError:
            continue

    # Check pyproject.toml if no requirements or as supplement
    for pp in sorted(
        p for p in root.rglob("pyproject.toml")
        if not any(part in p.parts for part in (".git", "node_modules", ".venv", "venv", ".claude", "dist"))
    ):
        rel = str(pp.relative_to(root)).replace("\\", "/")
        try:
            text = pp.read_text(encoding="utf-8", errors="ignore")
            in_deps = False
            for line in text.splitlines():
                stripped = line.strip()
                if stripped.startswith("dependencies = ["):
                    in_deps = True
                    continue
                if in_deps:
                    if stripped.startswith("]") or stripped.startswith("["):
                        in_deps = False
                        continue
                    item = stripped.strip('", ')
                    if not item or item.startswith("["):
                        continue
                    parsed = _parse_req_line(item)
                    if parsed and (parsed["name"].lower(), "runtime") not in seen:
                        seen.add((parsed["name"].lower(), "runtime"))
                        deps.append({
                            "name": parsed["name"],
                            "version": parsed["version"],
                            "ecosystem": "Python / PyPI",
                            "scope": "runtime",
                            "source": rel,
                        })
        except OSError:
            continue
    return deps


def _scan_node_deps(root: Path) -> list[dict[str, Any]]:
    deps: list[dict[str, Any]] = []
    pkg_files = sorted(
        p for p in root.rglob("package.json")
        if not any(part in p.parts for part in (".git", "node_modules", ".venv", "venv", ".claude", "dist"))
    )
    for pf in pkg_files:
        rel = str(pf.relative_to(root)).replace("\\", "/")
        try:
            data = json.loads(pf.read_text(encoding="utf-8", errors="ignore"))
        except (OSError, json.JSONDecodeError):
            continue
        for section, scope in (("dependencies", "runtime"), ("devDependencies", "dev")):
            block = data.get(section, {})
            if isinstance(block, dict):
                for name, ver in sorted(block.items()):
                    deps.append({
                        "name": name,
                        "version": str(ver),
                        "ecosystem": "Node.js / npm",
                        "scope": scope,
                        "source": rel,
                    })
    return deps


def _scan_docker_services(root: Path) -> list[dict[str, Any]]:
    services: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    compose_files = sorted(
        p for p in root.rglob("docker-compose*.y*ml")
        if not any(part in p.parts for part in (".git", "node_modules", ".claude", "dist"))
    )
    for cf in compose_files:
        rel = str(cf.relative_to(root)).replace("\\", "/")
        try:
            lines = cf.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            continue
        in_services = False
        current_svc: str | None = None
        svc_image = ""
        for raw in lines:
            if not raw.strip() or raw.strip().startswith("#"):
                continue
            indent = len(raw) - len(raw.lstrip(" "))
            stripped = raw.strip()
            if indent == 0 and stripped == "services:":
                in_services = True
                continue
            if indent == 0 and stripped.endswith(":") and stripped != "services:":
                in_services = False
                current_svc = None
                continue
            if in_services and indent == 2 and stripped.endswith(":"):
                if current_svc and (current_svc, rel) not in seen:
                    seen.add((current_svc, rel))
                    services.append({
                        "name": current_svc,
                        "image": svc_image or "custom-build",
                        "source": rel,
                    })
                current_svc = stripped[:-1]
                svc_image = ""
            elif in_services and current_svc and indent >= 4 and stripped.startswith("image:"):
                svc_image = stripped.split(":", 1)[1].strip().strip('"\'')
        if current_svc and (current_svc, rel) not in seen:
            seen.add((current_svc, rel))
            services.append({
                "name": current_svc,
                "image": svc_image or "custom-build",
                "source": rel,
            })
    return services


def _scan_tools_and_ci(root: Path) -> list[dict[str, Any]]:
    tools: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add_tool(name: str, category: str, source: str) -> None:
        if name.lower() not in seen:
            seen.add(name.lower())
            tools.append({"name": name, "category": category, "source": source})

    # CI workflows
    wf_dir = root / ".github" / "workflows"
    if wf_dir.is_dir():
        for wf in sorted(wf_dir.glob("*.y*ml")):
            add_tool(f"GitHub Actions ({wf.stem})", "CI/CD Workflow", f".github/workflows/{wf.name}")

    # Config-based tools
    tool_checks = [
        ("pyproject.toml", r"\[tool\.ruff", "Ruff Linter/Formatter", "Code Quality"),
        ("pyproject.toml", r"\[tool\.pytest", "Pytest Runner", "Testing"),
        ("pyproject.toml", r"\[tool\.coverage", "Coverage.py", "Testing"),
        ("backend/pyproject.toml", r"\[tool\.ruff", "Ruff Linter/Formatter", "Code Quality"),
        ("backend/pyproject.toml", r"\[tool\.pytest", "Pytest Runner", "Testing"),
        ("frontend/package.json", r'"vitest"', "Vitest", "Testing"),
        ("frontend/package.json", r'"playwright"', "Playwright E2E", "Testing"),
        ("frontend/package.json", r'"eslint"', "ESLint", "Code Quality"),
        ("frontend/package.json", r'"vite"', "Vite Bundler", "Build Tool"),
        (".pre-commit-config.yaml", r"gitleaks|trufflehog|pre-commit", "Pre-Commit & Secret Hooks", "Security"),
    ]
    for rel_path, pattern, label, cat in tool_checks:
        p = root / rel_path
        if p.is_file():
            try:
                if re.search(pattern, p.read_text(encoding="utf-8", errors="ignore")):
                    add_tool(label, cat, rel_path)
            except OSError:
                pass

    if (root / ".gitnexus").exists():
        add_tool("GitNexus MCP Index", "AI Code Intelligence", ".gitnexus")
    if (root / "backend" / "alembic").is_dir() or (root / "alembic").is_dir():
        add_tool("Alembic Migrations", "Database Schema", "alembic")

    return tools


def _scan_repositories(root: Path) -> list[dict[str, Any]]:
    repos: list[dict[str, Any]] = []
    if (root / ".git").exists():
        try:
            res = subprocess.run(
                ["git", "remote", "-v"],
                cwd=str(root),
                capture_output=True,
                text=True,
                timeout=5,
            )
            seen_remotes: set[tuple[str, str]] = set()
            for line in res.stdout.splitlines():
                parts = line.split()
                if len(parts) >= 2:
                    rname, rurl = parts[0], parts[1]
                    if (rname, rurl) not in seen_remotes:
                        seen_remotes.add((rname, rurl))
                        repos.append({"name": rname, "url": rurl, "type": "git-remote"})
        except (OSError, subprocess.SubprocessError):
            pass

    gitmodules = root / ".gitmodules"
    if gitmodules.is_file():
        try:
            for line in gitmodules.read_text(encoding="utf-8", errors="ignore").splitlines():
                if line.strip().startswith("url ="):
                    url = line.split("=", 1)[1].strip()
                    repos.append({"name": "submodule", "url": url, "type": "submodule"})
        except OSError:
            pass
    return repos


_ANDROID_NS = "{http://schemas.android.com/apk/res/android}"
_MOBILE_IGNORE_DIRS = frozenset({
    ".git", "node_modules", ".venv", "venv", "build", ".gradle", "dist", "__pycache__", "frozen",
})


def _parse_gradle_metadata(gradle_path: Path, root: Path) -> dict[str, Any]:
    """Extract high-signal Android metadata from build.gradle / build.gradle.kts."""
    meta: dict[str, Any] = {
        "gradle_path": str(gradle_path.relative_to(root)).replace("\\", "/"),
        "namespace": None,
        "applicationId": None,
        "versionName": None,
        "versionCode": None,
        "minifyEnabled": None,
        "dependencies_count": 0,
    }
    try:
        text = gradle_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return meta

    m_ns = re.search(r"""namespace\s*=?\s*["']([^"']+)["']""", text)
    if m_ns:
        meta["namespace"] = m_ns.group(1)
    m_app = re.search(r"""applicationId\s*=?\s*["']([^"']+)["']""", text)
    if m_app:
        meta["applicationId"] = m_app.group(1)
    m_vn = re.search(r"""versionName\s*=?\s*["']([^"']+)["']""", text)
    if m_vn:
        meta["versionName"] = m_vn.group(1)
    m_vc = re.search(r"""versionCode\s*=?\s*(\d+)""", text)
    if m_vc:
        meta["versionCode"] = int(m_vc.group(1))
    m_min = re.search(r"""minifyEnabled\s*=?\s*(true|false)""", text, re.IGNORECASE)
    if m_min:
        meta["minifyEnabled"] = m_min.group(1).lower() == "true"
    deps = re.findall(r"""(?m)^\s*(?:implementation|api|testImplementation|androidTestImplementation)\b""", text)
    meta["dependencies_count"] = len(deps)
    return meta


def _scan_mobile_manifests(root: Path) -> list[dict[str, Any]]:
    """Extract high-signal AndroidManifest.xml and build.gradle metadata without parsing Java/PNG."""
    manifests: list[dict[str, Any]] = []
    manifest_files: list[Path] = []
    gradle_files: list[Path] = []

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _MOBILE_IGNORE_DIRS]
        for fname in filenames:
            if fname == "AndroidManifest.xml":
                manifest_files.append(Path(dirpath) / fname)
            elif fname in ("build.gradle", "build.gradle.kts"):
                gradle_files.append(Path(dirpath) / fname)

    if not manifest_files and not gradle_files:
        return []

    def _find_nearest_gradle(mpath: Path) -> Path | None:
        # Prefer build.gradle in an ancestor directory of AndroidManifest.xml (e.g. app/build.gradle)
        cur = mpath.parent
        for _ in range(5):
            for name in ("build.gradle", "build.gradle.kts"):
                cand = cur / name
                if cand.is_file():
                    return cand
            if cur == root or cur.parent == cur:
                break
            cur = cur.parent
        return gradle_files[0] if gradle_files else None

    used_gradles: set[Path] = set()
    for mpath in sorted(manifest_files):
        rel = str(mpath.relative_to(root)).replace("\\", "/")
        package_name: str | None = None
        uses_cleartext: bool | None = None
        allow_backup: bool | None = None
        permissions: list[str] = []
        exported_components: list[str] = []
        findings: list[dict[str, str]] = []

        try:
            tree = ET.parse(mpath)  # nosec B314
            mroot = tree.getroot()
            package_name = mroot.attrib.get("package") or None
            for perm in mroot.findall("uses-permission"):
                pname = perm.attrib.get(f"{_ANDROID_NS}name") or perm.attrib.get("name")
                if pname:
                    permissions.append(pname)
            app_el = mroot.find("application")
            if app_el is not None:
                ct = app_el.attrib.get(f"{_ANDROID_NS}usesCleartextTraffic")
                if ct is not None:
                    uses_cleartext = ct.lower() == "true"
                ab = app_el.attrib.get(f"{_ANDROID_NS}allowBackup")
                if ab is not None:
                    allow_backup = ab.lower() == "true"
                for tag in ("activity", "service", "receiver", "provider"):
                    for comp in app_el.findall(tag):
                        if (comp.attrib.get(f"{_ANDROID_NS}exported") or "").lower() == "true":
                            cname = comp.attrib.get(f"{_ANDROID_NS}name") or tag
                            exported_components.append(f"{tag}:{cname}")
        except ET.ParseError:
            pass

        gpath = _find_nearest_gradle(mpath)
        gmeta: dict[str, Any] = {}
        if gpath is not None:
            used_gradles.add(gpath)
            gmeta = _parse_gradle_metadata(gpath, root)

        resolved_pkg = package_name or gmeta.get("applicationId") or gmeta.get("namespace")
        if uses_cleartext is True:
            findings.append({
                "severity": "MEDIUM",
                "rule": "ANDROID_CLEARTEXT_TRAFFIC",
                "file": rel,
                "detail": "AndroidManifest.xml sets android:usesCleartextTraffic=\"true\" (allows unencrypted HTTP).",
            })

        uniq_perms = sorted(set(permissions))
        manifests.append({
            "platform": "android",
            "manifest_path": rel,
            "gradle_path": gmeta.get("gradle_path"),
            "package": resolved_pkg,
            "versionName": gmeta.get("versionName"),
            "versionCode": gmeta.get("versionCode"),
            "usesCleartextTraffic": uses_cleartext,
            "allowBackup": allow_backup,
            "minifyEnabled": gmeta.get("minifyEnabled"),
            "permissions_count": len(uniq_perms),
            "permissions": uniq_perms[:40],
            "exported_components": exported_components[:20],
            "dependencies_count": int(gmeta.get("dependencies_count") or 0),
            "security_findings": findings,
        })

    # If only build.gradle exists without AndroidManifest.xml
    if not manifests:
        for gpath in sorted(gradle_files):
            gmeta = _parse_gradle_metadata(gpath, root)
            if gmeta.get("applicationId") or gmeta.get("namespace") or gmeta.get("versionName"):
                manifests.append({
                    "platform": "android",
                    "manifest_path": None,
                    "gradle_path": gmeta.get("gradle_path"),
                    "package": gmeta.get("applicationId") or gmeta.get("namespace"),
                    "versionName": gmeta.get("versionName"),
                    "versionCode": gmeta.get("versionCode"),
                    "usesCleartextTraffic": None,
                    "allowBackup": None,
                    "minifyEnabled": gmeta.get("minifyEnabled"),
                    "permissions_count": 0,
                    "permissions": [],
                    "exported_components": [],
                    "dependencies_count": int(gmeta.get("dependencies_count") or 0),
                    "security_findings": [],
                })

    return manifests


def generate_stack_inventory(target_dir: Path, output_dir: Path) -> dict[str, Any]:
    """Scan target_dir for dependencies, licenses, CycloneDX SBOM, containers, dev tools, mobile manifests, and repositories."""
    py_deps = _scan_python_deps(target_dir)
    node_deps = _scan_node_deps(target_dir)
    docker_svcs = _scan_docker_services(target_dir)
    tools = _scan_tools_and_ci(target_dir)
    repos = _scan_repositories(target_dir)
    mobile_manifests = _scan_mobile_manifests(target_dir)

    proj_license = _detect_project_license(target_dir)
    for d in py_deps:
        d.setdefault("license", "Unknown")
        d["license_risk"] = _classify_license(d["license"])
    for d in node_deps:
        lic = _resolve_node_license(target_dir, str(d.get("name", "")))
        d["license"] = lic
        d["license_risk"] = _classify_license(lic)

    all_deps = py_deps + node_deps
    copyleft_cnt = sum(1 for d in all_deps if d.get("license_risk") == "Copyleft")
    known_lic_cnt = sum(1 for d in all_deps if d.get("license") and d.get("license") != "Unknown")
    sbom = _build_cyclonedx_sbom(target_dir.name, proj_license, all_deps)

    payload = {
        "schema_version": "1.1.0",
        "project": target_dir.name,
        "project_license": proj_license,
        "summary": {
            "total_dependencies": len(all_deps),
            "python_dependencies": len(py_deps),
            "node_dependencies": len(node_deps),
            "docker_services": len(docker_svcs),
            "tools_and_ci": len(tools),
            "repositories": len(repos),
            "mobile_manifests_count": len(mobile_manifests),
            "licenses_detected": known_lic_cnt,
            "copyleft_count": copyleft_cnt,
        },
        "sbom_summary": {
            "bom_format": "CycloneDX",
            "spec_version": "1.5",
            "total_components": len(sbom["components"]),
            "project_license": proj_license,
            "licenses_detected": known_lic_cnt,
            "copyleft_count": copyleft_cnt,
            "sbom_file": "data/sbom.cdx.json",
        },
        "mobile_manifest": mobile_manifests[0] if mobile_manifests else None,
        "mobile_manifests": mobile_manifests,
        "dependencies": all_deps,
        "docker_services": docker_svcs,
        "tools": tools,
        "repositories": repos,
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "stack-ecosystem.json"
    js_path = output_dir / "stack_ecosystem.js"
    sbom_path = output_dir / "sbom.cdx.json"
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    js_path.write_text(f"window.STACK_ECOSYSTEM = {json.dumps(payload)};\n", encoding="utf-8")
    sbom_path.write_text(json.dumps(sbom, indent=2), encoding="utf-8")

    # Mirror to views/data if output_dir is .../data
    views_data = output_dir.parent / "views" / "data"
    if views_data.exists() or output_dir.name == "data":
        views_data.mkdir(parents=True, exist_ok=True)
        (views_data / "stack-ecosystem.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
        (views_data / "stack_ecosystem.js").write_text(f"window.STACK_ECOSYSTEM = {json.dumps(payload)};\n", encoding="utf-8")
        (views_data / "sbom.cdx.json").write_text(json.dumps(sbom, indent=2), encoding="utf-8")

    return payload
