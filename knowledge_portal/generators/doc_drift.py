"""
Knowledge Portal — Living Doc-Drift Detector & PR Context Generator (ADR-077).
100% Python stdlib zero-dependency analyzer:
- Reads `git diff --name-only <base>..HEAD` (or explicit changed_files list)
- Detects `.md` docs / ADRs / `llms.txt` referencing changed modules that were NOT updated in the same diff
- Computes impacted tests and renders a concise Markdown PR comment (`knowledge-portal pr-comment`)

Strictly enforces P4 Gate (excludes frozen/).
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

_IGNORE_DIRS = frozenset({".git", "node_modules", "dist", "build", ".venv", "venv", "__pycache__", "frozen"})


def _git_changed_files(project_dir: Path, base: str = "main") -> list[str]:
    if not (project_dir / ".git").exists():
        return []
    for ref_arg in (f"{base}...HEAD", f"{base}..HEAD", "HEAD~1..HEAD"):
        try:
            proc = subprocess.run(  # nosec B603 B607
                ["git", "-C", str(project_dir), "diff", "--name-only", ref_arg],
                capture_output=True,
                text=True,
                timeout=8,
                check=False,
            )
            if proc.returncode == 0 and proc.stdout.strip():
                return [ln.strip().replace("\\", "/") for ln in proc.stdout.splitlines() if ln.strip() and "frozen/" not in ln.lower()]
        except Exception:
            continue
    return []


def detect_doc_drift(
    project_dir: Path,
    base: str = "main",
    changed_files: list[str] | None = None,
) -> dict[str, Any]:
    """Identify documentation files that reference changed code modules without being updated."""
    project_dir = Path(project_dir).resolve()
    changed = list(changed_files) if changed_files is not None else _git_changed_files(project_dir, base=base)
    changed_set = {c.replace("\\", "/") for c in changed if "frozen/" not in c.lower()}
    code_changed = [c for c in changed_set if not c.lower().endswith((".md", ".txt", ".json", ".lock"))]

    # Build lookup tokens (relative path and meaningful stems >= 5 chars)
    token_to_code: dict[str, str] = {}
    for cf in code_changed:
        token_to_code[cf] = cf
        stem = Path(cf).stem
        if len(stem) >= 5 and stem.lower() not in ("index", "utils", "types", "models", "config", "common", "helpers", "__init__"):
            token_to_code[stem] = cf

    stale_docs: list[dict[str, Any]] = []
    if token_to_code:
        for root, dirs, files in os.walk(project_dir):
            dirs[:] = [d for d in dirs if d not in _IGNORE_DIRS and not d.startswith(".")]
            for fname in files:
                if not fname.endswith(".md") and fname != "llms.txt":
                    continue
                fpath = Path(root) / fname
                rel = str(fpath.relative_to(project_dir)).replace("\\", "/")
                if rel in changed_set or "frozen/" in rel.lower():
                    continue
                try:
                    if fpath.stat().st_size > 250_000:
                        continue
                    txt = fpath.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    continue
                hits = sorted({src_f for tok, src_f in token_to_code.items() if tok in txt})
                if hits:
                    stale_docs.append({"doc": rel, "referenced_changed_files": hits[:6]})

    # Identify candidate impacted tests by stem match
    impacted_tests: list[str] = []
    stems = {Path(c).stem.lower() for c in code_changed if len(Path(c).stem) >= 4}
    if stems:
        for root, dirs, files in os.walk(project_dir):
            dirs[:] = [d for d in dirs if d not in _IGNORE_DIRS and not d.startswith(".")]
            for fname in files:
                low = fname.lower()
                if low.startswith("test_") or ".spec." in low or ".test." in low:
                    if any(st in low for st in stems):
                        rel = str((Path(root) / fname).relative_to(project_dir)).replace("\\", "/")
                        impacted_tests.append(rel)

    stale_docs.sort(key=lambda d: (-len(d["referenced_changed_files"]), d["doc"]))
    return {
        "base_ref": base,
        "changed_files_count": len(changed_set),
        "code_files_changed": sorted(code_changed)[:40],
        "stale_docs_count": len(stale_docs),
        "stale_docs": stale_docs[:25],
        "impacted_tests": sorted(set(impacted_tests))[:25],
    }


def render_pr_comment_markdown(drift: dict[str, Any], health_report: dict[str, Any] | None = None) -> str:
    """Render a ready-to-post GitHub/GitLab PR review comment."""
    lines = [
        "## 🧭 Knowledge Portal — PR Intelligence & Doc-Drift Report",
        "",
        f"- **Base Ref**: `{drift.get('base_ref', 'main')}` · **Changed Files**: `{drift.get('changed_files_count', 0)}`",
    ]
    if health_report and isinstance(health_report.get("summary"), dict):
        s = health_report["summary"]
        hv4 = health_report.get("health_v4") or {}
        ow = (hv4.get("owasp_audit") or {}).get("findings_count", 0)
        lines.append(
            f"- **Architecture Health**: **{s.get('health_score', 0)}/100 (Grade {s.get('grade', '-')})** · "
            f"Cycles: `{s.get('cycle_count', 0)}` · OWASP Findings: `{ow}`"
        )
    stale = drift.get("stale_docs") or []
    lines.extend(["", f"### 📝 Candidate Stale Documentation ({len(stale)})", ""])
    if stale:
        for d in stale[:10]:
            refs = ", ".join(f"`{r}`" for r in d["referenced_changed_files"])
            lines.append(f"- `{d['doc']}` references modified code: {refs}")
    else:
        lines.append("- ✅ No stale Markdown docs or ADRs detected for this diff.")

    tests = drift.get("impacted_tests") or []
    if tests:
        lines.extend(["", f"### 🧪 Suggested Impacted Tests ({len(tests)})", "", f"```bash\npytest {' '.join(tests[:8])}\n```"])
    lines.append("")
    return "\n".join(lines)
