"""Text helpers for LLM responses — modern, no deprecated deps."""
from __future__ import annotations
import json


def extract_message_text(raw_content) -> str:
    if isinstance(raw_content, list):
        texts = []
        for block in raw_content:
            if isinstance(block, dict) and block.get("type") == "text":
                texts.append(block.get("text", ""))
            elif isinstance(block, str):
                texts.append(block)
        return "\n".join(texts).strip()
    return (raw_content or "").strip()


def extract_response_text(response) -> str:
    content = extract_message_text(getattr(response, "content", None))
    if content:
        return content
    extra = getattr(response, "additional_kwargs", {}) or {}
    content = extra.get("reasoning", "") or extra.get("reasoning_content", "") or ""
    meta = getattr(response, "response_metadata", {}) or {}
    if not content and isinstance(meta, dict):
        content = meta.get("reasoning", "") or ""
    return content or ""


def strip_code_fence(text: str) -> str:
    if not text.startswith("```"):
        return text
    parts = text.split("```")
    if len(parts) >= 2:
        text = parts[1]
        if text.startswith("python"):
            text = text[len("python"):].strip()
    return text.strip()


def parse_json_object(text: str) -> dict | None:
    if not text:
        return None
    text = text.strip()
    if text.startswith("```"):
        parts = text.split("```")
        if len(parts) >= 2:
            text = parts[1]
            if text.startswith("json"):
                text = text[4:]
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        return json.loads(text[start: end + 1])
    except json.JSONDecodeError:
        return None


def unwrap_output(output) -> str:
    if isinstance(output, list):
        texts = [b.get("text", "") for b in output if isinstance(b, dict) and b.get("type") == "text"]
        if texts:
            return "\n".join(texts)
        return str(output)
    return output
