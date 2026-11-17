"""
Unit Tests for Declarative Floorplan Generator
"""

import tempfile
import unittest
from pathlib import Path
from knowledge_portal.generators.floorplan import (
    parse_yaml_zero_dep,
    generate_floorplan_from_yaml,
)

class TestFloorplanGenerator(unittest.TestCase):
    def test_parse_yaml_zero_dep(self):
        sample_yaml = """
        title: "Test Architecture"
        description: "Sample test system"
        layers:
          - id: "frontend"
            name: "Layer 1: Frontend"
            color: "#38bdf8"
            services:
              - id: "web-ui"
                name: "React Web"
                desc: "Customer UI"
                status: "active"
          - id: "backend"
            name: "Layer 2: Backend"
            color: "#10b981"
            services:
              - id: "api-srv"
                name: "FastAPI"
                desc: "REST API"
                status: "dev"
        connections:
          - from: "frontend"
            to: "backend"
        """
        res = parse_yaml_zero_dep(sample_yaml)
        self.assertEqual(res.get("title"), "Test Architecture")
        self.assertEqual(len(res.get("layers", [])), 2)
        self.assertEqual(res["layers"][0]["id"], "frontend")
        self.assertEqual(len(res["layers"][0]["services"]), 1)
        self.assertEqual(res["layers"][0]["services"][0]["id"], "web-ui")
        self.assertEqual(res["layers"][0]["services"][0].get("status"), "active")
        self.assertEqual(res["layers"][1]["services"][0].get("status"), "dev")
        self.assertEqual(len(res.get("connections", [])), 1)
        self.assertEqual(res["connections"][0]["from"], "frontend")
        self.assertEqual(res["connections"][0]["to"], "backend")

    def test_generate_floorplan_from_yaml_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            yaml_file = tmp_path / "architecture.yaml"
            yaml_file.write_text("""
            title: "Enterprise Core"
            layers:
              - id: "gateway"
                name: "API Gateway"
                color: "#0284c7"
                services:
                  - id: "kong"
                    name: "Kong Proxy"
                    desc: "Routing"
                    status: "active"
              - id: "data"
                name: "Database"
                color: "#10b981"
                services:
                  - id: "postgres"
                    name: "PostgreSQL"
                    desc: "Storage"
                    status: "frozen"
            connections:
              - from: "gateway"
                to: "data"
            """, encoding="utf-8")

            out_html = tmp_path / "floorplan.html"
            result_path = generate_floorplan_from_yaml(yaml_file, out_html)

            self.assertTrue(result_path.exists())
            content = result_path.read_text(encoding="utf-8")
            self.assertIn("Enterprise Core", content)
            self.assertIn('id="layer-gateway"', content)
            self.assertIn('id="svc-kong"', content)
            self.assertIn('id="svc-postgres"', content)
            self.assertIn('data-status="active"', content)
            self.assertIn('data-status="frozen"', content)
            self.assertIn('id="fp-search"', content)
            self.assertIn('class="layer-pill', content)
            self.assertIn("status-badge", content)
            self.assertIn("<svg", content)
            self.assertIn("</svg>", content)

    def test_generate_floorplan_fallback_on_empty_or_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            missing_file = tmp_path / "non_existent.yaml"
            out_html = tmp_path / "floorplan_fallback.html"

            result_path = generate_floorplan_from_yaml(missing_file, out_html)
            self.assertTrue(result_path.exists())
            content = result_path.read_text(encoding="utf-8")
            self.assertIn("System Architecture Overview", content)
            self.assertIn("<svg", content)

if __name__ == "__main__":
    unittest.main()
