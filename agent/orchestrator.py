"""Agent orchestrator — modern create_agent (LangGraph), not deprecated AgentExecutor.

Uses:
- langchain.agents.create_agent (current)
- langchain_core.tools.StructuredTool (not langchain.tools)
- inference.config for Opencode Go
- selfLearn.generator/validator for gated extension
"""
import logging

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
- Always provide valid JSON args, non-empty strings.
"""


class NewToolRequest(BaseModel):
    tool_name: str = Field(description="snake_case name, e.g. fetch_exchange_rate")
    description: str = Field(description="One-sentence description")
    input_params: str = Field(description="Params with types, e.g. 'amount: float, currency: str'")
    return_type: str = Field(description="Return type, e.g. 'dict'")
    example: str = Field(description="Example call, e.g. fetch_exchange_rate(100.0, 'USD', 'ILS')")


# Middleware for runtime tool injection (LangGraph) — modern, no deprecated AgentExecutor
from langchain.agents.middleware import AgentMiddleware as _MW


class DynamicToolMiddleware(_MW):
    name = "dynamic_registry_tools"

    def wrap_model_call(self, request, handler):
        try:
            bound = {t.name for t in request.tools}
            extra = [t for t in registry.unique_tools() if t.name not in bound]
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
                return handler(request.override(tool=tool))
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
        self._build_executor()

    def _build_executor(self):
        request_tool = StructuredTool.from_function(
            func=self._handle_tool_request,
            name="request_new_tool",
            description="Call when you need a capability you don't have. System will generate it.",
            args_schema=NewToolRequest,
        )
        static_tools = [request_tool] + registry.unique_tools()
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

    def run(self, task: str) -> str:
        from selfLearn.textutils import unwrap_output

        print(f"\nTask: {task}\nAvailable tools: {registry.tool_names()}")
        result = self.agent_graph.invoke(
            {"messages": [{"role": "user", "content": task}]},
            config={"recursion_limit": self.max_iterations * 2 + 4},
        )
        messages = result.get("messages", [])
        return unwrap_output(messages[-1].content if messages else "")
