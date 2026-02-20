# DataPyn - Commit Instructions

Best practices guide for commits in the DataPyn project.

> **IMPORTANT**: All commit messages MUST be written in English.

---

## Conventional Commits Format

```
<type>(<scope>): <subject>
```

### Types

| Type | Description |
|------|-------------|
| `feat` | A new feature |
| `fix` | A bug fix |
| `refactor` | Code change that neither fixes a bug nor adds a feature |
| `docs` | Documentation changes only |
| `style` | Formatting, spacing (no code logic change) |
| `test` | Adding or updating tests |
| `chore` | Build, dependencies, CI/CD, configs |
| `perf` | Performance improvements |
| `ci` | CI/CD pipeline changes |
| `build` | Changes to build system or dependencies |
| `revert` | Reverts a previous commit |

### Project Scopes

DataPyn-specific scopes:

| Scope | Area |
|-------|------|
| `ui` | GUI, PyQt6 components |
| `editor` | Block editor, QScintilla, syntax highlighting |
| `database` | Connectors, SQLAlchemy, drivers (pymssql, psycopg2, etc.) |
| `executor` | SQL and Python execution, mixed syntax |
| `services` | Services layer (auto_update, file_import, etc.) |
| `workers` | Background workers, QThread |
| `panels` | Panel manager, results grid, output |
| `shortcuts` | Keyboard shortcuts |
| `settings` | Configuration, settings dialogs |
| `workspace` | Workspace management |
| `theme` | Themes, Material Design, dark/light |
| `i18n` | Internationalization, translations |
| `deps` | Dependencies (pyproject.toml, uv.lock) |
| `installer` | Installation scripts, MSI, PyInstaller |
| `tests` | Test infrastructure |

---

## Best Practices

### Use imperative mood

Write the subject line as a command – as if you're telling the codebase what to do.

- **Correct**: `fix(database): resolve timeout in SQL Server connections`
- **Wrong**: `fix(database): resolved timeout in SQL Server connections`
- **Wrong**: `fix(database): resolving timeout in SQL Server connections`

### Keep the subject line short

- Limit to **50 characters** (hard limit: 72).
- Do not end with a period.

### Be specific and direct

- **Correct**: `feat(executor): add retry logic for deadlock queries`
- **Wrong**: `feat: update executor stuff`
- **Wrong**: `fix: fix bug`

### Mention important changes

If the commit introduces a breaking change, new dependency, or any side effect, **state it clearly** in the body or footer.

```
feat(database): add LocalDB support

Adds automatic Windows Authentication for SQL Server
LocalDB instances.

Requires: SQL Server LocalDB installed on Windows
```

### One commit, one purpose

Each commit should represent a single logical change. Do not bundle unrelated changes together.

- **Correct**: One commit for the bug fix, another for the refactor.
- **Wrong**: One commit that fixes a bug, renames variables, and updates a config file.

### Use the body for context

If the subject line is not enough, add a body separated by a blank line. Explain **what** and **why**, not **how**.

```
fix(workers): prevent QThread crash in jedi completer

The autocomplete was being called after QThread was destroyed,
causing crash when opening Python blocks rapidly.
```

### Breaking Changes

Use the `BREAKING CHANGE:` footer or append `!` after the type/scope:

```
feat(executor)!: change mixed blocks syntax to {{ }}
```

---

## DataPyn-Specific Rules

### 1. Never use emojis

Commits, comments, and documentation must be emoji-free.

- **Wrong**: `feat: add dark mode`
- **Correct**: `feat(theme): add dark mode`

### 2. Always run tests

Before committing, run:

```bash
uv run pytest
```

If your commit breaks tests, fix them before pushing.

### 3. PyQt6 and QThread

Thread-related commits should be well-documented:

```
fix(workers): fix race condition in background worker

- Add lock for shared state access
- Check isRunning() before calling quit()
- Use deleteLater() for safe cleanup
```

### 4. Dependencies

When adding/updating dependencies, specify the version:

```
chore(deps): update PyQt6 to 6.7.0

New features used:
- Improved QWebEngineView
- Memory leak fix in QScintilla
```

### 5. Data migration

If the commit affects saved workspaces or configurations:

```
feat(workspace): add session_id field to workspace

BREAKING CHANGE: workspaces saved in previous versions
need to be re-saved to include the new field.
```

---

## Examples for DataPyn

```
feat(editor): add syntax highlighting for mixed blocks
feat(database): add MariaDB socket connection support
feat(panels): display execution time in results grid
feat(shortcuts): allow Ctrl+Enter customization

fix(executor): resolve memory leak in long-running queries
fix(ui): fix splitter resize in dock panel
fix(workers): prevent crash when canceling running query
fix(theme): adjust dark mode contrast in QScintilla

refactor(services): extract import logic to FileImportService
refactor(database): unify connector interfaces

perf(executor): use polars for large DataFrames (>100k rows)
perf(panels): implement lazy loading in results grid

test(executor): add tests for mixed syntax edge cases
test(database): cover timeout and retry scenarios

docs(readme): update installation instructions with uv
docs: add contribution guide

chore(deps): update pandas to 2.2.0
chore(installer): optimize MSI size
ci(actions): add uv cache in build pipeline
```

---

## Semantic Release

This project uses semantic-release for automatic versioning. Commits determine the release type:

| Commit Type | Release |
|-------------|---------|
| `fix` | Patch (1.0.X) |
| `feat` | Minor (1.X.0) |
| `feat!` or `BREAKING CHANGE` | Major (X.0.0) |

Commits that don't trigger a release: `docs`, `style`, `test`, `chore`, `ci`, `refactor`

---

## Pre-Commit Checklist

- [ ] Code compiles without errors
- [ ] All tests pass (`uv run pytest`)
- [ ] Commit follows the conventional commits format
- [ ] Scope is correct for the changed area
- [ ] No emojis in commit or code
- [ ] Breaking changes are documented
- [ ] New dependencies are in pyproject.toml
