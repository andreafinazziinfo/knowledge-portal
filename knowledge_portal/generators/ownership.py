"""
Knowledge Portal — Ownership, CODEOWNERS & Conway's Law Map Generator (ADR-077).
100% Python stdlib zero-dependency analyzer extracting:
- Explicit rules from `.github/CODEOWNERS`, `CODEOWNERS`, or `docs/CODEOWNERS`
- Historical top contributors per domain via read-only `git log --since="180 days ago"`
- Bus Factor & Conway Friction flags per domain

Outputs `data/ownership.json`. Strictly enforces P4 Gate (excludes frozen/).
"""

from __future__ import annotations

import fnmatch
import json
import subprocess
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

_DENY = frozenset({"frozen", ".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build"})


def _is_denied(rel: str) -> bool:
    return any(seg in _DENY for seg in rel.replace("\\", "/").lower().split("/"))


def _domain_of(rel: str) -> str:
    parts = [p for p in rel.replace("\\", "/").split("/") if p]
    if len(parts) >= 3 and parts[0] in ("backend", "frontend", "src", "packages"):
        return f"{parts[0]}/{parts[1]}/{parts[2]}" if parts[1] in ("app", "src") else f"{parts[0]}/{parts[1]}"
    if len(parts) >= 2:
        return f"{parts[0]}/{parts[1]}"
    return parts[0] if parts else "root"


def parse_codeowners(project_dir: Path) -> tuple[str | None, list[dict[str, Any]]]:
    """Parse CODEOWNERS rules into ordered [{pattern, owners}] list."""
    for rel in (".github/CODEOWNERS", "CODEOWNERS", "docs/CODEOWNERS"):
        p = project_dir / rel
        if p.is_file():
            rules: list[dict[str, Any]] = []
            for raw in p.read_text(encoding="utf-8", errors="ignore").splitlines():
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split()
                if len(parts) >= 2:
                    rules.append({"pattern": parts[0], "owners": parts[1:]})
            return rel, rules
    return None, []


def match_owners(rel_path: str, rules: list[dict[str, Any]]) -> list[str]:
    """Last-match-wins CODEOWNERS resolution."""
    norm = rel_path.replace("\\", "/").lstrip("/")
    matched: list[str] = []
    for r in rules:
        pat = str(r["pattern"]).lstrip("/")
        if pat.endswith("/"):
            if norm.startswith(pat) or f"/{pat}" in f"/{norm}":
                matched = list(r["owners"])
        elif fnmatch.fnmatch(norm, pat) or fnmatch.fnmatch(Path(norm).name, pat):
            matched = list(r["owners"])
    return matched


def generate_ownership_map(project_dir: Path, data_dir: Path, days: int = 180) -> dict[str, Any]:
    """Build domain ownership, CODEOWNERS coverage, and Conway friction map."""
    project_dir = Path(project_dir).resolve()
    data_dir = Path(data_dir)
    co_file, rules = parse_codeowners(project_dir)

    domain_authors: dict[str, Counter[str]] = defaultdict(Counter)
    domain_files: dict[str, set[str]] = defaultdict(set)
    git_available = False

    if (project_dir / ".git").exists():
        try:
            proc = subprocess.run(  # nosec B603 B607
                ["git", "-C", str(project_dir), "log", f"--since={days} days ago", "--name-only", "--format=AUTHOR|%an", "-n", "500"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            if proc.returncode == 0:
                git_available = True
                cur_author = "unknown"
                for line in proc.stdout.splitlines():
                    if line.startswith("AUTHOR|"):
                        cur_author = line.split("|", 1)[1].strip() or "unknown"
                    elif line.strip():
                        rel = line.strip().replace("\\", "/")
                        if _is_denied(rel):
                            continue
                        dom = _domain_of(rel)
                        domain_authors[dom][cur_author] += 1
                        domain_files[dom].add(rel)
        except Exception:
            git_available = False

    domains: list[dict[str, Any]] = []
    for dom, cnt in sorted(domain_authors.items(), key=lambda kv: (-sum(kv[1].values()), kv[0]))[:30]:
        total_touches = sum(cnt.values())
        top_authors: list[dict[str, Any]] = [{"author": a, "touches": n, "share_pct": round(100.0 * n / max(1, total_touches), 1)} for a, n in cnt.most_common(5)]
        bus_factor = sum(1 for a in top_authors if float(a["share_pct"]) >= 20.0) or 1
        co_owners = match_owners(f"{dom}/placeholder.py", rules) if rules else []
        conway_risk = "Single-Author Bottleneck" if len(cnt) == 1 and total_touches >= 5 else ("Multi-Team Friction" if len(cnt) >= 6 else "Healthy")
        domains.append({
            "domain": dom,
            "files_touched": len(domain_files[dom]),
            "total_touches": total_touches,
            "unique_authors": len(cnt),
            "bus_factor": bus_factor,
            "codeowners": co_owners,
            "top_authors": top_authors,
            "conway_status": conway_risk,
        })

    payload: dict[str, Any] = {
        "generated_at": time.time(),
        "codeowners_file": co_file,
        "codeowners_rules_count": len(rules),
        "codeowners_rules": rules[:60],
        "git_available": git_available,
        "window_days": days,
        "domains": domains,
    }

    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "ownership.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload
