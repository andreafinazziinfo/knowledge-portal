"""
Knowledge Portal — Agent Instructions Hygiene Audit (ADR-082 Track A).
100% Python stdlib zero-dependency linter for AI coding agent instruction files:
- Scans CLAUDE.md, AGENTS.md, GEMINI.md, .cursorrules, .github/copilot-instructions.md,
  .claude/**/*.md, .cursor/rules/*
- Detects dead/broken repo file paths, duplicated directives, contradictions, and token bloat
- Produces compression recommendations

Outputs `data/agent-instructions-audit.json` and `data/agent_instructions_audit.js`.
"""

from __future__ import annotations

import json
import math
import re
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

_SINGLE_FILES = (
    "CLAUDE.md",
    "AGENTS.md",
    "GEMINI.md",
    ".cursorrules",
    ".github/copilot-instructions.md",
)
_SCAN_DIRS = (
    ".claude",
    ".cursor/rules",
)

_PATH_BACKTICK_RE = re.compile(r"`([A-Za-z0-9_./-]+\.[A-Za-z0-9]{1,8})`")
_DIR_PREFIXES = (
    "backend/", "frontend/", "scripts/", "docs/", "tests/", "src/",
    "knowledge_portal/", "template/", "config/", ".github/", "packages/",
)
_IGNORE_PATH_TOKENS = ("*", "<", ">", "{", "}", "$", "http://", "https://", "localhost", "example.", "...")
_BLOAT_WARN_TOKENS = 2500
_BLOAT_HIGH_TOKENS = 5000

_CONTRADICTION_PAIRS: list[tuple[str, re.Pattern[str], re.Pattern[str], str]] = [
    (
        "python_pkg_manager",
        re.compile(r"\b(?:always|must|only)\s+use\s+uv\b", re.IGNORECASE),
        re.compile(r"\b(?:always|must|only)\s+use\s+pip\b", re.IGNORECASE),
        "Conflicting Python package manager directive (uv vs pip)",
    ),
    (
        "js_pkg_manager",
        re.compile(r"\b(?:always|must|only)\s+use\s+pnpm\b", re.IGNORECASE),
        re.compile(r"\b(?:always|must|only)\s+use\s+npm\b", re.IGNORECASE),
        "Conflicting JS package manager directive (pnpm vs npm)",
    ),
    (
        "mock_policy",
        re.compile(r"\bnever\s+(?:use\s+)?mock", re.IGNORECASE),
        re.compile(r"\balways\s+(?:use\s+)?mock", re.IGNORECASE),
        "Conflicting test mocking directive (never mock vs always mock)",
    ),
]


def _est_tokens(text: str) -> int:
    return math.ceil(len(text) / 3.8) if text else 0


def _collect_instruction_files(project_dir: Path) -> list[Path]:
    found: list[Path] = []
    seen: set[Path] = set()
    for rel in _SINGLE_FILES:
        p = project_dir / rel
        if p.is_file() and p not in seen:
            seen.add(p)
            found.append(p)
    for drel in _SCAN_DIRS:
        d = project_dir / drel
        if not d.is_dir():
            continue
        for p in sorted(d.rglob("*")):
            if not p.is_file() or p in seen:
                continue
            if p.suffix.lower() not in (".md", ".mdc", ".txt"):
                continue
            if p.name.startswith(".env"):
                continue
            seen.add(p)
            found.append(p)
    return found


def _extract_dead_paths(project_dir: Path, text: str) -> list[str]:
    dead: list[str] = []
    seen: set[str] = set()
    for m in _PATH_BACKTICK_RE.finditer(text):
        cand = m.group(1).strip().lstrip("./")
        if not cand or cand in seen:
            continue
        if any(tok in cand for tok in _IGNORE_PATH_TOKENS):
            continue
        if "/" not in cand:
            continue
        if not cand.startswith(_DIR_PREFIXES):
            continue
        seen.add(cand)
        if not (project_dir / cand).exists():
            dead.append(cand)
    return dead


def generate_agent_instructions_audit(project_dir: Path, data_dir: Path) -> dict[str, Any]:
    """Audit agent instruction files for dead paths, duplications, contradictions, and token bloat."""
    project_dir = Path(project_dir).resolve()
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)

    inst_files = _collect_instruction_files(project_dir)
    files_report: list[dict[str, Any]] = []
    dead_paths_all: list[dict[str, str]] = []
    norm_lines_map: dict[str, list[str]] = defaultdict(list)
    full_corpus: list[tuple[str, str]] = []

    total_tokens = 0
    bloat_files_count = 0

    for fpath in inst_files:
        rel = str(fpath.relative_to(project_dir)).replace("\\", "/")
        try:
            text = fpath.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        tok = _est_tokens(text)
        total_tokens += tok
        lines = text.splitlines()
        bloat = "HIGH" if tok > _BLOAT_HIGH_TOKENS else ("WARN" if tok > _BLOAT_WARN_TOKENS else "OK")
        if bloat != "OK":
            bloat_files_count += 1

        dead = _extract_dead_paths(project_dir, text)
        for dp in dead[:30]:
            dead_paths_all.append({"file": rel, "missing_path": dp})

        for ln in lines:
            s = ln.strip()
            if len(s) >= 35 and (s.startswith(("- ", "* ", "# ")) or "NEVER " in s.upper() or "ALWAYS " in s.upper()):
                norm = re.sub(r"\s+", " ", s.lower())
                norm_lines_map[norm].append(rel)

        full_corpus.append((rel, text))

        suggestions: list[str] = []
        if bloat == "HIGH":
            suggestions.append(f"Split {rel} (~{tok} tok) into concise root rules (<= 2,500 tok) + linked domain docs.")
        elif bloat == "WARN":
            suggestions.append(f"Trim {rel} (~{tok} tok) under 2,500 tok to save context on every agent turn.")
        if dead:
            suggestions.append(f"Remove or update {len(dead)} stale file path reference(s).")

        files_report.append({
            "path": rel,
            "bytes": len(text.encode("utf-8")),
            "lines": len(lines),
            "estimated_tokens": tok,
            "bloat_level": bloat,
            "dead_paths_count": len(dead),
            "dead_paths": dead[:20],
            "suggestions": suggestions,
        })

    duplications: list[dict[str, Any]] = []
    for norm_line, origins in norm_lines_map.items():
        if len(origins) >= 2:
            duplications.append({
                "line": norm_line[:140],
                "occurrences": len(origins),
                "files": sorted(set(origins)),
            })
    duplications.sort(key=lambda d: (-int(d["occurrences"]), str(d["line"])))

    contradictions: list[dict[str, Any]] = []
    for cid, pat_a, pat_b, desc in _CONTRADICTION_PAIRS:
        hit_a = [rel for rel, txt in full_corpus if pat_a.search(txt)]
        hit_b = [rel for rel, txt in full_corpus if pat_b.search(txt)]
        if hit_a and hit_b:
            contradictions.append({
                "id": cid,
                "description": desc,
                "side_a_files": hit_a,
                "side_b_files": hit_b,
            })

    penalty = (
        min(40, len(dead_paths_all) * 3)
        + min(25, bloat_files_count * 15)
        + min(20, len(duplications) * 2)
        + min(15, len(contradictions) * 10)
    )
    hygiene_score = max(0, 100 - penalty)

    payload: dict[str, Any] = {
        "schema_version": "1.0",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "summary": {
            "files_found": len(files_report),
            "total_tokens": total_tokens,
            "dead_paths_count": len(dead_paths_all),
            "duplications_count": len(duplications),
            "contradictions_count": len(contradictions),
            "bloat_files_count": bloat_files_count,
            "hygiene_score": hygiene_score,
        },
        "files": files_report,
        "dead_paths": dead_paths_all[:50],
        "duplications": duplications[:30],
        "contradictions": contradictions,
    }

    (data_dir / "agent-instructions-audit.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    (data_dir / "agent_instructions_audit.js").write_text(
        f"window.AGENT_INSTRUCTIONS_AUDIT = {json.dumps(payload)};\n",
        encoding="utf-8",
    )
    return payload
