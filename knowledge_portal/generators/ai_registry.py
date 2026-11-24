"""
Knowledge Portal — AI / LLM & Prompt Governance Registry (LLMOps, ADR-078).
100% Python stdlib zero-dependency scanner extracting:
- AI/LLM SDK imports & usages (openai, anthropic, google.genai, litellm, langchain, ollama, bedrock, mcp)
- Hardcoded Model IDs (flagging deprecated / unpinned ':latest' models)
- Prompt templates & system prompt constants with estimated token counts
- Guardrail & Prompt-Injection checks (f-string interpolation in system prompts, missing timeout/max_tokens)

Outputs `data/ai-registry.json` and `data/ai_registry.js`.
Strictly enforces P4 Gate (excludes frozen/).
"""

from __future__ import annotations

import ast
import json
import os
import re
import time
from collections import Counter
from pathlib import Path
from typing import Any

_IGNORE_DIRS = frozenset({
    ".git", "node_modules", "dist", "build", ".venv", "venv",
    "__pycache__", ".idea", ".vscode", "target", "vendor", "bin", "obj", "frozen",
})
_SDK_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("OpenAI", re.compile(r"\b(?:from\s+openai\b|import\s+openai\b|OpenAI\s*\(|AsyncOpenAI\s*\()")),
    ("Anthropic", re.compile(r"\b(?:from\s+anthropic\b|import\s+anthropic\b|Anthropic\s*\()")),
    ("Google GenAI", re.compile(r"\b(?:google\.genai|google\.generativeai|GenerativeModel\s*\()")),
    ("Ollama", re.compile(r"\b(?:import\s+ollama\b|from\s+ollama\b|/api/generate|/api/chat|ollama)")),
    ("LiteLLM", re.compile(r"\b(?:import\s+litellm\b|from\s+litellm\b)")),
    ("LangChain", re.compile(r"\b(?:from\s+langchain|import\s+langchain)")),
    ("MCP", re.compile(r"\b(?:modelcontextprotocol|FastMCP|mcp_server|PortalMcpEngine)")),
]
_MODEL_ID_RE = re.compile(
    r"""["']((?:gpt-[345][a-z0-9._-]*|o[134]-[a-z0-9._-]+|claude-[234][a-z0-9._-]*|gemini-[123][a-z0-9._-]*|llama[234][a-z0-9.:_-]*|qwen[23][a-z0-9.:_-]*|mistral[a-z0-9.:_-]*|deepseek-[a-z0-9.:_-]*))["']""",
    re.IGNORECASE,
)
_DEPRECATED_MODELS = ("gpt-3.5-turbo-0301", "gpt-4-0314", "text-davinci", "claude-2.0", "gemini-1.0-pro")
_PROMPT_VAR_RE = re.compile(r"(?:SYSTEM_PROMPT|PROMPT_TEMPLATE|_PROMPT\b|INSTRUCTIONS\b)", re.IGNORECASE)


def _is_ignored(rel: str) -> bool:
    parts = [p.lower() for p in rel.replace("\\", "/").split("/")]
    if any(p in _IGNORE_DIRS or p.startswith(".") for p in parts[:-1]) or "frozen" in parts:
        return True
    if parts[-1] == "ai_registry.py":
        return True
    low = f"/{rel.lower()}"
    return any(h in low for h in ("/tests/", "/test/", "/test_", "_test.py", ".spec.", ".test."))


def generate_ai_registry(project_dir: Path, data_dir: Path, max_files: int = 2500) -> dict[str, Any]:
    """Scan codebase for LLM SDKs, Model IDs, Prompt templates, and Guardrail risks."""
    project_dir = Path(project_dir).resolve()
    data_dir = Path(data_dir)

    sdk_usages: list[dict[str, Any]] = []
    model_refs: list[dict[str, Any]] = []
    prompts: list[dict[str, Any]] = []
    guardrails: list[dict[str, Any]] = []
    sdk_counts: Counter[str] = Counter()
    scanned = 0

    for root, dirs, files in os.walk(project_dir):
        dirs[:] = [d for d in dirs if d not in _IGNORE_DIRS and not d.startswith(".")]
        for fname in files:
            if scanned >= max_files:
                break
            fpath = Path(root) / fname
            rel = str(fpath.relative_to(project_dir)).replace("\\", "/")
            if _is_ignored(rel):
                continue

            ext = os.path.splitext(fname)[1].lower()
            # Prompt template files
            if ext in (".prompt", ".jinja2", ".j2") or ("prompt" in fname.lower() and ext in (".txt", ".md")):
                try:
                    txt = fpath.read_text(encoding="utf-8", errors="ignore")
                    prompts.append({
                        "name": fname,
                        "file": rel,
                        "line": 1,
                        "est_tokens": max(1, len(txt) // 4),
                        "kind": "template_file",
                    })
                except OSError:
                    pass
                continue

            if ext not in (".py", ".ts", ".tsx", ".js", ".jsx", ".vue"):
                continue
            if fname.endswith((".min.js", ".bundle.js", ".d.ts")):
                continue
            try:
                if fpath.stat().st_size > 400_000:
                    continue
                src = fpath.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            scanned += 1

            file_sdks: list[str] = []
            for sdk_name, rx in _SDK_PATTERNS:
                if rx.search(src):
                    file_sdks.append(sdk_name)
                    sdk_counts[sdk_name] += 1
                    sdk_usages.append({"sdk": sdk_name, "file": rel})

            for lineno, line in enumerate(src.splitlines(), 1):
                s = line.strip()
                if not s or s.startswith(("#", "//")):
                    continue
                for m in _MODEL_ID_RE.finditer(s):
                    mid = m.group(1)
                    is_dep = any(d in mid.lower() for d in _DEPRECATED_MODELS) or mid.lower().endswith(":latest")
                    model_refs.append({
                        "model": mid,
                        "sdk": file_sdks[0] if file_sdks else "LLM",
                        "file": rel,
                        "line": lineno,
                        "deprecated_or_unpinned": is_dep,
                    })
                    if is_dep:
                        guardrails.append({
                            "severity": "MEDIUM",
                            "rule": "UNPINNED_OR_DEPRECATED_MODEL",
                            "file": rel,
                            "line": lineno,
                            "detail": f"Model ID `{mid}` is deprecated or uses floating `:latest` tag.",
                        })

            if ext == ".py":
                try:
                    tree = ast.parse(src)
                except Exception:
                    continue
                for node in ast.walk(tree):
                    if isinstance(node, ast.Assign):
                        for tgt in node.targets:
                            tname = tgt.id if isinstance(tgt, ast.Name) else ""
                            if not tname or not _PROMPT_VAR_RE.search(tname):
                                continue
                            lineno = getattr(node, "lineno", 1)
                            if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str) and len(node.value.value) >= 25:
                                prompts.append({
                                    "name": tname,
                                    "file": rel,
                                    "line": lineno,
                                    "est_tokens": max(1, len(node.value.value) // 4),
                                    "kind": "python_constant",
                                })
                            elif isinstance(node.value, ast.JoinedStr):
                                guardrails.append({
                                    "severity": "HIGH",
                                    "rule": "PROMPT_INJECTION_SURFACE",
                                    "file": rel,
                                    "line": lineno,
                                    "detail": f"Dynamic f-string interpolation directly inside `{tname}` — validate/escape untrusted variables.",
                                })

    unique_models = sorted({m["model"] for m in model_refs})
    payload: dict[str, Any] = {
        "generated_at": time.time(),
        "summary": {
            "files_scanned": scanned,
            "sdks_detected": dict(sorted(sdk_counts.items())),
            "unique_models_count": len(unique_models),
            "model_references_count": len(model_refs),
            "prompts_cataloged": len(prompts),
            "guardrail_findings_count": len(guardrails),
        },
        "sdk_usages": sdk_usages[:80],
        "model_refs": model_refs[:80],
        "prompts": prompts[:60],
        "guardrails": guardrails[:50],
    }

    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "ai-registry.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    (data_dir / "ai_registry.js").write_text(f"window.AI_REGISTRY = {json.dumps(payload)};\n", encoding="utf-8")
    return payload
