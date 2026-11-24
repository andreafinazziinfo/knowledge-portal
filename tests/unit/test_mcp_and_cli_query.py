import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from knowledge_portal.mcp_server import PortalMcpEngine, handle_jsonrpc_request

REPO_ROOT = Path(__file__).resolve().parents[2]


class TestMcpAndCliQuery(unittest.TestCase):
    def test_mcp_jsonrpc_protocol_and_all_tools(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data = root / "data"
            data.mkdir()
            (root / "docs").mkdir()
            (root / "docs" / "arch.md").write_text("# Architecture", encoding="utf-8")
            (root / ".env").write_text("SECRET=1", encoding="utf-8")
            (root / "frozen").mkdir()
            (root / "frozen" / "secret.py").write_text("x=1", encoding="utf-8")

            (data / "omni-search-index.json").write_text(
                json.dumps([{"name": "OrderRouter", "category": "api", "path": "src/orders.py", "tab": "api-catalog"}]),
                encoding="utf-8",
            )
            (data / "process-flows.json").write_text(
                json.dumps({"flows": [{"name": "CreateOrder", "route": "/api/orders", "tables": ["orders"]}]}),
                encoding="utf-8",
            )
            (data / "db-schema.json").write_text(
                json.dumps({"tables": [{"name": "orders", "columns": ["id", "total"]}]}),
                encoding="utf-8",
            )
            (data / "stack-ecosystem.json").write_text(
                json.dumps({"summary": {"total": 1}, "items": [{"name": "pytest", "ecosystem": "python"}]}),
                encoding="utf-8",
            )
            (data / "graph.json").write_text(json.dumps({"nodes": [{"id": "n1"}], "edges": []}), encoding="utf-8")

            engine = PortalMcpEngine(project_dir=root, data_dir=data, portal_url="http://127.0.0.1:1")

            init_resp = handle_jsonrpc_request(engine, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
            self.assertEqual(init_resp["result"]["serverInfo"]["name"], "knowledge-portal-mcp")

            list_resp = handle_jsonrpc_request(engine, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
            tool_names = [t["name"] for t in list_resp["result"]["tools"]]
            self.assertEqual(
                tool_names,
                ["portal_search", "portal_process_flow", "portal_db_schema", "portal_stack", "portal_telemetry", "portal_read_doc", "portal_graph_neighbors", "portal_context_pack", "portal_impact", "portal_health_audit", "portal_api_catalog", "portal_arch_diff", "portal_call_chain", "portal_mission_pack", "portal_validate_change", "portal_pr_context", "portal_config_matrix", "portal_iac_topology", "portal_ai_registry", "portal_compliance", "portal_cve_report", "portal_dead_code", "portal_deep_audit", "portal_git_dag", "portal_adr_graph", "portal_mission_control", "portal_discover", "portal_codemode", "portal_slice_for_task", "portal_check_diff", "portal_agent_instructions_audit", "portal_handoff_pack", "portal_test_oracle", "portal_sarif_findings"],
            )

            for tool, args, expected_key in [
                ("portal_search", {"query": "OrderRouter"}, "OrderRouter"),
                ("portal_process_flow", {"query": "CreateOrder"}, "CreateOrder"),
                ("portal_db_schema", {"table": "orders"}, "orders"),
                ("portal_stack", {"query": "pytest"}, "pytest"),
                ("portal_telemetry", {}, "static_snapshot"),
                ("portal_read_doc", {"path": "docs/arch.md"}, "# Architecture"),
            ]:
                resp = handle_jsonrpc_request(
                    engine,
                    {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": tool, "arguments": args}},
                )
                self.assertFalse(resp["result"]["isError"], tool)
                self.assertIn(expected_key, resp["result"]["content"][0]["text"])

            # Security: block .env, traversal, and frozen/
            for bad in [".env", "../etc/passwd", "frozen/secret.py"]:
                bad_resp = handle_jsonrpc_request(
                    engine,
                    {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "portal_read_doc", "arguments": {"path": bad}}},
                )
                self.assertTrue(bad_resp["result"]["isError"], bad)

    def test_cli_status_and_query_commands(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp) / "data"
            data.mkdir()
            (data / "db-schema.json").write_text(json.dumps({"tables": [{"name": "users"}]}), encoding="utf-8")
            (data / "graph.json").write_text(json.dumps({"nodes": [], "edges": []}), encoding="utf-8")

            r_status = subprocess.run(
                [sys.executable, "-m", "knowledge_portal.cli", "status", "--url", "http://127.0.0.1:1", "--data-dir", str(data), "--json"],
                cwd=str(REPO_ROOT),
                capture_output=True,
                text=True,
                timeout=15,
            )
            self.assertEqual(r_status.returncode, 0, r_status.stderr)
            self.assertIn("static_snapshot", r_status.stdout)

            r_query = subprocess.run(
                [sys.executable, "-m", "knowledge_portal.cli", "query", "users", "--type", "schema", "--data-dir", str(data)],
                cwd=str(REPO_ROOT),
                capture_output=True,
                text=True,
                timeout=15,
            )
            self.assertEqual(r_query.returncode, 0, r_query.stderr)
            self.assertIn("users", r_query.stdout)


if __name__ == "__main__":
    unittest.main()
