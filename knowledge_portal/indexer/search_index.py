"""
Generic Federated Omni-Search Indexer (Zero Dependencies)
Indexes markdown documents, classes, and functions into a single omni-search-index.json
"""

import json
from pathlib import Path
from typing import Dict, List, Any

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
            title = md_path.stem.replace("-", " ").replace("_", " ").title()
            first_line = content.splitlines()[0].strip("# ") if content.splitlines() else title
            entities.append({
                "id": f"doc_{rel}",
                "title": first_line or title,
                "subtitle": rel,
                "badge": "📖 Note",
                "category": "documentation",
                "tab": "reader",
                "path": rel,
                "search_text": content[:500]
            })
        except Exception:
            pass

    # Write output
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump({"total": len(entities), "entities": entities}, f, indent=2)

    return len(entities)
