---
name: maf-plan
description: Manually ask a strong planner from a different agent (Codex for a Claude main chat, Claude Opus 5.5 or Fable 5.1 for a Codex main chat) for a read-only plan of a large task in a MAF-enabled repository.
disable-model-invocation: true
---

# Manual MAF plan

Run only when the human explicitly invokes `/maf-plan` (Claude) or `$maf-plan`
(Codex). Never invoke this skill from task size, uncertainty, or an automatic
workflow decision. The current main chat remains the implementer after planning.

The planner is the selected flow's `planner` role and must be a different agent
from the current main chat: a Claude chat uses the flow's Codex planner (default
`gpt-6-astra`, high effort); a Codex chat uses the flow's Claude planner (default
`claude-opus-5-5`, high effort; the user may select `claude-fable-5-1` in Flow
Studio). A second, independent model catches assumptions the main chat shares
with itself. If the selected flow's planner uses the same runtime, the CLI refuses;
report that and suggest a flow or Flow Studio change instead of working around it.

1. Resolve this skill's symlink to `<tool>/skills/maf-plan/SKILL.md`; the
   entrypoint is `<tool>/flow.py`. Use the current project's Git root as
   `--repo`, not the tool repository unless they are the same.
2. Build a concise goal from the invocation arguments and current request:
   objective, existing constraints, relevant paths, and acceptance criteria.
   Read only the relevant files. Do not include secrets or conversation
   transcripts. Write this goal to a private temporary file outside Git.
3. Run `python3 <tool>/flow.py --repo <project> --main <claude|codex> plan
   --goal-file <private-file>`, with `--main` naming the current chat's runtime.
   Add `--mode NAME` only when the user names a flow. The CLI checks the exact
   subscription route before inference. Inside Herdr, when the user-wide
   integration is on, a temporary read-only planner pane opens and closes
   automatically. Do not add API billing or bypass flags.
4. Summarize the plan in the current chat. Treat its proposed tasks as
   suggestions, not authorization. If implementation is not already authorized,
   show the concrete paths, tests, roles and risks and ask once before starting.
   Then continue within the approved scope without repeated prompts. Delegate
   narrow independent work to the flow's small-task agent when useful, and
   verify the final commit with tests and, when enabled, an independent review.

If readiness or billing confirmation is missing, show the exact route and
blocker. Never attest to a subscription on the user's behalf without their
confirmation for that configuration. Do not automatically retry quota or
authentication failures.
