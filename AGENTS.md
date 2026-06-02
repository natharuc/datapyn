# Agent instructions (DataPyn)

Instructions for AI agents (Cursor, Copilot, Claude, etc.) working in this repository.

## Conventional Commits (mandatory)

**All commits and PR titles must use Conventional Commits in English.**

Format: `type(scope): subject`

- `feat` — new feature (minor release on merge to `main`)
- `fix` — bug fix (patch release)
- `feat!` or `BREAKING CHANGE:` — major release
- `chore`, `ci`, `docs`, `test`, `refactor`, etc. — no automatic version bump

Free-form messages (e.g. `Improve grid performance`, `Delete file.txt`) cause the **Continuous Delivery - PSR** workflow to succeed without incrementing `pyproject.toml`.

When committing or opening a PR:

1. Pick the correct `type` and optional `scope`.
2. Use imperative mood in the subject (`add`, `fix`, `remove`, not `added` / `fixes`).
3. Align squash-merge PR titles with the same format so `main` receives a releasable commit.

See `.github/git-commit-instructions.md` and `.cursor/rules/conventional-commits.mdc` for details and scopes.

## Releases

After tests pass on `main`, python-semantic-release bumps the version and builds the Windows MSI. Manual recovery: GitHub Actions → **Continuous Delivery - PSR** → `force: patch|minor|major` (with `rebuild_only: false`).

## Project

- Python 3.12+, PyQt6, `uv` for dependencies
- Run tests: `uv run pytest` (see `pytest.ini` for CI ignores)
