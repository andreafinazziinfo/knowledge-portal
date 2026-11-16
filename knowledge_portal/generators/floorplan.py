"""
Declarative Interactive Floorplan & Architecture SVG Generator (Zero External Dependencies)
Parses architecture.yaml (or architecture.json) and compiles it into an interactive SVG floorplan.
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def parse_yaml_zero_dep(text: str) -> Dict[str, Any]:
    """
    Zero-dependency YAML parser for architecture descriptor files.
    Falls back gracefully if PyYAML is not present.
    """
    try:
        import yaml  # type: ignore
        res = yaml.safe_load(text)
        if isinstance(res, dict):
            return res
    except ImportError:
        pass
    except Exception:
        pass

    # Standard library fallback parser for simple YAML structures
    result: Dict[str, Any] = {"layers": [], "connections": []}
    lines = text.splitlines()

    current_layer: Optional[Dict[str, Any]] = None
    current_service: Optional[Dict[str, Any]] = None
    in_connections = False

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        indent = len(line) - len(line.lstrip(" "))

        if stripped.startswith("title:"):
            result["title"] = stripped.split(":", 1)[1].strip().strip("\"'")
            continue
        if stripped.startswith("description:"):
            result["description"] = stripped.split(":", 1)[1].strip().strip("\"'")
            continue

        if stripped == "connections:":
            in_connections = True
            current_layer = None
            current_service = None
            continue

        if stripped == "layers:":
            in_connections = False
            continue

        if in_connections:
            if stripped.startswith("- from:"):
                from_id = stripped.split(":", 1)[1].strip().strip("\"'")
                result["connections"].append({"from": from_id, "to": ""})
            elif stripped.startswith("to:") and result["connections"]:
                result["connections"][-1]["to"] = stripped.split(":", 1)[1].strip().strip("\"'")
            continue

        # Inside layers
        if indent == 2 and stripped.startswith("- id:"):
            l_id = stripped.split(":", 1)[1].strip().strip("\"'")
            current_layer = {"id": l_id, "name": l_id, "color": "#38bdf8", "services": []}
            result["layers"].append(current_layer)
            current_service = None
        elif current_layer is not None:
            if indent == 4 and stripped.startswith("name:"):
                current_layer["name"] = stripped.split(":", 1)[1].strip().strip("\"'")
            elif indent == 4 and stripped.startswith("color:"):
                current_layer["color"] = stripped.split(":", 1)[1].strip().strip("\"'")
            elif indent == 6 and stripped.startswith("- id:"):
                s_id = stripped.split(":", 1)[1].strip().strip("\"'")
                current_service = {"id": s_id, "name": s_id, "desc": ""}
                current_layer["services"].append(current_service)
            elif current_service is not None:
                if indent >= 8 and stripped.startswith("name:"):
                    current_service["name"] = stripped.split(":", 1)[1].strip().strip("\"'")
                elif indent >= 8 and stripped.startswith("desc:"):
                    current_service["desc"] = stripped.split(":", 1)[1].strip().strip("\"'")

    return result


def get_default_architecture() -> Dict[str, Any]:
    """Fallback architecture when input is empty or invalid."""
    return {
        "title": "System Architecture Overview",
        "description": "Multi-tier layered system topography and microservices map",
        "layers": [
            {
                "id": "presentation",
                "name": "Layer 1: Frontend & Presentation",
                "color": "#38bdf8",
                "services": [
                    {"id": "web-app", "name": "Web Application", "desc": "Interactive single-page app and client portal"},
                    {"id": "admin-portal", "name": "Admin Console", "desc": "Back-office management interface"}
                ]
            },
            {
                "id": "gateway",
                "name": "Layer 2: Gateway & Security",
                "color": "#0284c7",
                "services": [
                    {"id": "api-gateway", "name": "API Gateway", "desc": "Reverse proxy, rate limiting and auth routing"}
                ]
            },
            {
                "id": "application",
                "name": "Layer 3: Core Application Services",
                "color": "#8b5cf6",
                "services": [
                    {"id": "core-engine", "name": "Core Service Engine", "desc": "Business logic and async tasks"},
                    {"id": "auth-service", "name": "Auth Service", "desc": "Identity provider and token validator"}
                ]
            },
            {
                "id": "persistence",
                "name": "Layer 4: Storage & Persistence",
                "color": "#10b981",
                "services": [
                    {"id": "db-primary", "name": "Primary Database", "desc": "Relational transactional database"},
                    {"id": "cache-store", "name": "Memory Cache", "desc": "Key-value cache and fast buffer"}
                ]
            }
        ],
        "connections": [
            {"from": "presentation", "to": "gateway"},
            {"from": "gateway", "to": "application"},
            {"from": "application", "to": "persistence"}
        ]
    }


def compile_floorplan_svg(arch: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
    """
    Renders vector SVG graphic string and coordinates registry from architecture dict.
    """
    layers = arch.get("layers", [])
    if not layers:
        arch = get_default_architecture()
        layers = arch["layers"]

    connections = arch.get("connections", [])

    svg_width = 1200
    layer_height = 160
    layer_gap = 50
    margin_top = 40
    layer_width = 1080
    layer_x = 60

    total_height = margin_top + len(layers) * (layer_height + layer_gap) + 80

    layer_coords: Dict[str, Tuple[float, float, float, float]] = {}
    service_coords: Dict[str, Tuple[float, float, float, float]] = {}

    svg_parts: List[str] = [
        f'<svg viewBox="0 0 {svg_width} {total_height}" width="100%" height="100%" '
        'xmlns="http://www.w3.org/2000/svg" id="arch-svg">'
    ]

    # Definitions (Gradients & Filters)
    svg_parts.append("""
      <defs>
        <filter id="glow" x="-20%" y="-20%" width="140%" height="140%">
          <feGaussianBlur stdDeviation="3" result="blur" />
          <feComposite in="SourceGraphic" in2="blur" operator="over" />
        </filter>
        <marker id="arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto">
          <path d="M 0 1 L 10 5 L 0 9 z" fill="#38bdf8" />
        </marker>
        <pattern id="grid" width="40" height="40" patternUnits="userSpaceOnUse">
          <path d="M 40 0 L 0 0 0 40" fill="none" stroke="rgba(255,255,255,0.03)" stroke-width="1" />
        </pattern>
      </defs>
      <rect width="100%" height="100%" fill="url(#grid)" />
    """)

    # Render Layers
    for i, layer in enumerate(layers):
        l_id = layer.get("id", f"layer_{i}")
        l_name = layer.get("name", f"Layer {i+1}")
        color = layer.get("color", "#38bdf8")
        y = margin_top + i * (layer_height + layer_gap)

        layer_coords[l_id] = (layer_x, y, layer_width, layer_height)

        svg_parts.append(f"""
        <g id="layer-{l_id}" class="layer-container">
          <rect x="{layer_x}" y="{y}" width="{layer_width}" height="{layer_height}" rx="12"
                fill="#0b101d" stroke="{color}" stroke-opacity="0.35" stroke-width="1.5" />
          <rect x="{layer_x}" y="{y}" width="{layer_width}" height="32" rx="12"
                fill="{color}" fill-opacity="0.1" />
          <text x="{layer_x + 18}" y="{y + 21}" fill="{color}" font-family="monospace" font-size="12" font-weight="700">
            {l_name.upper()}
          </text>
        """)

        # Render Services inside Layer
        services = layer.get("services", [])
        if services:
            num_services = len(services)
            card_gap = 20
            available_width = layer_width - 40
            card_width = min(260, (available_width - (num_services - 1) * card_gap) // num_services)
            card_height = 95
            start_x = layer_x + 20

            for j, s in enumerate(services):
                s_id = s.get("id", f"{l_id}_s{j}")
                s_name = s.get("name", s_id)
                s_desc = s.get("desc", "")
                sx = start_x + j * (card_width + card_gap)
                sy = y + 46

                service_coords[s_id] = (sx, sy, card_width, card_height)

                safe_desc = (s_desc[:36] + "...") if len(s_desc) > 36 else s_desc
                svg_parts.append(f"""
                <g id="svc-{s_id}" class="service-node" cursor="pointer"
                   onclick="selectService('{s_id}', '{s_name}', '{s_desc}', '{color}')">
                  <rect x="{sx}" y="{sy}" width="{card_width}" height="{card_height}" rx="8"
                        fill="#101524" stroke="rgba(255,255,255,0.08)" stroke-width="1" class="svc-box" />
                  <circle cx="{sx + 20}" cy="{sy + 24}" r="5" fill="{color}" />
                  <text x="{sx + 34}" y="{sy + 28}" fill="#f1f5f9" font-family="monospace" font-size="12" font-weight="600">
                    {s_name}
                  </text>
                  <text x="{sx + 14}" y="{sy + 55}" fill="#94a3b8" font-family="sans-serif" font-size="11">
                    {safe_desc}
                  </text>
                  <text x="{sx + 14}" y="{sy + 78}" fill="{color}" font-family="monospace" font-size="10" opacity="0.8">
                    id: {s_id}
                  </text>
                </g>
                """)

        svg_parts.append("</g>")

    # Render Connections
    for conn in connections:
        src = conn.get("from", "")
        dst = conn.get("to", "")

        src_rect = service_coords.get(src) or layer_coords.get(src)
        dst_rect = service_coords.get(dst) or layer_coords.get(dst)

        if src_rect and dst_rect:
            x1 = src_rect[0] + src_rect[2] / 2
            y1 = src_rect[1] + src_rect[3]
            x2 = dst_rect[0] + dst_rect[2] / 2
            y2 = dst_rect[1]

            dy = (y2 - y1) / 2
            path_d = f"M {x1} {y1} C {x1} {y1 + dy}, {x2} {y2 - dy}, {x2} {y2}"
            svg_parts.append(f"""
            <path d="{path_d}" fill="none" stroke="rgba(56, 189, 248, 0.4)" stroke-width="2"
                  stroke-dasharray="4,4" marker-end="url(#arrow)" class="conn-line" />
            """)

    svg_parts.append("</svg>")
    return "\n".join(svg_parts), arch


def generate_floorplan_html(arch: Dict[str, Any]) -> str:
    """Compiles architecture into complete interactive HTML webpage."""
    svg_content, safe_arch = compile_floorplan_svg(arch)
    title = safe_arch.get("title", "Declarative Architecture Floorplan")
    desc = safe_arch.get("description", "System layers and topology generated by Knowledge Portal")

    html = f"""<!DOCTYPE html>
<html lang="it">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>{title} — Knowledge Portal Floorplan</title>
<style>
  :root {{
    --bg: #070a12;
    --panel: #0b101d;
    --border: rgba(255,255,255,0.09);
    --cyan: #38bdf8;
    --emerald: #10b981;
    --text: #f1f5f9;
    --muted: #94a3b8;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    background: var(--bg); color: var(--text);
    font-family: system-ui, -apple-system, sans-serif;
    min-height: 100vh; overflow: hidden; display: flex; flex-direction: column;
  }}
  header {{
    background: rgba(7, 10, 18, 0.94); backdrop-filter: blur(12px);
    border-bottom: 1px solid var(--border); padding: 12px 20px;
    display: flex; justify-content: space-between; align-items: center; z-index: 10;
  }}
  .title-wrap h1 {{ font-size: 15px; font-weight: 700; color: #fff; }}
  .title-wrap p {{ font-size: 11px; color: var(--muted); margin-top: 2px; }}
  .controls {{ display: flex; gap: 8px; align-items: center; }}
  .btn {{
    background: var(--panel); border: 1px solid var(--border); color: var(--text);
    padding: 6px 12px; border-radius: 6px; font-size: 11px; cursor: pointer; transition: all 0.2s;
  }}
  .btn:hover {{ border-color: var(--cyan); color: #fff; }}
  #viewport {{
    flex: 1; position: relative; overflow: auto; background: #05070f;
    display: flex; justify-content: center; padding: 20px;
  }}
  .svc-box:hover {{ stroke: var(--cyan) !important; stroke-width: 1.5 !important; }}
  #sidebar {{
    position: fixed; right: 0; top: 57px; bottom: 0; width: 320px;
    background: var(--panel); border-left: 1px solid var(--border);
    padding: 20px; transform: translateX(100%); transition: transform 0.25s ease-out;
    z-index: 20; box-shadow: -4px 0 20px rgba(0,0,0,0.5);
  }}
  #sidebar.open {{ transform: translateX(0); }}
  .side-close {{ float: right; background: none; border: none; color: var(--muted); font-size: 18px; cursor: pointer; }}
  .side-title {{ font-size: 16px; font-weight: 700; margin-bottom: 12px; color: #fff; }}
  .side-meta {{ font-size: 12px; line-height: 1.6; color: var(--muted); }}
</style>
<script src="live-reload.js"></script>
</head>
<body>
<header>
  <div class="title-wrap">
    <h1>🏗️ {title}</h1>
    <p>{desc} · Declarative Vector Floorplan</p>
  </div>
  <div class="controls">
    <button class="btn" onclick="zoom(1.15)">🔍 Zoom In</button>
    <button class="btn" onclick="zoom(0.85)">🔍 Zoom Out</button>
    <button class="btn" onclick="resetZoom()">↺ Reset</button>
  </div>
</header>

<div id="viewport">
  <div id="svg-wrap" style="transform-origin: top center; transition: transform 0.15s ease-out; width: 100%; max-width: 1200px;">
    {svg_content}
  </div>
</div>

<div id="sidebar">
  <button class="side-close" onclick="closeSidebar()">&times;</button>
  <div class="side-title" id="side-name">Service Details</div>
  <div class="side-meta">
    <p style="margin-bottom:8px"><b>Identificativo:</b> <code id="side-id" style="color:var(--cyan)">-</code></p>
    <p style="margin-bottom:8px"><b>Descrizione:</b> <span id="side-desc">-</span></p>
  </div>
</div>

<script>
let currentScale = 1.0;
function zoom(factor) {{
  currentScale *= factor;
  document.getElementById('svg-wrap').style.transform = `scale(${{currentScale}})`;
}}
function resetZoom() {{
  currentScale = 1.0;
  document.getElementById('svg-wrap').style.transform = 'scale(1)';
}}
function selectService(id, name, desc, color) {{
  document.getElementById('side-id').textContent = id;
  document.getElementById('side-name').textContent = name;
  document.getElementById('side-desc').textContent = desc || 'Nessuna descrizione specificata.';
  document.getElementById('sidebar').classList.add('open');
}}
function closeSidebar() {{
  document.getElementById('sidebar').classList.remove('open');
}}
</script>
</body>
</html>"""
    return html


def generate_floorplan_from_yaml(yaml_path: Path, output_html_path: Path) -> Path:
    """
    Main entry point: loads architecture file, generates interactive HTML floorplan.
    """
    if yaml_path.exists():
        content = yaml_path.read_text(encoding="utf-8", errors="replace")
        if yaml_path.suffix.lower() == ".json":
            try:
                arch = json.loads(content)
            except Exception:
                arch = get_default_architecture()
        else:
            arch = parse_yaml_zero_dep(content)
    else:
        arch = get_default_architecture()

    html = generate_floorplan_html(arch)
    output_html_path.parent.mkdir(parents=True, exist_ok=True)
    output_html_path.write_text(html, encoding="utf-8")
    return output_html_path
