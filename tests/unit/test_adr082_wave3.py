"""Unit tests for ADR-082 Wave 3 (AI-6): Data Contracts, Runtime Modes, MCP & UI."""

from __future__ import annotations

import json
from pathlib import Path

from knowledge_portal.generators.data_contracts import generate_data_contracts
from knowledge_portal.generators.runtime_modes import generate_runtime_modes
from knowledge_portal.mcp_budget import estimate_tokens
from knowledge_portal.mcp_server import PortalMcpEngine, handle_jsonrpc_request


def _seed_sample_repo(root: Path) -> Path:
    """Create a realistic mini full-stack repo for Wave 3 testing (zero proprietary terms)."""
    (root / "backend" / "app" / "schemas").mkdir(parents=True)
    (root / "backend" / "app" / "api").mkdir(parents=True)
    (root / "backend" / "app" / "db").mkdir(parents=True)
    (root / "migrations").mkdir(parents=True)
    (root / "frontend" / "src" / "types").mkdir(parents=True)
    data_dir = root / "data"
    data_dir.mkdir(parents=True)

    # Seed db-schema.json
    (data_dir / "db-schema.json").write_text(json.dumps({
        "tables": [
            {"name": "orders", "columns": [{"name": "id"}]},
            {"name": "audit_logs", "columns": [{"name": "id"}]},
            {"name": "orphan_table", "columns": [{"name": "id"}]},
        ]
    }), encoding="utf-8")

    # Pydantic models (OrderOut has drift vs TS; ItemOut is synced)
    (root / "backend" / "app" / "schemas" / "order.py").write_text(
        "from typing import Optional\n"
        "from pydantic import BaseModel\n\n"
        "class OrderOut(BaseModel):\n"
        "    order_id: int\n"
        "    symbol: str\n"
        "    total_amount: float\n"
        "    notes: Optional[str] = None\n\n"
        "class ItemOut(BaseModel):\n"
        "    id: int\n"
        "    name: str\n",
        encoding="utf-8",
    )

    # FastAPI routes + HTTPException + custom exception + SQL R/W
    (root / "backend" / "app" / "api" / "orders.py").write_text(
        "from fastapi import APIRouter, HTTPException\n"
        "from app.schemas.order import OrderOut\n\n"
        "router = APIRouter()\n\n"
        "class OrderNotFoundError(Exception):\n"
        "    '''Raised when an order cannot be found.'''\n"
        "    pass\n\n"
        "@router.get('/api/v1/orders/{order_id}', response_model=OrderOut)\n"
        "async def get_order(order_id: int, db=None):\n"
        "    rows = db.execute('SELECT id, symbol FROM orders WHERE id = :id')\n"
        "    if not rows:\n"
        "        raise HTTPException(status_code=404, detail='Order not found')\n"
        "    return rows[0]\n\n"
        "@router.post('/api/v1/orders/raw')\n"
        "async def create_raw_order(payload: dict, db=None) -> dict:\n"
        "    db.execute('INSERT INTO orders (symbol) VALUES (:s)')\n"
        "    db.execute('INSERT INTO audit_logs (action) VALUES (:a)')\n"
        "    return {'ok': True}\n",
        encoding="utf-8",
    )

    # Migration SQL
    (root / "migrations" / "001_init.sql").write_text(
        "CREATE TABLE orders (id SERIAL PRIMARY KEY, symbol TEXT);\n"
        "CREATE TABLE audit_logs (id SERIAL PRIMARY KEY, action TEXT);\n",
        encoding="utf-8",
    )

    # TypeScript interfaces (OrderOut missing notes + wrong type for orderId)
    (root / "frontend" / "src" / "types" / "order.ts").write_text(
        "export interface OrderOut {\n"
        "  orderId: string;\n"
        "  symbol: string;\n"
        "  totalAmount: number;\n"
        "  extraClientField?: boolean;\n"
        "}\n\n"
        "export interface ItemOut {\n"
        "  id: number;\n"
        "  name: string;\n"
        "}\n\n"
        "export function handleApiError(status: number) {\n"
        "  if (status === 401 || status === 404) return 'handled';\n"
        "  return 'other';\n"
        "}\n",
        encoding="utf-8",
    )

    # Runtime modes config + .env.example + real .env (MUST NEVER be read!)
    (root / ".env.example").write_text(
        "APP_ENV=dev\n"
        "TRADING_MODE=paper\n"
        "ENABLE_METRICS=true\n"
        "API_SECRET_KEY=placeholder_value\n",
        encoding="utf-8",
    )
    (root / ".env").write_text(
        "REAL_PROD_SECRET=DO_NOT_EVER_READ_THIS_TOKEN_12345\n"
        "SECRET_OVERRIDE=TOP_SECRET_VALUE\n",
        encoding="utf-8",
    )
    (root / "backend" / "app" / "config.py").write_text(
        "import os\n"
        "APP_ENV = os.getenv('APP_ENV', 'dev')\n"
        "TRADING_MODE = os.getenv('TRADING_MODE', 'paper')\n"
        "KILL_SWITCH_ENABLED = os.getenv('KILL_SWITCH_ENABLED', 'true')\n"
        "ENABLE_PAPER_BROKER = os.getenv('ENABLE_PAPER_BROKER', 'true')\n"
        "if TRADING_MODE == 'live':\n"
        "    guard = 'kill_switch'\n"
        "elif TRADING_MODE == 'shadow':\n"
        "    guard = 'read_only'\n"
        "elif TRADING_MODE == 'offline':\n"
        "    guard = 'dry_run'\n",
        encoding="utf-8",
    )

    return data_dir


def test_data_contracts_generator(tmp_path: Path) -> None:
    data_dir = _seed_sample_repo(tmp_path)
    res = generate_data_contracts(tmp_path, data_dir)

    assert (data_dir / "data-contracts.json").is_file()
    assert (data_dir / "data_contracts.js").is_file()
    assert "window.DATA_CONTRACTS_DATA" in (data_dir / "data_contracts.js").read_text(encoding="utf-8")

    s = res["summary"]
    assert s["pydantic_models_count"] == 2
    assert s["ts_types_count"] == 2
    assert s["matched_schemas_count"] == 2
    assert s["schema_drift_count"] == 1
    assert s["untyped_routes_count"] == 1
    assert s["http_exceptions_count"] == 1
    assert s["custom_exceptions_count"] == 1
    assert s["fe_error_handlers_count"] == 1
    assert s["db_rw_tables_count"] == 3
    assert s["orphan_tables_count"] == 1

    drift = res["schema_drift"][0]
    assert drift["pydantic_model"] == "OrderOut"
    assert "notes" in drift["missing_in_ts"]
    assert "extra_client_field" in drift["missing_in_py"]
    assert any(m["field"] == "order_id" for m in drift["type_mismatches"])

    rw_by_tbl = {r["table"]: r for r in res["db_rw_matrix"]}
    assert rw_by_tbl["orders"]["readers_count"] >= 1
    assert rw_by_tbl["orders"]["writers_count"] >= 1
    assert rw_by_tbl["orders"]["migrations_count"] == 1
    assert rw_by_tbl["orphan_table"]["is_orphan"] is True


def test_runtime_modes_generator_never_reads_real_dotenv(tmp_path: Path) -> None:
    data_dir = _seed_sample_repo(tmp_path)
    res = generate_runtime_modes(tmp_path, data_dir)

    raw_json = (data_dir / "runtime-modes.json").read_text(encoding="utf-8")
    assert "DO_NOT_EVER_READ_THIS_TOKEN_12345" not in raw_json
    assert "TOP_SECRET_VALUE" not in raw_json
    assert "REAL_PROD_SECRET" not in raw_json
    assert (data_dir / "runtime_modes.js").is_file()

    assert res["summary"]["modes_count"] == 5
    mode_names = [m["mode"] for m in res["modes"]]
    assert mode_names == ["offline", "dev", "paper", "shadow", "live"]
    assert res["summary"]["feature_flags_count"] >= 3
    assert "kill_switch" in res["summary"]["detected_guards"]
    assert res["summary"]["env_files_read"] == "templates_only_never_dotenv"


def test_mcp_portal_contract_all_kinds_and_resources(tmp_path: Path) -> None:
    data_dir = _seed_sample_repo(tmp_path)
    generate_data_contracts(tmp_path, data_dir)
    generate_runtime_modes(tmp_path, data_dir)

    eng = PortalMcpEngine(tmp_path, data_dir)

    for kind in ("schemas", "drift", "errors", "db_rw", "runtime_modes"):
        resp = handle_jsonrpc_request(eng, {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "portal_contract", "arguments": {"kind": kind}},
        })
        assert resp is not None and resp["result"]["isError"] is False
        txt = resp["result"]["content"][0]["text"]
        assert estimate_tokens(txt) <= 800
        body = json.loads(txt)
        assert body["kind"] == kind
        assert body["_detail"] == "summary"

    # Invalid kind returns structured error (zero silent-empty)
    bad = handle_jsonrpc_request(eng, {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {"name": "portal_contract", "arguments": {"kind": "bogus"}},
    })
    assert bad is not None
    bad_body = json.loads(bad["result"]["content"][0]["text"])
    assert bad_body["ok"] is False and bad_body["error"] == "invalid_kind"

    # Resources read
    for uri in ("portal://data-contracts", "portal://runtime-modes"):
        r = handle_jsonrpc_request(eng, {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "resources/read",
            "params": {"uri": uri},
        })
        assert r is not None and "result" in r
        parsed = json.loads(r["result"]["contents"][0]["text"])
        assert "summary" in parsed

    # check_diff flags SCHEMA_DRIFT on touched schema file
    diff_res = eng.check_diff(files=["backend/app/schemas/order.py"])
    assert any(a["rule"] == "SCHEMA_DRIFT" for a in diff_res.get("contract_alerts") or [])


def test_data_contracts_view_is_zero_cdn() -> None:
    view_path = Path(__file__).resolve().parents[2] / "template" / "views" / "data-contracts.html"
    assert view_path.is_file()
    html = view_path.read_text(encoding="utf-8")
    assert "http://" not in html and "https://" not in html
    assert "data-contracts.json" in html
    assert "runtime-modes.json" in html
