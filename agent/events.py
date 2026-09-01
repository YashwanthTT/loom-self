"""Event bus + rendering (modern, no deprecated deps)."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class EventView:
    line: str
    style: str
    status: str | None = None
    status_cls: str | None = None
    refresh: bool = False


def _clip(text: str, limit: int) -> str:
    return (text or "").replace("\n", " ")[:limit]


def render_event(event: dict) -> EventView | None:
    etype = event.get("type")
    if etype == "llm_info":
        return EventView(line=f"model: {event['model']} ({event['provider']}, {event['base_url']})", style="dim italic")
    if etype == "tool_call_start":
        args = ", ".join(f"{k}={v}" for k, v in event.get("args", {}).items())
        return EventView(line=f"▸ {event['tool']}({args})", style="cyan", status=f"running {event['tool']}…", status_cls="busy")
    if etype == "tool_call_end":
        if event.get("ok"):
            return EventView(line=f"✓ {_clip(event.get('preview',''),180)}", style="green", status=f"{event['tool']} done", status_cls="ok")
        return EventView(line=f"✗ {_clip(event.get('preview',''),180)}", style="red", status=f"{event['tool']} failed", status_cls="err")
    if etype == "tool_generate_start":
        return EventView(line=f"⚙ writing '{event['tool']}' (attempt {event['attempt']}/{event['max_attempts']})", style="yellow", status=f"generating {event['tool']}…", status_cls="busy")
    if etype == "tool_generated":
        return EventView(line=f"✚ tool registered: {event['tool']}", style="bold yellow", refresh=True)
    if etype == "tool_generate_failed":
        return EventView(line=f"✗ generation failed: {_clip(event.get('error',''),200)}", style="red")
    if etype == "tool_request_blocked":
        use = ", ".join(event.get("use_instead", [])) or "existing tools"
        return EventView(line=f"⊘ blocked '{event['tool']}' — use {use} ({event.get('reason','')})", style="magenta", status="rejected", status_cls="ok")
    if etype == "skill_created":
        return EventView(line=f"✚ skill saved: {event['skill']}", style="bold magenta", status="skill saved", status_cls="ok")
    if etype == "task_error":
        return EventView(line=f"⚠ {_clip(event.get('error',''),400)}", style="red", status="task error", status_cls="err")
    if etype == "log":
        return EventView(line=event.get("message",""), style="yellow")
    return None


class EventBus:
    def __init__(self):
        self._handlers: list[Callable[[dict], None]] = []

    def on(self, handler: Callable[[dict], None]):
        self._handlers.append(handler)

    def emit(self, event_type: str, **data):
        evt = {"type": event_type, **data}
        for h in self._handlers:
            try:
                h(evt)
            except Exception:
                pass
