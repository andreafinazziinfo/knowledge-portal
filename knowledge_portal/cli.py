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
    scan_p.add_argument("--output", "-o", default=None, help="Output directory for generated graph data (default: ./knowledge-portal-data)")

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
        from knowledge_portal.scanner.python_ast import scan_codebase
        from knowledge_portal.indexer.search_index import generate_search_index

        target = Path(args.path).resolve()
        pkg_root = Path(__file__).resolve().parent
        out = Path(args.output).resolve() if args.output else (pkg_root.parent / "template" / "data")

        print(f"🔍 Scanning codebase: {target}")
        stats = scan_codebase(target, out)
        omni_file = pkg_root.parent / "template" / "views" / "data" / "omni-search-index.json"
        indexed_count = generate_search_index(target, omni_file)

        print("✅ Scan complete!")
        print(f"   AST Nodes: {stats['total_nodes']} | Edges: {stats['total_edges']} | Indexed Docs: {indexed_count}")
        print(f"   Data written to: {out}")

    elif args.command == "serve":
        from knowledge_portal.server import run_server
        pkg_root = Path(__file__).resolve().parent
        template_dir = pkg_root.parent / "template"
        run_server(host=args.host, port=args.port, template_dir=template_dir, project_dir=Path(args.dir))

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
