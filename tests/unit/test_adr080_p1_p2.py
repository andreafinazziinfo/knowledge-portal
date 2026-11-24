"""Unit tests for ADR-080 Sprint 2 (Fase P1 + Fase P2) + Tab 10 + MCP v2 + SARIF."""

from __future__ import annotations

import json
from pathlib import Path

from knowledge_portal.generators.arch_health import generate_arch_health
from knowledge_portal.generators.audit_analyzers import analyze_semantic_clones
from knowledge_portal.generators.audit_report import render_markdown_report, render_sarif_report
from knowledge_portal.generators.call_graph import generate_call_graph
from knowledge_portal.generators.frontend_hygiene import analyze_frontend_hygiene
from knowledge_portal.generators.migration_sre import analyze_migration_and_sre
from knowledge_portal.generators.quality_telemetry import analyze_quality_telemetry
from knowledge_portal.mcp_server import PortalMcpEngine, handle_jsonrpc_request


# ── P1.1: Import-Aware Call Graph & Symbol-Level Dead Code ───────────────────
def test_p1_1_python_import_aware_and_dead_code(tmp_path: Path) -> None:
    proj = tmp_path / "repo"
    data = tmp_path / "data"
    (proj / "app").mkdir(parents=True)

    (proj / "app" / "helpers.py").write_text(
        """
__all__ = ["exported_util"]

def used_helper(x: int) -> int:
    return x + 1

def unused_orphan(x: int) -> int:
    return x * 2

def exported_util() -> str:
    return "ok"

def main() -> None:
    pass
""",
        encoding="utf-8",
    )
    (proj / "app" / "routes.py").write_text(
        """
from app.helpers import used_helper

class Router:
    def get(self, path):
        def dec(fn):
            return fn
        return dec

router = Router()

@router.get("/items")
def list_items():
    return used_helper(1)
""",
        encoding="utf-8",
    )

    res = generate_call_graph(proj, data)
    assert (data / "dead-code.json").exists()
    dc = res["dead_code"]
    dead_names = {s["symbol"] for s in dc["python_dead_symbols"]}
    assert "unused_orphan" in dead_names
    # Exclusions must hold
    assert "used_helper" not in dead_names
    assert "exported_util" not in dead_names
    assert "list_items" not in dead_names
    assert "main" not in dead_names


def test_p1_1_js_ts_vue_unused_exports_and_components(tmp_path: Path) -> None:
    proj = tmp_path / "repo"
    data = tmp_path / "data"
    (proj / "frontend" / "src" / "utils").mkdir(parents=True)
    (proj / "frontend" / "src" / "components").mkdir(parents=True)
    (proj / "frontend" / "src" / "views").mkdir(parents=True)

    (proj / "frontend" / "src" / "utils" / "math.ts").write_text(
        "export function usedFn(a: number) { return a; }\nexport const deadExport = 42;\n",
        encoding="utf-8",
    )
    (proj / "frontend" / "src" / "components" / "UsedCard.vue").write_text(
        "<template><div>ok</div></template>\n",
        encoding="utf-8",
    )
    (proj / "frontend" / "src" / "components" / "OrphanWidget.vue").write_text(
        "<template><div>orphan</div></template>\n",
        encoding="utf-8",
    )
    (proj / "frontend" / "src" / "views" / "HomeView.vue").write_text(
        "<script setup lang='ts'>\nimport { usedFn } from '../utils/math'\nimport UsedCard from '../components/UsedCard.vue'\n</script>\n<template><UsedCard /></template>\n",
        encoding="utf-8",
    )

    res = generate_call_graph(proj, data)
    dc = res["dead_code"]
    dead_js = {x["symbol"] for x in dc["js_unused_exports"]}
    dead_vue = {x["symbol"] for x in dc["vue_unused_components"]}
    assert "deadExport" in dead_js
    assert "usedFn" not in dead_js
    assert "OrphanWidget" in dead_vue
    assert "UsedCard" not in dead_vue


# ── P1.2: Unified Quality Telemetry ──────────────────────────────────────────
def test_p1_2_quality_telemetry_ingestion(tmp_path: Path) -> None:
    proj = tmp_path / "repo"
    data = tmp_path / "data"
    (proj / "backend").mkdir(parents=True)
    (proj / "frontend" / "coverage").mkdir(parents=True)
    (proj / "reports").mkdir(parents=True)

    # coverage.xml
    (proj / "backend" / "coverage.xml").write_text(
        """<?xml version="1.0" ?>
<coverage><packages><package name="app"><classes>
  <class filename="app/services/orders.py" line-rate="0.80"/>
  <class filename="app/services/billing.py" line-rate="0.60"/>
</classes></package></packages></coverage>
""",
        encoding="utf-8",
    )
    # lcov.info
    (proj / "frontend" / "coverage" / "lcov.info").write_text(
        "SF:src/stores/auth.ts\nLF:20\nLH:15\nend_of_record\n",
        encoding="utf-8",
    )
    # JUnit XML
    (proj / "reports" / "junit-backend.xml").write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<testsuite tests="3" failures="1" errors="0" skipped="1">
  <testcase classname="tests.test_a" name="test_fast" time="0.05"/>
  <testcase classname="tests.test_b" name="test_slow" time="2.40"><failure message="boom">trace</failure></testcase>
  <testcase classname="tests.test_c" name="test_skip" time="0.00"><skipped/></testcase>
</testsuite>
""",
        encoding="utf-8",
    )
    # Ruff JSON
    (proj / "reports" / "ruff-report.json").write_text(
        json.dumps([{"code": "F401", "filename": "backend/app/foo.py", "location": {"row": 3}, "message": "unused import"}]),
        encoding="utf-8",
    )
    # Mypy text
    (proj / "reports" / "mypy.txt").write_text(
        "backend/app/services/orders.py:12: error: Incompatible types [assignment]\n",
        encoding="utf-8",
    )
    # TSC output
    (proj / "reports" / "tsc-report.txt").write_text(
        "frontend/src/views/Home.vue(14,5): error TS2322: Type 'string' is not assignable to type 'number'.\n",
        encoding="utf-8",
    )

    qt = analyze_quality_telemetry(proj, data_dir=data)
    assert (data / "quality-telemetry.json").exists()
    assert qt["available"] is True
    assert qt["coverage"]["available"] is True
    assert len(qt["coverage"]["by_domain"]) >= 2
    assert qt["junit"]["tests_total"] == 3
    assert qt["junit"]["failures"] == 1
    assert qt["junit"]["skipped"] == 1
    assert qt["junit"]["slowest_tests"][0]["name"] == "test_slow"
    assert qt["ruff"]["total"] == 1
    assert qt["typecheck"]["mypy"]["total"] == 1
    assert qt["typecheck"]["tsc"]["total"] == 1


def test_p1_2_quality_telemetry_zero_crash_when_absent(tmp_path: Path) -> None:
    proj = tmp_path / "empty"
    proj.mkdir()
    qt = analyze_quality_telemetry(proj)
    assert qt["available"] is False
    assert qt["summary"]["sources_count"] == 0


# ── P1.3: DB Migration Safety & SRE Resilience ───────────────────────────────
def test_p1_3_migration_safety_and_sre_resilience(tmp_path: Path) -> None:
    proj = tmp_path / "repo"
    (proj / "migration").mkdir(parents=True)
    (proj / "backend" / "app").mkdir(parents=True)

    (proj / "migration" / "01_risky.sql").write_text(
        """
DROP TABLE legacy_orders;
CREATE INDEX idx_orders_user ON orders(user_id);
ALTER TABLE orders ADD COLUMN tenant_id TEXT NOT NULL;
""",
        encoding="utf-8",
    )
    (proj / "migration" / "02_safe.sql").write_text(
        """
SET lock_timeout = '5s';
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_orders_ts ON orders(created_at);
ALTER TABLE orders ADD COLUMN note TEXT NOT NULL DEFAULT '';
-- migration-safe
DROP TABLE temp_staging;
""",
        encoding="utf-8",
    )
    (proj / "backend" / "app" / "client.py").write_text(
        """
import logging
import httpx

logger = logging.getLogger(__name__)

def fetch_data(uid: str):
    logger.info(f"Fetching user {uid}")
    return httpx.get("https://example.invalid")
""",
        encoding="utf-8",
    )

    res = analyze_migration_and_sre(proj)
    mig = res["migration_safety"]
    rules = {f["rule"] for f in mig["findings"]}
    assert "SQL_DESTRUCTIVE_DDL" in rules
    assert "SQL_INDEX_WITHOUT_CONCURRENTLY" in rules
    assert "SQL_NOT_NULL_NO_DEFAULT" in rules
    assert "SQL_LOCK_TIMEOUT_MISSING" in rules
    # 02_safe.sql should produce 0 findings
    assert all(f["path"] != "migration/02_safe.sql" for f in mig["findings"])

    sre = res["sre_resilience"]
    assert sre["has_graceful_shutdown"] is False
    assert sre["fstring_logging_count"] == 1
    assert sre["http_llm_client_files_count"] == 1
    assert sre["http_llm_retry_coverage_pct"] == 0.0
    gap_rules = {g["rule"] for g in sre["gaps"]}
    assert "SRE_MISSING_GRACEFUL_SHUTDOWN" in gap_rules
    assert "SRE_MISSING_RETRY_BACKOFF" in gap_rules


# ── P2.1: Frontend Architecture, Bundle & a11y Hygiene ───────────────────────
def test_p2_1_frontend_hygiene_and_a11y(tmp_path: Path) -> None:
    proj = tmp_path / "repo"
    (proj / "frontend" / "src" / "router").mkdir(parents=True)
    (proj / "frontend" / "src" / "stores").mkdir(parents=True)
    (proj / "frontend" / "src" / "components").mkdir(parents=True)
    (proj / "frontend" / "dist" / "assets").mkdir(parents=True)

    (proj / "frontend" / "src" / "router" / "index.ts").write_text(
        """
import HomeView from '../views/HomeView.vue'
export const routes = [
  { path: '/', component: HomeView },
  { path: '/about', component: () => import('../views/AboutView.vue') },
]
""",
        encoding="utf-8",
    )
    # God store (>360 LOC)
    store_lines = ["import { ref, computed } from 'vue'"] + [f"const s{i} = ref({i})" for i in range(25)] + ["// pad"] * 350
    (proj / "frontend" / "src" / "stores" / "mega.ts").write_text("\n".join(store_lines), encoding="utf-8")

    # a11y issues
    (proj / "frontend" / "src" / "components" / "BadA11y.vue").write_text(
        """<template>
  <img src="/logo.png" />
  <div @click="openModal">Click me</div>
  <input type="text" v-model="query" />
  <img src="/ok.png" alt="Logo" />
</template>
""",
        encoding="utf-8",
    )
    # Oversized bundle chunk (>500 KB)
    (proj / "frontend" / "dist" / "assets" / "vendor.js").write_bytes(b"a" * (520 * 1024))

    res = analyze_frontend_hygiene(proj)
    rules = {f["rule"] for f in res["findings"]}
    assert "FE_EAGER_ROUTE_IMPORT" in rules
    assert "FE_GOD_STORE" in rules
    assert "A11Y_IMG_MISSING_ALT" in rules
    assert "A11Y_CLICKABLE_DIV_NO_ROLE" in rules
    assert "A11Y_INPUT_MISSING_LABEL" in rules
    assert "FE_LARGE_BUNDLE_CHUNK" in rules
    assert res["summary"]["lazy_route_coverage_pct"] == 50.0
    assert res["bundle_stats"]["available"] is True


# ── P2.2: AST-Normalized Semantic Code Clones ────────────────────────────────
def test_p2_2_ast_semantic_clones(tmp_path: Path) -> None:
    proj = tmp_path / "repo"
    (proj / "pkg").mkdir(parents=True)

    (proj / "pkg" / "mod_a.py").write_text(
        """
def process_orders(items, tax_rate):
    \"\"\"Compute total for orders.\"\"\"
    total = 0.0
    count = 0
    for item in items:
        if item > 0:
            val = item * tax_rate
            total += val
            count += 1
    if count == 0:
        return 0.0
    return total / count
""",
        encoding="utf-8",
    )
    (proj / "pkg" / "mod_b.py").write_text(
        """
def compute_invoices(records, fee_pct):
    \"\"\"Different docstring and identifiers, identical AST.\"\"\"
    acc = 1.0
    seen = 1
    for rec in records:
        if rec > 10:
            chunk = rec * fee_pct
            acc += chunk
            seen += 2
    if seen == 99:
        return 9.9
    return acc / seen
""",
        encoding="utf-8",
    )

    res = analyze_semantic_clones(proj, min_statements=8)
    assert res["method"] == "python_ast_normalized_v1"
    assert res["clone_groups_count"] == 1
    assert res["duplicated_functions_count"] == 2
    names = {f["name"] for f in res["top_clones"][0]["functions"]}
    assert names == {"process_orders", "compute_invoices"}


# ── End-to-End Arch Health + MCP v2 + SARIF + Tab 10 ─────────────────────────
def test_p1_p2_arch_health_mcp_and_sarif_integration(tmp_path: Path) -> None:
    proj = tmp_path / "repo"
    data = tmp_path / "data"
    (proj / "migration").mkdir(parents=True)
    (proj / "migration" / "01_drop.sql").write_text("DROP TABLE old_tbl;\n", encoding="utf-8")
    (proj / "app.py").write_text("def orphan_fn():\n    return 1\n", encoding="utf-8")

    rep = generate_arch_health(data, project_dir=proj)
    hv4 = rep["health_v4"]
    assert "dead_code_symbols" in hv4
    assert "quality_telemetry" in hv4
    assert "migration_sre" in hv4
    assert "frontend_hygiene" in hv4
    assert "semantic_clones" in hv4

    md = render_markdown_report(rep, project_name="Demo")
    assert "Dead Code" in md
    assert "Migration Safety & SRE" in md
    assert "AST Semantic Clones" in md

    sarif = render_sarif_report(rep)
    rule_ids = {r["ruleId"] for r in sarif["runs"][0]["results"]}
    assert "KP-MIGSRE-SQL_DESTRUCTIVE_DDL" in rule_ids

    eng = PortalMcpEngine(proj, data)
    res_dc = handle_jsonrpc_request(eng, {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "portal_dead_code", "arguments": {}}})
    assert res_dc is not None and "python_dead_symbols" in res_dc["result"]["content"][0]["text"]
    res_da = handle_jsonrpc_request(eng, {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "portal_deep_audit", "arguments": {}}})
    assert res_da is not None and "migration_sre" in res_da["result"]["content"][0]["text"]
