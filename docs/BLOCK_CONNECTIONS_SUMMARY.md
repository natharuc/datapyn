# Per-Block Connection Selection - Feature Summary

## Overview

This feature allows each code block to have its own database connection, enabling users to work with multiple data sources in a single tab.

## Key Changes

### 1. CodeBlock Component (`source/src/editors/code_block.py`)

**Added:**
- Connection name field (`_connection_name`)
- Connection selector combobox in the control bar
- Methods: `get_connection_name()`, `set_connection_name()`, `update_available_connections()`
- Serialization support for connection in `to_dict()` and `from_dict()`
- Default connection parameter in constructor

**UI:**
- Added a combobox next to the language selector
- Shows "(Default tab connection)" option plus all saved connections
- Displays connection in format: "name (db_type://host/database)"

### 2. BlockEditor Component (`source/src/editors/block_editor.py`)

**Added:**
- Default connection field (`_default_connection`)
- Method: `set_default_connection()` 
- Method: `update_available_connections()`
- Connection parameter in `add_block()`
- Updated signals to include connection_name:
  - `execute_sql(query, connection_name)`
  - `execute_python(code, connection_name)`
  - `execute_cross_syntax(code, connection_name)`
  - `execute_queue` now emits `(language, code, connection_name, block)`

**Behavior:**
- New blocks inherit the tab's default connection
- Blocks can override to use a different connection
- Serialization preserves each block's connection

### 3. SessionWidget Component (`source/src/ui/components/session_widget.py`)

**Added:**
- Method: `_get_connector_for_execution()` - resolves block connection to actual connector
- Method: `update_available_connections()` - updates all blocks
- Method: `set_default_connection()` - sets default for new blocks
- Connection parameter support in execution methods

**Enhanced Execution:**
- SQL execution: Uses block's connection or falls back to session connection
- Python execution: Injects `conn` and `connection` variables into namespace
- Queue processing: Handles connection_name in execution queue

**Connection Variables in Python:**
When a Python block executes, these variables are available:
- `conn` - the database connector object for the selected connection
- `connection` - alias for `conn`
- `pd` - pandas library
- `df` - result from last SQL block

### 4. MainWindow (`source/src/ui/main_window.py`)

**Added:**
- Method: `_update_block_connections()` - refreshes connections in all session widgets
- Enhanced `_create_session_widget()` to populate connections on creation
- Enhanced `_refresh_connections_list()` to trigger connection updates

**Integration:**
- When connections are added/edited/deleted, all blocks are updated
- New session widgets get the full list of available connections
- Connection format: `(name, "name (db_type://host/database)")`

## Usage Examples

### Example 1: Multi-Database Analysis

**Block 1** (Connection: `Production_DB` - Language: SQL)
```sql
SELECT customer_id, order_total 
FROM orders 
WHERE order_date >= '2024-01-01'
```

**Block 2** (Connection: `Analytics_DB` - Language: Python)
```python
import pandas as pd

# conn points to Analytics_DB
segments = pd.read_sql("SELECT * FROM customer_segments", conn)

# Merge with orders from previous block (df variable)
result = df.merge(segments, on='customer_id')
print(result)
```

### Example 2: Cross-Database ETL

**Block 1** - Extract (Connection: `Source_DB`)
```sql
SELECT * FROM legacy_users
```

**Block 2** - Transform & Load (Connection: `Target_DB`)
```python
# df contains data from Block 1
# conn points to Target_DB

# Transform
df['migrated_at'] = pd.to_datetime('now')

# Load to target database
df.to_sql('users', conn, if_exists='append', index=False)
print(f"Migrated {len(df)} users")
```

## Testing

Comprehensive tests added in `tests/test_block_editor.py`:

**CodeBlock Tests:**
- `test_connection_name_serialization` - Verify connection is saved/loaded
- `test_default_connection` - Verify default connection initialization
- `test_update_available_connections` - Verify connection list updates

**BlockEditor Tests:**
- `test_default_connection_propagates_to_blocks` - Blocks inherit default
- `test_add_block_with_connection` - Custom connection per block
- `test_set_default_connection_updates_editor` - Default connection updates
- `test_serialize_with_connections` - Serialization includes connections
- `test_execute_queue_includes_connection` - Queue passes connections

## Implementation Details

### Connection Resolution

1. Block has explicit connection → Use that connection
2. Block has empty connection → Use session/tab connection
3. No connection available → Show error

### Namespace Injection

In Python blocks, the connection object is injected as:
```python
namespace['conn'] = connector
namespace['connection'] = connector
```

This allows users to write:
```python
df = pd.read_sql("SELECT * FROM table", conn)
```

### Serialization Format

Blocks are saved with connection information:
```python
{
    'language': 'python',
    'code': 'print("hello")',
    'connection_name': 'my_connection',
    'height': 150
}
```

### Backward Compatibility

- Old sessions without connection info work fine (use default)
- Blocks without connection use session connection (previous behavior)
- Empty connection name ("") means use default

## Documentation

Detailed Portuguese documentation in: `docs/BLOCK_CONNECTIONS.md`

Covers:
- Feature overview
- How to use connections in Python code
- Available variables in Python namespace
- Workflow recommendations
- Practical examples
- Troubleshooting

## Benefits

1. **Flexibility**: Work with multiple databases in one tab
2. **Organization**: Each block clearly shows its data source
3. **ETL Workflows**: Extract from one DB, load to another
4. **Environment Comparison**: Compare dev/staging/prod data easily
5. **Data Integration**: Combine data from different sources in Python

## Migration Notes

No migration needed. Existing workspaces will:
- Continue working as before
- Blocks without connection use session connection
- Can gradually adopt per-block connections as needed
