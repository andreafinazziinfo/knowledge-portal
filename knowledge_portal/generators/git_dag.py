"""
Knowledge Portal — Git Worktree Hygiene & Stacked-PR DAG Generator (ADR-081).
100% Python stdlib zero-dependency scanner extracting:
- Active Git worktrees (`git worktree list --porcelain`) with clean/dirty/detached/stale/locked hygiene status
- Local branch inventory (`git for-each-ref`) with stale & merged-candidate detection
- Optional open PRs via `gh pr list --json ...` with 100% safe offline fallback
- Stacked-PR / stacked-branch topological DAG & recommended Merge Order
- GitHub Actions workflow inventory (`.github/workflows/*.yml`)

Outputs `data/git-dag.json` and `data/git_dag.js`.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess  # nosec B404
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

STALE_DAYS_THRESHOLD = 14


def _run_cmd(cmd: list[str], cwd: Path, timeout: float = 5.0) -> tuple[int, str, str]:
    """Run an external read-only CLI command safely without shell interpolation."""
    try:
        proc = subprocess.run(  # nosec B603
            cmd,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,
            check=False,
        )
        return proc.returncode, proc.stdout or "", proc.stderr or ""
    except (OSError, subprocess.SubprocessError):
        return 1, "", ""


def _detect_default_branch(git_bin: str, project_dir: Path) -> str:
    rc, out, _ = _run_cmd([git_bin, "symbolic-ref", "--short", "refs/remotes/origin/HEAD"], project_dir)
    if rc == 0 and out.strip():
        ref = out.strip()
        return ref.split("/", 1)[-1] if "/" in ref else ref
    for cand in ("main", "master"):
        rc, _, _ = _run_cmd([git_bin, "show-ref", "--verify", "--quiet", f"refs/heads/{cand}"], project_dir)
        if rc == 0:
            return cand
    rc, out, _ = _run_cmd([git_bin, "rev-parse", "--abbrev-ref", "HEAD"], project_dir)
    if rc == 0 and out.strip() and out.strip() != "HEAD":
        return out.strip()
    return "main"


def _parse_worktrees_porcelain(raw: str) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    cur: dict[str, Any] = {}
    for line in raw.splitlines():
        line = line.rstrip("\r\n")
        if not line.strip():
            if cur:
                entries.append(cur)
                cur = {}
            continue
        if line.startswith("worktree "):
            cur["raw_path"] = line[len("worktree "):].strip()
        elif line.startswith("HEAD "):
            cur["head"] = line[len("HEAD "):].strip()
        elif line.startswith("branch "):
            ref = line[len("branch "):].strip()
            cur["branch"] = ref[len("refs/heads/"):] if ref.startswith("refs/heads/") else ref
        elif line == "detached":
            cur["detached"] = True
        elif line == "bare":
            cur["bare"] = True
        elif line.startswith("locked"):
            cur["locked"] = True
            cur["lock_reason"] = line[len("locked"):].strip()
        elif line.startswith("prunable"):
            cur["prunable"] = True
            cur["prunable_reason"] = line[len("prunable"):].strip()
    if cur:
        entries.append(cur)
    return entries


def _inspect_worktrees(git_bin: str, project_dir: Path, max_inspect: int = 120) -> list[dict[str, Any]]:
    rc, out, _ = _run_cmd([git_bin, "worktree", "list", "--porcelain"], project_dir, timeout=6.0)
    if rc != 0 or not out.strip():
        return []

    raw_entries = _parse_worktrees_porcelain(out)[:max_inspect]
    now_ts = time.time()
    worktrees: list[dict[str, Any]] = []

    for idx, item in enumerate(raw_entries):
        raw_path = str(item.get("raw_path", ""))
        wt_path = Path(raw_path) if raw_path else project_dir
        name = wt_path.name or f"worktree-{idx + 1}"
        detached = bool(item.get("detached", False))
        bare = bool(item.get("bare", False))
        locked = bool(item.get("locked", False))
        prunable = bool(item.get("prunable", False))
        branch = str(item.get("branch") or ("HEAD (detached)" if detached else ("(bare)" if bare else "")))
        head = str(item.get("head", ""))[:12]

        dirty = False
        modified_count = 0
        last_commit_ts = 0
        last_commit_iso = ""
        age_days: int | None = None

        if not bare and not prunable and wt_path.exists():
            st_rc, st_out, _ = _run_cmd([git_bin, "-C", str(wt_path), "status", "--porcelain"], project_dir, timeout=2.5)
            if st_rc == 0:
                changed = [ln for ln in st_out.splitlines() if ln.strip()]
                modified_count = len(changed)
                dirty = modified_count > 0

            ts_rc, ts_out, _ = _run_cmd([git_bin, "-C", str(wt_path), "log", "-1", "--format=%ct"], project_dir, timeout=2.0)
            if ts_rc == 0 and ts_out.strip().isdigit():
                last_commit_ts = int(ts_out.strip())
                last_commit_iso = datetime.fromtimestamp(last_commit_ts, tz=timezone.utc).isoformat()
                age_days = max(0, int((now_ts - last_commit_ts) // 86400))

        stale = prunable or (age_days is not None and age_days >= STALE_DAYS_THRESHOLD)
        if prunable:
            status = "stale"
        elif detached:
            status = "detached"
        elif locked:
            status = "locked"
        elif dirty:
            status = "dirty"
        elif stale:
            status = "stale"
        else:
            status = "clean"

        is_primary = False
        try:
            is_primary = wt_path.resolve() == project_dir.resolve()
        except OSError:
            pass

        worktrees.append({
            "name": name,
            "branch": branch,
            "head": head,
            "is_primary": is_primary,
            "detached": detached,
            "bare": bare,
            "locked": locked,
            "prunable": prunable,
            "dirty": dirty,
            "modified_files": modified_count,
            "stale": stale,
            "age_days": age_days,
            "last_commit_at": last_commit_iso,
            "status": status,
        })

    return worktrees


def _inspect_branches(git_bin: str, project_dir: Path, default_branch: str) -> list[dict[str, Any]]:
    fmt = "%(refname:short)|%(objectname:short)|%(committerdate:unix)|%(upstream:short)|%(HEAD)"
    rc, out, _ = _run_cmd([git_bin, "for-each-ref", f"--format={fmt}", "refs/heads"], project_dir, timeout=5.0)
    if rc != 0 or not out.strip():
        return []

    merged_set: set[str] = set()
    mrc, mout, _ = _run_cmd([git_bin, "branch", "--merged", default_branch, "--format=%(refname:short)"], project_dir, timeout=4.0)
    if mrc == 0:
        merged_set = {ln.strip() for ln in mout.splitlines() if ln.strip()}

    now_ts = time.time()
    branches: list[dict[str, Any]] = []
    for line in out.splitlines():
        parts = line.split("|")
        if len(parts) < 5:
            continue
        name, sha, ts_raw, upstream, head_flag = parts[0], parts[1], parts[2], parts[3], parts[4]
        ts_int = int(ts_raw) if ts_raw.isdigit() else 0
        age_days = max(0, int((now_ts - ts_int) // 86400)) if ts_int > 0 else None
        last_iso = datetime.fromtimestamp(ts_int, tz=timezone.utc).isoformat() if ts_int > 0 else ""
        is_default = name == default_branch
        stale = (not is_default) and (age_days is not None and age_days >= STALE_DAYS_THRESHOLD)
        branches.append({
            "name": name,
            "sha": sha,
            "upstream": upstream,
            "is_current": head_flag.strip() == "*",
            "is_default": is_default,
            "merged_into_default": (not is_default) and (name in merged_set),
            "age_days": age_days,
            "stale": stale,
            "last_commit_at": last_iso,
        })

    branches.sort(key=lambda b: (not b["is_default"], not b["is_current"], b["name"]))
    return branches


def _normalize_ci_status(rollup: Any) -> str:
    if not isinstance(rollup, list) or not rollup:
        return "unknown"
    conclusions: list[str] = []
    states: list[str] = []
    for item in rollup:
        if not isinstance(item, dict):
            continue
        c = str(item.get("conclusion") or "").upper()
        s = str(item.get("status") or item.get("state") or "").upper()
        if c:
            conclusions.append(c)
        if s:
            states.append(s)
    if any(c in ("FAILURE", "ERROR", "TIMED_OUT", "CANCELLED", "ACTION_REQUIRED") for c in conclusions):
        return "red"
    if any(s in ("IN_PROGRESS", "QUEUED", "PENDING", "EXPECTED") for s in states):
        return "pending"
    if conclusions and all(c in ("SUCCESS", "NEUTRAL", "SKIPPED") for c in conclusions):
        return "green"
    return "unknown"


def _fetch_open_prs(project_dir: Path, include_gh: bool = True) -> tuple[bool, list[dict[str, Any]]]:
    if not include_gh:
        return False, []
    gh_bin = shutil.which("gh")
    if not gh_bin:
        return False, []
    fields = "number,title,headRefName,baseRefName,state,isDraft,additions,deletions,statusCheckRollup,url,updatedAt"
    rc, out, _ = _run_cmd(
        [gh_bin, "pr", "list", "--state", "open", "--limit", "50", "--json", fields],
        project_dir,
        timeout=6.0,
    )
    if rc != 0 or not out.strip():
        return False, []
    try:
        raw = json.loads(out)
    except json.JSONDecodeError:
        return False, []
    if not isinstance(raw, list):
        return False, []

    prs: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        is_draft = bool(item.get("isDraft", False))
        ci = "draft" if is_draft else _normalize_ci_status(item.get("statusCheckRollup"))
        prs.append({
            "number": int(item.get("number", 0)),
            "title": str(item.get("title", "")),
            "head": str(item.get("headRefName", "")),
            "base": str(item.get("baseRefName", "")),
            "state": str(item.get("state", "OPEN")),
            "is_draft": is_draft,
            "additions": int(item.get("additions", 0) or 0),
            "deletions": int(item.get("deletions", 0) or 0),
            "ci_status": ci,
            "url": str(item.get("url", "")),
            "updated_at": str(item.get("updatedAt", "")),
        })
    prs.sort(key=lambda p: p["number"])
    return True, prs


def build_stacked_dag(
    open_prs: list[dict[str, Any]],
    branches: list[dict[str, Any]],
    default_branch: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Compute DAG nodes, edges, stacked chains, and topological merge order."""
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    stacked_chains: list[dict[str, Any]] = []
    merge_order: list[dict[str, Any]] = []

    if open_prs:
        by_head: dict[str, dict[str, Any]] = {p["head"]: p for p in open_prs if p.get("head")}
        children: dict[str, list[dict[str, Any]]] = defaultdict(list)
        roots: list[dict[str, Any]] = []

        nodes.append({
            "id": f"branch:{default_branch}",
            "label": default_branch,
            "kind": "base",
            "depth": 0,
            "ci_status": "green",
        })

        for pr in open_prs:
            base = pr.get("base") or default_branch
            if base in by_head:
                children[base].append(pr)
                edges.append({
                    "source": f"pr:{by_head[base]['number']}",
                    "target": f"pr:{pr['number']}",
                    "relation": "stacked_on",
                })
            else:
                roots.append(pr)
                edges.append({
                    "source": f"branch:{default_branch}",
                    "target": f"pr:{pr['number']}",
                    "relation": "targets",
                })

        # BFS topological depth & merge order
        depth_map: dict[int, int] = {}
        queue: deque[tuple[dict[str, Any], int]] = deque((r, 1) for r in sorted(roots, key=lambda x: x["number"]))
        visited: set[int] = set()
        while queue:
            pr, depth = queue.popleft()
            num = pr["number"]
            if num in visited:
                continue
            visited.add(num)
            depth_map[num] = depth
            nodes.append({
                "id": f"pr:{num}",
                "label": f"#{num} {pr['title'][:42]}",
                "number": num,
                "head": pr["head"],
                "base": pr["base"],
                "kind": "pr",
                "depth": depth,
                "ci_status": pr["ci_status"],
                "is_draft": pr["is_draft"],
                "additions": pr["additions"],
                "deletions": pr["deletions"],
            })
            merge_order.append({
                "step": len(merge_order) + 1,
                "pr_number": num,
                "title": pr["title"],
                "head": pr["head"],
                "base": pr["base"],
                "depth": depth,
                "ci_status": pr["ci_status"],
            })
            for ch in sorted(children.get(pr["head"], []), key=lambda x: x["number"]):
                queue.append((ch, depth + 1))

        # Build stacked chains (any root that has descendants)
        def _collect_chain(pr_item: dict[str, Any]) -> list[int]:
            res = [pr_item["number"]]
            for ch in sorted(children.get(pr_item["head"], []), key=lambda x: x["number"]):
                res.extend(_collect_chain(ch))
            return res

        for r in sorted(roots, key=lambda x: x["number"]):
            chain_nums = _collect_chain(r)
            if len(chain_nums) >= 2:
                stacked_chains.append({
                    "root_pr": r["number"],
                    "base_branch": r["base"],
                    "length": len(chain_nums),
                    "prs": chain_nums,
                })
    else:
        # Offline fallback: build DAG from local branches relative to default_branch
        nodes.append({
            "id": f"branch:{default_branch}",
            "label": default_branch,
            "kind": "base",
            "depth": 0,
            "ci_status": "green",
        })
        for br in branches:
            if br["is_default"]:
                continue
            nid = f"branch:{br['name']}"
            status = "stale" if br["stale"] else ("merged" if br["merged_into_default"] else "active")
            nodes.append({
                "id": nid,
                "label": br["name"],
                "kind": "branch",
                "depth": 1,
                "ci_status": status,
                "sha": br["sha"],
                "stale": br["stale"],
                "merged_into_default": br["merged_into_default"],
            })
            edges.append({
                "source": f"branch:{default_branch}",
                "target": nid,
                "relation": "branch_of",
            })

    return nodes, edges, stacked_chains, merge_order


def _scan_workflows(project_dir: Path) -> list[dict[str, Any]]:
    wf_dir = project_dir / ".github" / "workflows"
    if not wf_dir.is_dir():
        return []
    workflows: list[dict[str, Any]] = []
    name_re = re.compile(r"^name:\s*(.+)$", re.MULTILINE)
    on_re = re.compile(r"\b(push|pull_request|workflow_dispatch|schedule|release)\b")
    for wf in sorted(wf_dir.iterdir()):
        if not wf.is_file() or wf.suffix.lower() not in (".yml", ".yaml"):
            continue
        try:
            text = wf.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        m_name = name_re.search(text)
        wf_name = m_name.group(1).strip().strip("\"'") if m_name else wf.stem
        triggers = sorted(set(on_re.findall(text)))
        workflows.append({
            "name": wf_name,
            "file": f".github/workflows/{wf.name}",
            "triggers": triggers,
        })
    return workflows


def generate_git_dag(
    project_dir: Path,
    output_dir: Path | None = None,
    *,
    include_gh: bool = True,
) -> dict[str, Any]:
    """Generate Git Worktree Hygiene Matrix & Stacked-PR DAG artifact."""
    project_dir = Path(project_dir).resolve()
    git_bin = shutil.which("git")
    generated_at = datetime.now(tz=timezone.utc).isoformat()

    is_git_repo = False
    default_branch = "main"
    current_branch = ""
    head_sha = ""
    worktrees: list[dict[str, Any]] = []
    branches: list[dict[str, Any]] = []
    gh_available = False
    open_prs: list[dict[str, Any]] = []

    if git_bin:
        rc, out, _ = _run_cmd([git_bin, "rev-parse", "--is-inside-work-tree"], project_dir)
        is_git_repo = rc == 0 and out.strip().lower() == "true"

    if is_git_repo and git_bin:
        default_branch = _detect_default_branch(git_bin, project_dir)
        rc_b, out_b, _ = _run_cmd([git_bin, "rev-parse", "--abbrev-ref", "HEAD"], project_dir)
        current_branch = out_b.strip() if rc_b == 0 else ""
        rc_s, out_s, _ = _run_cmd([git_bin, "rev-parse", "--short", "HEAD"], project_dir)
        head_sha = out_s.strip() if rc_s == 0 else ""
        worktrees = _inspect_worktrees(git_bin, project_dir)
        branches = _inspect_branches(git_bin, project_dir, default_branch)
        gh_available, open_prs = _fetch_open_prs(project_dir, include_gh=include_gh)

    nodes, edges, stacked_chains, merge_order = build_stacked_dag(open_prs, branches, default_branch)
    workflows = _scan_workflows(project_dir)

    summary = {
        "is_git_repo": is_git_repo,
        "total_worktrees": len(worktrees),
        "clean_worktrees": sum(1 for w in worktrees if w["status"] == "clean"),
        "dirty_worktrees": sum(1 for w in worktrees if w["dirty"]),
        "detached_worktrees": sum(1 for w in worktrees if w["detached"]),
        "stale_worktrees": sum(1 for w in worktrees if w["stale"]),
        "locked_worktrees": sum(1 for w in worktrees if w["locked"]),
        "total_branches": len(branches),
        "stale_branches": sum(1 for b in branches if b["stale"]),
        "merged_branches": sum(1 for b in branches if b["merged_into_default"]),
        "open_prs_count": len(open_prs),
        "stacked_chains_count": len(stacked_chains),
        "workflows_count": len(workflows),
        "gh_available": gh_available,
    }

    payload: dict[str, Any] = {
        "schema_version": "1.0",
        "generated_at": generated_at,
        "default_branch": default_branch,
        "current_branch": current_branch,
        "head_sha": head_sha,
        "summary": summary,
        "worktrees": worktrees,
        "branches": branches,
        "open_prs": open_prs,
        "nodes": nodes,
        "edges": edges,
        "stacked_chains": stacked_chains,
        "merge_order": merge_order,
        "workflows": workflows,
    }

    if output_dir is not None:
        out_path = Path(output_dir)
        out_path.mkdir(parents=True, exist_ok=True)
        (out_path / "git-dag.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        (out_path / "git_dag.js").write_text(
            f"window.GIT_DAG = {json.dumps(payload, ensure_ascii=False)};\n",
            encoding="utf-8",
        )

    return payload
