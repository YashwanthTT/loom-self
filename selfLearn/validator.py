"""Validator — AST + smoke test, no deprecated libs."""
import ast
import logging
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

logger = logging.getLogger(__name__)

_BANNED_BUILTIN_CALLS = {"eval", "exec", "compile", "__import__", "globals", "locals"}
_BANNED_ATTRIBUTE_CALLS = {
    ("os", "system"), ("os", "popen"), ("os", "remove"), ("os", "unlink"), ("os", "rmdir"),
    ("subprocess", "Popen"), ("subprocess", "call"), ("subprocess", "check_call"),
    ("subprocess", "getoutput"), ("subprocess", "getstatusoutput"),
    ("shutil", "rmtree"), ("shutil", "chown"), ("sys", "exit"), ("os", "_exit"), ("os", "kill"),
    ("signal", "signal"),
}
_BANNED_METHOD_NAMES = {"unlink", "rmdir", "kill", "terminate"}


class ValidationError(Exception):
    pass


class _BannedCallVisitor(ast.NodeVisitor):
    def __init__(self):
        self.violations: list[str] = []

    def visit_Call(self, node: ast.Call):
        func = node.func
        if isinstance(func, ast.Name) and func.id in _BANNED_BUILTIN_CALLS:
            self.violations.append(f"banned builtin: {func.id}()")
        elif isinstance(func, ast.Attribute):
            root = func
            while isinstance(root, ast.Attribute):
                root = root.value
            if isinstance(root, ast.Name) and (root.id, func.attr) in _BANNED_ATTRIBUTE_CALLS:
                self.violations.append(f"banned call: {root.id}.{func.attr}()")
            elif func.attr in _BANNED_METHOD_NAMES:
                self.violations.append(f"banned method: .{func.attr}()")
        self.generic_visit(node)


class ToolValidator:
    def validate(self, tool_name: str, source_code: str) -> bool:
        self._check_syntax(source_code)
        self._check_banned_calls(source_code)
        self._check_function_exists(tool_name, source_code)
        self._run_import_test(tool_name, source_code)
        return True

    def _check_syntax(self, source_code: str):
        try:
            ast.parse(source_code)
        except SyntaxError as e:
            raise ValidationError(f"Syntax error: {e}")

    def _check_banned_calls(self, source_code: str):
        tree = ast.parse(source_code)
        v = _BannedCallVisitor()
        v.visit(tree)
        if v.violations:
            raise ValidationError(f"Banned pattern: {v.violations[0]}" + (f" (+{len(v.violations)-1} more)" if len(v.violations) > 1 else ""))

    def _check_function_exists(self, tool_name: str, source_code: str):
        tree = ast.parse(source_code)
        funcs = [n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
        if tool_name not in funcs:
            raise ValidationError(f"Function '{tool_name}' not found. Found: {funcs}")

    def _run_import_test(self, tool_name: str, source_code: str):
        script = textwrap.dedent(f"""
import sys
try:
{textwrap.indent(source_code, "    ")}
    assert callable({tool_name}), "Not callable"
    print("OK")
except Exception as e:
    print(f"FAIL: {{e}}", file=sys.stderr)
    sys.exit(1)
""")
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(script)
            tmp = f.name
        try:
            r = subprocess.run([sys.executable, tmp], capture_output=True, text=True, timeout=10)
            if r.returncode != 0:
                raise ValidationError(f"Runtime validation failed: {r.stderr.strip()}")
        except subprocess.TimeoutExpired:
            raise ValidationError("Validation timed out (10s)")
        finally:
            Path(tmp).unlink(missing_ok=True)
