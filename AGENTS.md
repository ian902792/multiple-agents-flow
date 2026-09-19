# multiple-agents-flow

- Python 3.11+ standard library only. Run `python3 -m unittest discover -s tests -v`.
- Keep adapters, deterministic orchestration, and GitHub policy separate.
- Existing subscription allowances only. Never add API billing fallback or bypass flags.
- Agent claims are not verification. Tests and independent review must bind to exact Git commits.
- Fail closed on unknown state, expired approval, authentication or quota ambiguity.
- Never change provider accounts, billing settings, user-wide configuration, or branch protection.
- No secrets, transcripts, runtime state, or personal absolute paths in Git.
- A worktree is not a security sandbox. Only run trusted repositories and approved test commands.
- Use `apply_patch` for edits. Preserve unrelated changes.
- Prefix development shell commands with `rtk`; machine-readable subprocess output must not be filtered.
