"""
DrillholeDB - A Python library for geological drillhole data management

This library provides tools for managing, desurveying, and analyzing geological
drillhole data including collar, survey, assay, and other interval/point data.

Key Features:
- Multi-hole database management
- Minimum curvature desurveying (fully vectorized)
- Interval and point data management
- Automatic coordinate calculation
- Custom column mapping support
- Merge tables with common interval edges
- 3D visualization support (PyVista)

Basic Usage:
    >>> from drillholedb import DrillholeDatabase
    >>> import pandas as pd
    >>> 
    >>> # Load data
    >>> collar_df = pd.read_csv('collar.csv')
    >>> survey_df = pd.read_csv('survey.csv')
    >>> 
    >>> # Create database
    >>> db = DrillholeDatabase(collar_df, survey_df)
    >>> 
    >>> # Query individual drillhole
    >>> dh = db.get_drillhole('PB-01')
    >>> print(dh.summary())
"""

from .database import DrillholeDatabase, Drillhole
from .utils import dip_az_to_unit_vector

__version__ = "1.0.0"
__author__ = "DrillholeDB Contributors"

__all__ = [
    "DrillholeDatabase",
    "Drillhole",
    "dip_az_to_unit_vector",
]
