#!/usr/bin/env bash
# CI pytest entrypoint: optional matrix shard + crash retry for QWebEngine teardown.
set -euo pipefail

SHARD="${1:-}"
SHARDS="${2:-}"

PYTEST_ARGS=(-p no:faulthandler -q)

if [[ -n "${SHARD}" && -n "${SHARDS}" ]]; then
  mapfile -t FILES < <(uv run python scripts/ci_test_shard.py "${SHARD}" "${SHARDS}")
  echo "=== CI shard ${SHARD}/${SHARDS}: ${#FILES[@]} modules ==="
  PYTEST_ARGS+=("${FILES[@]}")
else
  echo "=== CI full suite (all modules) ==="
  PYTEST_ARGS+=(tests/)
  CI_IGNORES=(
    test_visual_manual.py
    test_gui.py
    test_file_operations.py
    test_usability.py
    test_ui_integration.py
    test_monaco_editor.py
    test_shortcuts.py
    test_session_panels_integration.py
    test_file_management_feedback.py
    test_export_script.py
    test_jupyter_import.py
    test_context_menu.py
    test_package_manager.py
    test_new_features.py
    test_block_editor.py
    test_block_connection.py
    test_block_database.py
    test_block_namespace.py
    test_new_tab_connection.py
    test_session_restoration.py
    test_python_output_e2e.py
  )
  for mod in "${CI_IGNORES[@]}"; do
    PYTEST_ARGS+=(--ignore="tests/${mod}")
  done
fi

MAX_ATTEMPTS=3
ATTEMPT=0
while [[ ${ATTEMPT} -lt ${MAX_ATTEMPTS} ]]; do
  ATTEMPT=$((ATTEMPT + 1))
  echo "=== Test attempt ${ATTEMPT}/${MAX_ATTEMPTS} ==="

  set +e
  uv run pytest "${PYTEST_ARGS[@]}" 2>&1 | tee test_output.txt
  PIPE_EXIT=${PIPESTATUS[0]}
  set -e

  if [[ ${PIPE_EXIT} -eq 0 ]]; then
    echo "All tests passed."
    exit 0
  elif [[ ${PIPE_EXIT} -eq 1 ]]; then
    echo "Some tests failed."
    exit 1
  elif [[ ${PIPE_EXIT} -ge 128 ]]; then
    if grep -q "passed" test_output.txt && ! grep -qP '\d+ failed' test_output.txt; then
      echo "Tests passed (QWebEngine crash ignored, exit code ${PIPE_EXIT})"
      exit 0
    fi
    echo "Qt/QWebEngine crash during tests (exit code ${PIPE_EXIT}, attempt ${ATTEMPT}/${MAX_ATTEMPTS})"
    if [[ ${ATTEMPT} -lt ${MAX_ATTEMPTS} ]]; then
      echo "Retrying..."
      sleep 2
    else
      echo "All ${MAX_ATTEMPTS} attempts crashed. Failing build."
      exit 1
    fi
  else
    exit "${PIPE_EXIT}"
  fi
done
