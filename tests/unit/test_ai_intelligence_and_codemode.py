"""
Unit & Adversarial Security Tests for ADR-069:
- Architectural Health Auditor (Tarjan SCC cycles, orphans, god-files, layer violations, P4 Gate)
- llms.txt & llms-full.txt generator
- PortalMcpEngine impact(), health_audit(), context_pack()
- Cloudflare-Style Code Mode AST Sandbox (multi-step pipelines + escape attempts)
- MCP JSON-RPC --code-mode (2-tool compact schema vs full schema)
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from knowledge_portal.codemode_sandbox import (
    CodeModeLimitError,
    CodeModeSecurityError,
    execute_codemode,
    get_codemode_sdk_reference,
)
from knowledge_portal.generators.arch_health import generate_arch_health
from knowledge_portal.generators.llms_txt import generate_llms_manifests
from knowledge_portal.mcp_server import PortalMcpEngine, handle_jsonrpc_request
from knowledge_portal.scanner.polyglot import _try_treesitter_extract


def _make_sample_portal(tmp_path: Path) -> tuple[Path, Path]:
    project_dir = tmp_path / "proj"
    data_dir = tmp_path / "template" / "data"
    project_dir.mkdir(parents=True)
    data_dir.mkdir(parents=True)

    (project_dir / "README.md").write_text("# Demo Project\nHello architecture.\n", encoding="utf-8")

    graph = {
        "nodes": [
            {"id": "ui_page", "label": "DashboardPage", "path": "frontend/views/dashboard.tsx", "type": "file", "loc": 120},
            {"id": "api_srv", "label": "ApiServer", "path": "backend/server.py", "type": "file", "loc": 620},
            {"id": "auth_mod", "label": "AuthService", "path": "backend/auth.py", "type": "file", "loc": 150},
            {"id": "db_repo", "label": "UserRepo", "path": "backend/db/users.py", "type": "file", "loc": 90},
            {"id": "orphan_util", "label": "UnusedHelper", "path": "backend/orphan.py", "type": "file", "loc": 30},
            {"id": "frozen_secret", "label": "FrozenCore", "path": "core/frozen/secret.py", "type": "file", "loc": 999},
        ],
        "edges": [
            {"source": "ui_page", "target": "api_srv", "relation": "calls"},
            {"source": "api_srv", "target": "auth_mod", "relation": "imports"},
            {"source": "auth_mod", "target": "api_srv", "relation": "imports"},  # cycle!
            {"source": "auth_mod", "target": "db_repo", "relation": "imports"},
            {"source": "ui_page", "target": "db_repo", "relation": "imports"},  # layer violation!
        ],
    }
    (data_dir / "graph.json").write_text(json.dumps(graph), encoding="utf-8")

    omni = {
        "entities": [
            {"title": "ApiServer", "category": "backend", "path": "backend/server.py", "subtitle": "Main HTTP server"},
            {"title": "AuthService", "category": "backend", "path": "backend/auth.py", "subtitle": "JWT authentication"},
            {"title": "UserRepo", "category": "db", "path": "backend/db/users.py", "subtitle": "SQLite user storage"},
        ]
    }
    (data_dir / "omni-search-index.json").write_text(json.dumps(omni), encoding="utf-8")

    flows = {
        "flows": [
            {"id": "flow_login", "name": "User Login Flow", "description": "ui_page -> api_srv -> auth_mod -> db_repo"}
        ]
    }
    (data_dir / "process-flows.json").write_text(json.dumps(flows), encoding="utf-8")
    return project_dir, data_dir


def test_arch_health_detects_cycles_orphans_violations_and_excludes_frozen(tmp_path: Path):
    _, data_dir = _make_sample_portal(tmp_path)
    report = generate_arch_health(data_dir)
    summary = report["summary"]

    assert (data_dir / "arch-health.json").exists()
    assert summary["cycle_count"] == 1
    assert report["cycles"][0] == ["backend/auth.py", "backend/server.py"]
    assert summary["orphan_count"] == 1
    assert report["orphans"][0]["id"] == "orphan_util"
    assert summary["layer_violation_count"] == 1
    assert report["layer_violations"][0]["rule"] == "UI_TO_DB_DIRECT_DEPENDENCY"
    # P4 Gate: frozen node must never appear
    all_ids = {g["id"] for g in report["god_files"]} | {o["id"] for o in report["orphans"]}
    assert "frozen_secret" not in all_ids
    assert summary["total_nodes"] == 5


def test_llms_txt_generation(tmp_path: Path):
    project_dir, data_dir = _make_sample_portal(tmp_path)
    generate_arch_health(data_dir)
    out_dir = tmp_path / "template"
    paths = generate_llms_manifests(project_dir, data_dir, out_dir, project_name="DemoPortal")

    llms_txt = paths["llms.txt"].read_text(encoding="utf-8")
    llms_full = paths["llms-full.txt"].read_text(encoding="utf-8")
    assert "# DemoPortal — Knowledge Portal" in llms_txt
    assert "/views/graph-studio.html" in llms_txt
    assert "--code-mode" in llms_txt
    assert "User Login Flow" in llms_full
    assert "Dependency Cycles" in llms_full


def test_engine_impact_and_context_pack(tmp_path: Path):
    project_dir, data_dir = _make_sample_portal(tmp_path)
    eng = PortalMcpEngine(project_dir=project_dir, data_dir=data_dir)

    imp = eng.impact("db_repo", max_depth=3)
    assert imp["counts"]["d1"] == 2  # auth_mod and ui_page directly import db_repo
    assert imp["counts"]["total"] >= 3
    assert imp["risk"] in ("MEDIUM", "HIGH", "CRITICAL")

    pack = eng.context_pack("AuthService", max_tokens=500)
    assert pack["estimated_tokens"] <= 600
    assert "# Context Pack: AuthService" in pack["markdown"]
    assert "## Architectural Health" in pack["markdown"]


def test_codemode_multistep_pipeline_and_mcp_compact_mode(tmp_path: Path):
    project_dir, data_dir = _make_sample_portal(tmp_path)
    eng = PortalMcpEngine(project_dir=project_dir, data_dir=data_dir)

    code = """
hits = portal.search("auth", limit=5)["results"]
health = portal.health()["summary"]
imp = portal.impact("db_repo", max_depth=2)
result = {
    "hit_count": len(hits),
    "cycles": health["cycle_count"],
    "db_d1": imp["counts"]["d1"],
}
"""
    res = execute_codemode(eng, code)
    assert res["ok"] is True
    assert res["result"]["cycles"] == 1
    assert res["result"]["db_d1"] == 2

    # Verify --code-mode exposes exactly 2 tools
    resp_cm = handle_jsonrpc_request(eng, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, code_mode=True)
    assert resp_cm is not None
    cm_names = [t["name"] for t in resp_cm["result"]["tools"]]
    assert cm_names == ["portal_discover", "portal_codemode"]

    # Verify standard mode exposes all tools including new ones
    resp_std = handle_jsonrpc_request(eng, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, code_mode=False)
    assert resp_std is not None
    std_names = {t["name"] for t in resp_std["result"]["tools"]}
    assert {"portal_context_pack", "portal_impact", "portal_health_audit", "portal_codemode"}.issubset(std_names)

    # Verify discover reference
    ref = get_codemode_sdk_reference("impact")
    assert any("portal.impact" in m["call"] for m in ref["methods"])


@pytest.mark.parametrize(
    "malicious_code",
    [
        "import os\nresult = os.listdir('.')",
        "from pathlib import Path\nresult = str(Path('.'))",
        "result = ().__class__.__mro__",
        "result = portal._engine",
        "portal = 123",
        "result = open('/etc/passwd').read()",
        "result = __import__('os')",
        "result = eval('1+1')",
        "x = [1]\nresult = x.__class__",
    ],
)
def test_codemode_blocks_adversarial_escapes(tmp_path: Path, malicious_code: str):
    project_dir, data_dir = _make_sample_portal(tmp_path)
    eng = PortalMcpEngine(project_dir=project_dir, data_dir=data_dir)
    with pytest.raises((CodeModeSecurityError, CodeModeLimitError)):
        execute_codemode(eng, malicious_code)


def test_codemode_enforces_step_limit(tmp_path: Path):
    project_dir, data_dir = _make_sample_portal(tmp_path)
    eng = PortalMcpEngine(project_dir=project_dir, data_dir=data_dir)
    code = """
total = 0
for i in range(500):
    for j in range(500):
        total += 1
result = total
"""
    with pytest.raises(CodeModeLimitError):
        execute_codemode(eng, code, max_steps=200)


def test_treesitter_helper_graceful_fallback():
    ok, nodes = _try_treesitter_extract("function hello() { return 1; }", "app.js", "javascript")
    assert isinstance(ok, bool)
    assert isinstance(nodes, list)


def test_arch_health_v2_martin_metrics_radar_and_dsm(tmp_path: Path):
    _, data_dir = _make_sample_portal(tmp_path)
    report = generate_arch_health(data_dir)
    assert "radar" in report and len(report["radar"]) == 6
    assert "martin_metrics" in report and len(report["martin_metrics"]) >= 1
    assert "dsm" in report and len(report["dsm"]["domains"]) >= 1
    for m in report["martin_metrics"]:
        assert 0.0 <= m["instability"] <= 1.0
        assert 0.0 <= m["abstractness"] <= 1.0
        assert 0.0 <= m["distance"] <= 1.0


def test_polyglot_python_imports_and_domain_communities(tmp_path: Path):
    from knowledge_portal.scanner.polyglot import scan_polyglot_codebase

    repo = tmp_path / "sample_repo"
    (repo / "backend" / "api").mkdir(parents=True)
    (repo / "backend" / "services").mkdir(parents=True)
    (repo / "backend" / "services" / "auth.py").write_text("class AuthService:\n    pass\n", encoding="utf-8")
    (repo / "backend" / "api" / "routes.py").write_text(
        "from backend.services.auth import AuthService\ndef login():\n    return AuthService()\n",
        encoding="utf-8",
    )
    out = tmp_path / "out"
    scan_polyglot_codebase(repo, out)
    g = json.loads((out / "graph.json").read_text(encoding="utf-8"))
    assert len(g["edges"]) >= 1
    assert any("backend/services/auth.py" in e["target"] for e in g["edges"])
    assert len(g["labels"]) >= 1
    assert (out / "graph_labels.js").exists()

