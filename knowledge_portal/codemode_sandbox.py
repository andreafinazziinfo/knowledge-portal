"""
Knowledge Portal — Cloudflare-Style Code Mode Read-Only AST Sandbox (ADR-069).
Evaluates multi-step Python query pipelines against a read-only `portal` SDK
without using eval()/exec(), without imports, without I/O, and without access
to private/dunder attributes. 100% Python stdlib zero-dependency.
"""

from __future__ import annotations

import ast
import json
import operator
from typing import Any, Callable

MAX_STEPS = 5000
MAX_OUTPUT_BYTES = 32_768
MAX_CODE_BYTES = 8_192


class CodeModeSecurityError(ValueError):
    """Raised when a Code Mode script attempts a disallowed operation."""


class CodeModeLimitError(RuntimeError):
    """Raised when a Code Mode script exceeds step or output limits."""


_BIN_OPS: dict[type[ast.operator], Callable[[Any, Any], Any]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
}

_UNARY_OPS: dict[type[ast.unaryop], Callable[[Any], Any]] = {
    ast.Not: operator.not_,
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}

_CMP_OPS: dict[type[ast.cmpop], Callable[[Any, Any], bool]] = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
    ast.In: lambda a, b: a in b,
    ast.NotIn: lambda a, b: a not in b,
    ast.Is: operator.is_,
    ast.IsNot: operator.is_not,
}

_SAFE_LIST_METHODS = frozenset({"append", "extend", "count", "index"})
_SAFE_DICT_METHODS = frozenset({"get", "keys", "values", "items"})
_SAFE_STR_METHODS = frozenset({
    "lower", "upper", "strip", "lstrip", "rstrip", "startswith", "endswith",
    "split", "rsplit", "join", "replace", "find", "count",
})


class PortalReadOnlySDK:
    """Explicit allowlisted read-only SDK exposed as `portal` inside Code Mode."""

    ALLOWED_METHODS = frozenset({
        "search",
        "neighbors",
        "impact",
        "flows",
        "schema",
        "stack",
        "health",
        "telemetry",
        "context_pack",
        "read_doc",
    })

    def __init__(self, engine: Any) -> None:
        self._engine = engine

    def search(self, query: str, limit: int = 15) -> dict[str, Any]:
        return self._engine.search(query, limit=limit)

    def neighbors(self, node_id: str, depth: int = 1) -> dict[str, Any]:
        return self._engine.graph_neighbors(node_id, depth=depth)

    def impact(self, target: str, max_depth: int = 3) -> dict[str, Any]:
        return self._engine.impact(target, max_depth=max_depth)

    def flows(self, query: str = "", limit: int = 10) -> dict[str, Any]:
        return self._engine.process_flow(query=query, limit=limit)

    def schema(self, table: str = "") -> dict[str, Any]:
        return self._engine.db_schema(table=table)

    def stack(self) -> dict[str, Any]:
        return self._engine.stack()

    def health(self) -> dict[str, Any]:
        return self._engine.health_audit()

    def telemetry(self) -> dict[str, Any]:
        return self._engine.telemetry()

    def context_pack(self, topic: str, max_tokens: int = 4000) -> dict[str, Any]:
        return self._engine.context_pack(topic, max_tokens=max_tokens)

    def read_doc(self, path: str, max_chars: int = 8000) -> dict[str, Any]:
        return self._engine.read_doc(path, max_chars=max_chars)


def get_codemode_sdk_reference(topic: str = "") -> dict[str, Any]:
    """Return typed SDK reference for `portal_discover` (~1k token footprint)."""
    methods = [
        {"call": "portal.search(query, limit=15)", "returns": "{query, engine, count, results: [{name, category, path, tab, subtitle}]}"},
        {"call": "portal.neighbors(node_id, depth=1)", "returns": "{query, depth, matched_nodes, neighbors, edges}"},
        {"call": "portal.impact(target, max_depth=3)", "returns": "{target, risk, counts: {d1, d2, d3, total}, by_depth, affected_flows}"},
        {"call": "portal.flows(query='', limit=10)", "returns": "{query, count, flows}"},
        {"call": "portal.schema(table='')", "returns": "{table, count, tables}"},
        {"call": "portal.stack()", "returns": "Technology stack inventory dict"},
        {"call": "portal.health()", "returns": "{summary: {health_score, grade, cycle_count, orphan_count, ...}, cycles, orphans, god_files, layer_violations}"},
        {"call": "portal.telemetry()", "returns": "Live host & portal sync telemetry dict"},
        {"call": "portal.context_pack(topic, max_tokens=4000)", "returns": "{topic, estimated_tokens, markdown}"},
        {"call": "portal.read_doc(path, max_chars=8000)", "returns": "{path, content, truncated}"},
    ]
    q = (topic or "").strip().lower()
    if q:
        filtered = [m for m in methods if q in m["call"].lower() or q in m["returns"].lower()]
        if filtered:
            methods = filtered
    return {
        "mode": "cloudflare-style-codemode-readonly",
        "usage": "Write a short Python snippet using `portal.<method>(...)` and assign the final value to `result` (or end with an expression). Imports, I/O, and private attributes are blocked.",
        "builtins": ["len", "sorted", "min", "max", "sum", "any", "all", "list", "dict", "set", "tuple", "str", "int", "float", "bool", "round", "enumerate", "zip", "range"],
        "methods": methods,
    }


class _SafeAstEvaluator:
    """Strictly allowlisted AST interpreter — never calls Python eval()/exec()."""

    def __init__(self, sdk: PortalReadOnlySDK, max_steps: int = MAX_STEPS) -> None:
        self._sdk = sdk
        self._max_steps = max_steps
        self._steps = 0
        self._env: dict[str, Any] = {
            "portal": sdk,
            "len": len,
            "min": min,
            "max": max,
            "sum": sum,
            "any": any,
            "all": all,
            "list": list,
            "dict": dict,
            "set": set,
            "tuple": tuple,
            "str": str,
            "int": int,
            "float": float,
            "bool": bool,
            "round": round,
            "enumerate": enumerate,
            "zip": zip,
            "range": lambda *a: range(*a) if (not a or abs(a[0]) <= 2000) else (_ for _ in ()).throw(CodeModeLimitError("range limit exceeded")),
            "sorted": self._safe_sorted,
        }

    def _tick(self) -> None:
        self._steps += 1
        if self._steps > self._max_steps:
            raise CodeModeLimitError(f"Execution exceeded max step budget ({self._max_steps})")

    def _safe_sorted(self, iterable: Any, key: Any = None, reverse: bool = False) -> list[Any]:
        if key is not None and not callable(key):
            raise CodeModeSecurityError("sorted() key must be a safe lambda")
        return sorted(iterable, key=key, reverse=bool(reverse))

    def run(self, code: str) -> Any:
        if not isinstance(code, str) or not code.strip():
            raise CodeModeSecurityError("Empty code snippet")
        if len(code.encode("utf-8")) > MAX_CODE_BYTES:
            raise CodeModeLimitError(f"Code exceeds {MAX_CODE_BYTES} byte limit")
        try:
            tree = ast.parse(code, mode="exec")
        except SyntaxError as exc:
            raise CodeModeSecurityError(f"Syntax error: {exc}") from exc

        last_val: Any = None
        for stmt in tree.body:
            last_val = self._exec_stmt(stmt)

        if "result" in self._env:
            return self._env["result"]
        return last_val

    def _exec_stmt(self, node: ast.stmt) -> Any:
        self._tick()
        if isinstance(node, ast.Expr):
            return self._eval_expr(node.value)
        if isinstance(node, ast.Assign):
            val = self._eval_expr(node.value)
            for target in node.targets:
                self._assign_target(target, val)
            return val
        if isinstance(node, ast.AugAssign):
            if not isinstance(node.target, ast.Name):
                raise CodeModeSecurityError("Augmented assignment only supported on variable names")
            op_fn = _BIN_OPS.get(type(node.op))
            if op_fn is None:
                raise CodeModeSecurityError(f"Disallowed operator: {type(node.op).__name__}")
            cur = self._lookup_name(node.target.id)
            new_val = op_fn(cur, self._eval_expr(node.value))
            self._set_name(node.target.id, new_val)
            return new_val
        if isinstance(node, ast.If):
            branch = node.body if self._eval_expr(node.test) else node.orelse
            res = None
            for s in branch:
                res = self._exec_stmt(s)
            return res
        if isinstance(node, ast.For):
            iterable = self._eval_expr(node.iter)
            res = None
            for item in iterable:
                self._tick()
                self._assign_target(node.target, item)
                for s in node.body:
                    res = self._exec_stmt(s)
            return res
        if isinstance(node, ast.Pass):
            return None
        raise CodeModeSecurityError(f"Disallowed statement: {type(node).__name__}")

    def _set_name(self, name: str, val: Any) -> None:
        if name.startswith("_") or name == "portal":
            raise CodeModeSecurityError(f"Cannot assign to protected identifier '{name}'")
        self._env[name] = val

    def _assign_target(self, target: ast.AST, val: Any) -> None:
        if isinstance(target, ast.Name):
            self._set_name(target.id, val)
        elif isinstance(target, (ast.Tuple, ast.List)):
            items = list(val)
            if len(items) != len(target.elts):
                raise CodeModeSecurityError("Unpacking length mismatch")
            for elt, item in zip(target.elts, items):
                self._assign_target(elt, item)
        elif isinstance(target, ast.Subscript):
            container = self._eval_expr(target.value)
            key = self._eval_expr(target.slice)
            if not isinstance(container, (dict, list)):
                raise CodeModeSecurityError("Subscript assignment only allowed on dict or list")
            container[key] = val
        else:
            raise CodeModeSecurityError(f"Disallowed assignment target: {type(target).__name__}")

    def _lookup_name(self, name: str) -> Any:
        if name.startswith("_"):
            raise CodeModeSecurityError(f"Access to private identifier '{name}' is blocked")
        if name not in self._env:
            raise CodeModeSecurityError(f"Unknown identifier '{name}'")
        return self._env[name]

    def _eval_expr(self, node: ast.AST) -> Any:
        self._tick()
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name):
            return self._lookup_name(node.id)
        if isinstance(node, ast.List):
            return [self._eval_expr(e) for e in node.elts]
        if isinstance(node, ast.Tuple):
            return tuple(self._eval_expr(e) for e in node.elts)
        if isinstance(node, ast.Set):
            return {self._eval_expr(e) for e in node.elts}
        if isinstance(node, ast.Dict):
            return {
                self._eval_expr(k): self._eval_expr(v)
                for k, v in zip(node.keys, node.values)
                if k is not None
            }
        if isinstance(node, ast.UnaryOp):
            op_fn = _UNARY_OPS.get(type(node.op))
            if op_fn is None:
                raise CodeModeSecurityError(f"Disallowed unary operator: {type(node.op).__name__}")
            return op_fn(self._eval_expr(node.operand))
        if isinstance(node, ast.BinOp):
            op_fn = _BIN_OPS.get(type(node.op))
            if op_fn is None:
                raise CodeModeSecurityError(f"Disallowed binary operator: {type(node.op).__name__}")
            return op_fn(self._eval_expr(node.left), self._eval_expr(node.right))
        if isinstance(node, ast.BoolOp):
            if isinstance(node.op, ast.And):
                val: Any = True
                for v in node.values:
                    val = self._eval_expr(v)
                    if not val:
                        return val
                return val
            if isinstance(node.op, ast.Or):
                val = False
                for v in node.values:
                    val = self._eval_expr(v)
                    if val:
                        return val
                return val
            raise CodeModeSecurityError("Disallowed BoolOp")
        if isinstance(node, ast.Compare):
            left = self._eval_expr(node.left)
            for op, comp in zip(node.ops, node.comparators):
                cmp_fn = _CMP_OPS.get(type(op))
                if cmp_fn is None:
                    raise CodeModeSecurityError(f"Disallowed comparator: {type(op).__name__}")
                right = self._eval_expr(comp)
                if not cmp_fn(left, right):
                    return False
                left = right
            return True
        if isinstance(node, ast.IfExp):
            return self._eval_expr(node.body) if self._eval_expr(node.test) else self._eval_expr(node.orelse)
        if isinstance(node, ast.Subscript):
            container = self._eval_expr(node.value)
            if isinstance(node.slice, ast.Slice):
                low = self._eval_expr(node.slice.lower) if node.slice.lower is not None else None
                up = self._eval_expr(node.slice.upper) if node.slice.upper is not None else None
                step = self._eval_expr(node.slice.step) if node.slice.step is not None else None
                return container[slice(low, up, step)]
            return container[self._eval_expr(node.slice)]
        if isinstance(node, ast.ListComp):
            return self._eval_comp(node.generators, lambda: self._eval_expr(node.elt))
        if isinstance(node, ast.SetComp):
            return set(self._eval_comp(node.generators, lambda: self._eval_expr(node.elt)))
        if isinstance(node, ast.DictComp):
            pairs = self._eval_comp(
                node.generators,
                lambda: (self._eval_expr(node.key), self._eval_expr(node.value)),
            )
            return dict(pairs)
        if isinstance(node, ast.Lambda):
            arg_names = [a.arg for a in node.args.args]
            if any(a.startswith("_") for a in arg_names):
                raise CodeModeSecurityError("Lambda argument cannot start with '_'")

            def _safe_lambda(*args: Any) -> Any:
                if len(args) != len(arg_names):
                    raise CodeModeSecurityError("Lambda argument count mismatch")
                saved = {k: self._env.get(k) for k in arg_names}
                existed = {k: (k in self._env) for k in arg_names}
                try:
                    for k, v in zip(arg_names, args):
                        self._env[k] = v
                    return self._eval_expr(node.body)
                finally:
                    for k in arg_names:
                        if existed[k]:
                            self._env[k] = saved[k]
                        else:
                            self._env.pop(k, None)

            return _safe_lambda
        if isinstance(node, ast.Attribute):
            return self._eval_attribute(node)
        if isinstance(node, ast.Call):
            return self._eval_call(node)
        if isinstance(node, ast.JoinedStr):
            return "".join(str(self._eval_expr(v)) for v in node.values)
        if isinstance(node, ast.FormattedValue):
            return self._eval_expr(node.value)
        raise CodeModeSecurityError(f"Disallowed expression: {type(node).__name__}")

    def _eval_comp(self, generators: list[ast.comprehension], emit: Callable[[], Any]) -> list[Any]:
        results: list[Any] = []

        def _recurse(idx: int) -> None:
            if idx >= len(generators):
                results.append(emit())
                return
            gen = generators[idx]
            for item in self._eval_expr(gen.iter):
                self._tick()
                self._assign_target(gen.target, item)
                if all(self._eval_expr(cond) for cond in gen.ifs):
                    _recurse(idx + 1)

        _recurse(0)
        return results

    def _eval_attribute(self, node: ast.Attribute) -> Any:
        attr = node.attr
        if attr.startswith("_"):
            raise CodeModeSecurityError(f"Access to private/dunder attribute '{attr}' is blocked")
        obj = self._eval_expr(node.value)
        if isinstance(obj, PortalReadOnlySDK):
            if attr not in PortalReadOnlySDK.ALLOWED_METHODS:
                raise CodeModeSecurityError(f"Unknown portal method '{attr}'")
            return getattr(obj, attr)
        if isinstance(obj, dict) and attr in _SAFE_DICT_METHODS:
            return getattr(obj, attr)
        if isinstance(obj, list) and attr in _SAFE_LIST_METHODS:
            return getattr(obj, attr)
        if isinstance(obj, str) and attr in _SAFE_STR_METHODS:
            return getattr(obj, attr)
        raise CodeModeSecurityError(f"Disallowed attribute access '{attr}' on {type(obj).__name__}")

    def _eval_call(self, node: ast.Call) -> Any:
        fn = self._eval_expr(node.func)
        if not callable(fn):
            raise CodeModeSecurityError("Target is not callable")
        args = [self._eval_expr(a) for a in node.args]
        kwargs: dict[str, Any] = {}
        for kw in node.keywords:
            if kw.arg is None or kw.arg.startswith("_"):
                raise CodeModeSecurityError("Disallowed keyword argument")
            kwargs[kw.arg] = self._eval_expr(kw.value)
        return fn(*args, **kwargs)


def execute_codemode(engine: Any, code: str, max_steps: int = MAX_STEPS) -> dict[str, Any]:
    """Execute a read-only Code Mode pipeline and return a JSON-safe response."""
    sdk = PortalReadOnlySDK(engine)
    evaluator = _SafeAstEvaluator(sdk, max_steps=max_steps)
    raw_result = evaluator.run(code)
    serialized = json.dumps(raw_result, ensure_ascii=False, default=str)
    truncated = False
    if len(serialized.encode("utf-8")) > MAX_OUTPUT_BYTES:
        truncated = True
        serialized = serialized[:MAX_OUTPUT_BYTES] + "... [TRUNCATED]"
        return {
            "ok": True,
            "steps": evaluator._steps,
            "truncated": truncated,
            "result_preview": serialized,
        }
    return {
        "ok": True,
        "steps": evaluator._steps,
        "truncated": False,
        "result": json.loads(serialized),
    }
