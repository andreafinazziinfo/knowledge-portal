"""Unit & Regression Tests for ADR-082 Wave 2 (AI-3 Vertical Slices + AI-4 Async Topology + 6 0-CDN Views)."""

from __future__ import annotations

import json
import re
from pathlib import Path

from knowledge_portal.generators.async_topology import generate_async_topology
from knowledge_portal.generators.vertical_slices import (
    generate_vertical_slices,
    normalize_api_path,
    strip_api_prefix,
)
from knowledge_portal.mcp_budget import estimate_tokens
from knowledge_portal.mcp_server import PortalMcpEngine, handle_jsonrpc_request


def _build_fullstack_fixture(root: Path) -> tuple[Path, Path]:
    """Create a realistic mini full-stack repo (Vue + Pinia + FastAPI + Celery + Redis + WS/SSE)."""
    (root / "frontend" / "src" / "stores").mkdir(parents=True)
    (root / "frontend" / "src" / "views").mkdir(parents=True)
    (root / "backend" / "app" / "api" / "v1").mkdir(parents=True)
    (root / "backend" / "app" / "workers").mkdir(parents=True)
    (root / "backend" / "app" / "websockets").mkdir(parents=True)
    data_dir = root / "data"
    data_dir.mkdir(parents=True)

    # Pinia store calling exact and parameterized API routes + helper
    (root / "frontend" / "src" / "stores" / "useOrdersStore.ts").write_text(
        """import { defineStore } from 'pinia'
import { ref } from 'vue'

const api = (p: string) => `${baseUrl}/api/v1/orders${p}`

export const useOrdersStore = defineStore('orders', () => {
  const items = ref([])
  const loading = ref(false)
  async function loadAll() {
    const r = await fetch(api('/list'))
    items.value = await r.json()
  }
  async function loadOne(id: string) {
    return await fetch(`/api/v1/orders/${id}`, { method: 'GET' })
  }
  async function createOrder(payload: any) {
    return await fetch('/api/v1/orders/create', { method: 'POST', body: JSON.stringify(payload) })
  }
  return { items, loading, loadAll, loadOne, createOrder }
})
""",
        encoding="utf-8",
    )

    # Vue component consuming store + WebSocket + EventSource
    (root / "frontend" / "src" / "views" / "OrdersView.vue").write_text(
        """<script setup lang="ts">
import { useOrdersStore } from '@/stores/useOrdersStore'
const store = useOrdersStore()
const ws = new WebSocket(`wss://localhost/api/v1/ws/orders/${symbol}`)
const es = new EventSource('/api/v1/orders/stream')
</script>
<template><div>Orders</div></template>
""",
        encoding="utf-8",
    )

    # Backend FastAPI router calling Celery task, Redis key, SQL table, and SSE
    (root / "backend" / "app" / "api" / "v1" / "orders.py").write_text(
        """from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from app.workers.tasks import process_order_task

router = APIRouter()

@router.get("/orders/list")
async def list_orders(redis_client):
    redis_client.get("orders:cache:all")
    sql = "SELECT * FROM orders"
    return {"sql": sql}

@router.get("/orders/{order_id}")
async def get_order(order_id: str):
    return {"id": order_id}

@router.post("/orders/create")
async def create_order(redis_client):
    redis_client.set("orders:lock:create", "1", nx=True, ex=30)
    process_order_task.delay(order_id=1)
    return {"ok": True}

@router.get("/orders/stream")
async def stream_orders():
    return StreamingResponse(iter([]), media_type="text/event-stream")
""",
        encoding="utf-8",
    )

    # Celery tasks + Beat schedule + Redis Pub/Sub
    (root / "backend" / "app" / "workers" / "tasks.py").write_text(
        """from celery import Celery
from celery.schedules import crontab

ORDERS_CHANNEL = "events:orders"
celery_app = Celery("demo")

celery_app.conf.beat_schedule = {
    "nightly-order-reconcile": {
        "task": "app.workers.tasks.reconcile_orders",
        "schedule": crontab(hour=2, minute=0),
        "options": {"queue": "maintenance"},
    }
}

@celery_app.task(name="app.workers.tasks.process_order_task", queue="orders", max_retries=3, soft_time_limit=60, rate_limit="10/m")
def process_order_task(order_id: int, redis_client=None):
    redis_client.publish(ORDERS_CHANNEL, str(order_id))
    redis_client.setex(f"orders:status:{order_id}", 300, "done")
    return order_id

@celery_app.task(name="app.workers.tasks.reconcile_orders", queue="maintenance")
def reconcile_orders():
    return True
""",
        encoding="utf-8",
    )

    # WebSocket endpoint + Redis subscriber
    (root / "backend" / "app" / "websockets" / "orders_ws.py").write_text(
        """from fastapi import APIRouter
router = APIRouter()
ORDERS_CHANNEL = "events:orders"

@router.websocket("/api/v1/ws/orders/{symbol}")
async def ws_orders(websocket, pubsub):
    await pubsub.subscribe(ORDERS_CHANNEL)
""",
        encoding="utf-8",
    )

    # Seed api-catalog.json & db-schema.json
    (data_dir / "api-catalog.json").write_text(
        json.dumps(
            {
                "endpoints": [
                    {"method": "GET", "path": "/orders/list", "tag": "Orders", "handler": "list_orders", "file": "backend/app/api/v1/orders.py", "line": 7, "auth": "JWT"},
                    {"method": "GET", "path": "/orders/{order_id}", "tag": "Orders", "handler": "get_order", "file": "backend/app/api/v1/orders.py", "line": 13, "auth": "JWT"},
                    {"method": "POST", "path": "/orders/create", "tag": "Orders", "handler": "create_order", "file": "backend/app/api/v1/orders.py", "line": 17, "auth": "JWT"},
                    {"method": "GET", "path": "/orders/stream", "tag": "Orders", "handler": "stream_orders", "file": "backend/app/api/v1/orders.py", "line": 23, "auth": "JWT"},
                ]
            }
        ),
        encoding="utf-8",
    )
    (data_dir / "db-schema.json").write_text(
        json.dumps(
            {
                "tables": [
                    {"name": "orders", "readers": ["backend/app/api/v1/orders.py"], "writers": ["backend/app/api/v1/orders.py"]}
                ]
            }
        ),
        encoding="utf-8",
    )
    return root, data_dir


def test_url_normalization_helpers() -> None:
    assert normalize_api_path("${apiBase}/api/v1/orders/${id}?limit=10") == "/api/v1/orders/{param}"
    assert normalize_api_path("https://example.com/api/v2/items/:itemId/") == "/api/v2/items/{param}"
    assert strip_api_prefix("/api/v1/orders/{param}") == "/orders/{param}"


def test_vertical_slices_generator_6_layers(tmp_path: Path) -> None:
    root, data_dir = _build_fullstack_fixture(tmp_path)
    res = generate_vertical_slices(root, data_dir)

    assert (data_dir / "vertical-slices.json").exists()
    assert (data_dir / "vertical_slices.js").exists()

    summary = res["summary"]
    assert summary["total_slices"] >= 3
    assert summary["cross_stack_edges_count"] >= 3
    assert summary["stores_count"] == 1
    assert summary["components_count"] == 1

    # Verify full 6-layer chain on POST /orders/create
    create_slice = next(s for s in res["slices"] if s["endpoint"] == "/orders/create")
    layers = create_slice["layers"]
    assert any("OrdersView.vue" in c for c in layers["components"])
    assert any("useOrdersStore" in st for st in layers["stores"])
    assert layers["backend_route"]["handler"] == "create_order"
    assert "process_order_task" in layers["services_and_tasks"]["celery_tasks"]
    assert "orders" in layers["storage"]["db_tables"]
    assert "orders:lock:create" in layers["storage"]["redis_keys"]


def test_async_topology_generator_extracts_all_5_pillars(tmp_path: Path) -> None:
    root, data_dir = _build_fullstack_fixture(tmp_path)
    res = generate_async_topology(root, data_dir)

    assert (data_dir / "async-topology.json").exists()
    assert (data_dir / "async_topology.js").exists()

    s = res["summary"]
    assert s["celery_tasks_count"] == 2
    assert s["beat_schedules_count"] == 1
    assert s["redis_keys_count"] >= 3
    assert s["redis_locks_count"] >= 1
    assert s["pubsub_channels_count"] == 1
    assert s["ws_streams_count"] == 1
    assert s["sse_streams_count"] == 1

    # Producer linked to Celery task
    proc_task = next(t for t in res["celery_tasks"] if t["function"] == "process_order_task")
    assert proc_task["queue"] == "orders"
    assert proc_task["max_retries"] == 3
    assert proc_task["soft_time_limit"] == 60
    assert proc_task["rate_limit"] == "10/m"
    assert len(proc_task["producers"]) == 1

    # Pub/Sub publisher <-> subscriber matched
    ch = res["pubsub_channels"][0]
    assert ch["channel"] == "events:orders"
    assert len(ch["publishers"]) == 1
    assert len(ch["subscribers"]) == 1

    # WS & SSE frontend consumers linked
    assert len(res["ws_streams"][0]["consumers"]) == 1
    assert len(res["sse_streams"][0]["consumers"]) == 1


def test_mcp_wave2_tools_resources_and_token_budgets(tmp_path: Path) -> None:
    root, data_dir = _build_fullstack_fixture(tmp_path)
    generate_vertical_slices(root, data_dir)
    generate_async_topology(root, data_dir)

    eng = PortalMcpEngine(project_dir=root, data_dir=data_dir)

    # 1. portal_vertical_slice summary <= 800 tokens
    r_vs = handle_jsonrpc_request(eng, {
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "portal_vertical_slice", "arguments": {"query": "orders"}},
    })
    assert r_vs is not None
    vs_payload = json.loads(r_vs["result"]["content"][0]["text"])
    assert vs_payload["_detail"] == "summary"
    assert estimate_tokens(vs_payload) <= 800
    assert vs_payload["matched_count"] >= 3

    # 2. portal_async_topology summary <= 700 tokens
    r_at = handle_jsonrpc_request(eng, {
        "jsonrpc": "2.0", "id": 2, "method": "tools/call",
        "params": {"name": "portal_async_topology", "arguments": {"kind": "all"}},
    })
    assert r_at is not None
    at_payload = json.loads(r_at["result"]["content"][0]["text"])
    assert at_payload["_detail"] == "summary"
    assert estimate_tokens(at_payload) <= 700
    assert at_payload["summary"]["celery_tasks_count"] == 2

    # 3. portal_slice_for_task enriched with vertical_slices & async_hooks
    r_sl = handle_jsonrpc_request(eng, {
        "jsonrpc": "2.0", "id": 3, "method": "tools/call",
        "params": {"name": "portal_slice_for_task", "arguments": {"task": "orders create process_order_task", "max_tokens": 1500}},
    })
    assert r_sl is not None
    sl_payload = json.loads(r_sl["result"]["content"][0]["text"])
    assert len(sl_payload.get("vertical_slices") or []) >= 1
    assert len(sl_payload.get("async_hooks") or []) >= 1
    assert sl_payload["budget_used_tokens"] <= 1500

    # 4. Resources portal://vertical-slices and portal://async-topology
    for uri in ("portal://vertical-slices", "portal://async-topology"):
        res = handle_jsonrpc_request(eng, {"jsonrpc": "2.0", "id": 4, "method": "resources/read", "params": {"uri": uri}})
        assert res is not None and "result" in res
        parsed = json.loads(res["result"]["contents"][0]["text"])
        assert "summary" in parsed


def test_wave2_six_html_views_zero_cdn_and_dashboard_wired() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    views_dir = repo_root / "template" / "views"
    wave2_views = [
        "async-topology.html",
        "worker-tasks.html",
        "frontend-state.html",
        "data-ingestion.html",
        "vertical-slices.html",
        "test-oracle.html",
    ]
    external_cdn_re = re.compile(r"""(?:https?:)?//(?:unpkg\.com|cdn\.jsdelivr\.net|cdnjs\.cloudflare\.com|fonts\.googleapis\.com)""", re.IGNORECASE)

    for vname in wave2_views:
        vpath = views_dir / vname
        assert vpath.exists(), f"Missing Wave 2 view: {vname}"
        html = vpath.read_text(encoding="utf-8")
        assert "portal-theme.css" in html, f"{vname} missing portal-theme.css"
        assert "portal-ui.js" in html, f"{vname} missing portal-ui.js"
        assert not external_cdn_re.search(html), f"{vname} still references external CDN!"

    dashboard = (repo_root / "template" / "dashboard.html").read_text(encoding="utf-8")
    for tab in ("vertical-slices", "test-oracle"):
        assert f"pane-{tab}" in dashboard
        assert f"views/{tab}.html" in dashboard
        assert f"'{tab}'" in dashboard

    codeql = repo_root / ".github" / "workflows" / "codeql.yml"
    assert codeql.exists()
    c_text = codeql.read_text(encoding="utf-8")
    assert "security-events: write" in c_text
    assert re.search(r"""@[0-9a-f]{40}""", c_text), "codeql.yml actions must be pinned to 40-char commit SHA"
