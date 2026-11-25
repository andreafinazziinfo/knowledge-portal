"""Core utilities for Knowledge Portal (freshness SLA, incremental file-hash cache)."""

from knowledge_portal.core.freshness import (
    FileHashCache,
    atomic_write_text,
    build_meta,
    clear_git_cache,
    get_git_branch,
    get_git_head_sha,
    stamp_json_file,
    stamp_meta,
)

__all__ = [
    "FileHashCache",
    "atomic_write_text",
    "build_meta",
    "clear_git_cache",
    "get_git_branch",
    "get_git_head_sha",
    "stamp_json_file",
    "stamp_meta",
]
