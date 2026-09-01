from dataclasses import dataclass
from memory import memory
from registry import registry

@dataclass
class EvaluationResult:
    tool_name: str
    total_runs: int
    success_rate: float
    avg_latency_ms: float
    recent_failure_streak: int
    score: float
    needs_improvement: bool
    reason: str


class ToolEvaluator:
    def evaluate(self, tool_name: str) -> EvaluationResult:
        key = tool_name.removeprefix("default.")
        history = memory.get_history(key)
        total = len(history)
        if total == 0:
            return EvaluationResult(
                tool_name=key,
                total_runs=0,
                success_rate=0.0,
                avg_latency_ms=0.0,
                recent_failure_streak=0,
                score=0.0,
                needs_improvement=False,
                reason="no history yet",
            )

        successes = sum(1 for h in history if h.get("success") is True)
        success_rate = successes / total if total else 0.0

        latencies = [h.get("latency_ms", 0) for h in history if isinstance(h.get("latency_ms"), (int, float))]
        avg_latency = sum(latencies) / len(latencies) if latencies else 0.0

        # recent failure streak: count consecutive failures from most recent backwards
        streak = 0
        for h in reversed(history):
            if h.get("success") is False:
                streak += 1
            else:
                break

        # last 3 runs all failed?
        last_3_failed = False
        if total >= 3:
            last_3_failed = all(h.get("success") is False for h in history[-3:])

        # scoring: base is success_rate; latency penalty is minor (not dominant)
        # keep score in [0,1] for simplicity
        score = round(success_rate, 3)

        needs = False
        reasons: list[str] = []
        if success_rate < 0.7:
            needs = True
            reasons.append(f"success_rate {success_rate:.2%} < 70%")
        if last_3_failed:
            needs = True
            reasons.append("last 3 runs failed")
        elif streak >= 3:
            needs = True
            reasons.append(f"recent failure streak={streak}")
        # Also trigger if single failure and success_rate is low? Keep threshold 0.7 above covers.

        reason = "; ".join(reasons) if reasons else ("healthy" if total > 0 else "no history")
        # If no trigger but success_rate ==1.0 and streak 0 => healthy
        if not needs and total > 0 and success_rate < 1.0 and streak > 0:
            # still report streak for visibility but not trigger unless >=3 or <0.7
            reason = f"healthy (streak={streak}, success_rate {success_rate:.2%})" if not reasons else reason

        return EvaluationResult(
            tool_name=key,
            total_runs=total,
            success_rate=round(success_rate, 3),
            avg_latency_ms=round(avg_latency, 2),
            recent_failure_streak=streak,
            score=score,
            needs_improvement=needs,
            reason=reason,
        )

    def evaluate_all(self) -> dict[str, EvaluationResult]:
        # Union of registered tools + any tool with memory history
        names = set(registry.tool_names())
        # strip default. prefix for display
        normalized = set()
        for n in names:
            normalized.add(n.removeprefix("default."))
        for n in memory.all_tool_names():
            normalized.add(n)
        # Remove empty
        normalized.discard("")
        results: dict[str, EvaluationResult] = {}
        for name in sorted(normalized):
            # skip default. aliases already normalized
            if name.startswith("default."):
                continue
            results[name] = self.evaluate(name)
        return results


def evaluate_all_tools():
    evaluator = ToolEvaluator()
    results = evaluator.evaluate_all()
    if not results:
        print("[Evaluator] No tools found (registry empty & no memory history).")
        return results

    # Print table
    header = f"{'Tool':<40} {'Runs':>4} {'Succ%':>6} {'Avg ms':>7} {'Streak':>6} {'Score':>5} {'Needs?':>6}  Reason"
    print(header)
    print("-" * len(header))
    for name, r in results.items():
        succ_pct = f"{r.success_rate*100:.0f}%"
        needs = "YES" if r.needs_improvement else "no"
        print(f"{name:<40} {r.total_runs:>4} {succ_pct:>6} {r.avg_latency_ms:>7.1f} {r.recent_failure_streak:>6} {r.score:>5.2f} {needs:>6}  {r.reason}")
    return results


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        ev = ToolEvaluator()
        for tool_name in sys.argv[1:]:
            r = ev.evaluate(tool_name)
            print(f"\n[Evaluator] {r.tool_name}: runs={r.total_runs} success_rate={r.success_rate:.2%} avg_latency={r.avg_latency_ms:.1f}ms streak={r.recent_failure_streak} score={r.score} needs_improvement={r.needs_improvement} reason={r.reason}")
            # also dump recent history
            hist = memory.get_history(r.tool_name)
            if hist:
                print(f"  Recent history (last 3):")
                for h in hist[-3:]:
                    print(f"    success={h.get('success')} latency={h.get('latency_ms')} error={str(h.get('result_or_error'))[:120]}")
    else:
        evaluate_all_tools()
