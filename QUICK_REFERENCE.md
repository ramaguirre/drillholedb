# DrillholeDB - Quick Reference Card

## 🚀 Installation

```bash
pip install -e .
```

## 📦 Import

```python
from drillholedb import DrillholeDatabase
import pandas as pd
```

## 🏗️ Create Database

```python
collar_df = pd.read_csv('collar.csv')
survey_df = pd.read_csv('survey.csv')
db = DrillholeDatabase(collar_df, survey_df)
```

## 🔍 Query Data

```python
# Get all holes
holes = db.get_holeid_list()

# Get specific hole
dh = db.get_drillhole('PB-01')

# Summary
print(db.summary())
print(dh.summary())
```

## 📊 Add Data

```python
# Add assays
assay_df = pd.read_csv('assays.csv')
db.add_interval_data(assay_df, name='assays')

# Add point data
db.add_point_data(gamma_df, name='gamma')
```

## 🧮 Calculate

```python
# Hole statistics
length = dh.calculate_hole_length()
rake = dh.calculate_rake_geometry()

# Interpolate
x, y, z = dh.interpolate_at_depth(50.0, attribute='xyz')
```

## 🔗 Merge Tables

```python
merged = db.merge_interval_tables(
    table_names=['Assay_1', 'Assay_2'],
    sel_columns_dict={'Assay_1': ['Au_ppm']},
    merged_table_name='combined'
)
```

## 📤 Export

```python
# Export traces
traces = db.get_all_traces()
traces.to_csv('traces.csv')

# Export statistics
stats = db.calculate_statistics()
stats.to_csv('stats.csv')
```

## 🎨 Visualize

```python
import pyvista as pv
trace = dh.get_pyvista_trace()
plotter = pv.Plotter()
plotter.add_mesh(trace, scalars='depth')
plotter.show()
```

## 📂 File Structure

```
drillholedb/
├── drillholedb/          # Package
├── docs/                 # Documentation
├── pyproject.toml        # Config
└── README.md             # Readme
```

## 📖 Documentation

- **README.md** - Overview
- **docs/user_guide.md** - Complete guide
- **docs/api_reference.md** - API docs

## 🛠️ Custom Columns

```python
db = DrillholeDatabase(
    collar_df, survey_df,
    collar_columns={'holeid': 'HOLE_ID', 'x': 'EASTING'},
    survey_columns={'depth': 'MD', 'dip': 'INC'}
)
```

## 🎯 Common Tasks

**Load everything:**
```python
db = DrillholeDatabase(collar_df, survey_df)
db.add_interval_data(assay_df, 'assays')
print(db.summary())
```

**Query & analyze:**
```python
dh = db.get_drillhole('PB-01')
length = dh.calculate_hole_length()
if 'assays' in dh.interval_data:
    assays = dh.interval_data['assays']
    print(assays[['from', 'to', 'Au_ppm']].head())
```

**Batch process:**
```python
stats = db.calculate_statistics()
traces = db.get_all_traces()
```

## ⚡ Performance Tips

- Use `use_cache=True` for repeated queries
- Set `auto_desurvey=False` if coordinates not needed
- Process holes in batches
- Use column selection in merges

## 🐛 Troubleshooting

**Import error?**
→ Run `pip install -e .`

**Column not found?**
→ Use custom column mapping

**Slow performance?**
→ Process fewer holes at once

## 📞 Getting Help

1. Check `docs/user_guide.md`
2. See `examples/basic_usage.py`
3. Review `SETUP_INSTRUCTIONS.md`
4. Read API docs in `docs/api_reference.md`

## ✅ Quick Test

```python
from drillholedb import DrillholeDatabase
import pandas as pd

# Test import
collar = pd.read_csv('test_data/collar.csv')
survey = pd.read_csv('test_data/survey.csv')
db = DrillholeDatabase(collar, survey)
print(f"Loaded {len(db.get_holeid_list())} holes ✓")
```

---

**Ready to start? Run: `pip install -e .`**
