"""Unit tests for ADR-076 — 10/10 Enterprise Completeness."""

from __future__ import annotations

import json
from pathlib import Path

from knowledge_portal.codemode_sandbox import execute_codemode
from knowledge_portal.exporter.static_export import export_static_portal
from knowledge_portal.generators.api_catalog import generate_api_catalog
from knowledge_portal.generators.audit_report import (
    evaluate_quality_gate,
    render_markdown_report,
    render_sarif_report,
)
from knowledge_portal.generators.stack_inventory import generate_stack_inventory
from knowledge_portal.mcp_server import PortalMcpEngine, handle_jsonrpc_request


def test_api_catalog_polyglot_extraction_and_p4_gate(tmp_path: Path):
    repo = tmp_path / "poly_api"
    data_dir = tmp_path / "data"
    (repo / "backend" / "api").mkdir(parents=True)
    (repo / "node_svc").mkdir(parents=True)
    (repo / "go_svc").mkdir(parents=True)
    (repo / "core" / "frozen").mkdir(parents=True)

    (repo / "backend" / "api" / "items.py").write_text(
        '''router = APIRouter(prefix="/api/v1", tags=["Items"])

@router.get("/items")
def list_items():
    """List all items."""
    return []

@router.post("/items", response_model=ItemOut)
def create_item(user=Depends(get_current_user)):
    """Create a new item."""
    return {}
''',
        encoding="utf-8",
    )
    (repo / "node_svc" / "server.js").write_text(
        'app.get("/js/ping", (req, res) => res.send("pong"));\nrouter.delete("/js/items/:id", authGuard, delItem);\n',
        encoding="utf-8",
    )
    (repo / "go_svc" / "main.go").write_text(
        'package main\nfunc main() { r.GET("/go/status", statusHandler) }\n',
        encoding="utf-8",
    )
    (repo / "core" / "frozen" / "secret_routes.py").write_text(
        '@app.post("/secret")\ndef secret(): pass\n',
        encoding="utf-8",
    )

    cat = generate_api_catalog(repo, data_dir)
    assert cat["summary"]["total_endpoints"] == 5
    paths = {(e["method"], e["path"]) for e in cat["endpoints"]}
    assert ("GET", "/api/v1/items") in paths
    assert ("POST", "/api/v1/items") in paths
    assert ("GET", "/js/ping") in paths
    assert ("DELETE", "/js/items/:id") in paths
    assert ("GET", "/go/status") in paths
    assert all("frozen" not in e["file"] for e in cat["endpoints"])

    post_ep = next(e for e in cat["endpoints"] if e["method"] == "POST" and e["path"] == "/api/v1/items")
    assert post_ep["auth"] == "Protected"
    assert post_ep["response_model"] == "ItemOut"
    assert cat["openapi"]["openapi"] == "3.1.0"
    assert (data_dir / "api-catalog.json").exists()
    assert (data_dir / "api_catalog.js").exists()


def test_stack_inventory_cyclonedx_sbom_and_licenses(tmp_path: Path):
    repo = tmp_path / "sbom_repo"
    out = tmp_path / "out" / "data"
    (repo / "node_modules" / "demo-pkg").mkdir(parents=True)
    (repo / "LICENSE").write_text("MIT License\nPermission is hereby granted, free of charge...", encoding="utf-8")
    (repo / "requirements.txt").write_text("fastapi==0.110.0\n", encoding="utf-8")
    (repo / "package.json").write_text(
        json.dumps({"name": "web", "license": "MIT", "dependencies": {"demo-pkg": "^1.2.3"}}),
        encoding="utf-8",
    )
    (repo / "node_modules" / "demo-pkg" / "package.json").write_text(
        json.dumps({"name": "demo-pkg", "version": "1.2.3", "license": "GPL-3.0"}),
        encoding="utf-8",
    )

    inv = generate_stack_inventory(repo, out)
    assert inv["project_license"] == "MIT"
    assert inv["summary"]["copyleft_count"] == 1
    assert inv["sbom_summary"]["bom_format"] == "CycloneDX"
    assert inv["sbom_summary"]["spec_version"] == "1.5"

    sbom_path = out / "sbom.cdx.json"
    assert sbom_path.exists()
    sbom = json.loads(sbom_path.read_text(encoding="utf-8"))
    assert sbom["bomFormat"] == "CycloneDX"
    assert len(sbom["components"]) == 2


def test_audit_report_markdown_sarif_and_quality_gate():
    sample_report = {
        "summary": {"health_score": 82, "grade": "B", "total_modules": 40, "total_edges": 90, "cycle_count": 1, "layer_violation_count": 0},
        "radar": {"Zero Cycles": 85, "Layer Purity": 100},
        "cycles": [["a.py", "b.py"]],
        "health_v4": {
            "owasp_audit": {
                "findings_count": 1,
                "by_severity": {"CRITICAL": 1, "HIGH": 0, "MEDIUM": 0},
                "findings": [{"severity": "CRITICAL", "rule": "SQL_INJECTION_AST", "path": "api.py", "line": 12, "detail": "Dynamic SQL"}],
            },
            "reliability_ast": {"total_issues": 1, "async_blocking_count": 0, "missing_timeout_count": 1, "silent_except_count": 0, "async_blocking": [], "missing_timeout": [{"path": "svc.py", "line": 8, "call": "requests.get"}]},
            "api_governance": {"mutating_routes_scanned": 2, "unprotected_count": 0, "missing_response_model_count": 0, "unprotected_mutating_routes": []},
            "db_governance": {"n_plus_one_count": 0, "unbounded_select_count": 0, "unreferenced_tables_count": 0, "n_plus_one_loops": []},
            "observability": {"has_health_probe": True, "has_ready_probe": False, "prod_print_count": 0, "prod_console_log_count": 0},
            "test_quality": {"by_domain": [], "test_smells_count": 0},
            "supply_chain_and_ai": {"pyproject_unpinned_count": 0, "lockfiles_present": ["poetry.lock"], "context_bombs_count": 0},
        },
        "fix_queue": [{"priority": "P0", "category": "OWASP", "target": "api.py:12", "action": "Fix SQLi"}],
    }

    md = render_markdown_report(sample_report, project_name="DemoApp")
    assert "# Architectural & Security Health Report — DemoApp" in md
    assert "**82 / 100**" in md
    assert "Fix SQLi" in md

    sarif = render_sarif_report(sample_report)
    assert sarif["version"] == "2.1.0"
    assert len(sarif["runs"][0]["results"]) == 3  # 1 OWASP + 1 timeout + 1 cycle

    ok, reasons = evaluate_quality_gate(sample_report, min_score=80, max_cycles=2, max_critical=2)
    assert ok is True and reasons == []

    ok2, reasons2 = evaluate_quality_gate(sample_report, min_score=90, max_cycles=0, max_critical=0)
    assert ok2 is False and len(reasons2) == 3


def test_mcp_v2_resources_prompts_and_codemode_parity(tmp_path: Path):
    repo = tmp_path / "mcp_repo"
    data_dir = tmp_path / "data"
    repo.mkdir()
    data_dir.mkdir()
    (repo / "routes.py").write_text('@app.get("/ping")\ndef ping(): return "ok"\n', encoding="utf-8")
    (data_dir / "graph.json").write_text(json.dumps({"nodes": [], "edges": []}), encoding="utf-8")

    eng = PortalMcpEngine(project_dir=repo, data_dir=data_dir)
    init = handle_jsonrpc_request(eng, {"jsonrpc": "2.0", "id": 1, "method": "initialize"})
    assert init is not None
    caps = init["result"]["capabilities"]
    assert "resources" in caps and "prompts" in caps and "tools" in caps

    rlist = handle_jsonrpc_request(eng, {"jsonrpc": "2.0", "id": 2, "method": "resources/list"})
    assert rlist is not None and len(rlist["result"]["resources"]) == 5

    rread = handle_jsonrpc_request(eng, {"jsonrpc": "2.0", "id": 3, "method": "resources/read", "params": {"uri": "portal://api-catalog"}})
    assert rread is not None and "/ping" in rread["result"]["contents"][0]["text"]

    plist = handle_jsonrpc_request(eng, {"jsonrpc": "2.0", "id": 4, "method": "prompts/list"})
    assert plist is not None and len(plist["result"]["prompts"]) == 2

    pget = handle_jsonrpc_request(eng, {"jsonrpc": "2.0", "id": 5, "method": "prompts/get", "params": {"name": "audit_pr_impact", "arguments": {"target": "routes.py"}}})
    assert pget is not None and "routes.py" in pget["result"]["messages"][0]["content"]["text"]

    cm = execute_codemode(eng, "result = len(portal.api_catalog()['endpoints'])")
    assert cm["ok"] is True and cm["result"] == 1


def test_static_export_generates_all_adr076_artifacts(tmp_path: Path):
    src = tmp_path / "sample_proj"
    dist = tmp_path / "dist"
    src.mkdir()
    (src / "app.py").write_text('@app.get("/hello")\ndef hello():\n    """Say hi."""\n    return "hi"\n', encoding="utf-8")
    (src / "requirements.txt").write_text("pytest==8.0.0\n", encoding="utf-8")

    export_static_portal(src, dist, project_name="SampleProj")
    for fname in ("arch-health.json", "arch-diff.json", "api-catalog.json", "stack-ecosystem.json", "sbom.cdx.json"):
        assert (dist / "data" / fname).exists(), f"Missing exported artifact: {fname}"
    assert (dist / "llms.txt").exists()
