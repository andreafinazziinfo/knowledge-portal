"""Unit tests for ADR-082 Wave 1 (AI-1 + AI-2 + Track A) & Wave 1.5 (Track B)."""

from __future__ import annotations

import json
from pathlib import Path

from knowledge_portal.generators.agent_instructions_audit import generate_agent_instructions_audit
from knowledge_portal.generators.module_cards import estimate_tokens, generate_module_cards
from knowledge_portal.generators.quality_telemetry import analyze_quality_telemetry
from knowledge_portal.generators.sarif_ingestor import generate_sarif_findings
from knowledge_portal.generators.test_oracle import generate_test_oracle
from knowledge_portal.mcp_server import PortalMcpEngine, handle_jsonrpc_request


def _seed_sample_repo(root: Path) -> Path:
    data = root / "data"
    data.mkdir(parents=True, exist_ok=True)
    (root / "backend" / "app" / "api").mkdir(parents=True, exist_ok=True)
    (root / "backend" / "tests").mkdir(parents=True, exist_ok=True)
    (root / "frontend" / "src" / "stores").mkdir(parents=True, exist_ok=True)
    (root / "reports").mkdir(parents=True, exist_ok=True)

    (root / "backend" / "app" / "api" / "orders.py").write_text(
        '"""Orders REST router."""\n'
        "import time\n"
        "import nonexistent_phantom_pkg\n"
        "from app.services import pricing\n\n"
        "@router.post('/api/v1/orders')\n"
        "async def create_order():\n"
        "    time.sleep(1)\n"
        "    q = 'SELECT * FROM orders_ledger'\n"
        "    return q\n",
        encoding="utf-8",
    )
    (root / "backend" / "app" / "api" / "untested_heavy.py").write_text(
        "\n".join([f"def fn_{i}(): return {i}" for i in range(220)]),
        encoding="utf-8",
    )
    (root / "backend" / "tests" / "test_orders.py").write_text(
        "import pytest\n"
        "from app.api import orders\n\n"
        "def test_create_order_fast(monkeypatch):\n"
        "    monkeypatch.setattr('app.api.orders.create_order', lambda: 'ok')\n"
        "    assert orders.create_order() == 'ok'\n",
        encoding="utf-8",
    )
    (root / "backend" / "tests" / "test_orders_e2e.py").write_text(
        "import pytest\n"
        "from app.api import orders\n\n"
        "@pytest.mark.slow\n"
        "def test_orders_slow(db_session):\n"
        "    assert orders is not None\n",
        encoding="utf-8",
    )
    (root / "frontend" / "src" / "stores" / "useOrders.ts").write_text(
        "// Orders Pinia store\n"
        "export const useOrdersStore = () => fetch('/api/v1/orders');\n",
        encoding="utf-8",
    )
    (root / "frontend" / "src" / "stores" / "useOrders.spec.ts").write_text(
        "import { useOrdersStore } from './useOrders'\n"
        "it('loads orders', () => { expect(useOrdersStore).toBeDefined() })\n",
        encoding="utf-8",
    )

    # Agent instructions with dead path, duplication, contradiction, and bloat
    (root / "CLAUDE.md").write_text(
        "# Agent Rules\n"
        "- Always use uv for Python dependency management in this repository.\n"
        "- Always check `backend/app/api/orders.py` before deploying.\n"
        "- Broken reference: `backend/app/api/missing_file.py`.\n"
        "- Always follow strict deterministic architecture rules across every module.\n"
        "- Always follow strict deterministic architecture rules across every module.\n",
        encoding="utf-8",
    )
    (root / "AGENTS.md").write_text(
        "# Secondary Agent Rules\n"
        "- Always use pip for Python dependency management in this repository.\n",
        encoding="utf-8",
    )

    # SARIF 2.1.0 report
    (root / "reports" / "semgrep.sarif").write_text(
        json.dumps({
            "version": "2.1.0",
            "runs": [{
                "tool": {"driver": {"name": "Semgrep"}},
                "results": [{
                    "ruleId": "python.lang.security.audit.exec-detected",
                    "level": "error",
                    "message": {"text": "Avoid dynamic exec"},
                    "locations": [{"physicalLocation": {"artifactLocation": {"uri": "backend/app/api/orders.py"}, "region": {"startLine": 7}}}],
                }],
            }],
        }),
        encoding="utf-8",
    )

    # Ecosystem telemetry reports: ESLint, Knip, Vulture, Deptry
    (root / "reports" / "eslint-report.json").write_text(
        json.dumps([{"filePath": "frontend/src/stores/useOrders.ts", "errorCount": 1, "warningCount": 0, "messages": [{"ruleId": "no-console", "severity": 2, "line": 2, "message": "Unexpected console"}]}]),
        encoding="utf-8",
    )
    (root / "reports" / "knip.json").write_text(
        json.dumps({"files": ["frontend/src/unused.ts"], "issues": [{"exports": ["foo"], "dependencies": ["left-pad"]}]}),
        encoding="utf-8",
    )
    (root / "reports" / "vulture.json").write_text(
        json.dumps([{"filename": "backend/app/api/orders.py", "first_lineno": 9, "name": "dead_fn", "confidence": 80, "message": "unused function"}]),
        encoding="utf-8",
    )
    (root / "reports" / "deptry.json").write_text(
        json.dumps([{"error": {"code": "DEP001", "message": "Missing dependency"}, "module": "requests", "location": {"file": "backend/app/api/orders.py"}}]),
        encoding="utf-8",
    )

    # Seed stack-ecosystem, graph, adr-graph (with one active & one superseded ADR)
    (data / "stack-ecosystem.json").write_text(
        json.dumps({"items": [{"name": "pytest", "version": "8.0.0", "ecosystem": "python"}]}),
        encoding="utf-8",
    )
    (data / "graph.json").write_text(
        json.dumps({
            "nodes": [
                {"id": "backend/app/api/orders.py", "path": "backend/app/api/orders.py", "label": "orders.py"},
                {"id": "frontend/src/stores/useOrders.ts", "path": "frontend/src/stores/useOrders.ts", "label": "useOrders.ts"},
            ],
            "edges": [{"source": "frontend/src/stores/useOrders.ts", "target": "backend/app/api/orders.py"}],
        }),
        encoding="utf-8",
    )
    (data / "adr-graph.json").write_text(
        json.dumps({
            "total_adrs": 2,
            "nodes": [
                {"id": "ADR-001", "title": "Legacy Orders Architecture", "status": "Superseded", "domain": "Backend"},
                {"id": "ADR-002", "title": "Orders Event Ledger", "status": "Accepted", "domain": "Backend"},
            ],
            "edges": [],
        }),
        encoding="utf-8",
    )
    return data


def test_generators_wave1_and_wave15(tmp_path: Path) -> None:
    data = _seed_sample_repo(tmp_path)

    # 1. Test Oracle
    oracle = generate_test_oracle(tmp_path, data)
    assert oracle["summary"]["total_test_files"] == 3
    assert "backend/app/api/orders.py" in oracle["source_to_tests"]
    assert oracle["source_to_tests"]["backend/app/api/orders.py"][0]["test"] == "backend/tests/test_orders.py"
    assert oracle["source_to_tests"]["backend/app/api/orders.py"][0]["tier"] == "fast"
    assert "frontend/src/stores/useOrders.ts" in oracle["source_to_tests"]
    assert any(b["path"] == "backend/app/api/untested_heavy.py" for b in oracle["blind_spots"])

    # 2. Module Cards (<= 180 tok/card)
    cards = generate_module_cards(tmp_path, data)
    assert cards["summary"]["total_files"] >= 3
    assert cards["summary"]["max_card_tokens"] <= 180
    order_card = cards["cards"]["backend/app/api/orders.py"]
    assert order_card["role"] == "fastapi_router"
    assert "POST /api/v1/orders" in order_card["routes"]
    assert "backend/tests/test_orders.py" in order_card["fast_tests"]
    assert estimate_tokens(order_card) <= 180

    # 3. Agent Instructions Audit
    audit = generate_agent_instructions_audit(tmp_path, data)
    assert audit["summary"]["files_found"] == 2
    assert audit["summary"]["dead_paths_count"] == 1
    assert audit["summary"]["duplications_count"] >= 1
    assert audit["summary"]["contradictions_count"] == 1

    # 4. Universal SARIF 2.1.0 Ingestor
    sarif = generate_sarif_findings(tmp_path, data)
    assert sarif["available"] is True
    assert sarif["summary"]["total"] == 1
    assert sarif["summary"]["by_tool"]["semgrep"] == 1

    # 5. Quality Telemetry Wave 1.5 parsers (ESLint, Knip, Vulture, Deptry)
    qt = analyze_quality_telemetry(tmp_path, data)
    assert qt["eslint"]["available"] is True and qt["eslint"]["errors"] == 1
    assert qt["knip"]["available"] is True and qt["knip"]["unused_files"] == 1
    assert qt["vulture"]["available"] is True and qt["vulture"]["total"] == 1
    assert qt["deptry"]["available"] is True and qt["deptry"]["total"] == 1


def test_mcp_wave1_tools(tmp_path: Path) -> None:
    data = _seed_sample_repo(tmp_path)
    generate_test_oracle(tmp_path, data)
    generate_module_cards(tmp_path, data)
    generate_agent_instructions_audit(tmp_path, data)
    generate_sarif_findings(tmp_path, data)

    eng = PortalMcpEngine(tmp_path, data)

    # 1. portal_slice_for_task (excludes Superseded ADRs, stays <= max_tokens)
    sl_resp = handle_jsonrpc_request(eng, {
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "portal_slice_for_task", "arguments": {"task": "orders api ledger", "max_tokens": 1200}},
    })
    assert sl_resp is not None and not sl_resp["result"]["isError"]
    sl_data = json.loads(sl_resp["result"]["content"][0]["text"])
    assert sl_data["budget_used_tokens"] <= 1200
    assert any(m["path"] == "backend/app/api/orders.py" for m in sl_data["selected_modules"])
    adr_ids = [a["id"] for a in sl_data["active_adrs"]]
    assert "ADR-002" in adr_ids and "ADR-001" not in adr_ids

    # 2. portal_check_diff (detects phantom import + sync I/O in async + frozen block)
    diff_resp = handle_jsonrpc_request(eng, {
        "jsonrpc": "2.0", "id": 2, "method": "tools/call",
        "params": {"name": "portal_check_diff", "arguments": {"files": ["backend/app/api/orders.py"]}},
    })
    assert diff_resp is not None
    diff_data = json.loads(diff_resp["result"]["content"][0]["text"])
    rules = {a["rule"] for a in diff_data["slop_and_cheat_alerts"]}
    assert "PHANTOM_IMPORT" in rules
    assert "SYNC_IO_IN_ASYNC" in rules
    assert diff_data["status"] in ("WARN", "BLOCK")
    assert diff_data["change_risk_score"] > 0

    frozen_resp = handle_jsonrpc_request(eng, {
        "jsonrpc": "2.0", "id": 3, "method": "tools/call",
        "params": {"name": "portal_check_diff", "arguments": {"files": ["frozen/core.py"]}},
    })
    assert json.loads(frozen_resp["result"]["content"][0]["text"])["status"] == "BLOCK"

    # 3. portal_test_oracle
    to_resp = handle_jsonrpc_request(eng, {
        "jsonrpc": "2.0", "id": 4, "method": "tools/call",
        "params": {"name": "portal_test_oracle", "arguments": {"files": ["backend/app/api/orders.py"], "include_slow": False}},
    })
    to_data = json.loads(to_resp["result"]["content"][0]["text"])
    assert to_data["matched_count"] == 1
    assert "pytest -q backend/tests/test_orders.py" in to_data["command"]

    # 4. portal_handoff_pack
    ho_resp = handle_jsonrpc_request(eng, {
        "jsonrpc": "2.0", "id": 5, "method": "tools/call",
        "params": {"name": "portal_handoff_pack", "arguments": {"task": "orders refactor", "files": ["backend/app/api/orders.py"]}},
    })
    ho_data = json.loads(ho_resp["result"]["content"][0]["text"])
    assert ho_data["estimated_tokens"] <= 1500
    assert "backend/app/api/orders.py" in ho_data["files_touched"]

    # 5. portal_sarif_findings & portal_agent_instructions_audit
    sf_resp = handle_jsonrpc_request(eng, {
        "jsonrpc": "2.0", "id": 6, "method": "tools/call",
        "params": {"name": "portal_sarif_findings", "arguments": {"tool": "semgrep"}},
    })
    sf_data = json.loads(sf_resp["result"]["content"][0]["text"])
    assert sf_data["summary"]["by_tool"]["semgrep"] == 1

    ai_resp = handle_jsonrpc_request(eng, {
        "jsonrpc": "2.0", "id": 7, "method": "tools/call",
        "params": {"name": "portal_agent_instructions_audit", "arguments": {}},
    })
    ai_data = json.loads(ai_resp["result"]["content"][0]["text"])
    assert ai_data["summary"]["dead_paths_count"] == 1
