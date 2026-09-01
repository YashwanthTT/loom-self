from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate

GENERATION_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """You are an expert Python engineer. Your job is to write a single, self-contained Python function.
 
Rules:
- The function name must exactly match the `tool_name` provided.
- The function must have a clear docstring.
- Use only standard library modules OR: requests, httpx, pandas, pydantic.
- Do NOT import from langchain, openai, or any LLM library.
- Do NOT use file system access outside of /tmp.
- Return ONLY the raw Python code. No markdown, no explanation, no ```python blocks.
- The function must handle errors gracefully with try/except.
- Always include type hints.
""",
        ),
        (
            "human",
            """Write a Python function with this specification:
 
Tool name: {tool_name}
Description: {description}
Expected input parameters: {input_params}
Expected return type: {return_type}
Example usage: {example}
""",
        ),
    ]
)


class ToolGeneratorAgent:
    def __init__(self, model: str = "gpt-4o"):
        self.llm = ChatOpenAI(model=model, temperature=0.1)
        self.chain = GENERATION_PROMPT | self.llm

    def generate(
        self,
        tool_name: str,
        description: str,
        input_params: str,
        return_type: str,
        example: str,
    ) -> str:
        print(f"[Generator] Writing tool: {tool_name}...")
        response = self.chain.invoke(
            {
                "tool_name": tool_name,
                "description": description,
                "input_params": input_params,
                "return_type": return_type,
                "example": example,
            }
        )
        return response.content.strip()
