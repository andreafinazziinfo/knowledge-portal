"""
Unit & Integration Tests for ADR-081 Sprint 1 (OSS Foundation):
- 3 stdlib generators: git_dag.py, adr_graph.py, mission_control.py
- 3 HTTP API endpoints: /api/git-dag, /api/adr-graph, /api/mission-control
- 3 MCP v2 tools & 3 MCP resources + CodeMode SDK integration
- 4 Air-gapped HTML views (0 CDN, dark/light theme, dashboard navigation wiring)
"""

from __future__ import annotations

import http.client
import json
import re
import shutil
import subprocess
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from knowledge_portal.generators.adr_graph import generate_adr_graph
from knowledge_portal.generators.git_dag import build_stacked_dag, generate_git_dag
from knowledge_portal.generators.mission_control import generate_mission_control
from knowledge_portal.mcp_server import PortalMcpEngine, handle_jsonrpc_request
from knowledge_portal.server import PortalRequestHandler, get_template_dir

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _git(cwd: Path, *args: str) -> None:
    git_bin = shutil.which("git")
    assert git_bin is not None, "git binary required for git_dag unit tests"
    subprocess.run(
        [git_bin, *args],
        cwd=str(cwd),
        check=True,
        capture_output=True,
        text=True,
    )


def _init_sample_git_repo(repo_dir: Path) -> Path:
    repo_dir.mkdir(parents=True, exist_ok=True)
    _git(repo_dir, "init", "-b", "main")
    _git(repo_dir, "config", "user.email", "dev@example.org")
    _git(repo_dir, "config", "user.name", "Test Developer")
    (repo_dir / "README.md").write_text("# Sample OSS Repo\n", encoding="utf-8")
    wf_dir = repo_dir / ".github" / "workflows"
    wf_dir.mkdir(parents=True, exist_ok=True)
    (wf_dir / "ci.yml").write_text(
        "name: Unit CI\non:\n  push:\n  pull_request:\njobs:\n  test:\n    runs-on: ubuntu-latest\n",
        encoding="utf-8",
    )
    _git(repo_dir, "add", ".")
    _git(repo_dir, "commit", "-m", "chore: initial commit")
    _git(repo_dir, "checkout", "-b", "feat/stacked-a")
    (repo_dir / "module_a.py").write_text("def alpha() -> int:\n    return 1\n", encoding="utf-8")
    _git(repo_dir, "add", "module_a.py")
    _git(repo_dir, "commit", "-m", "feat: add module_a")
    _git(repo_dir, "checkout", "main")
    return repo_dir


def test_git_dag_generator_worktrees_branches_and_offline_fallback(tmp_path: Path) -> None:
    repo = _init_sample_git_repo(tmp_path / "repo")
    wt_dirty = tmp_path / "wt-dirty"
    wt_detached = tmp_path / "wt-detached"

    _git(repo, "worktree", "add", str(wt_dirty), "feat/stacked-a")
    (wt_dirty / "untracked.txt").write_text("dirty state\n", encoding="utf-8")
    _git(repo, "worktree", "add", "--detach", str(wt_detached), "HEAD")

    out_dir = tmp_path / "data"
    data = generate_git_dag(repo, out_dir, include_gh=False)

    assert data["default_branch"] == "main"
    assert data["summary"]["is_git_repo"] is True
    assert data["summary"]["gh_available"] is False
    assert data["summary"]["total_worktrees"] == 3
    assert data["summary"]["dirty_worktrees"] >= 1
    assert data["summary"]["detached_worktrees"] >= 1
    assert data["summary"]["workflows_count"] == 1
    assert any(w["name"] == "Unit CI" for w in data["workflows"])

    statuses = {w["name"]: w["status"] for w in data["worktrees"]}
    assert statuses["wt-dirty"] == "dirty"
    assert statuses["wt-detached"] == "detached"
    assert (out_dir / "git-dag.json").is_file()
    assert (out_dir / "git_dag.js").is_file()


def test_git_dag_stacked_pr_chains_and_merge_order() -> None:
    open_prs = [
        {"number": 10, "title": "Base feature", "head": "feat/a", "base": "main", "is_draft": False, "additions": 50, "deletions": 5, "ci_status": "green"},
        {"number": 11, "title": "Stacked layer 2", "head": "feat/b", "base": "feat/a", "is_draft": False, "additions": 30, "deletions": 2, "ci_status": "pending"},
        {"number": 12, "title": "Stacked layer 3", "head": "feat/c", "base": "feat/b", "is_draft": True, "additions": 10, "deletions": 0, "ci_status": "draft"},
        {"number": 15, "title": "Independent fix", "head": "fix/x", "base": "main", "is_draft": False, "additions": 4, "deletions": 1, "ci_status": "green"},
    ]
    nodes, edges, chains, merge_order = build_stacked_dag(open_prs, [], "main")

    assert len(nodes) == 5  # main + 4 PRs
    assert len(edges) == 4
    assert len(chains) == 1
    assert chains[0]["prs"] == [10, 11, 12]
    ordered_nums = [m["pr_number"] for m in merge_order]
    assert ordered_nums.index(10) < ordered_nums.index(11) < ordered_nums.index(12)


def test_adr_graph_generator_parses_adrs_edges_and_runbooks(tmp_path: Path) -> None:
    adr_dir = tmp_path / "docs" / "adr"
    adr_dir.mkdir(parents=True)
    (adr_dir / "ADR-001-initial-auth.md").write_text(
        "# ADR-001: Initial Auth Architecture\n\n**Status**: Superseded\n**Date**: 2025-01-10\n\nUses session tokens.\n",
        encoding="utf-8",
    )
    (adr_dir / "ADR-002-jwt-auth.md").write_text(
        "# ADR-002: Stateless JWT Security\n\nStatus: Accepted\nDate: 2025-04-15\n\nSupersedes: ADR-001\n\nIntroduces short-lived JWT tokens.\n",
        encoding="utf-8",
    )
    (adr_dir / "ADR-003-mcp-copilot.md").write_text(
        "# ADR-003: AI MCP Copilot Integration\n\nStatus: Proposed\nDate: 2026-01-20\n\nBuilds on ADR-002 for agent auth.\n",
        encoding="utf-8",
    )

    rb_dir = tmp_path / "docs" / "runbooks"
    rb_dir.mkdir(parents=True)
    (rb_dir / "INCIDENT_RECOVERY.md").write_text(
        "# Incident Recovery Runbook\n\n- [ ] Check service health\n- [x] Verify DB connectivity\n\n```bash\ncurl -sf http://127.0.0.1:8000/health\n```\n",
        encoding="utf-8",
    )

    out_dir = tmp_path / "data"
    data = generate_adr_graph(tmp_path, out_dir)

    assert data["total_adrs"] == 3
    assert data["summary"]["accepted_count"] == 1
    assert data["summary"]["proposed_count"] == 1
    assert data["summary"]["superseded_count"] == 1
    assert any(e["source"] == "ADR-002" and e["target"] == "ADR-001" and e["type"] == "supersedes" for e in data["edges"])
    assert any(e["source"] == "ADR-003" and e["target"] == "ADR-002" and e["type"] == "references" for e in data["edges"])
    assert len(data["runbooks"]) == 1
    assert data["runbooks"][0]["step_count"] == 2
    assert "curl -sf" in data["runbooks"][0]["commands"][0]
    assert (out_dir / "adr-graph.json").is_file()
    assert (out_dir / "adr_graph.js").is_file()


def test_mission_control_aggregator_and_anomalies(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)
    (data_dir / "arch-health.json").write_text(
        json.dumps({
            "summary": {"health_score": 64, "grade": "C", "cycle_count": 2, "orphan_count": 5},
            "runtime_bugs": [{"severity": "CRITICAL", "rule": "RB001"}],
            "health_v4": {"dead_code_symbols": {"summary": {"total_dead_symbols": 12}}},
        }),
        encoding="utf-8",
    )
    (data_dir / "cve-report.json").write_text(
        json.dumps({"summary": {"critical": 1, "high": 2, "total_vulnerabilities": 3}}),
        encoding="utf-8",
    )
    (data_dir / "compliance-evidence.json").write_text(
        json.dumps({"summary": {"readiness_pct": 85.0, "passed": 17, "total_controls": 20}}),
        encoding="utf-8",
    )
    (data_dir / "git-dag.json").write_text(
        json.dumps({"summary": {"total_worktrees": 18, "dirty_worktrees": 1, "stale_worktrees": 12, "open_prs_count": 4, "stacked_chains_count": 1, "workflows_count": 2}}),
        encoding="utf-8",
    )
    (data_dir / "adr-graph.json").write_text(
        json.dumps({"summary": {"total_adrs": 10, "proposed_count": 2, "total_runbooks": 3}}),
        encoding="utf-8",
    )

    payload = generate_mission_control(
        tmp_path,
        data_dir,
        hub_summary={"anomalies": [{"severity": "P2", "category": "Plugin", "title": "Plugin check", "detail": "OK"}]},
    )

    assert payload["kpis"]["health_score"] == 64
    assert payload["kpis"]["cve_critical_high"] == 3
    assert payload["kpis"]["dead_code_count"] == 12
    assert payload["kpis"]["compliance_score"] == 85.0
    assert payload["kpis"]["total_adrs"] == 10
    assert payload["kpis"]["total_runbooks"] == 3
    assert len(payload["subsystems"]) == 6
    assert any(a["severity"] == "P0" for a in payload["anomalies"])
    assert any(a["category"] == "Plugin" for a in payload["anomalies"])
    assert (data_dir / "mission-control.json").is_file()
    assert (data_dir / "mission_control.js").is_file()


def test_mcp_v2_tools_resources_and_codemode(tmp_path: Path) -> None:
    repo = _init_sample_git_repo(tmp_path / "repo")
    adr_dir = repo / "docs" / "adr"
    adr_dir.mkdir(parents=True)
    (adr_dir / "ADR-010-core.md").write_text("# ADR-010: Core API\n\nStatus: Accepted\n", encoding="utf-8")

    data_dir = tmp_path / "data"
    engine = PortalMcpEngine(project_dir=repo, data_dir=data_dir)

    # Tools list includes the 3 new tools
    tlist = handle_jsonrpc_request(engine, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert tlist is not None
    tool_names = {t["name"] for t in tlist["result"]["tools"]}
    assert {"portal_git_dag", "portal_adr_graph", "portal_mission_control"}.issubset(tool_names)

    # Resources list includes the 3 new resources
    rlist = handle_jsonrpc_request(engine, {"jsonrpc": "2.0", "id": 2, "method": "resources/list"})
    assert rlist is not None
    res_uris = {r["uri"] for r in rlist["result"]["resources"]}
    assert {"portal://git-dag", "portal://adr-graph", "portal://mission-control"}.issubset(res_uris)

    # Call each tool and read each resource
    for idx, (tool_name, uri) in enumerate([
        ("portal_git_dag", "portal://git-dag"),
        ("portal_adr_graph", "portal://adr-graph"),
        ("portal_mission_control", "portal://mission-control"),
    ], start=10):
        tresp = handle_jsonrpc_request(engine, {"jsonrpc": "2.0", "id": idx, "method": "tools/call", "params": {"name": tool_name, "arguments": {}}})
        assert tresp is not None and not tresp["result"]["isError"]
        parsed_t = json.loads(tresp["result"]["content"][0]["text"])
        assert "schema_version" in parsed_t

        rresp = handle_jsonrpc_request(engine, {"jsonrpc": "2.0", "id": idx + 100, "method": "resources/read", "params": {"uri": uri}})
        assert rresp is not None
        parsed_r = json.loads(rresp["result"]["contents"][0]["text"])
        assert "schema_version" in parsed_r

    # CodeMode sandbox can call the 3 new SDK methods
    cm = engine.codemode_execute(
        "result = {'adrs': portal.adr_graph()['total_adrs'], 'wt': portal.git_dag()['summary']['total_worktrees'], 'ready': portal.mission_control()['kpis']['ai_readiness']}"
    )
    assert cm.get("ok") is True
    assert cm["result"]["adrs"] == 1
    assert cm["result"]["wt"] >= 1
    assert cm["result"]["ready"] == "READY"


def test_http_endpoints_git_dag_adr_graph_mission_control(tmp_path: Path) -> None:
    repo = _init_sample_git_repo(tmp_path / "repo")
    (repo / "docs" / "adr").mkdir(parents=True)
    (repo / "docs" / "adr" / "ADR-001-test.md").write_text("# ADR-001: Test\n\nStatus: Accepted\n", encoding="utf-8")

    tpl_dir = tmp_path / "tpl"
    (tpl_dir / "data").mkdir(parents=True)
    (tpl_dir / "dashboard.html").write_text("<html><body>ok</body></html>", encoding="utf-8")

    class _TestHandler(PortalRequestHandler):
        template_dir = tpl_dir
        project_dir = repo

    server = ThreadingHTTPServer(("127.0.0.1", 0), _TestHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        for ep, expected_key in [
            ("/api/git-dag", "worktrees"),
            ("/api/adr-graph", "nodes"),
            ("/api/mission-control", "kpis"),
        ]:
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            try:
                conn.request("GET", ep)
                resp = conn.getresponse()
                body = json.loads(resp.read().decode("utf-8"))
                assert resp.status == 200, f"{ep} returned {resp.status}"
                assert expected_key in body
            finally:
                conn.close()
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.parametrize(
    "view_name",
    [
        "mission-control.html",
        "git-pr-dag.html",
        "adr-runbook-hub.html",
        "ai-mission-launcher.html",
    ],
)
def test_new_views_are_airgapped_zero_cdn_and_wired(view_name: str) -> None:
    tpl_dir = get_template_dir()
    html_path = tpl_dir / "views" / view_name
    assert html_path.is_file(), f"Missing view: {html_path}"
    content = html_path.read_text(encoding="utf-8")

    # Zero external CDN links in script/link/img tags
    external_refs = re.findall(r"""(?:src|href)\s*=\s*["']https?://""", content, re.IGNORECASE)
    assert external_refs == [], f"External CDN reference found in {view_name}: {external_refs}"
    assert "portal-theme.css" in content
    assert "portal-ui.js" in content

    # Wired in dashboard.html
    dash = (tpl_dir / "dashboard.html").read_text(encoding="utf-8")
    tab_id = view_name.replace(".html", "")
    assert f"views/{view_name}" in dash
    assert f"'{tab_id}'" in dash
