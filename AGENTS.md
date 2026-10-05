# Agent instructions (DataPyn)

Instructions for AI agents (Cursor, Copilot, Claude, etc.) working in this repository.

## Conventional Commits (mandatory)

**All commits and PR titles must use Conventional Commits in English** when possible.

Format: `type(scope): subject`

Use `feat` for features, `fix` for corrections, and the appropriate `perf`, `refactor`, `revert`, `build`, `chore`, `ci`, `docs`, `style`, or `test` type for other changes. Conventional Commits describe the change; they do not automatically bump the Tauri version.

See `.github/git-commit-instructions.md` and `.cursor/rules/conventional-commits.mdc`.

## Releases

`main` is the authoritative Tauri application. A push to `main` publishes its current version after native validation on all three platforms when `tauri-vX.Y.Z` does not exist. An existing version tag skips build/publication. The migration branch remains a dry run; Tauri tag pushes and manual dispatch are also supported.

For a new release, update the app version in `desktop/package.json`, `desktop/package-lock.json`, `desktop/src-tauri/Cargo.toml`, `desktop/src-tauri/Cargo.lock`, and `desktop/src-tauri/tauri.conf.json`, then run `node scripts/tauri/release.mjs verify-version tauri-vX.Y.Z`. Keep dependency versions, the updater key/feed, and `app.datapyn.tauri` unchanged unless the task explicitly requires them. See `docs/TAURI_RELEASE.md`.

The PyQt version in `pyproject.toml` and its `vX.Y.Z` releases are independent historical artifacts. PSR has no automatic release from `main`; legacy maintenance requires an explicit historical tag or a PyQt-only branch. Historical tags can be rebuilt manually. Do not assume that PSR bumps a maintenance branch without checking its branch configuration.

## Pull requests (one at a time)

Never leave more than **one open PR** for the same author on this repo.

Before starting new work or opening a PR:

1. Run `gh pr list --author "@me" --state open` and confirm **zero** open PRs (or exactly one that you are continuing).
2. **Continue the existing PR** — push to the same branch and update the PR title/body if scope grew.
3. If scope changed entirely, **close the old PR** (with a short comment) before opening a new one.
4. Do **not** create a new branch/PR while another PR from the same workstream is still open.
5. When consolidating work from stale PRs, cherry-pick or merge into the active branch first, then close the superseded PRs without merging on GitHub.

Agents must not run `gh pr create` if an open PR already exists unless the user explicitly asked to replace it.

## Project

- Tauri 2 / Rust host, React / TypeScript frontend, and isolated Python session kernels.
- Prerequisites: Node.js 22, Rust 1.90+, Python 3.12+, and `uv`.
- Setup: `uv sync --dev --frozen` and `npm --prefix desktop ci`.
- Dev: `npm --prefix desktop run desktop:dev`.
- Frontend: `npm --prefix desktop test` and `npm --prefix desktop run build`.
- Runtime: `uv run pytest -c runtime_tests/pytest.ini runtime_tests -q`.
- Rust: from `desktop/src-tauri`, run `cargo fmt --check`, `cargo check --locked`, and `cargo test --locked`.
- Native build: `npm --prefix desktop run desktop:build -- --no-bundle`; signed distribution is documented in `docs/TAURI_DISTRIBUTION.md`.

## Cursor Cloud specific instructions

DataPyn is a Tauri desktop IDE with Python sidecars and per-session kernels. No separate API server or Docker stack is required. Linux system packages are not installed by `uv` or `npm`.

### Linux system dependencies

Match `.github/workflows/tauri.yml`: `libwebkit2gtk-4.1-dev`, `build-essential`, `libxdo-dev`, `libssl-dev`, `libayatana-appindicator3-dev`, `librsvg2-dev`, `patchelf`, `unixodbc-dev`, and `libmariadb-dev`. Driver requirements are in `docs/TAURI_RUNTIME_DISTRIBUTION.md`.

### Historical PyQt maintenance

The retained PyQt source and scripts support maintenance on historical references. Its entry point is `uv run python source/main.py`, and Linux dependencies follow `.github/workflows/tests.yml` or `scripts/linux/install.sh`.

### Historical tests and lint

- Lint: `uv run ruff check source/` (tests are excluded in `pyproject.toml`).
- **CI-like pytest** (headless, ignores QWebEngine-heavy modules): use the same `--ignore=…` list as `.github/workflows/tests.yml`, plus env `QT_QPA_PLATFORM=offscreen`, `QTWEBENGINE_DISABLE_SANDBOX=1`, `QTWEBENGINE_CHROMIUM_FLAGS=--no-sandbox`.
- **Full GUI tests** (`tests/test_gui.py`, etc.): need a real display (`DISPLAY=:1`) and the WebEngine env vars above; do not force `QT_QPA_PLATFORM=offscreen` for those.
- `pytest.ini` sets `QT_QPA_PLATFORM=offscreen` by default; override in the shell when running GUI tests with a display.

### External services (optional)

Live databases, GitHub Copilot (`gh` auth), and GitHub Releases (auto-update) are **not** required for the default test suite. No in-repo database container is provided.
