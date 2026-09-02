import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent.paths import get_paths

MEMORY_PATH = get_paths().state / "memory.json"


def _ensure_memory_dir() -> None:
    MEMORY_PATH.parent.mkdir(parents=True, exist_ok=True)

_MAX_STR_LEN = 2000
_REGRESSION_CAP = 5


def _redact(value: Any, max_len: int = _MAX_STR_LEN) -> Any:
    try:
        s = json.dumps(value, default=str, ensure_ascii=False)
    except Exception:
        s = str(value)
    if len(s) > max_len:
        return s[:max_len] + f"... [truncated {len(s)-max_len} chars]"
    return value


def _safe_serialize(value: Any) -> Any:
    try:
        json.dumps(value, default=str)
        return _redact(value)
    except Exception:
        return _redact(str(value))


class ExperienceMemory:
    def __init__(self, path: Path | None = None):
        self._path = path or MEMORY_PATH
        self._data: dict[str, list[dict]] = self._load()

    def _load(self) -> dict[str, list[dict]]:
        if self._path.exists():
            try:
                raw = json.loads(self._path.read_text())
                if isinstance(raw, dict):
                    return raw
            except Exception as e:
                print(f"[Memory] Failed to load {self._path}: {e}")
        return {}

    def _save(self):
        _ensure_memory_dir()
        self._path.write_text(json.dumps(self._data, indent=2, default=str))

    def record(
        self,
        tool_name: str,
        args: dict,
        success: bool,
        result_or_error: Any,
        latency_ms: float,
    ) -> dict:
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "args": _safe_serialize(args if isinstance(args, dict) else {"_args": args}),
            "success": bool(success),
            "result_or_error": _safe_serialize(result_or_error),
            "latency_ms": round(float(latency_ms), 2),
        }
        # Normalize tool_name: strip default. prefix if present
        key = tool_name.removeprefix("default.")
        if key not in self._data:
            self._data[key] = []
        self._data[key].append(entry)
        self._save()
        return entry

    def get_history(self, tool_name: str) -> list[dict]:
        key = tool_name.removeprefix("default.")
        return list(self._data.get(key, []))

    def get_regression_examples(self, tool_name: str, n: int = _REGRESSION_CAP) -> list[dict]:
        key = tool_name.removeprefix("default.")
        history = self._data.get(key, [])
        successes = [h for h in history if h.get("success") is True]
        last_n = successes[-n:] if n > 0 else []
        examples = []
        for h in last_n:
            examples.append({"args": h.get("args", {}), "expected": h.get("result_or_error")})
        return examples

    def all_tool_names(self) -> list[str]:
        return list(self._data.keys())

    def all_history(self) -> dict[str, list[dict]]:
        return {k: list(v) for k, v in self._data.items()}

    def clear(self, tool_name: str | None = None):
        if tool_name is None:
            self._data = {}
        else:
            key = tool_name.removeprefix("default.")
            self._data.pop(key, None)
        self._save()


memory = ExperienceMemory()
