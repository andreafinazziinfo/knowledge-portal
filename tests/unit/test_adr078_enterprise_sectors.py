"""Unit tests for ADR-078 — 4 New Zero-Dep Enterprise Sectors."""

from __future__ import annotations

import json
from pathlib import Path

from knowledge_portal.codemode_sandbox import execute_codemode
from knowledge_portal.generators.ai_registry import generate_ai_registry
from knowledge_portal.generators.compliance_evidence import generate_compliance_evidence
from knowledge_portal.generators.config_matrix import generate_config_matrix
from knowledge_portal.generators.iac_topology import generate_iac_topology
from knowledge_portal.mcp_server import PortalMcpEngine, handle_jsonrpc_request


def test_config_matrix_drift_flags_and_never_reads_dotenv(tmp_path: Path):
    repo = tmp_path / "cfg_repo"
    data_dir = tmp_path / "data"
    (repo / "src").mkdir(parents=True)
    (repo / "core" / "frozen").mkdir(parents=True)

    # Real .env MUST NEVER be read!
    (repo / ".env").write_text("TOP_SECRET_REAL_ENV=supersecret123\n", encoding="utf-8")
    (repo / ".env.example").write_text("DATABASE_URL=\nDEAD_UNUSED_VAR=\n", encoding="utf-8")
    (repo / "src" / "app.py").write_text(
        'import os\nDB = os.getenv("DATABASE_URL")\nFF = os.getenv("FEATURE_NEW_UI", "0")\nUNDOC = os.environ["MISSING_FROM_EXAMPLE"]\n',
        encoding="utf-8",
    )
    (repo / "core" / "frozen" / "hidden.py").write_text('X = os.getenv("FROZEN_ONLY_VAR")\n', encoding="utf-8")

    res = generate_config_matrix(repo, data_dir)
    names = {v["name"]: v for v in res["variables"]}
    assert "TOP_SECRET_REAL_ENV" not in names
    assert "FROZEN_ONLY_VAR" not in names
    assert names["DATABASE_URL"]["status"] == "OK"
    assert names["MISSING_FROM_EXAMPLE"]["status"] == "UNDOCUMENTED"
    assert names["DEAD_UNUSED_VAR"]["status"] == "UNUSED"
    assert names["FEATURE_NEW_UI"]["is_feature_flag"] is True
    assert (data_dir / "config-matrix.json").exists()


def test_iac_topology_docker_compose_nginx_and_gh_actions(tmp_path: Path):
    repo = tmp_path / "iac_repo"
    data_dir = tmp_path / "data"
    (repo / ".github" / "workflows").mkdir(parents=True)
    (repo / "Dockerfile").write_text("FROM python:latest\nEXPOSE 8000\nCMD [\"python\"]\n", encoding="utf-8")
    (repo / "docker-compose.yml").write_text(
        "services:\n  api:\n    image: myapp:1.0\n    ports:\n      - '8000:8000'\n    depends_on:\n      - db\n",
        encoding="utf-8",
    )
    (repo / "nginx.conf").write_text("server { listen 80; location / { proxy_pass http://127.0.0.1:8000; } }\n", encoding="utf-8")
    (repo / ".github" / "workflows" / "ci.yml").write_text("jobs:\n  test:\n    steps:\n      - uses: actions/checkout@v4\n", encoding="utf-8")

    res = generate_iac_topology(repo, data_dir)
    assert res["summary"]["dockerfiles"] == 1
    assert res["summary"]["compose_services"] == 1
    assert res["summary"]["nginx_configs"] == 1
    assert res["summary"]["ci_workflows"] == 1
    rules = {m["rule"] for m in res["misconfigs"]}
    assert {"DOCKER_UNPINNED_BASE", "DOCKER_ROOT_USER", "GHA_UNPINNED_ACTION"} <= rules


def test_ai_registry_models_prompts_and_guardrails(tmp_path: Path):
    repo = tmp_path / "llm_repo"
    data_dir = tmp_path / "data"
    repo.mkdir()
    (repo / "agent.py").write_text(
        '''from openai import OpenAI
MODEL = "gpt-4-0314"
SYSTEM_PROMPT = "You are a helpful architecture assistant with strict safety rules."
def bad(user_in: str):
    AGENT_PROMPT = f"Follow this user input: {user_in}"
    return AGENT_PROMPT
''',
        encoding="utf-8",
    )
    res = generate_ai_registry(repo, data_dir)
    assert "OpenAI" in res["summary"]["sdks_detected"]
    assert res["summary"]["unique_models_count"] == 1
    assert res["summary"]["prompts_cataloged"] == 1
    rules = {g["rule"] for g in res["guardrails"]}
    assert {"UNPINNED_OR_DEPRECATED_MODEL", "PROMPT_INJECTION_SURFACE"} <= rules


def test_compliance_evidence_and_mcp_codemode_parity(tmp_path: Path):
    repo = tmp_path / "comp_repo"
    data_dir = tmp_path / "data"
    (repo / ".github" / "workflows").mkdir(parents=True)
    data_dir.mkdir()
    (repo / "LICENSE").write_text("Apache-2.0\n", encoding="utf-8")
    (repo / "SECURITY.md").write_text("# Security\n", encoding="utf-8")
    (repo / ".github" / "CODEOWNERS").write_text("* @team\n", encoding="utf-8")
    (repo / ".github" / "workflows" / "ci.yml").write_text("name: CI\n", encoding="utf-8")
    (repo / "llms.txt").write_text("# App\n", encoding="utf-8")
    (data_dir / "sbom.cdx.json").write_text(json.dumps({"bomFormat": "CycloneDX", "specVersion": "1.5", "components": [{"name": "a"}]}), encoding="utf-8")
    (data_dir / "arch-health.json").write_text(json.dumps({"summary": {"cycle_count": 0}, "health_v4": {"owasp_audit": {"by_severity": {"CRITICAL": 0}}, "api_governance": {"unprotected_count": 0}, "observability": {"has_health_probe": True}, "supply_chain_and_ai": {"has_lockfile": True}}}), encoding="utf-8")

    ce = generate_compliance_evidence(repo, data_dir)
    assert ce["summary"]["overall_readiness_pct"] >= 90
    assert set(ce["frameworks"].keys()) == {"SOC2", "ISO27001", "EU_AI_ACT"}

    eng = PortalMcpEngine(project_dir=repo, data_dir=data_dir)
    rread = handle_jsonrpc_request(eng, {"jsonrpc": "2.0", "id": 99, "method": "resources/read", "params": {"uri": "portal://compliance"}})
    assert rread is not None and "SOC2" in rread["result"]["contents"][0]["text"]

    cm = execute_codemode(eng, "result = portal.compliance('SOC2')['summary']['overall_readiness_pct']")
    assert cm["ok"] is True and cm["result"] >= 90
