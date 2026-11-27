"""ADR-083 Sprint 4: PortalSVGViewport & 5 OSS 0-CDN SVG Visuals tests."""

from __future__ import annotations

import re
from pathlib import Path

VIEWS_DIR = Path(__file__).resolve().parents[2] / "template" / "views"
CDN_PATTERN = re.compile(
    r"https?://(?:cdn\.jsdelivr\.net|unpkg\.com|cdnjs\.cloudflare\.com|fonts\.googleapis\.com|fonts\.gstatic\.com)",
    re.IGNORECASE,
)


def test_portal_svg_viewport_present_in_portal_ui() -> None:
    ui_js = (VIEWS_DIR / "portal-ui.js").read_text(encoding="utf-8")
    assert "window.PortalSVGViewport" in ui_js
    assert "Export SVG" in ui_js
    assert "XMLSerializer" in ui_js
    assert "wheel" in ui_js
    assert not CDN_PATTERN.search(ui_js)


def test_existing_svg_views_wired_to_portal_svg_viewport() -> None:
    wired_views = [
        "git-pr-dag.html",
        "adr-runbook-hub.html",
        "vertical-slices.html",
        "async-topology.html",
        "data-ingestion.html",
    ]
    for name in wired_views:
        html = (VIEWS_DIR / name).read_text(encoding="utf-8")
        assert "<svg" in html, f"{name} missing <svg"
        assert "PortalSVGViewport.attach" in html, f"{name} missing PortalSVGViewport.attach"
        assert not CDN_PATTERN.search(html), f"{name} contains external CDN reference"


def test_five_new_oss_svg_charts_present_and_airgapped() -> None:
    expected = {
        "data-contracts.html": ("dc-sankey-svg", "PortalSVGViewport.attach", "<svg"),
        "test-oracle.html": ("to-treemap-svg", "filterByDomain", "<svg"),
        "worker-tasks.html": ("wt-gantt-svg", "renderBeatGantt", "<svg"),
        "frontend-state.html": ("fs-bipartite-svg", "PortalSVGViewport.attach", "<svg"),
        "mission-control.html": ("renderSubSparkline", "arch-health-history.json", "<svg"),
    }
    for name, markers in expected.items():
        html = (VIEWS_DIR / name).read_text(encoding="utf-8")
        for m in markers:
            assert m in html, f"{name} missing marker {m!r}"
        assert not CDN_PATTERN.search(html), f"{name} contains external CDN reference"
