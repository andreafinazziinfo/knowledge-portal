"""
Knowledge Portal CLI
"""

import sys
import argparse
from pathlib import Path

def main():
    parser = argparse.ArgumentParser(
        prog="knowledge-portal",
        description="Knowledge Portal — Universal Interactive Software Architecture & AST Knowledge Engine"
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Command: scan
    scan_p = subparsers.add_parser("scan", help="Scan codebase AST and generate graph data")
    scan_p.add_argument("path", nargs="?", default=".", help="Root directory of the codebase to scan (default: current directory)")
    scan_p.add_argument("--output", "-o", default=None, help="Output directory for generated graph data (default: ./template/data)")
    scan_p.add_argument("--classic", action="store_true", help="Use classic Python-only AST scanner instead of polyglot")

    # Command: export
    export_p = subparsers.add_parser("export", help="Export static zero-server bundle ready for GitHub Pages or offline use")
    export_p.add_argument("path", nargs="?", default=".", help="Root directory of the codebase to export (default: current directory)")
    export_p.add_argument("--output", "-o", default="./dist", help="Output directory for static site (default: ./dist)")
    export_p.add_argument("--name", "-n", default=None, help="Project name (default: directory name)")

    # Command: serve
    serve_p = subparsers.add_parser("serve", help="Start the Knowledge Portal HTTP server with SSE live-reload")
    serve_p.add_argument("--host", default="0.0.0.0", help="Host interface to bind (default: 0.0.0.0)")
    serve_p.add_argument("--port", "-p", type=int, default=8000, help="Port to listen on (default: 8000)")
    serve_p.add_argument("--dir", "-d", default=".", help="Project directory to serve (default: current directory)")

    # Command: audit
    audit_p = subparsers.add_parser("audit", help="Run Zero-Proprietary Sanitization Audit")
    audit_p.add_argument("path", nargs="?", default=".", help="Directory to audit")

    args = parser.parse_args()

    if args.command == "scan":
        from knowledge_portal.server import get_template_dir
        target = Path(args.path).resolve()
        template_dir = get_template_dir()
        out = Path(args.output).resolve() if args.output else (template_dir / "data")

        print(f"🔍 Scanning codebase: {target}")
        if args.classic:
            from knowledge_portal.scanner.python_ast import scan_codebase
            stats = scan_codebase(target, out)
        else:
            from knowledge_portal.scanner.polyglot import scan_polyglot_codebase
            stats = scan_polyglot_codebase(target, out)

        from knowledge_portal.indexer.search_index import generate_search_index
        omni_file = template_dir / "views" / "data" / "omni-search-index.json"
        indexed_count = generate_search_index(target, omni_file)

        print("✅ Scan complete!")
        print(f"   Architecture Nodes: {stats['total_nodes']} | Edges: {stats['total_edges']} | Indexed Docs: {indexed_count}")
        print(f"   Data written to: {out}")

    elif args.command == "export":
        from knowledge_portal.exporter.static_export import export_static_portal
        target = Path(args.path).resolve()
        out = Path(args.output).resolve()
        export_static_portal(target, out, project_name=args.name)

    elif args.command == "serve":
        from knowledge_portal.server import run_server, get_template_dir
        run_server(host=args.host, port=args.port, template_dir=get_template_dir(), project_dir=Path(args.dir))

    elif args.command == "audit":
        audit_script = Path(__file__).resolve().parent.parent / "verify_sanitization.py"
        if audit_script.exists():
            import subprocess
            subprocess.run([sys.executable, str(audit_script), args.path])
        else:
            print("Audit script not found.")
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
