import json
from pathlib import Path
from knowledge_portal.generators.stack_inventory import generate_stack_inventory


def test_generate_stack_inventory(tmp_path: Path):
    proj = tmp_path / "demo_proj"
    proj.mkdir()
    (proj / "requirements.txt").write_text("fastapi>=0.115.0\nredis>=5.0.0 # pubsub\n", encoding="utf-8")
    (proj / "package.json").write_text(json.dumps({
        "name": "demo-fe",
        "dependencies": {"vue": "^3.5.0"},
        "devDependencies": {"vitest": "^4.0.0"}
    }), encoding="utf-8")
    (proj / "docker-compose.yml").write_text(
        "services:\n  api:\n    image: python:3.12-slim\n  cache:\n    image: redis:7-alpine\n",
        encoding="utf-8"
    )
    wf = proj / ".github" / "workflows"
    wf.mkdir(parents=True)
    (wf / "ci.yml").write_text("name: CI\n", encoding="utf-8")

    out_dir = tmp_path / "out" / "data"
    payload = generate_stack_inventory(proj, out_dir)

    assert payload["summary"]["python_dependencies"] == 2
    assert payload["summary"]["node_dependencies"] == 2
    assert payload["summary"]["docker_services"] == 2
    assert payload["summary"]["tools_and_ci"] >= 1
    assert (out_dir / "stack-ecosystem.json").is_file()
    assert (out_dir / "stack_ecosystem.js").is_file()
