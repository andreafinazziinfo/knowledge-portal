"""Blocking CI Token-Budget & Zero-Silent-Empty Regression Tests (ADR-082)."""

from __future__ import annotations

import json
from pathlib import Path

from knowledge_portal.mcp_budget import estimate_tokens
from knowledge_portal.mcp_server import TOOLS_SPEC, PortalMcpEngine, handle_jsonrpc_request


def _seed_large_dataset(root: Path) -> Path:
    """Create a large realistic dataset (hundreds of items per artifact) to stress-test summary budgets."""
    data = root / "data"
    data.mkdir(parents=True, exist_ok=True)

    (data / "arch-health.json").write_text(json.dumps({
        "summary": {"health_score": 82, "grade": "B", "cycle_count": 3, "orphan_count": 40},
        "fix_queue": [{"priority": "P1", "category": "Security", "title": f"Fix issue {i}", "path": f"backend/app/mod_{i}.py"} for i in range(120)],
        "health_v4": {
            "severity_summary": [{"category": f"Cat{i}", "critical": 0, "high": i, "medium": i * 2} for i in range(12)],
            "dead_code_symbols": {"summary": {"total": 200}, "python_dead_symbols": [{"name": f"fn_{i}", "path": f"app/m{i}.py", "line": i} for i in range(200)]},
            "quality_telemetry": {"summary": {"sources_count": 5, "ruff_issues": 40}},
            "migration_sre": {"migration_safety": {"by_severity": {"HIGH": 2}}, "sre_resilience": {"score_pct": 85}},
            "frontend_hygiene": {"summary": {"total_issues": 15}},
            "semantic_clones": {"clone_groups_count": 4, "duplicated_functions_count": 9},
        },
        "cve_report": {"summary": {"total": 10, "critical": 0, "high": 2}, "vulnerabilities": [{"id": f"CVE-2026-{i:04d}", "severity": "HIGH", "package": f"pkg-{i}"} for i in range(60)]},
        "sarif_findings": {"summary": {"available": True, "total": 80, "by_tool": {"semgrep": 80}}, "findings": [{"tool": "semgrep", "severity": "HIGH", "rule_id": f"R{i}", "path": f"a/b_{i}.py", "line": i} for i in range(80)]},
    }), encoding="utf-8")

    (data / "git-dag.json").write_text(json.dumps({
        "summary": {"total_worktrees": 18, "dirty_worktrees": 4, "total_branches": 60},
        "worktrees": [{"branch": f"feat/wt-{i}", "status": "dirty" if i < 4 else "clean", "dirty_files": i} for i in range(40)],
        "branches": [{"name": f"feat/b-{i}", "sha": f"{i:08x}"} for i in range(100)],
        "merge_order": [f"feat/wt-{i}" for i in range(15)],
    }), encoding="utf-8")

    (data / "dead-code.json").write_text(json.dumps({
        "summary": {"python_count": 150, "js_export_count": 80, "vue_component_count": 20, "total": 250},
        "python_dead_symbols": [{"name": f"dead_py_{i}", "path": f"backend/app/m{i}.py", "line": i} for i in range(150)],
        "js_unused_exports": [{"name": f"deadJs{i}", "path": f"frontend/src/u{i}.ts"} for i in range(80)],
        "vue_unused_components": [{"name": f"DeadComp{i}", "path": f"frontend/src/C{i}.vue"} for i in range(20)],
    }), encoding="utf-8")

    (data / "adr-graph.json").write_text(json.dumps({
        "total_adrs": 90,
        "nodes": [{"id": f"ADR-{i:03d}", "title": f"Architecture Decision Number {i}", "status": "Accepted", "domain": "Backend"} for i in range(90)],
        "edges": [{"source": f"ADR-{i:03d}", "target": f"ADR-{i + 1:03d}"} for i in range(89)],
        "runbooks": [{"title": f"Runbook {i}", "steps": [f"step {j}" for j in range(10)]} for i in range(20)],
    }), encoding="utf-8")

    (data / "config-matrix.json").write_text(json.dumps({
        "summary": {"total_vars": 140, "drift_count": 30},
        "variables": [{"name": f"ENV_VAR_{i}", "status": "UNDOCUMENTED" if i < 30 else "OK", "in_code": True, "in_example": i >= 30} for i in range(140)],
    }), encoding="utf-8")

    (data / "api-catalog.json").write_text(json.dumps({
        "summary": {"total_endpoints": 180},
        "tags": [f"tag_{i}" for i in range(25)],
        "endpoints": [{"method": "GET", "path": f"/api/v1/resource/{i}", "handler": f"get_res_{i}", "auth_required": True, "file": f"backend/app/api/r{i}.py"} for i in range(180)],
    }), encoding="utf-8")

    (data / "db-schema.json").write_text(json.dumps({
        "tables": [{"name": f"table_{i}", "columns": [{"name": f"col_{j}", "type": "text"} for j in range(12)], "foreign_keys": [], "is_hypertable": i < 5} for i in range(45)],
    }), encoding="utf-8")

    (data / "stack-ecosystem.json").write_text(json.dumps({
        "summary": {"total": 200},
        "items": [{"name": f"package-{i}", "version": "1.2.3", "ecosystem": "python"} for i in range(200)],
    }), encoding="utf-8")

    (data / "iac-topology.json").write_text(json.dumps({
        "summary": {"services_count": 15, "misconfigs_count": 40},
        "misconfigurations": [{"severity": "HIGH", "rule": f"IAC_{i}", "file": f"docker/s{i}.yml", "message": "Hardening detail " * 5} for i in range(40)],
    }), encoding="utf-8")

    (data / "ai-registry.json").write_text(json.dumps({
        "summary": {"unique_models_count": 10, "guardrail_findings_count": 25},
        "models": [f"model-v{i}" for i in range(15)],
        "guardrail_findings": [{"severity": "MEDIUM", "rule": f"AI_{i}", "path": f"app/ai/m{i}.py"} for i in range(25)],
    }), encoding="utf-8")

    (data / "call-graph.json").write_text(json.dumps({
        "summary": {"symbols_count": 400, "chains_count": 80},
        "chains": [{"entry": f"/api/v1/e{i}", "steps": [f"fn_{j}" for j in range(8)]} for i in range(80)],
        "symbols": {f"mod.fn_{i}": {"id": f"mod.fn_{i}", "name": f"fn_{i}", "signature": "() -> None", "callees": [f"c_{j}" for j in range(10)], "db_tables": ["t1"]} for i in range(100)},
    }), encoding="utf-8")

    (data / "mission-control.json").write_text(json.dumps({
        "kpis": {"health_score": 82, "grade": "B", "open_anomalies": 20},
        "subsystems": [{"id": f"sub_{i}", "status": "green", "metric": f"{i} ok", "detail": "long text " * 20} for i in range(12)],
        "anomalies": [{"severity": "P1", "title": f"Anomaly {i} " + ("detail " * 10)} for i in range(30)],
    }), encoding="utf-8")

    (data / "sarif-findings.json").write_text(json.dumps({
        "available": True,
        "summary": {"available": True, "total": 100, "by_tool": {"semgrep": 60, "trivy": 40}},
        "findings": [{"tool": "semgrep", "severity": "HIGH", "rule_id": f"S{i}", "path": f"src/f{i}.py", "line": i, "message": "msg " * 10} for i in range(100)],
    }), encoding="utf-8")

    (data / "agent-instructions-audit.json").write_text(json.dumps({
        "summary": {"files_found": 5, "total_tokens": 9500, "dead_paths_count": 25, "duplications_count": 10, "contradictions_count": 1, "hygiene_score": 30},
        "files": [{"path": f"AGENT_{i}.md", "estimated_tokens": 1900, "bloat_level": "WARN", "dead_paths_count": 5} for i in range(5)],
        "dead_paths": [{"file": "CLAUDE.md", "missing_path": f"backend/missing_{i}.py"} for i in range(25)],
    }), encoding="utf-8")

    (data / "compliance-evidence.json").write_text(json.dumps({
        "summary": {"score_pct": 85},
        "controls": [{"framework": "SOC2", "control_id": f"CC{i}", "title": f"Control {i}", "status": "PASS", "evidence": "ev " * 10} for i in range(40)],
    }), encoding="utf-8")

    (data / "cve-report.json").write_text(json.dumps({
        "available": True,
        "summary": {"total": 50, "critical": 0, "high": 5},
        "vulnerabilities": [{"id": f"CVE-2026-{i:04d}", "severity": "HIGH", "package": f"pkg{i}"} for i in range(50)],
    }), encoding="utf-8")

    (data / "graph.json").write_text(json.dumps({"nodes": [{"id": "n1", "path": "a.py"}], "edges": []}), encoding="utf-8")
    (data / "process-flows.json").write_text(json.dumps({"flows": [{"name": "OrderFlow", "steps": ["a", "b"]}]}), encoding="utf-8")

    (data / "vertical-slices.json").write_text(json.dumps({
        "summary": {"total_slices": 150, "cross_stack_edges_count": 180, "exact_matches": 100, "parameterized_matches": 80, "stores_count": 20, "god_stores_count": 8, "components_count": 200, "features_count": 25},
        "slices": [
            {
                "id": f"GET /api/v1/mod{i}/items",
                "feature": f"mod{i % 10}",
                "method": "GET",
                "endpoint": f"/api/v1/mod{i}/items",
                "confidence": 1.0,
                "layers": {
                    "components": [f"frontend/src/views/V{i}.vue"],
                    "stores": [f"useMod{i}Store (frontend/src/stores/m{i}.ts)"],
                    "api_clients": [f"frontend/src/stores/m{i}.ts:42"],
                    "backend_route": {"file": f"backend/app/api/m{i}.py", "handler": f"list_{i}", "line": 10, "auth": "JWT"},
                    "services_and_tasks": {"services": [f"app.services.s{i}"], "celery_tasks": [f"task_{i}"]},
                    "storage": {"redis_keys": [f"cache:m{i}:*"], "db_tables": [f"table_{i}"]},
                },
            }
            for i in range(150)
        ],
        "stores": [{"name": f"useMod{i}Store", "file": f"frontend/src/stores/m{i}.ts", "loc": 400 + i, "is_god_store": i < 8, "api_calls_count": 6} for i in range(20)],
        "cross_stack_edges": [{"source": f"frontend/src/stores/m{i}.ts", "target": f"backend/app/api/m{i}.py", "type": "FE_CALLS_API"} for i in range(150)],
    }), encoding="utf-8")

    (data / "async-topology.json").write_text(json.dumps({
        "summary": {"celery_tasks_count": 40, "beat_schedules_count": 20, "redis_keys_count": 90, "redis_locks_count": 8, "pubsub_channels_count": 10, "ws_streams_count": 6, "sse_streams_count": 2, "queues": ["default", "batch"]},
        "celery_tasks": [{"name": f"app.tasks.t{i}", "function": f"task_{i}", "queue": "batch", "file": f"backend/app/workers/t{i}.py", "max_retries": 3, "producers": [{"file": "api.py", "line": i}]} for i in range(40)],
        "beat_schedules": [{"name": f"sched_{i}", "task": f"app.tasks.t{i}", "schedule": "crontab(minute=0)", "queue": "batch"} for i in range(20)],
        "redis_keys": [{"key_pattern": f"app:key:{i}:*", "kind": "lock" if i < 8 else "key", "ttl": 60, "operations": ["set", "get"]} for i in range(90)],
        "pubsub_channels": [{"channel": f"chan:{i}", "publishers": [{"file": "p.py"}], "subscribers": [{"file": "s.py"}]} for i in range(10)],
        "ws_streams": [{"protocol": "websocket", "path": f"/ws/s{i}", "consumers": [{"file": "App.vue"}]} for i in range(6)],
        "sse_streams": [{"protocol": "sse", "path": f"/sse/e{i}", "consumers": []} for i in range(2)],
    }), encoding="utf-8")
    (data / "data-contracts.json").write_text(json.dumps({
        "summary": {"pydantic_models_count": 200, "ts_types_count": 350, "matched_schemas_count": 80, "schema_drift_count": 35, "untyped_routes_count": 60, "untyped_routes_pct": 42.0, "http_exceptions_count": 150, "custom_exceptions_count": 20, "db_rw_tables_count": 35},
        "pydantic_models": [{"name": f"Model{i}", "file": f"backend/app/schemas/m{i}.py", "line": 10, "bases": ["BaseModel"], "fields": [{"name": "id", "type": "int", "optional": False}], "field_count": 1} for i in range(200)],
        "ts_types": [{"name": f"Model{i}", "kind": "interface", "file": f"frontend/src/types/m{i}.ts", "line": 5, "fields": [{"name": "id", "type": "number", "optional": False}], "field_count": 1} for i in range(350)],
        "matched_schemas": [{"pydantic_model": f"Model{i}", "pydantic_file": f"backend/app/schemas/m{i}.py", "ts_type": f"Model{i}", "ts_file": f"frontend/src/types/m{i}.ts", "status": "DRIFT" if i < 35 else "SYNCED", "missing_in_ts": ["extra_col"] if i < 35 else [], "missing_in_py": [], "type_mismatches": []} for i in range(80)],
        "schema_drift": [{"pydantic_model": f"Model{i}", "pydantic_file": f"backend/app/schemas/m{i}.py", "ts_type": f"Model{i}", "ts_file": f"frontend/src/types/m{i}.ts", "status": "DRIFT", "missing_in_ts": ["extra_col", "created_at"], "missing_in_py": [], "type_mismatches": [{"field": "id", "py_type": "int", "ts_type": "string"}]} for i in range(35)],
        "untyped_routes": [{"method": "GET", "path": f"/api/v1/raw/{i}", "handler": f"get_{i}", "file": f"backend/app/api/r{i}.py", "line": 12, "reason": "missing_response_model"} for i in range(60)],
        "error_taxonomy": {
            "by_status_code": {"404": 60, "400": 45, "403": 25, "500": 20},
            "http_exceptions": [{"status_code": 404, "detail": f"Item {i} not found", "file": f"backend/app/api/r{i}.py", "line": 20, "function": f"get_{i}"} for i in range(150)],
            "custom_exceptions": [{"name": f"Domain{i}Error", "bases": ["Exception"], "file": f"backend/app/errors/e{i}.py", "line": 5, "docstring": "Domain error"} for i in range(20)],
            "frontend_handlers": [{"file": "frontend/src/api/client.ts", "status_codes": [401, 403, 404, 500]}],
        },
        "db_rw_matrix": [{"table": f"table_{i}", "readers": [f"backend/app/repo/t{i}.py:read"], "writers": [f"backend/app/repo/t{i}.py:write"], "migrations": [f"migrations/00{i}.sql"], "readers_count": 3, "writers_count": 2, "migrations_count": 1, "is_orphan": False} for i in range(35)],
    }), encoding="utf-8")
    (data / "runtime-modes.json").write_text(json.dumps({
        "summary": {"modes_count": 5, "modes_detected_count": 5, "feature_flags_count": 40, "total_env_vars_scanned": 120, "detected_services": ["database", "redis", "worker"], "detected_guards": ["kill_switch", "paper_broker", "read_only_guard"]},
        "modes": [{"mode": m, "label": m.title(), "risk_level": "CRITICAL" if m == "live" else "LOW", "detected_in_code": True, "required_services": ["database", "redis"], "active_guards": [{"guard": "kill_switch", "detected_in_code": True, "files": ["app/guard.py"]}], "active_guards_detected_count": 1, "controlling_env_vars": [{"name": "APP_ENV", "default": m, "files": ["app/config.py"]}], "code_references": [{"file": "app/config.py", "line": 10, "match": m}]} for m in ("offline", "dev", "paper", "shadow", "live")],
        "feature_flags": [{"name": f"ENABLE_FEAT_{i}", "default": "false", "files": ["app/config.py"], "is_feature_flag": True} for i in range(40)],
    }), encoding="utf-8")
    (data / "module-cards.json").write_text(json.dumps({"summary": {"total_files": 1}, "cards": {"a.py": {"lang": "python", "loc": 10, "role": "module", "purpose": "sample", "exports": ["x"], "imports_internal": [], "routes": [], "tables_touched": [], "risk_flags": [], "fast_tests": []}}}), encoding="utf-8")
    (data / "test-oracle.json").write_text(json.dumps({"summary": {"total_test_files": 1}, "source_to_tests": {}, "symbol_to_tests": {}, "tests": {}, "blind_spots": []}), encoding="utf-8")
    (root / "README.md").write_text("# Sample Repo\n", encoding="utf-8")
    return data


def test_all_mcp_tools_respect_summary_token_ceiling(tmp_path: Path) -> None:
    """Every MCP tool in default summary mode MUST stay <= 1,200 tokens (hard CI ceiling)."""
    data = _seed_large_dataset(tmp_path)
    eng = PortalMcpEngine(tmp_path, data, portal_url="http://127.0.0.1:1")

    default_args: dict[str, dict[str, object]] = {
        "portal_search": {"query": "Order"},
        "portal_read_doc": {"path": "README.md"},
        "portal_graph_neighbors": {"node_id": "n1"},
        "portal_context_pack": {"topic": "Order", "max_tokens": 800},
        "portal_impact": {"target": "a.py"},
        "portal_mission_pack": {"task": "Order", "max_tokens": 800},
        "portal_validate_change": {"paths": ["a.py"]},
        "portal_codemode": {"code": "result = 42"},
        "portal_slice_for_task": {"task": "sample", "max_tokens": 1000},
        "portal_check_diff": {"files": ["a.py"], "max_tokens": 1000},
        "portal_handoff_pack": {"task": "sample", "files": ["a.py"], "max_tokens": 1000},
    }

    violations: list[str] = []
    for spec in TOOLS_SPEC:
        tname = spec["name"]
        args = default_args.get(tname, {})
        resp = handle_jsonrpc_request(eng, {
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": tname, "arguments": args},
        })
        assert resp is not None and "result" in resp, f"Missing result for {tname}"
        txt = resp["result"]["content"][0]["text"]
        tok = estimate_tokens(txt)
        if tok > 1200:
            violations.append(f"{tname}: {tok} tok > 1200")

    assert not violations, f"Tools exceeded 1200 token ceiling: {violations}"


def test_zero_silent_empty_and_alias_normalization(tmp_path: Path) -> None:
    """Missing required args or unknown args MUST return ok=False error; aliases MUST normalize."""
    data = _seed_large_dataset(tmp_path)
    eng = PortalMcpEngine(tmp_path, data, portal_url="http://127.0.0.1:1")

    # Missing required arg -> explicit invalid_arguments (zero silent-empty)
    for tool_name in ("portal_context_pack", "portal_mission_pack", "portal_slice_for_task", "portal_impact", "portal_read_doc"):
        resp = handle_jsonrpc_request(eng, {
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": tool_name, "arguments": {}},
        })
        assert resp is not None and resp["result"]["isError"] is True
        body = json.loads(resp["result"]["content"][0]["text"])
        assert body["ok"] is False and body["error"] == "invalid_arguments"

    # Unknown parameter -> explicit invalid_arguments
    bad = handle_jsonrpc_request(eng, {
        "jsonrpc": "2.0", "id": 2, "method": "tools/call",
        "params": {"name": "portal_health_audit", "arguments": {"nonexistent_param": 123}},
    })
    assert bad is not None and bad["result"]["isError"] is True
    assert json.loads(bad["result"]["content"][0]["text"])["unknown"] == ["nonexistent_param"]

    # Alias normalization: query -> topic on portal_context_pack, query -> task on portal_mission_pack
    aliased = handle_jsonrpc_request(eng, {
        "jsonrpc": "2.0", "id": 3, "method": "tools/call",
        "params": {"name": "portal_context_pack", "arguments": {"query": "Order", "max_tokens": 800}},
    })
    assert aliased is not None and aliased["result"]["isError"] is False
    aliased_body = json.loads(aliased["result"]["content"][0]["text"])
    assert aliased_body["_normalized_args"] == {"query": "topic"}
