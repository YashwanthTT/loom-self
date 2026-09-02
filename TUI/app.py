"""TUI — textual frontend for agent. Ready for manual testing."""

from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, Input, RichLog, Static
from textual.containers import Vertical
from textual import work

try:
    from agent.orchestrator import AgentOrchestrator
    from agent.registry import registry
except Exception:
    AgentOrchestrator = None  # type: ignore
    registry = None  # type: ignore


class LoomTUI(App):
    CSS = """
    #log {
        height: 1fr;
        border: solid $accent;
        padding: 1;
    }
    #status {
        height: 1;
        background: $surface;
        color: $text;
        padding: 0 1;
    }
    Input {
        dock: bottom;
        margin: 1 0;
    }
    """

    TITLE = "LoomSelf — Coding Agent (Go $10)"
    SUB_TITLE = "read / edit / bash · selfLearn gated"

    def __init__(self, model: str | None = None, **kwargs):
        super().__init__(**kwargs)
        self.model = model
        self.agent = None
        if AgentOrchestrator:
            try:
                self.agent = AgentOrchestrator(model=model)
            except Exception as e:
                self._agent_error = str(e)
            else:
                self._agent_error = None
        else:
            self._agent_error = "AgentOrchestrator not importable"

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(self._status_text(), id="status")
        yield RichLog(id="log", highlight=True, markup=True)
        yield Input(placeholder="Type a task and press Enter — e.g. 'read README and fix typo' (Ctrl+Q quit)", id="input")
        yield Footer()

    def _status_text(self) -> str:
        tools = ", ".join(registry.tool_names()) if registry else "no registry"
        model = self.model or "kimi-k2.6 (Go default)"
        return f"model: {model} | tools: {tools}"

    def on_mount(self) -> None:
        log = self.query_one("#log", RichLog)
        log.write("[bold green]LoomSelf ready[/] — folders: inference/ agent/ selfLearn/ TUI/")
        if getattr(self, "_agent_error", None):
            log.write(f"[red]Agent init failed: {self._agent_error}[/] — set OPENCODE_GO_API_KEY")
        else:
            log.write(f"[dim]{self._status_text()}[/]")
            log.write("[dim]Tip: plan mode gated — combine read/edit/bash before requesting new tool.[/]")

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        task = event.value.strip()
        if not task:
            return
        event.input.value = ""
        log = self.query_one("#log", RichLog)
        log.write(f"\n[bold cyan]▸ {task}[/]")
        if not self.agent:
            log.write("[red]Agent not available — check OPENCODE_GO_API_KEY[/]")
            return
        log.write("[yellow]… running (may call LLM)…[/]")
        self.run_task(task)

    @work(exclusive=True, thread=True)
    def run_task(self, task: str) -> None:
        try:
            result = self.agent.run(task)  # type: ignore
            self.call_from_thread(self._append_result, result, False)
        except Exception as e:
            self.call_from_thread(self._append_result, str(e), True)

    def _append_result(self, text: str, is_error: bool) -> None:
        log = self.query_one("#log", RichLog)
        if is_error:
            # Friendly hint for the 401 you saw
            if "401" in text and "ModelError" in text and "muse-spark" in text:
                log.write(f"[red]✗ {text}[/]")
                log.write("[yellow]Fix: .env had muse-spark (Zen) on Go endpoint → 401. Fixed to kimi-k2.6.[/]")
                log.write("[dim]If you want Zen free: set OPENCODE_API_KEY=public + OPENCODE_MODEL=muse-spark-1.2-contributor-free (no GO key). For Go: OPENCODE_GO_API_KEY=sk-... + OPENCODE_MODEL=kimi-k2.6 — see .env.example[/]")
            elif "401" in text:
                log.write(f"[red]✗ {text}[/]")
                log.write("[yellow]Check OPENCODE_GO_API_KEY and OPENCODE_MODEL in .env — see .env.example[/]")
            else:
                log.write(f"[red]✗ {text}[/]")
        else:
            log.write(f"[green]✓ {text}[/]")
        log.write(f"[dim]tools: {', '.join(registry.tool_names())}[/]" if registry else "")


def run(model: str | None = None) -> int:
    """Entry for main.py — returns exit code. Testable via `python -m TUI.app`."""
    app = LoomTUI(model=model)
    app.run()
    return 0


if __name__ == "__main__":
    run()
