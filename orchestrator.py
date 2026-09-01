from langchain_openai import ChatOpenAI
from langchain.agents import AgentExecutor, create_openai_tools_agent
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

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
    def __init__(self):
        self.llm = ChatOpenAI(model="gpt-4o", temperature=0)
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
        tools = [request_tool] + registry.all_tools()
        agent = create_openai_tools_agent(self.llm, tools, ORCHESTRATOR_PROMPT)
        self.executor = AgentExecutor(
            agent=agent,
            tools=tools,
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

                # Rebuild executor so new tool is immediately available
                self._build_executor()

                print(f"[Orchestrator] ✅ '{tool_name}' registered.")
                return (
                    f"Tool '{tool_name}' created and registered successfully. "
                    f"You can now use it to: {description}"
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
        result = self.executor.invoke({"input": task})
        return result["output"]
