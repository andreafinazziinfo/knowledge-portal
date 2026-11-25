"""ADR-083 Sprint 2: Blocking 100% True Air-Gap (0-CDN) verification tests.

Scans every .html and .css file in template/ (including template/dashboard.html
and template/assets/*.css) to ensure zero external CDN/font URLs remain.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_DIR = REPO_ROOT / "template"

FORBIDDEN_CDN_RE = re.compile(
    r"https?://(?:"
    r"fonts\.googleapis\.com"
    r"|fonts\.gstatic\.com"
    r"|cdn\.jsdelivr\.net"
    r"|cdnjs\.cloudflare\.com"
    r"|unpkg\.com"
    r"|d3js\.org"
    r"|esm\.sh"
    r"|cdn\.[a-z0-9.-]+"
    r")",
    re.IGNORECASE,
)


def _iter_template_html_and_css() -> list[Path]:
    files: list[Path] = []
    for path in sorted(TEMPLATE_DIR.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() not in {".html", ".css"}:
            continue
        # Exclude vendored third-party libraries (e.g. katex/perspective inside vendor/)
        rel_parts = path.relative_to(TEMPLATE_DIR).parts
        if "vendor" in rel_parts or "data" in rel_parts:
            continue
        files.append(path)
    return files


def test_zero_cdn_in_all_template_html_and_css() -> None:
    files = _iter_template_html_and_css()
    assert files, "No template HTML/CSS files discovered"

    violations: list[str] = []
    for path in files:
        content = path.read_text(encoding="utf-8", errors="ignore")
        for lineno, line in enumerate(content.splitlines(), start=1):
            match = FORBIDDEN_CDN_RE.search(line)
            if match:
                rel = path.relative_to(REPO_ROOT).as_posix()
                violations.append(f"{rel}:{lineno}: {match.group(0)}")

    assert not violations, "External CDN URLs found in air-gapped templates:\n" + "\n".join(violations)


def test_dashboard_mermaid_loaded_locally_without_defer_or_cdn() -> None:
    dash = (TEMPLATE_DIR / "dashboard.html").read_text(encoding="utf-8")
    assert 'src="vendor/mermaid.min.js"' in dash
    assert 'defer src="vendor/mermaid.min.js"' not in dash
    assert 'src="assets/marked.min.js"' in dash
    assert "fonts.gstatic.com" not in dash
    assert "fonts.googleapis.com" not in dash


def test_font_awesome_css_has_no_external_import() -> None:
    fa_css = (TEMPLATE_DIR / "assets" / "font-awesome.min.css").read_text(encoding="utf-8")
    assert "@import" not in fa_css.lower()
    assert "cdnjs.cloudflare.com" not in fa_css.lower()


def test_graph_views_use_local_vendored_assets_only() -> None:
    expected = {
        "GRAPH_TREE.html": "../assets/d3.v7.min.js",
        "graph.html": "../assets/vis-network.min.js",
        "graph_3d.html": "../assets/3d-force-graph.min.js",
        "tree_3d.html": "../assets/3d-force-graph.min.js",
    }
    for filename, local_src in expected.items():
        html = (TEMPLATE_DIR / "views" / filename).read_text(encoding="utf-8")
        assert local_src in html, f"{filename} missing local asset {local_src}"
        assert FORBIDDEN_CDN_RE.search(html) is None, f"{filename} still contains CDN reference"
