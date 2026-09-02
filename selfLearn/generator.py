"""Tool generator — uses inference.config (modern langchain_core), not deprecated langchain."""

import logging
from langchain_core.prompts import ChatPromptTemplate
from inference.config import create_chat_openai
from selfLearn.textutils import extract_response_text, strip_code_fence

logger = logging.getLogger(__name__)

GENERATION_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """You are an expert Python engineer. Write a single self-contained Python function.

Rules:
- Function name must exactly match tool_name.
- Use only stdlib OR: requests, httpx, pandas, pydantic, Pillow, pytesseract.
- Do NOT import langchain/openai.
- Create parent dirs with os.makedirs(exist_ok=True).
- Return ONLY raw Python code, no markdown.
- Handle errors with try/except, return dict with success flag.
- Include type hints, defaults "" for string params.
""",
        ),
        (
            "human",
            """Tool name: {tool_name}
Description: {description}
Params: {input_params}
Return: {return_type}
Example: {example}
""",
        ),
    ]
)


class ToolGeneratorAgent:
    def __init__(self, model: str | None = None):
        llm_kwargs = {"temperature": 0.1, "timeout": 90, "max_retries": 2}
        if model:
            llm_kwargs["model"] = model
        self.llm = create_chat_openai(**llm_kwargs)
        self.chain = GENERATION_PROMPT | self.llm

    def generate(
        self,
        tool_name: str,
        description: str,
        input_params: str,
        return_type: str,
        example: str,
    ) -> str:
        logger.info("Generating tool: %s", tool_name)
        response = self.chain.invoke(
            {
                "tool_name": tool_name,
                "description": description,
                "input_params": input_params,
                "return_type": return_type,
                "example": example,
            }
        )
        content = extract_response_text(response)
        content = strip_code_fence(content)
        if not content:
            raise ValueError(f"Empty generation for {tool_name}")
        return content.strip()
