import json
import tempfile
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from knowledge_portal.indexer.fts_engine import FtsSearchEngine
from knowledge_portal.mcp_server import PortalMcpEngine, handle_jsonrpc_request
from knowledge_portal.server import PortalRequestHandler


class TestFtsAndNeighbors(unittest.TestCase):
    def test_fts_engine_bm25_prefix_entities_and_graph_nodes(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp) / "data"
            data.mkdir()
            (data / "omni-search-index.json").write_text(
                json.dumps({
                    "total": 2,
                    "entities": [
                        {
                            "id": "e1",
                            "title": "RiskCircuitBreaker",
                            "subtitle": "risk/breaker.py",
                            "category": "code",
                            "tab": "graph",
                            "path": "risk/breaker.py",
                            "search_text": "Emergency drawdown kill switch breaker",
                        },
                        {
                            "id": "e2",
                            "title": "MetricsExporter",
                            "subtitle": "obs/metrics.py",
                            "category": "code",
                            "tab": "graph",
                            "path": "obs/metrics.py",
                            "search_text": "Prometheus exporter",
                        },
                    ],
                }),
                encoding="utf-8",
            )
            (data / "graph.json").write_text(
                json.dumps({
                    "nodes": [
                        {"id": "n_api", "label": "OrderGateway", "type": "api", "path": "api/orders.py"},
                        {"id": "n_svc", "label": "OrderService", "type": "service", "path": "svc/orders.py"},
                        {"id": "n_db", "label": "orders_table", "type": "table", "path": "sql/orders.sql"},
                    ],
                    "edges": [
                        {"source": "n_api", "target": "n_svc", "relation": "calls"},
                        {"source": "n_svc", "target": "n_db", "relation": "writes"},
                    ],
                }),
                encoding="utf-8",
            )

            fts = FtsSearchEngine(data)
            res = fts.search("drawdown")
            self.assertEqual(len(res), 1)
            self.assertEqual(res[0]["name"], "RiskCircuitBreaker")

            res_prefix = fts.search("OrderGate")
            self.assertTrue(any(r["name"] == "OrderGateway" for r in res_prefix))

            # MCP portal_graph_neighbors 1-hop & 2-hop
            mcp = PortalMcpEngine(project_dir=Path(tmp), data_dir=data)
            nb1 = handle_jsonrpc_request(
                mcp,
                {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "portal_graph_neighbors", "arguments": {"node_id": "OrderGateway", "depth": 1}}},
            )
            txt1 = nb1["result"]["content"][0]["text"]
            self.assertIn("OrderService", txt1)
            self.assertNotIn("orders_table", txt1)

            nb2 = handle_jsonrpc_request(
                mcp,
                {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "portal_graph_neighbors", "arguments": {"node_id": "OrderGateway", "depth": 2}}},
            )
            self.assertIn("orders_table", nb2["result"]["content"][0]["text"])

    def test_http_api_search_route(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tpl = root / "template"
            (tpl / "data").mkdir(parents=True)
            (tpl / "dashboard.html").write_text("<html>ok</html>", encoding="utf-8")
            (tpl / "data" / "omni-search-index.json").write_text(
                json.dumps({"entities": [{"id": "a1", "title": "TelemetryProbe", "subtitle": "server.py", "search_text": "cpu ram disk"}]}),
                encoding="utf-8",
            )
            PortalRequestHandler.template_dir = tpl
            PortalRequestHandler.project_dir = root
            server = ThreadingHTTPServer(("127.0.0.1", 0), PortalRequestHandler)
            port = server.server_address[1]
            t = threading.Thread(target=server.serve_forever, daemon=True)
            t.start()
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/search?q=Telemetry", timeout=3) as r:
                    hits = json.loads(r.read().decode("utf-8"))
                    self.assertTrue(any(h["name"] == "TelemetryProbe" for h in hits))
            finally:
                server.shutdown()
                server.server_close()


if __name__ == "__main__":
    unittest.main()
