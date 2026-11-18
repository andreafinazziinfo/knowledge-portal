"""
Universal Tech Stack, Dependencies, Infrastructure & Repository Ecosystem Scanner.
Zero external dependencies (Python stdlib only).
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any


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
                    if stripped.startswith("]"):
                        in_deps = False
                        continue
                    item = stripped.strip('", ')
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


def generate_stack_inventory(target_dir: Path, output_dir: Path) -> dict[str, Any]:
    """Scan target_dir for dependencies, containers, dev tools, and repositories."""
    py_deps = _scan_python_deps(target_dir)
    node_deps = _scan_node_deps(target_dir)
    docker_svcs = _scan_docker_services(target_dir)
    tools = _scan_tools_and_ci(target_dir)
    repos = _scan_repositories(target_dir)

    all_deps = py_deps + node_deps
    payload = {
        "schema_version": "1.0.0",
        "project": target_dir.name,
        "summary": {
            "total_dependencies": len(all_deps),
            "python_dependencies": len(py_deps),
            "node_dependencies": len(node_deps),
            "docker_services": len(docker_svcs),
            "tools_and_ci": len(tools),
            "repositories": len(repos),
        },
        "dependencies": all_deps,
        "docker_services": docker_svcs,
        "tools": tools,
        "repositories": repos,
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "stack-ecosystem.json"
    js_path = output_dir / "stack_ecosystem.js"
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    js_path.write_text(f"window.STACK_ECOSYSTEM = {json.dumps(payload)};\n", encoding="utf-8")

    # Mirror to views/data if output_dir is .../data
    views_data = output_dir.parent / "views" / "data"
    if views_data.exists() or output_dir.name == "data":
        views_data.mkdir(parents=True, exist_ok=True)
        (views_data / "stack-ecosystem.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
        (views_data / "stack_ecosystem.js").write_text(f"window.STACK_ECOSYSTEM = {json.dumps(payload)};\n", encoding="utf-8")

    return payload
