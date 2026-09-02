# LoomSelf — Improvement Backlog

> Generated 2026-09-02. Source: audit of `plan.md:462`, `TUI/app.py:120`, `agent/orchestrator.py:294`, `inference/config.py:95`, `agent/registry.py:98`, `requirements.txt`.
> Scale: Tau core + mini-Hermes overlay. No web frontend — single Textual TUI.

---

## 1. UI / UX — Textual TUI is minimal single-pane log

**Today:** `TUI/app.py:16-33` inline 3-rule CSS, `TUI/app.py:52-57` `Header/RichLog/Input/Footer` only, `TUI/app.py:86-89` blocks on `agent_graph.invoke` with `… running…` spinner. `agent/events.py:62` exists but never wired.

- [ ] **UI-1 (P0) Streaming tokens** — `agent/orchestrator.py:285` switch `invoke` → `astream_events` + Textual callback, render chunks in `RichLog`. Remove frozen state. Depends on `inference/config.py:create_chat_openai(streaming=True)`.
- [ ] **UI-2 (P0) Tool timeline** — Wire `agent/events.py:render_event` + `agent/orchestrator.py:52 _wrap_with_memory` to emit `tool_call_start/end` to TUI. Show per-tool latency, success/fail icon, expandable args/result.
- [ ] **UI-3 (P0) Plan/Build mode badge + approval** — Add `Static#mode` in `TUI/app.py:52 compose`, `agent/paths.py:47` `.agent/state.json` or `SessionDB`, implement `tool_guardrails` (mutating tools removed from schema in PLAN). TUI shows `PLAN | BUILD | CONFIG` and `/plan approve` buttons (`plan.md:230-235`).
- [ ] **UI-4 (P1) Split layout** — `TUI/app.py:16 CSS` replace with `*.tcss` file: left `RichLog`, right tabs `FilePreview | Diff | Plan | AGENTS.md`. Use `Vertical/Horizontal` containers.
- [ ] **UI-5 (P1) Input upgrades** — `TUI/app.py:56 Input` → multiline, history (↑), slash commands `/plan /build /config /help`, file autocomplete via `agent/paths.py`.
- [ ] **UI-6 (P1) Cancel/interrupt** — `@work(thread=True)` exclusive blocks cancel; add `Ctrl+C` → `agent_graph` interrupt / `asyncio.CancelledError`, `run_bash` kill.
- [ ] **UI-7 (P1) Session persistence** — Persist `RichLog` to `outputs/session-<ts>.md`, export, `AGENTS.md` live view.
- [ ] **UI-8 (P2) Theme & polish** — External theme tokens, dark/light toggle, markdown/rich code rendering, `Footer` help modal `?`, status line dynamic update `TUI/app.py:59 _status_text`.

---

## 2. Inference & Speed — Fully sync, no cache/stream

**Today:** `agent/orchestrator.py:289 invoke` sync, `selfLearn/generator.py:69` sync, `inference/config.py:create_chat_openai(timeout=90, max_retries=2)` no streaming/cache. `agent/memory.py:108` rewrites JSON per tool call.

- [ ] **INF-1 (P0) Async + streaming** — Add `a_create_chat_openai`, `agent/orchestrator.py:285 ainvoke/astream`, `selfLearn/generator.py` async, keep sync fallback.
- [ ] **INF-2 (P0) LLM cache** — `langchain.cache SQLiteCache` or `ChatOpenAI(cache=True)` + `get_llm_config` memo. Skip re-pay for repeated `read_file` prompts.
- [ ] **INF-3 (P1) Parallel validation** — `selfLearn/validator.py:94 _run_import_test` + `tests/regression_runner.py:161` subprocesses → `ThreadPoolExecutor` / `asyncio.gather` (5 regressions now serial). `improve.py:65 --all` batch via `abatch`.
- [ ] **INF-4 (P1) Faster web_search** — `.agent/tools/web_search.py:220` does 3 sequential scrapes (45s). Switch to `httpx.AsyncClient` parallel + cache to `outputs/cache/`, 15s total.
- [ ] **INF-5 (P1) IO batching** — `agent/memory.py` batch `record` + `json.dumps` debounce, rotate file >10k entries → SQLite. `agent/registry.py:56 persist_tool` same.
- [ ] **INF-6 (P2) Observability** — Token/cost counter per task (even Go $10 flat), `langsmith` tracing opt-in, latency table in TUI. Fix `create_chat_openai` noisy `print` → logger.
- [ ] **INF-7 (P2) Timeouts & recursion** — Make `max_iterations=25`, `recursion_limit`, `timeout 90` configurable via `opencode.json` + CLI `--timeout`.

---

## 3. Library — Missing built-ins, unpinned deps

**Today:** `requirements.txt` unpinned `langchain>=1.0`, `agent/tools/builtins.py:84` only 3 built-ins (`read_file/edit_file/run_bash`), no `pyproject.toml`.

- [ ] **LIB-1 (P0) `pyproject.toml`** — Define `project.name=loomSelf`, `dependencies` pinned (`langchain==1.3.18`, `langgraph==1.2.11`, `openai==3.6.0`, `textual==8.2.8`), `scripts loom=main:main`.
- [ ] **LIB-2 (P0) Pin & audit deps** — Lockfile, test `openai 3.x` + `muse-spark use_responses_api` compat `inference/config.py:124`.
- [ ] **LIB-3 (P0) Add missing built-ins** — `agent/tools/builtins.py` add `write_file`, `list_directory`, `grep` (or teach `run_bash rg` via skill) per `plan.md:344`. `edit_file` keep exact-replace.
- [ ] **LIB-4 (P1) `opencode.json` parity** — Add `instructions:["AGENTS.md"]`, `agent:{plan_mode:"always"}` per `plan.md:219`, support `OPENCODE_SMALL_MODEL`.
- [ ] **LIB-5 (P1) Single dotenv loader** — Confirm `inference/config.py:95` is sole loader, remove scattered `load_dotenv` if any.
- [ ] **LIB-6 (P2) Replace `requests` sync in tools** — Generated tool template `selfLearn/generator.py:10 GENERATION_PROMPT` allow `httpx` async, deprecate raw `requests` in new tools.

---

## 4. Features — Agent is "cheap tool factory" without guardrails

**Today:** `agent/orchestrator.py:25 BASE_PROMPT` has `Composition over creation` but no gate `plan.md:112 GATE_PROMPT` not implemented. `.agent/plans` empty, `.agent/skills` empty, no `AGENTS.md`, no curator.

- [ ] **FEAT-1 (P0) Gate LLM** — Implement `GATE_PROMPT` in `agent/orchestrator.py:158 _handle_tool_request` (check `registry.tool_names()` + `skills_block()`). `sufficient=true → block` with `use_instead` hint, guards `one tool/task`, `3 rejections→stop` `plan.md:118`.
- [ ] **FEAT-2 (P0) `AGENTS.md` living memory** — Create `core/agents_md.py` sync with `<!-- loom:managed -->`, `agent/paths.py:47` `workdir/AGENTS.md`, inject into `BASE_PROMPT` + `SkillInjector` top-3 `plan.md:135`.
- [ ] **FEAT-3 (P0) Skills system** — `self_learning_agent/skills/*.md` built-ins + `.agent/skills/*.md`, `skills/__init__.py:skills_block(task)` keyword-rank top-3 injection.
- [ ] **FEAT-4 (P1) Plan/Build/Config enforcement** — Two-layer `get_tool_definitions` filter + `tool_guardrails.py` dispatch guard `plan.md:204`, `.agent/plans/<task>.md` generation, `/plan approve/reject/exit`.
- [ ] **FEAT-5 (P1) `SkillForge` + `Curator`** — `after_agent_end` hook if 5+ tool calls → suggest `SKILL.md`; `loom --skill-review` rubric scorer (accuracy/completeness/actionability/uniqueness) per `plan.md:266` — suggest prune/merge, never auto-delete.
- [ ] **FEAT-6 (P1) Tool vs Skill vs Plugin ownership** — Docs + plan doc choice `Agent-local .agent/tools/` vs `src/` scaffold via `write_file` `plan.md:118`.
- [ ] **FEAT-7 (P2) Config CLI** — `loom config set model`, `loom auth`, `loom init` (`AGENTS.md` + `opencode.json`) `plan.md:214`, per-workdir isolation `config/paths.py`.
- [ ] **FEAT-8 (P2) Tests** — `tests/test_orchestrator_block`, `test_plan_blocks_mutations`, `test_agents_md_sync`, `test_skill_injector_ranking` `plan.md:367,458`.

---

## 5. Memory — Flat JSON, no retrieval, linear token bloat

**Today:** `agent/memory.py:108` is append-only `dict[tool -> list[entries]]` at `.agent/state/memory.json` via `agent/paths.py:24 state=.agent`. Every `record()` at `agent/memory.py:56` rewrites full JSON (`indent=2`, no rotation, unbounded). `agent/orchestrator.py:52 _wrap_with_memory` logs but never injects; `agent/evaluator.py:139` + `agent/rewriter.py:155` scan whole file. No skills memory, no `AGENTS.md` compaction, no retrieval. Scales linearly — 24 entries already 594 tokens/call if naively injected, vs 166 with retrieval (72% waste) [mem0.ai 2026 playbook](https://mem0.ai/blog/the-2026-token-optimization-playbook-cut-ai-agent-memory-costs-3%E2%80%934x). Missing the 4 memory types businesses need: Working/In-context (window), Episodic (session logs), Semantic (vector/RAG), Procedural (system prompt/config) [scalacode.com 2026](https://www.scalacode.com/blog/ai-agent-memory-optimization/).

**Research takeaway (web 2026):** Best memory is text the agent can read AND write — flat-file hierarchy + hybrid search, no external DB required [agent-memory.bruegs.com](https://agent-memory.bruegs.com/). Core fix: move work from retrieval-time to storage-time (single-pass ADD-only extraction, entity linking, lightweight graph), inject top-k only [emergentmind.com](https://www.emergentmind.com/topics/memory-optimization-agent). Compaction via Hermes 4-phase (prune tool results → boundaries → structured summary → reassemble) or Anthropic Compaction API [hermes-agent.nousresearch.com](https://hermes-agent.nousresearch.com/docs/developer-guide/context-compression-and-caching/?full=true).

### Choice for LoomSelf (small-scale, per-workdir, Opencode Go $10)

| Option | Stack | Pros | Cons | Verdict |
|---|---|---|---|---|
| **A. SQLite FTS5 + hybrid search (recommended)** | `.agent/memory.db` (SQLite FTS5 + `sqlite-vec` or `sentence-transformers` optional) + `.agent/mem/*.md` flat files, BM25 + cosine, top-3 injection | Zero deps by default, per-workdir isolation `agent/paths.py:41`, matches `plan.md:443 skills.db` target, 70-85% context cut, 91%+ LoCoMo recall | Needs FTS5 + vector setup | **Default** |
| **B. Mem0 SDK** | `mem0ai/mem0` (62k★, pip `mem0ai`) — single-pass extraction + graph + retrieval in one call | 26% LoCoMo, 20-30% LongMemEval lift, 3-4× token cut proven, quick integration | Extra dep, external vector store config | Drop-in if team wants managed |
| **C. Letta/MemGPT** | Agent loop with archival memory paging | Strong long-horizon | Heavy, overkill for <10k memories | Defer |

**Pick A** for v1, keep **B** as `pip install mem0ai` toggle behind `MEMORY_BACKEND=sqlite|mem0`.

- [ ] **MEM-1 (P0) Replace flat JSON with SQLite hybrid store** — Migrate `agent/memory.py:108` → `agent/memory2.py` (keep `ExperienceMemory` API compat). Schema: `memories(id, tool, type, text, args_json, success, latency_ms, created_at)` + FTS5 `memories_fts` + optional `vec` table. `record()` does single-pass ADD-only extraction (one LLM call or rule-based for tool logs) + poison guard (`is_safe_memory` regex `ignore previous|you are now|https?://|<script` [mem0 playbook]). `_save()` → `INSERT`, not full rewrite. Keep `memory.json` importer for migration.
- [ ] **MEM-2 (P0) Retrieval, not dump** — Never inject full history. `get_relevant(task, k=3)` = BM25 + vector rank → inject top-3 only (like `SkillInjector` top-3). Fixes linear 594→166 token bloat. Add `agent/memory.py:83 get_regression_examples(n=5)` but retrieval-filtered. Wire to `agent/orchestrator.py:25 BASE_PROMPT` as `<< memories top-3 >>` block.
- [ ] **MEM-3 (P0) Memory types + flat files** — Create `.agent/mem/` hierarchy: `AGENTS.md` (procedural), `MEMORY.md` (semantic facts), `USER.md` (episodic), `sessions/*.md` (working). Mirror `agent-memory.bruegs.com` optimized stack. Agent can `read/write` them; `ensure_runtime_dirs()` adds `mem` dir.
- [ ] **MEM-4 (P1) Single-pass extraction + entity linking** — On `record()`, extract atomic fact `"User prefers lights 40% after 9pm"` not raw chunk. Defer conflict resolution to retrieval/async. Add lightweight graph: link entities (`"kitchen light" ↔ "Philips Hue strip"`) in `memory_links(from,to,rel)` to avoid chunk-boundary bloat (3k retrieved for one sentence).
- [ ] **MEM-5 (P1) Compaction / summarization** — At 85% context (272K default) or `compression.threshold` 50% for 900K: Phase 1 prune old `tool_call` results (no LLM), Phase 2-4 structured summary (one LLM call) per Hermes [hermes compaction]. Also leverage Anthropic Compaction API / OpenAI `previous_response_id` chaining when on those providers. Store summary in `MEMORY.md`, not replayed history.
- [ ] **MEM-6 (P1) Per-workdir isolation + durable config** — Extend `agent/paths.py:8 AgentPaths` with `mem: Path = state/"mem"` and `memory_db`. Keep per-repo `.agent/` so `workdir/.agent/memory.db` travels with project, not global `~/.config/loom`. Add `opencode.json: instructions:["AGENTS.md",".agent/mem/MEMORY.md"]`.
- [ ] **MEM-7 (P2) Poison guard + GC** — Validate extracted facts (`is_safe_memory`), set cost alerts at 150%/200% baseline, Curator prunes stale `success=False` streak ≥3 after N days (suggest, not auto-delete). `clear(tool)` archives to `versions/`.
- [ ] **MEM-8 (P2) Mem0 toggle** — `MEMORY_BACKEND` env: `sqlite` (default) or `mem0`. If `mem0`, delegate `record/search` to `Mem0Client` with same `get_relevant(k=3)` interface. Document in `.env.example`.

---

## 6. Token Reduction — Biggest wins are context-engineering, not shorter prompts

**Today:** Every turn resends full `BASE_PROMPT` (7 lines) + all tool schemas (`read_file/edit_file/run_bash` + `request_new_tool` + dynamic `web_search`) + full `registry.tool_names()` list + unbounded history if ever injected. `inference/config.py:create_chat_openai` no caching, no compression, no routing. `.agent/tools/web_search.py:220` returns verbose `list[dict]{title,url,snippet,rank}` uncompressed.

**2026 research:** Token optimization is context-engineering, not prompt shortening [tokenoptimize.dev](https://www.tokenoptimize.dev/guides/llm-token-optimization-strategies). 30-70% bills cut without quality loss by caching + routing + compression [getmaxim.ai](https://www.getmaxim.ai/articles/top-5-strategies-to-reduce-llm-token-usage-and-costs). 90% cut demo: 10.5k → 650 tokens via compressed tools + telemetry summary + state memory [medium.com/@ravityuval](https://medium.com/@ravityuval/how-i-reduced-llm-token-costs-by-90-using-prompt-rag-and-ai-agent-optimization-f64bd1b56d9f). Skill body 39% reduction preserves quality (less-is-more) [arxiv 2603.29919 SkillReducer](https://arxiv.org/pdf/2603.29919v2). But query-aware compression breaks prefix caching — need cache-aware design [arxiv 2607.15516](https://arxiv.org/pdf/2607.15516v1). TOON cuts JSON 30-50% [qubittool.com](https://qubittool.com/blog/toon-format-llm-token-optimization). Tools: `headroom` 60-95% tool-output compression, `llm-token-saver-rs` 30-40% prompt saving [github topics token-compression](https://github.com/topics/token-compression?o=asc&s=forks).

- [ ] **TOK-1 (P0) Prompt caching** — Enable provider caching: Anthropic `cache_control` on stable prefix (system + tool schemas), OpenAI automatic prefix caching. Keep prefix stable (don't reorder tools). Measured `usage.prompt_tokens` before/after. In `inference/config.py:create_chat_openai` add `cache=True` + `extra_headers` for Anthropic. Benefit: cache reads ~90% cheaper, eliminates resend of `BASE_PROMPT` each turn.
- [ ] **TOK-2 (P0) Just-in-time retrieval + repo memory** — Split work into phases (discovery → impl → verify) in separate sessions; stale context from failed attempts is re-billed each turn. Use `AGENTS.md` for durable project knowledge (setup, conventions) instead of per-turn typing (already MEM-3). Targeted `read_file` + `grep` beats repo dump; `RepoCoder` iterative retrieval +10% accuracy with less context [tokenoptimize.dev].
- [ ] **TOK-3 (P0) Tool definition compression** — Compress `request_new_tool` / `evaluate_and_improve_tool` schemas: terse descriptions, short `Field(description)`, example `headroom` style `cpu_analyze(json)` not 200-token prose. `agent/orchestrator.py:40 NewToolRequest` descriptions → 10-15 words max. Saves 2000→200 tokens as in 90% case study.
- [ ] **TOK-4 (P1) Output compression (headroom)** — Wrap `run_bash`/`read_file`/`web_search` results via `headroom` (compress logs/files/RAG chunks 60-95%) before LLM sees them. Add `agent/tools/compress.py` or `pip headroom`. Clips `8000 chars` → semantic compression to ~300 tokens summary.
- [ ] **TOK-5 (P1) Structured summaries + compaction** — Replace raw telemetry/logs with 300-token summary (TOK-4) + state memory 150 tokens + compressed context 200 tokens (target `~650` vs `10,500` baseline). Wire Hermes Phase 1 prune (no LLM) before Phase 3 summary.
- [ ] **TOK-6 (P1) TOON for tool I/O** — For JSON-heavy tools (`web_search` list[dict]), use TOON (Token-Oriented Object Notation) 30-50% smaller than JSON, microsecond encode. Convert `web_search` return to TOON when `len>1k`.
- [ ] **TOK-7 (P1) Route to cheap model + budget caps** — Already have `opencode.json: small_model:kimi-k2.6` but unused. Route `generator/validator` to `small_model`, main agent to `model`. Add `Bifrost`-style virtual keys: hierarchical budgets + rate limits per team/key, checked per request [getmaxim.ai gateway]. Even on Go $10 flat, log tokens to catch loops.
- [ ] **TOK-8 (P2) Skill terse mode** — Apply SkillReducer: 39% body token cut on `skills/*.md` without quality loss. Add `spartan` dual-sided (input filtering + telegraphic output) 3 levels, 70-85% context cost target [github Lofelin/claude-skill-spartan]. Injected top-3 skills only, not all.
- [ ] **TOK-9 (P2) Cache-aware compression** — Don't use query-aware `LLMLingua` per-query (breaks prefix cache). Use stable `Cmprsr`/`Selective Context` on suffix only, keep cached prefix intact [arxiv 2607.15516 two-tier model]. Measure `ρ(N,|P|)` hit rate.

**Guardrails:** Never compress `edit_file` old_string/new_string verbatim; keep diff exact. Measure `prompt_tokens`/`completion_tokens` per task in `agent/memory.py:record` and alert at 150%/200% baseline.

---

## Execution Order

`LIB-1/2 + FEAT-1/2 + MEM-1/2` → `INF-1/2 + TOK-1/2/3 + UI-1/2/3` → `LIB-3 + FEAT-3/4 + MEM-3/4/5` → `TOK-4/5/6 + INF-3/4` → remaining P2. Verify each via `pytest` + manual `python -m TUI.app` + `--task "read/edit/test without generating tool"` + `usage.prompt_tokens` delta.
