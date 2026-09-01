"""Entry point — delegates to inference + agent + TUI."""

import argparse
import os
import sys


def _check_credentials():
    has_opencode = bool(os.getenv("OPENCODE_GO_API_KEY") or os.getenv("OPENCODE_API_KEY") or os.getenv("OPENCODE_ZEN_API_KEY"))
    has_openai = bool(os.getenv("OPENAI_API_KEY"))
    if not has_opencode and not has_openai:
        print("[warn] No LLM credentials.\n  export OPENCODE_GO_API_KEY='sk-...'  (https://opencode.ai/auth, $10 Go)\n  or OPENAI_API_KEY='sk-...'\n  See inference/config.py")


def main():
    parser = argparse.ArgumentParser(prog="loomSelf", description="LoomSelf coding agent (Opencode Go)")
    parser.add_argument("--task", type=str, help="Run a single task headlessly")
    parser.add_argument("--model", type=str, default=None, help="Model override (default kimi-k2.6)")
    parser.add_argument("--tui", action="store_true", help="Launch TUI (default if no --task)")
    args = parser.parse_args()

    # inference handles .env loading
    from agent.orchestrator import AgentOrchestrator

    _check_credentials()

    if args.task:
        agent = AgentOrchestrator(model=args.model)
        result = agent.run(args.task)
        print(f"\n✅ Result: {result}\n")
        return 0

    if args.tui or not args.task:
        try:
            from TUI.app import run as tui_run
            return tui_run(model=args.model)
        except ImportError as e:
            print(f"TUI requires 'textual' (pip install textual): {e}", file=sys.stderr)
            print("Falling back to headless. Use --task 'your task'", file=sys.stderr)
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
