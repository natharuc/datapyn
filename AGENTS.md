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

## Cursor Cloud specific instructions

DataPyn is a **single-process PyQt6 desktop IDE** (no separate API server or Docker stack). The update script only runs `uv sync --dev`; Linux **system packages** are not installed automatically on each VM start.

### Linux system dependencies

On Ubuntu/Debian, match CI (`.github/workflows/tests.yml`) or run `./scripts/linux/install.sh` once per VM: Qt/XCB/OpenGL libs, `libmariadb-dev`, `freeglut3-dev`, `xvfb` (optional, for headless GUI tests). Without these, `uv sync` may succeed but PyQt/WebEngine tests or the app can fail at runtime.

### Running the app

- Dev: `uv run python source/main.py` (needs `DISPLAY`; Cloud VMs usually have `:1`).
- WebEngine: set `QTWEBENGINE_DISABLE_SANDBOX=1` and `QTWEBENGINE_CHROMIUM_FLAGS=--no-sandbox` if Chromium sandbox errors appear.
- Optional: `./scripts/linux/run.sh` after install.

### Tests and lint

- Lint: `uv run ruff check source/` (tests are excluded in `pyproject.toml`).
- **CI-like pytest** (headless, ignores QWebEngine-heavy modules): use the same `--ignore=…` list as `.github/workflows/tests.yml`, plus env `QT_QPA_PLATFORM=offscreen`, `QTWEBENGINE_DISABLE_SANDBOX=1`, `QTWEBENGINE_CHROMIUM_FLAGS=--no-sandbox`.
- **Full GUI tests** (`tests/test_gui.py`, etc.): need a real display (`DISPLAY=:1`) and the WebEngine env vars above; do not force `QT_QPA_PLATFORM=offscreen` for those.
- `pytest.ini` sets `QT_QPA_PLATFORM=offscreen` by default; override in the shell when running GUI tests with a display.

### External services (optional)

Live databases, GitHub Copilot (`gh` auth), and GitHub Releases (auto-update) are **not** required for the default test suite. No in-repo database container is provided.
