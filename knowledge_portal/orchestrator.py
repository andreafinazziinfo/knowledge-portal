"""
Parallel 3-Wave DAG Rebuild Orchestrator with Incremental File-Hash Cache (ADR-083 Sprint 1).
100% Python standard library, zero external dependencies.

Waves:
  - Wave A (Core Graph & Search): save graph-prev.json -> PolyglotScanner -> omni-search-index.json + FTS5 SQLite
  - Wave B (Parallel Independent Generators): ThreadPoolExecutor(max_workers=min(4, cpu_count))
  - Wave C (Aggregators & Synthesis): vertical_slices -> arch_health -> compliance -> mission_control -> llms_txt
"""

from __future__ import annotations

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable

from knowledge_portal.core.freshness import (
    FileHashCache,
    atomic_write_text,
    clear_git_cache,
    get_git_branch,
    get_git_head_sha,
    stamp_json_file,
)

# Legacy graph views still load these via <script src="../data/*.js">; keep them even when emit_js=False.
_ESSENTIAL_JS_FILES: frozenset[str] = frozenset({
    "config.js",
    "graph_viz.js",
    "graph_labels.js",
    "process_flows.js",
    "views_manifest.js",
})

_CODE_EXTS: set[str] = {".py", ".ts", ".tsx", ".js", ".jsx", ".vue", ".go", ".rs", ".java", ".cs", ".rb", ".php"}
_DOC_EXTS: set[str] = {".md", ".mdx", ".rst", ".txt"}
_CONFIG_EXTS: set[str] = {".yml", ".yaml", ".json", ".toml", ".ini", ".cfg", ".conf", ".env.example"}
_SQL_EXTS: set[str] = {".sql"}
_DEP_FILENAMES: set[str] = {
    "pyproject.toml",
    "requirements.txt",
    "package.json",
    "package-lock.json",
    "cargo.toml",
    "go.mod",
    "dockerfile",
    "docker-compose.yml",
    "docker-compose.yaml",
    "compose.yml",
    "compose.yaml",
}


def save_prev_graph_snapshot(data_dir: Path) -> bool:
    """Save compact graph-prev.json snapshot BEFORE overwriting graph.json so arch-diff is real."""
    curr = data_dir / "graph.json"
    if not curr.is_file():
        return False
    try:
        g = json.loads(curr.read_text(encoding="utf-8"))
        mods = sorted({
            str(n.get("path") or n.get("id") or "").replace("\\", "/")
            for n in (g.get("nodes") or [])
            if isinstance(n, dict)
            and (n.get("path") or n.get("id"))
            and "frozen/" not in str(n.get("path") or "").lower()
        })
        edges = [
            {"source": str(e.get("source", "")), "target": str(e.get("target", ""))}
            for e in (g.get("edges") or g.get("links") or [])
            if isinstance(e, dict) and e.get("source") and e.get("target")
        ]
        atomic_write_text(
            data_dir / "graph-prev.json",
            json.dumps({"saved_at": time.time(), "modules": mods, "edges": edges}),
        )
        return True
    except (OSError, json.JSONDecodeError, TypeError):
        return False


def prune_optional_js_wrappers(data_dir: Path) -> int:
    """Remove redundant window.*_DATA .js wrappers when emit_js=False (keeps essential graph .js)."""
    removed = 0
    if not data_dir.is_dir():
        return 0
    for f in data_dir.glob("*.js"):
        if f.name in _ESSENTIAL_JS_FILES:
            continue
        try:
            f.unlink()
            removed += 1
        except OSError:
            pass
    return removed


def _stamp_outputs(
    outputs: list[Path],
    project_dir: Path,
    *,
    git_head_sha: str,
    git_branch: str,
    cache_hit: bool = False,
) -> None:
    for p in outputs:
        if p.suffix.lower() == ".json" and p.is_file():
            stamp_json_file(
                p,
                project_dir,
                git_head_sha=git_head_sha,
                git_branch=git_branch,
                cache_hit=cache_hit,
            )


def _needs_meta_refresh(outputs: list[Path], git_head_sha: str) -> bool:
    for p in outputs:
        if p.suffix.lower() != ".json" or not p.is_file():
            continue
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                meta = raw.get("_meta")
                if not isinstance(meta, dict) or meta.get("git_head_sha") != git_head_sha:
                    return True
        except (OSError, json.JSONDecodeError):
            return True
    return False


def run_portal_rebuild(
    project_dir: Path,
    data_dir: Path,
    *,
    template_dir: Path | None = None,
    classic: bool = False,
    use_cache: bool = True,
    parallel: bool = True,
    max_workers: int | None = None,
    emit_js: bool = False,
    project_name: str | None = None,
) -> dict[str, Any]:
    """
    Execute the full 3-Wave DAG portal rebuild with incremental file-hash caching and `_meta` stamping.
    """
    t0 = time.perf_counter()
    project_dir = Path(project_dir).resolve()
    data_dir = Path(data_dir).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    portal_root = Path(template_dir).resolve() if template_dir else data_dir.parent

    clear_git_cache()
    git_sha = get_git_head_sha(project_dir, use_cache=True)
    git_branch = get_git_branch(project_dir, use_cache=True)

    cache = FileHashCache(portal_root / ".portal-cache.json")
    snapshot = cache.compute_project_snapshot(project_dir)

    workers = max(1, min(int(max_workers or min(4, os.cpu_count() or 2)), 8)) if parallel else 1

    steps_meta: dict[str, dict[str, Any]] = {}
    cache_hits = 0
    cache_misses = 0

    # Pre-compute bucket hashes deterministically
    h_code = cache.hash_snapshot_bucket(snapshot, extensions=_CODE_EXTS | _SQL_EXTS)
    h_docs = cache.hash_snapshot_bucket(snapshot, extensions=_DOC_EXTS)
    h_cfg = cache.hash_snapshot_bucket(snapshot, extensions=_CONFIG_EXTS, filenames=_DEP_FILENAMES)
    h_all = cache.hash_snapshot_bucket(snapshot)
    h_git = cache.hash_snapshot_bucket(snapshot, extra_salt=f"git:{git_sha}:{git_branch}")

    def _run_step(
        name: str,
        wave: str,
        bucket_hash: str,
        required_outputs: list[Path],
        fn: Callable[[], Any],
        *,
        force: bool = False,
    ) -> tuple[bool, Any]:
        nonlocal cache_hits, cache_misses
        st0 = time.perf_counter()
        if use_cache and not force and not cache.is_dirty(name, bucket_hash, required_outputs):
            if _needs_meta_refresh(required_outputs, git_sha):
                _stamp_outputs(
                    required_outputs,
                    project_dir,
                    git_head_sha=git_sha,
                    git_branch=git_branch,
                    cache_hit=True,
                )
            elapsed = round(time.perf_counter() - st0, 4)
            steps_meta[name] = {"wave": wave, "cache_hit": True, "elapsed_sec": elapsed}
            cache_hits += 1
            return False, None

        res = fn()
        _stamp_outputs(
            required_outputs,
            project_dir,
            git_head_sha=git_sha,
            git_branch=git_branch,
            cache_hit=False,
        )
        cache.mark_clean(name, bucket_hash)
        elapsed = round(time.perf_counter() - st0, 4)
        steps_meta[name] = {"wave": wave, "cache_hit": False, "elapsed_sec": elapsed}
        cache_misses += 1
        return True, res

    # ── WAVE A: Core Graph + Search Index + FTS5 ──────────────────────────────
    def _wave_a_scan() -> dict[str, Any]:
        save_prev_graph_snapshot(data_dir)
        if classic:
            from knowledge_portal.scanner.python_ast import scan_codebase
            return scan_codebase(project_dir, data_dir)
        from knowledge_portal.scanner.polyglot import scan_polyglot_codebase
        return scan_polyglot_codebase(project_dir, data_dir)

    scan_outputs = [
        data_dir / "graph.json",
        data_dir / "db-schema.json",
        data_dir / "process-flows.json",
        data_dir / "views-manifest.json",
    ]
    scan_dirty, scan_stats = _run_step("core_graph", "A", h_code, scan_outputs, _wave_a_scan)

    def _wave_a_search() -> int:
        from knowledge_portal.indexer.fts_engine import FtsSearchEngine
        from knowledge_portal.indexer.search_index import generate_search_index

        omni_file = data_dir / "omni-search-index.json"
        cnt = generate_search_index(project_dir, omni_file)
        fts = FtsSearchEngine(data_dir)
        fts.search("portal", limit=1)
        return cnt

    search_outputs = [data_dir / "omni-search-index.json", data_dir / "omni-search.fts.sqlite"]
    _, indexed_docs = _run_step(
        "search_fts",
        "A",
        f"{h_docs}:{h_code}",
        search_outputs,
        _wave_a_search,
        force=scan_dirty,
    )

    # ── WAVE B: Parallel Independent Generators ───────────────────────────────
    from knowledge_portal.generators.adr_graph import generate_adr_graph
    from knowledge_portal.generators.agent_instructions_audit import generate_agent_instructions_audit
    from knowledge_portal.generators.ai_registry import generate_ai_registry
    from knowledge_portal.generators.api_catalog import generate_api_catalog
    from knowledge_portal.generators.async_topology import generate_async_topology
    from knowledge_portal.generators.call_graph import generate_call_graph
    from knowledge_portal.generators.config_matrix import generate_config_matrix
    from knowledge_portal.generators.cve_ingestor import generate_cve_report
    from knowledge_portal.generators.data_contracts import generate_data_contracts
    from knowledge_portal.generators.git_dag import generate_git_dag
    from knowledge_portal.generators.iac_topology import generate_iac_topology
    from knowledge_portal.generators.module_cards import generate_module_cards
    from knowledge_portal.generators.ownership import generate_ownership_map
    from knowledge_portal.generators.runtime_modes import generate_runtime_modes
    from knowledge_portal.generators.sarif_ingestor import generate_sarif_findings
    from knowledge_portal.generators.stack_inventory import generate_stack_inventory
    from knowledge_portal.generators.test_oracle import generate_test_oracle

    wave_b_specs: list[tuple[str, str, list[Path], Callable[[], Any]]] = [
        ("stack_inventory", h_cfg, [data_dir / "stack-ecosystem.json"], lambda: generate_stack_inventory(project_dir, data_dir)),
        ("cve_report", h_cfg, [data_dir / "cve-report.json"], lambda: generate_cve_report(project_dir, data_dir)),
        ("sarif_findings", h_cfg, [data_dir / "sarif-findings.json"], lambda: generate_sarif_findings(project_dir, data_dir)),
        ("api_catalog", h_code, [data_dir / "api-catalog.json"], lambda: generate_api_catalog(project_dir, data_dir)),
        ("call_graph", h_code, [data_dir / "call-graph.json", data_dir / "dead-code.json"], lambda: generate_call_graph(project_dir, data_dir)),
        ("async_topology", h_code, [data_dir / "async-topology.json"], lambda: generate_async_topology(project_dir, data_dir)),
        ("data_contracts", h_code, [data_dir / "data-contracts.json"], lambda: generate_data_contracts(project_dir, data_dir)),
        ("runtime_modes", h_code, [data_dir / "runtime-modes.json"], lambda: generate_runtime_modes(project_dir, data_dir)),
        ("ownership", h_all, [data_dir / "ownership.json"], lambda: generate_ownership_map(project_dir, data_dir)),
        ("config_matrix", f"{h_cfg}:{h_code}", [data_dir / "config-matrix.json"], lambda: generate_config_matrix(project_dir, data_dir)),
        ("iac_topology", h_cfg, [data_dir / "iac-topology.json"], lambda: generate_iac_topology(project_dir, data_dir)),
        ("ai_registry", f"{h_code}:{h_docs}", [data_dir / "ai-registry.json"], lambda: generate_ai_registry(project_dir, data_dir)),
        ("git_dag", h_git, [data_dir / "git-dag.json"], lambda: generate_git_dag(project_dir, data_dir)),
        ("adr_graph", h_docs, [data_dir / "adr-graph.json"], lambda: generate_adr_graph(project_dir, data_dir)),
        ("test_oracle", h_code, [data_dir / "test-oracle.json"], lambda: generate_test_oracle(project_dir, data_dir)),
        ("module_cards", h_code, [data_dir / "module-cards.json"], lambda: generate_module_cards(project_dir, data_dir)),
        ("agent_instructions_audit", h_docs, [data_dir / "agent-instructions-audit.json"], lambda: generate_agent_instructions_audit(project_dir, data_dir)),
    ]

    wave_b_dirty = False
    wave_b_results: dict[str, tuple[bool, float]] = {}

    def _exec_wave_b(spec: tuple[str, str, list[Path], Callable[[], Any]]) -> tuple[str, bool, float]:
        name, bhash, req_out, fn = spec
        st0 = time.perf_counter()
        if use_cache and not cache.is_dirty(name, bhash, req_out):
            if _needs_meta_refresh(req_out, git_sha):
                _stamp_outputs(req_out, project_dir, git_head_sha=git_sha, git_branch=git_branch, cache_hit=True)
            return name, False, round(time.perf_counter() - st0, 4)
        fn()
        _stamp_outputs(req_out, project_dir, git_head_sha=git_sha, git_branch=git_branch, cache_hit=False)
        return name, True, round(time.perf_counter() - st0, 4)

    if workers > 1:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futs = {pool.submit(_exec_wave_b, spec): spec for spec in wave_b_specs}
            for fut in as_completed(futs):
                name, ran, elapsed = fut.result()
                wave_b_results[name] = (ran, elapsed)
    else:
        for spec in wave_b_specs:
            name, ran, elapsed = _exec_wave_b(spec)
            wave_b_results[name] = (ran, elapsed)

    # Record Wave B results in deterministic spec order
    for name, bhash, _req_out, _fn in wave_b_specs:
        ran, elapsed = wave_b_results[name]
        steps_meta[name] = {"wave": "B", "cache_hit": not ran, "elapsed_sec": elapsed}
        if ran:
            cache.mark_clean(name, bhash)
            cache_misses += 1
            wave_b_dirty = True
        else:
            cache_hits += 1

    # ── WAVE C: Aggregators & Synthesis ───────────────────────────────────────
    from knowledge_portal.generators.arch_health import generate_arch_health
    from knowledge_portal.generators.compliance_evidence import generate_compliance_evidence
    from knowledge_portal.generators.llms_txt import generate_llms_manifests
    from knowledge_portal.generators.mission_control import generate_mission_control
    from knowledge_portal.generators.vertical_slices import generate_vertical_slices

    vs_dirty, _ = _run_step(
        "vertical_slices",
        "C",
        h_code,
        [data_dir / "vertical-slices.json"],
        lambda: generate_vertical_slices(project_dir, data_dir),
        force=scan_dirty or wave_b_results.get("api_catalog", (False, 0.0))[0] or wave_b_results.get("call_graph", (False, 0.0))[0],
    )
    ah_dirty, _ = _run_step(
        "arch_health",
        "C",
        f"{h_code}:{git_sha}",
        [data_dir / "arch-health.json", data_dir / "arch-diff.json"],
        lambda: generate_arch_health(data_dir, project_dir=project_dir),
        force=scan_dirty,
    )
    ce_dirty, _ = _run_step(
        "compliance_evidence",
        "C",
        f"{h_cfg}:{h_code}",
        [data_dir / "compliance-evidence.json"],
        lambda: generate_compliance_evidence(project_dir, data_dir),
        force=ah_dirty or wave_b_results.get("iac_topology", (False, 0.0))[0],
    )
    any_upstream_dirty = scan_dirty or wave_b_dirty or vs_dirty or ah_dirty or ce_dirty
    mc_dirty, _ = _run_step(
        "mission_control",
        "C",
        f"{h_all}:{git_sha}",
        [data_dir / "mission-control.json"],
        lambda: generate_mission_control(project_dir, data_dir),
        force=any_upstream_dirty,
    )
    _run_step(
        "llms_txt",
        "C",
        f"{h_all}:{git_sha}",
        [portal_root / "llms.txt", portal_root / "llms-full.txt"],
        lambda: generate_llms_manifests(project_dir, data_dir, portal_root, project_name=project_name),
        force=any_upstream_dirty or mc_dirty,
    )

    pruned_js = 0
    if not emit_js:
        pruned_js = prune_optional_js_wrappers(data_dir)

    cache.set_git_head_sha(git_sha)
    cache.save()

    total_elapsed = round(time.perf_counter() - t0, 3)
    graph_stats: dict[str, Any] = scan_stats if isinstance(scan_stats, dict) else {}
    if not graph_stats and (data_dir / "graph.json").is_file():
        try:
            g = json.loads((data_dir / "graph.json").read_text(encoding="utf-8"))
            nodes = g.get("nodes") or []
            graph_stats = {
                "total_files": len({n.get("path") for n in nodes if isinstance(n, dict) and n.get("path")}),
                "total_nodes": len(nodes),
                "total_edges": len(g.get("edges") or g.get("links") or []),
            }
        except (OSError, json.JSONDecodeError):
            graph_stats = {"total_files": 0, "total_nodes": 0, "total_edges": 0}

    return {
        "ok": True,
        "elapsed_sec": total_elapsed,
        "git_head_sha": git_sha,
        "git_branch": git_branch,
        "workers": workers,
        "parallel": parallel,
        "use_cache": use_cache,
        "emit_js": emit_js,
        "pruned_js": pruned_js,
        "cache_hits": cache_hits,
        "cache_misses": cache_misses,
        "total_files": graph_stats.get("total_files", 0),
        "total_nodes": graph_stats.get("total_nodes", 0),
        "total_edges": graph_stats.get("total_edges", 0),
        "indexed_docs": indexed_docs or 0,
        "steps": steps_meta,
    }
