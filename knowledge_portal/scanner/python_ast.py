"""
Generic Python AST Scanner (Zero Dependencies)
Scans Python source trees, extracts classes, functions, calls, and imports,
and generates standard graph visualization structures (graph.json and graph_viz.js).
"""

import ast
import os
import json
from pathlib import Path
from typing import Dict, Any

COMMUNITY_COLORS = [
    "#38bdf8", "#818cf8", "#34d399", "#f472b6", "#fbbf24",
    "#a78bfa", "#f87171", "#2dd4bf", "#fb923c", "#e879f9"
]

class CodeVisitor(ast.NodeVisitor):
    def __init__(self, file_path: str, rel_path: str):
        self.file_path = file_path
        self.rel_path = rel_path
        self.nodes: List[Dict[str, Any]] = []
        self.edges: List[Dict[str, Any]] = []
        self.current_class = None

    def visit_ClassDef(self, node):
        class_id = f"class_{self.rel_path}_{node.name}".replace("/", "_").replace(".", "_")
        self.nodes.append({
            "id": class_id,
            "label": node.name,
            "type": "class",
            "path": self.rel_path,
            "line": node.lineno,
            "doc": ast.get_docstring(node) or ""
        })
        prev_class = self.current_class
        self.current_class = class_id
        self.generic_visit(node)
        self.current_class = prev_class

    def visit_FunctionDef(self, node):
        func_id = f"func_{self.rel_path}_{node.name}".replace("/", "_").replace(".", "_")
        self.nodes.append({
            "id": func_id,
            "label": f"{node.name}()",
            "type": "function",
            "path": self.rel_path,
            "line": node.lineno,
            "doc": ast.get_docstring(node) or ""
        })
        if self.current_class:
            self.edges.append({
                "source": self.current_class,
                "target": func_id,
                "type": "method_of"
            })
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node):
        self.visit_FunctionDef(node)

def scan_codebase(target_dir: Path, output_dir: Path) -> Dict[str, Any]:
    all_nodes = []
    all_edges = []
    file_count = 0
    word_count = 0

    target_dir = target_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    for root, _, files in os.walk(target_dir):
        if any(p in root for p in [".git", "venv", ".venv", "__pycache__", "node_modules", "dist", "build"]):
            continue
        for file in files:
            if file.endswith(".py"):
                fpath = Path(root) / file
                rel = str(fpath.relative_to(target_dir)).replace("\\", "/")
                file_count += 1
                try:
                    content = fpath.read_text(encoding="utf-8", errors="replace")
                    word_count += len(content.split())
                    tree = ast.parse(content, filename=str(fpath))
                    visitor = CodeVisitor(str(fpath), rel)
                    visitor.visit(tree)
                    all_nodes.extend(visitor.nodes)
                    all_edges.extend(visitor.edges)
                except Exception as e:
                    print(f"[AST Scanner] Warning: could not parse {rel}: {e}")

    # Assign layout coordinates and communities
    viz_nodes = []
    for i, node in enumerate(all_nodes):
        comm = i % len(COMMUNITY_COLORS)
        viz_nodes.append({
            "id": node["id"],
            "label": node["label"],
            "community": comm,
            "color": COMMUNITY_COLORS[comm],
            "degree": 1,
            "path": node["path"],
            "x": (i % 20) * 40 - 400,
            "y": (i // 20) * 40 - 200,
            "doc": node.get("doc", "")
        })

    graph_data = {
        "nodes": viz_nodes,
        "edges": all_edges,
        "labels": {}
    }

    # Write data files
    graph_json_path = output_dir / "graph.json"
    graph_viz_js = output_dir / "graph_viz.js"
    config_js = output_dir / "config.js"

    with open(graph_json_path, "w", encoding="utf-8") as f:
        json.dump(graph_data, f, indent=2)

    with open(graph_viz_js, "w", encoding="utf-8") as f:
        f.write("window.GRAPH_VIZ = " + json.dumps(graph_data) + ";\n")

    with open(config_js, "w", encoding="utf-8") as f:
        f.write("window.GRAPH_CONFIG = { title: 'Knowledge Portal', node_limit: 5000 };\n")

    report_md = output_dir / "GRAPH_REPORT.md"
    report_content = f"# Codebase Architecture Report\n\n- Scanned Root: `{target_dir.name}`\n- Total Files: {file_count}\n- Total AST Nodes: {len(all_nodes)}\n- Total Edges: {len(all_edges)}\n"
    report_md.write_text(report_content, encoding="utf-8")

    return {
        "total_files": file_count,
        "total_words": word_count,
        "total_nodes": len(all_nodes),
        "total_edges": len(all_edges),
        "communities": min(len(COMMUNITY_COLORS), len(all_nodes)) if all_nodes else 0
    }
