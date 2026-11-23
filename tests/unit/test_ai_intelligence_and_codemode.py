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
    project_dir, data_dir = _make_sample_portal(tmp_path)
    (project_dir / "demo.py").write_text(
        'def complex_fn(x: int) -> int:\n    """Docstring."""\n    if x > 0:\n        for i in range(x):\n            if i % 2 == 0:\n                return i\n    return 0\n',
        encoding="utf-8",
    )
    report = generate_arch_health(data_dir, project_dir=project_dir)
    assert "radar" in report and len(report["radar"]) == 6
    assert "martin_metrics" in report and len(report["martin_metrics"]) >= 1
    assert "dsm" in report and len(report["dsm"]["domains"]) >= 1
    assert report["complexity"]["files_analyzed"] >= 1
    assert report["complexity"]["ai_readiness"]["docstring_coverage_pct"] == 100.0
    assert isinstance(report["history"], list) and len(report["history"]) >= 1
    assert isinstance(report["fix_queue"], list)
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


def test_health_engine_v4_all_eight_checks_and_p4_gate(tmp_path: Path):
    from knowledge_portal.generators.audit_analyzers import analyze_health_v4

    repo = tmp_path / "v4_repo"
    data_dir = tmp_path / "data"
    (repo / "backend" / "api").mkdir(parents=True)
    (repo / "frontend").mkdir(parents=True)
    (repo / "tests").mkdir(parents=True)
    (repo / "core" / "frozen").mkdir(parents=True)
    data_dir.mkdir(parents=True)

    (data_dir / "db-schema.json").write_text(
        json.dumps({"tables": [{"name": "orders", "columns": [{"name": "id", "pk": True}]}, {"name": "unused_legacy_tbl", "columns": [{"name": "id", "pk": True}]}]}),
        encoding="utf-8",
    )
    (repo / "backend" / "api" / "orders.py").write_text(
        '''import time
import requests

allow_origins = ["*"]

@router.get("/health")
def health_check():
    return {"ok": True}

@router.post("/orders")
async def create_order(oid: str, cursor, db, items):
    print("debug order")
    time.sleep(1)
    requests.get("https://api.example.com", verify=False)
    cursor.execute(f"SELECT id FROM orders WHERE id = {oid}")
    q = "SELECT id, name FROM orders"
    for it in items:
        db.execute("SELECT id FROM orders WHERE id = ?", (it,))
    try:
        return q
    except:
        pass
''',
        encoding="utf-8",
    )
    (repo / "frontend" / "app.vue").write_text(
        '<template><div v-html="raw"></div></template><script>console.log("dbg")</script>\n',
        encoding="utf-8",
    )
    (repo / "tests" / "test_orders.py").write_text(
        '''import time
import pytest

@pytest.mark.skip(reason="wip")
def test_skipped():
    assert True

def test_no_assert():
    time.sleep(0.01)
    x = 1 + 1
''',
        encoding="utf-8",
    )
    (repo / "pyproject.toml").write_text(
        '[project]\nname = "demo"\ndependencies = ["requests>=2.31", "pydantic==2.5.0"]\n',
        encoding="utf-8",
    )
    (repo / "poetry.lock").write_text("# lock\n", encoding="utf-8")
    # P4 Gate: frozen/ must be completely ignored
    fake_tok = "AKIA" + "IOSFODNN7EXAMPLE"
    (repo / "core" / "frozen" / "secret.py").write_text(
        f'AWS_KEY = "{fake_tok}"\ntry:\n    pass\nexcept:\n    pass\n',
        encoding="utf-8",
    )
    (repo / "llms.txt").write_text("# Demo\n", encoding="utf-8")

    res = analyze_health_v4(
        repo,
        data_dir=data_dir,
        complexity={"top_complex_files": [{"path": "backend/api/orders.py", "mccabe": 32, "loc": 50}]},
        git_crime_scene={
            "available": True,
            "hotspots": [{"path": "backend/api/orders.py", "commits": 8, "lines_churned": 220, "authors": 1, "hotspot_score": 43.2}],
            "temporal_coupling": [{"file_a": "backend/api/orders.py", "file_b": "frontend/app.vue", "co_changes": 4}],
        },
        coverage={"available": True, "overall_pct": 40.0, "lowest_covered": [{"path": "backend/api/orders.py", "coverage_pct": 10.0}]},
    )

    # 1. CodeScene Risk Matrix
    assert len(res["codescene_risk"]["top_risks"]) == 1
    assert res["codescene_risk"]["top_risks"][0]["risk_score"] > 10.0
    assert res["codescene_risk"]["temporal_coupling_enriched"][0]["coupling_ratio_pct"] > 0

    # 2. OWASP Quick-Audit (SQLi AST + TLS verify=False + CORS * + XSS v-html, zero frozen/)
    ow_rules = {f["rule"] for f in res["owasp_audit"]["findings"]}
    assert {"SQL_INJECTION_AST", "TLS_VERIFY_FALSE", "CORS_WILDCARD", "XSS_UNSAFE_HTML"} <= ow_rules
    assert all("frozen" not in f["path"] for f in res["owasp_audit"]["findings"])

    # 3. Reliability AST
    assert res["reliability_ast"]["async_blocking_count"] >= 1
    assert res["reliability_ast"]["missing_timeout_count"] >= 1
    assert res["reliability_ast"]["silent_except_count"] >= 1

    # 4. Observability
    assert res["observability"]["has_health_probe"] is True
    assert res["observability"]["prod_print_count"] >= 1
    assert res["observability"]["prod_console_log_count"] >= 1

    # 5. DB Governance
    assert res["db_governance"]["n_plus_one_count"] >= 1
    assert res["db_governance"]["unbounded_select_count"] >= 1
    assert "unused_legacy_tbl" in res["db_governance"]["unreferenced_tables"]
    assert "orders" not in res["db_governance"]["unreferenced_tables"]

    # 6. API Governance
    assert res["api_governance"]["mutating_routes_scanned"] == 1
    assert res["api_governance"]["unprotected_count"] == 1
    assert res["api_governance"]["missing_response_model_count"] == 1

    # 7. Test Suite Quality
    smell_rules = {s["rule"] for s in res["test_quality"]["test_smells"]}
    assert {"ASSERT_LESS_TEST", "SKIPPED_TEST", "SLEEP_IN_TEST"} <= smell_rules
    assert len(res["test_quality"]["by_domain"]) >= 1

    # 8. Supply Chain & AI
    assert res["supply_chain_and_ai"]["pyproject_unpinned_count"] == 1
    assert res["supply_chain_and_ai"]["has_lockfile"] is True
    assert res["supply_chain_and_ai"]["llms_txt_drift"]["status"] == "fresh"
    assert len(res["severity_summary"]) == 6


