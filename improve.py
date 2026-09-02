#!/usr/bin/env python3
"""Standalone entry point for the self-improvement loop.

Usage:
  python improve.py <tool_name>          # improve one tool
  python improve.py <tool_name> ...      # improve several
  python improve.py --all                # evaluate all tools, improve those that need it
  python improve.py --evaluate           # just print evaluation table, don't rewrite
"""
import argparse
import sys

from agent.orchestrator import AgentOrchestrator
from agent.evaluator import ToolEvaluator, evaluate_all_tools
from agent.memory import memory


def main():
    parser = argparse.ArgumentParser(description="Self-improvement loop for loom-self tools")
    parser.add_argument("tools", nargs="*", help="tool name(s) to improve")
    parser.add_argument("--all", action="store_true", help="improve all tools that need it")
    parser.add_argument("--evaluate", action="store_true", help="only evaluate, don't rewrite")
    args = parser.parse_args()

    evaluator = ToolEvaluator()

    if args.evaluate:
        evaluate_all_tools()
        return 0

    if args.all:
        results = evaluator.evaluate_all()
        to_improve = [name for name, r in results.items() if r.needs_improvement]
        if not to_improve:
            print("[improve] All tools are healthy — nothing to do.")
            for name, r in results.items():
                print(f"  {name}: score={r.score:.2f} {r.reason}")
            return 0
        print(f"[improve] Tools needing improvement: {to_improve}")
        args.tools = to_improve

    if not args.tools:
        parser.print_help()
        print("\n[improve] No tools specified. Use --all or list tool names.")
        print("Available tools with history:", list(memory.all_tool_names()) or "(no memory yet)")
        from agent.registry import registry
        print("Registered tools:", registry.tool_names())
        return 1

    orchestrator = AgentOrchestrator()
    for tool_name in args.tools:
        print(f"\n{'='*60}\n[improve] Improving '{tool_name}'...\n{'='*60}")
        try:
            result = orchestrator.improve_tool(tool_name)
            print(f"\n[improve] Result for '{tool_name}': {result}")
        except Exception as e:
            print(f"[improve] Failed for '{tool_name}': {e}", file=sys.stderr)
            import traceback
            traceback.print_exc()

    return 0


if __name__ == "__main__":
    sys.exit(main())
