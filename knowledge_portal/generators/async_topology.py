"""
ADR-082 Wave 2 (AI-4): Async / WebSocket / Redis / Celery Topology Generator (100% Python stdlib).

Extracts via AST + multi-pattern scanning (Python + TypeScript/Vue):
  1. Celery Tasks (@celery_app.task, @shared_task, queue, rate_limit, soft_time_limit,
     max_retries, autoretry_for, producers via .delay()/.apply_async()/.send_task())
  2. Celery Beat Schedules (AST parsing of beat_schedule = {...})
  3. Redis Keys & Distributed Locks (set/get/hset/delete/lock/setnx, key pattern, TTL,
     producers & consumers)
  4. Redis Pub/Sub Channels (.publish <-> .subscribe/.psubscribe)
  5. WebSocket & SSE Streams (@router.websocket, StreamingResponse text/event-stream
     <-> frontend new WebSocket / new EventSource)

Writes:
  - <data_dir>/async-topology.json
  - <data_dir>/async_topology.js (window.ASYNC_TOPOLOGY_DATA)
"""

from __future__ import annotations

import ast
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    "dist",
    "dev-dist",
    "build",
    "coverage",
    "vendor",
    "graphify-out",
    "knowledge_portal",
    ".next",
    ".nuxt",
    "htmlcov",
    "tests",
    "test",
}

FE_EXTENSIONS = {".vue", ".ts", ".tsx", ".js", ".jsx"}

_REDIS_WRITE_METHODS = {
    "set", "setex", "psetex", "setnx", "hset", "hmset", "lpush", "rpush",
    "sadd", "zadd", "incr", "decr", "expire", "delete", "unlink",
}
_REDIS_READ_METHODS = {
    "get", "mget", "hget", "hgetall", "lrange", "smembers", "zrange", "exists", "ttl",
}
_REDIS_LOCK_METHODS = {"lock"}
_REDIS_RECEIVER_HINTS = ("redis", "cache", "rc", "broker", "client")

_FE_WS_RE = re.compile(r"""new\s+WebSocket\s*\(\s*([^)\n]{1,180})\)""")
_FE_SSE_RE = re.compile(r"""new\s+EventSource\s*\(\s*([^)\n]{1,180})\)""")
_URL_PATH_EXTRACT_RE = re.compile(r"""(/api(?:/v\d+)?/[^'"`\s?)]+|/ws/[^'"`\s?)]+)""")


def _walk_source_files(project_dir: Path, extensions: set[str], include_tests: bool = False) -> list[Path]:
    results: list[Path] = []
    skip = SKIP_DIRS - {"tests", "test"} if include_tests else SKIP_DIRS
    for root, dirs, files in os.walk(project_dir):
        dirs[:] = [d for d in dirs if d not in skip and not d.startswith(".")]
        for fname in files:
            p = Path(root) / fname
            if p.suffix.lower() not in extensions:
                continue
            low = fname.lower()
            if any(low.endswith(s) for s in (".min.js", ".d.ts", ".generated.ts", ".spec.ts", ".test.ts")):
                continue
            if not include_tests and (low.startswith("test_") or low.endswith("_test.py")):
                continue
            results.append(p)
    return sorted(results)


def _eval_str_expr(node: ast.AST | None, local_consts: dict[str, str], global_consts: dict[str, str]) -> str | None:
    """Resolve a Python AST expression into a string pattern (f-strings become `*` wildcards)."""
    if node is None:
        return None
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return local_consts.get(node.id) or global_consts.get(node.id)
    if isinstance(node, ast.Attribute):
        return local_consts.get(node.attr) or global_consts.get(node.attr)
    if isinstance(node, ast.JoinedStr):
        parts: list[str] = []
        for val in node.values:
            if isinstance(val, ast.Constant) and isinstance(val.value, str):
                parts.append(val.value)
            elif isinstance(val, ast.FormattedValue):
                resolved = _eval_str_expr(val.value, local_consts, global_consts)
                if resolved and ":" not in resolved and len(resolved) < 32 and not resolved.startswith("{"):
                    parts.append(resolved)
                else:
                    parts.append("*")
        joined = "".join(parts)
        return joined if joined and joined != "*" else None
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _eval_str_expr(node.left, local_consts, global_consts)
        right = _eval_str_expr(node.right, local_consts, global_consts)
        if left and right:
            return left + right
        if left:
            return left + "*"
        if right:
            return "*" + right
    return None


def _eval_scalar(node: ast.AST | None) -> Any:
    if node is None:
        return None
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, (ast.Tuple, ast.List)):
        vals = [_eval_scalar(elt) for elt in node.elts]
        return [v for v in vals if v is not None]
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return ast.unparse(node)
    if isinstance(node, ast.Call):
        return ast.unparse(node)
    try:
        return ast.unparse(node)
    except Exception:
        return None


def _is_celery_task_decorator(dec: ast.AST) -> tuple[bool, dict[str, Any]]:
    """Return (is_task, kwargs) for @celery_app.task(...), @shared_task(...), etc."""
    func_node = dec.func if isinstance(dec, ast.Call) else dec
    is_task = False
    if isinstance(func_node, ast.Name) and func_node.id in ("shared_task", "task"):
        is_task = True
    elif isinstance(func_node, ast.Attribute) and func_node.attr in ("task", "shared_task"):
        is_task = True
    if not is_task:
        return False, {}

    meta: dict[str, Any] = {}
    if isinstance(dec, ast.Call):
        for kw in dec.keywords:
            if kw.arg:
                meta[kw.arg] = _eval_scalar(kw.value)
    return True, meta


def _is_redis_receiver(node: ast.AST) -> bool:
    """Heuristic check if an attribute call target looks like a Redis client."""
    try:
        src = ast.unparse(node).lower()
    except Exception:
        return False
    if src in ("r", "rc", "redis", "redis_client", "cache", "pubsub"):
        return True
    if any(h in src for h in _REDIS_RECEIVER_HINTS):
        return True
    return False


def _format_beat_schedule(node: ast.AST) -> str:
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)):
            return f"every {node.value}s"
        return str(node.value)
    try:
        return ast.unparse(node)
    except Exception:
        return "custom"


def _extract_beat_schedules(tree: ast.AST, rel_path: str) -> list[dict[str, Any]]:
    schedules: list[dict[str, Any]] = []

    def _parse_dict(dnode: ast.Dict, line: int) -> None:
        for k_node, v_node in zip(dnode.keys, dnode.values):
            if not isinstance(k_node, ast.Constant) or not isinstance(k_node.value, str):
                continue
            if not isinstance(v_node, ast.Dict):
                continue
            entry: dict[str, Any] = {
                "name": k_node.value,
                "task": "",
                "schedule": "",
                "queue": "default",
                "file": rel_path,
                "line": getattr(k_node, "lineno", line),
            }
            for ek, ev in zip(v_node.keys, v_node.values):
                if not isinstance(ek, ast.Constant) or not isinstance(ek.value, str):
                    continue
                if ek.value == "task":
                    val = _eval_scalar(ev)
                    entry["task"] = str(val) if val is not None else ""
                elif ek.value == "schedule":
                    entry["schedule"] = _format_beat_schedule(ev)
                elif ek.value == "options" and isinstance(ev, ast.Dict):
                    for ok, ov in zip(ev.keys, ev.values):
                        if isinstance(ok, ast.Constant) and ok.value == "queue":
                            q = _eval_scalar(ov)
                            if q:
                                entry["queue"] = str(q)
            if entry["task"] or entry["schedule"]:
                schedules.append(entry)

    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Dict):
            for tgt in node.targets:
                tname = ast.unparse(tgt) if isinstance(tgt, (ast.Name, ast.Attribute)) else ""
                if "beat_schedule" in tname:
                    _parse_dict(node.value, node.lineno)
        elif isinstance(node, ast.Call):
            for kw in node.keywords:
                if kw.arg == "beat_schedule" and isinstance(kw.value, ast.Dict):
                    _parse_dict(kw.value, node.lineno)
    return schedules


def _extract_ws_and_sse_python(tree: ast.AST, rel_path: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    ws_streams: list[dict[str, Any]] = []
    sse_streams: list[dict[str, Any]] = []

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue

        route_path = ""
        is_ws = False
        for dec in node.decorator_list:
            if not isinstance(dec, ast.Call):
                continue
            fn = dec.func
            attr = fn.attr if isinstance(fn, ast.Attribute) else ""
            if attr == "websocket":
                is_ws = True
                if dec.args and isinstance(dec.args[0], ast.Constant) and isinstance(dec.args[0].value, str):
                    route_path = dec.args[0].value
            elif attr in ("get", "post", "put", "patch", "delete", "api_route"):
                if dec.args and isinstance(dec.args[0], ast.Constant) and isinstance(dec.args[0].value, str):
                    route_path = dec.args[0].value

        if is_ws:
            ws_streams.append(
                {
                    "path": route_path or f"/ws/{node.name}",
                    "handler": node.name,
                    "file": rel_path,
                    "line": node.lineno,
                    "protocol": "websocket",
                    "consumers": [],
                }
            )
            continue

        # Detect SSE via StreamingResponse(..., media_type="text/event-stream") or EventSourceResponse
        is_sse = False
        for sub in ast.walk(node):
            if not isinstance(sub, ast.Call):
                continue
            cname = sub.func.id if isinstance(sub.func, ast.Name) else (
                sub.func.attr if isinstance(sub.func, ast.Attribute) else ""
            )
            if cname == "EventSourceResponse":
                is_sse = True
                break
            if cname == "StreamingResponse":
                for kw in sub.keywords:
                    if kw.arg == "media_type" and isinstance(kw.value, ast.Constant):
                        if "event-stream" in str(kw.value.value).lower():
                            is_sse = True
                            break
                if is_sse:
                    break
        if is_sse:
            sse_streams.append(
                {
                    "path": route_path or f"/sse/{node.name}",
                    "handler": node.name,
                    "file": rel_path,
                    "line": node.lineno,
                    "protocol": "sse",
                    "consumers": [],
                }
            )

    return ws_streams, sse_streams


def _normalize_ws_or_sse_path(raw: str) -> str:
    m = _URL_PATH_EXTRACT_RE.search(raw)
    path = m.group(1) if m else raw.strip(" '\"`")
    path = re.sub(r"""\$\{[^}]+\}""", "{param}", path)
    path = re.sub(r"""\{[^}]+\}""", "{param}", path)
    return path.split("?", 1)[0]


def generate_async_topology(project_dir: Path, data_dir: Path) -> dict[str, Any]:
    """Scan Python & Frontend sources for async/event-driven topology and write JSON + JS."""
    project_dir = Path(project_dir).resolve()
    data_dir = Path(data_dir).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)

    py_files = _walk_source_files(project_dir, {".py"})

    # Pass 1: collect global string constants (e.g. *_CHANNEL, *_KEY, *_LOCK, *_PREFIX)
    global_consts: dict[str, str] = {}
    parsed_trees: list[tuple[str, ast.Module, dict[str, str]]] = []

    for fpath in py_files:
        rel = fpath.relative_to(project_dir).as_posix()
        try:
            text = fpath.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(text)
        except (OSError, SyntaxError):
            continue

        local_consts: dict[str, str] = {}
        for stmt in tree.body:
            if isinstance(stmt, ast.Assign) and isinstance(stmt.value, ast.Constant) and isinstance(stmt.value.value, str):
                for tgt in stmt.targets:
                    if isinstance(tgt, ast.Name):
                        local_consts[tgt.id] = stmt.value.value
                        if tgt.id.isupper() or any(
                            k in tgt.id.upper() for k in ("CHANNEL", "TOPIC", "LOCK", "KEY", "PREFIX", "QUEUE", "STREAM")
                        ):
                            global_consts[tgt.id] = stmt.value.value
            elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                if isinstance(stmt.value, ast.Constant) and isinstance(stmt.value.value, str):
                    local_consts[stmt.target.id] = stmt.value.value
                    if stmt.target.id.isupper():
                        global_consts[stmt.target.id] = stmt.value.value
        parsed_trees.append((rel, tree, local_consts))

    # Pass 2: extract Celery tasks, Beat schedules, producers, Redis keys/locks, Pub/Sub, WS/SSE
    celery_tasks: list[dict[str, Any]] = []
    task_by_fn: dict[str, dict[str, Any]] = {}
    task_by_name: dict[str, dict[str, Any]] = {}
    beat_schedules: list[dict[str, Any]] = []
    raw_producers: list[dict[str, Any]] = []

    redis_keys_map: dict[str, dict[str, Any]] = {}
    pubsub_map: dict[str, dict[str, Any]] = {}
    ws_streams: list[dict[str, Any]] = []
    sse_streams: list[dict[str, Any]] = []

    for rel, tree, local_consts in parsed_trees:
        beat_schedules.extend(_extract_beat_schedules(tree, rel))
        file_ws, file_sse = _extract_ws_and_sse_python(tree, rel)
        ws_streams.extend(file_ws)
        sse_streams.extend(file_sse)

        # Build parent function context map for accurate attribution
        func_spans: list[tuple[int, int, str]] = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                end_line = getattr(node, "end_lineno", node.lineno) or node.lineno
                func_spans.append((node.lineno, end_line, node.name))

                # Check Celery task decorators
                for dec in node.decorator_list:
                    is_task, meta = _is_celery_task_decorator(dec)
                    if is_task:
                        t_name = str(meta.get("name") or node.name)
                        t_entry: dict[str, Any] = {
                            "name": t_name,
                            "function": node.name,
                            "file": rel,
                            "line": node.lineno,
                            "queue": str(meta.get("queue") or "default"),
                            "rate_limit": meta.get("rate_limit"),
                            "soft_time_limit": meta.get("soft_time_limit"),
                            "time_limit": meta.get("time_limit"),
                            "max_retries": meta.get("max_retries"),
                            "autoretry_for": meta.get("autoretry_for"),
                            "bind": bool(meta.get("bind", False)),
                            "producers": [],
                        }
                        celery_tasks.append(t_entry)
                        task_by_fn[node.name] = t_entry
                        task_by_name[t_name] = t_entry
                        break

        def _enclosing_fn(lineno: int) -> str:
            best = "<module>"
            best_span = 10**9
            for start, end, fname in func_spans:
                if start <= lineno <= end and (end - start) < best_span:
                    best = fname
                    best_span = end - start
            return best

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            attr = node.func.attr
            lineno = node.lineno
            caller_fn = _enclosing_fn(lineno)

            # A. Celery task producers (.delay, .apply_async, .send_task)
            if attr in ("delay", "apply_async"):
                target_expr = ast.unparse(node.func.value)
                target_fn = target_expr.split(".")[-1]
                if target_fn not in ("workflow", "chain", "group", "chord", "sig", "signature"):
                    raw_producers.append(
                        {
                            "target": target_fn,
                            "call": attr,
                            "file": rel,
                            "line": lineno,
                            "function": caller_fn,
                        }
                    )
            elif attr == "send_task" and node.args:
                tname = _eval_str_expr(node.args[0], local_consts, global_consts)
                if tname:
                    raw_producers.append(
                        {
                            "target": tname,
                            "call": "send_task",
                            "file": rel,
                            "line": lineno,
                            "function": caller_fn,
                        }
                    )

            # B. Redis Pub/Sub (.publish, .subscribe, .psubscribe)
            elif attr in ("publish", "subscribe", "psubscribe") and node.args:
                ch = _eval_str_expr(node.args[0], local_consts, global_consts)
                if not ch:
                    # Fallback to variable name if descriptive
                    arg0 = node.args[0]
                    if isinstance(arg0, ast.Name) and any(
                        k in arg0.id.lower() for k in ("chan", "topic", "stream", "pattern")
                    ):
                        ch = f"<{arg0.id}>"
                if ch:
                    rec = pubsub_map.setdefault(
                        ch,
                        {
                            "channel": ch,
                            "pattern": attr == "psubscribe" or "*" in ch,
                            "publishers": [],
                            "subscribers": [],
                        },
                    )
                    ref = {"file": rel, "line": lineno, "function": caller_fn}
                    if attr == "publish":
                        if ref not in rec["publishers"]:
                            rec["publishers"].append(ref)
                    else:
                        if attr == "psubscribe":
                            rec["pattern"] = True
                        if ref not in rec["subscribers"]:
                            rec["subscribers"].append(ref)

            # C. Redis Keys & Distributed Locks
            elif (
                attr in (_REDIS_WRITE_METHODS | _REDIS_READ_METHODS | _REDIS_LOCK_METHODS)
                and node.args
                and _is_redis_receiver(node.func.value)
            ):
                key_pat = _eval_str_expr(node.args[0], local_consts, global_consts)
                if not key_pat or len(key_pat) < 2 or len(key_pat) > 120:
                    continue
                if " " in key_pat or key_pat.startswith("http"):
                    continue

                # Determine TTL and lock semantics
                ttl: Any = None
                is_lock = attr in _REDIS_LOCK_METHODS or "lock" in key_pat.lower()
                if attr == "setex" and len(node.args) >= 2:
                    ttl = _eval_scalar(node.args[1])
                elif attr == "expire" and len(node.args) >= 2:
                    ttl = _eval_scalar(node.args[1])
                for kw in node.keywords:
                    if kw.arg in ("ex", "px", "timeout"):
                        ttl = _eval_scalar(kw.value)
                    if kw.arg == "nx" and isinstance(kw.value, ast.Constant) and kw.value.value is True:
                        is_lock = True

                rec = redis_keys_map.setdefault(
                    key_pat,
                    {
                        "key_pattern": key_pat,
                        "kind": "lock" if is_lock else "key",
                        "ttl": ttl,
                        "operations": [],
                        "producers": [],
                        "consumers": [],
                    },
                )
                if is_lock:
                    rec["kind"] = "lock"
                if ttl is not None and rec["ttl"] is None:
                    rec["ttl"] = ttl
                if attr not in rec["operations"]:
                    rec["operations"].append(attr)

                ref = {"file": rel, "line": lineno, "function": caller_fn, "op": attr}
                if attr in _REDIS_READ_METHODS:
                    if ref not in rec["consumers"]:
                        rec["consumers"].append(ref)
                else:
                    if ref not in rec["producers"]:
                        rec["producers"].append(ref)

    # Link producers to Celery tasks
    for prod in raw_producers:
        tgt = prod["target"]
        task = task_by_name.get(tgt) or task_by_fn.get(tgt)
        if task is not None:
            ref = {"file": prod["file"], "line": prod["line"], "function": prod["function"], "call": prod["call"]}
            if ref not in task["producers"]:
                task["producers"].append(ref)

    # Pass 3: Scan Frontend for WebSocket / EventSource consumers
    fe_files = _walk_source_files(project_dir, FE_EXTENSIONS)
    fe_ws_consumers: list[dict[str, Any]] = []
    fe_sse_consumers: list[dict[str, Any]] = []

    for fpath in fe_files:
        rel = fpath.relative_to(project_dir).as_posix()
        try:
            content = fpath.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for m in _FE_WS_RE.finditer(content):
            line = content.count("\n", 0, m.start()) + 1
            norm_p = _normalize_ws_or_sse_path(m.group(1))
            fe_ws_consumers.append({"file": rel, "line": line, "url": norm_p})
        for m in _FE_SSE_RE.finditer(content):
            line = content.count("\n", 0, m.start()) + 1
            norm_p = _normalize_ws_or_sse_path(m.group(1))
            fe_sse_consumers.append({"file": rel, "line": line, "url": norm_p})

    for ws in ws_streams:
        ws_norm = _normalize_ws_or_sse_path(ws["path"])
        ws_seg = ws_norm.strip("/").split("/")[-1] if ws_norm else ""
        for c in fe_ws_consumers:
            if ws_norm and (ws_norm in c["url"] or (ws_seg and ws_seg != "{param}" and ws_seg in c["url"])):
                ws["consumers"].append(c)

    for sse in sse_streams:
        sse_norm = _normalize_ws_or_sse_path(sse["path"])
        sse_seg = sse_norm.strip("/").split("/")[-1] if sse_norm else ""
        for c in fe_sse_consumers:
            if sse_norm and (sse_norm in c["url"] or (sse_seg and sse_seg != "{param}" and sse_seg in c["url"])):
                sse["consumers"].append(c)

    # Build topology graph (nodes & edges) for interactive SVG rendering
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    seen_nodes: set[str] = set()

    def _add_node(nid: str, label: str, kind: str, meta: dict[str, Any] | None = None) -> None:
        if nid not in seen_nodes:
            seen_nodes.add(nid)
            nodes.append({"id": nid, "label": label, "kind": kind, "meta": meta or {}})

    for task in celery_tasks:
        tid = f"task:{task['name']}"
        _add_node(tid, task["function"], "celery_task", {"queue": task["queue"], "file": task["file"]})
        for p in task["producers"][:8]:
            pid = f"prod:{p['file']}"
            _add_node(pid, Path(p["file"]).name, "producer", {"file": p["file"]})
            edges.append({"source": pid, "target": tid, "type": p["call"]})

    for b in beat_schedules:
        bid = f"beat:{b['name']}"
        _add_node(bid, b["name"], "beat_schedule", {"schedule": b["schedule"], "queue": b["queue"]})
        # Link to matching celery task if known
        matched = task_by_name.get(b["task"]) or task_by_fn.get(b["task"].split(".")[-1])
        if matched:
            edges.append({"source": bid, "target": f"task:{matched['name']}", "type": "schedules"})

    redis_keys_list = sorted(redis_keys_map.values(), key=lambda x: (x["kind"] != "lock", x["key_pattern"]))
    for rk in redis_keys_list:
        rid = f"redis:{rk['key_pattern']}"
        _add_node(rid, rk["key_pattern"], "redis_lock" if rk["kind"] == "lock" else "redis_key", {"ttl": rk["ttl"]})
        for p in rk["producers"][:4]:
            pid = f"prod:{p['file']}"
            _add_node(pid, Path(p["file"]).name, "producer", {"file": p["file"]})
            edges.append({"source": pid, "target": rid, "type": p["op"]})

    pubsub_list = sorted(pubsub_map.values(), key=lambda x: x["channel"])
    for ps in pubsub_list:
        cid = f"pubsub:{ps['channel']}"
        _add_node(cid, ps["channel"], "pubsub", {"pattern": ps["pattern"]})
        for pub in ps["publishers"][:6]:
            pid = f"prod:{pub['file']}"
            _add_node(pid, Path(pub["file"]).name, "producer", {"file": pub["file"]})
            edges.append({"source": pid, "target": cid, "type": "publish"})
        for sub in ps["subscribers"][:6]:
            sid = f"sub:{sub['file']}"
            _add_node(sid, Path(sub["file"]).name, "subscriber", {"file": sub["file"]})
            edges.append({"source": cid, "target": sid, "type": "subscribe"})

    for ws in ws_streams:
        wid = f"ws:{ws['path']}"
        _add_node(wid, ws["path"], "websocket", {"file": ws["file"], "handler": ws["handler"]})
        for c in ws["consumers"][:6]:
            fid = f"fe:{c['file']}"
            _add_node(fid, Path(c["file"]).name, "frontend_consumer", {"file": c["file"]})
            edges.append({"source": wid, "target": fid, "type": "ws_stream"})

    for sse in sse_streams:
        sid = f"sse:{sse['path']}"
        _add_node(sid, sse["path"], "sse", {"file": sse["file"], "handler": sse["handler"]})
        for c in sse["consumers"][:6]:
            fid = f"fe:{c['file']}"
            _add_node(fid, Path(c["file"]).name, "frontend_consumer", {"file": c["file"]})
            edges.append({"source": sid, "target": fid, "type": "sse_stream"})

    queues = sorted({t["queue"] for t in celery_tasks} | {b["queue"] for b in beat_schedules})
    locks_count = sum(1 for rk in redis_keys_list if rk["kind"] == "lock")

    payload: dict[str, Any] = {
        "schema_version": "1.0",
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "summary": {
            "celery_tasks_count": len(celery_tasks),
            "beat_schedules_count": len(beat_schedules),
            "redis_keys_count": len(redis_keys_list),
            "redis_locks_count": locks_count,
            "pubsub_channels_count": len(pubsub_list),
            "ws_streams_count": len(ws_streams),
            "sse_streams_count": len(sse_streams),
            "frontend_ws_consumers_count": len(fe_ws_consumers),
            "frontend_sse_consumers_count": len(fe_sse_consumers),
            "producers_count": len(raw_producers),
            "queues": queues,
            "graph_nodes_count": len(nodes),
            "graph_edges_count": len(edges),
        },
        "celery_tasks": celery_tasks,
        "beat_schedules": beat_schedules,
        "redis_keys": redis_keys_list,
        "pubsub_channels": pubsub_list,
        "ws_streams": ws_streams,
        "sse_streams": sse_streams,
        "frontend_consumers": {
            "websocket": fe_ws_consumers,
            "sse": fe_sse_consumers,
        },
        "graph": {
            "nodes": nodes,
            "edges": edges,
        },
    }

    json_path = data_dir / "async-topology.json"
    js_path = data_dir / "async_topology.js"
    json_text = json.dumps(payload, indent=2)
    json_path.write_text(json_text, encoding="utf-8")
    js_path.write_text(f"window.ASYNC_TOPOLOGY_DATA = {json_text};\n", encoding="utf-8")
    return payload
