"""
Freshness SLA & Incremental File-Hash Cache (ADR-083 Sprint 1).
100% Python standard library, zero external dependencies.

Provides:
- Cached `git rev-parse --short HEAD` & branch lookup (1 call per run / TTL).
- `_meta` envelope injection (`schema_version`, `git_head_sha`, `git_branch`, `generated_at`).
- `FileHashCache` persisted as `.portal-cache.json` with atomic `0o644` writes.
- Strict exclusions for `.git`, `frozen/`, `.env*`, `node_modules`, and virtualenvs.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

_DEFAULT_IGNORE_DIRS: frozenset[str] = frozenset({
    ".git",
    ".hg",
    ".svn",
    "node_modules",
    "dist",
    "build",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".idea",
    ".vscode",
    "target",
    "vendor",
    "bin",
    "obj",
    "frozen",
    "archive",
    "graphify-out",
})

_GIT_CACHE_LOCK = threading.Lock()
_GIT_CACHE: dict[str, tuple[float, str, str]] = {}


def atomic_write_text(path: Path, content: str, mode: int = 0o644) -> None:
    """Atomically write UTF-8 text via temp file + chmod + os.replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent),
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
        try:
            os.chmod(tmp_path, mode)
        except OSError:
            pass
        os.replace(tmp_path, path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise


def clear_git_cache() -> None:
    """Reset the in-process git HEAD/branch cache."""
    with _GIT_CACHE_LOCK:
        _GIT_CACHE.clear()


def _probe_git_info(project_dir: Path, *, use_cache: bool = True, ttl_sec: float = 10.0) -> tuple[str, str]:
    key = str(project_dir.resolve())
    now = time.monotonic()
    if use_cache:
        with _GIT_CACHE_LOCK:
            cached = _GIT_CACHE.get(key)
            if cached is not None and (now - cached[0]) <= ttl_sec:
                return cached[1], cached[2]

    sha = "unknown"
    branch = "unknown"
    try:
        r_sha = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=key,
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        if r_sha.returncode == 0 and r_sha.stdout.strip():
            sha = r_sha.stdout.strip()
        r_br = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=key,
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        if r_br.returncode == 0 and r_br.stdout.strip():
            branch = r_br.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass

    with _GIT_CACHE_LOCK:
        _GIT_CACHE[key] = (now, sha, branch)
    return sha, branch


def get_git_head_sha(project_dir: Path, *, use_cache: bool = True, ttl_sec: float = 10.0) -> str:
    """Return short Git HEAD SHA for project_dir (cached per run/TTL)."""
    sha, _ = _probe_git_info(project_dir, use_cache=use_cache, ttl_sec=ttl_sec)
    return sha


def get_git_branch(project_dir: Path, *, use_cache: bool = True, ttl_sec: float = 10.0) -> str:
    """Return current Git branch name for project_dir (cached per run/TTL)."""
    _, branch = _probe_git_info(project_dir, use_cache=use_cache, ttl_sec=ttl_sec)
    return branch


def build_meta(
    project_dir: Path,
    *,
    schema_version: str = "1.0",
    generator_version: str = "adr-083",
    cache_hit: bool = False,
    git_head_sha: str | None = None,
    git_branch: str | None = None,
) -> dict[str, Any]:
    """Construct the standardized `_meta` freshness envelope."""
    sha = git_head_sha if git_head_sha is not None else get_git_head_sha(project_dir)
    branch = git_branch if git_branch is not None else get_git_branch(project_dir)
    return {
        "schema_version": schema_version,
        "git_head_sha": sha,
        "git_branch": branch,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generator_version": generator_version,
        "cache_hit": cache_hit,
    }


def stamp_meta(
    payload: dict[str, Any],
    project_dir: Path,
    *,
    schema_version: str = "1.0",
    generator_version: str = "adr-083",
    cache_hit: bool = False,
    git_head_sha: str | None = None,
    git_branch: str | None = None,
) -> dict[str, Any]:
    """Inject `_meta` envelope into a JSON-serializable dict payload."""
    payload["_meta"] = build_meta(
        project_dir,
        schema_version=schema_version,
        generator_version=generator_version,
        cache_hit=cache_hit,
        git_head_sha=git_head_sha,
        git_branch=git_branch,
    )
    return payload


def stamp_json_file(
    json_path: Path,
    project_dir: Path,
    *,
    schema_version: str = "1.0",
    generator_version: str = "adr-083",
    cache_hit: bool = False,
    git_head_sha: str | None = None,
    git_branch: str | None = None,
) -> bool:
    """Inject `_meta` into an existing JSON object file on disk atomically."""
    if not json_path.is_file():
        return False
    try:
        raw = json.loads(json_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return False
        stamp_meta(
            raw,
            project_dir,
            schema_version=schema_version,
            generator_version=generator_version,
            cache_hit=cache_hit,
            git_head_sha=git_head_sha,
            git_branch=git_branch,
        )
        atomic_write_text(json_path, json.dumps(raw, indent=2, ensure_ascii=False))
        return True
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return False


def _is_sensitive_or_excluded(rel_posix: str, fname: str) -> bool:
    low_name = fname.lower()
    if low_name.startswith(".env"):
        return True
    if low_name.endswith((".key", ".pem", ".p12", ".pfx", ".sqlite", ".db", ".pyc")):
        return True
    parts = rel_posix.lower().split("/")
    return any(p == "frozen" for p in parts)


class FileHashCache:
    """
    Incremental file-hash cache stored in `<cache_dir>/.portal-cache.json`.
    Computes deterministic per-group fingerprints using `(rel_path, size, mtime_ns, content_sha256_head)`
    so unchanged generator inputs are skipped in milliseconds.
    """

    CACHE_VERSION = "1.0"

    def __init__(self, cache_path: Path) -> None:
        self.cache_path = Path(cache_path)
        self._data: dict[str, Any] = {"version": self.CACHE_VERSION, "groups": {}, "git_head_sha": "unknown"}
        self._load()

    def _load(self) -> None:
        if not self.cache_path.is_file():
            return
        try:
            loaded = json.loads(self.cache_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict) and loaded.get("version") == self.CACHE_VERSION:
                groups = loaded.get("groups")
                if isinstance(groups, dict):
                    self._data = loaded
        except (OSError, json.JSONDecodeError):
            pass

    def compute_project_snapshot(
        self,
        project_dir: Path,
        *,
        extra_ignore_dirs: Iterable[str] = (),
    ) -> list[tuple[str, str, int, int, str]]:
        """
        Walk project_dir once and return sorted tuples:
        `(rel_posix, ext_lower, size, mtime_ns, sha256_16)`.
        Never reads `.env*` or `frozen/`.
        """
        root_dir = project_dir.resolve()
        ignore = set(_DEFAULT_IGNORE_DIRS) | set(extra_ignore_dirs)
        entries: list[tuple[str, str, int, int, str]] = []

        for cur_root, dirs, files in os.walk(root_dir):
            dirs[:] = sorted(
                d for d in dirs
                if d not in ignore and not d.startswith(".")
            )
            cur_path = Path(cur_root)
            for fname in sorted(files):
                fpath = cur_path / fname
                try:
                    rel = fpath.relative_to(root_dir).as_posix()
                except ValueError:
                    continue
                if _is_sensitive_or_excluded(rel, fname):
                    continue
                try:
                    st = fpath.stat()
                    h = hashlib.sha256()
                    with fpath.open("rb") as fh:
                        h.update(fh.read(4096))
                    digest = h.hexdigest()[:16]
                    ext = fpath.suffix.lower()
                    entries.append((rel, ext, st.st_size, st.st_mtime_ns, digest))
                except OSError:
                    continue
        return entries

    @staticmethod
    def hash_snapshot_bucket(
        snapshot: list[tuple[str, str, int, int, str]],
        *,
        extensions: set[str] | None = None,
        path_prefixes: tuple[str, ...] = (),
        filenames: set[str] | None = None,
        extra_salt: str = "",
    ) -> str:
        """Compute deterministic SHA-256 digest for a filtered subset of snapshot entries."""
        h = hashlib.sha256()
        if extra_salt:
            h.update(extra_salt.encode("utf-8"))
            h.update(b"\n")
        for rel, ext, size, mtime_ns, digest in snapshot:
            if path_prefixes and not rel.startswith(path_prefixes):
                continue
            matched = False
            if extensions is None and filenames is None:
                matched = True
            else:
                if extensions is not None and ext in extensions:
                    matched = True
                if not matched and filenames is not None and Path(rel).name.lower() in filenames:
                    matched = True
            if not matched:
                continue
            h.update(f"{rel}|{size}|{mtime_ns}|{digest}\n".encode("utf-8"))
        return h.hexdigest()

    def is_dirty(
        self,
        group_name: str,
        current_hash: str,
        required_outputs: Iterable[Path] = (),
    ) -> bool:
        """Return True if group hash changed or any required output file is missing."""
        stored = self._data.get("groups", {}).get(group_name)
        if not isinstance(stored, dict) or stored.get("hash") != current_hash:
            return True
        for out_p in required_outputs:
            if not out_p.is_file():
                return True
        return False

    def mark_clean(self, group_name: str, current_hash: str) -> None:
        groups = self._data.setdefault("groups", {})
        groups[group_name] = {
            "hash": current_hash,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

    def set_git_head_sha(self, sha: str) -> None:
        self._data["git_head_sha"] = sha

    def save(self) -> None:
        self._data["saved_at"] = datetime.now(timezone.utc).isoformat()
        atomic_write_text(self.cache_path, json.dumps(self._data, indent=2, sort_keys=True))
