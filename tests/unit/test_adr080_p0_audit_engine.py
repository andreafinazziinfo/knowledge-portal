"""Unit tests for ADR-080 Sprint 1 (P0.1 Accuracy Patch, P0.2 Runtime Bugs v2, P0.3 CI/CD & CVE)."""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

from knowledge_portal.generators.audit_analyzers import analyze_db_health, analyze_health_v4
from knowledge_portal.generators.audit_report import render_markdown_report, render_sarif_report
from knowledge_portal.generators.compliance_evidence import generate_compliance_evidence
from knowledge_portal.generators.config_matrix import generate_config_matrix
from knowledge_portal.generators.cve_ingestor import generate_cve_report
from knowledge_portal.generators.iac_topology import generate_iac_topology
from knowledge_portal.mcp_server import PortalMcpEngine, handle_jsonrpc_request
from knowledge_portal.scanner.polyglot import scan_polyglot_codebase


def test_p01_polyglot_timescaledb_hypertables_caggs_and_alter(tmp_path: Path) -> None:
    mig = tmp_path / "migration"
    mig.mkdir()
    (mig / "01_base.sql").write_text(
        textwrap.dedent("""\
            CREATE TABLE market_bars (
                bar_time TIMESTAMPTZ NOT NULL,
                symbol TEXT NOT NULL,
                close DOUBLE PRECISION
            );
            CREATE TABLE accounts (
                id BIGSERIAL PRIMARY KEY,
                name TEXT NOT NULL
            );
            CREATE TABLE orders (
                id BIGSERIAL,
                account_id BIGINT NOT NULL
            );
        """),
        encoding="utf-8",
    )
    (mig / "02_timescale.sql").write_text(
        textwrap.dedent("""\
            DO $ht$
            BEGIN
              EXECUTE $e$
                SELECT create_hypertable(
                  'market_bars',
                  by_range('bar_time', INTERVAL '30 days'),
                  if_not_exists => TRUE
                )
              $e$;
            END $ht$;

            ALTER TABLE market_bars SET (
              timescaledb.compress,
              timescaledb.compress_segmentby = 'symbol'
            );

            CREATE MATERIALIZED VIEW IF NOT EXISTS market_bars_1d
            WITH (timescaledb.continuous) AS
            SELECT time_bucket('1 day', bar_time) AS bucket, symbol, last(close, bar_time) AS close
            FROM market_bars
            GROUP BY bucket, symbol;

            ALTER TABLE orders ADD COLUMN status TEXT NOT NULL;
            ALTER TABLE orders ADD CONSTRAINT pk_orders PRIMARY KEY (id);
            ALTER TABLE orders ADD CONSTRAINT fk_orders_acc FOREIGN KEY (account_id) REFERENCES accounts(id);
        """),
        encoding="utf-8",
    )

    out = tmp_path / "out"
    scan_polyglot_codebase(tmp_path, out)
    schema = json.loads((out / "db-schema.json").read_text(encoding="utf-8"))

    assert schema["summary"]["hypertables_count"] == 1
    assert schema["summary"]["caggs_count"] == 1
    assert schema["summary"]["compressed_count"] == 1

    by_name = {t["name"]: t for t in schema["tables"]}
    assert by_name["market_bars"]["is_hypertable"] is True
    assert by_name["market_bars"]["hypertable_time_column"] == "bar_time"
    assert by_name["market_bars"]["chunk_interval"] == "30 days"
    assert by_name["market_bars"]["compression_enabled"] is True

    assert by_name["market_bars_1d"]["is_cagg"] is True
    assert by_name["market_bars_1d"]["is_hypertable"] is True
    assert by_name["market_bars_1d"]["is_view"] is True
    assert by_name["market_bars_1d"]["source_table"] == "market_bars"

    orders = by_name["orders"]
    assert any(c["name"] == "status" for c in orders["columns"])
    assert any(c["name"] == "id" and c["pk"] is True for c in orders["columns"])
    assert any(fk["target_table"] == "accounts" for fk in orders["foreign_keys"])

    dbh = analyze_db_health(out)
    assert dbh["hypertables_count"] == 1
    assert dbh["caggs_count"] == 1
    assert "market_bars_1d" not in dbh["tables_without_pk"]


def test_p01_config_matrix_builtin_allowlist_and_env_prefix(tmp_path: Path) -> None:
    (tmp_path / ".env.example").write_text("APP_DB_URL=\nCUSTOM_API_KEY=\n", encoding="utf-8")
    src_fe = tmp_path / "frontend" / "src"
    src_fe.mkdir(parents=True)
    (src_fe / "env.ts").write_text(
        textwrap.dedent("""\
            export const isDev = import.meta.env.DEV;
            export const isProd = import.meta.env.PROD;
            export const mode = import.meta.env.MODE;
            export const base = import.meta.env.BASE_URL;
            export const nodeEnv = process.env.NODE_ENV;
            export const undoc = import.meta.env.VITE_SECRET_WIDGET;
        """),
        encoding="utf-8",
    )
    src_be = tmp_path / "backend" / "app"
    src_be.mkdir(parents=True)
    (src_be / "settings.py").write_text(
        textwrap.dedent("""\
            from pydantic_settings import BaseSettings, SettingsConfigDict
            from pydantic import Field

            class AppSettings(BaseSettings):
                model_config = SettingsConfigDict(env_prefix="APP_")
                db_url: str = "sqlite:///local.db"
                api_key: str = Field(default="", validation_alias="CUSTOM_API_KEY")
        """),
        encoding="utf-8",
    )

    out = tmp_path / "out"
    res = generate_config_matrix(tmp_path, out)
    by_name = {v["name"]: v for v in res["variables"]}

    for builtin in ("DEV", "PROD", "MODE", "BASE_URL", "NODE_ENV"):
        assert by_name[builtin]["status"] == "BUILTIN"
    assert res["summary"]["builtin_count"] >= 5
    assert by_name["APP_DB_URL"]["status"] == "OK"
    assert by_name["CUSTOM_API_KEY"]["status"] == "OK"
    assert by_name["VITE_SECRET_WIDGET"]["status"] == "UNDOCUMENTED"
    assert res["summary"]["undocumented_count"] == 1


def test_p01_domain_bucketing_and_router_level_auth(tmp_path: Path) -> None:
    svc = tmp_path / "backend" / "app" / "services"
    api = tmp_path / "backend" / "app" / "api"
    tst = tmp_path / "backend" / "tests"
    svc.mkdir(parents=True)
    api.mkdir(parents=True)
    tst.mkdir(parents=True)

    (svc / "billing.py").write_text("def compute(x: int) -> int:\n    return x * 2\n", encoding="utf-8")
    (api / "routes.py").write_text(
        textwrap.dedent("""\
            from fastapi import APIRouter, Depends

            def require_user():
                return "ok"

            protected_router = APIRouter(dependencies=[Depends(require_user)])
            open_router = APIRouter()

            @protected_router.post("/items")
            async def create_item() -> dict:
                return {"ok": True}

            @open_router.delete("/items/1")
            async def delete_item() -> dict:
                return {"ok": True}
        """),
        encoding="utf-8",
    )
    (tst / "test_billing.py").write_text("def test_ok():\n    assert 1 == 1\n", encoding="utf-8")
    (tst / "test_api_routes.py").write_text("def test_api():\n    assert True\n", encoding="utf-8")

    hv4 = analyze_health_v4(tmp_path)
    api_gov = hv4["api_governance"]
    assert api_gov["mutating_routes_scanned"] == 2
    assert api_gov["router_protected_count"] == 1
    assert api_gov["unprotected_count"] == 1
    assert api_gov["unprotected_mutating_routes"][0]["func"] == "delete_item"

    by_dom = {d["domain"]: d for d in hv4["test_quality"]["by_domain"]}
    assert by_dom["backend/app/api"]["test_files"] >= 1
    assert by_dom["backend/app/services"]["test_files"] >= 1


def test_p02_runtime_bugs_v2_python_and_vue_ts(tmp_path: Path) -> None:
    be = tmp_path / "backend" / "app"
    fe = tmp_path / "frontend" / "src"
    be.mkdir(parents=True)
    fe.mkdir(parents=True)

    (be / "worker.py").write_text(
        textwrap.dedent("""\
            import asyncio
            import sqlite3
            import subprocess
            from pathlib import Path

            def bad_defaults(items=[]):
                return items

            def leak_resource(p):
                conn = sqlite3.connect(p)
                return conn

            def swallow():
                try:
                    return 1 / 0
                except Exception:
                    return None

            def closures():
                fns = []
                for i in range(5):
                    fns.append(lambda: i)
                return fns

            async def async_handler(p: Path):
                subprocess.run(["echo", "hi"], timeout=2)
                _ = p.read_text()
                await asyncio.to_thread(p.read_text)
        """),
        encoding="utf-8",
    )

    (fe / "Widget.vue").write_text(
        textwrap.dedent("""\
            <template>
              <div>
                <span v-for="item in items">{{ item.name }}</span>
              </div>
            </template>
            <script setup lang="ts">
            const props = defineProps<{ items: any[]; count: number }>();
            function bump() {
              props.count = 10;
              fetch('/api/ping');
            }
            setInterval(() => bump(), 1000);
            </script>
        """),
        encoding="utf-8",
    )

    hv4 = analyze_health_v4(tmp_path)
    rt2 = hv4["runtime_bugs_v2"]
    rules = set(rt2["by_rule"].keys())

    # Python rules
    assert "ASYNC_BLOCKING_IO" in rules
    assert "MUTABLE_DEFAULT_ARG" in rules
    assert "UNCLOSED_RESOURCE" in rules
    assert "SWALLOWED_EXCEPTION" in rules
    assert "LATE_BINDING_CLOSURE" in rules
    # asyncio.to_thread(p.read_text) must NOT be flagged (only 2 blocking calls, not 3)
    assert hv4["reliability_ast"]["async_blocking_count"] == 2

    # Vue / TS rules
    assert "VUE_VFOR_NO_KEY" in rules
    assert "VUE_PROP_MUTATION" in rules
    assert "JS_LEAKED_LISTENER_OR_TIMER" in rules
    assert "TS_FLOATING_PROMISE" in rules
    assert rt2["frontend_count"] == 4


def test_p03_iac_hardening_cve_ingestion_sarif_and_mcp(tmp_path: Path) -> None:
    wf = tmp_path / ".github" / "workflows"
    wf.mkdir(parents=True)
    (wf / "ci.yml").write_text(
        textwrap.dedent("""\
            name: CI
            on:
              pull_request_target:
              issue_comment:
            permissions: write-all
            jobs:
              build:
                runs-on: self-hosted
                steps:
                  - uses: actions/checkout@v4
                    with:
                      ref: ${{ github.event.pull_request.head.sha }}
                  - uses: actions/setup-python@v5
                  - uses: actions/setup-node@v4
                  - uses: actions/cache@v4
                  - uses: actions/upload-artifact@v4
                  - run: echo "${{ github.event.issue.title }}"
        """),
        encoding="utf-8",
    )
    (tmp_path / "docker-compose.yml").write_text(
        textwrap.dedent("""\
            services:
              api:
                image: myapp:1.0
                privileged: true
                network_mode: host
                volumes:
                  - /var/run/docker.sock:/var/run/docker.sock
        """),
        encoding="utf-8",
    )
    out = tmp_path / "out"
    out.mkdir()
    (out / "sbom.cdx.json").write_text(
        json.dumps({
            "bomFormat": "CycloneDX",
            "specVersion": "1.5",
            "components": [{"name": "urllib3", "version": "1.26.5", "purl": "pkg:pypi/urllib3@1.26.5"}],
        }),
        encoding="utf-8",
    )
    (tmp_path / "pip-audit.json").write_text(
        json.dumps({
            "dependencies": [{
                "name": "urllib3",
                "version": "1.26.5",
                "vulns": [{"id": "GHSA-test-1", "aliases": ["CVE-2023-45803"], "severity": "CRITICAL", "fix_versions": ["2.0.7"], "description": "Cookie leak"}],
            }]
        }),
        encoding="utf-8",
    )

    iac = generate_iac_topology(tmp_path, out)
    iac_rules = [m["rule"] for m in iac["misconfigs"]]
    assert iac_rules.count("GHA_UNPINNED_ACTION") == 5
    assert "GHA_WRITE_ALL" in iac_rules
    assert "GHA_PULL_REQUEST_TARGET" in iac_rules
    assert "GHA_ISSUE_COMMENT_SELF_HOSTED" in iac_rules
    assert "GHA_SCRIPT_INJECTION" in iac_rules
    assert "COMPOSE_PRIVILEGED" in iac_rules
    assert "COMPOSE_DOCKER_SOCK" in iac_rules
    assert "COMPOSE_NO_HEALTHCHECK" in iac_rules

    cve = generate_cve_report(tmp_path, out)
    assert cve["available"] is True
    assert cve["summary"]["critical"] == 1
    assert cve["summary"]["sbom_correlated"] == 1
    sbom_after = json.loads((out / "sbom.cdx.json").read_text(encoding="utf-8"))
    assert len(sbom_after.get("vulnerabilities") or []) == 1

    comp = generate_compliance_evidence(tmp_path, out)
    by_ctrl = {f"{c['framework']}:{c['control_id']}": c for c in comp["controls"]}
    assert by_ctrl["ISO27001:A.8.8"]["status"] == "FAIL"
    assert by_ctrl["SOC2:CC6.6"]["status"] == "FAIL"

    sarif = render_sarif_report(
        {"health_v4": {"runtime_bugs_v2": {"findings": [{"rule": "VUE_VFOR_NO_KEY", "severity": "HIGH", "path": "a.vue", "line": 3, "detail": "missing key"}]}}},
        iac_topology=iac,
        cve_report=cve,
    )
    sarif_rules = {r["ruleId"] for r in sarif["runs"][0]["results"]}
    assert "KP-RUNTIME-VUE_VFOR_NO_KEY" in sarif_rules
    assert "KP-IAC-GHA_WRITE_ALL" in sarif_rules
    assert "KP-CVE-CVE-2023-45803" in sarif_rules

    md = render_markdown_report({"summary": {}, "health_v4": {}, "cve_report": cve, "db_health": {"hypertables_count": 2, "caggs_count": 3}})
    assert "Runtime Bugs v2" in md
    assert "CVE & SBOM" in md
    assert "2` Hypertables" in md

    eng = PortalMcpEngine(tmp_path, out)
    resp = handle_jsonrpc_request(eng, {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "portal_cve_report", "arguments": {}}})
    assert resp is not None and not resp["result"]["isError"]
    assert "CVE-2023-45803" in resp["result"]["content"][0]["text"]
