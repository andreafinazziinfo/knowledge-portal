"""Unit tests for ADR-077 — Enterprise Human & AI Codebase Intelligence."""

from __future__ import annotations

import json
from pathlib import Path

from knowledge_portal.codemode_sandbox import execute_codemode
from knowledge_portal.generators.call_graph import generate_call_graph
from knowledge_portal.generators.doc_drift import detect_doc_drift, render_pr_comment_markdown
from knowledge_portal.generators.ownership import generate_ownership_map, match_owners, parse_codeowners
from knowledge_portal.indexer.fts_engine import FtsSearchEngine
from knowledge_portal.mcp_server import PortalMcpEngine, handle_jsonrpc_request


def test_call_graph_extraction_chains_and_p4_gate(tmp_path: Path):
    repo = tmp_path / "cg_repo"
    data_dir = tmp_path / "data"
    (repo / "api").mkdir(parents=True)
    (repo / "svc").mkdir(parents=True)
    (repo / "core" / "frozen").mkdir(parents=True)

    (repo / "svc" / "orders.py").write_text(
        '''def save_order(db, order_id: int) -> dict:
    db.execute("INSERT INTO orders_tbl VALUES (?)", (order_id,))
    return {"id": order_id}
''',
        encoding="utf-8",
    )
    (repo / "api" / "routes.py").write_text(
        '''@router.post("/orders")
def create_order(db, oid: int) -> dict:
    return save_order(db, oid)
''',
        encoding="utf-8",
    )
    (repo / "core" / "frozen" / "secret.py").write_text(
        "def hidden_fn(): return 42\n",
        encoding="utf-8",
    )

    cg = generate_call_graph(repo, data_dir)
    assert cg["summary"]["total_symbols"] == 2
    assert cg["summary"]["total_call_edges"] == 1
    assert cg["summary"]["route_entries"] == 1
    assert len(cg["chains"]) == 1
    chain = cg["chains"][0]
    assert chain["label"] == "POST /orders"
    assert "orders_tbl" in chain["db_tables"]
    assert len(chain["steps"]) == 2
    assert all("frozen" not in k for k in cg["symbols"])
    assert (data_dir / "call-graph.json").exists()


def test_ownership_codeowners_and_conway_map(tmp_path: Path):
    repo = tmp_path / "own_repo"
    data_dir = tmp_path / "data"
    (repo / ".github").mkdir(parents=True)
    (repo / ".github" / "CODEOWNERS").write_text(
        "* @platform-team\nbackend/api/ @api-guild @sec-team\n",
        encoding="utf-8",
    )

    co_file, rules = parse_codeowners(repo)
    assert co_file == ".github/CODEOWNERS"
    assert len(rules) == 2
    assert match_owners("backend/api/orders.py", rules) == ["@api-guild", "@sec-team"]
    assert match_owners("README.md", rules) == ["@platform-team"]

    ow = generate_ownership_map(repo, data_dir)
    assert ow["codeowners_rules_count"] == 2
    assert (data_dir / "ownership.json").exists()


def test_ai_mission_pack_invariants_and_hybrid_search(tmp_path: Path):
    repo = tmp_path / "ai_repo"
    data_dir = tmp_path / "data"
    repo.mkdir()
    data_dir.mkdir()
    (repo / "auth.py").write_text('@app.post("/login")\ndef login(): return token_helper()\n', encoding="utf-8")
    (repo / "token_helper.py").write_text("def token_helper(): return 'jwt'\n", encoding="utf-8")
    (data_dir / "omni-search-index.json").write_text(
        json.dumps([{"name": "auth.py", "category": "code", "path": "auth.py", "tab": "reader", "subtitle": "login auth"}]),
        encoding="utf-8",
    )
    (data_dir / "graph.json").write_text(
        json.dumps({
            "nodes": [{"id": "auth.py", "path": "auth.py"}, {"id": "token_helper.py", "path": "token_helper.py"}],
            "edges": [{"source": "auth.py", "target": "token_helper.py"}],
        }),
        encoding="utf-8",
    )

    # Hybrid FTS5 + 1-hop graph expansion
    fts = FtsSearchEngine(data_dir)
    res_exp = fts.search("auth", limit=10, expand_graph=True)
    assert any(r.get("path") == "token_helper.py" and r.get("graph_expanded") for r in res_exp)

    # MCP Mission Pack & Invariants & Validate Change
    eng = PortalMcpEngine(project_dir=repo, data_dir=data_dir)
    val_bad = eng.validate_change(["core/frozen/secret.py"])
    assert val_bad["allowed"] is False
    assert val_bad["violations"][0]["rule"] == "P4_FROZEN_GATE"

    mp = eng.mission_pack("auth", max_tokens=2000)
    assert "# AI Mission Pack: auth" in mp["markdown"]
    assert mp["estimated_tokens"] <= 2000

    inv_res = handle_jsonrpc_request(eng, {"jsonrpc": "2.0", "id": 10, "method": "resources/read", "params": {"uri": "portal://invariants"}})
    assert inv_res is not None and "P4_FROZEN_GATE" in inv_res["result"]["contents"][0]["text"]

    cm = execute_codemode(eng, "result = portal.validate_change(['frozen/x.py'])['allowed']")
    assert cm["ok"] is True and cm["result"] is False


def test_doc_drift_detector_and_pr_comment(tmp_path: Path):
    repo = tmp_path / "drift_repo"
    (repo / "docs").mkdir(parents=True)
    (repo / "tests").mkdir(parents=True)
    (repo / "billing_engine.py").write_text("def charge(): pass\n", encoding="utf-8")
    (repo / "docs" / "BILLING.md").write_text("# Billing\nHandled by `billing_engine.py`.\n", encoding="utf-8")
    (repo / "tests" / "test_billing_engine.py").write_text("def test_charge(): assert True\n", encoding="utf-8")

    drift = detect_doc_drift(repo, base="main", changed_files=["billing_engine.py"])
    assert drift["stale_docs_count"] == 1
    assert drift["stale_docs"][0]["doc"] == "docs/BILLING.md"
    assert "tests/test_billing_engine.py" in drift["impacted_tests"]

    md = render_pr_comment_markdown(drift)
    assert "docs/BILLING.md" in md
    assert "pytest tests/test_billing_engine.py" in md
