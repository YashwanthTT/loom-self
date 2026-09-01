import json
import importlib.util
from pathlib import Path
from typing import Callable, Optional
from langchain.tools import StructuredTool
 
TOOLS_DIR = Path(__file__).parent / "tools"
TOOLS_DIR.mkdir(exist_ok=True)
MANIFEST_PATH = TOOLS_DIR / "manifest.json"
 
 
class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, StructuredTool] = {}
        self._load_persisted_tools()
 
    def register(self, name: str, func: Callable, description: str) -> StructuredTool:
        tool = StructuredTool.from_function(
            func=func,
            name=name,
            description=description,
        )
        self._tools[name] = tool
        return tool
 
    def get(self, name: str) -> Optional[StructuredTool]:
        return self._tools.get(name)
 
    def has(self, name: str) -> bool:
        return name in self._tools
 
    def all_tools(self) -> list[StructuredTool]:
        return list(self._tools.values())
 
    def tool_names(self) -> list[str]:
        return list(self._tools.keys())
 
    def persist_tool(self, name: str, source_code: str, description: str):
        tool_file = TOOLS_DIR / f"{name}.py"
        tool_file.write_text(source_code)
        manifest = self._load_manifest()
        manifest[name] = {"description": description, "file": f"{name}.py"}
        MANIFEST_PATH.write_text(json.dumps(manifest, indent=2))
 
    def _load_manifest(self) -> dict:
        if MANIFEST_PATH.exists():
            return json.loads(MANIFEST_PATH.read_text())
        return {}
 
    def _load_persisted_tools(self):
        manifest = self._load_manifest()
        for name, meta in manifest.items():
            tool_file = TOOLS_DIR / meta["file"]
            if not tool_file.exists():
                continue
            try:
                spec = importlib.util.spec_from_file_location(name, tool_file)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                func = getattr(module, name, None)
                if callable(func):
                    self.register(name, func, meta["description"])
                    print(f"[Registry] Loaded persisted tool: {name}")
            except Exception as e:
                print(f"[Registry] Failed to load {name}: {e}")
 
 
registry = ToolRegistry()
