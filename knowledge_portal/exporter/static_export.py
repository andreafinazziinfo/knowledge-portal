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
from knowledge_portal.generators.api_catalog import generate_api_catalog
from knowledge_portal.generators.call_graph import generate_call_graph
from knowledge_portal.generators.ownership import generate_ownership_map
from knowledge_portal.generators.config_matrix import generate_config_matrix
from knowledge_portal.generators.iac_topology import generate_iac_topology
from knowledge_portal.generators.ai_registry import generate_ai_registry
from knowledge_portal.generators.compliance_evidence import generate_compliance_evidence
from knowledge_portal.generators.cve_ingestor import generate_cve_report
from knowledge_portal.generators.stack_inventory import generate_stack_inventory
from knowledge_portal.generators.llms_txt import generate_llms_manifests
from knowledge_portal.generators.git_dag import generate_git_dag
from knowledge_portal.generators.adr_graph import generate_adr_graph
from knowledge_portal.generators.mission_control import generate_mission_control
from knowledge_portal.generators.test_oracle import generate_test_oracle
from knowledge_portal.generators.module_cards import generate_module_cards
from knowledge_portal.generators.agent_instructions_audit import generate_agent_instructions_audit
from knowledge_portal.generators.sarif_ingestor import generate_sarif_findings
from knowledge_portal.generators.vertical_slices import generate_vertical_slices
from knowledge_portal.generators.async_topology import generate_async_topology

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

    # 2b. Generate Architectural Health, API Catalog, Call Graph, Ownership, Stack/SBOM & llms.txt manifests
    generate_arch_health(data_dir, project_dir=source_dir)
    generate_api_catalog(source_dir, data_dir)
    generate_call_graph(source_dir, data_dir)
    generate_vertical_slices(source_dir, data_dir)
    generate_async_topology(source_dir, data_dir)
    generate_ownership_map(source_dir, data_dir)
    generate_config_matrix(source_dir, data_dir)
    generate_iac_topology(source_dir, data_dir)
    generate_ai_registry(source_dir, data_dir)
    generate_stack_inventory(source_dir, data_dir)
    generate_cve_report(source_dir, data_dir)
    generate_sarif_findings(source_dir, data_dir)
    generate_compliance_evidence(source_dir, data_dir)
    generate_git_dag(source_dir, data_dir)
    generate_adr_graph(source_dir, data_dir)
    generate_test_oracle(source_dir, data_dir)
    generate_module_cards(source_dir, data_dir)
    generate_agent_instructions_audit(source_dir, data_dir)
    generate_mission_control(source_dir, data_dir)
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
