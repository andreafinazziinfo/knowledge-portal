"""
Unit Tests for Database Lineage SQL Scanner & Manifest Generation
"""

import json
import tempfile
import unittest
from pathlib import Path
from knowledge_portal.scanner.polyglot import PolyglotScanner, scan_polyglot_codebase

class TestDbLineageScanner(unittest.TestCase):
    def test_parse_sql_tables_and_columns(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            sql_content = """
            -- User and authentication schema
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                username VARCHAR(100) NOT NULL,
                email VARCHAR(255) NOT NULL,
                created_at TIMESTAMPTZ DEFAULT NOW()
            );

            CREATE TABLE orders (
                order_id BIGINT,
                user_id INT NOT NULL,
                amount NUMERIC(10, 2),
                status VARCHAR(50),
                PRIMARY KEY (order_id),
                CONSTRAINT fk_orders_user FOREIGN KEY (user_id) REFERENCES users(id)
            );
            """
            sql_file = tmp_path / "schema.sql"
            sql_file.write_text(sql_content, encoding="utf-8")

            scanner = PolyglotScanner(tmp_path)
            nodes, edges = scanner.scan()

            self.assertIn("users", scanner.db_tables)
            self.assertIn("orders", scanner.db_tables)

            users_tbl = scanner.db_tables["users"]
            self.assertGreaterEqual(len(users_tbl["columns"]), 3)
            id_col = next(c for c in users_tbl["columns"] if c["name"] == "id")
            self.assertTrue(id_col["pk"])

            orders_tbl = scanner.db_tables["orders"]
            order_id_col = next(c for c in orders_tbl["columns"] if c["name"] == "order_id")
            self.assertTrue(order_id_col["pk"])
            self.assertEqual(len(orders_tbl["foreign_keys"]), 1)
            self.assertEqual(orders_tbl["foreign_keys"][0]["target_table"], "users")

    def test_scan_generates_db_schema_and_manifest(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir) / "project"
            root_dir.mkdir()
            out_dir = Path(tmpdir) / "output" / "data"
            out_dir.mkdir(parents=True)

            sql_file = root_dir / "models.sql"
            sql_file.write_text("""
            CREATE TABLE products (
                sku VARCHAR(50) PRIMARY KEY,
                title TEXT NOT NULL,
                price DECIMAL(8, 2)
            );
            """, encoding="utf-8")

            stats = scan_polyglot_codebase(root_dir, out_dir)

            self.assertEqual(stats["total_tables"], 1)
            self.assertTrue((out_dir / "db-schema.json").exists())
            self.assertTrue((out_dir / "db_schema.js").exists())
            self.assertTrue((out_dir / "views-manifest.json").exists())
            self.assertTrue((out_dir / "views_manifest.js").exists())

            with open(out_dir / "db-schema.json", "r", encoding="utf-8") as f:
                data = json.load(f)
                self.assertEqual(data["summary"]["total_tables"], 1)
                self.assertEqual(data["tables"][0]["name"], "products")

            with open(out_dir / "views-manifest.json", "r", encoding="utf-8") as f:
                manifest = json.load(f)
                self.assertIn("home", manifest["available_views"])
                self.assertIn("db-lineage", manifest["available_views"])

if __name__ == "__main__":
    unittest.main()
