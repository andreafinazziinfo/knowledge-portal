import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from knowledge_portal.server import PortalRequestHandler, safe_resolve_under


class TestServerSecurity(unittest.TestCase):
    def test_safe_resolve_blocks_traversal_and_sensitive_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "docs").mkdir()
            good = root / "docs" / "readme.md"
            good.write_text("# ok", encoding="utf-8")
            (root / ".env").write_text("SECRET=1", encoding="utf-8")
            (root / ".git").mkdir()
            (root / ".git" / "config").write_text("x", encoding="utf-8")
            (root / "frozen").mkdir()
            (root / "frozen" / "core.py").write_text("x", encoding="utf-8")

            self.assertEqual(safe_resolve_under(root, "docs/readme.md"), good.resolve())
            self.assertIsNone(safe_resolve_under(root, "../etc/passwd"))
            self.assertIsNone(safe_resolve_under(root, ".env"))
            self.assertIsNone(safe_resolve_under(root, ".env.local"))
            self.assertIsNone(safe_resolve_under(root, ".git/config"))
            self.assertIsNone(safe_resolve_under(root, "frozen/core.py"))
            self.assertIsNone(safe_resolve_under(root, "cert.key"))
            self.assertIsNone(safe_resolve_under(root, "docs/a\x00b.md"))

    def test_http_smoke_headers_telemetry_and_read_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tpl = root / "template"
            tpl.mkdir()
            (tpl / "dashboard.html").write_text("<html>ok</html>", encoding="utf-8")
            (root / ".env").write_text("SECRET=1", encoding="utf-8")

            PortalRequestHandler.template_dir = tpl
            PortalRequestHandler.project_dir = root

            prev_ro = os.environ.get("PORTAL_READ_ONLY")
            prev_log = os.environ.get("PORTAL_ACCESS_LOG")
            os.environ["PORTAL_READ_ONLY"] = "1"
            os.environ["PORTAL_ACCESS_LOG"] = "0"

            server = ThreadingHTTPServer(("127.0.0.1", 0), PortalRequestHandler)
            port = server.server_address[1]
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/dashboard.html", timeout=3) as r:
                    self.assertEqual(r.status, 200)
                    self.assertEqual(r.headers.get("X-Content-Type-Options"), "nosniff")
                    self.assertEqual(r.headers.get("X-Frame-Options"), "SAMEORIGIN")
                    self.assertEqual(r.headers.get("Referrer-Policy"), "no-referrer")

                with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/telemetry", timeout=3) as r:
                    self.assertEqual(r.status, 200)
                    payload = json.loads(r.read().decode("utf-8"))
                    self.assertEqual(payload["mode"], "standalone")

                with self.assertRaises(urllib.error.HTTPError) as ctx:
                    urllib.request.urlopen(f"http://127.0.0.1:{port}/api/file?path=../.env", timeout=3)
                self.assertEqual(ctx.exception.code, 404)

                req = urllib.request.Request(
                    f"http://127.0.0.1:{port}/api/file",
                    data=b"{}",
                    method="POST",
                )
                with self.assertRaises(urllib.error.HTTPError) as ctx_post:
                    urllib.request.urlopen(req, timeout=3)
                self.assertEqual(ctx_post.exception.code, 403)
            finally:
                server.shutdown()
                server.server_close()
                if prev_ro is None:
                    os.environ.pop("PORTAL_READ_ONLY", None)
                else:
                    os.environ["PORTAL_READ_ONLY"] = prev_ro
                if prev_log is None:
                    os.environ.pop("PORTAL_ACCESS_LOG", None)
                else:
                    os.environ["PORTAL_ACCESS_LOG"] = prev_log


if __name__ == "__main__":
    unittest.main()
