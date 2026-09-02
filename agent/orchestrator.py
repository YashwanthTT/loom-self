"""Agent orchestrator — modern create_agent (LangGraph), not deprecated AgentExecutor.

Uses:
- langchain.agents.create_agent (current)
- langchain_core.tools.StructuredTool (not langchain.tools)
- inference.config for Opencode Go
- selfLearn.generator/validator for gated extension
- agent.memory/evaluator/rewriter for the self-improvement loop
"""
import json
import logging
import time as _time
from datetime import datetime as _datetime, timezone as _timezone
from pathlib import Path

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from inference.config import create_chat_openai
from agent.registry import registry

logger = logging.getLogger(__name__)


BASE_PROMPT = """You are an autonomous coding agent.

Built-ins you ALWAYS have:
- read_file(file_path) — read a text file
- edit_file(file_path, old_string, new_string) — edit via exact replace
- run_bash(command, timeout) — run any bash command

Rules:
- Composition over creation: combine read_file/edit_file/run_bash before requesting a new tool.
- If you truly lack a capability, call request_new_tool with a precise spec.
- When a tool repeatedly fails or is unreliable, call evaluate_and_improve_tool with its name.
- Always provide valid JSON args, non-empty strings.
"""


class NewToolRequest(BaseModel):
    tool_name: str = Field(description="snake_case name, e.g. fetch_exchange_rate")
    description: str = Field(description="One-sentence description")
    input_params: str = Field(description="Params with types, e.g. 'amount: float, currency: str'")
    return_type: str = Field(description="Return type, e.g. 'dict'")
    example: str = Field(description="Example call, e.g. fetch_exchange_rate(100.0, 'USD', 'ILS')")


class EvaluateAndImproveRequest(BaseModel):
    tool_name: str = Field(description="snake_case name of existing tool to evaluate and improve")


def _wrap_with_memory(tool: StructuredTool) -> StructuredTool:
    """Wrap a registry StructuredTool so every invocation is timed and recorded to memory."""
    from agent.memory import memory

    orig_func = getattr(tool, "func", None) or getattr(tool, "coroutine", None)
    orig_name = tool.name
    schema = getattr(tool, "args_schema", None)

    def _wrapper(**kwargs):
        start = _time.perf_counter()
        try:
            result = orig_func(**kwargs) if orig_func else None
            latency = (_time.perf_counter() - start) * 1000
            success = not (isinstance(result, dict) and result.get("success") is False)
            memory.record(orig_name, kwargs, success, result, latency)
            return result
        except Exception as e:
            latency = (_time.perf_counter() - start) * 1000
            memory.record(orig_name, kwargs, False, str(e), latency)
            raise

    kwargs_for_tool: dict = {
        "func": _wrapper,
        "name": tool.name,
        "description": tool.description,
        "handle_tool_error": True,
    }
    if schema is not None:
        kwargs_for_tool["args_schema"] = schema
    return StructuredTool.from_function(**kwargs_for_tool)


# Middleware for runtime tool injection (LangGraph) — modern, no deprecated AgentExecutor
from langchain.agents.middleware import AgentMiddleware as _MW


class DynamicToolMiddleware(_MW):
    name = "dynamic_registry_tools"

    def wrap_model_call(self, request, handler):
        try:
            bound = {t.name for t in request.tools}
            extra = [_wrap_with_memory(t) for t in registry.unique_tools() if t.name not in bound]
            if extra:
                request = request.override(tools=[*request.tools, *extra])
        except Exception:
            pass
        return handler(request)

    def wrap_tool_call(self, request, handler):
        try:
            name = request.tool_call["name"]
            canonical = name[len("default."):] if name.startswith("default.") else name
            tool = registry.get(canonical)
            if tool is not None and name not in {t.name for t in request.tools}:
                return handler(request.override(tool=_wrap_with_memory(tool)))
        except Exception:
            pass
        return handler(request)


class AgentOrchestrator:
    def __init__(self, model: str | None = None, temperature: float = 0, verbose: bool = False, max_iterations: int = 25):
        self.verbose = verbose
        self.max_iterations = max_iterations
        self.llm = create_chat_openai(model=model, temperature=temperature) if model else create_chat_openai(temperature=temperature)
        # lazy generator/validator — only needed when self-extending
        from selfLearn.generator import ToolGeneratorAgent
        from selfLearn.validator import ToolValidator
        self.generator = ToolGeneratorAgent()
        self.validator = ToolValidator()
        # lazy self-improvement machinery
        from agent.evaluator import ToolEvaluator
        from agent.rewriter import ToolRewriterAgent
        self.evaluator = ToolEvaluator()
        self.rewriter = ToolRewriterAgent()
        self._build_executor()

    def _build_executor(self):
        request_tool = StructuredTool.from_function(
            func=self._handle_tool_request,
            name="request_new_tool",
            description="Call when you need a capability you don't have. System will generate it.",
            args_schema=NewToolRequest,
        )
        improve_tool = StructuredTool.from_function(
            func=self.improve_tool,
            name="evaluate_and_improve_tool",
            description=(
                "Evaluate a tool's execution history and, if it is weak (low success rate or repeated failures), "
                "rewrite it to fix failures while preserving working behavior. "
                "Use when a tool has failed or you suspect it is unreliable. "
                "Input is the tool's snake_case name, e.g. write_text_file."
            ),
            args_schema=EvaluateAndImproveRequest,
        )
        static_tools = [request_tool, improve_tool] + [_wrap_with_memory(t) for t in registry.unique_tools()]
        from langchain.agents import create_agent

        self.agent_graph = create_agent(
            model=self.llm,
            tools=static_tools,
            system_prompt=BASE_PROMPT,
            middleware=[DynamicToolMiddleware()],
        )

    def _handle_tool_request(self, tool_name: str, description: str, input_params: str, return_type: str, example: str) -> str:
        if registry.has(tool_name):
            return f"Tool '{tool_name}' already exists. Use it directly."
        for attempt in range(1, 4):
            try:
                source_code = self.generator.generate(tool_name, description, input_params, return_type, example)
                self.validator.validate(tool_name, source_code)
                exec_globals = {}
                exec(source_code, exec_globals)
                func = exec_globals[tool_name]
                registry.register(tool_name, func, description)
                registry.persist_tool(tool_name, source_code, description)
                return f"Tool '{tool_name}' created and registered. You can now use it: {description}. Example: {example}"
            except Exception as e:
                if attempt == 3:
                    return f"Failed to generate '{tool_name}' after 3 attempts: {e}"
        return f"Tool generation failed for '{tool_name}'."

    def improve_tool(self, tool_name: str) -> str:
        """Self-improvement loop: evaluate -> rewrite -> validate -> regression -> backup & replace."""
        from agent.memory import memory
        from agent.paths import get_paths

        key = tool_name.removeprefix("default.")
        print(f"\n[Orchestrator] Evaluating '{key}' for improvement...")
        evaluation = self.evaluator.evaluate(key)
        print(f"[Orchestrator] Score: {evaluation.score:.2f} success_rate={evaluation.success_rate:.2%} avg_latency={evaluation.avg_latency_ms:.1f}ms streak={evaluation.recent_failure_streak} needs_improvement={evaluation.needs_improvement} reason={evaluation.reason}")
        if not evaluation.needs_improvement:
            return f"Tool '{key}' is healthy (score={evaluation.score:.2f}, success_rate={evaluation.success_rate:.2%}, {evaluation.reason}). No rewrite needed."
        if evaluation.total_runs == 0:
            return f"Tool '{key}' has no execution history yet — cannot improve without evidence."

        tools_dir = get_paths().tools
        tool_file = tools_dir / f"{key}.py"
        if not tool_file.exists():
            return f"Tool '{key}' source not found at {tool_file}. Cannot rewrite."
        current_source = tool_file.read_text()
        # description from manifest
        description = key
        try:
            manifest = json.loads((tools_dir / "manifest.json").read_text()) if (tools_dir / "manifest.json").exists() else {}
            if key in manifest:
                description = manifest[key].get("description", key)
        except Exception:
            pass

        # Gather failures for prompt (last 3 failures)
        history = memory.get_history(key)
        failures = [h for h in history if h.get("success") is False][-3:]
        print(f"[Orchestrator] Found {len(failures)} recent failures, {len(memory.get_regression_examples(key))} regression examples for '{key}'")

        print(f"[Orchestrator] Rewriting '{key}' (attempt 1/1)...")
        try:
            new_source = self.rewriter.rewrite(key, current_source, description, failures)
        except Exception as e:
            print(f"[Orchestrator] Rewrite failed: {e}")
            return f"Rewrite failed for '{key}': {e}"

        print(f"[Orchestrator] Validating rewritten '{key}'...")
        try:
            self.validator.validate(key, new_source)
            print(f"[Orchestrator] Validation passed for '{key}'")
        except Exception as e:
            print(f"[Orchestrator] Validation failed for '{key}': {e}")
            return f"Rewritten '{key}' failed validation: {e}"

        print(f"[Orchestrator] Running regression for '{key}'...")
        try:
            from tests.regression_runner import run_regression
            ok, fails = run_regression(key, new_source)
            if not ok:
                print(f"[Orchestrator] Regression failed for '{key}': {fails}")
                return f"Rewritten '{key}' failed regression: {fails}"
            print(f"[Orchestrator] Regression passed for '{key}' ({len(memory.get_regression_examples(key))} examples)")
        except Exception as e:
            print(f"[Orchestrator] Regression harness error for '{key}': {e}")
            return f"Regression check failed for '{key}': {e}"

        # Check that the triggering failure is now fixed (if there was a failure) — no crash, graceful handling allowed
        if failures:
            last_failure = failures[-1]
            last_args = last_failure.get("args", {})
            if isinstance(last_args, dict) and last_args:
                print(f"[Orchestrator] Verifying fix for triggering failure args={last_args}...")
                try:
                    from tests.regression_runner import _run_single_no_crash
                    fixed_ok, fixed_err = _run_single_no_crash(key, new_source, last_args)
                    if not fixed_ok:
                        print(f"[Orchestrator] Triggering failure still crashes after rewrite: {fixed_err}")
                        return f"Rewritten '{key}' still crashes on the triggering case {last_args}: {fixed_err}. Not keeping."
                    print(f"[Orchestrator] Triggering failure fixed for '{key}' (no crash, graceful handling)")
                except Exception as e:
                    print(f"[Orchestrator] Could not verify triggering failure fix: {e}")

        # Backup old version (never overwrite without fallback)
        try:
            backup_path = tool_file.with_suffix(".py.bak")
            backup_path.write_text(current_source)
            print(f"[Orchestrator] Backup saved to {backup_path}")
            versions_dir = tools_dir / "versions"
            versions_dir.mkdir(exist_ok=True)
            timestamp = _datetime.now(_timezone.utc).strftime("%Y%m%d_%H%M%S")
            versioned = versions_dir / f"{key}_{timestamp}.py"
            versioned.write_text(current_source)
            print(f"[Orchestrator] Version saved to {versioned}")
        except Exception as e:
            print(f"[Orchestrator] Backup failed: {e}")

        # Write new source, update manifest, re-register, rebuild executor
        try:
            tool_file.write_text(new_source)
            registry.persist_tool(key, new_source, description)
            exec_globals: dict = {}
            exec(new_source, exec_globals)  # noqa: S102
            func = exec_globals[key]
            registry.register(key, func, description)
            self._build_executor()
            print(f"[Orchestrator] '{key}' improved and re-registered (old version backed up).")
            return f"Tool '{key}' improved successfully. Validation and regression passed. Backup saved to {tool_file}.bak and versions/. New version is now active."
        except Exception as e:
            print(f"[Orchestrator] Failed to persist improved '{key}': {e}")
            try:
                tool_file.write_text(current_source)
            except Exception:
                pass
            return f"Failed to persist improved '{key}': {e}"

    def run(self, task: str) -> str:
        from selfLearn.textutils import unwrap_output

        print(f"\nTask: {task}\nAvailable tools: {registry.tool_names()}")
        result = self.agent_graph.invoke(
            {"messages": [{"role": "user", "content": task}]},
            config={"recursion_limit": self.max_iterations * 2 + 4},
        )
        messages = result.get("messages", [])
        return unwrap_output(messages[-1].content if messages else "")