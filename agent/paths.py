"""Runtime paths — per-workdir isolation."""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AgentPaths:
    workdir: Path
    outputs: Path
    state: Path
    tools: Path
    skills: Path
    agents_md: Path
    plans: Path


_paths: AgentPaths | None = None


def configure(workdir: str | Path | None = None, outputs_dir: str | Path | None = None,
              tools_dir: str | Path | None = None, skills_dir: str | Path | None = None) -> AgentPaths:
    root = Path(workdir or Path.cwd()).expanduser().resolve()
    state = root / ".agent"
    outputs = Path(outputs_dir).expanduser().resolve() if outputs_dir else root / "outputs"
    tools = Path(tools_dir).expanduser().resolve() if tools_dir else state / "tools"
    skills = Path(skills_dir).expanduser().resolve() if skills_dir else state / "skills"
    plans = state / "plans"
    global _paths
    _paths = AgentPaths(root, outputs, state, tools, skills, root / "AGENTS.md", plans)
    return _paths


def get_paths() -> AgentPaths:
    global _paths
    if _paths is None:
        _paths = configure()
    return _paths


def ensure_runtime_dirs() -> AgentPaths:
    paths = get_paths()
    paths.outputs.mkdir(parents=True, exist_ok=True)
    paths.tools.mkdir(parents=True, exist_ok=True)
    paths.skills.mkdir(parents=True, exist_ok=True)
    paths.plans.mkdir(parents=True, exist_ok=True)
    return paths
