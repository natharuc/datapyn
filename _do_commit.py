import subprocess, os

os.chdir(r"c:\nac\datapyn")

# Unstage test artifacts
subprocess.run(["git", "reset", "HEAD", "--", 
    "test_result.txt", "test_result_latest.txt", "test_result_layout.txt",
    "test_result_uv.txt", "test_result_uv2.txt", "test_results_final.txt",
    "test_results_latest.txt", "test_results.txt", "test_results_current.txt",
    "test_output.txt", "test_run_output.txt", "workflow_log.txt",
    "git_status.txt", "_git_commit.ps1", "_log.txt",
    "git_commit_result.txt"
], stderr=subprocess.DEVNULL)

# Stage source files
subprocess.run(["git", "add", "source/", "pyproject.toml", "uv.lock"])

# Diff stat
r = subprocess.run(["git", "diff", "--cached", "--stat"], capture_output=True, text=True)
print("=== STAGED FILES ===")
print(r.stdout)

# Check current log
r = subprocess.run(["git", "log", "--oneline", "-3"], capture_output=True, text=True)
print("=== CURRENT LOG ===")
print(r.stdout)

# Commit
msg = """feat: jedi autocomplete, package sources, database switch propagation

- Jedi-based Python autocomplete (classes, methods, modules, imports)
- Package manager: configurable extra index URLs (sources)
- Database switch: propaga para connection panel, status bar, tab color, todos os blocos
- i18n: strings adicionadas em en-US e pt-BR

Suite: 1060 passed, 2 skipped"""

r = subprocess.run(["git", "commit", "-m", msg], capture_output=True, text=True)
print("=== COMMIT RESULT ===")
print(r.stdout)
print(r.stderr)

# Log after
r = subprocess.run(["git", "log", "--oneline", "-3"], capture_output=True, text=True)
print("=== LOG AFTER ===")
print(r.stdout)
