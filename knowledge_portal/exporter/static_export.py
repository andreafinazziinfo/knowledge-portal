"""
Knowledge Portal — Static Zero-Server Exporter
Packages a codebase knowledge portal into a completely self-contained static site
ready for GitHub Pages, Netlify, or local offline browsing (file://).
"""

import shutil
from pathlib import Path
from typing import Any, Dict
from knowledge_portal.scanner.polyglot import scan_polyglot_codebase
from knowledge_portal.indexer.search_index import generate_search_index

def export_static_portal(source_dir: Path, output_dir: Path, project_name: str = None) -> Dict[str, Any]:
    source_dir = source_dir.resolve()
    output_dir = output_dir.resolve()

    if not project_name:
        project_name = source_dir.name

    pkg_root = Path(__file__).resolve().parent.parent
    template_dir = pkg_root.parent / "template"

    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # 1. Copy template files
    print(f"📦 Copying portal template to: {output_dir}")
    for item in template_dir.iterdir():
        if item.name in ["data", ".git"]:
            continue
        dest = output_dir / item.name
        if item.is_dir():
            shutil.copytree(item, dest)
        else:
            shutil.copy2(item, dest)

    # 2. Run Polyglot Scanner into output_dir/data
    data_dir = output_dir / "data"
    print(f"🔍 Scanning polyglot codebase: {source_dir}")
    stats = scan_polyglot_codebase(source_dir, data_dir)

    # 3. Generate Search Index into output_dir/views/data/omni-search-index.json
    omni_dir = output_dir / "views" / "data"
    omni_dir.mkdir(parents=True, exist_ok=True)
    omni_file = omni_dir / "omni-search-index.json"
    indexed_count = generate_search_index(source_dir, omni_file)

    # 4. Create index.html as primary entrypoint (copy of dashboard.html)
    dashboard_file = output_dir / "dashboard.html"
    index_file = output_dir / "index.html"
    if dashboard_file.exists():
        content = dashboard_file.read_text(encoding="utf-8")
        # Set project config
        cfg_override = f"""<script>
    window.PROJECT_CONFIG = {{
      projectName: "{project_name}",
      apiPort: null,
      isStaticExport: true
    }};
  </script>"""
        if "window.PROJECT_CONFIG =" in content:
            content = content.replace("window.PROJECT_CONFIG = { projectName: \"Knowledge Base\", apiPort: 18115 };", f"window.PROJECT_CONFIG = {{ projectName: \"{project_name}\", apiPort: null, isStaticExport: true }};")
        else:
            content = content.replace("<head>", f"<head>\n  {cfg_override}")

        index_file.write_text(content, encoding="utf-8")
        dashboard_file.write_text(content, encoding="utf-8")

    # 5. Create .nojekyll for GitHub Pages compatibility
    (output_dir / ".nojekyll").touch()

    print("✅ Static export completed successfully!")
    print(f"   Root Entrypoint: {index_file}")
    print(f"   Total Nodes: {stats['total_nodes']} | Edges: {stats['total_edges']} | Docs: {indexed_count}")
    return stats
