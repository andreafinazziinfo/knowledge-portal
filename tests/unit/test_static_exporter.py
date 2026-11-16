"""
Unit Tests for Static Exporter & Bundling
"""

import tempfile
import unittest
from pathlib import Path
from knowledge_portal.exporter.static_export import export_static_portal

class TestStaticExporter(unittest.TestCase):
    def test_static_export_creates_complete_bundle(self):
        with tempfile.TemporaryDirectory() as src_tmp, tempfile.TemporaryDirectory() as out_tmp:
            src = Path(src_tmp)
            out = Path(out_tmp) / "dist"

            (src / "app.py").write_text("class CoreApp:\n    def run(self):\n        pass\n", encoding="utf-8")
            (src / "schema.sql").write_text("CREATE TABLE users (id INT PRIMARY KEY, name TEXT);\n", encoding="utf-8")
            (src / "architecture.yaml").write_text("""
            title: "Test System"
            layers:
              - id: "core"
                name: "Core"
                services:
                  - id: "app"
                    name: "App"
            """, encoding="utf-8")

            stats = export_static_portal(src, out, project_name="ExportTest")

            self.assertGreaterEqual(stats["total_files"], 1)
            self.assertTrue((out / "index.html").exists())
            self.assertTrue((out / "dashboard.html").exists())
            self.assertTrue((out / ".nojekyll").exists())
            self.assertTrue((out / "data" / "graph.json").exists())
            self.assertTrue((out / "data" / "db-schema.json").exists())
            self.assertTrue((out / "data" / "views-manifest.json").exists())
            self.assertTrue((out / "views" / "db-lineage.html").exists())
            self.assertTrue((out / "views" / "floorplan.html").exists())

            content = (out / "index.html").read_text(encoding="utf-8")
            self.assertIn("ExportTest", content)

if __name__ == "__main__":
    unittest.main()
