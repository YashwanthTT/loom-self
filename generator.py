from langchain_core.prompts import ChatPromptTemplate

from llm_config import create_chat_openai

GENERATION_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """You are an expert Python engineer. Your job is to write a single, self-contained Python function.
 
Rules:
- The function name must exactly match the `tool_name` provided.
- The function must have a clear docstring.
- Use only standard library modules OR: requests, httpx, pandas, pydantic, Pillow (PIL), pytesseract.
- For OCR tasks: prefer subprocess tesseract CLI (subprocess.run) with fallback to requests to https://api.ocr.space if tesseract not installed. Use PIL only if available.
- Do NOT import from langchain, openai, or any LLM library.
- File system: you MAY read/write files at any path given in params (especially under /tmp and output_text_path/output_path/file_path). Always create parent dirs with os.makedirs(exist_ok=True). For self-learning file tasks, use /tmp as base.
- Return ONLY the raw Python code. No markdown, no explanation, no ```python blocks.
- The function must handle errors gracefully with try/except and return dict with success flag and message.
- Always include type hints. Make string params optional with default "" to handle empty calls gracefully.
- For OCR: signature should be def tool_name(image_path: str = "", output_text_path: str = "") -> dict
- For read/write: signatures like def write_text_file(file_path: str = "", content: str = "") -> dict and def read_text_file(file_path: str = "") -> dict
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
    def __init__(self, model: str | None = None):
        # Muse Spark 1.2 free per user request — reads from .env (muse-spark-1.2-contributor-free)
        llm_kwargs = {"temperature": 0.1, "timeout": 90, "max_retries": 2}
        if model:
            llm_kwargs["model"] = model
        # else let llm_config pick from .env (muse-spark-1.2-contributor-free)
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
        print(f"[Generator] Writing tool: {tool_name} with muse-spark-1.2...")
        response = self.chain.invoke(
            {
                "tool_name": tool_name,
                "description": description,
                "input_params": input_params,
                "return_type": return_type,
                "example": example,
            }
        )
        # Muse Spark via Responses API returns content as list of blocks
        raw_content = response.content
        if isinstance(raw_content, list):
            # Extract text blocks, ignore reasoning
            texts = []
            for block in raw_content:
                if isinstance(block, dict) and block.get("type") == "text":
                    texts.append(block.get("text", ""))
                elif isinstance(block, str):
                    texts.append(block)
            content = "\n".join(texts).strip()
        else:
            content = (raw_content or "").strip()
        if not content:
            extra = getattr(response, "additional_kwargs", {}) or {}
            content = extra.get("reasoning", "") or extra.get("reasoning_content", "") or ""
            meta = getattr(response, "response_metadata", {}) or {}
            if not content and isinstance(meta, dict):
                content = meta.get("reasoning", "") or ""
        if content.startswith("```"):
            parts = content.split("```")
            if len(parts) >= 2:
                content = parts[1]
                if content.startswith("python"):
                    content = content[len("python"):].strip()
                content = content.strip()
        if not content:
            raise ValueError(f"Empty generation for {tool_name}: raw={response}")
        return content.strip()
