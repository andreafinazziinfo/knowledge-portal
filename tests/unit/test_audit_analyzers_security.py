"""Regression tests for EVAL_EXEC & security_hygiene false-positive/false-negative accuracy."""

from __future__ import annotations

from pathlib import Path

from knowledge_portal.generators.audit_analyzers import analyze_extended_health_checks


def test_js_ts_regexp_exec_and_method_calls_are_not_flagged(tmp_path: Path) -> None:
    """RegExp.exec(...) and method calls .exec()/.eval() in JS/TS/Vue must not trigger EVAL_EXEC."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "parser.ts").write_text(
        """
const LABEL_RE = /^T([+-]\\d+)?/;
export function parseLabel(label: string): number {
  const m = LABEL_RE.exec(label.trim());
  const n = /^T(?:([+-]\\d+))?$/.exec(label);
  const fence = /^```(?:json)?\\s*([\\s\\S]*?)```\\s*$/i.exec(label);
  const dyn = new RegExp("[*:?+]").exec(label);
  const custom = helper.eval(label);
  return m && n && fence && dyn && custom ? 1 : 0;
}
""".lstrip(),
        encoding="utf-8",
    )
    (tmp_path / "src" / "Section.vue").write_text(
        """
<script setup lang="ts">
function color(label: string): string {
  const m = /^T([+-]\\d+)?/.exec(label);
  return m ? "#f59e0b" : "#94a3b8";
}
</script>
""".lstrip(),
        encoding="utf-8",
    )

    res = analyze_extended_health_checks(tmp_path)
    assert res["security_hygiene"]["findings_count"] == 0
    assert res["security_hygiene"]["findings"] == []


def test_generated_pwa_dev_dist_and_workbox_are_excluded(tmp_path: Path) -> None:
    """Generated build artifacts in dev-dist/, dist/, and workbox-*.js must be ignored."""
    (tmp_path / "frontend" / "dev-dist").mkdir(parents=True)
    (tmp_path / "frontend" / "dev-dist" / "workbox-5b2a77ea.js").write_text(
        "const r = regExp.exec(url.href);\neval(payload);\n",
        encoding="utf-8",
    )
    (tmp_path / "frontend" / "dist").mkdir(parents=True)
    (tmp_path / "frontend" / "dist" / "app.js").write_text("eval(x);\n", encoding="utf-8")
    (tmp_path / "frontend" / "public").mkdir(parents=True)
    (tmp_path / "frontend" / "public" / "workbox-deadbeef.js").write_text("eval(y);\n", encoding="utf-8")

    res = analyze_extended_health_checks(tmp_path)
    assert res["security_hygiene"]["findings_count"] == 0


def test_python_docstrings_comments_and_model_eval_are_not_flagged(tmp_path: Path) -> None:
    """Python docstrings, comments, and .eval() method calls (e.g. PyTorch model.eval()) must not trigger findings."""
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "sandbox.py").write_text(
        '''"""
Read-only AST sandbox that runs queries without using eval()/exec(),
and documents docs/eval (golden set) and shell=True hygiene checks.
"""


class Sandbox:
    """Strictly allowlisted interpreter — never calls Python eval()/exec()."""

    def evaluate(self, model):
        # Never call eval(user_input) or exec(code) here
        model.eval()  # PyTorch inference mode; not builtin eval(x)
        return True
''',
        encoding="utf-8",
    )

    res = analyze_extended_health_checks(tmp_path)
    assert res["security_hygiene"]["findings_count"] == 0


def test_js_comments_mentioning_eval_are_not_flagged(tmp_path: Path) -> None:
    """Single-line and multi-line JS/TS comments mentioning eval() must be ignored."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "safe.ts").write_text(
        """
/**
 * Safe expression evaluator — never uses eval(expr) or window.eval(expr).
 */
export function safeCalc(a: number, b: number): number {
  /* Do not replace with eval(a + b) */
  // Avoid eval(input)
  return a + b; // inline comment mentioning eval(x)
}
""".lstrip(),
        encoding="utf-8",
    )

    res = analyze_extended_health_checks(tmp_path)
    assert res["security_hygiene"]["findings_count"] == 0


def test_true_positives_python_and_js_eval_exec_are_detected(tmp_path: Path) -> None:
    """Real Python eval()/exec() and JS eval()/window.eval()/globalThis.eval() must still be detected."""
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "danger.py").write_text(
        """import builtins

def run_bad(user_input: str, code: str) -> None:
    eval(user_input)
    exec(code)
    builtins.eval(user_input)
    builtins.exec(code)
    eval(user_input)  # nosec
""",
        encoding="utf-8",
    )
    (tmp_path / "web").mkdir()
    (tmp_path / "web" / "danger.js").write_text(
        """function bad(x) {
  eval(x);
  window.eval(x);
  globalThis.eval(x);
  eval(x); // nosec
}
""",
        encoding="utf-8",
    )

    res = analyze_extended_health_checks(tmp_path)
    findings = res["security_hygiene"]["findings"]
    eval_findings = [(f["path"], f["line"], f["rule"]) for f in findings]

    assert ("app/danger.py", 4, "EVAL_EXEC") in eval_findings
    assert ("app/danger.py", 5, "EVAL_EXEC") in eval_findings
    assert ("app/danger.py", 6, "EVAL_EXEC") in eval_findings
    assert ("app/danger.py", 7, "EVAL_EXEC") in eval_findings
    assert ("app/danger.py", 8, "EVAL_EXEC") not in eval_findings  # nosec

    assert ("web/danger.js", 2, "EVAL_EXEC") in eval_findings
    assert ("web/danger.js", 3, "EVAL_EXEC") in eval_findings
    assert ("web/danger.js", 4, "EVAL_EXEC") in eval_findings
    assert ("web/danger.js", 5, "EVAL_EXEC") not in eval_findings  # nosec
    assert len(eval_findings) == 7
