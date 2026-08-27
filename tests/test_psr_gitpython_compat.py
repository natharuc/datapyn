"""GitPython 3.1.60 compatibility for python-semantic-release."""

from git import Actor

from scripts.psr_gitpython_compat import patch_gitpython_actor


def test_patch_restores_name_email_regex_when_missing():
    original = getattr(Actor, "name_email_regex", None)
    try:
        if hasattr(Actor, "name_email_regex"):
            delattr(Actor, "name_email_regex")
        assert not hasattr(Actor, "name_email_regex")

        patch_gitpython_actor()

        matched = Actor.name_email_regex.match(
            "github-actions <actions@users.noreply.github.com>"
        )
        assert matched is not None
        commit_author = Actor(*matched.groups())
        assert commit_author.name == "github-actions"
        assert commit_author.email == "actions@users.noreply.github.com"
    finally:
        if original is not None:
            Actor.name_email_regex = original
        elif hasattr(Actor, "name_email_regex"):
            delattr(Actor, "name_email_regex")


def test_patch_is_idempotent_when_regex_already_exists():
    patch_gitpython_actor()
    first = Actor.name_email_regex
    patch_gitpython_actor()
    assert Actor.name_email_regex is first
