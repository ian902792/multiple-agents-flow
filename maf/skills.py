"""One-time, user-wide Claude and Codex skill discovery links."""
import os
from pathlib import Path

from . import core


def install(home=None):
    home = Path.home() if home is None else Path(home)
    source = Path(__file__).resolve().parents[1] / "skills" / "maf"
    plan_source = source.parent / "maf-plan"
    if not (source / "SKILL.md").is_file() or not (plan_source / "SKILL.md").is_file():
        raise core.FlowError("MAF skill source is missing.")
    links = [(source, home / host / "skills" / "maf") for host in (".agents", ".claude")]
    links += [(plan_source, home / host / "skills" / "maf-plan") for host in (".agents", ".claude")]
    # Preflight both hosts before making any registration changes.
    for target, link in links:
        for parent in (link.parent.parent, link.parent):
            if parent.is_symlink() or (parent.exists() and not parent.is_dir()):
                raise core.FlowError(f"Refusing redirected/non-directory skill parent: {parent}")
        if link.is_symlink() and link.resolve() == target:
            continue
        if link.exists() or link.is_symlink():
            raise core.FlowError(f"Skill already exists; refusing to overwrite: {link}")
    for target, link in links:
        link.parent.mkdir(parents=True, exist_ok=True)
        if not link.is_symlink():
            link.symlink_to(os.path.relpath(target, link.parent.resolve()), target_is_directory=True)
    return {"skills": [str(link) for _, link in links[:2]], "manual_plan": [str(link) for _, link in links[2:]],
            "claude": "/maf status, /maf-plan", "codex": "$maf status, $maf-plan",
            "next": "Open/reload Claude or Codex sessions if the skill is not listed."}
