# LoomSelf — Plan: From Cheap Tool Factory to Real Coding Agent

> **Goal:** Make LoomSelf a **coding agent first**, self-learning second — like Tau/Hermes at small scale — where `AGENTS.md` keeps it project-aware, `plugins` do things, `skills` know things, and a sub-agent builds new capabilities only when the hierarchy proves nothing existing fits. Runs on the **Opencode Go $10/mo API** (`https://opencode.ai/zen/go/v1`, OpenAI-compatible).

---

## 1. Diagnosis — Why `main` Feels Cheap

**File evidence:** `orchestrator.py:20-33`, `generator.py:8-23`, `registry.py:20-30` on `main`.

| Symptom | Root cause |
|---|---|
| Creates a tool for *everything* (read/write, `cat`, counting lines, one-off scrape) | `ORCHESTRATOR_PROMPT` says "if you lack a tool, request it" with no hierarchy. No built-ins, no gate. `request_new_tool` is the *only* tool at boot. |
| Zero coding ability | No `run_bash`, `read_file`, `write_file`, `edit` loop. Can't `grep`, `git diff`, run tests. The demo tasks in `main.py:54-55` are toy scripts, not agentic coding. |
| No `AGENTS.md` / project awareness | Agent has no memory of repo structure, conventions, or what it learned. Every run starts blank. |
| No distinction tool vs plugin vs skill | Everything is a `tools/<name>.py`. No skill markdown, no plugin manifest. Agent can't "know" vs "do". |
| Generation is unconstrained | `generator.py` allows any stdlib+requests, no banned-call AST check (`validator.py:1-85` on main is weak). No composition check. |
| LLM mis-wired for Go | `llm_config.py` supports Go but `opencode.json:2` still defaults to `muse-spark-1.2-contributor-free` on Zen. Go users pay $10 then hit Zen endpoint. |
| No plan/build/config separation | Every run immediately mutates files. No read-only planning, no config gate, no ownership signal. |

**`rewrite` branch fixes this but goes too far the other way** — keep its good parts (see §10), drop the over-engineering.

---

## 2. Reference: What Tau & Hermes Do Right (verified via web)

> Sources: `hermes-agent.nousresearch.com/docs`, `github.com/NousResearch/hermes-agent` (issues #20616, #26352), `github.com/Svtter/opencode-self-improve`, `opencode.ai/docs/rules`, `agents.md`.

**Tau (disciplined coding agent pattern):**
- 5 built-ins only: `read`, `write`, `bash`, `list_dir`, `fetch`. Everything else is *composition* via `bash` (python/node one-liners, `grep -r`, `pytest`).
- Strong `AGENTS.md` at repo root: project map, conventions, tool table — **read at prompt injection, rewritten by agent after each extension**.
- Instruction: *"Composition over creation. If you can do it by combining existing tools + a 10-line script in `run_bash`, do that."*

**Hermes (self-evolving agent) — at scale:**

Hermes is the 210k-star Nous Research agent. Its differentiator is a built-in learning loop, not just code gen:

- **Three-layer memory:** persistent SQLite + FTS5 across sessions, Honcho user modeling ("how you communicate, what projects you own"). Every session extracts facts/preferences.
- **Skills as procedural memory:** after a task with ~5+ tool calls, Hermes writes a reusable `SKILL.md` (name, description, steps). Skills live under `~/.hermes/skills/`, become slash commands, follow `agentskills.io`. They are *patched during use* when outdated.
- **Autonomous Curator:** scheduled background job that re-scores skills (accuracy/completeness/actionability/uniqueness), merges duplicates, archives stale ones, protects pinned skills. Never touches bundled/hub skills. Controlled via `curator.enabled`, `min_idle_hours`.
- **SkillInjector:** before each turn, inject top-3 relevant skills into system prompt (not all skills — ranked injection).
- **Plan/Build enforcement (issues #20616, #26352):** Hermes ships a `/plan` *skill* (advisory only, one-shot, evicted on compaction) but users demand a config-level `agent.plan_mode` + `/plan` + `/build` *toggles* with **tool-level enforcement** like OpenCode: (1) system prompt constraint + (2) **mutating tools literally removed from the tool schema** passed to the LLM in plan mode. Design sketch: mode stored in `SessionDB state_meta` (`plan:<session_id>`), survives compaction, two-layer fail-closed enforcement (toolset restriction + dispatch guard in `tool_guardrails.py`), approval via `clarify` buttons on Telegram/Discord.

**Small-scale port: `opencode-self-improve` (Svtter):** Hermes pattern shrunk to an OpenCode plugin — **SkillForge** (`agent_end` hook → extract patterns → create/update skill), **Curator** (timer → re-score/prune/merge), **SkillInjector** (`before_agent_start` → inject top-3), **SkillStore** (SQLite), **RubricScorer** (4 dims). LoomSelf should copy *this scale*, not full Hermes.

**OpenCode + AGENTS.md (opencode.ai/docs/rules, agents.md spec — 60k+ repos):**
- `AGENTS.md` is the README-for-agents: setup, tests, code style, project structure. OpenCode discovers `AGENTS.md` at git root → `~/.config/opencode/AGENTS.md` (global) → fallback `CLAUDE.md`. `opencode.json` `instructions` field can load multiple globs (`packages/*/AGENTS.md`, remote URLs). Keep it concise, reference detailed guidelines.

**LoomSelf should be Tau at its core, mini-Hermes on top.** Not the other way around. And plan/build should be *enforced*, not suggested.

---

## 3. Core Principle — Agent First, Learning Second

```
Phase 1: Make it a useful coding agent WITHOUT any self-learning
   └─> if it can't `read -> edit -> test -> commit` without generating a tool, it's not an agent

Phase 2: Overlay self-learning as a *privilege*, not the default
   └─> gated, budgeted, only for genuinely reusable gaps, curated over time
```

**Rule:** Self-extension is a *fallback*, not the strategy. The agent must prove it tried existing tools first and that the gap is *reusable*.

---

## 4. Target Architecture (mini-Hermes for LoomSelf)

```
┌─────────────────────────────────────────────────────────────────────┐
│  Main Coding Agent (LangGraph create_agent — rewrite preferred)      │
│  System prompt = BASE_SYSTEM_PROMPT + AGENTS.md + injected skills   │
│  Budget: max_iterations=25, max_execution_time=300s                  │
│                                                                      │
│  Built-ins (always in context):                                      │
│   read_file · write_file · edit_file · run_bash · list_directory   │
│   fetch_url · grep (via run_bash rg) · git ops (via run_bash)      │
│                                                                      │
│  Modes (tool-level enforced, like OpenCode/Hermes #26352):          │
│   PLAN   — read/search/plan only, mutating tools removed from schema│
│   BUILD  — full execution                                            │
│   CONFIG — setup keys, models, workdir, no task execution            │
│                                                                      │
│  Meta-tools (gated, build mode only):                               │
│   request_new_tool  ──► Gate LLM ──► Sub-agent Generator ──►       │
│   request_new_skill ──► (main writes, validated) ──►                │
│                                                                      │
│  Learning loop (background, small scale — like opencode-self-improve):│
│   SkillInjector (before turn) → SkillForge (after turn) → Curator  │
│                                                                      │
│  Registry: builtins (code) + learned tools (.agent/tools/*.py +    │
│            manifest.json) — exposed via DynamicToolMiddleware        │
│                                                                      │
│  Memory: AGENTS.md (project map) + skills/*.md (know-how)          │
│          SQLite skill store (optional, for scoring) + outputs/      │
└─────────────────────────────────────────────────────────────────────┘
```

Keep per-workdir isolation from `rewrite`: `config/paths.py:20-30` (`workdir/.agent/tools`, `.agent/skills`, `outputs/`, `AGENTS.md`, `.agent/skills.db` if using SQLite). Essential for a coding agent that runs against arbitrary repos (`cli.py:25-33 --workdir`).

---

## 5. Fix the Cheap Part — Tool-Use Hierarchy + Ownership

### 5.1 Hierarchy the agent MUST follow (replaces `orchestrator.py:20-33`)

1.  **Can I answer directly or with a one-liner in `run_bash`?** → Do it. No tool/skill. Example: `generate a password` → `run_bash("python3 -c 'import secrets...'")`.
2.  **Can I compose existing tools?** → Do it. Example: "top 10 grossing films" → `fetch_url` → `run_bash` parse → `write_file(outputs/movies.txt)`.
3.  **Is there already a learned tool/skill that covers this?** → Use it. `registry.tool_names()` and `skills_block()` are in the prompt.
4.  **Is the gap *reusable* and not expressible as (1) or (2)?** → `request_new_tool` (does) or `request_new_skill` (knows). Everything else → rejected.

**Enforcement (keep from `rewrite`):**

- `GATE_PROMPT` (`orchestrator.py:37-76`) — second LLM call that checks proposal against catalog. `sufficient=true` → block with `use_instead` hint. Fail-open so gate never bricks.
- Guards: `one tool per task` (`orchestrator.py:378`), `3 rejections → hard stop` (`orchestrator.py:403`), `DUPLICATE_KEYWORDS` fast-path (`orchestrator.py:110-118`).
- Prompt line: *"Every request_new_tool call is vetted… redundant requests are rejected"* (`orchestrator.py:105-107`) — tell the *main* LLM this so it self-censors.

### 5.2 Ownership — The Notion Example, Corrected

**Previous plan's confusing example:** "Build a reusable Notion API client" — does the *user* now own this in their codebase? **No. Clarified:**

| Question | Answer |
|---|---|
| Where does a generated `notion_client` live? | **Agent-owned** by default: `.agent/tools/notion_client.py` + `manifest.json`. Private to LoomSelf, not committed to the user's repo. Used via registry in future tasks. |
| When does it become project-owned? | Only if user explicitly asks: `"scaffold a Notion client into src/notion/"` or `"add it to the codebase"`. Then agent uses `write_file`/`edit_file` to emit `src/notion/client.py` + tests, as normal coding — not via `request_new_tool`. Plan mode must surface this choice. |
| Why the distinction? | Reusable *for the agent* ≠ reusable *for the project*. Tool = agent's private capability (like Hermes skills in `~/.hermes/skills/`). Project code = committed, reviewed, owned by user. Conflating them pollutes the repo with agent internals. |
| How does user control it? | `/build` vs `/plan` output + `AGENTS.md` table. In plan, agent writes: `Option A: agent-local tool (.agent/tools/) — no repo change. Option B: scaffold into src/ — adds 3 files, requires review.` User picks. |

**Rule:** `request_new_tool` = agent-local. Scaffolding into repo = `write_file`/`edit_file` via normal build mode, gated by plan approval.

---

## 6. AGENTS.md — The Agent's Living Project Memory

**What it is:** Repo-root markdown the agent reads at start and rewrites after every extension. Not a log — a *reference*. Per `agents.md` spec + `opencode.ai/docs/rules`.

**Location:** `AGENTS.md` at `workdir` root (`config/paths.py:29`). Must travel with the project. Also support `opencode.json: instructions: ["AGENTS.md", "packages/*/AGENTS.md"]` for monorepos, and don't clobber existing files — use `<!-- loom:managed -->` markers.

**Content contract (`core/agents_md.py:20-75` from `rewrite` is good — keep it, add mode section):**

```markdown
# AGENTS.md — <project name>
_Last synced: 2026-09-01 12:00:00_  <!-- loom:managed -->

## Setup
- Install: `pnpm install` / `pip install -e .`
- Test: `pytest` / `pnpm test`

## Tools (N)
### Built-in
| Name | Description |
### Learned (agent-local, .agent/tools/)
| Name | Description | Uses |

## Skills (M)
- **csv_analysis** — when to use, one-liner (injected top-3 per turn)
Skill bodies: self_learning_agent/skills/*.md + .agent/skills/*.md

## Modes
- PLAN — read-only, produces .agent/plans/<id>.md
- BUILD — full execution, requires plan approval if plan_mode=always
- CONFIG — `hermes config`-style setup

## Self-extension
- `request_new_tool` (build only) — agent-local, validated, curated
- `request_new_skill` — markdown playbook, scored by Curator
Rule: tools DO, skills KNOW. Reusable for agent ≠ committed to repo.
```

**When to sync:** `sync_agents_md()` after `registry.persist_tool()` and after `request_new_skill` writes (`orchestrator.py:459,554`). Also on boot via `ensure_runtime_dirs()`. Curator updates counts/scores.

**How agent stays aware:** `SkillInjector` pattern (mini-Hermes) — before each turn, rank skills by relevance to task (keyword + embedding, take top-3) and inject only those, not the full library. Keeps context small. `AGENTS.md` summary injected always; full skill bodies only if relevant.

---

## 7. Plugins vs Skills vs Tools — Clear the Confusion

| Kind | What it is | Lives at | When agent needs it | Who makes it | Ownership |
|---|---|---|---|---|---|
| **Tool** | Executable Python function (`def fetch_foo(...) -> dict`) | `.agent/tools/<name>.py` + `manifest.json` (or SQLite) | Capability gap — "I need to *do* something I have no code for" | Sub-agent `ToolGeneratorAgent` → `validator.py` → `registry` | Agent-local |
| **Skill** | Markdown playbook injected into system prompt (top-3) | `self_learning_agent/skills/*.md` (built-in) + `.agent/skills/*.md` (learned) | Knowledge gap — "I need *guidance* that would improve every similar task" | Main agent writes via `request_new_skill` (no code gen), scored by Curator | Agent-local |
| **Plugin** | Bundled extension (tools + skills + hooks) | `.opencode/plugins/<name>/` or `self_learning_agent/plugins/` (future) | Cross-cutting suite (e.g. `github`, `postgres`) | Human or sub-agent scaffolds a directory | Agent-local until scaffolded |

**Recommendation:** Don't build a plugin system v1. Tools + skills already cover 95%. If you want plugins, make them *thin wrappers* that install a set of tools/skills + `opencode.json` hooks — don't invent a third registry yet. Defer to Phase 3.

**How agent knows which to request:**

```
Need to RUN something?    → request_new_tool  (build mode only)
Need to REMEMBER something? → request_new_skill
Need a SUITE for a service? → (future) request_new_plugin or scaffold into src/
```

Encode in `BASE_SYSTEM_PROMPT:86-98` and `skills/tool_authoring.md:7`.

---

## 8. Build / Plan / Config Modes — Mini-Hermes (NEW)

This is the biggest missing piece from both `main` and `rewrite`. Hermes issue #26352 + OpenCode's proven pattern: **plan mode must be enforced at the tool-schema layer, not just prompted.**

### 8.1 Modes

| Mode | CLI | What agent can do | How enforced | Output |
|---|---|---|---|---|
| **PLAN** | `/plan`, `--plan`, `agent.plan_mode: always` | Read, search, `grep`, produce `.agent/plans/<id>.md`. No writes outside plan file, no `run_bash` that mutates. | **Two layers, fail-closed:** (1) `get_tool_definitions(enabled_toolsets=[read,search,skill])` — mutating tools removed from schema; (2) dispatch guard in `tool_guardrails.py` blocks `MUTATING_TOOL_NAMES` if session state is `planning`/`pending_approval`. Unreadable state → blocked, not open. | `.agent/plans/<task>-<date>.md` with options, risks, file list, ownership choice |
| **BUILD** | `/build`, `/plan approve`, default | Full execution, gated `request_new_*` allowed. | Normal toolset. | Edits, tests, `outputs/`, agent-local tools/skills |
| **CONFIG** | `/config`, `loom config`, `--workdir`, `opencode auth` | Setup keys, models, workdir, `AGENTS.md` init. No task execution. | Separate command, never in agent turn. | `~/.config/loom/config.yaml` or `.env`, `opencode.json` |

### 8.2 Config mode specifics (small scale)

Hermes stores per-profile `~/.hermes/config.yaml` + `~/.hermes/.env`. LoomSelf mirrors but smaller:

- **One dotenv loader only:** `config/llm.py:25-34` (not scattered `main.py:3-14`). Candidates: `workdir/.env` → `~/.config/loom/.env` → `package_root/.env`.
- **`loom config` commands:**
  - `loom config set model kimi-k2.6` / `loom config set provider opencode-go`
  - `loom auth` → checks `OPENCODE_GO_API_KEY` vs `OPENCODE_ZEN_API_KEY` vs `OPENAI_API_KEY`
  - `loom init` → creates `AGENTS.md` from template + `opencode.json` with `instructions` field (like `opencode /init`)
- **`opencode.json` as config layer** (not just model):
  ```json
  {
    "model": "opencode/kimi-k2.6",
    "instructions": ["AGENTS.md", "packages/*/AGENTS.md"],
    "agent": { "plan_mode": "always" }
  }
  ```
  `agent.plan_mode: always` = every new session starts in PLAN, needs explicit `/plan approve` → BUILD (fixes Hermes #20616 "always plan first" demand for SRE safety).
- **Per-task override:** `loom --plan "add feature X"` starts in plan, `loom --build "fix typo"` skips plan.

### 8.3 Plan approval flow (like Hermes #26352 sketch)

1. User: `loom --plan "add auth"` → session state `plan:<id> = {status: planning, plan_path: .agent/plans/add-auth-20260901.md}`
2. Agent in PLAN: reads codebase, writes plan file (only write allowed), ends with `clarify: "Plan ready — approve execution? [Approve / Keep planning]"` — buttons on TUI, text in CLI.
3. User: `/plan approve` → state `approved`, toolset restriction lifted. Or `/plan reject <feedback>` → back to planning. `/plan exit` discards without approving (never silent approve).
4. Agent in BUILD: executes plan, gated `request_new_tool` if needed, `sync_agents_md()` on extension.
5. State survives compaction/restart (stored in `SessionDB state_meta` or `.agent/state.json` for LoomSelf small scale).

### 8.4 Why this matters for ownership question

Plan doc forces the agent to state **before mutating**:

> "This task needs a reusable Notion capability. Options: (A) agent-local tool `.agent/tools/notion_client.py` — no repo change, reusable for future agent tasks. (B) scaffold `src/integrations/notion/client.py` — adds 3 files to your repo, you own it. Recommend A unless you need it in production code."

User picks. No surprise tool in repo.

---

## 9. Sub-Agent Factory + Learning Loop (Small-Scale Hermes)

**Anti-pattern on `main`:** main agent writes tool code in same context → sloppy.

**Mini-Hermes loop (keep `rewrite` + add Curator/Forge):**

- **Main agent = planner/executor** — decides *what* is missing, emits spec (`NewToolRequest:194-205`).
- **ToolGenerator sub-agent** (`ToolGeneratorAgent:40-77`) — narrow prompt ("one function, no markdown, stdlib+requests only") writes code.
- **Validator** (`core/validator.py`) — AST banned calls (`os.system`, `eval`, `exec`, `shutil.rmtree`...), smoke import.
- **Registry** → `DynamicToolMiddleware` (`orchestrator.py:139-169`) — injects into live run.

**For skills:** main agent writes markdown itself, but **mini pipeline** inspired by `opencode-self-improve`:

| Component | When | Does what | LoomSelf small scale |
|---|---|---|---|
| **SkillInjector** | `before_agent_start` | Inject top-3 relevant skills into prompt | `skills/__init__.py: skills_block(task)` — keyword match,  not all skills |
| **SkillForge** | `after_agent_end` | Extract pattern if task had 5+ tool calls and was completed, create/update `SKILL.md` | Background hook: if task repeated 2-3x, suggest skill via `request_new_skill` (don't auto-create silently v1; surface suggestion) |
| **Curator** | Timer / `loom curator` / `--skill-review` | Re-score (accuracy/completeness/actionability/uniqueness), merge duplicates, prune low-quality | Manual `loom --skill-review` or weekly cron; rubric scorer simple (usage count + recency + user rating); never touches `self_learning_agent/skills/` bundled |
| **SkillStore** | Always | SQLite or markdown + `manifest.json` | Start with `.agent/skills/` markdown + `skill.json` frontmatter (`score`, `uses`, `created_at`). Upgrade to SQLite if needed. |

**Budget:** One `request_new_tool` per task (`_extension_attempted`). `request_new_skill` unlimited but duplicate-checked. Curator never auto-deletes in v1 — suggests.

---

## 10. Opencode Go ($10/mo) Wiring — Fix the API Layer

**Current bug:** `opencode.json:2` pins `muse-spark-1.2-contributor-free` on Zen even when Go key is set.

**Fix (keep `rewrite` `config/llm.py:1-145`):**

- Env priority: `OPENCODE_GO_API_KEY` → `https://opencode.ai/zen/go/v1` · `OPENCODE_ZEN_API_KEY`/`OPENCODE_API_KEY` → `https://opencode.ai/zen/v1` · fallback `OPENAI_API_KEY`.
- `.env` loader lives in **one place** — `config/llm.py:25-34`.
- Model default: if `base_url` contains `/go` → `DEFAULT_GO_MODEL = kimi-k2.6` (good for Go), else `muse-spark-1.2`. Override via `OPENCODE_MODEL` / `OPENCODE_SMALL_MODEL` / `--model`.
- `muse-spark` requires `use_responses_api=True` and base `.../v1` (not `/chat/completions`) — handled at `config/llm.py:124-131`. Don't set it for Kimi.
- `opencode.json` should expose **both** providers + instructions + plan_mode:

```json
{
  "model": "opencode/kimi-k2.6",
  "small_model": "opencode/kimi-k2.6",
  "instructions": ["AGENTS.md"],
  "agent": { "plan_mode": "always" },
  "provider": {
    "opencode-go": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "Opencode Go",
      "options": {
        "baseURL": "https://opencode.ai/zen/go/v1",
        "apiKey": "{env:OPENCODE_GO_API_KEY}"
      }
    }
  }
}
```

Document in `.env.example` (currently deleted on `main` — restore from `rewrite`).

---

## 11. Keep vs Drop — Curating the `rewrite` Branch

**Keep (good parts):**

- `config/paths.py` per-workdir isolation + `ensure_runtime_dirs()`
- `tools/builtins.py` 5 built-ins (245 lines) — add `edit_file`
- `skills/*.md` + `skills/__init__.py` injection (`skills_block()`)
- `core/agents_md.py` living AGENTS.md
- `core/registry.py` builtin vs learned split, `unique_tools()`, `builtin_names`
- `core/generator.py` narrow sub-agent, `textutils.py` unwrapping
- `orchestrator.py` gate, `DynamicToolMiddleware`, per-task guards, event system (`core/events.py`), `BASE_SYSTEM_PROMPT` hierarchy
- `cli.py` + `tui/app.py` + `pyproject.toml` installability
- `core/validator.py` banned-call AST check

**Fix before merging:**

- `orchestrator.py:183-191` duplicates `_build_orchestrator_prompt()` — dedupe.
- `AGENTS.md` path writes to workdir root — use `<!-- loom:managed -->` markers, don't overwrite user sections.
- `tools/builtins.py` missing `edit_file` — add for coding agent.
- `TOOLS_DIR` in `registry.py` points to `get_paths().tools` (`.agent/tools`) but `main.py` old `tools/manifest.json` is at `tools/` — add migration.
- Tests (`tests/test_*.py`) from `rewrite` — add e2e `test_orchestrator_block` + `test_plan_mode_blocks_mutations`.

**Drop / defer:**

- Don't claim `langchain.agents.create_agent` migration done until e2e tested — keep classic fallback but make langgraph primary.
- Don't build full Hermes Honcho/SessionDB — start with `.agent/state.json` + plan files. Graduate if needed.
- Remove stale `main.py` toy tasks (`main.py:53-55` movies) — replace with coding tasks: "write tests for X", "refactor Y".

---

## 12. Roadmap — Agent First, Then Learning, With Modes

### Phase 0 — Reset (1 day)
- `git checkout main` then cherry-pick `rewrite` keeps above (or merge rewrite → prune).
- Restore `plan.md` (this file), `.env.example`, `pyproject.toml`.
- Fix duplicate prompt, add `edit_file` builtin, add `opencode.json` `instructions` + `agent.plan_mode`.

### Phase 1 — Coding Agent Without Learning (1-2 weeks)
- Built-ins: `read_file`, `write_file`, `edit_file`, `run_bash`, `list_directory`, `fetch_url` — all with Pydantic schemas.
- System prompt: `BASE_SYSTEM_PROMPT` with hierarchy (§5) + `AGENTS.md` injection + `SkillInjector` top-3.
- Loop: `create_agent` (langgraph) with `DynamicToolMiddleware` stub even before learning exists.
- **Modes:** Implement PLAN vs BUILD enforcement (tool schema removal + dispatch guard) + `.agent/plans/` writing. CONFIG via `loom config`/`loom init`.
- Validation: Can agent `read prompt → edit code → run pytest → fix` without `request_new_*`? And does plan mode block `edit_file` until approved?

### Phase 2 — Self-Learning Overlay (1 week)
- Gate LLM + `request_new_tool` / `request_new_skill` (build mode only).
- Sub-agent generator + validator + registry persist.
- `SkillForge` suggestion hook (after task) + `sync_agents_md()` on extension.
- Heuristic: If task says "create a reusable X tool" → allow. If one-off Q&A → gate blocks. Tune `GATE_PROMPT` with few-shot examples.

### Phase 3 — Curator & Ownership Polish (1 week)
- `loom --skill-review` / `loom curator` — rubric scorer (usage, recency, accuracy, uniqueness), suggest prune/merge.
- Ownership choice in plan doc: agent-local `.agent/tools/` vs scaffold into `src/` via `write_file`.
- Add `grep`/`glob` or teach `run_bash rg` via skill.
- Wire Opencode Go end-to-end (cred check, `opencode.json`, docs).

### Phase 4 — Hardening
- Cost tracking per task (Go $10 flat but still log tokens).
- Tool quality score: deprecate unused tools after N days (curator suggests, not auto-deletes).
- E2e tests: `test_plan_blocks_mutations`, `test_orchestrator_block`, `test_agents_md_sync`, `test_skill_injector_ranking`.

---

## 13. How the Agent Decides at Runtime — Concrete Flow

```
User: "Add a CSV cleaning skill and fix the broken import in src/foo.py"
Mode: BUILD (plan_mode=always but task is small → agent can still ask to plan)

Main agent (Kimi via Go, SkillInjector injected csv_analysis top-3):
  1. READ: AGENTS.md + skills → knows repo is Python, csv_analysis exists
  2. PLAN (if plan_mode=always, writes .agent/plans/fix-import-20260901.md first,
     waits for /plan approve — ownership: no new tool needed, just edit)
  3. BUILD: read_file("src/foo.py") → sees broken import
  4. edit_file("src/foo.py", oldString=..., newString=...) → fixes
  5. run_bash("pytest tests/test_foo.py") → verifies
  6. Skill decision: "CSV cleaning" → skill gap? csv_analysis already covers it → no request.
     If genuinely new pattern: request_new_skill(skill_name="csv_dedupe",
       description="dedupe CSV rows by key", guidance="...") → .agent/skills/csv_dedupe.md → Curator scores later

User: "Build a reusable Notion API client"
Mode: PLAN

Main agent in PLAN (mutating tools removed from schema):
  1. Searches codebase (read/grep only), measures: no notion tool, needs auth/pagination
  2. Writes .agent/plans/notion-client-20260901.md:
     "Option A (agent-local): .agent/tools/notion_client.py — reusable for agent tasks, NOT in repo.
      Option B (project-owned): scaffold src/integrations/notion/client.py + tests — you own it in repo.
      Gates: if reusable for agent only → A, if app needs it in prod → B. Recommend A."
  3. Clarify: "Plan ready — approve? [Approve A / Approve B / Keep planning]"
User: /plan approve A

Main agent in BUILD (gate checks catalog → sufficient=false):
  1. Calls request_new_tool(tool_name="notion_client", ...) → sub-agent → validator → .agent/tools/
  2. Calls notion_client(...) with concrete args
  3. sync_agents_md(), SkillForge notes pattern for future
```

---

## 14. What to Add Next (Beyond Mini-Hermes)

- `edit_file` not `write_file` for edits — exact replace, avoids overwriting.
- Diff preview — `run_bash("git diff")` before commit, gated in build approval.
- Checkpoint — `run_bash("git stash")` before risky edits.
- `AGENTS.md` nesting — `packages/*/AGENTS.md` via `opencode.json` instructions, like OpenCode does.
- Remote instructions — `https://your-org.example.com/shared-rules.md` in `opencode.json`.

---

## 15. File Map After This Plan

```
loomSelf/
├── plan.md                      ← this file
├── AGENTS.md                    ← living, per-workdir (gitignored, generated, loom:managed)
├── .agent/
│   ├── plans/<task>.md          ← plan mode outputs, requires approval
│   ├── tools/<name>.py + manifest.json  ← agent-local tools (NOT repo code)
│   ├── skills/<name>.md + skill.json    ← learned skills, scored by Curator
│   └── state.json               ← plan:<id> mode state (or SessionDB later)
├── opencode.json                ← model + instructions + agent.plan_mode
├── .env / .env.example          ← OPENCODE_GO_API_KEY (single loader in config/llm.py)
├── pyproject.toml
├── main.py                      ← thin shim → self_learning_agent.cli:main
├── self_learning_agent/
│   ├── config/llm.py            ← Go/Zen/OpenAI resolver
│   ├── config/paths.py          ← workdir isolation
│   ├── core/orchestrator.py     ← loop + gate + plan/build enforcement
│   ├── core/agents_md.py        ← AGENTS.md sync (with markers)
│   ├── core/registry.py         ← builtins + learned
│   ├── core/generator.py        ← sub-agent
│   ├── core/validator.py        ← AST + smoke
│   ├── core/curator.py          ← (new, mini) rubric scorer + prune/merge suggestions
│   ├── tools/builtins.py        ← + edit_file
│   ├── skills/*.md              ← 5 built-ins, top-3 injected
│   └── tui/app.py               ← shows mode badge (PLAN/BUILD), plan preview
└── outputs/                     ← per-project artifacts (never /tmp)
```

---

## 16. Success Criteria

- [ ] Coding tasks `read/edit/test` complete **without** generating a tool, in both PLAN→BUILD and direct BUILD.
- [ ] One-off Q&A answered via `run_bash` + `fetch_url`, gate blocks `request_new_tool`, plan mode blocks `edit_file`.
- [ ] Reusable capability: plan doc offers agent-local vs project-owned choice; `notion_client` generates once into `.agent/tools/` if A, or scaffolded into `src/` if B.
- [ ] `AGENTS.md` after 5 tasks lists correct built-ins + learned tools + skills with timestamps; `opencode.json` `instructions` works for `packages/*/AGENTS.md`.
- [ ] `--plan` produces `.agent/plans/*.md` and `build` is blocked until `/plan approve`; config `plan_mode: always` persists across restarts (like Hermes).
- [ ] Sub-agent generation + Curator scoring + `SkillInjector` top-3 + `DynamicToolMiddleware` work end-to-end.
- [ ] `opencode.json` + `.env.example` work with a fresh Go $10 subscription (single Go key, no Zen confusion).
- [ ] `pytest` passes including `test_plan_blocks_mutations`, `test_orchestrator_block`, `test_agents_md_sync`.

---

*This plan is the spec. Implement Plan→Build→Config modes first — if the agent can't separate planning from building, learning will only make it worse. Start small like opencode-self-improve, not full Hermes.*
