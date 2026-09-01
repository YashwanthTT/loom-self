try:
    from langchain.agents import AgentExecutor, create_openai_tools_agent
except ImportError:
    # langchain 1.x moved agents to langchain-classic
    from langchain_classic.agents import AgentExecutor, create_openai_tools_agent  # type: ignore

from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from llm_config import create_chat_openai
from registry import registry
from generator import ToolGeneratorAgent
from validator import ToolValidator, ValidationError

ORCHESTRATOR_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """You are an autonomous AI agent with the ability to extend your own capabilities.
 
When you need to perform an action for which you have no tool:
1. Use the `request_new_tool` tool to describe exactly what you need.
2. Wait — the system will generate and register the tool automatically.
3. The new tool will then be available. Use it to complete the task.
 
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


class SelfExtendingOrchestrator:
    def __init__(self, model: str | None = None, temperature: float = 0):
        # Uses Opencode (Zen / Go) if OPENCODE_*_API_KEY is set, else falls back to OPENAI_API_KEY.
        # See llm_config.py and https://opencode.ai/docs/zen / https://opencode.ai/docs/go
        # Env: OPENCODE_API_KEY / OPENCODE_ZEN_API_KEY / OPENCODE_GO_API_KEY + OPENCODE_MODEL
        self.llm = create_chat_openai(model=model, temperature=temperature) if model else create_chat_openai(temperature=temperature)
        self.generator = ToolGeneratorAgent()
        self.validator = ToolValidator()
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
        # Deduplicate by tool name to handle default. prefix aliasing
        seen = set()
        unique_tools = []
        for t in [request_tool] + registry.all_tools():
            if t.name not in seen:
                seen.add(t.name)
                unique_tools.append(t)
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
                        # Update current executor if it exists (mid-invoke stale map)
                        if hasattr(self.executor, "tools"):
                            # Langchain classic stores tools list
                            if new_tool not in self.executor.tools:
                                self.executor.tools.append(new_tool)
                        # Also handle dict-based lookup if present
                        for attr in ["_tools_by_name", "tool_map", "name_to_tool_map"]:
                            if hasattr(self.executor, attr):
                                getattr(self.executor, attr)[tool_name] = new_tool
                                getattr(self.executor, attr)[f"default.{tool_name}"] = new_tool
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
