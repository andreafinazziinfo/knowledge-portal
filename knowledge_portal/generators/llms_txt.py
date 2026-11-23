"""
Knowledge Portal — llms.txt & llms-full.txt Generator (ADR-069).
Generates AI-friendly discovery manifests inspired by the llms.txt specification.
Zero external dependencies; respects P4 Gate (excludes frozen/ and secrets).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _load_json_safe(path: Path) -> Any:
    if not path.exists() or not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def generate_llms_manifests(
    project_dir: Path,
    data_dir: Path,
    output_dir: Path,
    project_name: str | None = None,
) -> dict[str, Path]:
    """Generate llms.txt (concise) and llms-full.txt (comprehensive) in output_dir."""
    project_dir = Path(project_dir).resolve()
    data_dir = Path(data_dir).resolve()
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    name = project_name or project_dir.name
    graph = _load_json_safe(data_dir / "graph.json") or {}
    health = _load_json_safe(data_dir / "arch-health.json") or {}
    stack = _load_json_safe(data_dir / "stack-inventory.json") or {}
    flows = (
        _load_json_safe(data_dir / "process-flows.json")
        or _load_json_safe(data_dir.parent / "views" / "data" / "process-flows.json")
        or {}
    )
    schema = (
        _load_json_safe(data_dir / "database-schema.json")
        or _load_json_safe(data_dir.parent / "views" / "data" / "database-schema.json")
        or {}
    )

    nodes = graph.get("nodes") or []
    edges = graph.get("edges") or graph.get("links") or []
    h_sum = health.get("summary") or {}

    llms_lines = [
        f"# {name} — Knowledge Portal",
        "",
        "> Interactive software architecture, AST knowledge graph, and AI query engine.",
        "",
        "## Snapshot Metrics",
        f"- Graph Nodes: {len(nodes)}",
        f"- Graph Edges: {len(edges)}",
        f"- Architectural Health: {h_sum.get('health_score', 'N/A')}/100 (Grade {h_sum.get('grade', 'N/A')})",
        f"- Dependency Cycles: {h_sum.get('cycle_count', 0)} | Orphans: {h_sum.get('orphan_count', 0)}",
        "",
        "## Primary Views",
        "- `/dashboard.html` — Main portal shell & live search",
        "- `/views/graph-studio.html` — Unified Graph Studio (2D/3D Network, Z-Planes, Chord, Tree/Treemap/Sunburst)",
        "- `/views/floorplan.html` — Architectural Vector Floorplan",
        "- `/views/database-schema.html` — Interactive DB Schema & ERD",
        "- `/views/process-flows.html` — Execution & Process Flows",
        "- `/views/live-telemetry.html` — Live System Telemetry & Sync Status",
        "",
        "## AI & Machine-Readable Endpoints",
        "- `GET /api/search?q=<term>&limit=15` — SQLite FTS5 BM25 instant search",
        "- `GET /api/context-pack?q=<topic>&max_tokens=4000` — Compressed single-call AI briefing",
        "- `GET /api/impact?target=<symbol_or_file>&depth=3` — Reverse-dependency blast radius",
        "- `GET /api/health-audit` — Architectural health audit (cycles, orphans, god-files)",
        "- `GET /api/telemetry` — Live host & portal status",
        "- `GET /llms-full.txt` — Extended full-context snapshot",
        "",
        "## MCP Integration (Stdio JSON-RPC 2.0)",
        "- Standard mode (10+ tools): `knowledge-portal mcp --dir .`",
        "- Compact Code Mode (2 tools, ~1k token schema): `knowledge-portal mcp --dir . --code-mode`",
        "",
    ]

    full_lines = list(llms_lines)

    god_files = health.get("god_files") or []
    if god_files:
        full_lines.append("## Core Architectural Hubs (Top Connected Modules)")
        for g in god_files[:15]:
            full_lines.append(
                f"- `{g.get('path') or g.get('id')}` (in={g.get('in_degree', 0)}, out={g.get('out_degree', 0)}, loc={g.get('loc', 0)})"
            )
        full_lines.append("")

    cycles = health.get("cycles") or []
    if cycles:
        full_lines.append("## Dependency Cycles")
        for idx, cyc in enumerate(cycles[:10], 1):
            full_lines.append(f"- Cycle #{idx}: " + " -> ".join(cyc[:8]))
        full_lines.append("")

    if isinstance(stack, dict) and stack:
        full_lines.append("## Technology Stack Summary")
        langs = stack.get("languages") or stack.get("summary") or {}
        if isinstance(langs, dict):
            for k, v in list(langs.items())[:15]:
                full_lines.append(f"- {k}: {v}")
        full_lines.append("")

    flow_list = flows.get("flows") if isinstance(flows, dict) else (flows if isinstance(flows, list) else [])
    if flow_list:
        full_lines.append("## Key Execution & Process Flows")
        for fl in flow_list[:20]:
            if isinstance(fl, dict):
                full_lines.append(f"- **{fl.get('name') or fl.get('id', 'Flow')}**: {fl.get('description', '')}")
        full_lines.append("")

    tables = schema.get("tables") if isinstance(schema, dict) else []
    if isinstance(tables, list) and tables:
        full_lines.append("## Database Schema Tables")
        for tbl in tables[:30]:
            if isinstance(tbl, dict):
                cols = tbl.get("columns") or []
                full_lines.append(f"- `{tbl.get('name')}` ({len(cols)} columns)")
        full_lines.append("")

    llms_path = output_dir / "llms.txt"
    llms_full_path = output_dir / "llms-full.txt"
    llms_path.write_text("\n".join(llms_lines), encoding="utf-8")
    llms_full_path.write_text("\n".join(full_lines), encoding="utf-8")

    return {"llms.txt": llms_path, "llms-full.txt": llms_full_path}
