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
_GHA_SCRIPT_INJECTION_RE = re.compile(
    r"\$\{\{\s*github\.event\.(?:issue\.(?:title|body)|pull_request\.(?:title|body|head\.ref|head\.label)|comment\.body|review\.body|head_commit\.message|discussion\.(?:title|body)|commits\[[^\]]*\]\.message)\s*\}\}"
)
_GHA_PERMISSIONS_RE = re.compile(r"(?m)^\s*permissions\s*:")
_GHA_WRITE_ALL_RE = re.compile(r"(?m)^\s*permissions\s*:\s*write-all\b")
_GHA_PR_TARGET_RE = re.compile(r"(?m)^\s*pull_request_target\s*:|\bon\s*:\s*\[[^\]]*\bpull_request_target\b")
_GHA_ISSUE_COMMENT_RE = re.compile(r"(?m)^\s*issue_comment\s*:|\bon\s*:\s*\[[^\]]*\bissue_comment\b")
_GHA_SELF_HOSTED_RE = re.compile(r"runs-on\s*:.*self-hosted", re.IGNORECASE)
_TF_RES_RE = re.compile(r'resource\s+"([^"]+)"\s+"([^"]+)"')
_NGINX_PROXY_RE = re.compile(r"proxy_pass\s+([^;\s]+);")
_NGINX_LISTEN_RE = re.compile(r"listen\s+([0-9:.*\[\]]+)")
_NGINX_SERVER_NAME_RE = re.compile(r"(?m)^\s*server_name\s+([^;]+);")
_NGINX_UPSTREAM_RE = re.compile(r"(?m)^\s*upstream\s+([A-Za-z0-9_.-]+)\s*\{")
_NGINX_LOCATION_RE = re.compile(r"(?m)^\s*location\s+([^{;\n]+?)\s*\{")
_NGINX_INCLUDE_RE = re.compile(r"(?m)^\s*include\s+([^;\s]+);")
_NGINX_REWRITE_RE = re.compile(r"(?m)^\s*rewrite\s+([^;]+);")
_NGINX_TRY_FILES_RE = re.compile(r"(?m)^\s*try_files\s+([^;]+);")
_NGINX_ADD_HEADER_RE = re.compile(r"(?m)^\s*add_header\s+([A-Za-z0-9_-]+)\s+([^;]+);")
_NGINX_SECURITY_HEADERS = frozenset({
    "content-security-policy",
    "strict-transport-security",
    "x-frame-options",
    "x-content-type-options",
    "referrer-policy",
    "cross-origin-opener-policy",
    "cross-origin-resource-policy",
    "cross-origin-embedder-policy",
    "permissions-policy",
})
_SH_ENV_RE = re.compile(r"\$\{?([A-Z][A-Z0-9_]{2,})\}?")
_SH_BUILTIN_ENVS = frozenset({
    "PATH", "HOME", "PWD", "USER", "SHELL", "IFS", "LINENO", "FUNCNAME",
    "BASH_SOURCE", "SHLVL", "OLDPWD", "UID", "EUID", "PIPESTATUS", "RANDOM",
    "SECONDS", "REPLY", "OPTIND", "OPTARG", "TERM", "LANG", "LC_ALL", "HOSTNAME",
})
_SH_INFRA_CMDS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("docker-compose", re.compile(r"\bdocker[\s-]+compose\b")),
    ("docker", re.compile(r"\bdocker\b")),
    ("pgbackrest", re.compile(r"\bpgbackrest\b")),
    ("psql", re.compile(r"\bpsql\b")),
    ("pg_dump", re.compile(r"\bpg_dump\b")),
    ("systemctl", re.compile(r"\bsystemctl\b")),
    ("rclone", re.compile(r"\brclone\b")),
    ("rsync", re.compile(r"\brsync\b")),
    ("curl", re.compile(r"\bcurl\b")),
    ("kubectl", re.compile(r"\bkubectl\b")),
    ("helm", re.compile(r"\bhelm\b")),
    ("terraform", re.compile(r"\bterraform\b")),
    ("nginx", re.compile(r"\bnginx\b")),
    ("redis-cli", re.compile(r"\bredis-cli\b")),
    ("crontab", re.compile(r"\bcrontab\b")),
    ("ssh", re.compile(r"\bssh\b")),
)
_COMPOSE_ONESHOT_HINTS = ("init", "migrate", "migration", "seed", "backup", "cli", "tool", "certbot")


def _extract_brace_block(text: str, open_idx: int) -> str:
    """Extract balanced `{ ... }` body starting at `open_idx`."""
    depth = 0
    for idx in range(open_idx, len(text)):
        ch = text[idx]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[open_idx + 1 : idx]
    return text[open_idx + 1 :]


def _parse_nginx_conf(rel: str, text: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Parse an Nginx .conf file for listen, upstream, locations, proxy_pass, and security headers."""
    # Strip full-line comments to avoid false positives from commented examples
    uncommented_lines = [ln for ln in text.splitlines() if not ln.lstrip().startswith("#")]
    clean = "\n".join(uncommented_lines)

    listens = sorted(set(_NGINX_LISTEN_RE.findall(clean)))
    proxies = sorted(set(_NGINX_PROXY_RE.findall(clean)))
    server_names = sorted({
        tok for m in _NGINX_SERVER_NAME_RE.findall(clean) for tok in m.split() if tok
    })
    upstreams = sorted(set(_NGINX_UPSTREAM_RE.findall(clean)))
    includes = sorted(set(_NGINX_INCLUDE_RE.findall(clean)))
    has_gzip = bool(re.search(r"(?m)^\s*gzip\s+on\s*;", clean))

    security_headers: dict[str, str] = {}
    nginx_misconfigs: list[dict[str, Any]] = []
    for hdr_name, hdr_val in _NGINX_ADD_HEADER_RE.findall(clean):
        if hdr_name.lower() in _NGINX_SECURITY_HEADERS:
            val_clean = hdr_val.strip()
            security_headers[hdr_name] = val_clean[:200]
            if hdr_name.lower() == "content-security-policy" and "'unsafe-eval'" in val_clean.lower():
                nginx_misconfigs.append({
                    "severity": "MEDIUM",
                    "rule": "NGINX_CSP_UNSAFE_EVAL",
                    "file": rel,
                    "line": 1,
                    "detail": "Nginx Content-Security-Policy allows `'unsafe-eval'`.",
                    "remediation": "Remove `'unsafe-eval'` from CSP or scope strictly to isolated worker routes.",
                })

    locations: list[dict[str, Any]] = []
    server_includes_sec = any("security" in inc.lower() for inc in includes)
    for m in _NGINX_LOCATION_RE.finditer(clean):
        loc_path = m.group(1).strip()
        brace_idx = clean.find("{", m.start())
        body = _extract_brace_block(clean, brace_idx) if brace_idx != -1 else ""
        loc_proxies = sorted(set(_NGINX_PROXY_RE.findall(body)))
        loc_rewrites = [r.strip() for r in _NGINX_REWRITE_RE.findall(body)]
        loc_try = [t.strip() for t in _NGINX_TRY_FILES_RE.findall(body)]
        loc_includes = sorted(set(_NGINX_INCLUDE_RE.findall(body)))
        loc_headers = [h[0] for h in _NGINX_ADD_HEADER_RE.findall(body)]
        locations.append({
            "path": loc_path,
            "proxy_pass": loc_proxies[:4],
            "rewrite": loc_rewrites[:3],
            "try_files": loc_try[:2],
            "includes": loc_includes[:4],
            "has_add_header": bool(loc_headers),
        })
        if (
            server_includes_sec
            and loc_headers
            and not any("security" in inc.lower() for inc in loc_includes)
            and not any(h.lower() in _NGINX_SECURITY_HEADERS for h in loc_headers)
        ):
            nginx_misconfigs.append({
                "severity": "MEDIUM",
                "rule": "NGINX_HEADER_INHERITANCE_LOSS",
                "file": rel,
                "line": 1,
                "detail": f"Location `{loc_path}` defines `add_header` without re-including security headers.",
                "remediation": "Include the shared security-headers.conf inside any location block that sets `add_header`.",
            })

    entry: dict[str, Any] = {
        "file": rel,
        "listen": listens[:8],
        "server_name": server_names[:6],
        "upstreams": upstreams[:10],
        "proxy_pass": proxies[:12],
        "locations": locations[:30],
        "includes": includes[:12],
        "gzip": has_gzip,
        "security_headers": security_headers,
    }
    return entry, nginx_misconfigs


def _classify_shell_role(rel: str, text_low: str) -> str:
    """Classify a shell script into an operational entrypoint role."""
    rlow = rel.lower()
    if any(k in rlow for k in ("dr_test", "dr-drill", "restore", "recovery")):
        return "dr_drill"
    if any(k in rlow for k in ("backup", "pgbackrest", "dump", "rclone", "snapshot")):
        return "backup"
    if any(k in rlow for k in ("deploy", "release", "rollout", "install", "bootstrap", "setup", "provision", "entrypoint", "start")):
        return "deploy"
    if any(k in rlow for k in ("notify", "alert", "telegram", "slack", "webhook")):
        return "notify"
    if any(k in rlow for k in ("ci", "lint", "test", "check", "verify", "audit", "gate", "smoke")):
        return "ci"
    if any(k in rlow for k in ("health", "monitor", "probe", "watchdog", "status")):
        return "healthcheck"
    if "pgbackrest" in text_low or "pg_dump" in text_low:
        return "backup"
    if "docker compose" in text_low or "systemctl" in text_low:
        return "deploy"
    return "ops"


def scan_shell_scripts(project_dir: Path) -> list[dict[str, Any]]:
    """Scan all `*.sh` scripts in `project_dir` extracting role, env var names (never values), and infra commands."""
    project_dir = Path(project_dir).resolve()
    scripts: list[dict[str, Any]] = []
    for root, dirs, files in os.walk(project_dir):
        dirs[:] = [d for d in dirs if d not in _IGNORE_DIRS and not d.startswith(".")]
        for fname in sorted(files):
            if not fname.lower().endswith(".sh"):
                continue
            fpath = Path(root) / fname
            rel = str(fpath.relative_to(project_dir)).replace("\\", "/")
            if _is_ignored(rel):
                continue
            try:
                text = fpath.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            lines = text.splitlines()
            uncommented = "\n".join(ln for ln in lines if not ln.lstrip().startswith("#"))
            text_low = uncommented.lower()
            strict_mode = bool(
                re.search(r"(?m)^\s*set\s+-[a-zA-Z]*e", uncommented)
                and ("pipefail" in uncommented or re.search(r"(?m)^\s*set\s+-[a-zA-Z]*u", uncommented))
            )
            env_vars = sorted({
                m for m in _SH_ENV_RE.findall(uncommented)
                if m not in _SH_BUILTIN_ENVS
            })[:25]
            infra_cmds = [name for name, pat in _SH_INFRA_CMDS if pat.search(uncommented)]
            role = _classify_shell_role(rel, text_low)
            scripts.append({
                "path": rel,
                "entrypoint_role": role,
                "strict_mode": strict_mode,
                "env_vars_referenced": env_vars,
                "infra_commands": infra_cmds,
            })
    scripts.sort(key=lambda s: str(s["path"]))
    return scripts


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

            # 2. docker-compose*.yml (ADR-080 P0.3 hardening: privileged, docker.sock, host network, healthcheck)
            elif low.startswith("docker-compose") and low.endswith((".yml", ".yaml")):
                try:
                    lines = fpath.read_text(encoding="utf-8", errors="ignore").splitlines()
                except OSError:
                    continue
                in_svc = False
                cur: dict[str, Any] | None = None
                cur_line = 1
                cur_has_healthcheck = False
                in_ports = False
                in_deps = False
                in_vols = False

                def _finalize_compose_svc(svc: dict[str, Any] | None, svc_ln: int, has_hc: bool) -> None:
                    if not svc:
                        return
                    compose_services.append(svc)
                    sname_low = str(svc.get("name", "")).lower()
                    if not has_hc and not any(h in sname_low for h in _COMPOSE_ONESHOT_HINTS):
                        misconfigs.append({
                            "severity": "LOW",
                            "rule": "COMPOSE_NO_HEALTHCHECK",
                            "file": rel,
                            "line": svc_ln,
                            "detail": f"Service `{svc['name']}` has no `healthcheck:` directive defined.",
                            "remediation": "Add a `healthcheck:` block so orchestrators can detect unhealthy containers.",
                        })

                for lineno, ln in enumerate(lines, 1):
                    s = ln.strip()
                    if not s or s.startswith("#"):
                        continue
                    indent = len(ln) - len(ln.lstrip(" "))
                    if indent == 0 and s == "services:":
                        in_svc = True
                        continue
                    if indent == 0 and s.endswith(":"):
                        _finalize_compose_svc(cur, cur_line, cur_has_healthcheck)
                        in_svc = False
                        cur = None
                        continue
                    if in_svc and indent == 2 and s.endswith(":"):
                        _finalize_compose_svc(cur, cur_line, cur_has_healthcheck)
                        cur = {"name": s[:-1], "image": "build", "ports": [], "depends_on": [], "file": rel}
                        cur_line = lineno
                        cur_has_healthcheck = False
                        in_ports = False
                        in_deps = False
                        in_vols = False
                    elif in_svc and cur and indent == 4:
                        in_ports = s == "ports:"
                        in_deps = s == "depends_on:"
                        in_vols = s == "volumes:"
                        if s.startswith("image:"):
                            cur["image"] = s.split(":", 1)[1].strip().strip("\"'")
                        elif s.startswith("healthcheck:"):
                            cur_has_healthcheck = True
                        elif re.match(r"^privileged\s*:\s*true\b", s, re.IGNORECASE):
                            misconfigs.append({
                                "severity": "CRITICAL",
                                "rule": "COMPOSE_PRIVILEGED",
                                "file": rel,
                                "line": lineno,
                                "detail": f"Service `{cur['name']}` runs with `privileged: true` (full host root capabilities).",
                                "remediation": "Remove `privileged: true` and grant only specific Linux capabilities via `cap_add`.",
                            })
                        elif re.match(r"^network_mode\s*:\s*[\"']?host[\"']?\b", s, re.IGNORECASE):
                            misconfigs.append({
                                "severity": "MEDIUM",
                                "rule": "COMPOSE_HOST_NETWORK",
                                "file": rel,
                                "line": lineno,
                                "detail": f"Service `{cur['name']}` uses `network_mode: host` (bypasses container network isolation).",
                                "remediation": "Use a dedicated bridge network with explicit port mappings instead of host networking.",
                            })
                    elif in_svc and cur and indent >= 6 and s.startswith("- "):
                        val = s[2:].strip().strip("\"'")
                        if in_ports:
                            cur["ports"].append(val)
                        elif in_deps:
                            cur["depends_on"].append(val)
                        elif in_vols and "/var/run/docker.sock" in val:
                            misconfigs.append({
                                "severity": "HIGH",
                                "rule": "COMPOSE_DOCKER_SOCK",
                                "file": rel,
                                "line": lineno,
                                "detail": f"Service `{cur['name']}` mounts `/var/run/docker.sock` (container escape / host root risk).",
                                "remediation": "Avoid mounting docker.sock directly or proxy read-only calls through a restricted socket proxy.",
                            })
                _finalize_compose_svc(cur, cur_line, cur_has_healthcheck)

            # 3. GitHub Actions Workflows (ADR-080 P0.3: uncapped unpinned actions + supply-chain hardening)
            elif ".github/workflows/" in rel and low.endswith((".yml", ".yaml")):
                try:
                    text = fpath.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    continue
                actions: list[str] = []
                unpinned_actions = 0
                wf_lines = text.splitlines()

                # GHA_WRITE_ALL / GHA_MISSING_PERMISSIONS
                if _GHA_WRITE_ALL_RE.search(text):
                    m_wa = _GHA_WRITE_ALL_RE.search(text)
                    wa_line = text[: m_wa.start()].count("\n") + 1 if m_wa else 1
                    misconfigs.append({
                        "severity": "CRITICAL",
                        "rule": "GHA_WRITE_ALL",
                        "file": rel,
                        "line": wa_line,
                        "detail": "Workflow grants `permissions: write-all` to GITHUB_TOKEN.",
                        "remediation": "Restrict token permissions to least privilege (e.g. `permissions: { contents: read }`).",
                    })
                elif not _GHA_PERMISSIONS_RE.search(text):
                    misconfigs.append({
                        "severity": "MEDIUM",
                        "rule": "GHA_MISSING_PERMISSIONS",
                        "file": rel,
                        "line": 1,
                        "detail": "Workflow does not declare an explicit `permissions:` block.",
                        "remediation": "Add top-level `permissions: { contents: read }` and elevate only specific jobs.",
                    })

                # GHA_PULL_REQUEST_TARGET
                m_prt = _GHA_PR_TARGET_RE.search(text)
                if m_prt:
                    prt_line = text[: m_prt.start()].count("\n") + 1
                    checks_out_head = "pull_request.head" in text
                    misconfigs.append({
                        "severity": "CRITICAL" if checks_out_head else "HIGH",
                        "rule": "GHA_PULL_REQUEST_TARGET",
                        "file": rel,
                        "line": prt_line,
                        "detail": "Workflow uses `pull_request_target` trigger" + (" with PR head checkout (untrusted code execution with repo secrets!)." if checks_out_head else " (runs with write token/secrets on fork PRs)."),
                        "remediation": "Use `pull_request` trigger or never checkout/execute untrusted PR head code inside `pull_request_target`.",
                    })

                # GHA_ISSUE_COMMENT_SELF_HOSTED
                m_ic = _GHA_ISSUE_COMMENT_RE.search(text)
                if m_ic and _GHA_SELF_HOSTED_RE.search(text) and "author_association" not in text:
                    ic_line = text[: m_ic.start()].count("\n") + 1
                    misconfigs.append({
                        "severity": "CRITICAL",
                        "rule": "GHA_ISSUE_COMMENT_SELF_HOSTED",
                        "file": rel,
                        "line": ic_line,
                        "detail": "`issue_comment` workflow runs on `self-hosted` runner without `author_association` guard.",
                        "remediation": "Restrict execution to trusted maintainers (`github.event.comment.author_association == 'OWNER'`).",
                    })

                # Per-line checks: uncapped GHA_UNPINNED_ACTION + GHA_SCRIPT_INJECTION in run: blocks
                in_run_block = False
                run_indent = 0
                for lineno, ln in enumerate(wf_lines, 1):
                    s = ln.strip()
                    indent = len(ln) - len(ln.lstrip(" "))
                    if s.startswith("run:") or s.startswith("- run:"):
                        in_run_block = True
                        run_indent = indent
                    elif s and not s.startswith("#") and indent <= run_indent and not s.startswith("|") and not s.startswith(">"):
                        in_run_block = False

                    if in_run_block and _GHA_SCRIPT_INJECTION_RE.search(ln):
                        misconfigs.append({
                            "severity": "HIGH",
                            "rule": "GHA_SCRIPT_INJECTION",
                            "file": rel,
                            "line": lineno,
                            "detail": "Untrusted `${{ github.event.* }}` expression interpolated directly inside `run:` shell script.",
                            "remediation": "Pass the expression via an `env:` variable and reference it as `\"$VAR\"` in shell.",
                        })

                    m = _USES_RE.search(ln)
                    if m:
                        act = m.group(1)
                        actions.append(act)
                        if not _SHA_PIN_RE.search(act) and not act.startswith("./"):
                            unpinned_actions += 1
                            misconfigs.append({
                                "severity": "MEDIUM",
                                "rule": "GHA_UNPINNED_ACTION",
                                "file": rel,
                                "line": lineno,
                                "detail": f"GitHub Action `{act}` is not pinned to a full commit SHA.",
                                "remediation": "Pin third-party actions to a 40-char commit SHA (`uses: owner/action@<sha> # vX`).",
                            })
                ci_workflows.append({"name": Path(rel).stem, "file": rel, "actions_count": len(actions), "unpinned_actions": unpinned_actions})

            # 4. Nginx configs (check full relative path `rel`, e.g. frontend/nginx/default.conf)
            elif ("nginx" in rel.lower() or "nginx" in low) and low.endswith(".conf"):
                try:
                    text = fpath.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    continue
                nginx_entry, nginx_mc = _parse_nginx_conf(rel, text)
                nginx_proxies.append(nginx_entry)
                misconfigs.extend(nginx_mc)

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

    # 7. Shell scripts (*.sh) — compact ops/backup/deploy/ci metadata (env names only, never values)
    shell_scripts = scan_shell_scripts(project_dir)
    role_counts: dict[str, int] = {}
    cmd_counts: dict[str, int] = {}
    for sc in shell_scripts:
        r = str(sc.get("entrypoint_role", "ops"))
        role_counts[r] = role_counts.get(r, 0) + 1
        for cmd in sc.get("infra_commands") or []:
            cmd_counts[cmd] = cmd_counts.get(cmd, 0) + 1
    top_infra_cmds = [
        {"command": k, "scripts_count": v}
        for k, v in sorted(cmd_counts.items(), key=lambda kv: (-kv[1], kv[0]))[:15]
    ]
    all_nginx_sec_headers = sorted({
        hdr
        for nx in nginx_proxies
        for hdr in (nx.get("security_headers") or {}).keys()
    })
    nginx_locations_total = sum(len(nx.get("locations") or []) for nx in nginx_proxies)

    sev_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
    misconfigs.sort(key=lambda m: (sev_order.get(str(m.get("severity", "MEDIUM")).upper(), 4), str(m.get("file", "")), int(m.get("line", 1))))
    by_sev = {
        "CRITICAL": sum(1 for m in misconfigs if str(m.get("severity", "")).upper() == "CRITICAL"),
        "HIGH": sum(1 for m in misconfigs if str(m.get("severity", "")).upper() == "HIGH"),
        "MEDIUM": sum(1 for m in misconfigs if str(m.get("severity", "")).upper() == "MEDIUM"),
        "LOW": sum(1 for m in misconfigs if str(m.get("severity", "")).upper() == "LOW"),
    }

    payload: dict[str, Any] = {
        "generated_at": time.time(),
        "summary": {
            "dockerfiles": len(dockerfiles),
            "compose_services": len(compose_services),
            "nginx_configs": len(nginx_proxies),
            "nginx_locations_count": nginx_locations_total,
            "nginx_security_headers_count": len(all_nginx_sec_headers),
            "shell_scripts_count": len(shell_scripts),
            "shell_scripts_by_role": role_counts,
            "ci_workflows": len(ci_workflows),
            "terraform_resources": len(terraform_resources),
            "k8s_workloads": len(k8s_workloads),
            "misconfigs_count": len(misconfigs),
            "by_severity": by_sev,
        },
        "dockerfiles": dockerfiles[:30],
        "compose_services": compose_services[:60],
        "nginx_proxies": nginx_proxies[:20],
        "nginx_security_headers": all_nginx_sec_headers,
        "shell_scripts_count": len(shell_scripts),
        "shell_scripts_summary": {
            "total": len(shell_scripts),
            "strict_mode_count": sum(1 for s in shell_scripts if s.get("strict_mode")),
            "by_role": role_counts,
            "top_infra_commands": top_infra_cmds,
            "scripts": shell_scripts[:100],
        },
        "ci_workflows": ci_workflows[:30],
        "terraform_resources": terraform_resources[:60],
        "k8s_workloads": k8s_workloads[:60],
        "misconfigs": misconfigs[:150],
    }

    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "iac-topology.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    (data_dir / "iac_topology.js").write_text(f"window.IAC_TOPOLOGY = {json.dumps(payload)};\n", encoding="utf-8")
    return payload
