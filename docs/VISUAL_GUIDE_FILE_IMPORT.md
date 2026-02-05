# Visual Guide: File Import Feature

## How the Feature Works

### Before: Manual Import (Old Way)
```python
# User had to type this manually:
import pandas as pd
df = pd.read_csv('/path/to/file.csv')
```

### After: Drag-and-Drop Import (New Way)
```
┌─────────────────────────────────────────┐
│  File Explorer                          │
│  📁 Documents                           │
│    📄 sales_2024.csv   ◄─── Drag this   │
│    📄 customers.json                    │
│    📄 products.xlsx                     │
└─────────────────────────────────────────┘
           │
           │ (Drag)
           ▼
┌─────────────────────────────────────────┐
│  DataPyn - Block Editor                 │
│  ┌────────────────────────────────────┐ │
│  │ [PYTHON] Block 1                   │ │
│  │                                    │ │◄─ Drop here
│  │ import pandas as pd                │ │
│  │ df = pd.read_csv('/Documents/      │ │
│  │   sales_2024.csv')                 │ │
│  │                                    │ │
│  └────────────────────────────────────┘ │
│                                         │
│  + Adicionar Bloco                      │
└─────────────────────────────────────────┘
```

## Example: Single File Import

### Step 1: Locate your data file
```
📁 My Documents
  ├── 📄 sales_2024.csv
  ├── 📄 customer_data.json
  └── 📄 inventory.xlsx
```

### Step 2: Drag file to DataPyn
```
[Dragging sales_2024.csv...]
```

### Step 3: Python block created automatically
```python
import pandas as pd
df = pd.read_csv('/home/user/Documents/sales_2024.csv')
```

### Step 4: Execute and use
```python
# Press F5 to execute
# Now you can use the dataframe:
print(df.head())
print(df.describe())
```

## Example: Multiple Files Import

### Drop 3 files at once:
```
┌──────────────────────────────┐
│ sales.csv                    │
│ customers.json               │◄─── Select all 3
│ products.xlsx                │     and drag together
└──────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────┐
│  DataPyn creates 3 blocks:              │
│  ┌────────────────────────────────────┐ │
│  │ [PYTHON] Block 1                   │ │
│  │ import pandas as pd                │ │
│  │ df = pd.read_csv('sales.csv')      │ │
│  └────────────────────────────────────┘ │
│  ┌────────────────────────────────────┐ │
│  │ [PYTHON] Block 2                   │ │
│  │ import pandas as pd                │ │
│  │ df = pd.read_json('customers.json')│ │
│  └────────────────────────────────────┘ │
│  ┌────────────────────────────────────┐ │
│  │ [PYTHON] Block 3                   │ │
│  │ import pandas as pd                │ │
│  │ df = pd.read_excel('products.xlsx')│ │
│  └────────────────────────────────────┘ │
└─────────────────────────────────────────┘
```

## Supported File Types

| Extension | Function Used        | Example                                    |
|-----------|---------------------|-------------------------------------------|
| `.csv`    | `pd.read_csv()`     | `df = pd.read_csv('data.csv')`            |
| `.json`   | `pd.read_json()`    | `df = pd.read_json('data.json')`          |
| `.xlsx`   | `pd.read_excel()`   | `df = pd.read_excel('data.xlsx')`         |
| `.xls`    | `pd.read_excel()`   | `df = pd.read_excel('data.xls')`          |

## Benefits

### ⚡ Fast
- No need to type file paths manually
- No need to remember pandas functions
- Instant code generation

### 🎯 Accurate
- No typos in file paths
- Correct pandas function for each file type
- Normalized paths work on all platforms

### 🔧 Flexible
- Edit generated code as needed
- Add parameters to read functions
- Rename variables
- Combine with existing code

## Advanced Usage Examples

### Example 1: CSV with custom parameters
```python
# Generated code:
import pandas as pd
df = pd.read_csv('/data/sales.csv')

# You can edit to add parameters:
import pandas as pd
df = pd.read_csv('/data/sales.csv', 
                  sep=';', 
                  encoding='utf-8',
                  parse_dates=['date'])
```

### Example 2: Excel with sheet selection
```python
# Generated code:
import pandas as pd
df = pd.read_excel('/data/report.xlsx')

# Edit to specify sheet:
import pandas as pd
df = pd.read_excel('/data/report.xlsx', sheet_name='Summary')
```

### Example 3: JSON with nested data
```python
# Generated code:
import pandas as pd
df = pd.read_json('/data/api_response.json')

# Edit to normalize nested JSON:
import pandas as pd
df = pd.json_normalize(pd.read_json('/data/api_response.json')['results'])
```

## Workflow Example

```
Typical data analysis workflow:

1. 📥 Drag data.csv → Auto-generates import code
2. ▶️  Execute block → Data loaded into df
3. 🔍 Add new block → Explore data
   print(df.head())
   print(df.info())
4. 📊 Add analysis block → Analyze
   df.groupby('category')['sales'].sum()
5. 💾 Export results → Save findings
```

## Technical Details

### Implementation
- **File**: `source/src/editors/block_editor.py`
- **Method**: `dropEvent()` handles file drops
- **Code Gen**: `_generate_import_code()` creates pandas code

### Path Normalization
```python
# Windows path:
C:\Users\João\data.csv
# Becomes:
C:/Users/João/data.csv

# Works perfectly on all platforms!
```

### Case Insensitive
```python
# All these work:
data.CSV  → pd.read_csv()
data.csv  → pd.read_csv()
DATA.CSV  → pd.read_csv()
```

## FAQ

**Q: What if I drop a file that's not supported?**
A: The file will be ignored. Only .csv, .json, .xlsx, .xls are accepted.

**Q: Can I drop files onto existing blocks?**
A: New blocks are always created. Existing blocks are never modified.

**Q: What variable name is used?**
A: Always `df` (DataFrame). You can rename it after generation.

**Q: Does it work with network paths?**
A: Yes! Any valid file path works, including UNC paths on Windows.

**Q: Can I drop the same file twice?**
A: Yes! Each drop creates a new block with the same import code.
