---
name: maf-plan
description: Manually ask Codex GPT-6 Astra for a read-only plan for a large task in a MAF-enabled repository.
disable-model-invocation: true
---

# Manual MAF plan

Run only when the human explicitly invokes `/maf-plan`. Never invoke this skill
from task size, uncertainty, or an automatic workflow decision. Claude remains
the main implementer after planning.

1. Resolve this skill's symlink to `<tool>/skills/maf-plan/SKILL.md`; the
   entrypoint is `<tool>/flow.py`. Use the current project's Git root as
   `--repo`, not the tool repository unless they are the same.
2. Build a concise goal from the invocation arguments and current request:
   objective, existing constraints, relevant paths, and acceptance criteria.
   Read only the relevant files. Do not include secrets or conversation
   transcripts. Write this goal to a private temporary file outside Git.
3. Run `rtk proxy python3 <tool>/flow.py --repo <project> plan --mode planned
   --goal-file <private-file>`. The planned profile defaults to read-only Codex
   `gpt-6-astra` with high effort; a user-edited profile may deliberately
   select another model/effort. The CLI checks the exact subscription route
   before inference. Do not add API billing or bypass flags.
4. Summarize the plan in the current Claude chat. Treat its proposed tasks as
   suggestions, not authorization. Continue implementation only within the
   user's existing authorization. Delegate narrow independent work to Pi when
   useful, and verify the final commit with tests and an independent review.

If readiness or billing confirmation is missing, show the exact route and
blocker. Never attest to a subscription on the user's behalf without their
confirmation for that configuration. Do not automatically retry quota or
authentication failures.
