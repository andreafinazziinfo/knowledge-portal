"""
Polyglot Architecture AST Scanner (Zero Dependencies)
Scans Python, TypeScript, JavaScript, Vue, Go, Rust, C/C++, Java/Kotlin, C#, and SQL source trees,
extracts structural symbols (classes, interfaces, functions, stores, structs, methods, tables),
and maps inter-file dependency edges into unified graph structures (graph.json and graph_viz.js).
"""

import ast
import json
import os
from pathlib import Path
import re
from typing import Any, Dict, List, Tuple

COMMUNITY_COLORS = [
    "#38bdf8", "#818cf8", "#34d399", "#f472b6", "#fbbf24",
    "#a78bfa", "#f87171", "#2dd4bf", "#fb923c", "#e879f9",
    "#4ade80", "#22d3ee", "#f43f5e", "#c084fc", "#60a5fa"
]


def sanitize_id(s: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_]", "_", s)



def _try_treesitter_extract(content: str, rel_path: str, lang: str) -> Tuple[bool, List[Dict[str, Any]]]:
    """Optional tree-sitter AST extraction when the [treesitter] extra is installed.
    Returns (True, extracted_nodes) if tree-sitter parsed the file, else (False, []).
    """
    try:
        from tree_sitter import Language, Parser  # type: ignore
    except Exception:
        return False, []

    mod_map = {
        "typescript": ("tree_sitter_typescript", "language_typescript"),
        "javascript": ("tree_sitter_javascript", "language"),
        "rust": ("tree_sitter_rust", "language"),
        "go": ("tree_sitter_go", "language"),
        "java": ("tree_sitter_java", "language"),
        "cpp": ("tree_sitter_cpp", "language"),
    }
    spec = mod_map.get(lang)
    if not spec:
        return False, []
    try:
        import importlib
        gram_mod = importlib.import_module(spec[0])
        lang_fn = getattr(gram_mod, spec[1])
        parser = Parser(Language(lang_fn()))
        tree = parser.parse(content.encode("utf-8", errors="ignore"))
    except Exception:
        return False, []

    target_types = {
        "function_declaration": "function",
        "method_definition": "method",
        "class_declaration": "class",
        "interface_declaration": "interface",
        "function_item": "function",
        "struct_item": "struct",
        "impl_item": "class",
        "method_declaration": "method",
        "type_spec": "struct",
    }
    extracted: List[Dict[str, Any]] = []
    stack = [tree.root_node]
    while stack:
        node = stack.pop()
        if node.type in target_types:
            name_node = node.child_by_field_name("name")
            if name_node is not None:
                sym = content.encode("utf-8", errors="ignore")[name_node.start_byte:name_node.end_byte].decode("utf-8", errors="ignore").strip()
                if sym:
                    extracted.append({
                        "id": f"ts_{lang}_{sanitize_id(rel_path)}_{sanitize_id(sym)}",
                        "label": sym,
                        "type": target_types[node.type],
                        "lang": lang,
                        "path": rel_path,
                        "parser": "tree-sitter",
                    })
        stack.extend(node.children)
    return (len(extracted) > 0), extracted


class PolyglotScanner:
    def __init__(self, target_dir: Path):
        self.target_dir = target_dir.resolve()
        self.nodes: List[Dict[str, Any]] = []
        self.edges: List[Dict[str, Any]] = []
        self.db_tables: Dict[str, Dict[str, Any]] = {}
        self.process_flows: List[Dict[str, Any]] = []
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
                doc = ast.get_docstring(node) or ""
                lineno = getattr(node, "lineno", 1)
                self.nodes.append({
                    "id": f_id,
                    "label": f"{node.name}()",
                    "type": "function",
                    "lang": "python",
                    "path": rel_path,
                    "line": lineno,
                    "doc": doc
                })

                # Check for route decorators or entrypoints
                route_path = None
                http_method = None
                is_endpoint = False

                for dec in getattr(node, "decorator_list", []):
                    if isinstance(dec, ast.Call):
                        if isinstance(dec.func, ast.Attribute):
                            attr_name = dec.func.attr.lower()
                            if attr_name in ["get", "post", "put", "delete", "patch"]:
                                is_endpoint = True
                                http_method = attr_name.upper()
                                if dec.args and isinstance(dec.args[0], ast.Constant) and isinstance(dec.args[0].value, str):
                                    route_path = dec.args[0].value
                            elif attr_name in ["route", "endpoint"]:
                                is_endpoint = True
                                http_method = "ANY"
                                if dec.args and isinstance(dec.args[0], ast.Constant) and isinstance(dec.args[0].value, str):
                                    route_path = dec.args[0].value
                        elif isinstance(dec.func, ast.Name):
                            dec_name = dec.func.id.lower()
                            if "route" in dec_name or "endpoint" in dec_name:
                                is_endpoint = True
                                http_method = "ANY"
                                if dec.args and isinstance(dec.args[0], ast.Constant) and isinstance(dec.args[0].value, str):
                                    route_path = dec.args[0].value

                # Analyze internal calls and SQL table access within function
                called_funcs = set()
                tables_accessed = set()

                for sub in ast.walk(node):
                    if isinstance(sub, ast.Call):
                        if isinstance(sub.func, ast.Name):
                            called_funcs.add(sub.func.id)
                        elif isinstance(sub.func, ast.Attribute):
                            called_funcs.add(sub.func.attr)
                    elif isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                        val_lower = sub.value.lower()
                        if any(k in val_lower for k in ["select ", "insert into", "update ", "from ", "delete from"]):
                            tbl_matches = re.findall(r"(?:from|into|update|join)\s+([a-zA-Z0-9_]+)", val_lower)
                            for t in tbl_matches:
                                if t not in ["where", "set", "select", "values"]:
                                    tables_accessed.add(t)
                            for tbl in self.db_tables.keys():
                                if re.search(rf"\b{re.escape(tbl)}\b", val_lower):
                                    tables_accessed.add(tbl)

                if is_endpoint:
                    self.process_flows.append({
                        "id": f"flow_{sanitize_id(rel_path)}_{node.name}",
                        "name": f"{http_method} {route_path or '/' + node.name}",
                        "category": "api_route",
                        "route": route_path or f"/{node.name}",
                        "method": http_method,
                        "entrypoint": {
                            "file": rel_path,
                            "function": node.name,
                            "line": lineno
                        },
                        "call_chain": sorted(list(called_funcs))[:10],
                        "tables_accessed": sorted(list(tables_accessed)),
                        "description": doc or f"API Route handler {node.name}"
                    })
                elif node.name in ["main", "cli", "run", "serve", "scan", "export"] or any("command" in getattr(d, "id", getattr(d, "attr", "")).lower() for d in getattr(node, "decorator_list", [])):
                    self.process_flows.append({
                        "id": f"flow_{sanitize_id(rel_path)}_{node.name}",
                        "name": f"Flow: {node.name}()",
                        "category": "cli_command",
                        "route": None,
                        "method": None,
                        "entrypoint": {
                            "file": rel_path,
                            "function": node.name,
                            "line": lineno
                        },
                        "call_chain": sorted(list(called_funcs))[:10],
                        "tables_accessed": sorted(list(tables_accessed)),
                        "description": doc or f"Command/Entrypoint {node.name}()"
                    })

    def parse_typescript_javascript(self, content: str, rel_path: str):
        ts_lang = "typescript" if rel_path.endswith((".ts", ".tsx")) else "javascript"
        ok_ts, ts_nodes = _try_treesitter_extract(content, rel_path, ts_lang)
        if ok_ts:
            self.nodes.extend(ts_nodes)
        lines = content.splitlines()
        cls_pattern = re.compile(r"^\s*(?:export\s+)?(?:default\s+)?(?:abstract\s+)?(class|interface)\s+([A-Za-z0-9_]+)")
        pinia_pattern = re.compile(r"^\s*(?:export\s+)?const\s+(use[A-Za-z0-9_]*Store)\s*=\s*defineStore\s*\(\s*['\"]([^'\"]+)['\"]")
        func_pattern = re.compile(r"^\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z0-9_]+)\s*\(")
        const_fn_pattern = re.compile(r"^\s*export\s+const\s+([A-Za-z0-9_]+)\s*=\s*(?:async\s*)?\(")
        import_pattern = re.compile(r"import\s+.*?from\s+['\"]([^'\"]+)['\"]")
        route_pattern = re.compile(r"(?:app|router)\.(get|post|put|delete|patch)\s*\(\s*['\"]([^'\"]+)['\"]")

        for idx, line in enumerate(lines, start=1):
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

            m_rt = route_pattern.search(line)
            if m_rt:
                m_method = m_rt.group(1).upper()
                m_path = m_rt.group(2)
                self.process_flows.append({
                    "id": f"flow_ts_{sanitize_id(rel_path)}_{idx}",
                    "name": f"{m_method} {m_path}",
                    "category": "api_route",
                    "route": m_path,
                    "method": m_method,
                    "entrypoint": {
                        "file": rel_path,
                        "function": f"route_{m_method.lower()}",
                        "line": idx
                    },
                    "call_chain": [],
                    "tables_accessed": [],
                    "description": f"Express/TypeScript Route {m_method} {m_path}"
                })

            m_imp = import_pattern.search(line)
            if m_imp:
                imp_target = m_imp.group(1)
                if imp_target.startswith("."):
                    target_rel = os.path.normpath(os.path.join(os.path.dirname(rel_path), imp_target)).replace("\\", "/")
                    self.edges.append({
                        "source": rel_path,
                        "target": target_rel,
                        "type": "imports"
                    })

    def parse_vue(self, content: str, rel_path: str):
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
            self.parse_typescript_javascript(script_match.group(1), rel_path)

    def parse_go(self, content: str, rel_path: str):
        lines = content.splitlines()
        type_pattern = re.compile(r"^\s*type\s+([A-Za-z0-9_]+)\s+(struct|interface)")
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
        decl_pattern = re.compile(r"^\s*(?:pub(?:\([^)]+\))?\s+)?(struct|enum|trait)\s+([A-Za-z0-9_]+)")
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

    def parse_cpp_c(self, content: str, rel_path: str):
        lines = content.splitlines()
        cls_pattern = re.compile(r"^\s*(?:class|struct)\s+([A-Za-z0-9_]+)\s*(?::\s*[^{]*)?\{?")
        fn_pattern = re.compile(r"^\s*(?:(?:virtual|static|inline|explicit)\s+)*[A-Za-z0-9_:<>&*]+\s+([A-Za-z0-9_]+)\s*\([^)]*\)\s*(?:const)?\s*(?:\{.*)?$")

        for idx, line in enumerate(lines, start=1):
            m_c = cls_pattern.search(line)
            if m_c:
                name = m_c.group(1)
                c_id = f"cpp_cls_{sanitize_id(rel_path)}_{name}"
                self.nodes.append({
                    "id": c_id,
                    "label": name,
                    "type": "class",
                    "lang": "cpp",
                    "path": rel_path,
                    "line": idx,
                    "doc": "C/C++ Class/Struct"
                })
                continue

            m_f = fn_pattern.search(line)
            if m_f:
                name = m_f.group(1)
                if name not in ["if", "for", "while", "switch"]:
                    f_id = f"cpp_fn_{sanitize_id(rel_path)}_{name}"
                    self.nodes.append({
                        "id": f_id,
                        "label": f"{name}()",
                        "type": "function",
                        "lang": "cpp",
                        "path": rel_path,
                        "line": idx,
                        "doc": "C/C++ Function"
                    })

    def parse_java_kotlin(self, content: str, rel_path: str):
        lines = content.splitlines()
        type_pattern = re.compile(r"^\s*(?:public|protected|private)?\s*(?:abstract|final|open|data)?\s*(class|interface|enum|record)\s+([A-Za-z0-9_]+)")
        fn_pattern = re.compile(r"^\s*(?:public|protected|private|override)?\s*(?:fun\s+|[A-Za-z0-9_<>\[\]]+\s+)([A-Za-z0-9_]+)\s*\(")

        for idx, line in enumerate(lines, start=1):
            m_t = type_pattern.search(line)
            if m_t:
                kind, name = m_t.group(1), m_t.group(2)
                t_id = f"jvm_{kind}_{sanitize_id(rel_path)}_{name}"
                self.nodes.append({
                    "id": t_id,
                    "label": name,
                    "type": kind,
                    "lang": "java",
                    "path": rel_path,
                    "line": idx,
                    "doc": f"JVM {kind}"
                })
                continue

            m_fn = fn_pattern.search(line)
            if m_fn:
                name = m_fn.group(1)
                if name not in ["if", "for", "while", "catch", "synchronized"]:
                    f_id = f"jvm_fn_{sanitize_id(rel_path)}_{name}"
                    self.nodes.append({
                        "id": f_id,
                        "label": f"{name}()",
                        "type": "function",
                        "lang": "java",
                        "path": rel_path,
                        "line": idx,
                        "doc": "JVM Method"
                    })

    def parse_csharp(self, content: str, rel_path: str):
        lines = content.splitlines()
        type_pattern = re.compile(r"^\s*(?:public|internal|private)?\s*(?:static|abstract|sealed)?\s*(class|interface|record|struct)\s+([A-Za-z0-9_]+)")
        fn_pattern = re.compile(r"^\s*(?:public|private|protected|internal)\s+(?:async\s+)?[A-Za-z0-9_<>\[\]]+\s+([A-Za-z0-9_]+)\s*\(")

        for idx, line in enumerate(lines, start=1):
            m_t = type_pattern.search(line)
            if m_t:
                kind, name = m_t.group(1), m_t.group(2)
                t_id = f"cs_{kind}_{sanitize_id(rel_path)}_{name}"
                self.nodes.append({
                    "id": t_id,
                    "label": name,
                    "type": kind,
                    "lang": "csharp",
                    "path": rel_path,
                    "line": idx,
                    "doc": f"C# {kind}"
                })
                continue

            m_fn = fn_pattern.search(line)
            if m_fn:
                name = m_fn.group(1)
                f_id = f"cs_fn_{sanitize_id(rel_path)}_{name}"
                self.nodes.append({
                    "id": f_id,
                    "label": f"{name}()",
                    "type": "function",
                    "lang": "csharp",
                    "path": rel_path,
                    "line": idx,
                    "doc": "C# Method"
                })

    def parse_sql(self, content: str, rel_path: str):
        # Strip comments
        clean = re.sub(r"--.*", "", content)
        clean = re.sub(r"/\*.*?\*/", "", clean, flags=re.DOTALL)

        table_block_pattern = re.compile(
            r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([A-Za-z0-9_.\"']+)\s*\((.*?)\)(?:\s*;|\s*$)",
            re.IGNORECASE | re.DOTALL
        )

        matches = list(table_block_pattern.finditer(clean))
        if not matches:
            # Fallback line-by-line if parenthesis not closed with semicolon
            table_pattern = re.compile(r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([A-Za-z0-9_.\"']+)", re.IGNORECASE)
            fk_pattern = re.compile(r"FOREIGN\s+KEY\s*\([^)]+\)\s*REFERENCES\s+([A-Za-z0-9_.\"']+)", re.IGNORECASE)
            current_table = None
            current_raw = None
            for line in content.splitlines():
                m_tbl = table_pattern.search(line)
                if m_tbl:
                    current_raw = m_tbl.group(1).strip("\"'").split(".")[-1]
                    t_id = f"sql_tbl_{sanitize_id(rel_path)}_{current_raw}"
                    current_table = t_id
                    self.nodes.append({
                        "id": t_id,
                        "label": f"🗄️ {current_raw}",
                        "type": "table",
                        "lang": "sql",
                        "path": rel_path,
                        "line": 1,
                        "doc": "SQL Table"
                    })
                    if current_raw not in self.db_tables:
                        self.db_tables[current_raw] = {
                            "name": current_raw,
                            "schema": "public",
                            "is_view": False,
                            "is_hypertable": False,
                            "is_cagg": False,
                            "columns": [],
                            "foreign_keys": [],
                            "readers": [],
                            "writers": [],
                            "ddl_sources": [{"file": rel_path, "kind": "CREATE_TABLE"}]
                        }
                    continue

                m_fk = fk_pattern.search(line)
                if m_fk and current_table and current_raw:
                    ref_tbl = m_fk.group(1).strip("\"'").split(".")[-1]
                    self.edges.append({
                        "source": current_table,
                        "target": ref_tbl,
                        "type": "foreign_key"
                    })
                    self.db_tables[current_raw]["foreign_keys"].append({
                        "name": f"fk_{current_raw}_{ref_tbl}",
                        "source_table": current_raw,
                        "target_table": ref_tbl
                    })
            return

        for m in matches:
            raw_tbl = m.group(1).strip("\"'").split(".")[-1]
            body = m.group(2)
            t_id = f"sql_tbl_{sanitize_id(rel_path)}_{raw_tbl}"

            self.nodes.append({
                "id": t_id,
                "label": f"🗄️ {raw_tbl}",
                "type": "table",
                "lang": "sql",
                "path": rel_path,
                "line": 1,
                "doc": "SQL Table"
            })

            columns: List[Dict[str, Any]] = []
            fks: List[Dict[str, Any]] = []
            pk_cols = set()

            lines = [stmt.strip() for stmt in body.splitlines() if stmt.strip()]
            for item in lines:
                item = item.rstrip(",")
                fk_m = re.search(r"FOREIGN\s+KEY\s*\(([^\)]+)\)\s*REFERENCES\s+([A-Za-z0-9_.\"']+)\s*(?:\(([^\)]+)\))?", item, re.IGNORECASE)
                if fk_m:
                    fk_col = fk_m.group(1).strip()
                    ref_tbl = fk_m.group(2).strip("\"'").split(".")[-1]
                    fks.append({
                        "name": f"fk_{raw_tbl}_{ref_tbl}",
                        "source_table": raw_tbl,
                        "target_table": ref_tbl,
                        "column": fk_col
                    })
                    self.edges.append({
                        "source": t_id,
                        "target": ref_tbl,
                        "type": "foreign_key"
                    })
                    continue

                pk_m = re.search(r"PRIMARY\s+KEY\s*\(([^\)]+)\)", item, re.IGNORECASE)
                if pk_m:
                    for c in pk_m.group(1).split(","):
                        pk_cols.add(c.strip().strip("\"'"))
                    continue

                parts = item.split()
                if parts and parts[0].upper() not in ["CONSTRAINT", "CHECK", "UNIQUE", "INDEX"]:
                    cname = parts[0].strip("\"'")
                    ctype = parts[1] if len(parts) > 1 else "TEXT"
                    is_pk = "PRIMARY KEY" in item.upper()
                    if is_pk:
                        pk_cols.add(cname)
                    nullable = "NOT NULL" not in item.upper() and not is_pk

                    inline_ref = re.search(r"REFERENCES\s+([A-Za-z0-9_.\"']+)", item, re.IGNORECASE)
                    if inline_ref:
                        ref_tbl = inline_ref.group(1).strip("\"'").split(".")[-1]
                        fks.append({
                            "name": f"fk_{raw_tbl}_{ref_tbl}",
                            "source_table": raw_tbl,
                            "target_table": ref_tbl,
                            "column": cname
                        })
                        self.edges.append({
                            "source": t_id,
                            "target": ref_tbl,
                            "type": "foreign_key"
                        })

                    columns.append({
                        "name": cname,
                        "type": ctype.upper(),
                        "pk": is_pk,
                        "nullable": nullable
                    })

            for col in columns:
                if col["name"] in pk_cols:
                    col["pk"] = True

            self.db_tables[raw_tbl] = {
                "name": raw_tbl,
                "schema": "public",
                "is_view": False,
                "is_hypertable": False,
                "is_cagg": False,
                "columns": columns,
                "foreign_keys": fks,
                "readers": [],
                "writers": [],
                "ddl_sources": [{"file": rel_path, "kind": "CREATE_TABLE"}]
            }

    def scan(self, max_files: int = 15000) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        supported_exts = {
            ".py", ".ts", ".js", ".vue", ".go", ".rs",
            ".cpp", ".c", ".h", ".hpp", ".cc", ".cxx",
            ".java", ".kt", ".cs", ".sql"
        }

        ignore_dirs = {
            ".git", "node_modules", "dist", "build", ".venv", "venv",
            "__pycache__", ".idea", ".vscode", "target", "vendor", "bin", "obj"
        }

        for root, dirs, files in os.walk(self.target_dir):
            dirs[:] = [d for d in dirs if d not in ignore_dirs and not d.startswith(".")]
            files.sort(key=lambda f: (0 if f.endswith(".sql") else 1, f))

            for fname in files:
                if self.file_count >= max_files:
                    break
                ext = os.path.splitext(fname)[1].lower()
                if ext not in supported_exts:
                    continue

                fpath = Path(root) / fname
                rel = str(fpath.relative_to(self.target_dir)).replace("\\", "/")
                self.file_count += 1

                try:
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
                    elif ext in [".cpp", ".c", ".h", ".hpp", ".cc", ".cxx"]:
                        self.parse_cpp_c(content, rel)
                    elif ext in [".java", ".kt"]:
                        self.parse_java_kotlin(content, rel)
                    elif ext == ".cs":
                        self.parse_csharp(content, rel)
                    elif ext == ".sql":
                        self.parse_sql(content, rel)
                except Exception as e:
                    print(f"[Polyglot Scanner] Warning: could not parse {rel}: {e}")

        # Fallback synthesis: if no process flows were explicitly found,
        # extract top functions/classes as primary process flows
        if not self.process_flows and self.nodes:
            top_fns = [n for n in self.nodes if n.get("type") in ["function", "method"]][:8]
            if not top_fns:
                top_fns = self.nodes[:8]
            for n in top_fns:
                self.process_flows.append({
                    "id": f"flow_auto_{n['id']}",
                    "name": f"Flow: {n['label']}",
                    "category": "service_flow",
                    "route": None,
                    "method": None,
                    "entrypoint": {
                        "file": n.get("path", ""),
                        "function": n.get("label", "").replace("()", ""),
                        "line": n.get("line", 1)
                    },
                    "call_chain": [],
                    "tables_accessed": list(self.db_tables.keys())[:3],
                    "description": n.get("doc", "") or f"Core flow {n['label']}"
                })

        return self.nodes, self.edges


def scan_polyglot_codebase(target_dir: Path, output_dir: Path) -> Dict[str, Any]:
    scanner = PolyglotScanner(target_dir)
    nodes, edges = scanner.scan()

    output_dir.mkdir(parents=True, exist_ok=True)

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

    graph_json_path = output_dir / "graph.json"
    graph_viz_js = output_dir / "graph_viz.js"
    config_js = output_dir / "config.js"

    with open(graph_json_path, "w", encoding="utf-8") as f:
        json.dump(graph_data, f, indent=2)

    with open(graph_viz_js, "w", encoding="utf-8") as f:
        f.write("window.GRAPH_VIZ = " + json.dumps(graph_data) + ";\n")

    with open(config_js, "w", encoding="utf-8") as f:
        f.write("window.GRAPH_CONFIG = { title: 'Knowledge Portal', node_limit: 15000 };\n")

    # Write db-schema.json and db_schema.js
    total_fks = sum(len(t.get("foreign_keys", [])) for t in scanner.db_tables.values())
    db_schema_data = {
        "schema_version": "1.0.0",
        "summary": {
            "total_tables": len(scanner.db_tables),
            "relationships_count": total_fks
        },
        "tables": list(scanner.db_tables.values())
    }

    db_json_path = output_dir / "db-schema.json"
    db_js_path = output_dir / "db_schema.js"

    with open(db_json_path, "w", encoding="utf-8") as f:
        json.dump(db_schema_data, f, indent=2)

    with open(db_js_path, "w", encoding="utf-8") as f:
        f.write("window.DB_SCHEMA = " + json.dumps(db_schema_data) + ";\n")

    # Write process-flows.json and process_flows.js
    flows_data = {
        "version": "1.0.0",
        "summary": {
            "total_flows": len(scanner.process_flows),
            "categories": sorted(list(set(f["category"] for f in scanner.process_flows)))
        },
        "flows": scanner.process_flows
    }

    flows_json_path = output_dir / "process-flows.json"
    flows_js_path = output_dir / "process_flows.js"

    with open(flows_json_path, "w", encoding="utf-8") as f:
        json.dump(flows_data, f, indent=2)

    with open(flows_js_path, "w", encoding="utf-8") as f:
        f.write("window.PROCESS_FLOWS = " + json.dumps(flows_data) + ";\n")

    # Detect active views for Adaptive Dashboard
    views_dir = output_dir.parent / "views" if output_dir.name == "data" else output_dir / "views"
    pkg_views_dir = Path(__file__).resolve().parent.parent.parent / "template" / "views"

    def has_view(view_name: str) -> bool:
        return (views_dir / f"{view_name}.html").exists() or (pkg_views_dir / f"{view_name}.html").exists()

    available_views = ["home", "reader"]
    if len(nodes) > 0:
        available_views.extend(["graph", "canvas", "tree", "graph_3d"])
    if len(scanner.db_tables) > 0 or has_view("db-lineage"):
        available_views.append("db-lineage")
    if has_view("floorplan"):
        available_views.append("floorplan")
    if has_view("api-catalog"):
        available_views.append("api-catalog")

    views_manifest = {
        "version": "1.0.0",
        "available_views": available_views
    }

    manifest_json_path = output_dir / "views-manifest.json"
    manifest_js_path = output_dir / "views_manifest.js"

    with open(manifest_json_path, "w", encoding="utf-8") as f:
        json.dump(views_manifest, f, indent=2)

    with open(manifest_js_path, "w", encoding="utf-8") as f:
        f.write("window.VIEWS_MANIFEST = " + json.dumps(views_manifest) + ";\n")

    report_md = output_dir / "GRAPH_REPORT.md"
    report_content = f"# Polyglot Codebase Architecture Report\n\n- Scanned Root: `{target_dir.resolve().name}`\n- Total Source Files: {scanner.file_count}\n- Total Architecture Nodes: {len(nodes)}\n- Total Edges: {len(edges)}\n- Total DB Tables: {len(scanner.db_tables)}\n- Total Process Flows: {len(scanner.process_flows)}\n"
    report_md.write_text(report_content, encoding="utf-8")

    return {
        "total_files": scanner.file_count,
        "total_words": scanner.word_count,
        "total_nodes": len(nodes),
        "total_edges": len(edges),
        "total_tables": len(scanner.db_tables),
        "total_flows": len(scanner.process_flows),
        "communities": min(len(COMMUNITY_COLORS), len(nodes)) if nodes else 0
    }
