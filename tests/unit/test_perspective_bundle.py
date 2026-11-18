from pathlib import Path
from knowledge_portal.server import PortalRequestHandler


def test_wasm_mime_registered():
    assert PortalRequestHandler.extensions_map.get(".wasm") == "application/wasm"


def test_perspective_offline_bundle_present():
    repo_root = Path(__file__).resolve().parents[2]
    vendor = repo_root / "template" / "vendor" / "perspective"
    expected = [
        vendor / "client" / "dist" / "cdn" / "perspective.js",
        vendor / "client" / "dist" / "wasm" / "perspective-js.wasm",
        vendor / "server" / "dist" / "wasm" / "perspective-server.wasm",
        vendor / "viewer" / "dist" / "cdn" / "perspective-viewer.js",
        vendor / "viewer" / "dist" / "wasm" / "perspective-viewer.wasm",
        vendor / "viewer" / "dist" / "css" / "pro-dark.css",
        vendor / "viewer-datagrid" / "dist" / "cdn" / "perspective-viewer-datagrid.js",
        vendor / "viewer-d3fc" / "dist" / "cdn" / "perspective-viewer-d3fc.js",
    ]
    for p in expected:
        assert p.is_file(), f"Missing Perspective offline asset: {p}"


def test_data_explorer_view_is_airgapped():
    repo_root = Path(__file__).resolve().parents[2]
    explorer = repo_root / "template" / "views" / "data-explorer.html"
    assert explorer.is_file()
    txt = explorer.read_text(encoding="utf-8")
    assert "https://" not in txt and "http://" not in txt
    assert "../vendor/perspective/client/dist/cdn/perspective.js" in txt
