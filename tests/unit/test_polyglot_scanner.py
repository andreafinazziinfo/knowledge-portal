"""
Unit tests for Polyglot Architecture AST Scanner
Tests Python, TypeScript, Vue 3, Go, and Rust parsing without external dependencies.
"""

import unittest
from pathlib import Path
import tempfile
from knowledge_portal.scanner.polyglot import PolyglotScanner, scan_polyglot_codebase

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
    '''Core data retrieval service'''
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
import { apiService } from './api';

export interface UserProfile {
    id: string;
    username: string;
}

export const useUserStore = defineStore('user', () => {
    const user = ref<UserProfile | null>(null);
    return { user };
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
        self.assertTrue(any(e["type"] == "imports" for e in edges))

    def test_parse_vue_component(self):
        vue_file = self.root / "DashboardView.vue"
        vue_file.write_text("""
<template>
  <div class="dashboard"><h1>Title</h1></div>
</template>

<script setup lang="ts">
import { useUserStore } from './userStore';

export interface WidgetConfig {
  w: number;
  h: number;
}

export function refreshWidgets() {
  console.log('refreshed');
}
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

type ServerConfig struct {
    Port int
    Host string
}

type Router interface {
    Handle(path string)
}

func (s *ServerConfig) Start() error {
    return nil
}

func HelperInit() {
}
""", encoding="utf-8")

        scanner = PolyglotScanner(self.root)
        nodes, edges = scanner.scan()

        labels = [n["label"] for n in nodes]
        self.assertIn("ServerConfig", labels)
        self.assertIn("Router", labels)
        self.assertIn("Start()", labels)
        self.assertIn("HelperInit()", labels)

    def test_parse_rust(self):
        rs_file = self.root / "engine.rs"
        rs_file.write_text("""
pub struct ExecutionEngine {
    worker_id: u32,
}

pub enum State {
    Idle,
    Running,
}

pub trait Runnable {
    fn run(&self);
}

pub async fn execute_task(task_id: u64) -> bool {
    true
}
""", encoding="utf-8")

        scanner = PolyglotScanner(self.root)
        nodes, edges = scanner.scan()

        labels = [n["label"] for n in nodes]
        self.assertIn("ExecutionEngine", labels)
        self.assertIn("State", labels)
        self.assertIn("Runnable", labels)
        self.assertIn("execute_task()", labels)

    def test_resilience_to_malformed_files(self):
        broken_file = self.root / "broken.py"
        broken_file.write_text("def broken_syntax( { : not valid python", encoding="utf-8")

        scanner = PolyglotScanner(self.root)
        nodes, edges = scanner.scan()
        # Should not raise exception
        self.assertIsInstance(nodes, list)

if __name__ == "__main__":
    unittest.main()
