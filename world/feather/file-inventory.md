# Feather inventory — plugins/evo tree

**Agents**
- `verifier.md` — static audit: leakage, gates, hypothesis, artifacts; pre/post phases
- `ideator.md` — experiment proposals: failure_analysis, literature, frontier_extrapolation
- `benchmark-reviewer.md` — benchmark audit & per-task failure classification

**Skills** (excludes detailed subagent/SKILL.md above)
- `discover/`, `optimize/`, `report/`, `ship/` — main orchestrator workflows
- `finetuning/`, `infra-setup/`, `subagent/` — category-specific protocols

**Resources**
- `references/` — CLI quick ref, SDK (Python/JS), inline_instrumentation, CLI docs, evo-wait
- `finetuning/references/`, `discover/references/` — technique sheets, trace schema, ART, vLLM
- `bin/` — helper scripts (`evo`, `evo-dashboard`, `evo-drain`, `evo-gates`)
- `commands/` — plugin command manifests (`.claude-plugin/`, `.codex-plugin/`, `.kimi-plugin/`)
- `hooks/` — host-specific hook definitions (e.g. `claude_code_tool_use_end`)
- `src/evo/` — core Python (dashboard, graph, scratchpad)
- `sdk/python/`, `sdk/node/` — minimal SDK for `evo.record(score)` instrumentation

**Config & tests**
- `pyproject.toml`, `uv.lock` — Python deps
- `tests/` — e2e + live suites + fixtures
- `scripts/` — dashboard.py, graph.py, scratchpad.py, harness scripts

**Runtime data (not committed)**
- `.evo/` — active run state (config, graph.json, experiments/, traces/)
- `logs/` — benchmark/infra logs
- `cache/` — reusable intermediate artifacts
- `workspace_notes.json` — global notes visible to all subagents

**Host plugin manifests**
- `.claude-plugin/` — Claude Code plugin definition
- `.codex-plugin/` — Codex plugin definition  
- `.kimi-plugin/` — Kimi plugin definition

**Size pattern:** core agents (verifier/ideator/benchmark-reviewer) are 11–12k lines; skill protocol files are large (subagent/SKILL.md = 417 lines); reference docs are concise (200–500 lines).