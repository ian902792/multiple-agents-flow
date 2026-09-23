"""Project-local skill discovery links. No user-wide configuration."""
import os
from pathlib import Path

from . import core


def install(repo):
    repo = Path(repo).resolve()
    source = Path(__file__).resolve().parents[1] / "skills" / "maf"
    plan_source = source.parent / "maf-plan"
    if not (source / "SKILL.md").is_file() or not (plan_source / "SKILL.md").is_file():
        raise core.FlowError("MAF skill source is missing.")
    if repo == Path.home().resolve():
        raise core.FlowError("Refusing to install skills into the user-wide home directory.")
    root = core.root_for(repo)
    links = [(source, repo / host / "skills" / "maf") for host in (".agents", ".claude")]
    links.append((plan_source, repo / ".claude" / "skills" / "maf-plan"))
    # Preflight both hosts before making any registration changes.
    for target, link in links:
        for parent in (link.parent.parent, link.parent):
            if parent.is_symlink() or (parent.exists() and not parent.is_dir()):
                raise core.FlowError(f"Refusing redirected/non-directory skill parent: {parent}")
        if link.is_symlink() and link.resolve() == target:
            continue
        if link.exists() or link.is_symlink():
            raise core.FlowError(f"Skill already exists; refusing to overwrite: {link}")
    if repo != source.parents[1]:
        exclude = root.parent / "info" / "exclude"
        exclude.parent.mkdir(exist_ok=True)
        content = exclude.read_text() if exclude.exists() else ""
        with exclude.open("a") as stream:
            for _, link in links:
                pattern = "/" + str(link.relative_to(repo))
                if pattern not in content.splitlines():
                    stream.write("\n" + pattern + "\n")
    for target, link in links:
        link.parent.mkdir(parents=True, exist_ok=True)
        if not link.is_symlink():
            link.symlink_to(os.path.relpath(target, link.parent), target_is_directory=True)
    return {"skills": [str(link) for _, link in links[:2]], "manual_plan": str(links[2][1]),
            "claude": "/maf status", "codex": "/skills -> maf, or $maf status",
            "next": "Open/reload the target project session if the skill is not listed."}
