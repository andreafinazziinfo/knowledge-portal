"""Unit tests for ADR-083 Sprint 1: Freshness SLA, FileHashCache, Parallel DAG Rebuild & FTS5 Client."""

from __future__ import annotations

import json
import threading
import time
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from knowledge_portal.core.freshness import (
    FileHashCache,
    build_meta,
    clear_git_cache,
    get_git_head_sha,
    stamp_json_file,
    stamp_meta,
)
from knowledge_portal.orchestrator import run_portal_rebuild
from knowledge_portal.server import PortalRequestHandler

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _seed_mini_project(root: Path) -> None:
    (root / "app").mkdir(parents=True, exist_ok=True)
    (root / "docs").mkdir(parents=True, exist_ok=True)
    (root / "frozen").mkdir(parents=True, exist_ok=True)
    (root / "app" / "main.py").write_text(
        '"""Entry module."""\nfrom app.service import compute\n\ndef run() -> int:\n    return compute(2)\n',
        encoding="utf-8",
    )
    (root / "app" / "service.py").write_text(
        '"""Service module."""\ndef compute(x: int) -> int:\n    return x * 2\n',
        encoding="utf-8",
    )
    (root / "docs" / "README.md").write_text("# Demo Architecture\nPortal freshness test.\n", encoding="utf-8")
    (root / "frozen" / "sealed.py").write_text("SECRET_SEAL = 1\n", encoding="utf-8")
    (root / ".env").write_text("DO_NOT_READ=1\n", encoding="utf-8")


def test_freshness_meta_envelope_and_git_sha(tmp_path: Path) -> None:
    clear_git_cache()
    sha = get_git_head_sha(REPO_ROOT, use_cache=True)
    assert isinstance(sha, str) and len(sha) >= 6 and sha != "unknown"

    meta = build_meta(REPO_ROOT)
    assert meta["schema_version"] == "1.0"
    assert meta["git_head_sha"] == sha
    assert "generated_at" in meta and "T" in meta["generated_at"]

    payload: dict[str, object] = {"summary": {"ok": True}}
    stamped = stamp_meta(payload, REPO_ROOT)
    assert stamped["_meta"]["git_head_sha"] == sha  # type: ignore[index]

    jf = tmp_path / "sample.json"
    jf.write_text(json.dumps({"hello": "world"}), encoding="utf-8")
    assert stamp_json_file(jf, REPO_ROOT) is True
    reloaded = json.loads(jf.read_text(encoding="utf-8"))
    assert reloaded["_meta"]["git_head_sha"] == sha
    assert reloaded["hello"] == "world"


def test_file_hash_cache_hit_miss_and_exclusions(tmp_path: Path) -> None:
    proj = tmp_path / "proj"
    _seed_mini_project(proj)
    cache_file = tmp_path / ".portal-cache.json"
    out_file = tmp_path / "out.json"
    out_file.write_text("{}", encoding="utf-8")

    cache = FileHashCache(cache_file)
    snap1 = cache.compute_project_snapshot(proj)
    rels = [entry[0] for entry in snap1]
    assert "app/main.py" in rels
    assert "docs/README.md" in rels
    # Must never index .env or frozen/
    assert not any(".env" in r for r in rels)
    assert not any("frozen/" in r for r in rels)

    h_code_1 = cache.hash_snapshot_bucket(snap1, extensions={".py"})
    h_docs_1 = cache.hash_snapshot_bucket(snap1, extensions={".md"})
    assert cache.is_dirty("code", h_code_1, [out_file]) is True
    cache.mark_clean("code", h_code_1)
    cache.mark_clean("docs", h_docs_1)
    cache.save()

    # Reload persisted cache -> both clean
    cache2 = FileHashCache(cache_file)
    snap2 = cache2.compute_project_snapshot(proj)
    assert cache2.is_dirty("code", cache2.hash_snapshot_bucket(snap2, extensions={".py"}), [out_file]) is False
    assert cache2.is_dirty("docs", cache2.hash_snapshot_bucket(snap2, extensions={".md"}), [out_file]) is False

    # Modify only a .py file -> code dirty, docs still clean!
    time.sleep(0.02)
    (proj / "app" / "service.py").write_text("def compute(x: int) -> int:\n    return x * 3\n", encoding="utf-8")
    snap3 = cache2.compute_project_snapshot(proj)
    assert cache2.is_dirty("code", cache2.hash_snapshot_bucket(snap3, extensions={".py"}), [out_file]) is True
    assert cache2.is_dirty("docs", cache2.hash_snapshot_bucket(snap3, extensions={".md"}), [out_file]) is False


def test_parallel_rebuild_cache_and_real_arch_diff(tmp_path: Path) -> None:
    proj = tmp_path / "proj"
    portal = tmp_path / "portal"
    data_dir = portal / "data"
    _seed_mini_project(proj)

    # Cold run (parallel, emit_js=False)
    cold = run_portal_rebuild(proj, data_dir, template_dir=portal, use_cache=True, parallel=True, max_workers=2, emit_js=False)
    assert cold["ok"] is True
    assert cold["cache_misses"] > 0
    assert (portal / ".portal-cache.json").is_file()
    assert (data_dir / "graph.json").is_file()
    assert (data_dir / "omni-search.fts.sqlite").is_file()
    # Redundant JS wrappers pruned, essential graph JS kept
    assert (data_dir / "graph_viz.js").is_file()
    assert not (data_dir / "api_catalog.js").is_file()

    # Verify _meta envelope injected into JSON artifacts
    for fname in ("graph.json", "api-catalog.json", "arch-health.json", "mission-control.json"):
        doc = json.loads((data_dir / fname).read_text(encoding="utf-8"))
        assert "_meta" in doc
        assert doc["_meta"]["schema_version"] == "1.0"
        assert "git_head_sha" in doc["_meta"]
        assert "generated_at" in doc["_meta"]

    # Warm run (no changes) -> 100% cache hits
    warm = run_portal_rebuild(proj, data_dir, template_dir=portal, use_cache=True, parallel=True, max_workers=2, emit_js=False)
    assert warm["ok"] is True
    assert warm["cache_misses"] == 0
    assert warm["cache_hits"] == cold["cache_misses"]

    # Add a new Python module -> graph-prev.json saved before overwrite -> real arch-diff!
    time.sleep(0.02)
    (proj / "app" / "extra.py").write_text("def extra_fn() -> int:\n    return 42\n", encoding="utf-8")
    inc = run_portal_rebuild(proj, data_dir, template_dir=portal, use_cache=True, parallel=True, max_workers=2, emit_js=False)
    assert inc["ok"] is True
    assert inc["steps"]["core_graph"]["cache_hit"] is False
    assert inc["steps"]["adr_graph"]["cache_hit"] is True  # docs unchanged!
    assert (data_dir / "graph-prev.json").is_file()
    diff = json.loads((data_dir / "arch-diff.json").read_text(encoding="utf-8"))
    added = diff.get("added_modules") or []
    assert any("extra.py" in str(m) for m in added)


def test_parallel_vs_sequential_deterministic_steps(tmp_path: Path) -> None:
    proj = tmp_path / "proj"
    _seed_mini_project(proj)
    d_par = tmp_path / "p_par" / "data"
    d_seq = tmp_path / "p_seq" / "data"

    r_par = run_portal_rebuild(proj, d_par, template_dir=d_par.parent, use_cache=False, parallel=True, max_workers=2, emit_js=False)
    r_seq = run_portal_rebuild(proj, d_seq, template_dir=d_seq.parent, use_cache=False, parallel=False, emit_js=False)

    assert list(r_par["steps"].keys()) == list(r_seq["steps"].keys())
    assert r_par["total_nodes"] == r_seq["total_nodes"]
    assert r_par["total_edges"] == r_seq["total_edges"]


def test_live_status_and_meta_head_endpoints(tmp_path: Path) -> None:
    tpl = tmp_path / "tpl"
    (tpl / "data").mkdir(parents=True)
    (tpl / "data" / "graph.json").write_text('{"nodes":[],"edges":[]}', encoding="utf-8")

    class _Handler(PortalRequestHandler):
        template_dir = tpl
        project_dir = REPO_ROOT

        def log_message(self, format: str, *args: object) -> None:
            return None

    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        expected_sha = get_git_head_sha(REPO_ROOT)
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/live-status", timeout=5) as resp:
            assert resp.status == 200
            ls = json.loads(resp.read().decode("utf-8"))
            assert ls["git_head_sha"] == expected_sha
            assert "server_time" in ls
            assert "graph" in ls["domains"]

        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/meta/head", timeout=5) as resp:
            assert resp.status == 200
            mh = json.loads(resp.read().decode("utf-8"))
            assert mh["git_head_sha"] == expected_sha
            assert "git_branch" in mh

        # Missing optional offline data/*.js wrapper returns 200 JS stub in HTTP mode (no 404 noise)
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/data/mission_control.js", timeout=5) as resp:
            assert resp.status == 200
            assert "javascript" in (resp.headers.get("Content-Type") or "")
            assert b"optional offline wrapper" in resp.read()
    finally:
        srv.shutdown()
        srv.server_close()


def test_ui_freshness_helper_and_fts5_dashboard_slimming() -> None:
    portal_ui = (REPO_ROOT / "template" / "views" / "portal-ui.js").read_text(encoding="utf-8")
    assert "checkFreshness" in portal_ui
    assert "PortalUI" in portal_ui
    assert "/api/live-status" in portal_ui
    assert "STALE" in portal_ui and "FRESH" in portal_ui

    dash = (REPO_ROOT / "template" / "dashboard.html").read_text(encoding="utf-8")
    assert "isHttpPortal" in dash
    assert "if (!isHttpPortal)" in dash
    assert "/api/search?q=" in dash
    assert "150" in dash
