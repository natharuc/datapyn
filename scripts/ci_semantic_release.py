"""Run python-semantic-release after applying GitPython 3.1.60 compatibility.

The official GitHub Action rebuilds its image and pip-installs latest GitPython
on every run, which currently crashes config load. CI should invoke this wrapper
with the project lockfile instead:

    uv run python scripts/ci_semantic_release.py -v version
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.psr_gitpython_compat import patch_gitpython_actor

patch_gitpython_actor()

from semantic_release.__main__ import main

if __name__ == "__main__":
    main()
