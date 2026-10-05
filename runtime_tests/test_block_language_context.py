"""Metadata must follow the physical SQL session selected by each block."""

import threading
from collections import OrderedDict, deque

from datapyn_runtime.supervisor import SessionRuntime


def session_stub():
    session = SessionRuntime.__new__(SessionRuntime)
    session._lock = threading.RLock()
    session._wake = threading.Event()
    session._closed = session._failed = False
    session._pending_reset = None
    session._queue = deque()
    session.session_id = "session"
    session.language_contexts = OrderedDict()
    session.language_variables = {"frame": {"type": "DataFrame", "columns": ["title"]}}
    session.language_version = 4
    session._context_codes = {}
    session._context_requests = set()
    return session


def test_metadata_requests_are_coalesced_per_block_without_sharing_temp_tables():
    session = session_stub()
    scope = {"connection_id": "saved", "database": "warehouse", "schema": "dbo", "code": "SELECT * FROM #sample"}
    first, second = ({**scope, "block_id": block} for block in ("first", "second"))
    session.prepare_context(first)
    session.prepare_context(first)
    session.prepare_context(second)
    assert len(session._queue) == 2

    first_key, second_key = session.context_key(first), session.context_key(second)
    session.language_contexts[first_key] = {"schema": {"tables": [{"name": "#sample"}]}}
    session.language_contexts[second_key] = {"schema": {"tables": [{"name": "#other"}]}}
    assert session.editor_context(first, refresh=False)["schema"]["tables"] == [{"name": "#sample"}]
    assert session.editor_context(second, refresh=False)["schema"]["tables"] == [{"name": "#other"}]
    assert session.context_key(scope) == "saved|warehouse|dbo"


def test_context_updates_forward_block_owner_and_requested_scope():
    session = session_stub()
    messages = []
    session.emit = messages.append
    scope = {"connection_id": "saved", "database": "warehouse", "schema": "finance"}
    params = {**scope, "block_id": "first", "scope_inherited": True}
    key = session.context_key(params)
    session._context_requests.add(key)
    session._receive({"language_context": {
        "key": key, "block_id": "first", "scope_inherited": True, "connection_id": "saved", "database": "warehouse", "schema_name": "finance",
        "schema": {}, "schema_complete": False, "metadata_state": "error", "schema_error": "PermissionError: unavailable",
        "requested_scope": scope,
    }})
    assert messages[-1]["payload"]["block_id"] == "first"
    assert messages[-1]["payload"]["scope_inherited"] is True
    assert messages[-1]["payload"]["requested_scope"] == scope
    assert messages[-1]["payload"]["metadata_state"] == "error"
    assert messages[-1]["payload"]["variables"]["frame"]["columns"] == ["title"]
    assert key not in session._context_requests


def test_legacy_context_events_keep_their_existing_shape():
    session = session_stub()
    messages = []
    session.emit = messages.append
    session._receive({"language_context": {"key": "saved||", "connection_id": "saved", "variables": {}}})
    assert "block_id" not in messages[-1]["payload"]
    assert "scope_inherited" not in messages[-1]["payload"]


def test_toggling_same_block_between_pinned_and_inherited_prepares_separate_sessions():
    session = session_stub()
    pinned = {"block_id": "first", "connection_id": "saved", "database": "warehouse", "schema": "dbo", "code": "SELECT * FROM #sample"}
    inherited = {**pinned, "scope_inherited": True}
    session.prepare_context(pinned)
    session.prepare_context(inherited)
    assert len(session._queue) == 2
    assert session.context_key(pinned) == "saved|warehouse|dbo|block:first"
    assert session.context_key(inherited) == "saved|warehouse|dbo|block:first|scope:inherited"
    session.language_contexts[session.context_key(pinned)] = {"schema": {"tables": [{"name": "#pinned"}]}}
    assert "schema" not in session.editor_context(inherited, refresh=False)


def test_only_legacy_clients_can_borrow_a_connection_wide_snapshot():
    session = session_stub()
    scope = {"connection_id": "saved", "database": "warehouse", "schema": "dbo"}
    session.language_contexts[session.context_key(scope)] = {"schema": {"tables": [{"name": "#global"}]}}
    request = {**scope, "block_id": "first"}
    assert session.editor_context(request, refresh=False)["schema"]["tables"] == [{"name": "#global"}]
    for inherits in (False, True):
        assert "schema" not in session.editor_context({**request, "scope_inherited": inherits}, refresh=False)

    session.language_contexts[session.context_key(request)] = {"version": 2, "schema": {"tables": [{"name": "#old"}]}}
    session.language_contexts[session.context_key(scope)] = {"version": 3, "schema": {"tables": [{"name": "#refreshed"}]}}
    assert session.editor_context(request, refresh=False)["schema"]["tables"] == [{"name": "#refreshed"}]
    assert session.editor_context({**request, "scope_inherited": False}, refresh=False)["schema"]["tables"] == [{"name": "#old"}]


def test_switch_invalidation_preserves_pinned_peer_but_ddl_invalidates_connection():
    session = session_stub()
    messages = []
    session.emit = messages.append
    for block in ("first", "second"):
        key = session.context_key({"connection_id": "saved", "block_id": block})
        session.language_contexts[key] = {
            "connection_id": "saved", "block_id": block,
            "schema": {"tables": [{"name": block}]}, "schema_complete": True,
        }
        session._context_codes[key] = (("sample",), 1)
    update = {"key": session.context_key({"connection_id": "saved", "block_id": "first"}),
              "connection_id": "saved", "block_id": "first", "schema": {},
              "metadata_invalidated": True, "metadata_invalidation_scope": "block"}
    session._receive({"language_context": update})
    first = session.context_key({"connection_id": "saved", "block_id": "first"})
    second = session.context_key({"connection_id": "saved", "block_id": "second"})
    assert session.language_contexts[first]["schema"] == {}
    assert session.language_contexts[second]["schema"]["tables"] == [{"name": "second"}]
    assert second in session._context_codes and first not in session._context_codes
    assert messages[-1]["payload"]["metadata_invalidation_scope"] == "block"

    session._receive({"language_context": {**update, "metadata_invalidation_scope": "connection"}})
    assert session.language_contexts[second]["schema"] == {}
    assert second not in session._context_codes


def test_inherited_switch_invalidates_family_snapshots_without_clearing_pinned_peer():
    session = session_stub()
    session.emit = lambda _message: None
    for block, inherits in (("running", True), ("sibling", True), ("pinned", False)):
        params = {"connection_id": "saved", "block_id": block, "scope_inherited": inherits}
        key = session.context_key(params)
        session.language_contexts[key] = {**params, "schema": {"tables": [{"name": block}]}}
    running = {"connection_id": "saved", "block_id": "running", "scope_inherited": True}
    session._receive({"language_context": {**running, "key": session.context_key(running), "schema": {},
                                           "metadata_invalidated": True, "metadata_invalidation_scope": "block"}})
    sibling = session.context_key({"connection_id": "saved", "block_id": "sibling", "scope_inherited": True})
    pinned = session.context_key({"connection_id": "saved", "block_id": "pinned", "scope_inherited": False})
    assert session.language_contexts[sibling]["schema"] == {}
    assert session.language_contexts[pinned]["schema"]["tables"] == [{"name": "pinned"}]
