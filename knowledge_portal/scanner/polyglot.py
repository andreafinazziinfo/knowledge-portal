"""
Polyglot Architecture AST Scanner (Zero Dependencies)
Scans Python, TypeScript, JavaScript, Vue, Go, and Rust source trees,
extracts structural symbols (classes, interfaces, functions, stores, structs, methods),
and maps inter-file dependency edges into unified graph structures (graph.json and graph_viz.js).
"""

import ast
import os
import re
import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

COMMUNITY_COLORS = [
    "#38bdf8", "#818cf8", "#34d399", "#f472b6", "#fbbf24",
    "#a78bfa", "#f87171", "#2dd4bf", "#fb923c", "#e879f9",
    "#4ade80", "#22d3ee", "#f43f5e", "#c084fc", "#60a5fa"
]

def sanitize_id(s: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_]", "_", s)

class PolyglotScanner:
    def __init__(self, target_dir: Path):
        self.target_dir = target_dir.resolve()
        self.nodes: List[Dict[str, Any]] = []
        self.edges: List[Dict[str, Any]] = []
        self.file_count = 0
        self.word_count = 0

    def parse_python(self, content: str, rel_path: str):
        try:
            tree = ast.parse(content)
        except Exception:
            return

        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                c_id = f"py_cls_{sanitize_id(rel_path)}_{node.name}"
                self.nodes.append({
                    "id": c_id,
                    "label": node.name,
                    "type": "class",
                    "lang": "python",
                    "path": rel_path,
                    "line": getattr(node, "lineno", 1),
                    "doc": ast.get_docstring(node) or ""
                })
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                f_id = f"py_fn_{sanitize_id(rel_path)}_{node.name}"
                self.nodes.append({
                    "id": f_id,
                    "label": f"{node.name}()",
                    "type": "function",
                    "lang": "python",
                    "path": rel_path,
                    "line": getattr(node, "lineno", 1),
                    "doc": ast.get_docstring(node) or ""
                })

    def parse_typescript_javascript(self, content: str, rel_path: str):
        lines = content.splitlines()

        # 1. Classes & Interfaces
        cls_pattern = re.compile(r"^\s*(?:export\s+)?(?:default\s+)?(?:abstract\s+)?(class|interface)\s+([A-Za-z0-9_]+)")
        # 2. Pinia Stores: const use...Store = defineStore('name', ...)
        pinia_pattern = re.compile(r"^\s*(?:export\s+)?const\s+(use[A-Za-z0-9_]*Store)\s*=\s*defineStore\s*\(\s*['\"]([^'\"]+)['\"]")
        # 3. Functions
        func_pattern = re.compile(r"^\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z0-9_]+)\s*\(")
        # 4. Exported Arrow Functions / Constants
        const_fn_pattern = re.compile(r"^\s*export\s+const\s+([A-Za-z0-9_]+)\s*=\s*(?:async\s*)?\(")
        # 5. Imports
        import_pattern = re.compile(r"import\s+.*?from\s+['\"]([^'\"]+)['\"]")

        for idx, line in enumerate(lines, start=1):
            # Classes / Interfaces
            m_cls = cls_pattern.search(line)
            if m_cls:
                kind, name = m_cls.group(1), m_cls.group(2)
                c_id = f"ts_{kind}_{sanitize_id(rel_path)}_{name}"
                self.nodes.append({
                    "id": c_id,
                    "label": name,
                    "type": kind,
                    "lang": "typescript",
                    "path": rel_path,
                    "line": idx,
                    "doc": f"TypeScript {kind}"
                })
                continue

            # Pinia Stores
            m_pinia = pinia_pattern.search(line)
            if m_pinia:
                store_var, store_id = m_pinia.group(1), m_pinia.group(2)
                p_id = f"ts_store_{sanitize_id(rel_path)}_{store_var}"
                self.nodes.append({
                    "id": p_id,
                    "label": f"🏪 {store_var}",
                    "type": "store",
                    "lang": "typescript",
                    "path": rel_path,
                    "line": idx,
                    "doc": f"Pinia Store ('{store_id}')"
                })
                continue

            # Functions
            m_fn = func_pattern.search(line) or const_fn_pattern.search(line)
            if m_fn:
                name = m_fn.group(1)
                f_id = f"ts_fn_{sanitize_id(rel_path)}_{name}"
                self.nodes.append({
                    "id": f_id,
                    "label": f"{name}()",
                    "type": "function",
                    "lang": "typescript",
                    "path": rel_path,
                    "line": idx,
                    "doc": "TypeScript Function"
                })

            # Imports
            m_imp = import_pattern.search(line)
            if m_imp:
                imp_target = m_imp.group(1)
                if not imp_target.startswith("."):
                    continue
                # Create a dependency edge
                target_rel = os.path.normpath(os.path.join(os.path.dirname(rel_path), imp_target)).replace("\\", "/")
                self.edges.append({
                    "source": rel_path,
                    "target": target_rel,
                    "type": "imports"
                })

    def parse_vue(self, content: str, rel_path: str):
        # Extract script section
        script_match = re.search(r"<script[^>]*>(.*?)</script>", content, re.DOTALL)
        comp_name = Path(rel_path).stem
        comp_id = f"vue_comp_{sanitize_id(rel_path)}_{comp_name}"
        self.nodes.append({
            "id": comp_id,
            "label": f"📦 <{comp_name}/>",
            "type": "component",
            "lang": "vue",
            "path": rel_path,
            "line": 1,
            "doc": "Vue 3 Component"
        })

        if script_match:
            script_content = script_match.group(1)
            self.parse_typescript_javascript(script_content, rel_path)

    def parse_go(self, content: str, rel_path: str):
        lines = content.splitlines()
        # Structs & Interfaces
        type_pattern = re.compile(r"^\s*type\s+([A-Za-z0-9_]+)\s+(struct|interface)")
        # Functions & Methods
        fn_pattern = re.compile(r"^\s*func\s+(?:\((?:[A-Za-z0-9_*\s]+)\)\s+)?([A-Za-z0-9_]+)\s*\(")

        for idx, line in enumerate(lines, start=1):
            m_t = type_pattern.search(line)
            if m_t:
                name, kind = m_t.group(1), m_t.group(2)
                t_id = f"go_{kind}_{sanitize_id(rel_path)}_{name}"
                self.nodes.append({
                    "id": t_id,
                    "label": name,
                    "type": kind,
                    "lang": "go",
                    "path": rel_path,
                    "line": idx,
                    "doc": f"Go {kind}"
                })
                continue

            m_fn = fn_pattern.search(line)
            if m_fn:
                name = m_fn.group(1)
                f_id = f"go_fn_{sanitize_id(rel_path)}_{name}"
                self.nodes.append({
                    "id": f_id,
                    "label": f"{name}()",
                    "type": "function",
                    "lang": "go",
                    "path": rel_path,
                    "line": idx,
                    "doc": "Go Function/Method"
                })

    def parse_rust(self, content: str, rel_path: str):
        lines = content.splitlines()
        # Struct, Enum, Trait
        decl_pattern = re.compile(r"^\s*(?:pub(?:\([^)]+\))?\s+)?(struct|enum|trait)\s+([A-Za-z0-9_]+)")
        # Functions
        fn_pattern = re.compile(r"^\s*(?:pub(?:\([^)]+\))?\s+)?(?:async\s+)?fn\s+([A-Za-z0-9_]+)")

        for idx, line in enumerate(lines, start=1):
            m_d = decl_pattern.search(line)
            if m_d:
                kind, name = m_d.group(1), m_d.group(2)
                d_id = f"rs_{kind}_{sanitize_id(rel_path)}_{name}"
                self.nodes.append({
                    "id": d_id,
                    "label": name,
                    "type": kind,
                    "lang": "rust",
                    "path": rel_path,
                    "line": idx,
                    "doc": f"Rust {kind}"
                })
                continue

            m_fn = fn_pattern.search(line)
            if m_fn:
                name = m_fn.group(1)
                f_id = f"rs_fn_{sanitize_id(rel_path)}_{name}"
                self.nodes.append({
                    "id": f_id,
                    "label": f"{name}()",
                    "type": "function",
                    "lang": "rust",
                    "path": rel_path,
                    "line": idx,
                    "doc": "Rust Function"
                })

    def scan(self, max_files: int = 15000) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        for root, _, files in os.walk(self.target_dir):
            if any(p in root for p in [".git", "node_modules", "dist", "build", "target", "vendor", "__pycache__", ".venv", "venv"]):
                continue
            for file in files:
                if self.file_count >= max_files:
                    break
                ext = Path(file).suffix.lower()
                if ext not in [".py", ".ts", ".js", ".vue", ".go", ".rs"]:
                    continue

                fpath = Path(root) / file
                rel = str(fpath.relative_to(self.target_dir)).replace("\\", "/")
                self.file_count += 1

                try:
                    # Circuit breaker on file size: skip files > 1.5MB
                    if fpath.stat().st_size > 1_500_000:
                        continue
                    content = fpath.read_text(encoding="utf-8", errors="replace")
                    self.word_count += len(content.split())

                    if ext == ".py":
                        self.parse_python(content, rel)
                    elif ext in [".ts", ".js"]:
                        self.parse_typescript_javascript(content, rel)
                    elif ext == ".vue":
                        self.parse_vue(content, rel)
                    elif ext == ".go":
                        self.parse_go(content, rel)
                    elif ext == ".rs":
                        self.parse_rust(content, rel)
                except Exception as e:
                    print(f"[Polyglot Scanner] Warning: could not parse {rel}: {e}")

        return self.nodes, self.edges

def scan_polyglot_codebase(target_dir: Path, output_dir: Path) -> Dict[str, Any]:
    scanner = PolyglotScanner(target_dir)
    nodes, edges = scanner.scan()

    output_dir.mkdir(parents=True, exist_ok=True)

    # Assign layout coordinates and communities
    viz_nodes = []
    for i, node in enumerate(nodes):
        comm = i % len(COMMUNITY_COLORS)
        viz_nodes.append({
            "id": node["id"],
            "label": node["label"],
            "community": comm,
            "color": COMMUNITY_COLORS[comm],
            "degree": 1,
            "path": node["path"],
            "lang": node.get("lang", "unknown"),
            "x": (i % 25) * 45 - 500,
            "y": (i // 25) * 45 - 300,
            "doc": node.get("doc", "")
        })

    graph_data = {
        "nodes": viz_nodes,
        "edges": edges,
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
        f.write("window.GRAPH_CONFIG = { title: 'Knowledge Portal', node_limit: 15000 };\n")

    report_md = output_dir / "GRAPH_REPORT.md"
    report_content = f"# Polyglot Codebase Architecture Report\n\n- Scanned Root: `{target_dir.resolve().name}`\n- Total Source Files: {scanner.file_count}\n- Total Architecture Nodes: {len(nodes)}\n- Total Edges: {len(edges)}\n"
    report_md.write_text(report_content, encoding="utf-8")

    return {
        "total_files": scanner.file_count,
        "total_words": scanner.word_count,
        "total_nodes": len(nodes),
        "total_edges": len(edges),
        "communities": min(len(COMMUNITY_COLORS), len(nodes)) if nodes else 0
    }
