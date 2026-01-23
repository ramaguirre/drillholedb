# API Reference

## DrillholeDatabase Class

Main class for managing multiple geological drillholes.

### Constructor

```python
DrillholeDatabase(
    collar_data: pd.DataFrame,
    survey_data: pd.DataFrame,
    collar_columns: Optional[Dict[str, str]] = None,
    survey_columns: Optional[Dict[str, str]] = None,
    dogleg_threshold: float = 500.0,
    validate: bool = True
)
```

**Parameters:**
- `collar_data`: DataFrame with collar information for all drillholes
- `survey_data`: DataFrame with survey data for all drillholes
- `collar_columns`: Custom column name mapping for collar data
- `survey_columns`: Custom column name mapping for survey data
- `dogleg_threshold`: Maximum dogleg severity (degrees per 30m). Points exceeding this are ignored
- `validate`: Whether to perform input validation

**Returns:** DrillholeDatabase instance

---

### Query Methods

#### `get_holeid_list()`

Get list of all drillhole IDs in the database.

**Returns:** List[str] - Sorted list of holeid strings

**Example:**
```python
holes = db.get_holeid_list()
print(f"Database contains {len(holes)} drillholes")
```

---

#### `get_drillhole(holeid, use_cache=True)`

Get a Drillhole object for a specific holeid.

**Parameters:**
- `holeid`: Drillhole identifier (str)
- `use_cache`: Whether to use cached drillhole object (bool, default=True)

**Returns:** Drillhole object

**Raises:** ValueError if holeid not found

**Example:**
```python
dh = db.get_drillhole('HOLE-01')
print(dh.summary())
```

---

### Data Management Methods

#### `add_interval_data(data, name, column_mapping=None, validate=True, auto_desurvey=True)`

Add interval data for all drillholes.

**Parameters:**
- `data`: DataFrame with interval data for multiple holes
- `name`: Dataset identifier (str)
- `column_mapping`: Custom column mappings (dict, optional)
- `validate`: Whether to validate the data (bool, default=True)
- `auto_desurvey`: Whether to automatically add xyz coordinates (bool, default=True)

**Example:**
```python
assay_df = pd.read_csv('assays.csv')
db.add_interval_data(assay_df, name='assays')

# With custom columns
db.add_interval_data(
    lith_df,
    name='lithology',
    column_mapping={'holeid': 'HOLE_ID', 'from': 'FROM_M', 'to': 'TO_M'}
)
```

---

#### `add_point_data(data, name, column_mapping=None, validate=True, auto_desurvey=True)`

Add point data for all drillholes.

**Parameters:**
- `data`: DataFrame with point data for multiple holes
- `name`: Dataset identifier (str)
- `column_mapping`: Custom column mappings (dict, optional)
- `validate`: Whether to validate the data (bool, default=True)
- `auto_desurvey`: Whether to automatically add xyz coordinates (bool, default=True)

**Example:**
```python
gamma_df = pd.read_csv('gamma.csv')
db.add_point_data(gamma_df, name='gamma')
```

---

#### `add_collar_data(collar_data, survey_data=None, collar_columns=None, survey_columns=None)`

Add new collar data and optionally survey data to database. Automatically reconciles orphaned interval data.

**Parameters:**
- `collar_data`: DataFrame with collar data
- `survey_data`: DataFrame with survey data (optional)
- `collar_columns`: Custom column mapping for collar data (dict, optional)
- `survey_columns`: Custom column mapping for survey data (dict, optional)

**Example:**
```python
# Add missing collar data
db.add_collar_data(new_collar_df, new_survey_df)
```

---

### Desurveying Methods

#### `desurvey_point_data(point_data, depth_column='depth', filter_column=None)`

Desurvey any point data using pre-calculated minimum curvature trajectories.

**Parameters:**
- `point_data`: DataFrame with holeid and depth columns
- `depth_column`: Name of depth column (str, default='depth')
- `filter_column`: Column to filter points (str, optional)

**Returns:** DataFrame with x, y, z columns added

**Example:**
```python
custom_points = pd.DataFrame({
    'holeid': ['HOLE-01', 'HOLE-01'],
    'depth': [10.0, 20.0],
    'measurement': [100, 150]
})
desurveyed = db.desurvey_point_data(custom_points)
```

---

#### `desurvey_interval_data(interval_data, from_column='from', to_column='to')`

Desurvey any interval data using minimum curvature method.

**Parameters:**
- `interval_data`: DataFrame with holeid, from, and to columns
- `from_column`: Name of 'from' depth column (str, default='from')
- `to_column`: Name of 'to' depth column (str, default='to')

**Returns:** DataFrame with top/mid/bottom xyz columns added

---

### Table Merging Methods

#### `merge_interval_tables(table_names=None, sel_columns_dict=None, merged_table_name=None, store_as_merged=True, auto_desurvey=True)`

Merge multiple interval tables into a single DataFrame with common interval edges.

**Parameters:**
- `table_names`: List of table names to merge (list, optional). If None, merges all tables
- `sel_columns_dict`: Dict mapping table names to columns to select (dict, optional)
- `merged_table_name`: Name for merged table (str, optional)
- `store_as_merged`: Whether to store the merged table (bool, default=True)
- `auto_desurvey`: Whether to add xyz coordinates (bool, default=True)

**Returns:** DataFrame with merged data

**Example:**
```python
merged = db.merge_interval_tables(
    table_names=['Assay_1', 'Assay_2'],
    sel_columns_dict={
        'Assay_1': ['Au_ppm', 'Cu_pct'],
        'Assay_2': ['Ag_ppm']
    },
    merged_table_name='precious_metals'
)
```

---

#### `get_merged_table_info(merged_table_name=None)`

Get information about merged tables.

**Parameters:**
- `merged_table_name`: Specific table name (str, optional). If None, returns info for all

**Returns:** 
- If name specified: Dict with merge parameters
- If None: DataFrame summarizing all merged tables

**Example:**
```python
# Get info for specific table
info = db.get_merged_table_info('precious_metals')
print(info['source_tables'])

# Get summary of all merged tables
summary = db.get_merged_table_info()
print(summary)
```

---

### Batch Processing Methods

#### `get_all_traces(holeids=None, point_spacing=1.0)`

Get densified traces for all or specified drillholes.

**Parameters:**
- `holeids`: List of holeids to process (list, optional). If None, process all
- `point_spacing`: Spacing between interpolated points in meters (float, default=1.0)

**Returns:** DataFrame with combined trace data

**Example:**
```python
# Get all traces
traces = db.get_all_traces()
traces.to_csv('all_traces.csv', index=False)

# Get specific holes
traces = db.get_all_traces(['HOLE-01', 'HOLE-02', 'HOLE-03'])
```

---

#### `calculate_statistics(holeids=None)`

Calculate summary statistics for all or specified drillholes.

**Parameters:**
- `holeids`: List of holeids to process (list, optional)

**Returns:** DataFrame with statistics

**Example:**
```python
stats = db.calculate_statistics()
print(stats[['holeid', 'hole_length', 'tvd', 'horizontal_disp']].head())
```

---

### Utility Methods

#### `summary()`

Generate database summary string.

**Returns:** str - Formatted summary

**Example:**
```python
print(db.summary())
```

---

## Drillhole Class

Individual drillhole object returned by `get_drillhole()`.

### Attributes

- `holeid` (str): Drillhole identifier
- `collar` (pd.Series): Collar information
- `survey` (pd.DataFrame): Survey data
- `trace` (pd.DataFrame): Calculated 3D trace
- `interval_data` (Dict[str, pd.DataFrame]): Dictionary of interval datasets
- `point_data` (Dict[str, pd.DataFrame]): Dictionary of point datasets

---

### Methods

#### `calculate_hole_length()`

Calculate total 3D hole length.

**Returns:** float - Total length in meters

**Example:**
```python
length = dh.calculate_hole_length()
print(f"Hole length: {length:.2f} m")
```

---

#### `calculate_rake_geometry()`

Calculate rake geometry properties.

**Returns:** Dict with geometry properties:
- `vertical_depth`: Vertical depth (m)
- `horizontal_displacement`: Horizontal displacement (m)
- `final_bearing`: Final bearing (degrees)
- `upward_sections`: Length of upward sections (m)
- `downward_sections`: Length of downward sections (m)
- `max_dip`: Maximum dip (degrees)
- `min_dip`: Minimum dip (degrees)

**Example:**
```python
rake = dh.calculate_rake_geometry()
print(f"TVD: {rake['vertical_depth']:.2f} m")
print(f"Horizontal displacement: {rake['horizontal_displacement']:.2f} m")
```

---

#### `interpolate_at_depth(depth, attribute='xyz')`

Interpolate position or attributes at specific depth(s) using minimum curvature.

**Parameters:**
- `depth`: Single depth or array of depths (float or np.ndarray)
- `attribute`: What to interpolate (str):
  - `'xyz'`: 3D coordinates
  - `'dip'`: Dip angle
  - `'azimuth'`: Azimuth angle
  - `'all'`: Everything

**Returns:** Interpolated values (format depends on attribute)

**Example:**
```python
# Single depth
x, y, z = dh.interpolate_at_depth(50.0, attribute='xyz')

# Multiple depths
depths = np.array([10.0, 20.0, 30.0])
xyz = dh.interpolate_at_depth(depths, attribute='xyz')  # Returns array

# Get all attributes
all_data = dh.interpolate_at_depth(50.0, attribute='all')
print(all_data)  # {'x': ..., 'y': ..., 'z': ..., 'dip': ..., 'azimuth': ...}
```

---

#### `get_pyvista_trace(point_spacing=1.0, **kwargs)`

Generate PyVista PolyData for 3D visualization.

**Parameters:**
- `point_spacing`: Spacing between interpolated points in meters (float, default=1.0)
- `**kwargs`: Additional arguments passed to pv.PolyData

**Returns:** pv.PolyData - Densified trace for visualization

**Requires:** PyVista installed

**Example:**
```python
import pyvista as pv

trace = dh.get_pyvista_trace(point_spacing=1.0)
plotter = pv.Plotter()
plotter.add_mesh(trace, scalars='depth', render_lines_as_tubes=True)
plotter.show()
```

---

#### `summary()`

Generate drillhole summary string.

**Returns:** str - Formatted summary

**Example:**
```python
print(dh.summary())
```

---

## Utility Functions

### `dip_az_to_unit_vector(dip, azimuth)`

Convert dip and azimuth angles to unit direction vectors.

**Parameters:**
- `dip`: Dip angle in degrees (float or array)
- `azimuth`: Azimuth angle in degrees (float or array)

**Returns:** np.ndarray - Unit vector [x, y, z] where x=East, y=North, z=Down

**Example:**
```python
from drillholedb import dip_az_to_unit_vector

# Single angle
vec = dip_az_to_unit_vector(45.0, 90.0)  # 45° dip, East

# Multiple angles
dips = np.array([0, 45, 90])
azimuths = np.array([0, 90, 180])
vecs = dip_az_to_unit_vector(dips, azimuths)
```

---

## Data Structures

### Standard Column Names

**Collar Data:**
- `holeid`: Drillhole identifier
- `x`: Easting coordinate
- `y`: Northing coordinate
- `z`: Elevation/RL
- `depth`: Total/planned depth

**Survey Data:**
- `holeid`: Drillhole identifier
- `depth`: Measured depth
- `dip`: Dip/inclination angle (degrees)
- `azimuth`: Azimuth/bearing angle (degrees)

**Interval Data:**
- `holeid`: Drillhole identifier
- `from`: From depth
- `to`: To depth
- Additional columns: Any data columns (Au_ppm, Cu_pct, etc.)

**Point Data:**
- `holeid`: Drillhole identifier
- `depth`: Measured depth
- Additional columns: Any data columns

### Auto-Generated Columns

**Survey Data (auto-generated):**
- `dogleg_severity`: Dogleg severity (degrees per 30m)
- `ignored`: Boolean flag for ignored survey points
- `x`, `y`, `z`: 3D coordinates at survey stations

**Interval Data (when auto_desurvey=True):**
- `top_x`, `top_y`, `top_z`: Coordinates at 'from' depth
- `mid_x`, `mid_y`, `mid_z`: Coordinates at midpoint
- `bottom_x`, `bottom_y`, `bottom_z`: Coordinates at 'to' depth

**Point Data (when auto_desurvey=True):**
- `x`, `y`, `z`: 3D coordinates at depth

---

## Error Handling

### Common Exceptions

**ValueError**: Raised when:
- Required columns are missing
- Holeid not found in database
- Invalid intervals (from >= to)
- Invalid depths (depth < 0)

**KeyError**: Raised when:
- Accessing non-existent table or dataset
- Merged table not found

**ImportError**: Raised when:
- PyVista not installed but visualization requested

### Warnings

**UserWarning**: Issued for:
- Holes in collar data missing survey data
- Holes in survey data missing collar data
- Invalid intervals or depths
- Survey points exceeding dogleg threshold
- Orphaned interval data (holes without collar data)

---

## Performance Considerations

### Optimization Tips

1. **Caching**: Use `use_cache=True` for repeated queries
2. **Batch operations**: Process multiple holes together
3. **Disable auto-desurvey**: Set `auto_desurvey=False` if coordinates not needed
4. **Column selection**: Use `sel_columns_dict` when merging
5. **Point spacing**: Use larger spacing for faster trace generation

### Typical Performance

- **Database initialization**: 1-5 seconds for 6000+ holes
- **Desurveying**: 100,000+ intervals/second
- **Query (cached)**: <50ms per drillhole
- **Batch statistics**: 2-5 seconds for 100 holes

---

## Version History

### 1.0.0
- Initial release
- Multi-hole database management
- Vectorized desurveying
- Table merging
- PyVista visualization
- Automatic coordinate calculation
