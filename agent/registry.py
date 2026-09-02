"""Registry — modern, uses langchain_core (not deprecated langchain.tools)."""
import importlib.util
import json
import logging
from pathlib import Path
from typing import Callable, Optional

from langchain_core.tools import StructuredTool

from .paths import ensure_runtime_dirs, get_paths

logger = logging.getLogger(__name__)


def _tools_dir() -> Path:
    return get_paths().tools


def _manifest_path() -> Path:
    return _tools_dir() / "manifest.json"


class ToolRegistry:
    def __init__(self) -> None:
        ensure_runtime_dirs()
        self._tools: dict[str, StructuredTool] = {}
        self._builtin_names: set[str] = set()
        self._load_builtins()
        self._load_persisted_tools()

    @property
    def builtin_names(self) -> set[str]:
        return set(self._builtin_names)

    def register(self, name: str, func: Callable, description: str, args_schema: type | None = None) -> StructuredTool:
        tool = StructuredTool.from_function(func=func, name=name, description=description, args_schema=args_schema, handle_tool_error=True)
        self._tools[f"default.{name}"] = tool
        self._tools[name] = tool
        return tool

    def get(self, name: str) -> Optional[StructuredTool]:
        return self._tools.get(name)

    def has(self, name: str) -> bool:
        return name in self._tools

    def all_tools(self) -> list[StructuredTool]:
        return list(self._tools.values())

    def unique_tools(self) -> list[StructuredTool]:
        return [t for n, t in self._tools.items() if not n.startswith("default.")]

    def tool_names(self) -> list[str]:
        return [n for n in self._tools if not n.startswith("default.")]

    def persist_tool(self, name: str, source_code: str, description: str) -> None:
        tool_file = _tools_dir() / f"{name}.py"
        tool_file.write_text(source_code)
        manifest = self._load_manifest()
        manifest[name] = {"description": description, "file": f"{name}.py"}
        _manifest_path().write_text(json.dumps(manifest, indent=2))
        logger.info("Persisted tool: %s", name)

    def _load_manifest(self) -> dict:
        p = _manifest_path()
        if p.exists():
            return json.loads(p.read_text())
        return {}

    def _load_builtins(self) -> None:
        from .tools.builtins import BUILTIN_TOOLS

        for spec in BUILTIN_TOOLS:
            self.register(spec["name"], spec["func"], spec["description"], args_schema=spec.get("args_schema"))
            self._builtin_names.add(spec["name"])
        logger.info("Loaded %d built-ins", len(BUILTIN_TOOLS))

    def _load_persisted_tools(self) -> None:
        manifest = self._load_manifest()
        for name, meta in manifest.items():
            if name in self._builtin_names:
                continue
            tool_file = _tools_dir() / meta["file"]
            if not tool_file.exists():
                continue
            try:
                spec = importlib.util.spec_from_file_location(name, tool_file)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                func = getattr(module, name, None)
                if callable(func):
                    self.register(name, func, meta["description"])
                    logger.info("Loaded persisted tool: %s", name)
            except Exception as e:
                logger.warning("Failed to load %s: %s", name, e)


registry = ToolRegistry()
