# DrillholeDB

A comprehensive Python library for geological drillhole data management, desurveying, and analysis.

[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## Features

✨ **Multi-Hole Database Management** - Load and manage multiple drillholes simultaneously  
📐 **Minimum Curvature Desurveying** - Industry-standard desurveying with full vectorization  
🚀 **High Performance** - Vectorized operations processing 100,000+ intervals/second  
🔄 **Flexible Data Input** - Automatic column name detection and custom mapping support  
📊 **Interval & Point Data** - Manage assays, lithology, geophysics, and any interval/point data  
🔗 **Table Merging** - Merge multiple interval tables with common interval edges  
📈 **3D Visualization** - PyVista integration for interactive 3D visualization  
🎯 **Auto-Coordinate Calculation** - Automatic XYZ calculation for all data types  

## Installation

### From PyPI (when published)
```bash
pip install drillholedb
```

### From Source
```bash
git clone https://github.com/yourusername/drillholedb.git
cd drillholedb
pip install -e .
```

### With Optional Dependencies
```bash
# For 3D visualization
pip install drillholedb[viz]

# For progress bars
pip install drillholedb[progress]

# Everything
pip install drillholedb[all]
```

## Quick Start

```python
from drillholedb import DrillholeDatabase
import pandas as pd

# Load collar and survey data
collar_df = pd.read_csv('collar.csv')
survey_df = pd.read_csv('survey.csv')

# Create database (automatically desurveys all data)
db = DrillholeDatabase(collar_df, survey_df)

# Query specific drillhole
dh = db.get_drillhole('PB-01')
print(dh.summary())

# Add interval data (e.g., assays)
assay_df = pd.read_csv('assays.csv')
db.add_interval_data(assay_df, name='assays')

# Access desurveyed data
dh = db.get_drillhole('PB-01')
print(dh.interval_data['assays'][['from', 'to', 'Au_ppm', 'mid_x', 'mid_y', 'mid_z']])
```

## Input Data Format

### Collar Data
| HOLEID | EAST | NORTH | RL | DEPTH |
|--------|------|-------|-------|-------|
| PB-01 | 483624.56 | 7436035.26 | 2401.64 | 300.0 |
| PB-02 | 483830.33 | 7435840.12 | 2422.79 | 350.0 |

### Survey Data
| HOLEID | DEPTH | DIP | AZIMUTH |
|--------|-------|-----|---------|
| PB-01 | 0.0 | 89.656 | 88.211 |
| PB-01 | 10.0 | 89.724 | 92.555 |

### Interval Data (e.g., Assays)
| HOLEID | SAMPFROM | SAMPTO | Au_ppm | Cu_pct |
|--------|----------|--------|--------|--------|
| PB-01 | 0.0 | 2.0 | 0.5 | 1.2 |
| PB-01 | 2.0 | 4.0 | 0.8 | 1.5 |

## Key Features

### Custom Column Mapping

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

### Automatic Coordinate Calculation

All interval and point data automatically gets XYZ coordinates:
- **Interval data**: `top_x`, `top_y`, `top_z`, `mid_x`, `mid_y`, `mid_z`, `bottom_x`, `bottom_y`, `bottom_z`
- **Point data**: `x`, `y`, `z`

### Merge Multiple Tables

```python
# Merge assay tables with common intervals
merged = db.merge_interval_tables(
    table_names=['Assay_1', 'Assay_2'],
    sel_columns_dict={
        'Assay_1': ['Au_ppm', 'Cu_pct'],
        'Assay_2': ['Ag_ppm']
    },
    merged_table_name='precious_metals'
)
```

### Export Traces

```python
# Export 3D traces for all holes
traces = db.get_all_traces()
traces.to_csv('drillhole_traces.csv', index=False)
```

### Calculate Statistics

```python
# Get summary statistics
stats = db.calculate_statistics()
print(stats[['holeid', 'hole_length', 'tvd', 'horizontal_disp']].head())
```

### 3D Visualization

```python
# Get PyVista polydata for visualization
dh = db.get_drillhole('PB-01')
trace_3d = dh.get_pyvista_trace(point_spacing=1.0)

# Plot with PyVista
import pyvista as pv
plotter = pv.Plotter()
plotter.add_mesh(trace_3d, scalars='depth', render_lines_as_tubes=True, line_width=5)
plotter.show()
```

## Advanced Features

### Dogleg Severity Filtering

```python
# Set custom dogleg threshold (degrees per 30m)
db = DrillholeDatabase(
    collar_df, 
    survey_df,
    dogleg_threshold=300.0  # More restrictive
)
```

### Orphaned Data Reconciliation

```python
# Add interval data even if some holes don't have collar data yet
db.add_interval_data(assay_df, name='assays')
# Warning: X holes not found in collar data

# Later, add missing collar data - automatically reconciles
db.add_collar_data(missing_collar_df, missing_survey_df)
# Auto-reconciling orphaned interval data...
```

### Table Dependencies

Merged tables automatically update when source tables change:

```python
# Create merged table
db.merge_interval_tables(['Assay_1', 'Assay_2'], merged_table_name='combined')

# Update source table
db.add_interval_data(new_assay_data, 'Assay_1')
# Output: Updating 1 dependent merged table(s)...
#         ✓ Updated merged table 'combined'
```

## Performance

DrillholeDB is built for speed with fully vectorized operations:

- **Desurveying**: 100,000+ intervals/second
- **Database creation**: 1,000 holes in seconds
- **Memory efficient**: Sparse matrix for overlap detection
- **Batch processing**: Process all holes simultaneously

## Documentation

- **User Guide**: [docs/user_guide.md](docs/user_guide.md)
- **API Reference**: [docs/api_reference.md](docs/api_reference.md)

## Requirements

### Core Dependencies
- Python ≥ 3.8
- NumPy ≥ 1.20
- Pandas ≥ 1.3
- SciPy ≥ 1.7

### Optional Dependencies
- PyVista ≥ 0.38 (for 3D visualization)
- tqdm ≥ 4.60 (for progress bars)

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Citation

If you use this software in your research, please cite:

```bibtex
@software{drillholedb,
  author = {Your Name},
  title = {DrillholeDB: A Python Library for Geological Drillhole Data Management},
  year = {2025},
  url = {https://github.com/yourusername/drillholedb}
}
```

## Acknowledgments

- Minimum curvature algorithm based on industry standards
- Vectorization techniques inspired by modern pandas best practices

## Support

For questions, issues, or feature requests, please open an issue on GitHub.

---

**Made with ❤️ for the geoscience community**
