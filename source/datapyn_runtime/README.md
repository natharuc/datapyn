# DataPyn runtime protocol v1

Start with `PYTHONPATH=source python -m datapyn_runtime`. A Tauri sidecar may
freeze the same entry point. Stdin and stdout carry UTF-8 JSON, one message per
line. Application diagnostics belong on stderr. The runtime has no Qt imports.

Requests use `{ "id": 1, "method": "system.info", "params": {} }`.
Responses use `{ "id": 1, "result": ... }` or
`{ "id": 1, "error": { "code": "...", "message": "..." } }`.
Events use `{ "event": "...", "payload": { ... } }`.
Request IDs are integer correlation IDs; session and execution IDs are strings.

| Method | Parameters | Result |
| --- | --- | --- |
| `system.info` | none | `protocol_version`, `python_version`, capabilities object |
| `system.shutdown` | none | `{status:"closing"}`; then closes kernels and exits |
| `session.create` | optional `session_id` | `session_id`, `status:"created"` |
| `session.close` | `session_id` | `session_id`, `status:"closed"` |
| `connection.connect` | `session_id`, `config` | `status:"connected"`, `db_type` |
| `schema.get` | `session_id` | `db_type`, `database`, `schemas`, `tables` |
| `execution.run` | `session_id`, `execution_id`, `language`, `code`, optional `variable_name`, `parameters` | `execution_id`, `status:"queued"` |
| `execution.cancel` | `session_id`, `execution_id` | `execution_id`, `status` |
| `result.page` | `session_id`, `result_id`, `offset`, `limit`, optional `sort`, `filter` | `columns`, `rows`, `total_rows`, `offset` |
| `workspace.read` | `path` | canonical `path`, `document` |
| `workspace.write` | `path`, `document` | canonical `path`, `bytes_written` |

Connection configuration accepts the legacy DatabaseConnector fields:
`db_type`, `host`, `port`, `database`, `username`, `password`, and authentication
options. SQLite (`database:":memory:"` by default) supports local smoke tests.
Production drivers are reused; live authentication and databases require
separate validation. Credentials stay in their session kernel after connection.

Each session has a spawned interpreter and a serial operation queue. The initial
namespace contains `pd`, `np`, and `pl`. Connecting injects the SQLAlchemy
`db_engine` and database context. SQL results are assigned to `df`, or a provided
variable name; multiple results use `df`, `df1`, `df2`. Python retains variables
and evaluates its last expression. pandas/Polars frames and series become opaque
result handles. Matplotlib figures use Agg and emit PNG rich outputs.

`session.ready` signals kernel availability. Execution events are
`execution.started`, `execution.output`, and `execution.finished`. Output carries
session ID, execution ID, stream (`stdout` or `stderr`), and text. Finished carries
IDs, status (`succeeded`, `failed`, `cancelled`), `duration_ms`, `results`,
`variables`, optional error string, and optional `rich_outputs`. Result descriptors
contain `result_id`, `variable_name`, `columns` (`name`, `dtype`), and `row_count`.
Rich images contain `{type:"image",mime:"image/png",data:"<base64>"}`.

Active cancellation terminates and recreates only the affected kernel. Its
namespace, results, and database connection are lost. Operations already queued
for that session are cancelled. `session.reset` carries `reason`,
`namespace_lost:true`, and `connection_lost:true`; reconnect explicitly. Cancelling
an execution that has not started removes that execution without a kernel reset.
Unexpected worker exit follows the same reset path with `reason:"worker_crashed"`.

Pages return arrays of primitive cells in column order. Null/NaN/infinity become
null, integers outside JavaScript's safe range and decimals become strings, and
dates become ISO strings. Sorting uses `{column,direction:"asc"|"desc"}`. Filtering
resolves the descriptor's string name to the original Python column label;
ambiguous duplicate names return an explicit error. Filtering accepts `{text}`
for case-insensitive literal matching across columns, or
`{column,operator:"contains"|"equals"|"gt"|"lt",value}`. Filtering and sorting happen
inside the kernel; they can scan the full resident frame. SQL results currently
materialize in memory before paging. Paging reduces transport/rendering load, not
the memory needed to execute a query.

Limits: 16 sessions, 64 queued operations per session, 1 MiB code, 2 MiB requests,
1,000 rows per page, 64 result handles per kernel, and 256 KiB captured output per
execution. Native descriptor and subprocess output is discarded so it cannot
corrupt the protocol. Python `print` and `sys.stderr.write` are streamed. Interactive
`input()` receives EOF. Kernels and their child processes exit on cancellation,
stdin EOF, or supervisor death. Each kernel belongs to its own Windows Job Object
(inside the Tauri job) or POSIX process group. Failure to establish Windows
ownership fails the session explicitly.

Workspace I/O preserves unknown JSON fields and writes atomically; it does not
restore Python memory, connections, or serialized DataFrames. This runtime is a
desktop execution boundary for trusted local code, not a sandbox for untrusted
code.

Independent tests: `python -m pytest -c runtime_tests/pytest.ini runtime_tests -q`.
They launch the actual NDJSON process with pipes and do not load the legacy Qt
`tests/conftest.py`.
