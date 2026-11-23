"""
Knowledge Portal — Static Zero-Server Exporter
Packages a codebase knowledge portal into a completely self-contained static site
ready for GitHub Pages, Netlify, or local offline browsing (file://).
"""

import shutil
from pathlib import Path
from typing import Any, Dict, Optional
from knowledge_portal.server import get_template_dir
from knowledge_portal.scanner.polyglot import scan_polyglot_codebase
from knowledge_portal.indexer.search_index import generate_search_index
from knowledge_portal.generators.floorplan import generate_floorplan_from_yaml
from knowledge_portal.generators.arch_health import generate_arch_health
from knowledge_portal.generators.llms_txt import generate_llms_manifests

def export_static_portal(source_dir: Path, output_dir: Path, project_name: Optional[str] = None) -> Dict[str, Any]:
    source_dir = source_dir.resolve()
    output_dir = output_dir.resolve()

    if not project_name:
        project_name = source_dir.name

    template_dir = get_template_dir()

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

    # 2b. Generate Architectural Health & llms.txt manifests
    generate_arch_health(data_dir)
    generate_llms_manifests(source_dir, data_dir, output_dir, project_name=project_name)

    # 3. Generate Search Index into output_dir/views/data/omni-search-index.json
    omni_dir = output_dir / "views" / "data"
    omni_dir.mkdir(parents=True, exist_ok=True)
    omni_file = omni_dir / "omni-search-index.json"
    indexed_count = generate_search_index(source_dir, omni_file)

    # 4. Compile architecture.yaml if present in project root
    for candidate in [source_dir / "architecture.yaml", source_dir / "architecture.yml", source_dir / "architecture.json"]:
        if candidate.exists():
            print(f"🏗️ Compiling project floorplan: {candidate.name}")
            generate_floorplan_from_yaml(candidate, output_dir / "views" / "floorplan.html")
            break

    # 5. Create index.html as primary entrypoint (copy of dashboard.html)
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
