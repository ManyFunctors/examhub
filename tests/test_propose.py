"""Tests for branch naming, the protected-branch rules, and the commit path.

The commit test runs in a throwaway repository under tmp_path; nothing here
pushes.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from examhub_pipeline import record as rec_ops
from examhub_pipeline.config import Settings
from examhub_pipeline.propose import (
    PROTECTED_BRANCHES,
    Proposal,
    ProposeError,
    is_git_repo,
    propose,
    sanitise_branch,
)
from examhub_pipeline.review import build_bundle


def record(vacancies: int | None = None) -> dict:
    r = rec_ops.skeleton(title="SSC CGL 2027", slug="ssc-cgl-2027", body="in-ssc")
    if vacancies is not None:
        rec_ops.set_value(r, "vacancies", str(vacancies))
    return r


class TestBranchNames:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("pipeline/2026-09-27-review", "pipeline/2026-09-27-review"),
            ("feat/my thing", "feat/my-thing"),
            ("feat/my  thing!!", "feat/my-thing"),
            ("has spaces and  $", "has-spaces-and"),
            # A stray symbol between two words is dropped and the words close
            # up. That is fine for a branch name and better than guessing
            # where the word boundary was.
            ("has and $ymbols", "has-and-ymbols"),
            ("a" * 500, "a" * 200),
        ],
    )
    def test_sanitisation(self, raw, expected):
        assert sanitise_branch(raw) == expected

    def test_git_forbidden_characters_are_neutralised(self):
        name = sanitise_branch("branch~with^control^chars")
        assert "~" not in name and "^" not in name

    @pytest.mark.parametrize("protected", sorted(PROTECTED_BRANCHES))
    def test_a_protected_branch_name_is_never_produced(self, protected):
        """main, master and friends are refused as outputs, not just as
        inputs. A caller that passes --branch main gets main-proposed."""
        name = sanitise_branch(protected)
        assert name.split("/")[-1].lower() not in PROTECTED_BRANCHES
        assert name.endswith("-proposed")

    def test_a_path_is_never_emptied(self):
        assert sanitise_branch("///") 
        assert sanitise_branch("").startswith("update")
        assert sanitise_branch("-").startswith("update")


class TestGitHelpers:
    def test_is_git_repo_on_a_plain_directory(self, tmp_path):
        assert is_git_repo(tmp_path) is False

    def test_is_git_repo_on_a_missing_directory(self, tmp_path):
        assert is_git_repo(tmp_path / "nope") is False

    def test_is_git_repo_detects_a_repository(self, tmp_path):
        subprocess.run(["git", "init", "-q", str(tmp_path)], check=True, capture_output=True)
        assert is_git_repo(tmp_path) is True


class TestRefusals:
    def test_it_refuses_a_directory_that_is_not_a_repository(self, settings: Settings, tmp_path):
        a = record()
        b = record(vacancies=100)
        bundle = build_bundle(
            settings, [("content/exams/x.md", a, b, {}, {})], stamp="s"
        )
        with pytest.raises(ProposeError, match="not inside a git repository"):
            propose(settings, bundle, repo=tmp_path / "not-a-repo")

    def test_it_refuses_when_there_is_nothing_to_propose(self, settings: Settings):
        a = record()
        bundle = build_bundle(settings, [("content/exams/x.md", a, rec_ops.copy_of(a), {}, {})], stamp="s")
        with pytest.raises(ProposeError, match="nothing to propose"):
            propose(settings, bundle, repo=settings.repo_dir)

    def test_the_refusal_message_explains_the_scheduled_job(self, settings: Settings):
        a = record()
        bundle = build_bundle(settings, [("content/exams/x.md", a, rec_ops.copy_of(a), {}, {})], stamp="s")
        with pytest.raises(ProposeError) as exc:
            propose(settings, bundle, repo=settings.repo_dir)
        assert "scheduled job" in str(exc.value)

    def test_the_default_target_is_the_site_folder(self):
        """Records go into site/ in this repo by default."""
        assert Settings().repo_dir == Path.cwd() / "site"

    def test_protected_branches_cover_the_obvious_cases(self):
        assert {"main", "master"} <= PROTECTED_BRANCHES


class TestRendering:
    def test_a_proposal_never_claims_to_have_pushed(self):
        proposal = Proposal(branch="pipeline/x", repo="/tmp/r", files=["a.md"])
        rendered = proposal.render()
        assert "Nothing was pushed" in rendered
        assert "main was not touched" in rendered
        assert "committed: no" in rendered

    def test_the_pr_command_is_printed_not_run(self):
        proposal = Proposal(
            branch="pipeline/x", repo="/tmp/r", files=["a.md"],
            pr_command="git -C /tmp/r push && gh pr create",
        )
        rendered = proposal.render()
        assert "to open the pull request yourself:" in rendered
        assert "gh pr create" in rendered

    def test_notes_are_surfaced(self):
        proposal = Proposal(branch="b", repo="r", notes=["the working tree was dirty"])
        assert "the working tree was dirty" in proposal.render()

    def test_json_round_trip(self):
        import json

        proposal = Proposal(branch="b", repo="r", files=["a.md"], commit_sha="deadbeef")
        assert json.loads(json.dumps(proposal.to_json()))["branch"] == "b"


class TestCommit:
    def test_it_commits_into_a_site_subfolder(self, settings: Settings, tmp_path, monkeypatch):
        """The site lives in site/ of the repo; paths are relative to it."""
        repo = tmp_path / "repo"
        (repo / "site" / "content" / "exams").mkdir(parents=True)
        (repo / "site" / "hugo.toml").write_text("title = 'x'\n")
        git = ["git", "-c", "user.name=t", "-c", "user.email=t@t"]
        subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
        subprocess.run([*git, "-C", str(repo), "add", "-A"], check=True)
        subprocess.run([*git, "-C", str(repo), "commit", "-qm", "base"], check=True)
        bundle = build_bundle(settings, [("content/exams/x.md", record(), record(vacancies=100),
                                          {}, {"is_new": True})], stamp="s")
        bundle.write(settings)
        for k in ("GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL"):
            monkeypatch.setenv(k, "t")
        proposal = propose(settings, bundle, repo=repo / "site", commit=True)
        assert proposal.committed
        shown = subprocess.run(["git", "-C", str(repo), "show", "--name-only", "--format=",
                                proposal.branch], capture_output=True, text=True, check=True)
        assert shown.stdout.strip() == "site/content/exams/x.md"
