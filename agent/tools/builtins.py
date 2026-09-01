"""Built-ins: read, edit, bash."""
import os
import subprocess

from pydantic import BaseModel, Field

MAX_CHARS = 8000


class ReadArgs(BaseModel):
    file_path: str = Field(description="Path to read")


class EditArgs(BaseModel):
    file_path: str = Field(description="Path to edit")
    old_string: str = Field(description="Exact string to replace")
    new_string: str = Field(description="Replacement string")


class BashArgs(BaseModel):
    command: str = Field(description="Bash command")
    timeout: int = Field(default=60, ge=1, le=600)


def _clip(t: str, n: int = MAX_CHARS) -> str:
    return t if len(t) <= n else t[:n] + f"\n… [truncated {len(t)-n}]"


def read_file(file_path: str = "") -> dict:
    if not file_path or not isinstance(file_path, str):
        return {"success": False, "error": "file_path required"}
    if not os.path.exists(file_path):
        return {"success": False, "error": f"not found: {file_path}"}
    if os.path.isdir(file_path):
        return {"success": False, "error": f"is directory: {file_path}"}
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
    except UnicodeDecodeError:
        with open(file_path, "r", encoding="latin-1") as f:
            content = f.read()
    return {"success": True, "content": _clip(content), "file_path": file_path}


def edit_file(file_path: str = "", old_string: str = "", new_string: str = "") -> dict:
    if not file_path or not isinstance(file_path, str):
        return {"success": False, "error": "file_path required"}
    if old_string is None or old_string == "":
        return {"success": False, "error": "old_string required (exact match)"}
    if not os.path.exists(file_path):
        return {"success": False, "error": f"not found: {file_path}"}
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
    except UnicodeDecodeError:
        with open(file_path, "r", encoding="latin-1") as f:
            content = f.read()
    if old_string not in content:
        return {"success": False, "error": "old_string not found"}
    new_content = content.replace(old_string, new_string, 1)
    os.makedirs(os.path.dirname(os.path.abspath(file_path)) or ".", exist_ok=True)
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(new_content)
    return {"success": True, "file_path": file_path}


def run_bash(command: str = "", timeout: int = 60) -> dict:
    if not command or not isinstance(command, str) or not command.strip():
        return {"success": False, "error": "command required", "returncode": -1}
    timeout = max(1, min(int(timeout), 600))
    try:
        proc = subprocess.run(["bash", "-lc", command], capture_output=True, text=True, timeout=timeout)
        return {"success": proc.returncode == 0, "returncode": proc.returncode, "stdout": _clip(proc.stdout), "stderr": _clip(proc.stderr)}
    except subprocess.TimeoutExpired:
        return {"success": False, "error": f"timeout {timeout}s", "returncode": -1}
    except Exception as e:
        return {"success": False, "error": str(e), "returncode": -1}


BUILTIN_TOOLS = [
    {"name": "read_file", "func": read_file, "description": "Read a text file", "args_schema": ReadArgs},
    {"name": "edit_file", "func": edit_file, "description": "Edit a file via exact old_string → new_string", "args_schema": EditArgs},
    {"name": "run_bash", "func": run_bash, "description": "Run a bash command", "args_schema": BashArgs},
]
