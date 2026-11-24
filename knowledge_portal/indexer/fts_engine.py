"""
Zero-Dependency SQLite FTS5 Search Engine (BM25 + Prefix Matching).
Indexes omni-search-index.json (entities/items) and graph.json nodes into
omni-search.fts.sqlite with automatic mtime invalidation and read-only /tmp fallback.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import tempfile
import threading
from pathlib import Path
from typing import Any


class FtsSearchEngine:
    """Thread-safe SQLite FTS5 search index over Knowledge Portal JSON artifacts."""

    def __init__(self, data_dir: Path, extra_omni_path: Path | None = None) -> None:
        self.data_dir = data_dir.resolve()
        self.extra_omni_path = extra_omni_path.resolve() if extra_omni_path else None
        self._lock = threading.Lock()
        self._db_path: Path | None = None
        self._mem_conn: sqlite3.Connection | None = None
        self._last_sig: tuple[float, float] = (-1.0, -1.0)

    def _find_omni_file(self) -> Path | None:
        candidates = []
        if self.extra_omni_path:
            candidates.append(self.extra_omni_path)
        candidates.extend([
            self.data_dir / "omni-search-index.json",
            self.data_dir.parent / "views" / "data" / "omni-search-index.json",
        ])
        for p in candidates:
            if p.exists() and p.is_file():
                return p
        return None

    def _find_graph_file(self) -> Path | None:
        for p in (self.data_dir / "graph.json", self.data_dir.parent / "data" / "graph.json"):
            if p.exists() and p.is_file():
                return p
        return None

    def _resolve_db_path(self) -> Path | None:
        if self._db_path is not None:
            return self._db_path
        preferred = self.data_dir / "omni-search.fts.sqlite"
        try:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            test_file = self.data_dir / ".fts_write_test"
            test_file.write_text("1", encoding="utf-8")
            test_file.unlink(missing_ok=True)
            self._db_path = preferred
            return self._db_path
        except OSError:
            pass
        try:
            cache_dir = Path(tempfile.gettempdir()) / "portal_fts_cache"
            cache_dir.mkdir(parents=True, exist_ok=True)
            key = hashlib.sha256(str(self.data_dir).encode("utf-8")).hexdigest()[:12]
            self._db_path = cache_dir / f"omni-{key}.fts.sqlite"
            return self._db_path
        except OSError:
            return None

    def _open_conn(self) -> sqlite3.Connection:
        db_path = self._resolve_db_path()
        if db_path is not None:
            return sqlite3.connect(str(db_path), check_same_thread=False)
        if self._mem_conn is None:
            self._mem_conn = sqlite3.connect(":memory:", check_same_thread=False)
        return self._mem_conn

    def _ensure_index(self) -> sqlite3.Connection:
        omni_file = self._find_omni_file()
        graph_file = self._find_graph_file()
        omni_mt = os.path.getmtime(omni_file) if omni_file else 0.0
        graph_mt = os.path.getmtime(graph_file) if graph_file else 0.0
        sig = (omni_mt, graph_mt)

        conn = self._open_conn()
        if sig == self._last_sig and self._table_exists(conn):
            return conn

        self._rebuild(conn, omni_file, graph_file)
        self._last_sig = sig
        return conn

    @staticmethod
    def _table_exists(conn: sqlite3.Connection) -> bool:
        try:
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='fts_entities'"
            ).fetchone()
            return row is not None
        except sqlite3.Error:
            return False

    @staticmethod
    def _rebuild(conn: sqlite3.Connection, omni_file: Path | None, graph_file: Path | None) -> None:
        conn.execute("DROP TABLE IF EXISTS fts_entities")
        conn.execute(
            "CREATE VIRTUAL TABLE fts_entities USING fts5("
            "title, subtitle, search_text, id UNINDEXED, badge UNINDEXED, "
            "category UNINDEXED, tab UNINDEXED, hash UNINDEXED, action UNINDEXED, path UNINDEXED"
            ")"
        )
        rows: list[tuple[str, ...]] = []
        seen_titles: set[str] = set()

        if omni_file:
            try:
                raw = json.loads(omni_file.read_text(encoding="utf-8"))
                items = (
                    raw.get("entities") or raw.get("items") or []
                    if isinstance(raw, dict)
                    else (raw if isinstance(raw, list) else [])
                )
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    item_path = str(item.get("path") or "")
                    if any(seg.startswith(".") or seg == "frozen" for seg in item_path.replace("\\", "/").split("/") if seg):
                        continue
                    title = str(item.get("title") or item.get("name") or "").strip()
                    if not title or title == "---":
                        fallback_src = item_path or str(item.get("subtitle") or "")
                        if fallback_src:
                            title = Path(fallback_src).stem.replace("-", " ").replace("_", " ").title()
                    subtitle = str(item.get("subtitle") or "")
                    stext = str(item.get("search_text") or item.get("summary") or item.get("tags") or "")
                    rows.append((
                        title,
                        subtitle,
                        stext,
                        str(item.get("id") or title),
                        str(item.get("badge") or ""),
                        str(item.get("category") or "item"),
                        str(item.get("tab") or ""),
                        str(item.get("hash") or ""),
                        str(item.get("action") or ""),
                        str(item.get("path") or ""),
                    ))
                    if title:
                        seen_titles.add(title)
            except Exception:
                pass

        if graph_file:
            try:
                gdata = json.loads(graph_file.read_text(encoding="utf-8"))
                for node in gdata.get("nodes", []):
                    if not isinstance(node, dict):
                        continue
                    title = str(node.get("label") or node.get("name") or node.get("id") or "")
                    if not title or title in seen_titles:
                        continue
                    path = str(node.get("path") or "")
                    rows.append((
                        title,
                        path,
                        f"{node.get('type', 'node')} {path}",
                        str(node.get("id") or title),
                        "🔗",
                        str(node.get("type") or "node"),
                        "graph",
                        "",
                        "",
                        path,
                    ))
                    seen_titles.add(title)
            except Exception:
                pass

        if rows:
            conn.executemany(
                "INSERT INTO fts_entities(title, subtitle, search_text, id, badge, category, tab, hash, action, path) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                rows,
            )
        conn.commit()

    @staticmethod
    def _build_fts_query(query: str) -> str:
        tokens = [t for t in re.findall(r"[A-Za-z0-9_]+", query) if t]
        if not tokens:
            return ""
        return " AND ".join(f'"{t}"*' for t in tokens[:8])

    def search(self, query: str, limit: int = 30, expand_graph: bool = False) -> list[dict[str, Any]]:
        q = (query or "").strip()
        if not q:
            return []
        lim = max(1, min(int(limit or 30), 50))
        with self._lock:
            conn = self._ensure_index()
            fts_q = self._build_fts_query(q)
            rows = []
            if fts_q:
                try:
                    rows = conn.execute(
                        "SELECT id, title, subtitle, badge, category, tab, hash, action, path "
                        "FROM fts_entities WHERE fts_entities MATCH ? "
                        "ORDER BY bm25(fts_entities) LIMIT ?",
                        (fts_q, lim),
                    ).fetchall()
                except sqlite3.Error:
                    rows = []
            if not rows:
                like_q = f"%{q.lower()}%"
                rows = conn.execute(
                    "SELECT id, title, subtitle, badge, category, tab, hash, action, path "
                    "FROM fts_entities WHERE lower(title) LIKE ? OR lower(subtitle) LIKE ? OR lower(search_text) LIKE ? "
                    "LIMIT ?",
                    (like_q, like_q, like_q, lim),
                ).fetchall()
            if self._mem_conn is None:
                conn.close()

        results: list[dict[str, Any]] = [
            {
                "id": r[0],
                "name": r[1],
                "subtitle": r[2],
                "badge": r[3],
                "category": r[4],
                "tab": r[5],
                "hash": r[6],
                "action": r[7],
                "path": r[8],
            }
            for r in rows
        ]

        if expand_graph and results and len(results) < lim:
            graph_file = self._find_graph_file()
            if graph_file is not None:
                try:
                    g = json.loads(graph_file.read_text(encoding="utf-8"))
                    seeds = {str(r.get("path") or r.get("id") or "").lower() for r in results[:3] if r.get("path") or r.get("id")}
                    seen_paths = {str(r.get("path") or r.get("name") or "").lower() for r in results}
                    for e in g.get("edges") or g.get("links") or []:
                        if len(results) >= lim:
                            break
                        if not isinstance(e, dict):
                            continue
                        s = str(e.get("source", "")).replace("\\", "/")
                        t = str(e.get("target", "")).replace("\\", "/")
                        neighbor = ""
                        if s.lower() in seeds and t.lower() not in seen_paths:
                            neighbor = t
                        elif t.lower() in seeds and s.lower() not in seen_paths:
                            neighbor = s
                        if neighbor and "frozen/" not in neighbor.lower():
                            seen_paths.add(neighbor.lower())
                            results.append({
                                "id": neighbor,
                                "name": Path(neighbor).name,
                                "subtitle": "1-hop graph neighbor",
                                "badge": "GRAPH",
                                "category": "graph-neighbor",
                                "tab": "reader",
                                "hash": "",
                                "action": "openFile",
                                "path": neighbor,
                                "graph_expanded": True,
                            })
                except Exception:
                    pass

        return results
