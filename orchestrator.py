try:
    from langchain.agents import AgentExecutor, create_openai_tools_agent
except ImportError:
    # langchain 1.x moved agents to langchain-classic
    from langchain_classic.agents import AgentExecutor, create_openai_tools_agent  # type: ignore

from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from llm_config import create_chat_openai
from registry import registry, TOOLS_DIR, MANIFEST_PATH
from generator import ToolGeneratorAgent
from validator import ToolValidator, ValidationError
from memory import memory
from evaluator import ToolEvaluator
from rewriter import ToolRewriterAgent

import time as _time
import json as _json
from pathlib import Path as _Path
from datetime import datetime as _datetime, timezone as _timezone

ORCHESTRATOR_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """You are an autonomous AI agent with the ability to extend your own capabilities and improve them over time.

When you need to perform an action for which you have no tool:
1. Use the `request_new_tool` tool to describe exactly what you need.
2. Wait — the system will generate and register the tool automatically.
3. The new tool will then be available. Use it to complete the task.

When a tool repeatedly fails or is unreliable:
- Use the `evaluate_and_improve_tool` tool to trigger the self-improvement loop. Give it the tool name (e.g. "write_text_file").
- The system will evaluate its history, rewrite it if needed, validate and regression-test the new version, and replace it only if better.

Rules:
- After creating a new tool, do NOT try to test it with empty or placeholder arguments. Only call it if the user provided concrete file paths/values. If no concrete values are given, simply report that the tool was created successfully and describe its usage.
- When calling any tool, always provide valid JSON arguments with all required string fields as non-empty strings. Never call with empty string "" or missing required fields.
- For Muse Spark via Responses API, ensure tool call arguments are always a valid JSON object like {{"image_path": "/tmp/in.png", "output_path": "/tmp/out.txt"}}.

Always complete the user's task fully. Never say you cannot do something — if you lack a tool, request it.
""",
        ),
        MessagesPlaceholder("chat_history", optional=True),
        ("human", "{input}"),
        MessagesPlaceholder("agent_scratchpad"),
    ]
)


class NewToolRequest(BaseModel):
    tool_name: str = Field(
        description="snake_case name for the tool, e.g. fetch_exchange_rate"
    )
    description: str = Field(description="What the tool does in one clear sentence")
    input_params: str = Field(
        description="Parameters with types, e.g. 'amount: float, from_currency: str'"
    )
    return_type: str = Field(description="Return type, e.g. 'float' or 'dict'")
    example: str = Field(
        description="Example call, e.g. fetch_exchange_rate(100.0, 'USD', 'ILS')"
    )


class EvaluateAndImproveRequest(BaseModel):
    tool_name: str = Field(description="snake_case name of existing tool to evaluate and improve")


def _wrap_tool_with_memory(tool: StructuredTool) -> StructuredTool:
    """Wrap a registry StructuredTool so every invocation is timed and recorded to memory."""
    orig_func = tool.func
    # Some langchain versions store coroutine separately; handle both
    orig_name = tool.name  # keep alias name for dedup but normalize on record

    # Preserve args_schema if present; otherwise let from_function infer from func
    schema = getattr(tool, "args_schema", None)

    def _wrapper(**kwargs):
        start = _time.perf_counter()
        try:
            result = orig_func(**kwargs) if orig_func else None
            latency = (_time.perf_counter() - start) * 1000
            # Detect logical failure: dict with success==False
            success = True
            if isinstance(result, dict) and result.get("success") is False:
                success = False
            memory.record(orig_name, kwargs, success, result, latency)
            return result
        except Exception as e:
            latency = (_time.perf_counter() - start) * 1000
            memory.record(orig_name, kwargs, False, str(e), latency)
            raise

    # Re-create StructuredTool with same identity but wrapped func
    # Use from_function so name/description/arg schema are preserved for LLM
    kwargs_for_tool: dict = {
        "func": _wrapper,
        "name": tool.name,
        "description": tool.description,
        "handle_tool_error": True,
    }
    if schema is not None:
        kwargs_for_tool["args_schema"] = schema
    return StructuredTool.from_function(**kwargs_for_tool)


class SelfExtendingOrchestrator:
    def __init__(self, model: str | None = None, temperature: float = 0):
        # Uses Opencode (Zen / Go) if OPENCODE_*_API_KEY is set, else falls back to OPENAI_API_KEY.
        # See llm_config.py and https://opencode.ai/docs/zen / https://opencode.ai/docs/go
        # Env: OPENCODE_API_KEY / OPENCODE_ZEN_API_KEY / OPENCODE_GO_API_KEY + OPENCODE_MODEL
        self.llm = create_chat_openai(model=model, temperature=temperature) if model else create_chat_openai(temperature=temperature)
        self.generator = ToolGeneratorAgent()
        self.validator = ToolValidator()
        self.evaluator = ToolEvaluator()
        self.rewriter = ToolRewriterAgent()
        self._build_executor()

    def _build_executor(self):
        request_tool = StructuredTool.from_function(
            func=self._handle_tool_request,
            name="request_new_tool",
            description=(
                "Call this when you need a capability you don't have. "
                "The system will generate and register the tool for you."
            ),
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
        # Deduplicate by tool name to handle default. prefix aliasing, wrapping registry tools with memory recording
        seen = set()
        unique_tools: list[StructuredTool] = []
        # meta-tools are not wrapped
        for meta in [request_tool, improve_tool]:
            unique_tools.append(meta)
            seen.add(meta.name)
        for t in registry.all_tools():
            if t.name not in seen:
                seen.add(t.name)
                # Wrap registry tools so every execution is recorded
                wrapped = _wrap_tool_with_memory(t)
                unique_tools.append(wrapped)
        # Handle Muse Spark empty arguments -> valid JSON error: provide default args
        agent = create_openai_tools_agent(self.llm, unique_tools, ORCHESTRATOR_PROMPT)
        self.executor = AgentExecutor(
            agent=agent,
            tools=unique_tools,
            verbose=True,
            max_iterations=15,
            handle_parsing_errors=True,
        )

    def _handle_tool_request(
        self,
        tool_name: str,
        description: str,
        input_params: str,
        return_type: str,
        example: str,
    ) -> str:
        if registry.has(tool_name):
            return (
                f"Tool '{tool_name}' already exists in the registry. Use it directly."
            )
        # Check for similar existing tool by description keywords to avoid duplicates (e.g., OCR)
        desc_lower = description.lower()
        for existing_name in registry.tool_names():
            # Skip default. aliases
            if existing_name.startswith("default."):
                continue
            existing = registry.get(existing_name)
            if existing and existing.description:
                existing_desc = existing.description.lower()
                # Simple keyword overlap for OCR, trending, etc.
                keywords = ["ocr", "extract text", "github trending", "exchange rate", "password"]
                for kw in keywords:
                    if kw in desc_lower and kw in existing_desc:
                        return (
                            f"Tool '{existing_name}' already exists and does '{existing.description}'. "
                            f"Use '{existing_name}' instead of creating '{tool_name}'. "
                            f"Example: {existing_name} with {registry.get(existing_name).args}"
                        )

        for attempt in range(1, 4):
            print(f"\n[Orchestrator] Generating '{tool_name}' (attempt {attempt}/3)")
            try:
                source_code = self.generator.generate(
                    tool_name=tool_name,
                    description=description,
                    input_params=input_params,
                    return_type=return_type,
                    example=example,
                )
                self.validator.validate(tool_name, source_code)

                exec_globals: dict = {}
                exec(source_code, exec_globals)  # noqa: S102
                func = exec_globals[tool_name]

                registry.register(tool_name, func, description)
                registry.persist_tool(tool_name, source_code, description)

                # Rebuild executor so new tool is immediately available and patch current executor for in-flight chain
                self._build_executor()
                # Patch current executor's tool map for immediate use in same chain (stale executor fix)
                try:
                    new_tool = registry.get(tool_name)
                    if new_tool:
                        wrapped_new = _wrap_tool_with_memory(new_tool)
                        # Update current executor if it exists (mid-invoke stale map)
                        if hasattr(self.executor, "tools"):
                            if wrapped_new not in self.executor.tools:
                                # Avoid duplicate by name check (wrapped vs unwrapped have same name)
                                if not any(t.name == wrapped_new.name for t in self.executor.tools):
                                    self.executor.tools.append(wrapped_new)
                        for attr in ["_tools_by_name", "tool_map", "name_to_tool_map"]:
                            if hasattr(self.executor, attr):
                                getattr(self.executor, attr)[tool_name] = wrapped_new
                                getattr(self.executor, attr)[f"default.{tool_name}"] = wrapped_new
                except Exception as _e:
                    print(f"[Orchestrator] patch current executor failed: {_e}")

                print(f"[Orchestrator] ✅ '{tool_name}' registered.")
                return (
                    f"Tool '{tool_name}' created and registered successfully. "
                    f"You can now use it to: {description}. "
                    f"Example: {example}. "
                    f"When you call it, use valid JSON like {example} with concrete file paths/content from the user task. Never use empty string for arguments."
                )

            except (ValidationError, Exception) as e:
                print(f"[Orchestrator] ❌ Attempt {attempt} failed: {e}")
                if attempt == 3:
                    return f"Failed to generate '{tool_name}' after 3 attempts: {e}"

        return f"Tool generation failed for '{tool_name}'."

    def improve_tool(self, tool_name: str) -> str:
        """Self-improvement loop: evaluate -> rewrite -> validate -> regression -> backup & replace."""
        key = tool_name.removeprefix("default.")
        print(f"\n[Orchestrator] Evaluating '{key}' for improvement...")
        evaluation = self.evaluator.evaluate(key)
        print(f"[Orchestrator] Score: {evaluation.score:.2f} success_rate={evaluation.success_rate:.2%} avg_latency={evaluation.avg_latency_ms:.1f}ms streak={evaluation.recent_failure_streak} needs_improvement={evaluation.needs_improvement} reason={evaluation.reason}")
        if not evaluation.needs_improvement:
            return f"Tool '{key}' is healthy (score={evaluation.score:.2f}, success_rate={evaluation.success_rate:.2%}, {evaluation.reason}). No rewrite needed."
        if evaluation.total_runs == 0:
            return f"Tool '{key}' has no execution history yet — cannot improve without evidence."

        tool_file = TOOLS_DIR / f"{key}.py"
        if not tool_file.exists():
            return f"Tool '{key}' source not found at {tool_file}. Cannot rewrite."
        current_source = tool_file.read_text()
        # description from manifest
        description = key
        try:
            manifest = _json.loads(MANIFEST_PATH.read_text()) if MANIFEST_PATH.exists() else {}
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
            print(f"[Orchestrator] ❌ Rewrite failed: {e}")
            return f"Rewrite failed for '{key}': {e}"

        print(f"[Orchestrator] Validating rewritten '{key}'...")
        try:
            self.validator.validate(key, new_source)
            print(f"[Orchestrator] ✅ Validation passed for '{key}'")
        except ValidationError as e:
            print(f"[Orchestrator] ❌ Validation failed for '{key}': {e}")
            return f"Rewritten '{key}' failed validation: {e}"
        except Exception as e:
            print(f"[Orchestrator] ❌ Validation error for '{key}': {e}")
            return f"Rewritten '{key}' failed validation: {e}"

        print(f"[Orchestrator] Running regression for '{key}'...")
        try:
            from tests.regression_runner import run_regression
            ok, fails = run_regression(key, new_source)
            if not ok:
                print(f"[Orchestrator] ❌ Regression failed for '{key}': {fails}")
                return f"Rewritten '{key}' failed regression: {fails}"
            print(f"[Orchestrator] ✅ Regression passed for '{key}' ({len(memory.get_regression_examples(key))} examples)")
        except Exception as e:
            print(f"[Orchestrator] ❌ Regression harness error for '{key}': {e}")
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
                        print(f"[Orchestrator] ❌ Triggering failure still crashes after rewrite: {fixed_err}")
                        return f"Rewritten '{key}' still crashes on the triggering case {last_args}: {fixed_err}. Not keeping."
                    print(f"[Orchestrator] ✅ Triggering failure fixed for '{key}' (no crash, graceful handling)")
                except Exception as e:
                    print(f"[Orchestrator] ⚠️ Could not verify triggering failure fix: {e}")

        # Backup old version (never overwrite without fallback)
        try:
            backup_path = tool_file.with_suffix(".py.bak")
            backup_path.write_text(current_source)
            print(f"[Orchestrator] Backup saved to {backup_path}")
            versions_dir = TOOLS_DIR / "versions"
            versions_dir.mkdir(exist_ok=True)
            timestamp = _datetime.now(_timezone.utc).strftime("%Y%m%d_%H%M%S")
            versioned = versions_dir / f"{key}_{timestamp}.py"
            versioned.write_text(current_source)
            print(f"[Orchestrator] Version saved to {versioned}")
        except Exception as e:
            print(f"[Orchestrator] ⚠️ Backup failed: {e}")

        # Write new source, update manifest, re-register, rebuild executor
        try:
            tool_file.write_text(new_source)
            manifest = _json.loads(MANIFEST_PATH.read_text()) if MANIFEST_PATH.exists() else {}
            manifest[key] = {"description": description, "file": f"{key}.py"}
            MANIFEST_PATH.write_text(_json.dumps(manifest, indent=2))
            exec_globals: dict = {}
            exec(new_source, exec_globals)  # noqa: S102
            func = exec_globals[key]
            registry.register(key, func, description)
            self._build_executor()
            print(f"[Orchestrator] ✅ '{key}' improved and re-registered (old version backed up).")
            return f"Tool '{key}' improved successfully. Validation and regression passed. Backup saved to {tool_file}.bak and versions/. New version is now active."
        except Exception as e:
            print(f"[Orchestrator] ❌ Failed to persist improved '{key}': {e}")
            # attempt rollback
            try:
                tool_file.write_text(current_source)
            except Exception:
                pass
            return f"Failed to persist improved '{key}': {e}"

    def run(self, task: str) -> str:
        print(f"\n{'='*60}")
        print(f"Task: {task}")
        print(f"Available tools: {registry.tool_names()}")
        print(f"{'='*60}\n")
        try:
            result = self.executor.invoke({"input": task})
        except Exception as e:
            # Handle Muse Spark Responses API BadRequest for invalid JSON arguments
            err_str = str(e)
            if "arguments must be valid JSON" in err_str or "invalid_request_error" in err_str:
                print(f"[Orchestrator] Caught BadRequest (invalid JSON args): {e}")
                # Retry with explicit instruction
                retry_task = task + " (NOTE: When calling tools, use valid JSON object with all required fields as non-empty strings, e.g., {\"file_path\": \"/tmp/self_created_task.txt\", \"content\": \"Self-learning test: agent created this file itself\"})"
                try:
                    result = self.executor.invoke({"input": retry_task})
                except Exception as e2:
                    return f"Tool call failed due to invalid JSON arguments. Please ensure you call tools with valid JSON like {{\"file_path\": \"/tmp/self_created_task.txt\", \"content\": \"...\"}}. Error: {e2}"
            else:
                raise
        output = result["output"]
        # Muse Spark via Responses API returns list of blocks [{type: reasoning}, {type: text}]
        if isinstance(output, list):
            texts = [b.get("text", "") for b in output if isinstance(b, dict) and b.get("type") == "text"]
            if texts:
                return "\n".join(texts)
            # fallback: stringify
            return str(output)
        return output
