import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from knowledge_portal.server import PortalRequestHandler

REPO_ROOT = Path(__file__).resolve().parents[2]


class TestCliAndRoutes(unittest.TestCase):
    def test_api_token_guard_stats_tree_sse_and_wasm(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tpl = root / "template"
            (tpl / "data").mkdir(parents=True)
            (tpl / "assets").mkdir(parents=True)
            (tpl / "dashboard.html").write_text("<html>ok</html>", encoding="utf-8")
            (tpl / "assets" / "mod.wasm").write_bytes(b"\x00asm\x01\x00\x00\x00")
            (tpl / "data" / "graph.json").write_text(
                json.dumps({"nodes": [{"id": "a", "path": "src/a.py", "community": 0}], "edges": []}),
                encoding="utf-8",
            )
            (root / "docs").mkdir()
            (root / "docs" / "guide.md").write_text("# Guide", encoding="utf-8")

            PortalRequestHandler.template_dir = tpl
            PortalRequestHandler.project_dir = root

            prev_ro = os.environ.get("PORTAL_READ_ONLY")
            prev_tok = os.environ.get("PORTAL_API_TOKEN")
            prev_log = os.environ.get("PORTAL_ACCESS_LOG")
            os.environ["PORTAL_READ_ONLY"] = "0"
            os.environ["PORTAL_API_TOKEN"] = "test-secret-token"
            os.environ["PORTAL_ACCESS_LOG"] = "0"

            server = ThreadingHTTPServer(("127.0.0.1", 0), PortalRequestHandler)
            port = server.server_address[1]
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                # 1. /api/stats
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/stats", timeout=3) as r:
                    stats = json.loads(r.read().decode("utf-8"))
                    self.assertEqual(stats["total_nodes"], 1)
                    self.assertEqual(stats["communities"], 1)

                # 2. /api/tree
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/tree", timeout=3) as r:
                    tree = json.loads(r.read().decode("utf-8"))
                    self.assertTrue(any(d["name"] == "docs" for d in tree))

                # 3. /api/rebuild/status
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/rebuild/status", timeout=3) as r:
                    rb = json.loads(r.read().decode("utf-8"))
                    self.assertFalse(rb["rebuilding"])

                # 4. .wasm MIME
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/assets/mod.wasm", timeout=3) as r:
                    self.assertEqual(r.headers.get("Content-Type"), "application/wasm")

                # 5. /api/live-events SSE initial frame
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/live-events", timeout=3) as r:
                    self.assertEqual(r.headers.get("Content-Type"), "text/event-stream")
                    first_line = r.readline().decode("utf-8")
                    self.assertIn("connected", first_line)

                # 6. POST without token -> 401; with valid token -> 404 (auth passed)
                req_no_tok = urllib.request.Request(f"http://127.0.0.1:{port}/api/file", data=b"{}", method="POST")
                with self.assertRaises(urllib.error.HTTPError) as ctx_401:
                    urllib.request.urlopen(req_no_tok, timeout=3)
                self.assertEqual(ctx_401.exception.code, 401)

                req_ok_tok = urllib.request.Request(
                    f"http://127.0.0.1:{port}/api/file",
                    data=b"{}",
                    method="POST",
                    headers={"X-Portal-Token": "test-secret-token"},
                )
                with self.assertRaises(urllib.error.HTTPError) as ctx_404:
                    urllib.request.urlopen(req_ok_tok, timeout=3)
                self.assertEqual(ctx_404.exception.code, 404)
            finally:
                server.shutdown()
                server.server_close()
                for k, v in [("PORTAL_READ_ONLY", prev_ro), ("PORTAL_API_TOKEN", prev_tok), ("PORTAL_ACCESS_LOG", prev_log)]:
                    if v is None:
                        os.environ.pop(k, None)
                    else:
                        os.environ[k] = v

    def test_cli_scan_and_export_on_sample_project(self):
        sample = REPO_ROOT / "sample_project"
        if not sample.exists():
            self.skipTest("sample_project not present")
        with tempfile.TemporaryDirectory() as tmp:
            out_scan = Path(tmp) / "scan-out"
            res = subprocess.run(
                [sys.executable, "-m", "knowledge_portal.cli", "scan", str(sample), "--output", str(out_scan)],
                cwd=str(REPO_ROOT),
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(res.returncode, 0, res.stderr)
            self.assertTrue((out_scan / "graph.json").exists())


if __name__ == "__main__":
    unittest.main()
