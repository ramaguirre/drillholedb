# User Guide

## Installation

```bash
pip install drillholedb
```

Or from source:
```bash
git clone https://github.com/yourusername/drillholedb.git
cd drillholedb
pip install -e .
```

## Creating a Database

### Basic Setup

```python
from drillholedb import DrillholeDatabase
import pandas as pd

# Load your data
collar_df = pd.read_csv('collar.csv')
survey_df = pd.read_csv('survey.csv')

# Create database
db = DrillholeDatabase(collar_df, survey_df)
```

### Custom Column Names

If your data uses non-standard column names:

```python
db = DrillholeDatabase(
    collar_df,
    survey_df,
    collar_columns={
        'holeid': 'HOLE_ID',
        'x': 'EASTING',
        'y': 'NORTHING',
        'z': 'ELEVATION',
        'depth': 'MAX_DEPTH'
    },
    survey_columns={
        'holeid': 'HOLE_ID',
        'depth': 'MD',
        'dip': 'INCLINATION',
        'azimuth': 'BEARING'
    }
)
```

### Dogleg Severity Filtering

Control which survey points are used based on dogleg severity:

```python
db = DrillholeDatabase(
    collar_df,
    survey_df,
    dogleg_threshold=300.0  # degrees per 30m (default: 500.0)
)
```

## Working with Interval Data

### Adding Assay Data

```python
assay_df = pd.read_csv('assays.csv')
db.add_interval_data(assay_df, name='assays')
```

The library automatically:
- ✅ Detects column names (SAMPFROM, SAMPTO, etc.)
- ✅ Calculates XYZ coordinates (top, mid, bottom)
- ✅ Distributes data to individual drillholes

### Accessing Interval Data

```python
# Query specific drillhole
dh = db.get_drillhole('PB-01')

# Access interval data with coordinates
assays = dh.interval_data['assays']
print(assays[['from', 'to', 'Au_ppm', 'mid_x', 'mid_y', 'mid_z']])
```

### Multiple Interval Datasets

You can add multiple types of interval data:

```python
db.add_interval_data(assay_df, name='assays')
db.add_interval_data(lith_df, name='lithology')
db.add_interval_data(geotech_df, name='geotech')

# Access all datasets
dh = db.get_drillhole('PB-01')
print(dh.interval_data.keys())  # ['assays', 'lithology', 'geotech']
```

## Merging Tables

Merge multiple interval tables with common interval edges:

```python
# Merge all assay tables
merged = db.merge_interval_tables(
    table_names=['Assay_1', 'Assay_2', 'Assay_3'],
    sel_columns_dict={
        'Assay_1': ['Au_ppm', 'Cu_pct'],
        'Assay_2': ['Ag_ppm'],
        'Assay_3': ['Pb_ppm', 'Zn_pct']
    },
    merged_table_name='all_metals'
)

# Access merged table
print(db.merged_interval_data['all_metals'].head())

# Get merge information
info = db.get_merged_table_info('all_metals')
print(info['source_tables'])
```

## Working with Point Data

```python
# Add geophysics logs
gamma_df = pd.read_csv('gamma_log.csv')
db.add_point_data(gamma_df, name='gamma')

# Access with coordinates
dh = db.get_drillhole('PB-01')
gamma = dh.point_data['gamma']
print(gamma[['depth', 'gamma_cps', 'x', 'y', 'z']])
```

## Batch Operations

### Export All Traces

```python
# Export 3D traces for all holes
traces = db.get_all_traces()
traces.to_csv('all_traces.csv', index=False)

# Export specific holes
traces = db.get_all_traces(['PB-01', 'PB-02', 'PB-03'])
```

### Calculate Statistics

```python
# Calculate for all holes
stats = db.calculate_statistics()

# Calculate for specific holes
stats = db.calculate_statistics(['PB-01', 'PB-02'])

# View results
print(stats[['holeid', 'hole_length', 'tvd', 'horizontal_disp']])
```

## 3D Visualization

```python
import pyvista as pv

# Get single drillhole trace
dh = db.get_drillhole('PB-01')
trace = dh.get_pyvista_trace(point_spacing=1.0)

# Visualize
plotter = pv.Plotter()
plotter.add_mesh(trace, scalars='depth', render_lines_as_tubes=True, line_width=5)
plotter.show()

# Visualize with interval data
if 'assays' in dh.interval_data:
    assays = dh.interval_data['assays']
    points = pv.PolyData(assays[['mid_x', 'mid_y', 'mid_z']].values)
    points['Au_ppm'] = assays['Au_ppm'].values
    plotter.add_mesh(points, scalars='Au_ppm', point_size=10)
```

## Advanced Features

### Custom Desurveying

```python
# Desurvey custom point data
custom_df = pd.DataFrame({
    'holeid': ['PB-01', 'PB-01'],
    'depth': [10.0, 20.0],
    'measurement': [100, 150]
})

desurveyed = db.desurvey_point_data(custom_df, depth_column='depth')
print(desurveyed[['holeid', 'depth', 'measurement', 'x', 'y', 'z']])
```

### Interpolation at Specific Depths

```python
dh = db.get_drillhole('PB-01')

# Get XYZ at specific depth
x, y, z = dh.interpolate_at_depth(50.0, attribute='xyz')

# Get multiple depths
depths = [10.0, 20.0, 30.0, 40.0, 50.0]
xyz = dh.interpolate_at_depth(depths, attribute='xyz')

# Get dip and azimuth
dip = dh.interpolate_at_depth(50.0, attribute='dip')
azimuth = dh.interpolate_at_depth(50.0, attribute='azimuth')

# Get everything
all_data = dh.interpolate_at_depth(50.0, attribute='all')
print(all_data)  # {'x': ..., 'y': ..., 'z': ..., 'dip': ..., 'azimuth': ...}
```

### Handling Missing Collar Data

```python
# Add interval data even if some holes lack collar data
db.add_interval_data(assay_df, name='assays')
# Warning: X holes not found in collar data

# Later, add missing collar data
db.add_collar_data(new_collar_df, new_survey_df)
# Auto-reconciling orphaned interval data...
```

## Performance Tips

1. **Use caching**: Set `use_cache=True` when repeatedly querying the same holes
2. **Batch operations**: Process multiple holes together for better performance
3. **Disable auto-desurvey**: Set `auto_desurvey=False` if you don't need coordinates
4. **Filter columns**: Use `sel_columns_dict` when merging to reduce memory usage

## Common Patterns

### Quality Control

```python
# Check for holes with suspicious geometry
stats = db.calculate_statistics()
suspicious = stats[
    (stats['horizontal_disp'] > 100) |  # Large displacement
    (stats['max_dip'] < 45)  # Too shallow
]
print(suspicious)
```

### Data Export

```python
# Export everything for GIS
for holeid in db.get_holeid_list():
    dh = db.get_drillhole(holeid)
    
    # Export collar
    collar_point = pd.DataFrame([{
        'holeid': holeid,
        'x': dh.collar['x'],
        'y': dh.collar['y'],
        'z': dh.collar['z']
    }])
    
    # Export trace
    trace = dh.trace
    
    # Export assays with coordinates
    if 'assays' in dh.interval_data:
        assays = dh.interval_data['assays']
        assays.to_csv(f'output/{holeid}_assays.csv')
```

### Database Summary

```python
# Get overview
print(db.summary())

# Get counts
print(f"Total holes: {len(db.get_holeid_list())}")
print(f"Interval datasets: {list(db.interval_data.keys())}")
print(f"Merged tables: {list(db.merged_interval_data.keys())}")

# Get merge information
if db.merged_interval_data:
    merge_info = db.get_merged_table_info()
    print(merge_info)
```

## Troubleshooting

### Column Not Found
If you get "Missing required columns" error:
- Check your column names match standard formats
- Use `collar_columns` or `survey_columns` parameters for custom names

### Dogleg Warnings
If you see "survey points exceed dogleg threshold":
- Some survey points have extreme direction changes
- Points are automatically flagged and ignored
- Adjust `dogleg_threshold` if needed

### Performance Issues
If processing is slow:
- Reduce the number of holes processed at once
- Disable `auto_desurvey` and calculate coordinates only when needed
- Use `use_cache=True` for repeated queries

## Next Steps

- See [API Reference](api_reference.md) for complete method documentation
- Review the code examples throughout this guide for usage patterns
- Check the method signatures in the API reference for all available parameters
