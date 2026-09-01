import os

# Load .env if present (OPENCODE_API_KEY, etc.) — also supports env.example
try:
    from dotenv import load_dotenv
    from pathlib import Path

    for _env_file in (".env", "env.example", ".env.example"):
        _p = Path(__file__).parent / _env_file
        if _p.exists():
            load_dotenv(_p, override=False)
            break
except ImportError:
    pass

from orchestrator import SelfExtendingOrchestrator


def _check_credentials():
    has_opencode = any(
        os.getenv(k)
        for k in ("OPENCODE_GO_API_KEY", "OPENCODE_ZEN_API_KEY", "OPENCODE_API_KEY")
    )
    has_openai = bool(os.getenv("OPENAI_API_KEY"))
    if not has_opencode and not has_openai:
        print(
            "[warn] No LLM credentials found.\n"
            "  For Opencode Go (recommended, $10/mo): https://opencode.ai/auth -> subscribe to Go\n"
            "    export OPENCODE_GO_API_KEY='sk-...'\n"
            "    # optional: export OPENCODE_MODEL='opencode-go/kimi-k2.6'\n"
            "  For Opencode Zen (pay-as-you-go): https://opencode.ai/auth\n"
            "    export OPENCODE_API_KEY='sk-...'  # or OPENCODE_ZEN_API_KEY\n"
            "    # optional free model: export OPENCODE_API_KEY='public' + OPENCODE_MODEL='opencode/big-pickle'\n"
            "  Or fallback OpenAI:\n"
            "    export OPENAI_API_KEY='sk-...'\n"
            "  Endpoints (OpenAI-compatible):\n"
            "    Zen: https://opencode.ai/zen/v1/chat/completions (@ai-sdk/openai-compatible)\n"
            "    Go : https://opencode.ai/zen/go/v1/chat/completions\n"
            "  See llm_config.py and https://opencode.ai/docs/go + https://opencode.ai/docs/zen"
        )


# "What is the current USD to ILS exchange rate? Convert 5000 USD.",
# "Get the top 5 trending GitHub repositories today and list their names and stars.",
# "Generate a 16-character secure password and calculate its entropy in bits.",
# "Create OCR tool to extract text from images and save it to a text file.",
def main():
    _check_credentials()
    agent = SelfExtendingOrchestrator()

    tasks = [
        # Self-learning read/write demo: if agent can't read/write, it will create the tool itself
        # "Write the text 'Self-learning test: agent created this file itself' to /tmp/self_created_task.txt and then read it back to verify.",
        "create bash srcipt that will read the main.js file and run the javascript code in it and write the output to a file called output.txt",
        "create a simple web scraper that fetches the top 10 grossing films and show of all time and write it to movies.txt",
    ]

    for task in tasks:
        result = agent.run(task)
        print(f"\n✅ Result: {result}\n")
        print("-" * 60)


if __name__ == "__main__":
    main()
