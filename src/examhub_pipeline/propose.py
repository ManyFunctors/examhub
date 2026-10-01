"""Write a git branch. Never commit to main, never push, never publish.

The tool's whole safety story is in this file, so it is worth stating the
rules explicitly rather than implying them:

1. The default target is ``site/`` in this repo; changes go on a new branch
   in a separate worktree, never on the checked-out branch.
2. ``main`` and ``master`` are refused as a target branch, always.
3. Nothing is pushed. ``gh pr create`` is *printed*, not run, so the human
   who reads the review output is the human who opens the pull request.
4. With ``--no-commit`` (the default) files are written into a branch
   worktree and nothing is committed at all, which is what CI wants and what
   the tests exercise.
5. A patch file is always written, so the change can be applied by hand with
   ``git apply`` if the branch route is not wanted.

The one operation this module performs on a repository is a ``git add`` and
``git commit`` on a freshly created branch, and only when ``--commit`` is
passed explicitly.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from .config import Settings
from .review import ReviewBundle

#: Branches this tool will never write to. Not a config option.
PROTECTED_BRANCHES = frozenset({"main", "master", "trunk", "develop", "production"})

#: The longest branch name git will accept, minus room for the suffix.
_MAX_BRANCH = 200


class ProposeError(RuntimeError):
    """The branch could not be created. Never raised for a partial success."""


@dataclass(slots=True)
class Proposal:
    """The outcome of one ``propose`` call."""

    branch: str
    repo: str
    files: list[str] = field(default_factory=list)
    committed: bool = False
    commit_sha: str | None = None
    worktree: str | None = None
    patch_path: str | None = None
    pr_command: str = ""
    notes: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return {
            "branch": self.branch,
            "repo": self.repo,
            "files": self.files,
            "committed": self.committed,
            "commit_sha": self.commit_sha,
            "worktree": self.worktree,
            "patch_path": self.patch_path,
            "pr_command": self.pr_command,
            "notes": self.notes,
            "skipped": self.skipped,
        }

    def render(self) -> str:
        lines = [f"branch:    {self.branch}", f"repo:      {self.repo}"]
        if self.worktree:
            lines.append(f"worktree:  {self.worktree}")
        lines.append(f"files:     {len(self.files)}")
        for name in self.files:
            lines.append(f"           {name}")
        lines.append(
            "committed: " + (f"yes ({self.commit_sha[:10]})" if self.commit_sha else "no")
        )
        if self.patch_path:
            lines.append(f"patch:     {self.patch_path}")
        for name in self.skipped:
            lines.append(f"skipped:   {name}  (left untouched; see notes)")
        for note in self.notes:
            lines.append(f"note:      {note}")
        if self.pr_command:
            lines.append("")
            lines.append("to open the pull request yourself:")
            lines.append(f"  {self.pr_command}")
        lines.append("")
        lines.append("Nothing was pushed. main was not touched.")
        return "\n".join(lines)


# --------------------------------------------------------------------------
# git plumbing
# --------------------------------------------------------------------------


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if check and result.returncode != 0:
        raise ProposeError(
            f"git {' '.join(args)} failed in {repo}: "
            f"{(result.stderr or result.stdout).strip()[:300]}"
        )
    return result


def is_git_repo(path: Path) -> bool:
    if not path.is_dir():
        return False
    result = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "--is-inside-work-tree"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    return result.returncode == 0 and result.stdout.strip() == "true"


def current_branch(repo: Path) -> str:
    return _git(repo, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()


def worktree_is_dirty(repo: Path) -> bool:
    return bool(_git(repo, "status", "--porcelain").stdout.strip())


def sanitise_branch(name: str) -> str:
    """A branch name git will accept, with any attempt to write to main
    neutralised rather than merely discouraged."""
    # Every *run* of invalid characters becomes one separator. Replacing them
    # one at a time gave "my thing!!" -> "my-thing--" and then
    # "has-spaces-and-$ymbols" -> "has-spaces-and-ymbols", gluing two words
    # together because the character between them vanished.
    cleaned = re.sub(r"[^A-Za-z0-9._/-]+", "-", name.replace("~", "-").replace("^", "-"))
    cleaned = re.sub(r"-{2,}", "-", cleaned).strip("-./")
    cleaned = "-".join(part for part in cleaned.split("-") if part) or "update"
    base = cleaned.rsplit("/", 1)[-1]
    if base.lower() in PROTECTED_BRANCHES:
        cleaned = f"{cleaned}-proposed"
    return cleaned[:_MAX_BRANCH]


# --------------------------------------------------------------------------
# The proposal
# --------------------------------------------------------------------------


def propose(
    settings: Settings,
    bundle: ReviewBundle,
    *,
    branch: str | None = None,
    repo: Path | None = None,
    commit: bool = False,
    base: str | None = None,
    use_worktree: bool = True,
    message: str | None = None,
) -> Proposal:
    """Write the bundle's changes onto a new branch.

    ``commit=False`` (the default) writes the files into a branch worktree
    and stops. Nothing is staged, nothing is committed, and running this in
    CI is therefore safe by construction.
    """
    target = Path(repo) if repo else settings.repo_dir
    material = bundle.material

    if not material:
        raise ProposeError(
            "nothing to propose: the review bundle has no material changes. "
            "This is the normal outcome of a re-run with no new information, "
            "and the reason the scheduled job skips the pull request."
        )
    if not is_git_repo(target):
        raise ProposeError(
            f"{target} is not inside a git repository; pass --repo with the "
            "Hugo site folder to write into."
        )

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    branch_name = sanitise_branch(branch or f"{settings.branch_prefix}/{stamp}-review")

    if not commit and not use_worktree:
        # Plain branch checkout, no commit. Still refuses protected branches.
        if branch_name.split("/")[-1].lower() in PROTECTED_BRANCHES:
            raise ProposeError(f"refusing to write to protected branch {branch_name!r}")

    worktree: Path | None = None
    notes: list[str] = []
    skipped: list[str] = []
    write_root = target

    try:
        if use_worktree:
            worktree_root = settings.work_dir / "branches"
            worktree_root.mkdir(parents=True, exist_ok=True)
            worktree = worktree_root / branch_name.replace("/", "_")
            base_ref = base or current_branch(target)
            if worktree.exists():
                shutil.rmtree(worktree)
            if worktree_is_dirty(target):
                notes.append(
                    "the source working tree has uncommitted changes; the branch "
                    "worktree was created from HEAD and does not include them"
                )
            _git(
                target,
                "worktree",
                "add",
                "-b",
                branch_name,
                str(worktree),
                base_ref,
            )
            # The site may be a folder inside the repo (site/), so write there in the worktree too.
            prefix = _git(target, "rev-parse", "--show-prefix").stdout.strip()
            write_root = worktree / prefix if prefix else worktree
        else:
            base_ref = base or current_branch(target)
            if branch_name.split("/")[-1].lower() in PROTECTED_BRANCHES:
                raise ProposeError(
                    f"refusing to write to protected branch {branch_name!r}"
                )
            _git(target, "checkout", "-b", branch_name, base_ref)
    except ProposeError:
        raise
    except (OSError, subprocess.SubprocessError) as exc:
        raise ProposeError(f"could not create branch {branch_name!r}: {exc}") from exc

    written: list[str] = []
    try:
        for change in material:
            destination = write_root / change.path
            if (
                change.before
                and not change.is_new
                and not _matches(destination, change.before)
            ):
                # The file on disk is not the file the diff was computed
                # against. Overwriting it would silently discard somebody
                # else's edit, so it is left alone and reported.
                skipped.append(change.path)
                notes.append(
                    f"{change.path}: on-disk content differs from the baseline the "
                    "diff was computed against; left untouched"
                )
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(change.after, encoding="utf-8")
            written.append(change.path)
    except OSError as exc:
        raise ProposeError(f"could not write files into {write_root}: {exc}") from exc

    proposal = Proposal(
        branch=branch_name,
        repo=str(target),
        files=written,
        worktree=str(worktree) if worktree else None,
    )

    patch_path = bundle.root / "propose.patch"
    if patch_path.exists():
        proposal.patch_path = str(patch_path)

    if commit:
        if not written:
            proposal.notes.append("no files were written, so nothing was committed")
        else:
            sha = _commit(
                write_root,
                written,
                message or _commit_message(bundle, branch_name),
            )
            proposal.committed = True
            proposal.commit_sha = sha
    else:
        proposal.notes.append(
            "files written to the branch worktree but NOT committed "
            "(--commit was not passed); the working tree is there for inspection"
        )

    base_branch = base or current_branch(target)
    proposal.pr_command = (
        f"git -C {target} push -u origin {branch_name} && "
        f"gh pr create --base {base_branch} --head {branch_name} "
        f"--title 'pipeline: {len(written)} exam record(s) re-checked' "
        f"--body-file {bundle.root / 'summary.txt'}"
    )
    return proposal


def _matches(path: Path, expected: str) -> bool:
    if not path.exists():
        return not expected.strip()
    try:
        return path.read_text(encoding="utf-8") == expected
    except OSError:  # pragma: no cover
        return False


def _commit_message(bundle: ReviewBundle, branch: str) -> str:
    counts = bundle.counts()
    material = bundle.material
    lines = [
        f"pipeline: re-check {len(material)} exam record(s)",
        "",
    ]
    for change in material[:10]:
        fields = ", ".join(
            c.field for c in change.material if c.is_material
        )
        lines.append(f"- {change.path}: {fields}")
    if len(material) > 10:
        lines.append(f"- ... and {len(material) - 10} more")
    lines += [
        "",
        f"Field verdicts: verified {counts['verified']}, undecided {counts['undecided']}, "
        f"disputed {counts['disputed']}, not model-checked {counts['not_validated']}.",
        "",
        "Produced by examhub-pipeline. Human-reviewed; not published automatically.",
    ]
    return "\n".join(lines) + "\n"


def _commit(root: Path, files: Sequence[str], message: str) -> str:
    # paths are relative to the site folder, so git runs from there
    _git(root, "add", "--", *files)
    _git(root, "commit", "-m", message)
    return _git(root, "rev-parse", "HEAD").stdout.strip()


def write_proposal_json(proposal: Proposal, bundle: ReviewBundle) -> Path:
    path = bundle.root / "proposal.json"
    path.write_text(
        json.dumps(proposal.to_json(), indent=2, default=str), encoding="utf-8"
    )
    return path
