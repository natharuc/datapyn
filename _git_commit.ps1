Set-Location c:\nac\datapyn
git reset HEAD -- test_result.txt test_result_latest.txt test_result_layout.txt test_result_uv.txt test_result_uv2.txt test_results_final.txt test_results_latest.txt test_results.txt test_results_current.txt test_output.txt test_run_output.txt workflow_log.txt git_status.txt 2>$null
git add source/ pyproject.toml uv.lock
$stat = git diff --cached --stat
$stat | Out-File c:\nac\datapyn\git_status.txt -Encoding utf8
git commit -m "feat: jedi autocomplete, package sources, database switch propagation`n`n- Jedi-based Python autocomplete (classes, methods, modules, imports)`n- Package manager: configurable extra index URLs (sources)`n- Database switch: propaga para connection panel, status bar, tab color, todos os blocos`n- i18n: strings adicionadas em en-US e pt-BR`n`nSuite: 1052 passed, 2 skipped" 2>&1 | Out-File c:\nac\datapyn\git_commit_result.txt -Encoding utf8
Write-Output "DONE"
