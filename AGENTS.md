# Agent instructions (DataPyn)

Instructions for AI agents (Cursor, Copilot, Claude, etc.) working in this repository.

## Conventional Commits (mandatory)

**All commits and PR titles must use Conventional Commits in English** when possible.

Format: `type(scope): subject`

| Type | Semver on merge to `main` |
|------|---------------------------|
| `feat` | Minor |
| `fix`, `perf`, `refactor`, `revert`, `build` | Patch |
| `chore`, `ci`, `docs`, `style`, `test` | No automatic bump |

CI uses `scripts/datapyn_commit_parser.py` (extends python-semantic-release) plus a **fallback patch** if no release is detected. Imperative subjects without a prefix (e.g. `Add …`, `Improve …`) are mapped heuristically, but **`feat:` / `fix:` are still required** for predictable changelog and semver.

See `.github/git-commit-instructions.md` and `.cursor/rules/conventional-commits.mdc`.

## Releases

After tests pass on `main`, python-semantic-release bumps the version and builds the Windows MSI. Manual recovery: GitHub Actions → **Continuous Delivery - PSR** → `force: patch|minor|major` (with `rebuild_only: false`).

## Project

- Python 3.12+, PyQt6, `uv` for dependencies
- Run tests: `uv run pytest` (see `pytest.ini` for CI ignores)
