"""
Knowledge Portal — ADR Decision Graph & Interactive Runbook Hub Generator (ADR-081).
100% Python stdlib zero-dependency Markdown parser extracting:
- Architecture Decision Records (ADRs) from `docs/adr/`, `adr/`, `docs/decisions/`, `docs/architecture/decisions/`
- ADR metadata: ID, number, title, status (Accepted/Proposed/Superseded/Deprecated/Draft), date, domain
- Dependency & superseding graph (`nodes` + `edges`) from cross-referenced `ADR-XXX` mentions
- Interactive Runbook catalog from `docs/runbooks/`, `runbooks/`, `docs/ops/`, and `docs/**/RUNBOOK*.md`
  with parsed checklists and fenced shell commands.

Outputs `data/adr-graph.json` and `data/adr_graph.js`.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_ADR_ID_RE = re.compile(
    r"\bADR[-_ ]?((?:[A-Z][A-Z0-9]{0,5}[-_])+\d{1,4}|\d{1,4})\b",
    re.IGNORECASE,
)
_STATUS_RE = re.compile(
    r"^\s*(?:[-*]\s*)?(?:\*\*)?(?:status|stato)(?:\*\*)?\s*[:\-]\s*(.+)$",
    re.IGNORECASE | re.MULTILINE,
)
_DATE_RE = re.compile(
    r"^\s*(?:[-*]\s*)?(?:\*\*)?(?:date|data)(?:\*\*)?\s*[:\-]\s*(\d{4}-\d{2}-\d{2}[^\n]*)$",
    re.IGNORECASE | re.MULTILINE,
)
_SUPERSEDES_RE = re.compile(
    r"(?:supersedes|replaces|sostituisce)\s*[:\-]?\s*([^\n]+)",
    re.IGNORECASE,
)
_HEADING_RE = re.compile(r"^#\s+(.+)$", re.MULTILINE)
_H2_RE = re.compile(r"^##\s+(.+)$", re.MULTILINE)
_CHECKBOX_RE = re.compile(r"^\s*[-*]\s+\[([ xX])\]\s+(.+)$", re.MULTILINE)
_NUMBERED_STEP_RE = re.compile(r"^\s*\d+\.\s+(.+)$", re.MULTILINE)
_CODE_BLOCK_RE = re.compile(r"```(?:bash|sh|shell|zsh|console)?\n(.*?)```", re.DOTALL | re.IGNORECASE)

_DOMAIN_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("Security", ("security", "auth", "owasp", "compliance", "cve", "sanitiz", "secret", "rbac", "tls", "audit")),
    ("DataOps", ("database", "schema", "migration", "sql", "storage", "backup", "ingestion", "etl", "pipeline", "cache")),
    ("Infra/CI", ("docker", "kubernetes", "k8s", "ci", "cd", "deploy", "nginx", "infra", "terraform", "github", "systemd")),
    ("AI/MCP", ("mcp", "llm", "ai ", "prompt", "agent", "codemode", "rag", "embedding", "vector")),
    ("Portal/UI", ("portal", "ui", "frontend", "dashboard", "view", "graph", "theme", "playwright", "css", "svg")),
    ("Architecture", ("architecture", "module", "layer", "event", "async", "worker", "queue", "api", "service")),
]


def _normalize_status(raw: str) -> str:
    low = raw.strip().lower()
    if "supersed" in low or "replaced" in low or "sostituit" in low:
        return "Superseded"
    if "deprecat" in low or "obsolet" in low:
        return "Deprecated"
    if "reject" in low or "rifiut" in low:
        return "Rejected"
    if "propos" in low or "rfc" in low or "propost" in low:
        return "Proposed"
    if "draft" in low or "wip" in low or "bozza" in low:
        return "Draft"
    if "accept" in low or "approv" in low or "implement" in low or "active" in low or "attivo" in low:
        return "Accepted"
    return "Accepted"


def _infer_domain(title: str, text: str) -> str:
    hay = f"{title}\n{text[:1200]}".lower()
    for domain, keywords in _DOMAIN_RULES:
        if any(kw in hay for kw in keywords):
            return domain
    return "General"


def _normalize_adr_token(raw_token: str) -> tuple[str, int | None]:
    token = raw_token.upper().replace("_", "-")
    if token.isdigit():
        num = int(token)
        return f"ADR-{num:03d}", num
    return f"ADR-{token}", None


def _extract_adr_id(fpath: Path, title: str) -> tuple[str, int | None]:
    for source in (fpath.stem, title):
        m = _ADR_ID_RE.search(source)
        if m:
            return _normalize_adr_token(m.group(1))
    return fpath.stem.upper(), None


def _extract_summary(text: str) -> str:
    for para in text.split("\n\n"):
        cleaned = para.strip()
        if not cleaned or cleaned.startswith("#") or cleaned.startswith("---") or cleaned.startswith("```"):
            continue
        if cleaned.startswith(">"):
            cleaned = re.sub(r"^>\s*(\[![A-Z]+\])?\s*", "", cleaned, flags=re.MULTILINE).strip()
        if cleaned:
            return re.sub(r"\s+", " ", cleaned)[:240]
    return ""


def _discover_adr_files(project_dir: Path) -> list[Path]:
    candidates: list[Path] = []
    seen: set[Path] = set()
    adr_dirs = [
        project_dir / "docs" / "adr",
        project_dir / "adr",
        project_dir / "docs" / "decisions",
        project_dir / "docs" / "architecture" / "decisions",
    ]
    for d in adr_dirs:
        if not d.is_dir():
            continue
        for f in sorted(d.rglob("*.md")):
            if f.name.lower() in ("readme.md", "index.md", "template.md"):
                continue
            rp = f.resolve()
            if rp not in seen:
                seen.add(rp)
                candidates.append(f)
    return candidates


def _discover_runbook_files(project_dir: Path) -> list[Path]:
    candidates: list[Path] = []
    seen: set[Path] = set()
    rb_dirs = [
        project_dir / "docs" / "runbooks",
        project_dir / "runbooks",
        project_dir / "docs" / "ops",
    ]
    for d in rb_dirs:
        if not d.is_dir():
            continue
        for f in sorted(d.rglob("*.md")):
            if f.name.lower() == "readme.md":
                continue
            rp = f.resolve()
            if rp not in seen:
                seen.add(rp)
                candidates.append(f)

    # Also discover docs/**/RUNBOOK*.md or top-level RUNBOOK*.md
    for root_cand in (project_dir / "docs", project_dir):
        if not root_cand.is_dir():
            continue
        pattern = "**/RUNBOOK*.md" if root_cand.name == "docs" else "RUNBOOK*.md"
        for f in sorted(root_cand.glob(pattern)):
            if not f.is_file():
                continue
            rp = f.resolve()
            if rp not in seen:
                seen.add(rp)
                candidates.append(f)
    return candidates


def _parse_runbook(fpath: Path, project_dir: Path) -> dict[str, Any]:
    text = fpath.read_text(encoding="utf-8", errors="replace")
    rel = str(fpath.relative_to(project_dir)).replace("\\", "/")
    m_title = _HEADING_RE.search(text)
    title = m_title.group(1).strip() if m_title else fpath.stem.replace("_", " ").replace("-", " ").title()

    steps: list[dict[str, Any]] = []
    for idx, m in enumerate(_CHECKBOX_RE.finditer(text), 1):
        steps.append({"id": f"chk-{idx}", "text": m.group(2).strip(), "checked": m.group(1).lower() == "x"})
    if not steps:
        for idx, m in enumerate(_NUMBERED_STEP_RE.finditer(text), 1):
            steps.append({"id": f"step-{idx}", "text": m.group(1).strip(), "checked": False})
    if not steps:
        for idx, m in enumerate(_H2_RE.finditer(text), 1):
            steps.append({"id": f"sec-{idx}", "text": m.group(1).strip(), "checked": False})

    commands: list[str] = []
    for m in _CODE_BLOCK_RE.finditer(text):
        block = m.group(1).strip()
        if block:
            commands.append(block[:600])

    category = _infer_domain(title, text)
    return {
        "id": fpath.stem.lower(),
        "title": title,
        "path": rel,
        "category": category,
        "summary": _extract_summary(text),
        "steps": steps[:30],
        "commands": commands[:12],
        "step_count": len(steps),
    }


def generate_adr_graph(project_dir: Path, output_dir: Path | None = None) -> dict[str, Any]:
    """Generate ADR timeline/dependency graph & interactive runbook catalog."""
    project_dir = Path(project_dir).resolve()
    generated_at = datetime.now(tz=timezone.utc).isoformat()

    adr_files = _discover_adr_files(project_dir)
    nodes: list[dict[str, Any]] = []
    node_ids: set[str] = set()
    id_to_paths: dict[str, list[str]] = {}
    raw_refs: list[tuple[str, list[str], list[str]]] = []

    for fpath in adr_files:
        try:
            text = fpath.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        rel = str(fpath.relative_to(project_dir)).replace("\\", "/")
        m_title = _HEADING_RE.search(text)
        title = m_title.group(1).strip() if m_title else fpath.stem
        base_adr_id, adr_num = _extract_adr_id(fpath, title)
        id_to_paths.setdefault(base_adr_id, []).append(rel)

        # Ensure unique ID while recording duplicates (NEW-10)
        adr_id = base_adr_id
        if adr_id in node_ids:
            adr_id = f"{adr_id}-{fpath.stem[:12]}"
        node_ids.add(adr_id)

        m_status = _STATUS_RE.search(text[:2500])
        status = _normalize_status(m_status.group(1)) if m_status else "Accepted"

        m_date = _DATE_RE.search(text[:2500])
        date_str = m_date.group(1).strip()[:10] if m_date else ""

        domain = _infer_domain(title, text)

        supersedes: list[str] = []
        for sm in _SUPERSEDES_RE.finditer(text):
            for ref in _ADR_ID_RE.findall(sm.group(1)):
                norm, _ = _normalize_adr_token(ref)
                if norm != adr_id and norm not in supersedes:
                    supersedes.append(norm)

        references: list[str] = []
        for ref in _ADR_ID_RE.findall(text):
            norm, _ = _normalize_adr_token(ref)
            if norm != adr_id and norm not in supersedes and norm not in references:
                references.append(norm)

        raw_refs.append((adr_id, supersedes, references))
        nodes.append({
            "id": adr_id,
            "number": adr_num,
            "title": title,
            "status": status,
            "date": date_str,
            "domain": domain,
            "path": rel,
            "summary": _extract_summary(text),
            "supersedes": supersedes,
            "references": references[:15],
        })

    # Sort chronologically by number, then ID
    nodes.sort(key=lambda n: (n["number"] is None, n["number"] or 0, n["id"]))

    edges: list[dict[str, str]] = []
    seen_edges: set[tuple[str, str, str]] = set()
    for src_id, sup_list, ref_list in raw_refs:
        for tgt in sup_list:
            if tgt in node_ids and (src_id, tgt, "supersedes") not in seen_edges:
                seen_edges.add((src_id, tgt, "supersedes"))
                edges.append({"source": src_id, "target": tgt, "type": "supersedes"})
        for tgt in ref_list:
            if tgt in node_ids and (src_id, tgt, "references") not in seen_edges:
                seen_edges.add((src_id, tgt, "references"))
                edges.append({"source": src_id, "target": tgt, "type": "references"})

    runbook_files = _discover_runbook_files(project_dir)
    runbooks = [_parse_runbook(rb, project_dir) for rb in runbook_files]

    by_status = dict(Counter(n["status"] for n in nodes))
    by_domain = dict(Counter(n["domain"] for n in nodes))

    duplicate_ids = {k: paths for k, paths in sorted(id_to_paths.items()) if len(paths) > 1}

    summary = {
        "total_adrs": len(nodes),
        "accepted_count": by_status.get("Accepted", 0),
        "proposed_count": by_status.get("Proposed", 0) + by_status.get("Draft", 0),
        "superseded_count": by_status.get("Superseded", 0) + by_status.get("Deprecated", 0),
        "duplicate_ids_count": len(duplicate_ids),
        "edges_count": len(edges),
        "total_runbooks": len(runbooks),
        "total_runbook_steps": sum(r["step_count"] for r in runbooks),
    }

    payload: dict[str, Any] = {
        "schema_version": "1.0",
        "generated_at": generated_at,
        "total_adrs": len(nodes),
        "by_status": by_status,
        "by_domain": by_domain,
        "duplicate_ids": duplicate_ids,
        "summary": summary,
        "nodes": nodes,
        "edges": edges,
        "runbooks": runbooks,
    }

    if output_dir is not None:
        out_path = Path(output_dir)
        out_path.mkdir(parents=True, exist_ok=True)
        (out_path / "adr-graph.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        (out_path / "adr_graph.js").write_text(
            f"window.ADR_GRAPH = {json.dumps(payload, ensure_ascii=False)};\n",
            encoding="utf-8",
        )

    return payload
