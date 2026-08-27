import pytest

from PyQt6.QtCore import QCoreApplication


@pytest.fixture
def qapp():
    app = QCoreApplication.instance()
    if app is None:
        app = QCoreApplication([])
    return app


def test_jedi_completer_singleton():
    from src.services.jedi_completer import JediCompleter

    first = JediCompleter.instance()
    second = JediCompleter.instance()
    assert first is second


def test_monaco_completion_service_emits_sql_results(qapp, qtbot):
    from src.editors.monaco.monaco_completion_service import MonacoCompletionService

    service = MonacoCompletionService()
    service.set_sql_schema({
        "tables": [{"name": "users", "schema": "dbo", "type": "TABLE"}],
        "columns": {"users": [{"name": "id", "type": "int"}]},
    })

    with qtbot.waitSignal(service.sql_completions_ready, timeout=5000) as blocker:
        service.request_sql_completions(7, "SELECT * FROM ", 1, 16)

    request_id, payload = blocker.args
    assert request_id == 7
    assert isinstance(payload, list)


def test_monaco_completion_service_cancels_previous_worker(qapp, qtbot):
    from src.editors.monaco.monaco_completion_service import MonacoCompletionService

    service = MonacoCompletionService()
    service.set_sql_schema({"tables": [], "columns": {}})

    received = []

    def capture(request_id, payload):
        received.append(request_id)

    service.sql_completions_ready.connect(capture)
    service.request_sql_completions(1, "SELECT ", 1, 8)
    service.request_sql_completions(2, "SELECT id", 1, 10)

    qtbot.waitUntil(lambda: 2 in received, timeout=5000)
    assert received[-1] == 2

    # Rapid follow-up after worker finished should not crash on deleted C++ object.
    service.request_sql_completions(3, "SELECT name", 1, 12)
    qtbot.waitUntil(lambda: 3 in received, timeout=5000)


def test_sql_autocomplete_service_is_reused(qapp):
    from src.editors.monaco.monaco_completion_service import MonacoCompletionService

    service = MonacoCompletionService()
    first = service._sql_autocomplete_service()
    second = service._sql_autocomplete_service()
    assert first is second


def test_sql_typing_path_does_not_wait_for_python_worker():
    from pathlib import Path

    html = Path("source/src/editors/monaco/monaco_template.html").read_text(encoding="utf-8")
    assert "const wantsRemote = invokeSuggest;" in html
    assert "sqlContextWantsRemote(textBeforeCursor)" not in html
    assert "function collectScopedColumnItems(" in html
    assert "function lookupColumnsForTable(" in html
    assert "alias.column — only that table" in html
    assert "Object.keys(sqlSchemaIndex.columnsByKey || {}).forEach(pushCols)" not in html
    assert "mergeCompletionItems(dotItems, contextual)" not in html


def test_completion_worker_does_not_start_until_requested(qapp):
    from src.editors.monaco.monaco_completion_service import MonacoCompletionService

    service = MonacoCompletionService()
    assert service._worker is None
    assert service._pending is None
