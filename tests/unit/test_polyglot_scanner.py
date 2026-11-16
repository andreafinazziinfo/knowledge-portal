"""
Unit tests for Polyglot Architecture AST Scanner
Tests Python, TypeScript, Vue 3, Go, Rust, C/C++, Java/Kotlin, C#, and SQL parsing.
"""

import unittest
from pathlib import Path
import tempfile
from knowledge_portal.scanner.polyglot import PolyglotScanner

class TestPolyglotScanner(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_parse_python(self):
        py_file = self.root / "service.py"
        py_file.write_text("""
class DataService:
    def fetch_records(self, query: str):
        return []

    async def stream_ticks(self):
        yield 1
""", encoding="utf-8")

        scanner = PolyglotScanner(self.root)
        nodes, edges = scanner.scan()

        labels = [n["label"] for n in nodes]
        self.assertIn("DataService", labels)
        self.assertIn("fetch_records()", labels)
        self.assertIn("stream_ticks()", labels)

    def test_parse_typescript_and_pinia(self):
        ts_file = self.root / "userStore.ts"
        ts_file.write_text("""
import { ref } from 'vue';

export interface UserProfile {
    id: string;
}

export const useUserStore = defineStore('user', () => {
    return {};
});

export async function loginUser(creds: any) {
    return true;
}
""", encoding="utf-8")

        scanner = PolyglotScanner(self.root)
        nodes, edges = scanner.scan()

        labels = [n["label"] for n in nodes]
        self.assertIn("UserProfile", labels)
        self.assertIn("🏪 useUserStore", labels)
        self.assertIn("loginUser()", labels)

    def test_parse_vue_component(self):
        vue_file = self.root / "DashboardView.vue"
        vue_file.write_text("""
<template><div>Title</div></template>
<script setup lang="ts">
export interface WidgetConfig { w: number; }
export function refreshWidgets() {}
</script>
""", encoding="utf-8")

        scanner = PolyglotScanner(self.root)
        nodes, edges = scanner.scan()

        labels = [n["label"] for n in nodes]
        self.assertIn("📦 <DashboardView/>", labels)
        self.assertIn("WidgetConfig", labels)
        self.assertIn("refreshWidgets()", labels)

    def test_parse_go(self):
        go_file = self.root / "server.go"
        go_file.write_text("""
package main
type ServerConfig struct { Port int }
type Router interface { Handle(p string) }
func Start() error { return nil }
""", encoding="utf-8")

        scanner = PolyglotScanner(self.root)
        nodes, edges = scanner.scan()

        labels = [n["label"] for n in nodes]
        self.assertIn("ServerConfig", labels)
        self.assertIn("Router", labels)
        self.assertIn("Start()", labels)

    def test_parse_rust(self):
        rs_file = self.root / "engine.rs"
        rs_file.write_text("""
pub struct Engine;
pub enum State { Running }
pub trait Runnable {}
pub fn execute() {}
""", encoding="utf-8")

        scanner = PolyglotScanner(self.root)
        nodes, edges = scanner.scan()

        labels = [n["label"] for n in nodes]
        self.assertIn("Engine", labels)
        self.assertIn("State", labels)
        self.assertIn("Runnable", labels)
        self.assertIn("execute()", labels)

    def test_parse_cpp(self):
        cpp_file = self.root / "matching_engine.cpp"
        cpp_file.write_text("""
class OrderBook {
public:
    void matchOrders() {}
};
struct Trade { double price; };
""", encoding="utf-8")

        scanner = PolyglotScanner(self.root)
        nodes, edges = scanner.scan()

        labels = [n["label"] for n in nodes]
        self.assertIn("OrderBook", labels)
        self.assertIn("Trade", labels)
        self.assertIn("matchOrders()", labels)

    def test_parse_java_and_kotlin(self):
        java_file = self.root / "UserController.java"
        java_file.write_text("""
public class UserController {
    public Response getUser() { return null; }
}
public interface UserRepository {}
""", encoding="utf-8")

        scanner = PolyglotScanner(self.root)
        nodes, edges = scanner.scan()

        labels = [n["label"] for n in nodes]
        self.assertIn("UserController", labels)
        self.assertIn("UserRepository", labels)
        self.assertIn("getUser()", labels)

    def test_parse_csharp(self):
        cs_file = self.root / "OrderService.cs"
        cs_file.write_text("""
public class OrderService {
    public async Task ProcessOrder() {}
}
public record OrderDto(int Id);
""", encoding="utf-8")

        scanner = PolyglotScanner(self.root)
        nodes, edges = scanner.scan()

        labels = [n["label"] for n in nodes]
        self.assertIn("OrderService", labels)
        self.assertIn("OrderDto", labels)
        self.assertIn("ProcessOrder()", labels)

    def test_parse_sql(self):
        sql_file = self.root / "schema.sql"
        sql_file.write_text("""
CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100)
);

CREATE TABLE orders (
    id SERIAL PRIMARY KEY,
    user_id INT,
    FOREIGN KEY (user_id) REFERENCES users(id)
);
""", encoding="utf-8")

        scanner = PolyglotScanner(self.root)
        nodes, edges = scanner.scan()

        labels = [n["label"] for n in nodes]
        self.assertIn("🗄️ users", labels)
        self.assertIn("🗄️ orders", labels)
        self.assertTrue(any(e["type"] == "foreign_key" for e in edges))

    def test_resilience(self):
        broken = self.root / "broken.py"
        broken.write_text("def error: syntax", encoding="utf-8")
        scanner = PolyglotScanner(self.root)
        nodes, edges = scanner.scan()
        self.assertIsInstance(nodes, list)

if __name__ == "__main__":
    unittest.main()
