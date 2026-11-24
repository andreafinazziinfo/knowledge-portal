"""
Generic Federated Omni-Search Indexer (Zero Dependencies)
Indexes markdown documents, classes, and functions into a single omni-search-index.json
"""

import json
from pathlib import Path

def _extract_markdown_title(content: str, fallback: str) -> str:
    """Extract Markdown document title, skipping YAML frontmatter (`--- ... ---`) (QA-4)."""
    lines = content.splitlines()
    if not lines:
        return fallback

    idx = 0
    # Skip leading blank lines
    while idx < len(lines) and not lines[idx].strip():
        idx += 1

    # Handle YAML frontmatter block
    if idx < len(lines) and lines[idx].strip() == "---":
        idx += 1
        fm_title = ""
        while idx < len(lines) and lines[idx].strip() != "---":
            line = lines[idx].strip()
            if line.lower().startswith("title:"):
                val = line.split(":", 1)[1].strip().strip("'\"")
                if val and val != "---":
                    fm_title = val
            idx += 1
        if idx < len(lines) and lines[idx].strip() == "---":
            idx += 1
        if fm_title:
            return fm_title

    # Look for first Markdown heading after frontmatter
    for line in lines[idx:idx + 30]:
        s = line.strip()
        if not s or s == "---":
            continue
        if s.startswith("#"):
            cleaned = s.lstrip("#").strip()
            if cleaned and cleaned != "---":
                return cleaned
        break

    return fallback


def generate_search_index(codebase_dir: Path, output_file: Path) -> int:
    entities = []
    output_file.parent.mkdir(parents=True, exist_ok=True)

    # 1. Index Markdown Notes
    for md_path in codebase_dir.rglob("*.md"):
        if any(p in str(md_path) for p in [".git", "venv", ".venv", "node_modules"]):
            continue
        try:
            content = md_path.read_text(encoding="utf-8", errors="replace")
            rel = str(md_path.relative_to(codebase_dir)).replace("\\", "/")
            fallback_title = md_path.stem.replace("-", " ").replace("_", " ").title()
            doc_title = _extract_markdown_title(content, fallback_title)
            entities.append({
                "id": f"doc_{rel}",
                "title": doc_title,
                "subtitle": rel,
                "badge": "📖 Note",
                "category": "documentation",
                "tab": "reader",
                "path": rel,
                "search_text": content[:4000]
            })
        except Exception:
            pass

    # Write output
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump({"total": len(entities), "entities": entities}, f, indent=2)

    return len(entities)
