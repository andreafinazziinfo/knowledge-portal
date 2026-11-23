"""
Knowledge Portal — IaC, Runtime & CI/CD Topology Scanner (ADR-078).
100% Python stdlib zero-dependency analyzer extracting:
- Dockerfiles: base images, :latest tags, USER root risk, EXPOSE ports, multi-stage hygiene
- docker-compose*.yml: services, images, published ports, depends_on edges
- Nginx / Caddy configs: upstream proxies & listen ports
- Terraform (*.tf) & Kubernetes YAML manifests
- GitHub Actions (.github/workflows/*.yml): triggers, jobs, unpinned third-party actions

Outputs `data/iac-topology.json` and `data/iac_topology.js`.
Strictly enforces P4 Gate (excludes frozen/).
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any

_IGNORE_DIRS = frozenset({
    "node_modules", "dist", "build", ".venv", "venv",
    "__pycache__", ".idea", ".vscode", "target", "vendor", "bin", "obj", "frozen",
})
_USES_RE = re.compile(r"uses:\s*([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:@[A-Za-z0-9_./-]+)?)")
_SHA_PIN_RE = re.compile(r"@[0-9a-f]{40}$")
_TF_RES_RE = re.compile(r'resource\s+"([^"]+)"\s+"([^"]+)"')
_NGINX_PROXY_RE = re.compile(r"proxy_pass\s+([^;\s]+);")
_NGINX_LISTEN_RE = re.compile(r"listen\s+([0-9:.*\[\]]+)")


def _is_ignored(rel: str) -> bool:
    parts = [p.lower() for p in rel.replace("\\", "/").split("/")]
    return any(p in _IGNORE_DIRS for p in parts)


def generate_iac_topology(project_dir: Path, data_dir: Path) -> dict[str, Any]:
    """Scan IaC, Docker, Nginx, Terraform, K8s, and GitHub Actions workflows."""
    project_dir = Path(project_dir).resolve()
    data_dir = Path(data_dir)

    dockerfiles: list[dict[str, Any]] = []
    compose_services: list[dict[str, Any]] = []
    nginx_proxies: list[dict[str, Any]] = []
    ci_workflows: list[dict[str, Any]] = []
    terraform_resources: list[dict[str, Any]] = []
    k8s_workloads: list[dict[str, Any]] = []
    misconfigs: list[dict[str, Any]] = []

    for root, dirs, files in os.walk(project_dir):
        dirs[:] = [d for d in dirs if d not in _IGNORE_DIRS and (not d.startswith(".") or d == ".github")]
        for fname in files:
            fpath = Path(root) / fname
            rel = str(fpath.relative_to(project_dir)).replace("\\", "/")
            if _is_ignored(rel):
                continue
            low = fname.lower()

            # 1. Dockerfiles
            if low == "dockerfile" or low.startswith("dockerfile.") or low.endswith(".dockerfile"):
                try:
                    lines = fpath.read_text(encoding="utf-8", errors="ignore").splitlines()
                except OSError:
                    continue
                bases: list[str] = []
                ports: list[str] = []
                has_non_root = False
                for lineno, ln in enumerate(lines, 1):
                    s = ln.strip()
                    if s.upper().startswith("FROM "):
                        img = s.split()[1]
                        bases.append(img)
                        if img.endswith(":latest") or (":" not in img and "@" not in img and img.lower() != "scratch"):
                            misconfigs.append({"severity": "MEDIUM", "rule": "DOCKER_UNPINNED_BASE", "file": rel, "line": lineno, "detail": f"Base image `{img}` is not pinned to a specific version/digest."})
                    elif s.upper().startswith("EXPOSE "):
                        ports.extend(s.split()[1:])
                    elif s.upper().startswith("USER "):
                        u = s.split()[1].strip().lower()
                        if u not in ("root", "0", "0:0"):
                            has_non_root = True
                if bases and not has_non_root:
                    misconfigs.append({"severity": "HIGH", "rule": "DOCKER_ROOT_USER", "file": rel, "line": 1, "detail": "Dockerfile does not drop privileges with a non-root `USER` directive."})
                dockerfiles.append({"file": rel, "base_images": bases, "exposed_ports": ports, "multi_stage": len(bases) > 1, "non_root": has_non_root})

            # 2. docker-compose*.yml
            elif low.startswith("docker-compose") and low.endswith((".yml", ".yaml")):
                try:
                    lines = fpath.read_text(encoding="utf-8", errors="ignore").splitlines()
                except OSError:
                    continue
                in_svc = False
                cur: dict[str, Any] | None = None
                in_ports = False
                in_deps = False
                for ln in lines:
                    s = ln.strip()
                    if not s or s.startswith("#"):
                        continue
                    indent = len(ln) - len(ln.lstrip(" "))
                    if indent == 0 and s == "services:":
                        in_svc = True
                        continue
                    if indent == 0 and s.endswith(":"):
                        in_svc = False
                        cur = None
                        continue
                    if in_svc and indent == 2 and s.endswith(":"):
                        if cur:
                            compose_services.append(cur)
                        cur = {"name": s[:-1], "image": "build", "ports": [], "depends_on": [], "file": rel}
                        in_ports = False
                        in_deps = False
                    elif in_svc and cur and indent == 4:
                        in_ports = s == "ports:"
                        in_deps = s == "depends_on:"
                        if s.startswith("image:"):
                            cur["image"] = s.split(":", 1)[1].strip().strip("\"'")
                    elif in_svc and cur and indent >= 6 and s.startswith("- "):
                        val = s[2:].strip().strip("\"'")
                        if in_ports:
                            cur["ports"].append(val)
                        elif in_deps:
                            cur["depends_on"].append(val)
                if cur:
                    compose_services.append(cur)

            # 3. GitHub Actions Workflows
            elif ".github/workflows/" in rel and low.endswith((".yml", ".yaml")):
                try:
                    text = fpath.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    continue
                actions: list[str] = []
                unpinned_actions = 0
                for lineno, ln in enumerate(text.splitlines(), 1):
                    m = _USES_RE.search(ln)
                    if m:
                        act = m.group(1)
                        actions.append(act)
                        if not _SHA_PIN_RE.search(act) and not act.startswith("./"):
                            unpinned_actions += 1
                            if unpinned_actions <= 3:
                                misconfigs.append({"severity": "MEDIUM", "rule": "GHA_UNPINNED_ACTION", "file": rel, "line": lineno, "detail": f"GitHub Action `{act}` is not pinned to a full commit SHA."})
                ci_workflows.append({"name": Path(rel).stem, "file": rel, "actions_count": len(actions), "unpinned_actions": unpinned_actions})

            # 4. Nginx configs
            elif "nginx" in low and low.endswith(".conf"):
                try:
                    text = fpath.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    continue
                listens = sorted(set(_NGINX_LISTEN_RE.findall(text)))
                proxies = sorted(set(_NGINX_PROXY_RE.findall(text)))
                nginx_proxies.append({"file": rel, "listen": listens[:8], "proxy_pass": proxies[:12]})

            # 5. Terraform (*.tf)
            elif low.endswith(".tf"):
                try:
                    text = fpath.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    continue
                for rtype, rname in _TF_RES_RE.findall(text):
                    terraform_resources.append({"type": rtype, "name": rname, "file": rel})
                if "0.0.0.0/0" in text:
                    misconfigs.append({"severity": "HIGH", "rule": "TF_OPEN_CIDR", "file": rel, "line": 1, "detail": "Open CIDR `0.0.0.0/0` found in Terraform configuration."})

            # 6. Kubernetes manifests
            elif low.endswith((".yml", ".yaml")) and any(k in rel.lower() for k in ("k8s/", "kubernetes/", "helm/", "manifests/")):
                try:
                    text = fpath.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    continue
                m_kind = re.search(r"^kind:\s*(\w+)", text, re.MULTILINE)
                m_name = re.search(r"^\s*name:\s*([a-zA-Z0-9_.-]+)", text, re.MULTILINE)
                if m_kind:
                    k8s_workloads.append({"kind": m_kind.group(1), "name": m_name.group(1) if m_name else Path(rel).stem, "file": rel})

    payload: dict[str, Any] = {
        "generated_at": time.time(),
        "summary": {
            "dockerfiles": len(dockerfiles),
            "compose_services": len(compose_services),
            "nginx_configs": len(nginx_proxies),
            "ci_workflows": len(ci_workflows),
            "terraform_resources": len(terraform_resources),
            "k8s_workloads": len(k8s_workloads),
            "misconfigs_count": len(misconfigs),
        },
        "dockerfiles": dockerfiles[:30],
        "compose_services": compose_services[:60],
        "nginx_proxies": nginx_proxies[:20],
        "ci_workflows": ci_workflows[:30],
        "terraform_resources": terraform_resources[:60],
        "k8s_workloads": k8s_workloads[:60],
        "misconfigs": misconfigs[:50],
    }

    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "iac-topology.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    (data_dir / "iac_topology.js").write_text(f"window.IAC_TOPOLOGY = {json.dumps(payload)};\n", encoding="utf-8")
    return payload
