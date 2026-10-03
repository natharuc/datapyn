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
| `system.activity` | none | aggregate busy state and kernel/package/Pynia/background counts |
| `system.flush_workspace` | none | asynchronous opt-in snapshot flush of existing idle kernels, bounded to 15 seconds |
| `system.shutdown` | none | `{status:"closing"}`; then closes kernels and exits |
| `session.create` | optional `session_id` | created or idempotent existing status, readiness and queue metadata |
| `session.close` | `session_id` | `session_id`, `status:"closed"` |
| `connection.connect` | session ID, saved connection ID or transient config | connected status, safe config, database/schema context |
| `connection.disconnect` | session ID, optional connection ID | disconnected status |
| `connection.test` / `connection.test_cancel` | config or saved ID; optional test ID | isolated connection test / cancellation status |
| `connection.idle_timeout` | seconds, 0 disables, default 300 | applied globally and to existing sessions |
| `connections.*` / `groups.*` | CRUD, clone, move, reorder; chosen import/export path | persistent catalog with nested groups, colors and favorites |
| `configurations.inspect/import/export` | chosen folder; import requires inspection `preview_token`; export accepts frontend `preferences`/`shortcuts`/`defaults` | public PyQt connection JSON, native shortcuts/INI, preserved extensions; converted preferences, CSV/clipboard/Pynia defaults, package sources and transfer warnings |
| `configurations.defaults.get` | none | current profile defaults for documents and new conversations |
| `explorer.list` | session/context; optional parent node, refresh | lazy nodes and actual connection context |
| `explorer.details/query/use_database` | session/context and object name/schema/kind | entity details, dialect-aware query, applied namespace |
| `language.complete/diagnostics/format` | code, language, one-based line/column, optional session/context/block ID | completion items, markers, formatted code |
| `parameters.scan` | block code, workspace codes, prior local/shared definitions, delimiter template | merged parameter definitions |
| `schema.get` | `session_id` | `db_type`, `database`, `schemas`, `tables` |
| `execution.run` | IDs, language/code; variable name, per-block connection/database/schema, local/shared parameters/delimiter, SQL export | queued status |
| `execution.cancel` | `session_id`, `execution_id` | `execution_id`, `status` |
| `result.page` | `session_id`, `result_id`, `offset`, `limit`, optional `sort`, `filter` | `columns`, `rows`, `total_rows`, `offset` |
| `result.release` | `session_id`, `result_id` | releases a table handle and its cached views; preserves namespace variables |
| `data.import` / `variable.inspect/delete` | session ID and chosen file or variable name | imported results, bounded inspection, updated namespace |
| `result.export/export_table` | result/variable, scope/filter/sort, destination | file or database export summary |
| `result.summary/chart/chart_export` | result/variable, scope/filter/sort, chart config, destination | statistics, bounded Plotly figure, saved chart |
| `result.artifact_write` | session ID, artifact ID, chosen path/format | atomic rich output export without retransmitting data |
| `document.read/script_export` | session ID, chosen path, document/options | Python/SQL/notebook document or script |
| `notifications.settings.get/set` / `notifications.evaluate/send/test` | settings or session context/custom rules | settings, rendered notification, delivery statuses |
| `snapshot.settings.get/set` / `snapshot.list/save/restore/delete` | settings or session/snapshot ID | opt-in Parquet cache metadata and restored results |
| `workspace.profiles.*` | list/create/rename/clone/delete/restore/select/state/save/patch | isolated profile; incremental transactional private session store |
| `packages.list/search/install/uninstall/sources` | query/packages/source options | isolated extension environment and streamed events |
| `pynia.catalog/state/select_agent/prompt/cancel/clear/config/answer_permission` | session, agent/prompt/config/permission | real ACP session/chat state and events |
| `pynia.attach/authenticate/install/inline/tool_reply` | chosen files, advertised auth method, agent, prompt/tool result | attachments, auth/install status, AI completion, correlated tool reply |
| `workspace.read` | `path` | canonical `path`, `document` |
| `workspace.write` | `path`, `document` | canonical `path`, `bytes_written` |

Connection configuration accepts the legacy DatabaseConnector fields:
`db_type`, `host`, `port`, `database`, `username`, `password`, and authentication
options. SQLite (`database:":memory:"` by default) supports local smoke tests.
Production drivers are reused; live authentication and databases require
separate validation. Saved credentials use OS keyring entries namespaced to the
preview workspace; catalog JSON and public DTOs contain no passwords/tokens.
Existing PyQt data is imported only from an explicitly chosen file. Each session
caches up to eight engines keyed by saved connection and namespace. Idle engines
close between operations and reconnect for the next routed operation; in-memory
SQLite remains open to preserve its data.

Each session has a spawned interpreter and a serial operation queue. The initial
namespace contains `pd`, `np`, and `pl`. Connecting injects the SQLAlchemy
`db_engine` and database context. SQL results are assigned to `df`, or a provided
variable name; multiple results use `df`, `df1`, `df2`. Python retains variables
and evaluates its last expression. pandas/Polars frames and series become opaque
result handles. Matplotlib/Pillow PNG, `_repr_html_` and `_repr_json_`, dict/list
trees, and Plotly figures produce rich outputs. A local `display()` helper accepts
multiple rich values. Matplotlib uses Agg; Plotly returns figure JSON for the local
renderer. HTML must be rendered in a sandboxed iframe.

`session.ready` signals kernel availability. Execution events are
`execution.started`, `execution.output`, and `execution.finished`. Output carries
session ID, execution ID, stream (`stdout` or `stderr`), and text. Finished carries
IDs, status (`succeeded`, `failed`, `cancelled`), `duration_ms`, `results`,
`variables`, optional error string, and optional `rich_outputs`. Result descriptors
contain `result_id`, `variable_name`, `columns` (`name`, `dtype`), and `row_count`.
Rich outputs carry an artifact ID and type (image/html/json/plotly); images contain
PNG MIME/base64, others HTML text or bounded JSON. Up to 64 artifacts are retained
under a combined 32 MiB budget.

SQL `export:{path,format:"csv"|"parquet",options}` streams driver chunks directly
to staged files without creating a DataFrame. `execution.export_progress` carries
file index/path/rows/size/total rows at up to ten updates per second per file.
Finished includes `export:{files,total_rows,cancelled,errors}`; each file has
path/rows/columns/size. Cancellation kills that kernel and cleans its stages.

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
inside the kernel; they can scan the full resident frame. Four recently transformed
views are cached under a 256 MiB structural-memory budget and shared by paging,
statistics, charts and exports. Executions invalidate views to account for Python
mutation. Normal SQL results materialize before paging; direct SQL downloads use
bounded driver chunks.

Limits: 16 sessions, 64 queued operations per session, 1 MiB code, 24 MiB requests,
1,000 rows per page, 64 result handles per kernel, and 256 KiB captured output per
execution. Native descriptor and subprocess output is discarded so it cannot
corrupt the protocol. Python `print` and `sys.stderr.write` are streamed. Interactive
`input()` receives EOF. Kernels and their child processes exit on cancellation,
stdin EOF, or supervisor death. Each kernel belongs to its own Windows Job Object
(inside the Tauri job) or POSIX process group. Failure to establish Windows
ownership fails the session explicitly.

Workspace I/O preserves unknown JSON fields and writes atomically. Profiles
isolate catalogs, preferences, notifications, ACP history, variable snapshots and
frontend documents. Switching refuses active operations and closes old kernels.
Variable recovery is separately opt-in and uses Parquet. Successful executions,
imports and deletions coalesce into a serial idle save; closing an idle session
flushes its current namespace before disposing its process. Saving failures emit
nonfatal `snapshot.warning` events. `system.flush_workspace` lets the desktop
await durability before native shutdown or update installation. Packages use a shared
extension environment and configured indexes.

Editor requests run independently from executions using immutable namespace and
lazy schema snapshots. Jedi parser access is serialized; obsolete block requests
are coalesced. Metadata loads wait in the connection's serial queue. Connection
tests, notification deliveries, packages, kernels and ACP agents have independent
process ownership and shutdown cleanup. Notification transport uses privately
captured settings/secrets and does not block SQL or Jedi.

Kernel responses use a blocking reader and bounded event queue to wake the
session supervisor immediately. Idle supervisors sleep; page requests do not
wait for a polling interval. Wire scalars are actual Python builtins, preventing
NumPy primitive subclasses from importing scientific libraries in the broker
during unpickling.

Frozen Python completion uses a persistent owned interpreter. It initializes
scientific libraries on its main thread, supplies Jedi's embedded interpreter
environment explicitly, and reuses inference caches across requests. Startup
readiness and each completion share a 12-second deadline; timeout disposes the
worker, obsolete queued requests skip work, and profile changes or shutdown
dispose its process group. Source runs retain the threaded Jedi service.

Pynia reuses the four existing ACP agents and protocol/config/permission rules.
Each tab has its own agent session, conversation and optional separate inline
completion session. Its authenticated loopback MCP proxy exposes nine consolidated
`datapyn_*` tools. Database/query/variable tools use real kernels; UI edits use
correlated frontend tool requests.

This runtime is a
desktop execution boundary for trusted local code, not a sandbox for untrusted
code.

Independent tests: `python -m pytest -c runtime_tests/pytest.ini runtime_tests -q`.
They launch the actual NDJSON process with pipes and do not load the legacy Qt
`tests/conftest.py`.

Private session drafts use per-profile SQLite, separate document payload/header/metadata rows, guarded WAL or DELETE journals, and durable synchronous settings. The original workspace_state.json migrates once and remains preserved. Public .dpw/script/notebook formats remain unchanged; restore never executes saved code. See [private session persistence](../../docs/TAURI_SESSION_PERSISTENCE.md) for patch DTOs, recovery rules and measured source smoke.
