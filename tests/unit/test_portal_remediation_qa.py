"""Regression tests for Portal Remediation (NEW-2, NEW-3, NEW-5, NEW-10, NEW-11, QA-1..QA-6)."""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

from knowledge_portal.generators.adr_graph import generate_adr_graph
from knowledge_portal.generators.audit_report import render_markdown_report
from knowledge_portal.generators.compliance_evidence import generate_compliance_evidence
from knowledge_portal.generators.git_dag import _fetch_open_prs_rest_api
from knowledge_portal.generators.mission_control import generate_mission_control
from knowledge_portal.indexer.fts_engine import FtsSearchEngine
from knowledge_portal.indexer.search_index import generate_search_index
from knowledge_portal.mcp_budget import ai_slop_and_cheat_guard, estimate_tokens
from knowledge_portal.mcp_server import PortalMcpEngine, handle_jsonrpc_request


def test_new2_new3_mission_control_reads_health_v4_and_compliance_keys(tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir(parents=True)
    (data / "arch-health.json").write_text(json.dumps({
        "summary": {"health_score": 55, "grade": "D", "cycle_count": 6, "orphan_count": 10},
        "health_v4": {
            "runtime_bugs_v2": {
                "total_issues": 85,
                "by_severity": {"CRITICAL": 14, "HIGH": 70, "MEDIUM": 1},
            },
            "owasp_audit": {"findings_count": 3, "by_severity": {"CRITICAL": 1}},
            "migration_sre": {"sre_resilience": {"gaps": [{"severity": "HIGH"}]}},
            "severity_summary": [{"category": "Runtime", "critical": 15, "high": 70, "medium": 1}],
        },
    }), encoding="utf-8")
    (data / "compliance-evidence.json").write_text(json.dumps({
        "summary": {
            "overall_readiness_pct": 71,
            "total_controls": 9,
            "pass_count": 5,
            "warn_count": 3,
            "fail_count": 1,
        },
    }), encoding="utf-8")

    mc = generate_mission_control(tmp_path, data)
    kpis = mc["kpis"]
    assert kpis["runtime_bugs_count"] == 85
    assert kpis["critical_findings"] == 15
    assert kpis["compliance_score"] == 71.0
    assert kpis["controls_passed"] == 5
    assert kpis["controls_total"] == 9


def test_new5_compliance_evidence_warns_missing_cve_and_thresholds_cc71(tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir(parents=True)
    (data / "arch-health.json").write_text(json.dumps({
        "summary": {"cycle_count": 0},
        "health_v4": {
            "observability": {"has_health_probe": True},
            "reliability_ast": {"total_issues": 225},
            "supply_chain_and_ai": {"has_lockfile": True},
        },
    }), encoding="utf-8")
    (data / "sbom.cdx.json").write_text(json.dumps({"bomFormat": "CycloneDX", "components": [{"name": "x"}]}), encoding="utf-8")
    (data / "cve-report.json").write_text(json.dumps({"available": False, "summary": {"total": 0, "critical": 0, "high": 0}}), encoding="utf-8")

    res = generate_compliance_evidence(tmp_path, data)
    by_id = {c["control_id"]: c for c in res["controls"]}
    assert by_id["CC7.1"]["status"] == "FAIL"
    assert by_id["A.8.8"]["status"] == "WARN"


def test_new10_adr_graph_prefixed_ids_and_duplicates(tmp_path: Path) -> None:
    adr_dir = tmp_path / "docs" / "adr"
    adr_dir.mkdir(parents=True)
    for fname, title in [
        ("ADR-CI-003-pipeline.md", "# ADR-CI-003 Pipeline"),
        ("ADR-T13-002-storage.md", "# ADR-T13-002 Storage"),
        ("ADR-UI-002-theme.md", "# ADR-UI-002 Theme"),
        ("ADR-WG-REV-001-review.md", "# ADR-WG-REV-001 Review"),
        ("ADR-012-first.md", "# ADR-012 First"),
        ("ADR-012-second.md", "# ADR-012 Second"),
    ]:
        (adr_dir / fname).write_text(f"{title}\nStatus: Accepted\n", encoding="utf-8")

    out = generate_adr_graph(tmp_path, tmp_path / "out")
    ids = {n["id"] for n in out["nodes"]}
    assert {"ADR-CI-003", "ADR-T13-002", "ADR-UI-002", "ADR-WG-REV-001"}.issubset(ids)
    assert "ADR-012" in out["duplicate_ids"]
    assert len(out["duplicate_ids"]["ADR-012"]) == 2
    assert out["summary"]["duplicate_ids_count"] == 1


def test_new11_git_dag_rest_api_fallback(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "test-readonly-token")
    fake_payload = json.dumps([
        {
            "number": 777,
            "title": "fix(arch): cycles",
            "head": {"ref": "fix/cycles"},
            "base": {"ref": "main"},
            "state": "open",
            "draft": False,
            "html_url": "https://github.com/org/repo/pull/777",
            "updated_at": "2026-11-24T00:00:00Z",
        }
    ]).encode("utf-8")

    class _FakeResp(io.BytesIO):
        status = 200
        def __enter__(self) -> "_FakeResp":
            return self
        def __exit__(self, *args: object) -> None:
            return None

    with (
        patch("knowledge_portal.generators.git_dag._parse_github_owner_repo", return_value="org/repo"),
        patch("urllib.request.urlopen", return_value=_FakeResp(fake_payload)),
    ):
        ok, prs = _fetch_open_prs_rest_api(tmp_path, timeout=5.0)
    assert ok is True
    assert len(prs) == 1
    assert prs[0]["number"] == 777
    assert prs[0]["head"] == "fix/cycles"


def test_qa1_qa2_async_topology_redis_samples_and_strict_enum_validation(tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir(parents=True)
    (data / "async-topology.json").write_text(json.dumps({
        "summary": {"redis_keys_count": 2, "redis_locks_count": 1},
        "celery_tasks": [],
        "beat_schedules": [],
        "redis_keys": [
            {"key_pattern": "cache:bars:*", "kind": "key", "ttl": 60, "operations": ["get", "set"]},
            {"key_pattern": "lock:backtest:*", "kind": "lock", "ttl": 300, "operations": ["set"]},
        ],
        "pubsub_channels": [],
        "ws_streams": [],
        "sse_streams": [],
    }), encoding="utf-8")
    (data / "vertical-slices.json").write_text(json.dumps({"summary": {}, "slices": [], "stores": []}), encoding="utf-8")

    eng = PortalMcpEngine(tmp_path, data, portal_url="http://127.0.0.1:1")

    # QA-1: kind="redis" exposes sample_redis_keys & sample_redis_locks
    resp_redis = handle_jsonrpc_request(eng, {
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "portal_async_topology", "arguments": {"kind": "redis"}},
    })
    assert resp_redis is not None and resp_redis["result"]["isError"] is False
    body = json.loads(resp_redis["result"]["content"][0]["text"])
    assert len(body["sample_redis_keys"]) == 1
    assert len(body["sample_redis_locks"]) == 1

    # QA-2: invalid enum values return isError=True & ok=False
    bad_async = handle_jsonrpc_request(eng, {
        "jsonrpc": "2.0", "id": 2, "method": "tools/call",
        "params": {"name": "portal_async_topology", "arguments": {"kind": "kafka_invalid"}},
    })
    assert bad_async is not None and bad_async["result"]["isError"] is True
    assert json.loads(bad_async["result"]["content"][0]["text"])["error"] == "invalid_kind"

    bad_slice = handle_jsonrpc_request(eng, {
        "jsonrpc": "2.0", "id": 3, "method": "tools/call",
        "params": {"name": "portal_vertical_slice", "arguments": {"layer": "invalid_layer"}},
    })
    assert bad_slice is not None and bad_slice["result"]["isError"] is True
    assert json.loads(bad_slice["result"]["content"][0]["text"])["error"] == "invalid_layer"


def test_qa3_legacy_tools_respect_summary_token_cap(tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir(parents=True)
    (data / "omni-search-index.json").write_text(json.dumps({
        "entities": [
            {"id": f"e{i}", "title": f"Order Service {i}", "subtitle": "sub " * 25, "category": "doc", "path": f"docs/f{i}.md", "search_text": "order " * 40}
            for i in range(60)
        ]
    }), encoding="utf-8")
    (data / "process-flows.json").write_text(json.dumps({
        "flows": [{"id": f"f{i}", "name": f"Order Flow {i}", "steps": [f"step_{j}_" + ("x" * 60) for j in range(25)]} for i in range(20)]
    }), encoding="utf-8")
    eng = PortalMcpEngine(tmp_path, data, portal_url="http://127.0.0.1:1")

    for tname, args in [
        ("portal_search", {"query": "Order", "limit": 50}),
        ("portal_process_flow", {"query": "Order", "limit": 20}),
    ]:
        resp = handle_jsonrpc_request(eng, {
            "jsonrpc": "2.0", "id": 10, "method": "tools/call",
            "params": {"name": tname, "arguments": args},
        })
        assert resp is not None
        tok = estimate_tokens(resp["result"]["content"][0]["text"])
        assert tok <= 1200, f"{tname} exceeded 1200 tok: {tok}"


def test_qa4_obsidian_frontmatter_title_and_fts_sanitization(tmp_path: Path) -> None:
    note = tmp_path / "obsidian" / "backtest_notes.md"
    note.parent.mkdir(parents=True)
    note.write_text("---\ntags: [quant]\ntitle: Backtest Engine Architecture\n---\n\n# Heading\nBody", encoding="utf-8")
    out_idx = tmp_path / "data" / "omni-search-index.json"
    generate_search_index(tmp_path, out_idx)
    payload = json.loads(out_idx.read_text(encoding="utf-8"))
    assert payload["entities"][0]["title"] == "Backtest Engine Architecture"

    # Also test FtsSearchEngine sanitizes stale "---" titles
    out_idx.write_text(json.dumps({
        "entities": [{"id": "d1", "title": "---", "path": "obsidian/stale_note.md", "search_text": "backtest engine"}]
    }), encoding="utf-8")
    fts = FtsSearchEngine(tmp_path / "data")
    hits = fts.search("backtest")
    assert hits and (hits[0].get("name") or hits[0].get("title")) == "Stale Note"


def test_qa5_phantom_import_pip_aliases(tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir(parents=True)
    (data / "stack-ecosystem.json").write_text(json.dumps({
        "items": [{"name": "python-jose"}, {"name": "Pillow"}, {"name": "PyYAML"}, {"name": "fastapi"}]
    }), encoding="utf-8")
    src = tmp_path / "sample_api.py"
    src.write_text("import jose\nfrom PIL import Image\nimport yaml\nimport nonexistent_hallucinated_xyz\n", encoding="utf-8")

    alerts = ai_slop_and_cheat_guard(tmp_path, ["sample_api.py"], "HEAD", data)
    phantom = [a["detail"] for a in alerts if a["rule"] == "PHANTOM_IMPORT"]
    assert not any("jose" in d or "PIL" in d or "yaml" in d for d in phantom)
    assert any("nonexistent_hallucinated_xyz" in d for d in phantom)


def test_qa6_audit_report_formats_none_coverage_as_na() -> None:
    report = {
        "summary": {"health_score": 80, "grade": "B"},
        "health_v4": {
            "quality_telemetry": {"summary": {"sources_count": 0, "coverage_pct": None}},
        },
    }
    md = render_markdown_report(report)
    assert "None%" not in md
    assert "coverage: N/A" in md
