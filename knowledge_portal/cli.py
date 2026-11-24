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

    # Command: floorplan
    floorplan_p = subparsers.add_parser("floorplan", help="Generate interactive vector floorplan from architecture.yaml")
    floorplan_p.add_argument("file", nargs="?", default="architecture.yaml", help="Path to architecture.yaml (default: architecture.yaml)")
    floorplan_p.add_argument("--output", "-o", default=None, help="Output path for generated HTML (default: template/views/floorplan.html)")

    # Command: audit
    audit_p = subparsers.add_parser("audit", help="Run Zero-Proprietary Sanitization Audit")
    audit_p.add_argument("path", nargs="?", default=".", help="Directory to audit")

    # Command: mcp
    mcp_p = subparsers.add_parser("mcp", help="Start stdio MCP (Model Context Protocol) server for AI agents")
    mcp_p.add_argument("--dir", "-d", default=".", help="Project root directory (default: current directory)")
    mcp_p.add_argument("--data-dir", default=None, help="Portal data directory (default: template/data)")
    mcp_p.add_argument("--url", default="http://127.0.0.1:8000", help="Running portal URL for live telemetry")
    mcp_p.add_argument("--code-mode", action="store_true", help="Expose compact 2-tool Cloudflare-style Code Mode MCP (~1k token schema)")

    # Command: status
    status_p = subparsers.add_parser("status", help="Inspect live portal telemetry or static snapshot status")
    status_p.add_argument("--url", default="http://127.0.0.1:8000", help="Running portal URL (default: http://127.0.0.1:8000)")
    status_p.add_argument("--data-dir", default=None, help="Portal data directory (default: template/data)")
    status_p.add_argument("--json", action="store_true", help="Output raw JSON")

    # Command: query
    query_p = subparsers.add_parser("query", help="Query portal knowledge artifacts (search, flow, schema, stack)")
    query_p.add_argument("term", nargs="?", default="", help="Search term or table/symbol name")
    query_p.add_argument("--type", "-t", choices=["search", "flow", "schema", "stack", "impact", "health", "context-pack", "api-catalog", "arch-diff"], default="search", help="Query target")
    query_p.add_argument("--limit", "-l", type=int, default=15, help="Max results")
    query_p.add_argument("--data-dir", default=None, help="Portal data directory (default: template/data)")
    query_p.add_argument("--dir", "-d", default=".", help="Project root directory")

    # Command: report
    report_p = subparsers.add_parser("report", help="Generate Executive Markdown or SARIF 2.1.0 audit report")
    report_p.add_argument("--format", "-f", choices=["md", "sarif"], default="md", help="Report format (default: md)")
    report_p.add_argument("--output", "-o", default=None, help="Write report to file instead of stdout")
    report_p.add_argument("--data-dir", default=None, help="Portal data directory (default: template/data)")
    report_p.add_argument("--dir", "-d", default=".", help="Project root directory")

    # Command: gate
    gate_p = subparsers.add_parser("gate", help="CI Quality Gate — exits 0 on pass, 1 on threshold violation")
    gate_p.add_argument("--min-score", type=int, default=0, help="Minimum required Health Score (0-100)")
    gate_p.add_argument("--max-cycles", type=int, default=None, help="Maximum allowed dependency cycles")
    gate_p.add_argument("--max-critical", type=int, default=None, help="Maximum allowed CRITICAL security/SRE findings")
    gate_p.add_argument("--data-dir", default=None, help="Portal data directory (default: template/data)")
    gate_p.add_argument("--dir", "-d", default=".", help="Project root directory")

    # Command: pr-comment
    pr_p = subparsers.add_parser("pr-comment", help="Generate Markdown PR review comment with Doc-Drift & impacted tests")
    pr_p.add_argument("--base", "-b", default="main", help="Base git ref to diff against (default: main)")
    pr_p.add_argument("--data-dir", default=None, help="Portal data directory (default: template/data)")
    pr_p.add_argument("--dir", "-d", default=".", help="Project root directory")

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

        from knowledge_portal.generators.stack_inventory import generate_stack_inventory
        from knowledge_portal.generators.arch_health import generate_arch_health
        from knowledge_portal.generators.api_catalog import generate_api_catalog
        from knowledge_portal.generators.call_graph import generate_call_graph
        from knowledge_portal.generators.ownership import generate_ownership_map
        from knowledge_portal.generators.config_matrix import generate_config_matrix
        from knowledge_portal.generators.iac_topology import generate_iac_topology
        from knowledge_portal.generators.ai_registry import generate_ai_registry
        from knowledge_portal.generators.cve_ingestor import generate_cve_report
        from knowledge_portal.generators.compliance_evidence import generate_compliance_evidence
        from knowledge_portal.generators.llms_txt import generate_llms_manifests
        from knowledge_portal.generators.git_dag import generate_git_dag
        from knowledge_portal.generators.adr_graph import generate_adr_graph
        from knowledge_portal.generators.mission_control import generate_mission_control
        generate_stack_inventory(target, out)
        generate_cve_report(target, out)
        generate_api_catalog(target, out)
        generate_call_graph(target, out)
        generate_ownership_map(target, out)
        generate_config_matrix(target, out)
        generate_iac_topology(target, out)
        generate_ai_registry(target, out)
        generate_arch_health(out, project_dir=target)
        generate_compliance_evidence(target, out)
        generate_git_dag(target, out)
        generate_adr_graph(target, out)
        generate_mission_control(target, out)
        generate_llms_manifests(target, out, template_dir)

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

    elif args.command == "floorplan":
        from knowledge_portal.server import get_template_dir
        from knowledge_portal.generators.floorplan import generate_floorplan_from_yaml
        yaml_file = Path(args.file).resolve()
        template_dir = get_template_dir()
        out_html = Path(args.output).resolve() if args.output else (template_dir / "views" / "floorplan.html")

        print(f"🏗️ Compiling declarative floorplan: {yaml_file}")
        generated = generate_floorplan_from_yaml(yaml_file, out_html)
        print("✅ Floorplan generated successfully!")
        print(f"   Interactive Vector View: {generated}")

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

    elif args.command == "mcp":
        from knowledge_portal.mcp_server import run_mcp_stdio
        from knowledge_portal.server import get_template_dir
        data_dir = Path(args.data_dir).resolve() if args.data_dir else (get_template_dir() / "data")
        run_mcp_stdio(project_dir=Path(args.dir), data_dir=data_dir, portal_url=args.url, code_mode=getattr(args, "code_mode", False))

    elif args.command == "status":
        import json
        from knowledge_portal.mcp_server import PortalMcpEngine
        from knowledge_portal.server import get_template_dir
        data_dir = Path(args.data_dir).resolve() if args.data_dir else (get_template_dir() / "data")
        engine = PortalMcpEngine(project_dir=Path.cwd(), data_dir=data_dir, portal_url=args.url)
        res = engine.telemetry(args.url)
        if args.json:
            print(json.dumps(res, indent=2, ensure_ascii=False))
        else:
            mode = "LIVE" if res.get("live") else "STATIC"
            print(f"Knowledge Portal [{mode}] ({res.get('url')})")
            print(json.dumps(res, indent=2, ensure_ascii=False))

    elif args.command == "query":
        import json
        from knowledge_portal.mcp_server import PortalMcpEngine
        from knowledge_portal.server import get_template_dir
        data_dir = Path(args.data_dir).resolve() if args.data_dir else (get_template_dir() / "data")
        engine = PortalMcpEngine(project_dir=Path(args.dir), data_dir=data_dir)
        dispatch = {
            "search": lambda: engine.search(args.term, args.limit),
            "flow": lambda: engine.process_flow(args.term, args.limit),
            "schema": lambda: engine.db_schema(args.term),
            "stack": lambda: engine.stack(args.term),
            "impact": lambda: engine.impact(args.term),
            "health": lambda: engine.health_audit(),
            "context-pack": lambda: engine.context_pack(args.term),
            "api-catalog": lambda: engine.api_catalog(args.term),
            "arch-diff": lambda: engine.arch_diff(),
        }
        print(json.dumps(dispatch[args.type](), indent=2, ensure_ascii=False))

    elif args.command == "report":
        import json
        from knowledge_portal.generators.arch_health import generate_arch_health
        from knowledge_portal.generators.audit_report import render_markdown_report, render_sarif_report
        from knowledge_portal.server import get_template_dir
        target = Path(args.dir).resolve()
        data_dir = Path(args.data_dir).resolve() if args.data_dir else (get_template_dir() / "data")
        health_file = data_dir / "arch-health.json"
        report_data = json.loads(health_file.read_text(encoding="utf-8")) if health_file.exists() else generate_arch_health(data_dir, project_dir=target)
        if args.format == "md":
            out_text = render_markdown_report(report_data, project_name=target.name)
        else:
            iac_file = data_dir / "iac-topology.json"
            cve_file = data_dir / "cve-report.json"
            iac_data = json.loads(iac_file.read_text(encoding="utf-8")) if iac_file.exists() else None
            cve_data = json.loads(cve_file.read_text(encoding="utf-8")) if cve_file.exists() else None
            out_text = json.dumps(render_sarif_report(report_data, iac_topology=iac_data, cve_report=cve_data), indent=2)
        if args.output:
            Path(args.output).write_text(out_text, encoding="utf-8")
            print(f"✅ Report written to {args.output}")
        else:
            print(out_text)

    elif args.command == "gate":
        import json
        from knowledge_portal.generators.arch_health import generate_arch_health
        from knowledge_portal.generators.audit_report import evaluate_quality_gate
        from knowledge_portal.server import get_template_dir
        target = Path(args.dir).resolve()
        data_dir = Path(args.data_dir).resolve() if args.data_dir else (get_template_dir() / "data")
        health_file = data_dir / "arch-health.json"
        report_data = json.loads(health_file.read_text(encoding="utf-8")) if health_file.exists() else generate_arch_health(data_dir, project_dir=target)
        passed, reasons = evaluate_quality_gate(
            report_data,
            min_score=args.min_score,
            max_cycles=args.max_cycles,
            max_critical=args.max_critical,
        )
        if passed:
            s = report_data.get("summary") or {}
            print(f"✅ QUALITY GATE PASSED (Score: {s.get('health_score', 0)}/100 Grade {s.get('grade', '-')}, Cycles: {s.get('cycle_count', 0)})")
            sys.exit(0)
        else:
            print("❌ QUALITY GATE FAILED:")
            for r in reasons:
                print(f"   - {r}")
            sys.exit(1)

    elif args.command == "pr-comment":
        from knowledge_portal.mcp_server import PortalMcpEngine
        from knowledge_portal.server import get_template_dir
        target = Path(args.dir).resolve()
        data_dir = Path(args.data_dir).resolve() if args.data_dir else (get_template_dir() / "data")
        engine = PortalMcpEngine(project_dir=target, data_dir=data_dir)
        ctx = engine.pr_context(base=args.base)
        print(ctx.get("pr_comment_markdown", ""))
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
