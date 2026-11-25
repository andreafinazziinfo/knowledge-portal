"""ADR-083 Sprint 3 unit tests:
- Nginx rel-path parser + security headers + compliance-evidence
- Shell scripts (*.sh) parser (env names only, roles, infra commands)
- AndroidManifest.xml + build.gradle metadata in stack-ecosystem.json
- Protobuf (.proto) wire contract parser + portal_contract(kind="proto")
- Declarative .arch-rules.json Fitness Gate + CLI `gate` exit code
- CodeScene `codescene_risk` (churn x max_mccabe) & `hidden_temporal_coupling`
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from knowledge_portal.generators.arch_health import evaluate_arch_rules, generate_arch_health
from knowledge_portal.generators.audit_analyzers import analyze_git_crime_scene
from knowledge_portal.generators.audit_report import evaluate_quality_gate
from knowledge_portal.generators.compliance_evidence import generate_compliance_evidence
from knowledge_portal.generators.data_contracts import generate_data_contracts
from knowledge_portal.generators.iac_topology import generate_iac_topology
from knowledge_portal.generators.mission_control import generate_mission_control
from knowledge_portal.generators.stack_inventory import generate_stack_inventory
from knowledge_portal.mcp_server import PortalMcpEngine


def test_nginx_rel_path_parser_and_compliance_evidence(tmp_path: Path) -> None:
    proj = tmp_path / "proj"
    data = tmp_path / "data"
    nginx_dir = proj / "frontend" / "nginx"
    nginx_dir.mkdir(parents=True)

    (nginx_dir / "default.conf").write_text(
        """
upstream api_backend {
    server backend:8000;
}
server {
    listen 80;
    server_name example.local;
    include /etc/nginx/conf.d/security-headers.conf;
    location /api/ {
        proxy_pass http://api_backend;
    }
    location /assets/ {
        include /etc/nginx/conf.d/security-headers.conf;
        add_header Cache-Control "public, max-age=31536000";
        try_files $uri =404;
    }
    gzip on;
}
""",
        encoding="utf-8",
    )
    (nginx_dir / "security-headers.conf").write_text(
        """
add_header Content-Security-Policy "default-src 'self';" always;
add_header Strict-Transport-Security "max-age=63072000; includeSubDomains" always;
add_header X-Frame-Options "SAMEORIGIN" always;
add_header X-Content-Type-Options "nosniff" always;
""",
        encoding="utf-8",
    )

    iac = generate_iac_topology(proj, data)
    assert iac["summary"]["nginx_configs"] == 2
    assert iac["summary"]["nginx_locations_count"] == 2
    assert iac["summary"]["nginx_security_headers_count"] >= 4
    sec_hdrs = set(iac["nginx_security_headers"])
    assert {"Content-Security-Policy", "Strict-Transport-Security", "X-Frame-Options", "X-Content-Type-Options"} <= sec_hdrs

    default_entry = next(n for n in iac["nginx_proxies"] if n["file"].endswith("default.conf"))
    assert "80" in default_entry["listen"]
    assert "api_backend" in default_entry["upstreams"]
    assert any(loc["path"] == "/api/" for loc in default_entry["locations"])

    comp = generate_compliance_evidence(proj, data)
    assert comp["summary"]["nginx_configs"] == 2
    assert "Content-Security-Policy" in comp["summary"]["nginx_security_headers"]
    a89 = next(c for c in comp["controls"] if c["control_id"] == "A.8.9")
    assert "nginx_configs=2" in a89["evidence"]


def test_shell_scripts_parser_extracts_roles_cmds_and_env_names_only(tmp_path: Path) -> None:
    proj = tmp_path / "proj"
    data = tmp_path / "data"
    (proj / "scripts").mkdir(parents=True)

    (proj / "scripts" / "backup_db.sh").write_text(
        """#!/usr/bin/env bash
set -euo pipefail
pgbackrest --stanza=main backup
rclone sync /var/backups "$REMOTE_BUCKET_URL"
psql "$DATABASE_URL" -c "SELECT 1;"
""",
        encoding="utf-8",
    )
    (proj / "scripts" / "deploy_prod.sh").write_text(
        """#!/usr/bin/env bash
set -euo pipefail
docker compose up -d
systemctl reload nginx
curl -sf http://127.0.0.1:8000/health
""",
        encoding="utf-8",
    )

    iac = generate_iac_topology(proj, data)
    assert iac["summary"]["shell_scripts_count"] == 2
    assert iac["shell_scripts_count"] == 2
    sh_sum = iac["shell_scripts_summary"]
    assert sh_sum["strict_mode_count"] == 2
    assert sh_sum["by_role"]["backup"] == 1
    assert sh_sum["by_role"]["deploy"] == 1

    bkp = next(s for s in sh_sum["scripts"] if s["path"] == "scripts/backup_db.sh")
    assert "DATABASE_URL" in bkp["env_vars_referenced"]
    assert "REMOTE_BUCKET_URL" in bkp["env_vars_referenced"]
    assert {"pgbackrest", "rclone", "psql"} <= set(bkp["infra_commands"])


def test_android_manifest_and_gradle_metadata(tmp_path: Path) -> None:
    proj = tmp_path / "proj"
    data = tmp_path / "data"
    manifest_dir = proj / "mobile" / "android" / "app" / "src" / "main"
    manifest_dir.mkdir(parents=True)

    (manifest_dir / "AndroidManifest.xml").write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android">
    <application android:usesCleartextTraffic="true" android:allowBackup="false">
        <activity android:name=".MainActivity" android:exported="true" />
    </application>
    <uses-permission android:name="android.permission.INTERNET" />
    <uses-permission android:name="android.permission.ACCESS_NETWORK_STATE" />
</manifest>
""",
        encoding="utf-8",
    )
    (proj / "mobile" / "android" / "app" / "build.gradle").write_text(
        """
android {
    namespace = "com.example.mobile"
    defaultConfig {
        applicationId "com.example.mobile"
        versionCode 42
        versionName "2.3.1"
    }
    buildTypes {
        release {
            minifyEnabled true
        }
    }
}
dependencies {
    implementation "androidx.appcompat:appcompat:1.6.1"
    testImplementation "junit:junit:4.13.2"
}
""",
        encoding="utf-8",
    )

    stack = generate_stack_inventory(proj, data)
    assert stack["summary"]["mobile_manifests_count"] == 1
    mm = stack["mobile_manifest"]
    assert mm is not None
    assert mm["package"] == "com.example.mobile"
    assert mm["versionName"] == "2.3.1"
    assert mm["versionCode"] == 42
    assert mm["usesCleartextTraffic"] is True
    assert mm["permissions_count"] == 2
    assert "android.permission.INTERNET" in mm["permissions"]
    assert any(f["rule"] == "ANDROID_CLEARTEXT_TRAFFIC" for f in mm["security_findings"])


def test_proto_wire_contracts_and_mcp_portal_contract_proto(tmp_path: Path) -> None:
    proj = tmp_path / "proj"
    data = tmp_path / "data"
    proto_dir = proj / "proto"
    proto_dir.mkdir(parents=True)

    (proto_dir / "orders.proto").write_text(
        """
syntax = "proto3";
package acme.orders.v1;

import "common.proto";

enum OrderSide {
    ORDER_SIDE_UNSPECIFIED = 0;
    ORDER_SIDE_BUY = 1;
    ORDER_SIDE_SELL = 2;
}

message CreateOrderReq {
    string symbol = 1;
    OrderSide side = 2;
    double quantity = 3;
}

message CreateOrderRes {
    string order_id = 1;
    bool accepted = 2;
}

service OrderGateway {
    rpc CreateOrder (CreateOrderReq) returns (CreateOrderRes);
}
""",
        encoding="utf-8",
    )

    contracts = generate_data_contracts(proj, data)
    assert contracts["summary"]["proto_files_count"] == 1
    assert contracts["summary"]["proto_messages_count"] == 2
    assert contracts["summary"]["proto_enums_count"] == 1
    assert contracts["summary"]["proto_rpcs_count"] == 1
    assert contracts["proto_contracts"][0]["package"] == "acme.orders.v1"

    engine = PortalMcpEngine(project_dir=proj, data_dir=data)
    res = engine.contract(kind="proto", query="CreateOrder", detail="summary")
    assert res["summary"]["proto_messages_count"] == 2
    assert len(res["proto_contracts"]) == 1
    assert any(m["name"] == "CreateOrderReq" for m in res["proto_contracts"][0]["messages"])


def test_arch_rules_fitness_gate_and_cli_exit_code(tmp_path: Path) -> None:
    proj = tmp_path / "proj"
    data = tmp_path / "data"
    proj.mkdir()
    data.mkdir()

    graph = {
        "nodes": [
            {"id": "n1", "path": "app/domain/frozen/core.py"},
            {"id": "n2", "path": "app/api/routes.py"},
            {"id": "n3", "path": "app/services/bridge.py"},
        ],
        "edges": [
            {"source": "n1", "target": "n2"},
            {"source": "n3", "target": "n1"},
        ],
    }
    (data / "graph.json").write_text(json.dumps(graph), encoding="utf-8")

    # 1. Failing rule (ERROR severity)
    rules_fail = {
        "rules": [
            {
                "id": "no-frozen-reverse",
                "from": "app/domain/**/frozen/**",
                "forbid": "app/api/**",
                "severity": "ERROR",
                "message": "Frozen domain must not depend on API layer",
            }
        ]
    }
    (proj / ".arch-rules.json").write_text(json.dumps(rules_fail), encoding="utf-8")

    fg_fail = evaluate_arch_rules(graph, project_dir=proj)
    assert fg_fail["available"] is True
    assert fg_fail["rules_count"] == 1
    assert fg_fail["violations_count"] == 1
    assert fg_fail["errors_count"] == 1
    assert fg_fail["passed"] is False

    report = generate_arch_health(data, project_dir=proj)
    assert report["fitness_gate"]["passed"] is False
    ok, reasons = evaluate_quality_gate(report)
    assert ok is False
    assert any("no-frozen-reverse" in r for r in reasons)

    # Verify CLI `knowledge-portal gate` returns non-zero exit code
    proc_fail = subprocess.run(
        [sys.executable, "-m", "knowledge_portal.cli", "gate", "--dir", str(proj), "--data-dir", str(data)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc_fail.returncode != 0

    # 2. Passing rule (with allow_from)
    rules_pass = {
        "rules": [
            {
                "id": "only-bridge-to-frozen",
                "from": "**",
                "forbid": "app/domain/**/frozen/**",
                "allow_from": ["app/services/bridge.py"],
                "severity": "ERROR",
            }
        ]
    }
    (proj / ".arch-rules.json").write_text(json.dumps(rules_pass), encoding="utf-8")
    generate_arch_health(data, project_dir=proj)

    proc_pass = subprocess.run(
        [sys.executable, "-m", "knowledge_portal.cli", "gate", "--dir", str(proj), "--data-dir", str(data)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc_pass.returncode == 0


def test_codescene_risk_and_hidden_temporal_coupling(tmp_path: Path) -> None:
    proj = tmp_path / "repo"
    data = tmp_path / "data"
    proj.mkdir()
    data.mkdir()

    def _git(*args: str) -> None:
        subprocess.run(["git", "-C", str(proj), *args], check=True, capture_output=True, text=True)

    _git("init")
    _git("config", "user.email", "dev@example.com")
    _git("config", "user.name", "Dev One")

    (proj / "src").mkdir()
    (proj / "tests").mkdir()

    # Create 4 commits co-changing:
    # - src/a.py & src/b.py (NO direct import -> hidden temporal coupling!)
    # - src/a.py & src/c.py (DIRECT import in graph.json -> NOT hidden)
    # - src/a.py & tests/test_a.py (src<->test pair -> NOT hidden)
    for idx in range(4):
        (proj / "src" / "a.py").write_text(
            f"def calc(x):\n"
            f"    if x > {idx}:\n"
            f"        return x + 1\n"
            f"    elif x < 0:\n"
            f"        return -x\n"
            f"    return 0\n",
            encoding="utf-8",
        )
        (proj / "src" / "b.py").write_text(f"VAL = {idx}\n", encoding="utf-8")
        (proj / "src" / "c.py").write_text(f"OTHER = {idx}\n", encoding="utf-8")
        (proj / "tests" / "test_a.py").write_text(f"def test_ok(): assert {idx} >= 0\n", encoding="utf-8")
        _git("add", ".")
        _git("commit", "-m", f"commit {idx}")

    graph = {
        "nodes": [
            {"id": "src/a.py", "path": "src/a.py"},
            {"id": "src/b.py", "path": "src/b.py"},
            {"id": "src/c.py", "path": "src/c.py"},
        ],
        "edges": [
            {"source": "src/a.py", "target": "src/c.py"},
        ],
    }
    (data / "graph.json").write_text(json.dumps(graph), encoding="utf-8")

    cs = analyze_git_crime_scene(proj, days=90, graph_data=graph)
    assert cs["available"] is True
    assert cs["hotspots"], "Expected hotspots from 4 commits"
    for h in cs["hotspots"]:
        assert h["codescene_risk"] is not None
        assert h["codescene_risk"] >= 0
        assert h["max_mccabe"] >= 1
    hot_a = next(h for h in cs["hotspots"] if h["path"] == "src/a.py")
    assert hot_a["max_mccabe"] >= 3
    assert hot_a["codescene_risk"] == round(hot_a["lines_churned"] * hot_a["max_mccabe"], 1)

    hidden_pairs = {(p["file_a"], p["file_b"]) for p in cs["hidden_temporal_coupling"]}
    assert ("src/a.py", "src/b.py") in hidden_pairs
    assert ("src/a.py", "src/c.py") not in hidden_pairs
    assert ("src/a.py", "tests/test_a.py") not in hidden_pairs

    # Verify mission-control.json surfaces CodeScene summary
    generate_arch_health(data, project_dir=proj)
    mc = generate_mission_control(proj, data)
    assert mc["codescene_summary"]["available"] is True
    assert mc["codescene_summary"]["hidden_temporal_coupling_count"] >= 1
    assert mc["kpis"]["max_codescene_risk"] > 0
