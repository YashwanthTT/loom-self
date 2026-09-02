import json
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

from agent.memory import memory

# Reuse same timeout as validator
_TIMEOUT = 10


def _run_single(tool_name: str, source_code: str, args: dict) -> tuple[bool, str]:
    """Regression check: success examples must still return success!=False and no exception."""
    return _run_single_impl(tool_name, source_code, args, check_success=True)


def _run_single_no_crash(tool_name: str, source_code: str, args: dict) -> tuple[bool, str]:
    """Check that tool no longer crashes on failure args — success==False is allowed if graceful."""
    return _run_single_impl(tool_name, source_code, args, check_success=False)


def _run_single_impl(tool_name: str, source_code: str, args: dict, check_success: bool = True) -> tuple[bool, str]:
    # Write args to temp json file to avoid escaping issues, load in subprocess
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as af:
        json.dump(args, af, default=str)
        args_path = af.name

    # Build check snippet depending on mode
    if check_success:
        check_snippet = """
    if isinstance(result, dict) and result.get("success") is False:
        print(f"FAIL: returned success=False: {result}", file=sys.stderr)
        sys.exit(1)
    if result is None:
        print(f"FAIL: returned None", file=sys.stderr)
        sys.exit(1)"""
    else:
        check_snippet = """
    # For failure-case fix check: just ensure it doesn't crash and returns a dict (success flag may be False if graceful)
    if result is None:
        print(f"FAIL: returned None", file=sys.stderr)
        sys.exit(1)
    if not isinstance(result, dict):
        print(f"FAIL: expected dict result, got {type(result)}: {result}", file=sys.stderr)
        sys.exit(1)"""

    script = textwrap.dedent(
        f"""
import json
import sys
import traceback
from pathlib import Path

{source_code}

if not callable({tool_name}):
    print(f"FAIL: {{tool_name}} not callable", file=sys.stderr)
    sys.exit(1)

try:
    _args = json.loads(Path(r"{args_path}").read_text())
    result = {tool_name}(**_args)
{check_snippet}
    print("OK")
except Exception as e:
    traceback.print_exc(file=sys.stderr)
    print(f"FAIL: {{e}}", file=sys.stderr)
    sys.exit(1)
"""
    )
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(script)
        tmp_path = f.name
    try:
        result = subprocess.run(
            [sys.executable, tmp_path],
            capture_output=True,
            text=True,
            timeout=_TIMEOUT,
        )
        if result.returncode == 0 and "OK" in result.stdout:
            return True, ""
        err = (result.stderr or result.stdout).strip()
        if not err:
            err = f"exit {result.returncode}: {result.stdout.strip()}"
        return False, err[:2000]
    except subprocess.TimeoutExpired:
        return False, f"timeout ({_TIMEOUT}s limit)"
    finally:
        Path(tmp_path).unlink(missing_ok=True)
        Path(args_path).unlink(missing_ok=True)


def run_regression(tool_name: str, new_source: str | None = None, new_func=None) -> tuple[bool, list[str]]:
    """
    Replay stored regression examples for `tool_name` against `new_source`.

    Accepts either source string or callable (inspected). Runs each example in an
    isolated subprocess (same sandboxing as validator._run_import_test) so a bad
    rewrite cannot pollute the host process.

    Returns (all_passed, failure_reasons). If no regressions stored, all_passed=True.
    """
    key = tool_name.removeprefix("default.")
    # Resolve source
    if new_source is None and new_func is not None:
        try:
            import inspect
            new_source = inspect.getsource(new_func)
        except Exception:
            return False, [f"cannot get source from callable {new_func}: failed inspect"]
    if not new_source or not isinstance(new_source, str):
        return False, ["no source code provided for regression check"]

    examples = memory.get_regression_examples(key, n=5)
    if not examples:
        return True, []

    failures: list[str] = []
    for idx, ex in enumerate(examples, 1):
        args = ex.get("args", {})
        # Handle redacted args (string with truncation note) — skip
        if isinstance(args, str) and "truncated" in args:
            failures.append(f"example {idx}: args truncated/redacted, skipping: {args[:200]}")
            continue
        if not isinstance(args, dict):
            # memory may store {"_args": ...} if original args was not dict — try to extract
            if isinstance(args, dict) and "_args" in args:
                args = args["_args"]
            else:
                failures.append(f"example {idx}: args not a dict: {args}")
                continue
        ok, err = _run_single(key, new_source, args)
        if not ok:
            failures.append(f"example {idx} args={args} -> {err}")

    all_passed = len(failures) == 0
    return all_passed, failures


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python -m tests.regression_runner <tool_name> [source_file]")
        sys.exit(1)
    tool = sys.argv[1]
    from agent.paths import get_paths
    source_file = sys.argv[2] if len(sys.argv) > 2 else str(get_paths().tools / f"{tool}.py")
    p = Path(source_file)
    if not p.exists():
        print(f"source file not found: {p}")
        sys.exit(1)
    src = p.read_text()
    ok, fails = run_regression(tool, src)
    print(f"[Regression] tool={tool} examples={len(memory.get_regression_examples(tool))} all_passed={ok}")
    for f in fails:
        print(f"  - {f}")
    sys.exit(0 if ok else 1)
