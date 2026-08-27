"""Restore GitPython Actor regex APIs removed in 3.1.60.

python-semantic-release 10.5/10.6 still validates ``commit_author`` with
``Actor.name_email_regex``. GitPython 3.1.60 dropped that class attribute, so
every ``semantic-release`` command fails while loading config. Keep the same
pattern GitPython used so PSR can construct ``Actor(name, email)``.
"""

from __future__ import annotations

import re

from git import Actor

# Same pattern GitPython used through 3.1.59.
_NAME_EMAIL_REGEX = re.compile(r"(.*) <(.*?)>")
_NAME_ONLY_REGEX = re.compile(r"<(.*)>")


def patch_gitpython_actor() -> None:
    """No-op on GitPython < 3.1.60; restores class regexes on 3.1.60+."""
    if not hasattr(Actor, "name_email_regex"):
        Actor.name_email_regex = _NAME_EMAIL_REGEX
    if not hasattr(Actor, "name_only_regex"):
        Actor.name_only_regex = _NAME_ONLY_REGEX
