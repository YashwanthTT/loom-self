from langchain_core.prompts import ChatPromptTemplate

from agent.memory import memory
from agent.paths import get_paths
from inference.config import create_chat_openai
from selfLearn.textutils import extract_response_text, strip_code_fence

TOOLS_DIR = get_paths().tools

REWRITE_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """You are an expert Python engineer. Your job is to REWRITE a single, self-contained Python function to fix its failures.

Rules (same as generation, do not relax):
- The function name must exactly match the `tool_name` provided — do not rename it.
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
- Preserve working behavior covered by the regression examples — do not break existing successful cases.
- Fix the specific failures listed while keeping the function self-contained and minimal.
""",
        ),
        (
            "human",
            """Rewrite the Python function with this specification:

Tool name: {tool_name}
Description: {description}

Current source code (to fix):
```python
{current_source}
```

Recent failures (most recent 2-3, with args and error):
{failures_text}

Regression examples to preserve (last successful runs):
{regression_text}

Instructions: Return ONLY the revised raw Python code for `{tool_name}` that fixes the failures above without breaking the regression examples. Keep the same function name and handle all errors gracefully.
""",
        ),
    ]
)


class ToolRewriterAgent:
    def __init__(self, model: str | None = None):
        llm_kwargs = {"temperature": 0.1, "timeout": 90, "max_retries": 2}
        if model:
            llm_kwargs["model"] = model
        self.llm = create_chat_openai(**llm_kwargs)
        self.chain = REWRITE_PROMPT | self.llm

    def rewrite(
        self,
        tool_name: str,
        current_source: str,
        description: str,
        failures: list[dict] | None = None,
        regression_examples: list[dict] | None = None,
    ) -> str:
        # Normalize failures: pull from memory if not provided
        if failures is None:
            history = memory.get_history(tool_name)
            recent_failures = [h for h in history if h.get("success") is False][-3:]
            failures = recent_failures
        # regression
        if regression_examples is None:
            regression_examples = memory.get_regression_examples(tool_name, n=5)

        # Format failures for prompt
        if failures:
            failures_text = ""
            for i, f in enumerate(failures[-3:], 1):
                args = f.get("args", f.get("input", {}))
                err = f.get("result_or_error", f.get("error", f.get("message", "")))
                ts = f.get("timestamp", "")
                failures_text += f"{i}. args={args} -> error={err} (at {ts})\n"
        else:
            failures_text = "(no recorded failures — improve robustness and error handling)"

        if regression_examples:
            regression_text = ""
            for i, ex in enumerate(regression_examples, 1):
                regression_text += f"{i}. args={ex.get('args')} -> expected contains {ex.get('expected')}\n"
        else:
            regression_text = "(no regression examples stored yet)"

        print(f"[Rewriter] Rewriting tool: {tool_name} with {len(failures or [])} failures, {len(regression_examples or [])} regressions...")

        response = self.chain.invoke(
            {
                "tool_name": tool_name,
                "description": description,
                "current_source": current_source.strip(),
                "failures_text": failures_text.strip(),
                "regression_text": regression_text.strip(),
            }
        )
        content = extract_response_text(response)
        content = strip_code_fence(content)
        if not content:
            raise ValueError(f"Empty rewrite for {tool_name}: raw={response}")
        return content.strip()

    def rewrite_from_registry(self, tool_name: str) -> str:
        """Convenience: read current source + description from tools/, pull failures/regressions from memory, and rewrite."""
        key = tool_name.removeprefix("default.")
        tool_file = TOOLS_DIR / f"{key}.py"
        if not tool_file.exists():
            raise FileNotFoundError(f"Tool source not found: {tool_file}")
        current_source = tool_file.read_text()

        # description from manifest or fallback
        description = key
        try:
            import json
            manifest_path = TOOLS_DIR / "manifest.json"
            if manifest_path.exists():
                manifest = json.loads(manifest_path.read_text())
                if key in manifest:
                    description = manifest[key].get("description", key)
        except Exception:
            pass

        return self.rewrite(key, current_source, description)


if __name__ == "__main__":
    import sys
    import json as _json

    if len(sys.argv) < 2:
        print("Usage: python rewriter.py <tool_name>")
        sys.exit(1)
    agent = ToolRewriterAgent()
    for name in sys.argv[1:]:
        try:
            new_src = agent.rewrite_from_registry(name)
            print(f"\n--- Rewritten source for {name} ---\n")
            print(new_src)
        except Exception as e:
            print(f"[Rewriter] failed for {name}: {e}")
            sys.exit(1)
