import ast
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

BANNED_PATTERNS = [
    "os.system",
    "subprocess.call",
    "subprocess.Popen",
    "__import__",
    "eval(",
    "exec(",
    "shutil.rmtree",
    "sys.exit",
]


class ValidationError(Exception):
    pass


class ToolValidator:

    def validate(self, tool_name: str, source_code: str) -> bool:
        self._check_syntax(source_code)
        self._check_banned_patterns(source_code)
        self._check_function_exists(tool_name, source_code)
        self._run_import_test(tool_name, source_code)
        return True

    def _check_syntax(self, source_code: str):
        try:
            ast.parse(source_code)
        except SyntaxError as e:
            raise ValidationError(f"Syntax error: {e}")

    def _check_banned_patterns(self, source_code: str):
        for pattern in BANNED_PATTERNS:
            if pattern in source_code:
                raise ValidationError(f"Banned pattern detected: '{pattern}'")

    def _check_function_exists(self, tool_name: str, source_code: str):
        tree = ast.parse(source_code)
        functions = [
            node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
        ]
        if tool_name not in functions:
            raise ValidationError(
                f"Function '{tool_name}' not found. Found: {functions}"
            )

    def _run_import_test(self, tool_name: str, source_code: str):
        test_script = textwrap.dedent(
            f"""
import sys
try:
{textwrap.indent(source_code, "    ")}
    assert callable({tool_name}), "Not callable"
    print("OK")
except Exception as e:
    print(f"FAIL: {{e}}", file=sys.stderr)
    sys.exit(1)
"""
        )
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(test_script)
            tmp_path = f.name

        try:
            result = subprocess.run(
                [sys.executable, tmp_path],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode != 0:
                raise ValidationError(
                    f"Runtime validation failed: {result.stderr.strip()}"
                )
        except subprocess.TimeoutExpired:
            raise ValidationError("Validation timed out (10s limit)")
        finally:
            Path(tmp_path).unlink(missing_ok=True)
