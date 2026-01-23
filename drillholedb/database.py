"""
DrillholeDatabase Class for Geological Drillhole Processing

This module provides a comprehensive database class for managing multiple geological 
drillholes, including desurveying, 3D visualization, and interval data management.

Example Input Data Formats:
---------------------------
Collar Data (DataFrame):
    HOLEID    EAST        NORTH       RL        DEPTH
    PB-01     483624.56   7436035.26  2401.64   300.0
    PB-02     483830.33   7435840.12  2422.79   350.0
    
Survey Data (DataFrame):
    HOLEID    DEPTH    DIP      AZIMUTH
    PB-01     0.0      89.656   88.211
    PB-01     10.0     89.724   92.555
    PB-02     0.0      88.500   85.000
    
Interval Data (DataFrame):
    HOLEID    SAMPFROM  SAMPTO   Au_ppm   Cu_pct
    PB-01     0.0       2.0      0.5      1.2
    PB-01     2.0       4.0      0.8      1.5
    PB-02     0.0       3.0      0.3      0.9
"""

import numpy as np
import pandas as pd
from typing import Optional, Union, List, Dict, Tuple
import warnings
from scipy.sparse import lil_matrix
from .utils import dip_az_to_unit_vector
import time

# Optional tqdm import for progress bars
try:
    from tqdm.auto import tqdm
    TQDM_AVAILABLE = True
except ImportError:
    TQDM_AVAILABLE = False
    # Fallback: create a no-op tqdm
    def tqdm(iterable, **kwargs):
        return iterable


class DrillholeDatabase:
    """
    A database class for managing multiple geological drillholes.
    
    This class stores and manages collar, survey, interval, and point data for
    multiple drillholes. It provides methods to query individual drillholes and
    perform batch operations.
    
    Attributes:
        collar_data (pd.DataFrame): All collar data
        survey_data (pd.DataFrame): All survey data
        interval_data (Dict[str, pd.DataFrame]): Dictionary of interval datasets
        point_data (Dict[str, pd.DataFrame]): Dictionary of point datasets
        drillholes (Dict[str, Drillhole]): Cache of created drillhole objects
        column_mapping (Dict[str, Dict]): Custom column name mappings
    """
    
    def __init__(
        self,
        collar_data: pd.DataFrame,
        survey_data: pd.DataFrame,
        collar_columns: Optional[Dict[str, str]] = None,
        survey_columns: Optional[Dict[str, str]] = None,
        dogleg_threshold: float = 500.0,
        validate: bool = True
    ):
        """
        Initialize DrillholeDatabase with collar and survey data for all holes.
        
        Parameters:
            collar_data (pd.DataFrame): Collar data for all drillholes
            survey_data (pd.DataFrame): Survey data for all drillholes
            collar_columns (dict, optional): Custom column mapping for collar data
                Example: {'holeid': 'HOLE_ID', 'x': 'EASTING', 'y': 'NORTHING', 
                         'z': 'ELEVATION', 'depth': 'MAX_DEPTH'}
            survey_columns (dict, optional): Custom column mapping for survey data
                Example: {'holeid': 'HOLE_ID', 'depth': 'MD', 'dip': 'INCLINATION',
                         'azimuth': 'BEARING'}
            dogleg_threshold (float): Dogleg severity threshold (°/30m) above which 
                survey points are flagged as ignored (default 500.0)
            validate (bool): Whether to perform input validation
        """
        # Store threshold
        self.dogleg_threshold = dogleg_threshold
        
        # Set default column mappings
        self.collar_mapping = self._get_default_collar_mapping()
        self.survey_mapping = self._get_default_survey_mapping()
        
        # Update with custom mappings if provided
        if collar_columns:
            for std_name, custom_name in collar_columns.items():
                if std_name in self.collar_mapping:
                    # Prepend custom name to the list of candidates
                    if isinstance(custom_name, str):
                        self.collar_mapping[std_name].insert(0, custom_name)
                    elif isinstance(custom_name, list):
                        self.collar_mapping[std_name] = custom_name + self.collar_mapping[std_name]
        
        if survey_columns:
            for std_name, custom_name in survey_columns.items():
                if std_name in self.survey_mapping:
                    # Prepend custom name to the list of candidates
                    if isinstance(custom_name, str):
                        self.survey_mapping[std_name].insert(0, custom_name)
                    elif isinstance(custom_name, list):
                        self.survey_mapping[std_name] = custom_name + self.survey_mapping[std_name]
        
        # Process and standardize data (preserves all original columns)
        self.collar_data = self._standardize_collar_data(collar_data)
        self.survey_data = self._standardize_survey_data(survey_data)
        
        # Calculate dogleg severity and add ignored mask to survey data
        self._calculate_and_add_dogleg_severity()
        
        # Build trajectory lookup tables for all holes (pre-calculated once)
        print('Building trajectories...')
        self._build_all_trajectories()
        print('Desruveying all survey data...')
        # Desurvey all survey data and add xyz coordinates
        self._desurvey_all_survey_data()
        
        # Storage for interval and point data
        self.interval_data: Dict[str, pd.DataFrame] = {}
        self.point_data: Dict[str, pd.DataFrame] = {}
        
        # Storage for merged interval tables
        self.merged_interval_data: Dict[str, pd.DataFrame] = {}
        
        # Track merge parameters for each merged table (for reproduction)
        self._merge_parameters: Dict[str, Dict] = {}
        
        # TableId counter for assigning unique identifiers to interval tables
        self._next_table_id: int = 1
        self._table_ids: Dict[str, int] = {}  # Maps table name to TableId
        
        # Track which merged tables depend on which source tables
        self._merged_table_dependencies: Dict[str, List[str]] = {}  # merged_name -> [source_names]
        
        # Counter for auto-naming merged tables
        self._next_merged_ordinal: int = 1
        
        # Cache for drillhole objects
        self.drillholes: Dict[str, 'Drillhole'] = {}
        
        # Track orphaned interval data (holeids not in collar table)
        self._orphaned_interval_data: Dict[str, List[str]] = {}
        
        # Reverse mapping for code to holeid
        self._code_to_holeid: Dict[int, str] = {v: k for k, v in self._holeid_to_code.items()}
        
        # Validate if requested
        if validate:
            self._validate_database()
        
        print(f"✓ DrillholeDatabase initialized with {len(self.get_holeid_list())} drillholes")
    
    def _get_default_collar_mapping(self) -> Dict[str, List[str]]:
        """Get default column name mappings for collar data."""
        return {
            'holeid': ['HOLEID', 'holeid', 'HOLE_ID', 'HoleID', 'hole_id'],
            'x': ['EAST', 'east', 'X', 'x', 'EASTING', 'easting'],
            'y': ['NORTH', 'north', 'Y', 'y', 'NORTHING', 'northing'],
            'z': ['RL', 'rl', 'Z', 'z', 'ELEVATION', 'elevation', 'ELEV', 'elev'],
            'depth': ['DEPTH', 'depth', 'MAX_DEPTH', 'max_depth', 'TOTAL_DEPTH']
        }
    
    def _get_default_survey_mapping(self) -> Dict[str, List[str]]:
        """Get default column name mappings for survey data."""
        return {
            'holeid': ['HOLEID', 'holeid', 'HOLE_ID', 'HoleID', 'hole_id'],
            'depth': ['DEPTH', 'depth', 'MD', 'md', 'MEASURED_DEPTH'],
            'dip': ['DIP', 'dip', 'INCLINATION', 'inclination', 'INC', 'inc'],
            'azimuth': ['AZIMUTH', 'azimuth', 'BEARING', 'bearing', 'AZ', 'az', 'AZIM']
        }
    
    def _find_column(self, df: pd.DataFrame, candidates: List[str]) -> Optional[str]:
        """Find the first matching column name from a list of candidates."""
        for candidate in candidates:
            if candidate in df.columns:
                return candidate
        return None
    
    def _standardize_collar_data(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Standardize collar data column names while preserving all original columns.
        Required columns: holeid, x, y, z, depth
        All other columns are preserved as additional columns.
        """
        df = df.copy()
        
        # Define required columns
        required_cols = ['holeid', 'x', 'y', 'z', 'depth']
        
        # Create mapping of found columns
        rename_map = {}
        found_originals = {}  # Track which original columns were mapped
        
        for std_name, candidates in self.collar_mapping.items():
            found_col = self._find_column(df, candidates)
            if found_col:
                rename_map[found_col] = std_name
                found_originals[found_col] = std_name
        
        # Check for required columns
        missing = [col for col in required_cols if col not in rename_map.values()]
        if missing:
            raise ValueError(
                f"Missing required collar columns: {missing}\n"
                f"Available columns: {list(df.columns)}\n"
                f"Use collar_columns parameter to specify custom mappings."
            )
        
        # Handle conflicts: if a calculated column name exists in additional columns
        calculated_cols = required_cols  # These will be created/standardized
        for col in df.columns:
            if col not in found_originals and col in calculated_cols:
                # Rename conflicting additional column
                rename_map[col] = f"{col}_original"
        
        # Rename columns
        df = df.rename(columns=rename_map)
        
        # Reorder: required columns first, then additional columns
        additional_cols = [col for col in df.columns if col not in required_cols]
        final_cols = required_cols + additional_cols
        
        return df[final_cols]
    
    def _standardize_survey_data(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Standardize survey data column names while preserving all original columns.
        Required columns: holeid, depth, dip, azimuth
        Calculated columns: dogleg_severity, ignored (added later)
        All other columns are preserved as additional columns.
        """
        df = df.copy()
        
        # Define required columns
        required_cols = ['holeid', 'depth', 'dip', 'azimuth']
        
        # Create mapping of found columns
        rename_map = {}
        found_originals = {}  # Track which original columns were mapped
        
        for std_name, candidates in self.survey_mapping.items():
            found_col = self._find_column(df, candidates)
            if found_col:
                rename_map[found_col] = std_name
                found_originals[found_col] = std_name
        
        # Check for required columns
        missing = [col for col in required_cols if col not in rename_map.values()]
        if missing:
            raise ValueError(
                f"Missing required survey columns: {missing}\n"
                f"Available columns: {list(df.columns)}\n"
                f"Use survey_columns parameter to specify custom mappings."
            )
        
        # Handle conflicts: if a calculated column name exists in additional columns
        calculated_cols = required_cols + ['dogleg_severity', 'ignored']
        for col in df.columns:
            if col not in found_originals and col in calculated_cols:
                # Rename conflicting additional column
                rename_map[col] = f"{col}_original"
        
        # Rename columns
        df = df.rename(columns=rename_map)
        
        # Sort by holeid and depth
        df = df.sort_values(['holeid', 'depth'])
        
        # Reorder: required columns first, then additional columns
        additional_cols = [col for col in df.columns if col not in required_cols]
        final_cols = required_cols + additional_cols
        
        return df[final_cols]
    
    def _validate_database(self):
        """Validate the database integrity."""
        # Check for holes in collar but not in survey
        collar_holes = set(self.collar_data['holeid'].unique())
        survey_holes = set(self.survey_data['holeid'].unique())
        
        missing_survey = collar_holes - survey_holes
        if missing_survey:
            warnings.warn(
                f"Holes in collar data but missing survey data: {missing_survey}"
            )
        
        missing_collar = survey_holes - collar_holes
        if missing_collar:
            warnings.warn(
                f"Holes in survey data but missing collar data: {missing_collar}"
            )
    
    def _calculate_and_add_dogleg_severity(self):
        """
        Calculate dogleg severity for all survey data and add ignored mask.
        Adds two calculated columns to survey_data:
        - dogleg_severity: degrees per 30 meters
        - ignored: boolean mask (True if dogleg_severity > threshold)
        
        Uses vectorized operations for improved performance.
        """
        survey = self.survey_data.copy()
        # ############################
        # # Sort to ensure proper ordering
        # survey = survey.sort_values(['holeid', 'depth']).reset_index(drop=True)
        
        # # Convert angles to radians
        # dip_rad = np.radians(survey['dip'].values)
        # azimuth_rad = np.radians(survey['azimuth'].values)
        # depths = survey['depth'].values
        
        # # Calculate differences between consecutive points
        # dip_diff = np.diff(dip_rad)
        # azi_diff = np.diff(azimuth_rad)
        # depth_diff = np.diff(depths)
        
        # # Get arrays for current and next points
        # dip1 = dip_rad[:-1]
        # dip2 = dip_rad[1:]
        # azi1 = azimuth_rad[:-1]
        # azi2 = azimuth_rad[1:]
        
        # # Vectorized dogleg calculation
        # cos_dogleg = (np.cos(dip2 - dip1) - 
        #              np.sin(dip1) * np.sin(dip2) * (1 - np.cos(azi2 - azi1)))
        # cos_dogleg = np.clip(cos_dogleg, -1.0, 1.0)
        # dogleg_rad = np.arccos(cos_dogleg)
        
        # # Convert to degrees per 30m
        # # Avoid division by zero
        # dogleg_severity = np.where(
        #     depth_diff > 0,
        #     np.degrees(dogleg_rad) * 30.0 / depth_diff,
        #     0.0
        # )
        
        # # Check for hole boundaries (where holeid changes)
        # holeid_changes = survey['holeid'].values[:-1] != survey['holeid'].values[1:]
        
        # # Set dogleg to 0 at hole boundaries
        # dogleg_severity[holeid_changes] = 0.0
        
        # # Prepend 0 for first point of each hole (no previous point to compare)
        # survey['dogleg_severity'] = np.concatenate([[0.0], dogleg_severity])
        
        # # Add ignored mask based on threshold
        # survey['ignored'] = survey['dogleg_severity'] > self.dogleg_threshold
        # ######################################
        ############################
        # Sort to ensure proper ordering
        survey = survey.sort_values(['holeid', 'depth']).reset_index(drop=True)

        vecs =dip_az_to_unit_vector(survey['dip'].values, survey['azimuth'].values)
        depth_diff = np.diff(survey['depth'].values)

        dogleg_severity = np.where(
            depth_diff > 0,
            np.degrees(np.arccos(np.sum(vecs[:-1]*vecs[1:], axis=1)))*30/depth_diff,
            0.0
        )

        # Check for hole boundaries (where holeid changes)
        holeid_changes = survey['holeid'].values[:-1] != survey['holeid'].values[1:]

        # Set dogleg to 0 at hole boundaries
        dogleg_severity[holeid_changes] = 0.0

        # Prepend 0 for first point of each hole (no previous point to compare)
        survey['dogleg_severity'] = np.concatenate([[0.0], dogleg_severity])

        # Add ignored mask based on threshold
        survey['ignored'] = survey['dogleg_severity'] > self.dogleg_threshold
        ######################################
        # Update the survey_data
        self.survey_data = survey
        
        # Report statistics
        n_ignored = survey['ignored'].sum()
        if n_ignored > 0:
            max_dogleg = survey['dogleg_severity'].max()
            print(f"  Warning: {n_ignored} survey points exceed dogleg threshold ({self.dogleg_threshold}°/30m)")
            print(f"  Maximum dogleg severity: {max_dogleg:.2f}°/30m")
    
    def _build_all_trajectories(self):
        """
        Build trajectory lookup table for all holes at initialization.
        
        FULLY VECTORIZED: Processes ALL drillholes simultaneously using pandas groupby
        and vectorized numpy operations. No loops over holes.
        
        Pre-calculates minimum curvature parameters for each survey interval across
        ALL drillholes and stores in a single DataFrame for maximum vectorization.
        
        Creates self._interval_params DataFrame with columns:
        - holeid: Drillhole identifier
        - from_depth, to_depth: Interval bounds
        - x0, y0, z0: Starting position for interval
        - dip1, dip2, azi1, azi2: Survey angles (radians)
        - rf: Ratio factor for minimum curvature
        - md_diff: Measured depth difference
        
        Also creates self._collar_positions for before-first-station lookups.
        """
        # Prepare collar positions lookup (vectorized)
        self._collar_positions = self.collar_data[['holeid', 'x', 'y', 'z']].rename(
            columns={'x': 'collar_x', 'y': 'collar_y', 'z': 'collar_z'}
        ).copy()
        self._collar_positions['first_depth'] = 0.0
        
        # Work with survey data
        survey = self.survey_data.copy()

        #Avoids errors on reruns
        survey.drop(columns=['x', 'y', 'z'], inplace=True, errors='ignore')
        
        # Filter ignored survey points
        if 'ignored' in survey.columns:
            survey = survey[~survey['ignored']].copy()
        
        if len(survey) == 0:
            self._interval_params = pd.DataFrame()
            return
        
        # Ensure each hole starts at depth 0 (vectorized)
        # Get first survey point per hole
        first_surveys = survey.groupby('holeid').first().reset_index()
        first_surveys['depth'] = 0.0
        
        # Remove any existing depth 0 rows to avoid duplicates
        survey = survey[survey['depth'] != 0.0]
        
        # Add depth 0 rows
        survey = pd.concat([first_surveys[['holeid', 'depth', 'dip', 'azimuth']], survey], 
                          ignore_index=True)
        
        # Sort by holeid and depth
        survey = survey.sort_values(['holeid', 'depth']).reset_index(drop=True)
        
        # Convert angles to radians
        survey['dip_rad'] = np.radians(survey['dip'])
        survey['azi_rad'] = np.radians(survey['azimuth'])
        
        # Merge collar positions
        survey = survey.merge(
            self.collar_data[['holeid', 'x', 'y', 'z']],
            on='holeid',
            how='left'
        )
        
        # Create shifted columns for interval endpoints (vectorized)
        survey['next_depth'] = survey.groupby('holeid')['depth'].shift(-1)
        survey['next_dip'] = survey.groupby('holeid')['dip'].shift(-1)
        survey['next_azimuth'] = survey.groupby('holeid')['azimuth'].shift(-1)
        survey['next_dip_rad'] = survey.groupby('holeid')['dip_rad'].shift(-1)
        survey['next_azi_rad'] = survey.groupby('holeid')['azi_rad'].shift(-1)
        
        # Remove last row of each hole (no next point)
        intervals = survey[survey['next_depth'].notna()].copy()
        
        # Calculate interval parameters for multi-station holes (all vectorized)
        if len(intervals) > 0:
            intervals['md_diff'] = intervals['next_depth'] - intervals['depth']
            
            # Dogleg calculation (vectorized)
            # Using Haversine formula for better numerical stability with small angles
            dip1 = intervals['dip_rad'].values
            dip2 = intervals['next_dip_rad'].values
            azi1 = intervals['azi_rad'].values
            azi2 = intervals['next_azi_rad'].values
            
            # a = (np.sin((dip2 - dip1) / 2)**2 + 
            #      np.sin(dip1) * np.sin(dip2) * np.sin((azi2 - azi1) / 2)**2)
            # dogleg = 2 * np.arcsin(np.sqrt(np.clip(a, 0, 1)))
            
            # Convert to unit vectors
            v1 = dip_az_to_unit_vector(dip1, azi1)
            v2 = dip_az_to_unit_vector(dip2, azi2)

            # Row-wise dot product
            dot = np.einsum('ij,ij->i', v1, v2)

            # Numerical safety
            dot = np.clip(dot, -1.0, 1.0)


            # Dogleg angle (radians)
            dogleg = np.arccos(dot)
            
            # Ratio factor for minimum curvature
            intervals['rf'] = np.where(
                dogleg < 1e-6,
                1.0,
                2 / dogleg * np.tan(dogleg / 2)
            )
            
            # Calculate increments using minimum curvature (vectorized)
            md_diff = intervals['md_diff'].values
            rf = intervals['rf'].values
            
            # Horizontal components (northing)
            dn1 = md_diff / 2 * np.cos(dip1) * np.cos(azi1)
            dn2 = md_diff / 2 * np.cos(dip2) * np.cos(azi2)
            delta_n = (dn1 + dn2) * rf
            
            # Horizontal components (easting)
            de1 = md_diff / 2 * np.cos(dip1) * np.sin(azi1)
            de2 = md_diff / 2 * np.cos(dip2) * np.sin(azi2)
            delta_e = (de1 + de2) * rf
            
            # Vertical components
            dv1 = md_diff / 2 * np.sin(dip1)
            dv2 = md_diff / 2 * np.sin(dip2)
            delta_v = (dv1 + dv2) * rf
            
            # Handle zero or negative depth differences
            valid_increments = md_diff > 0
            intervals['delta_e'] = np.where(valid_increments, delta_e, 0.0)
            intervals['delta_n'] = np.where(valid_increments, delta_n, 0.0)
            intervals['delta_v'] = np.where(valid_increments, delta_v, 0.0)
            
            # Cumulative sum per hole to get coordinates (vectorized groupby)
            intervals['x_cum'] = intervals['x'] + intervals.groupby('holeid')['delta_e'].cumsum()
            intervals['y_cum'] = intervals['y'] + intervals.groupby('holeid')['delta_n'].cumsum()
            intervals['z_cum'] = intervals['z'] - intervals.groupby('holeid')['delta_v'].cumsum()
            
            # Calculate starting positions (shift back by one within each hole)
            intervals['x0'] = intervals.groupby('holeid')['x_cum'].shift(1).fillna(intervals['x'])
            intervals['y0'] = intervals.groupby('holeid')['y_cum'].shift(1).fillna(intervals['y'])
            intervals['z0'] = intervals.groupby('holeid')['z_cum'].shift(1).fillna(intervals['z'])
        
        # Handle single-station holes (holes with no intervals after removing last row)
        # For these holes, create a single interval from 0 to infinity
        holes_with_intervals = intervals['holeid'].unique()
        all_holes = survey['holeid'].unique()
        single_station_holes = [h for h in all_holes if h not in holes_with_intervals]
        
        if len(single_station_holes) > 0:
            # Get the single survey point for each of these holes
            single_station_data = survey[survey['holeid'].isin(single_station_holes)].copy()
            single_station_data['from_depth'] = 0.0
            single_station_data['to_depth'] = np.inf
            single_station_data['x0'] = single_station_data['x']
            single_station_data['y0'] = single_station_data['y']
            single_station_data['z0'] = single_station_data['z']
            single_station_data['last_x'] = single_station_data['x']
            single_station_data['last_y'] = single_station_data['y']
            single_station_data['last_z'] = single_station_data['z']
            single_station_data['dip1'] = single_station_data['dip_rad']
            single_station_data['dip2'] = single_station_data['dip_rad']
            single_station_data['azi1'] = single_station_data['azi_rad']
            single_station_data['azi2'] = single_station_data['azi_rad']
            single_station_data['dip1_deg'] = single_station_data['dip']
            single_station_data['dip2_deg'] = single_station_data['dip']
            single_station_data['azi1_deg'] = single_station_data['azimuth']
            single_station_data['azi2_deg'] = single_station_data['azimuth']
            single_station_data['rf'] = 1.0
            single_station_data['md_diff'] = np.inf
            
            single_station_intervals = single_station_data[[
                'holeid', 'from_depth', 'to_depth', 'x0', 'y0', 'z0',
                'dip1', 'dip2', 'azi1', 'azi2', 'dip1_deg', 'dip2_deg', 'azi1_deg', 'azi2_deg',
                'rf', 'md_diff', 'last_x', 'last_y', 'last_z'
            ]]
            
            # Add to intervals
            if len(intervals) > 0:
                intervals = pd.concat([intervals[[
                    'holeid', 'depth', 'next_depth', 'x0', 'y0', 'z0',
                    'dip_rad', 'next_dip_rad', 'azi_rad', 'next_azi_rad',
                    'dip', 'next_dip', 'azimuth', 'next_azimuth',
                    'rf', 'md_diff', 'x_cum', 'y_cum', 'z_cum'
                ]].rename(columns={
                    'depth': 'from_depth',
                    'next_depth': 'to_depth',
                    'dip_rad': 'dip1',
                    'next_dip_rad': 'dip2',
                    'azi_rad': 'azi1',
                    'next_azi_rad': 'azi2',
                    'dip': 'dip1_deg',
                    'next_dip': 'dip2_deg',
                    'azimuth': 'azi1_deg',
                    'next_azimuth': 'azi2_deg',
                    'x_cum': 'last_x',
                    'y_cum': 'last_y',
                    'z_cum': 'last_z'
                }), single_station_intervals], ignore_index=True)
                self._interval_params = intervals
            else:
                self._interval_params = single_station_intervals
        else:
            # Build final interval parameters dataframe
            self._interval_params = intervals[[
                'holeid', 'depth', 'next_depth', 'x0', 'y0', 'z0',
                'dip_rad', 'next_dip_rad', 'azi_rad', 'next_azi_rad',
                'dip', 'next_dip', 'azimuth', 'next_azimuth',
                'rf', 'md_diff', 'x_cum', 'y_cum', 'z_cum'
            ]].rename(columns={
                'depth': 'from_depth',
                'next_depth': 'to_depth',
                'dip_rad': 'dip1',
                'next_dip_rad': 'dip2',
                'azi_rad': 'azi1',
                'next_azi_rad': 'azi2',
                'dip': 'dip1_deg',
                'next_dip': 'dip2_deg',
                'azimuth': 'azi1_deg',
                'next_azimuth': 'azi2_deg',
                'x_cum': 'last_x',
                'y_cum': 'last_y',
                'z_cum': 'last_z'
            }).copy()
        
        if len(self._interval_params) == 0:
            return
        
        # Add synthetic intervals for extrapolation (only for multi-station holes)
        # 1. Add interval from last survey depth to infinity (for extrapolation beyond last station)
        # Only for holes that don't already have an infinite interval (i.e., multi-station holes)
        last_intervals = self._interval_params.groupby('holeid').last().reset_index()
        needs_infinity = last_intervals['to_depth'] != np.inf
        
        if needs_infinity.sum() > 0:
            infinity_intervals = last_intervals[needs_infinity].copy()
            infinity_intervals['from_depth'] = infinity_intervals['to_depth']
            infinity_intervals['to_depth'] = np.inf
            infinity_intervals['x0'] = infinity_intervals['last_x']
            infinity_intervals['y0'] = infinity_intervals['last_y']
            infinity_intervals['z0'] = infinity_intervals['last_z']
            # Keep same angles for extrapolation (dip1=dip2, azi1=azi2)
            infinity_intervals['dip1'] = infinity_intervals['dip2']
            infinity_intervals['azi1'] = infinity_intervals['azi2']
            infinity_intervals['dip1_deg'] = infinity_intervals['dip2_deg']
            infinity_intervals['azi1_deg'] = infinity_intervals['azi2_deg']
            infinity_intervals['rf'] = 1.0  # No curvature for straight extrapolation
            infinity_intervals['md_diff'] = np.inf
            
            # Combine with infinity intervals
            infinity_intervals = infinity_intervals[[
                'holeid', 'from_depth', 'to_depth', 'x0', 'y0', 'z0',
                'dip1', 'dip2', 'azi1', 'azi2', 'dip1_deg', 'dip2_deg', 'azi1_deg', 'azi2_deg',
                'rf', 'md_diff', 'last_x', 'last_y', 'last_z'
            ]]
            self._interval_params = pd.concat([self._interval_params, infinity_intervals], ignore_index=True)
        
        # 2. Add interval from 0 to first survey depth if first interval doesn't start at 0
        first_intervals = self._interval_params.groupby('holeid').first().reset_index()
        needs_zero_interval = first_intervals['from_depth'] > 0
        
        if needs_zero_interval.sum() > 0:
            zero_intervals = first_intervals[needs_zero_interval].copy()
            zero_intervals['to_depth'] = zero_intervals['from_depth']
            zero_intervals['from_depth'] = 0.0
            zero_intervals['last_x'] = zero_intervals['x0']
            zero_intervals['last_y'] = zero_intervals['y0']
            zero_intervals['last_z'] = zero_intervals['z0']
            # Get collar positions for x0, y0, z0
            zero_intervals = zero_intervals.merge(
                self.collar_data[['holeid', 'x', 'y', 'z']],
                on='holeid',
                how='left',
                suffixes=('', '_collar')
            )
            zero_intervals['x0'] = zero_intervals['x']
            zero_intervals['y0'] = zero_intervals['y']
            zero_intervals['z0'] = zero_intervals['z']
            # Keep same angles for extrapolation (dip1=dip2, azi1=azi2)
            zero_intervals['dip2'] = zero_intervals['dip1']
            zero_intervals['azi2'] = zero_intervals['azi1']
            zero_intervals['dip2_deg'] = zero_intervals['dip1_deg']
            zero_intervals['azi2_deg'] = zero_intervals['azi1_deg']
            zero_intervals['rf'] = 1.0
            
            # Select only needed columns
            zero_intervals = zero_intervals[[
                'holeid', 'from_depth', 'to_depth', 'x0', 'y0', 'z0',
                'dip1', 'dip2', 'azi1', 'azi2', 'dip1_deg', 'dip2_deg', 'azi1_deg', 'azi2_deg',
                'rf', 'md_diff', 'last_x', 'last_y', 'last_z'
            ]]
            
            # Combine with main intervals
            self._interval_params = pd.concat([self._interval_params, zero_intervals], ignore_index=True)
        
        # Create holeid-to-numeric mapping for monotonic sorting
        # Include ALL holes from collar data, not just those with intervals
        all_holeids = self.collar_data['holeid'].unique()
        self._holeid_to_code = {holeid: (i + 1) * 1000000 for i, holeid in enumerate(all_holeids)}
        
        # Add numeric hole code for monotonic depth sorting
        self._interval_params['_hole_code'] = self._interval_params['holeid'].map(self._holeid_to_code)
        self._interval_params['_monotonic_from'] = self._interval_params['_hole_code'] + self._interval_params['from_depth']
        
        # Sort by monotonic_from for merge_asof (critical!)
        self._interval_params = self._interval_params.sort_values('_monotonic_from').reset_index(drop=True)
    
    def desurvey_point_data(
        self,
        point_data: pd.DataFrame,
        depth_column: str = 'depth',
        filter_column: Optional[str] = None,
    ) -> pd.DataFrame:
        """
        Desurvey any point data using pre-calculated minimum curvature trajectories.
        
        Adds x, y, z coordinate columns to the DataFrame.
        This method works with any point dataset including survey data, geophysics logs,
        structural data, sample points, etc.
        
        FULLY VECTORIZED: Processes all points across all holes simultaneously
        by merging with pre-calculated interval parameters DataFrame.
        
        Uses proper minimum curvature interpolation with cached interval parameters.
        
        Parameters:
            point_data (pd.DataFrame): Point data with holeid and depth columns
            depth_column (str): Name of the depth column (default 'depth')
            filter_column (str, optional): Column to filter points
                Points where this column is True will get NaN coordinates
        
        Returns:
            pd.DataFrame: Point data with x, y, z columns added
        
        Example:
            >>> # Desurvey gamma log data
            >>> gamma_data = pd.DataFrame({
            ...     'holeid': ['PB-01', 'PB-01', 'PB-02'],
            ...     'depth': [10.0, 20.0, 15.0],
            ...     'gamma_cps': [150, 180, 200]
            ... })
            >>> gamma_xyz = db.desurvey_point_data(gamma_data)
        """
        data = point_data.copy()
        
        # Initialize coordinate arrays with NaN
        data['x'] = np.nan
        data['y'] = np.nan
        data['z'] = np.nan
        data[depth_column] = data[depth_column].astype(float)
        
        # Create filter mask
        if filter_column and filter_column in data.columns:
            valid_mask = ~data[filter_column]
        else:
            valid_mask = pd.Series(True, index=data.index)
        
        # Filter to valid points (not filtered, with valid holeid and depth)
        valid_mask = valid_mask & data['holeid'].notna() & data[depth_column].notna()
        valid_data = data[valid_mask].copy()
        
        if len(valid_data) == 0:
            return data
        
        # Merge with interval parameters to find which interval each point belongs to
        # Store original indices before sorting
        valid_data['_original_index'] = data.index[valid_mask].values
        
        # Create monotonic depth column using hole codes
        valid_data['_hole_code'] = valid_data['holeid'].map(self._holeid_to_code)
        
        # Filter out any points with holes not in the mapping (safety check)
        has_hole_code = valid_data['_hole_code'].notna()
        if not has_hole_code.all():
            missing_holes = valid_data.loc[~has_hole_code, 'holeid'].unique()
            warnings.warn(f"Skipping {(~has_hole_code).sum()} points from holes not in database: {missing_holes[:5]}")
            valid_data = valid_data[has_hole_code].copy()
        
        if len(valid_data) == 0:
            return data
        
        valid_data['_monotonic_depth'] = valid_data['_hole_code'] + valid_data[depth_column]
        
        # Sort by monotonic depth column (this ensures left keys are sorted)
        valid_data = valid_data.sort_values('_monotonic_depth').reset_index(drop=True)
        
        # Merge_asof using monotonic depth columns (no 'by' parameter needed)
        merged = pd.merge_asof(
            valid_data,
            self._interval_params,
            left_on='_monotonic_depth',
            right_on='_monotonic_from',
            direction='backward',
            suffixes=('', '_interval')
        )
        
        # Filter to ensure we matched the correct hole (comparing hole codes, not just holeid)
        # For rows where hole codes don't match, set interval columns to NaN (treat as no match)
        if 'holeid_interval' in merged.columns and '_hole_code_interval' in merged.columns:
            # Compare hole codes for exact hole matching
            wrong_hole = (merged['_hole_code'] != merged['_hole_code_interval']) & merged['holeid_interval'].notna()
            if wrong_hole.sum() > 0:
                # Set interval columns to NaN for wrong-hole matches
                interval_cols = [col for col in merged.columns if col.endswith('_interval') or col in ['from_depth', 'to_depth', 'x0', 'y0', 'z0', 'dip1', 'dip2', 'azi1', 'azi2', 'rf', 'md_diff', 'last_x', 'last_y', 'last_z']]
                merged.loc[wrong_hole, interval_cols] = np.nan
        
        # All points should have an interval now (including synthetic intervals for 0 and infinity)
        # Just apply minimum curvature formula for all valid matches
        has_interval = merged['from_depth'].notna()
        
        if has_interval.sum() > 0:
            range_data = merged[has_interval]
            
            # Calculate position within interval (vectorized)
            md_target = range_data[depth_column].values - range_data['from_depth'].values
            md_diff = range_data['md_diff'].values
            
            # Handle infinite md_diff (extrapolation intervals)
            finite_diff = np.isfinite(md_diff)
            fraction = np.where(finite_diff & (md_diff > 0), md_target / md_diff, 0.0)
            
            # Interpolate angles (vectorized)
            dip_interp = range_data['dip1'].values + fraction * (range_data['dip2'].values - range_data['dip1'].values)
            azi_interp = range_data['azi1'].values + fraction * (range_data['azi2'].values - range_data['azi1'].values)
            
            # Extract interval parameters (all arrays)
            rf = range_data['rf'].values
            dip1 = range_data['dip1'].values
            dip2 = range_data['dip2'].values
            azi1 = range_data['azi1'].values
            azi2 = range_data['azi2'].values
            x0 = range_data['x0'].values
            y0 = range_data['y0'].values
            z0 = range_data['z0'].values
            
            # Minimum curvature calculation (fully vectorized)
            dn = md_target * (np.cos(dip1) * np.cos(azi1) + np.cos(dip2) * np.cos(azi2)) / 2 * rf
            de = md_target * (np.cos(dip1) * np.sin(azi1) + np.cos(dip2) * np.sin(azi2)) / 2 * rf
            dv = md_target * (np.sin(dip1) + np.sin(dip2)) / 2 * rf
            
            # Calculate final positions
            merged.loc[has_interval, 'x'] = x0 + de
            merged.loc[has_interval, 'y'] = y0 + dn
            merged.loc[has_interval, 'z'] = z0 - dv
        
        # Map results back to original DataFrame using direct array assignment
        # This is much faster than .loc[array_of_indices] for large datasets
        valid_positions = np.arange(len(data))
        update_positions = valid_positions[merged['_original_index'].values]
        data['x'].values[update_positions] = merged['x'].values
        data['y'].values[update_positions] = merged['y'].values
        data['z'].values[update_positions] = merged['z'].values
        
        return data
    
    def desurvey_interval_data(
        self,
        interval_data: pd.DataFrame,
        from_column: str = 'from',
        to_column: str = 'to'
    ) -> pd.DataFrame:
        """
        Desurvey any interval data using minimum curvature method.
        
        Adds top_x, top_y, top_z, mid_x, mid_y, mid_z, bottom_x, bottom_y, bottom_z
        columns to the DataFrame.
        This method works with any interval dataset including assays, lithology,
        geotechnical data, etc.
        
        OPTIMIZED: Uses a single desurveying pass for all three points (top, mid, bottom)
        instead of three separate passes, providing ~3x performance improvement.
        
        Parameters:
            interval_data (pd.DataFrame): Interval data with holeid, from, and to columns
            from_column (str): Name of the 'from' depth column (default 'from')
            to_column (str): Name of the 'to' depth column (default 'to')
        
        Returns:
            pd.DataFrame: Interval data with top/mid/bottom xyz columns added
        
        Example:
            >>> # Desurvey assay data
            >>> assay_data = pd.DataFrame({
            ...     'holeid': ['PB-01', 'PB-01', 'PB-02'],
            ...     'from': [0.0, 10.0, 0.0],
            ...     'to': [10.0, 20.0, 15.0],
            ...     'Au_ppm': [0.5, 1.2, 0.8]
            ... })
            >>> assay_xyz = db.desurvey_interval_data(assay_data)
        """
        data = interval_data.copy()
        n_intervals = len(data)
        
        # Calculate midpoint depths
        mid_depths = (data[from_column] + data[to_column]) / 2
        
        # Create a stacked DataFrame with all points (top, mid, bottom) for single desurvey pass
        # This is ~3x faster than calling desurvey_point_data three separate times
        all_points = pd.DataFrame({
            'holeid': np.repeat(data['holeid'].values, 3),
            'depth': np.concatenate([
                data[from_column].values,      # Top points (indices 0, 3, 6, ...)
                mid_depths.values,              # Mid points (indices 1, 4, 7, ...)
                data[to_column].values          # Bottom points (indices 2, 5, 8, ...)
            ]),
            '_point_type': np.tile(['top', 'mid', 'bottom'], n_intervals),  # For debugging/verification
            '_original_index': np.repeat(np.arange(n_intervals), 3)  # Track original row
        })
        
        # Single desurveying pass for all points
        all_desurveyed = self.desurvey_point_data(all_points, depth_column='depth')
        
        # Reshape results back to separate top/mid/bottom columns
        # Use direct indexing since we know the pattern: top=0,3,6..., mid=1,4,7..., bottom=2,5,8...
        top_indices = np.arange(0, len(all_desurveyed), 3)
        mid_indices = np.arange(1, len(all_desurveyed), 3)
        bottom_indices = np.arange(2, len(all_desurveyed), 3)
        
        # Add coordinates to interval data (direct array assignment for speed)
        data['top_x'] = all_desurveyed['x'].iloc[top_indices].values
        data['top_y'] = all_desurveyed['y'].iloc[top_indices].values
        data['top_z'] = all_desurveyed['z'].iloc[top_indices].values
        
        data['mid_x'] = all_desurveyed['x'].iloc[mid_indices].values
        data['mid_y'] = all_desurveyed['y'].iloc[mid_indices].values
        data['mid_z'] = all_desurveyed['z'].iloc[mid_indices].values
        
        data['bottom_x'] = all_desurveyed['x'].iloc[bottom_indices].values
        data['bottom_y'] = all_desurveyed['y'].iloc[bottom_indices].values
        data['bottom_z'] = all_desurveyed['z'].iloc[bottom_indices].values
        
        return data
    
    def _desurvey_all_survey_data(self):
        """
        Desurvey all survey data using minimum curvature method.
        Adds calculated columns to survey_data:
        - x, y, z: 3D coordinates at each survey station
        
        Filters out ignored points before desurveying.
        """
        # Use the public desurveying method
        self.survey_data = self.desurvey_point_data(
            self.survey_data,
            depth_column='depth',
            filter_column='ignored'
        )
        
        # Report statistics
        n_desurveyed = self.survey_data['x'].notna().sum()
        n_total = len(self.survey_data)
        print(f"  Desurveyed {n_desurveyed:,} survey points ({n_total - n_desurveyed:,} ignored)")

    
    def get_holeid_list(self) -> List[str]:
        """
        Get list of all drillhole IDs in the database.
        
        Returns:
            List of holeid strings
        """
        collar_holes = set(self.collar_data['holeid'].unique())
        survey_holes = set(self.survey_data['holeid'].unique())
        return sorted(collar_holes & survey_holes)
    
    def get_drillhole(self, holeid: str, use_cache: bool = True) -> 'Drillhole':
        """
        Get a Drillhole object for a specific holeid.
        
        Parameters:
            holeid (str): Drillhole identifier
            use_cache (bool): Whether to use cached drillhole object
            
        Returns:
            Drillhole: Drillhole object with trace calculated
            
        Raises:
            ValueError: If holeid not found in database
        """
        if holeid not in self.get_holeid_list():
            raise ValueError(
                f"Holeid '{holeid}' not found in database.\n"
                f"Available holes: {self.get_holeid_list()[:10]}..."
            )
        
        # Return cached version if available
        if use_cache and holeid in self.drillholes:
            return self.drillholes[holeid]
        
        # Create trajectory dict for this hole from DataFrames
        trajectory = None
        if len(self._interval_params) > 0:
            hole_intervals = self._interval_params[self._interval_params['holeid'] == holeid]
            hole_collar = self._collar_positions[self._collar_positions['holeid'] == holeid]
            
            if len(hole_intervals) > 0 and len(hole_collar) > 0:
                # Build trajectory dict from DataFrame rows
                intervals = hole_intervals.to_dict('records')
                
                # Extract survey station info from intervals
                depths = [intervals[0]['from_depth']]
                depths.extend([iv['to_depth'] for iv in intervals])
                
                # Build dip and azimuth arrays from intervals
                dip_rad = [intervals[0]['dip1']]
                dip_rad.extend([iv['dip2'] for iv in intervals])
                azi_rad = [intervals[0]['azi1']]
                azi_rad.extend([iv['azi2'] for iv in intervals])
                
                # Build cumulative coordinate arrays
                x_cum = [intervals[0]['x0']]
                x_cum.extend([iv['last_x'] for iv in intervals])
                y_cum = [intervals[0]['y0']]
                y_cum.extend([iv['last_y'] for iv in intervals])
                z_cum = [intervals[0]['z0']]
                z_cum.extend([iv['last_z'] for iv in intervals])
                
                # Get collar info
                collar_info = hole_collar.iloc[0]
                
                trajectory = {
                    'collar_x': collar_info['collar_x'],
                    'collar_y': collar_info['collar_y'],
                    'collar_z': collar_info['collar_z'],
                    'depths': np.array(depths),
                    'x': np.array(x_cum),
                    'y': np.array(y_cum),
                    'z': np.array(z_cum),
                    'dip': np.array(dip_rad),
                    'azimuth': np.array(azi_rad),
                    'intervals': intervals
                }
        
        # Create new drillhole object with trajectory cache
        collar = self.collar_data[self.collar_data['holeid'] == holeid].iloc[0]
        survey = self.survey_data[self.survey_data['holeid'] == holeid].copy()
        
        dh = Drillhole(holeid, collar, survey, trajectory=trajectory)
        
        # Add interval data if available
        for name, df in self.interval_data.items():
            if holeid in df['holeid'].values:
                dh.add_interval_data(df, name, validate=False)
        
        # Add point data if available
        for name, df in self.point_data.items():
            if holeid in df['holeid'].values:
                dh.add_point_data(df, name, validate=False)
        
        # Cache and return
        if use_cache:
            self.drillholes[holeid] = dh
        
        return dh
    
    def add_interval_data(
        self,
        data: pd.DataFrame,
        name: str,
        column_mapping: Optional[Dict[str, str]] = None,
        validate: bool = True,
        auto_desurvey: bool = True
    ):
        """
        Add interval data for all drillholes.
        
        Parameters:
            data (pd.DataFrame): Interval data for multiple holes
            name (str): Dataset identifier
            column_mapping (dict, optional): Custom column mappings
                Example: {'holeid': 'HOLE_ID', 'from': 'FROM_M', 'to': 'TO_M'}
            validate (bool): Whether to validate the data
            auto_desurvey (bool): Whether to automatically add xyz coordinates
                (top_x, top_y, top_z, mid_x, mid_y, mid_z, bottom_x, bottom_y, bottom_z).
                Default is True.
        """
        df = data.copy()
        
        # Default interval column mapping
        default_mapping = {
            'holeid': ['HOLEID', 'holeid', 'HOLE_ID', 'hole_id'],
            'from': ['SAMPFROM', 'from', 'FROM', 'depth_from', 'FROM_M'],
            'to': ['SAMPTO', 'to', 'TO', 'depth_to', 'TO_M']
        }
        
        # Apply custom mapping if provided
        if column_mapping:
            for std_name, custom_name in column_mapping.items():
                if isinstance(custom_name, str):
                    default_mapping[std_name] = [custom_name]
        
        # Standardize columns
        rename_map = {}
        for std_name, candidates in default_mapping.items():
            found_col = self._find_column(df, candidates)
            if found_col:
                rename_map[found_col] = std_name
        
        # Check required columns
        required = ['holeid', 'from', 'to']
        missing = [col for col in required if col not in rename_map.values()]
        if missing:
            raise ValueError(f"Missing required interval columns: {missing}")
        
        df = df.rename(columns=rename_map)
        
        # Store original holeid for potential future matching
        df['_original_holeid'] = df['holeid']
        
        # Identify missing holeids
        missing_holeids = set(df['holeid'].unique()) - set(self._holeid_to_code.keys())
        
        if missing_holeids:
            print(f"⚠ Warning: {len(missing_holeids)} holeids in interval data not found in collar table")
            print(f"  Missing: {list(missing_holeids)[:5]}{'...' if len(missing_holeids) > 5 else ''}")
            
            # Assign temporary negative codes to missing holeids
            # This prevents conflicts with existing codes
            # Start at -10M to ensure |code| > 1,000,000
            next_temp_code = -1000000
            temp_code_mapping = {}
            for hid in missing_holeids:
                temp_code_mapping[hid] = next_temp_code
                next_temp_code -= 1000000
            
            # Update the mapping with temporary codes
            self._holeid_to_code.update(temp_code_mapping)
            self._code_to_holeid.update({v: k for k, v in temp_code_mapping.items()})
            
            # Store orphaned holeids for later reconciliation
            self._orphaned_interval_data[name] = list(missing_holeids)
        
        if validate:
            # Check for valid intervals
            invalid = df[df['from'] >= df['to']]
            if len(invalid) > 0:
                warnings.warn(f"Found {len(invalid)} invalid intervals (from >= to)")
        
        # Sort by holeid and from depth
        df = df.sort_values(['holeid', 'from']).reset_index(drop=True)
        
        # Create IntervalIndex using holeid codes + depths for monotonic intervals
        hid_codes = df['holeid'].map(self._holeid_to_code).values
        ii_tuples = [
            tuple(i) 
            for i in list(df[['from', 'to']].values + hid_codes.reshape(-1, 1))
        ]
        df = df.set_index(pd.IntervalIndex.from_tuples(ii_tuples, closed='left'))
        
        # Assign a unique TableId if this is a new table
        if name not in self._table_ids:
            self._table_ids[name] = self._next_table_id
            self._next_table_id += 1
        
        # Store the interval data with IntervalIndex
        self.interval_data[name] = df
        
        # Automatically desurvey if requested
        if auto_desurvey:
            n_intervals = len(df)
            start_time = time.time()
            print(f"  Desurveying {n_intervals:,} intervals in '{name}'...")
            
            self.interval_data[name] = self.desurvey_interval_data(
                self.interval_data[name],
                from_column='from',
                to_column='to'
            )
            
            elapsed = time.time() - start_time
            rate = n_intervals / elapsed if elapsed > 0 else 0
            print(f"    ✓ Desurveyed in {elapsed:.2f}s ({rate:,.0f} intervals/sec)")
        
        # Update any merged tables that depend on this source table
        self._update_dependent_merged_tables(name)
        
        # Clear cache since data changed (but don't rebuild trajectories - not needed for interval data)
        self.drillholes.clear()
        
        table_id = self._table_ids[name]
        print(f"✓ Interval data '{name}' (TableId: {table_id}) added: {len(df)} intervals across {df['holeid'].nunique()} holes")
    
    def _create_sparse_overlap_matrix(self, interval_index: pd.IntervalIndex):
        """
        Create a sparse boolean matrix showing which intervals overlap.
        
        Uses an optimized algorithm that sorts intervals by start position
        and only checks intervals that could possibly overlap, avoiding
        unnecessary comparisons.
        
        Parameters:
            interval_index (pd.IntervalIndex): An IntervalIndex containing the 
                intervals to check for overlaps.
        
        Returns:
            scipy.sparse.csr_matrix: A sparse boolean matrix where element [i,j] 
                is True if interval i overlaps with interval j. The matrix is symmetric.
        
        Notes:
            Two intervals overlap if: left_i < right_j AND left_j < right_i
        """
        num_intervals = len(interval_index)
        
        # Sort intervals by start position for efficiency
        sorted_indices = np.argsort(interval_index.left.values)
        left = interval_index.left.values[sorted_indices]
        right = interval_index.right.values[sorted_indices]
        
        # Use sparse matrix (only store True values)
        sparse_matrix = lil_matrix((num_intervals, num_intervals), dtype=bool)
        
        # For each interval, only check intervals that could possibly overlap
        for i in range(num_intervals):
            # Only check intervals that start before this one ends
            for j in range(i + 1, num_intervals):
                if left[j] >= right[i]:
                    break  # No more possible overlaps
                # Check if they actually overlap
                if left[i] < right[j] and left[j] < right[i]:
                    orig_i = sorted_indices[i]
                    orig_j = sorted_indices[j]
                    sparse_matrix[orig_i, orig_j] = True
                    sparse_matrix[orig_j, orig_i] = True
        
        return sparse_matrix.tocsr()
    
    def _non_overlapping_mask(self, interval_index: pd.IntervalIndex) -> np.ndarray:
        """
        Create a boolean mask indicating which intervals do NOT overlap with any other interval.
        
        Parameters:
            interval_index (pd.IntervalIndex): An IntervalIndex containing the 
                intervals to check.
        
        Returns:
            np.ndarray: A boolean array where True indicates the interval at that 
                position does NOT overlap with any other interval.
        
        Example:
            >>> import pandas as pd
            >>> intervals = pd.IntervalIndex.from_tuples([(0, 5), (3, 8), (10, 15)])
            >>> db._non_overlapping_mask(intervals)
            array([False, False, True])  # Only the third interval doesn't overlap
        """
        sparse_matrix = self._create_sparse_overlap_matrix(interval_index)
        
        # An interval is non-overlapping if it has no non-zero entries in its row
        no_overlap_mask = np.array(sparse_matrix.sum(axis=1)).flatten() == 0
        
        return no_overlap_mask
    
    def _max_disjoint_mask(self, interval_index: pd.IntervalIndex) -> np.ndarray:
        """
        Create a boolean mask for the maximum disjoint set of intervals.
        
        Uses a greedy algorithm that selects intervals finishing earliest first.
        This approach guarantees finding a maximal (though not necessarily maximum)
        disjoint set efficiently.
        
        Parameters:
            interval_index (pd.IntervalIndex): An IntervalIndex containing the 
                intervals to process.
        
        Returns:
            np.ndarray: A boolean array where True indicates the interval at that 
                position is part of the maximum disjoint set.
        
        Notes:
            The greedy algorithm works by:
            1. Sorting intervals by their end position (right boundary)
            2. Selecting intervals that don't overlap with previously selected ones
            3. An interval is selected if its start >= the end of the last selected interval
        
        Example:
            >>> import pandas as pd
            >>> intervals = pd.IntervalIndex.from_tuples([(0, 10), (5, 15), (10, 20)])
            >>> db._max_disjoint_mask(intervals)
            array([True, False, True])  # Selects first and third intervals
        """
        num_intervals = len(interval_index)
        
        # Sort by end time (finish earliest first) for greedy algorithm
        sorted_indices = np.argsort(interval_index.right.values)
        
        disjoint_set = []
        last_end = -np.inf
        
        for idx in sorted_indices:
            interval = interval_index[idx]
            # If this interval starts after or at the last selected interval's end
            if interval.left >= last_end:
                disjoint_set.append(idx)
                last_end = interval.right
        
        # Create boolean mask
        disjoint_mask = np.zeros(num_intervals, dtype=bool)
        disjoint_mask[disjoint_set] = True
        
        return disjoint_mask
    
    def _fix_overlaps(
        self, 
        table_name: str, 
        max_disjoint: bool = True
    ) -> pd.DataFrame:
        """
        Remove overlapping intervals from an interval data table.
        
        This method provides two strategies for handling overlapping intervals:
        1. Maximum disjoint set (max_disjoint=True): Returns the largest subset of 
           non-overlapping intervals using a greedy algorithm
        2. Non-overlapping only (max_disjoint=False): Returns only intervals that 
           don't overlap with any other interval
        
        Parameters:
            table_name (str): Name of the interval data table in self.interval_data
            max_disjoint (bool): If True, returns maximum disjoint set (greedy algorithm).
                If False, returns only intervals that don't overlap with any others.
                Default is True.
        
        Returns:
            pd.DataFrame: A subset of the original table with overlapping intervals removed.
                The returned DataFrame preserves all original columns and uses the same
                IntervalIndex structure.
        
        Raises:
            KeyError: If table_name is not found in self.interval_data
        
        Notes:
            - The method first removes rows with NaN values in 'holeid', 'from', or 'to'
            - The IntervalIndex is used to efficiently detect overlaps
            - For max_disjoint=True, intervals are selected greedily by finish time
            - For max_disjoint=False, ALL overlapping intervals are excluded (stricter)
        
        Example:
            >>> # Add interval data with overlaps
            >>> db.add_interval_data(assay_df, 'assays')
            >>> # Get maximum disjoint set
            >>> clean_assays = db._fix_overlaps('assays', max_disjoint=True)
            >>> print(f"Original: {len(db.interval_data['assays'])} intervals")
            >>> print(f"Cleaned: {len(clean_assays)} intervals")
        """
        # Validate table exists
        if table_name not in self.interval_data:
            raise KeyError(f"Table '{table_name}' not found in interval data. "
                          f"Available tables: {list(self.interval_data.keys())}")
        
        # Get the table and remove invalid rows
        table = self.interval_data[table_name]
        table_clean = table.dropna(subset=['holeid', 'from', 'to']).copy()
        
        if max_disjoint:
            # Use greedy algorithm to get maximum disjoint set
            mask = self._max_disjoint_mask(table_clean.index)
            table_result = table_clean.iloc[mask, :]
        else:
            # Get only intervals that don't overlap with any others
            mask = self._non_overlapping_mask(table_clean.index)
            table_result = table_clean.iloc[mask, :]
        
        return table_result
    
    def add_point_data(
        self,
        data: pd.DataFrame,
        name: str,
        column_mapping: Optional[Dict[str, str]] = None,
        validate: bool = True,
        auto_desurvey: bool = True
    ):
        """
        Add point data for all drillholes.
        
        Parameters:
            data (pd.DataFrame): Point data for multiple holes
            name (str): Dataset identifier
            column_mapping (dict, optional): Custom column mappings
            validate (bool): Whether to validate the data
            auto_desurvey (bool): Whether to automatically add xyz coordinates.
                Default is True.
        """
        df = data.copy()
        
        # Default point column mapping
        default_mapping = {
            'holeid': ['HOLEID', 'holeid', 'HOLE_ID', 'hole_id'],
            'depth': ['DEPTH', 'depth', 'MD', 'md']
        }
        
        # Apply custom mapping if provided
        if column_mapping:
            for std_name, custom_name in column_mapping.items():
                if isinstance(custom_name, str):
                    default_mapping[std_name] = [custom_name]
        
        # Standardize columns
        rename_map = {}
        for std_name, candidates in default_mapping.items():
            found_col = self._find_column(df, candidates)
            if found_col:
                rename_map[found_col] = std_name
        
        # Check required columns
        required = ['holeid', 'depth']
        missing = [col for col in required if col not in rename_map.values()]
        if missing:
            raise ValueError(f"Missing required point columns: {missing}")
        
        df = df.rename(columns=rename_map)
        
        if validate:
            # Check for valid depths
            invalid = df[df['depth'] < 0]
            if len(invalid) > 0:
                warnings.warn(f"Found {len(invalid)} invalid depths (depth < 0)")
        
        self.point_data[name] = df.sort_values(['holeid', 'depth']).reset_index(drop=True)
        
        # Automatically desurvey if requested
        if auto_desurvey:
            print(f"  Desurveying point data '{name}'...")
            self.point_data[name] = self.desurvey_point_data(
                self.point_data[name],
                depth_column='depth'
            )
        
        # Clear cache since data changed
        self.drillholes.clear()
        
        print(f"✓ Point data '{name}' added: {len(df)} points across {df['holeid'].nunique()} holes")
    
    def _auto_reconcile_orphaned_data(self, new_holeids: set):
        """
        Automatically reconcile orphaned interval data when new collar data is added.
        Called internally AFTER _build_all_trajectories has rebuilt holeid mappings.
        
        Parameters:
            new_holeids (set): Set of holeid strings that were just added
        """
        if not self._orphaned_interval_data:
            return
        
        print(f"\n🔍 Auto-reconciling orphaned interval data...")
        
        for table_name, orphaned_hids in list(self._orphaned_interval_data.items()):
            newly_found = set(orphaned_hids) & new_holeids
            
            if newly_found:
                print(f"  ✓ Reconciling {len(newly_found)} holeids in '{table_name}'")
                print(f"    Holeids: {list(newly_found)[:5]}{'...' if len(newly_found) > 5 else ''}")
                
                # Update orphaned list (remove reconciled holeids)
                still_orphaned = set(orphaned_hids) - newly_found
                
                # Add back any still-orphaned holeids with temp codes
                # (they may have been lost during _build_all_trajectories)
                if still_orphaned:
                    next_temp_code = -10000000
                    for hid in still_orphaned:
                        if hid not in self._holeid_to_code:
                            self._holeid_to_code[hid] = next_temp_code
                            self._code_to_holeid[next_temp_code] = hid
                            next_temp_code -= 1000000
                    self._orphaned_interval_data[table_name] = list(still_orphaned)
                else:
                    del self._orphaned_interval_data[table_name]
                    print(f"    ✓ All holeids in '{table_name}' now have collar data")
    
    def _update_collar_internal(
        self,
        new_collar_data: pd.DataFrame,
        new_survey_data: Optional[pd.DataFrame] = None,
        collar_columns: Optional[Dict[str, str]] = None,
        survey_columns: Optional[Dict[str, str]] = None,
        auto_reconcile: bool = True
    ):
        """
        Internal method to update collar/survey data and automatically reconcile orphaned interval data.
        Users should call add_collar_data() or add_survey_data() instead.
        """
        print(f"\n🔄 Updating collar data with {len(new_collar_data)} new records...")
        
        # Standardize new collar data using the same logic as __init__
        if collar_columns:
            for std_name, custom_name in collar_columns.items():
                if std_name in self.collar_mapping:
                    if isinstance(custom_name, str):
                        self.collar_mapping[std_name].insert(0, custom_name)
                    elif isinstance(custom_name, list):
                        self.collar_mapping[std_name] = custom_name + self.collar_mapping[std_name]
        
        new_collar_std = self._standardize_collar_data(new_collar_data)
        
        # Merge new collar with existing (update existing, add new)
        self.collar_data = pd.concat([self.collar_data, new_collar_std], ignore_index=True)
        self.collar_data = self.collar_data.drop_duplicates(subset=['holeid'], keep='last')
        
        # If survey data provided, update it
        if new_survey_data is not None:
            if survey_columns:
                for std_name, custom_name in survey_columns.items():
                    if std_name in self.survey_mapping:
                        if isinstance(custom_name, str):
                            self.survey_mapping[std_name].insert(0, custom_name)
                        elif isinstance(custom_name, list):
                            self.survey_mapping[std_name] = custom_name + self.survey_mapping[std_name]
            
            new_survey_std = self._standardize_survey_data(new_survey_data)
            self.survey_data = pd.concat([self.survey_data, new_survey_std], ignore_index=True)
            self.survey_data = self.survey_data.drop_duplicates(subset=['holeid', 'depth'], keep='last')
            
            # Recalculate dogleg severity
            self._calculate_and_add_dogleg_severity()
        
        # Rebuild trajectory lookup tables first (this creates new holeid_to_code mapping)
        print('Rebuilding trajectories...')
        self._build_all_trajectories()
        print('Desurveying all survey data...')
        self._desurvey_all_survey_data()
        
        # Auto-reconcile orphaned data AFTER rebuilding trajectories
        new_holeids = set(new_collar_std['holeid'])
        if auto_reconcile:
            self._auto_reconcile_orphaned_data(new_holeids)
        
        # Clear cache since trajectories changed
        self.drillholes.clear()
        
        print(f"\n✓ Database updated with {len(self.collar_data)} total collar records")
    
    def add_collar_data(
        self,
        collar_data: pd.DataFrame,
        survey_data: Optional[pd.DataFrame] = None,
        collar_columns: Optional[Dict[str, str]] = None,
        survey_columns: Optional[Dict[str, str]] = None
    ):
        """
        Add new collar data (and optionally survey data) to the database.
        Automatically reconciles any previously orphaned interval data.
        
        Parameters:
            collar_data (pd.DataFrame): Collar data to add
            survey_data (pd.DataFrame, optional): Survey data to add (recommended)
            collar_columns (dict, optional): Custom column mapping for collar data
            survey_columns (dict, optional): Custom column mapping for survey data
            
        Example:
            >>> # Add new drillholes that were missing when interval data was loaded
            >>> db.add_collar_data(new_collar_df, new_survey_df)
        """
        self._update_collar_internal(collar_data, survey_data, collar_columns, survey_columns)
    
    def add_survey_data(
        self,
        survey_data: pd.DataFrame,
        survey_columns: Optional[Dict[str, str]] = None
    ):
        """
        Add new survey data to the database.
        Automatically rebuilds trajectories for affected drillholes.
        
        Parameters:
            survey_data (pd.DataFrame): Survey data to add
            survey_columns (dict, optional): Custom column mapping for survey data
            
        Example:
            >>> # Add additional survey points
            >>> db.add_survey_data(new_survey_df)
        """
        self._update_collar_internal(pd.DataFrame(), survey_data, None, survey_columns)
    
    # Keep update_collar as alias for backward compatibility
    def update_collar(
        self,
        new_collar_data: pd.DataFrame,
        new_survey_data: Optional[pd.DataFrame] = None,
        collar_columns: Optional[Dict[str, str]] = None,
        survey_columns: Optional[Dict[str, str]] = None
    ):
        """Alias for add_collar_data() - kept for backward compatibility."""
        self._update_collar_internal(new_collar_data, new_survey_data, collar_columns, survey_columns)
    
    def get_all_traces(self, holeids: Optional[List[str]] = None, point_spacing: float = 1.0) -> pd.DataFrame:
        """
        Get densified traces for all or specified drillholes.
        
        Parameters:
            holeids (list, optional): List of holeids to process. If None, process all.
            point_spacing (float): Spacing between interpolated points in meters (default 1.0m)
            
        Returns:
            pd.DataFrame: Combined densified trace data with holeid column
        """
        if holeids is None:
            holeids = self.get_holeid_list()
        
        traces = []
        for holeid in holeids:
            try:
                dh = self.get_drillhole(holeid)
                
                # Create densified trace with regular spacing (same as PyVista)
                max_depth = dh.collar['depth']
                interp_depths = np.arange(0, max_depth + point_spacing, point_spacing)
                
                # Interpolate positions using minimum curvature
                xyz = dh.interpolate_at_depth(interp_depths, attribute='xyz')
                dip = dh.interpolate_at_depth(interp_depths, attribute='dip')
                azimuth = dh.interpolate_at_depth(interp_depths, attribute='azimuth')
                
                # Create DataFrame with densified trace
                trace = pd.DataFrame({
                    'holeid': holeid,
                    'depth': interp_depths,
                    'x': xyz[:, 0],
                    'y': xyz[:, 1],
                    'z': xyz[:, 2],
                    'dip': dip,
                    'azimuth': azimuth
                })
                traces.append(trace)
            except Exception as e:
                warnings.warn(f"Could not process {holeid}: {e}")
        
        if not traces:
            return pd.DataFrame()
        
        return pd.concat(traces, ignore_index=True)
    
    def calculate_statistics(self, holeids: Optional[List[str]] = None) -> pd.DataFrame:
        """
        Calculate summary statistics for all or specified drillholes.
        
        Parameters:
            holeids (list, optional): List of holeids to process
            
        Returns:
            pd.DataFrame: Summary statistics
        """
        if holeids is None:
            holeids = self.get_holeid_list()
        
        results = []
        for holeid in holeids:
            try:
                dh = self.get_drillhole(holeid)
                rake = dh.calculate_rake_geometry()
                length = dh.calculate_hole_length()
                
                results.append({
                    'holeid': holeid,
                    'collar_x': dh.collar['x'],
                    'collar_y': dh.collar['y'],
                    'collar_z': dh.collar['z'],
                    'planned_depth': dh.collar['depth'],
                    'hole_length': length,
                    'tvd': rake['vertical_depth'],
                    'horizontal_disp': rake['horizontal_displacement'],
                    'final_bearing': rake['final_bearing'],
                    'max_dip': rake['max_dip'],
                    'min_dip': rake['min_dip'],
                    'survey_points': len(dh.survey)
                })
            except Exception as e:
                warnings.warn(f"Could not calculate statistics for {holeid}: {e}")
        
        return pd.DataFrame(results)
    
    def merge_interval_tables(
        self,
        table_names: Optional[List[str]] = None,
        sel_columns_dict: Optional[Dict[str, List[str]]] = None,
        merged_table_name: Optional[str] = None,
        store_as_merged: bool = True,
        auto_desurvey: bool = True
    ) -> pd.DataFrame:
        """
        Merge multiple interval tables into a single DataFrame with common interval edges.
        
        This method creates a unified interval structure by finding all unique interval
        boundaries across the specified tables, then aligning each table's data to these
        common intervals. The merged table can be stored for later use and will be
        automatically updated when source tables change.
        
        Parameters:
            table_names (list, optional): List of table names to merge. If None, merges 
                all tables in self.interval_data
            sel_columns_dict (dict, optional): Dictionary mapping table names to list of 
                columns to select from each table.
                Example: {'Assay_Sondajes_1': ['Au_ppm', 'Cu_pct'], 
                         'Assay_Sondajes_2': ['Ag_ppm']}
                If None, all columns are included for each table.
            merged_table_name (str, optional): Name for the merged table. If None and 
                store_as_merged=True, automatically generates name as 'merged_table_<ordinal>'
            store_as_merged (bool): If True, stores the merged table in self.merged_interval_data
                and tracks dependencies for automatic updates. Default is True.
            auto_desurvey (bool): Whether to automatically add xyz coordinates to merged table.
                Default is True.
        
        Returns:
            pd.DataFrame: Merged DataFrame with common interval edges across all tables.
                Columns from each source table are suffixed with '_T<TableId>' to ensure uniqueness.
        
        Notes:
            - Each interval table has a unique TableId assigned when first added
            - Column names are suffixed with '_T<TableId>' (e.g., 'Au_ppm_T1')
            - Overlapping intervals in source tables are automatically fixed using max disjoint set
            - The merge parameters are stored to enable reproduction
            - When source tables are modified, dependent merged tables are automatically updated
        
        Example:
            >>> # Add multiple assay tables
            >>> db.add_interval_data(assay1_df, 'Assay_1')
            >>> db.add_interval_data(assay2_df, 'Assay_2')
            >>> 
            >>> # Merge all tables
            >>> merged = db.merge_interval_tables()
            >>> 
            >>> # Merge specific tables with column selection
            >>> merged = db.merge_interval_tables(
            ...     table_names=['Assay_1', 'Assay_2'],
            ...     sel_columns_dict={'Assay_1': ['Au_ppm', 'Cu_pct'], 
            ...                       'Assay_2': ['Ag_ppm']},
            ...     merged_table_name='precious_metals'
            ... )
        """
        # Default to all tables if not specified
        if table_names is None:
            table_names = list(self.interval_data.keys())
        elif isinstance(table_names, str):
            table_names = [table_names]
        
        if len(table_names) == 0:
            raise ValueError("No interval tables available to merge")
        
        # Check that all table names exist
        missing = [name for name in table_names if name not in self.interval_data]
        if missing:
            raise ValueError(f"Table(s) not found: {missing}")
        
        # Build unified interval edges from all tables
        interval_list = []
        for table_name in table_names:
            imported_df = self.interval_data[table_name].copy()
            interval_list.append(imported_df[['holeid', 'from']])
            aux = imported_df[['holeid', 'to']]
            aux.columns = ['holeid', 'from']
            interval_list.append(aux)
        
        # Create unified interval edges DataFrame
        interval_edges_df = pd.concat(interval_list, axis=0).reset_index(drop=True).dropna()
        interval_edges_df = interval_edges_df.dropna().sort_values(['holeid', 'from'])
        interval_edges_df['__hole_code'] = interval_edges_df['holeid'].map(self._holeid_to_code)
        interval_edges_df['__interval_from'] = interval_edges_df['__hole_code'] + interval_edges_df['from']
        interval_edges_df = interval_edges_df.sort_values('__interval_from').drop_duplicates('__interval_from', keep='first').reset_index(drop=True)
        interval_edges_df['to'] = interval_edges_df.groupby('holeid')['from'].shift(-1)
        interval_edges_df = interval_edges_df[['holeid', 'from', 'to', '__hole_code', '__interval_from']]
        interval_edges_df = interval_edges_df.dropna(subset=['from', 'to']).reset_index(drop=True)
        interval_from = interval_edges_df['__interval_from'].tolist()
        
        # Start merging list with the interval edges
        merging_list = [interval_edges_df]
        
        # Process each table
        for table_name in table_names:
            table = self.interval_data[table_name].dropna(subset=['holeid', 'from', 'to']).copy()
            
            # Fix overlaps if necessary
            if table.index.is_overlapping:
                print(f"Table {table_name} has overlapping intervals. Cleaning (maximum disjoint) before merging.")
                table = self._fix_overlaps(table_name)
            
            # Get indexer for alignment
            indexer = table.index.get_indexer_non_unique(interval_from)
            
            # Select specific columns if requested
            if sel_columns_dict is not None and table_name in sel_columns_dict:
                # Ensure 'holeid', 'from', 'to' are always included
                base_cols = ['holeid', 'from', 'to']
                selected_cols = base_cols + [col for col in sel_columns_dict[table_name] if col not in base_cols]
                # Filter to only existing columns
                selected_cols = [col for col in selected_cols if col in table.columns]
                table = table[selected_cols]
            
            # Get TableId for this table
            table_id = self._table_ids.get(table_name, 0)
            
            # Rename columns to include TableId suffix (except base columns)
            base_cols = ['holeid', 'from', 'to', '_original_holeid']
            rename_dict = {
                col: f"{col}_T{table_id}" 
                for col in table.columns 
                if col not in base_cols
            }
            table = table.rename(columns=rename_dict)
            
            print(f"Table {table_name} (T{table_id}): {len(table.columns)} columns")
            
            # Align table to common intervals
            table_out = table.iloc[indexer[0], :].reset_index()
            table_out.loc[indexer[0] == -1, :] = np.nan
            merging_list.append(table_out)
            print(f"  Aligned: {len(merging_list[-1])} rows, {len(interval_from)} edges")
        
        # Concatenate all tables horizontally
        merged_table = pd.concat(merging_list, axis=1)
        
        # Remove duplicate holeid, from, to columns (keep only first occurrence)
        merged_table = merged_table.loc[:, ~merged_table.columns.duplicated()]
        
        # Automatically desurvey merged table if requested
        if auto_desurvey and 'holeid' in merged_table.columns:
            print("  Desurveying merged table...")
            merged_table = self.desurvey_interval_data(
                merged_table,
                from_column='from',
                to_column='to'
            )
        
        print('Merging complete')
        
        # Store the merged table if requested
        if store_as_merged:
            # Generate name if not provided
            if merged_table_name is None:
                merged_table_name = f'merged_table_{self._next_merged_ordinal}'
                self._next_merged_ordinal += 1
            
            # Store the merged table
            self.merged_interval_data[merged_table_name] = merged_table
            
            # Store merge parameters for reproduction
            self._merge_parameters[merged_table_name] = {
                'table_names': table_names.copy(),
                'sel_columns_dict': sel_columns_dict.copy() if sel_columns_dict else None,
                'auto_desurvey': auto_desurvey,
                'timestamp': pd.Timestamp.now()
            }
            
            # Track dependencies
            self._merged_table_dependencies[merged_table_name] = table_names.copy()
            
            print(f"✓ Merged table '{merged_table_name}' stored with {len(merged_table)} intervals")
        
        return merged_table
    
    def _update_dependent_merged_tables(self, source_table_name: str):
        """
        Update all merged tables that depend on the given source table.
        
        This method is automatically called when an interval table is added or modified.
        It identifies all merged tables that include the modified source table and
        regenerates them using the stored merge parameters.
        
        Parameters:
            source_table_name (str): Name of the source interval table that was modified
        """
        # Find all merged tables that depend on this source table
        dependent_merged = [
            merged_name 
            for merged_name, sources in self._merged_table_dependencies.items()
            if source_table_name in sources
        ]
        
        if not dependent_merged:
            return  # No dependent merged tables
        
        print(f"  Updating {len(dependent_merged)} dependent merged table(s)...")
        
        for merged_name in dependent_merged:
            # Get stored merge parameters
            params = self._merge_parameters[merged_name]
            
            # Check if all source tables still exist
            missing_sources = [
                name for name in params['table_names'] 
                if name not in self.interval_data
            ]
            
            if missing_sources:
                print(f"  ⚠ Warning: Cannot update '{merged_name}' - missing source tables: {missing_sources}")
                continue
            
            # Recreate the merged table with the same parameters
            try:
                updated_table = self.merge_interval_tables(
                    table_names=params['table_names'],
                    sel_columns_dict=params['sel_columns_dict'],
                    merged_table_name=merged_name,
                    store_as_merged=True,
                    auto_desurvey=params.get('auto_desurvey', True)
                )
                print(f"  ✓ Updated merged table '{merged_name}'")
            except Exception as e:
                print(f"  ✗ Error updating merged table '{merged_name}': {e}")
    
    def get_merged_table_info(self, merged_table_name: Optional[str] = None) -> Union[Dict, pd.DataFrame]:
        """
        Get information about merged tables, including their source tables and parameters.
        
        Parameters:
            merged_table_name (str, optional): Name of a specific merged table. If None,
                returns information about all merged tables.
        
        Returns:
            If merged_table_name is specified: Dict with merge parameters and metadata
            If merged_table_name is None: DataFrame summarizing all merged tables
        
        Example:
            >>> # Get info about a specific merged table
            >>> info = db.get_merged_table_info('precious_metals')
            >>> print(info['table_names'])
            >>> 
            >>> # Get summary of all merged tables
            >>> summary = db.get_merged_table_info()
            >>> print(summary)
        """
        if merged_table_name is not None:
            # Return info for specific merged table
            if merged_table_name not in self.merged_interval_data:
                raise KeyError(f"Merged table '{merged_table_name}' not found")
            
            params = self._merge_parameters.get(merged_table_name, {})
            table = self.merged_interval_data[merged_table_name]
            
            return {
                'name': merged_table_name,
                'source_tables': params.get('table_names', []),
                'selected_columns': params.get('sel_columns_dict', None),
                'created': params.get('timestamp', None),
                'num_intervals': len(table),
                'num_holes': table['holeid'].nunique() if 'holeid' in table.columns else 0,
                'columns': list(table.columns)
            }
        else:
            # Return summary DataFrame for all merged tables
            if not self.merged_interval_data:
                return pd.DataFrame(columns=['merged_table', 'num_intervals', 'num_holes', 'source_tables', 'created'])
            
            summary_data = []
            for merged_name, table in self.merged_interval_data.items():
                params = self._merge_parameters.get(merged_name, {})
                summary_data.append({
                    'merged_table': merged_name,
                    'num_intervals': len(table),
                    'num_holes': table['holeid'].nunique() if 'holeid' in table.columns else 0,
                    'source_tables': ', '.join(params.get('table_names', [])),
                    'created': params.get('timestamp', None)
                })
            
            return pd.DataFrame(summary_data)
    
    def __repr__(self) -> str:
        """String representation."""
        return (
            f"DrillholeDatabase("
            f"holes={len(self.get_holeid_list())}, "
            f"intervals={len(self.interval_data)}, "
            f"merged={len(self.merged_interval_data)}, "
            f"points={len(self.point_data)})"
        )
    
    def summary(self) -> str:
        """Generate database summary."""
        holes = self.get_holeid_list()
        
        summary = f"""
========================================
Drillhole Database Summary
========================================
Total Drillholes: {len(holes)}
Interval Datasets: {len(self.interval_data)}
Merged Tables: {len(self.merged_interval_data)}
Point Datasets: {len(self.point_data)}

Collar Data: {len(self.collar_data)} records
Survey Data: {len(self.survey_data)} records
"""
        
        if self.interval_data:
            summary += "\nInterval Data:\n"
            for name, df in self.interval_data.items():
                table_id = self._table_ids.get(name, '?')
                summary += f"  {name} (T{table_id}): {len(df)} intervals ({df['holeid'].nunique()} holes)\n"
        
        if self.merged_interval_data:
            summary += "\nMerged Tables:\n"
            for name, df in self.merged_interval_data.items():
                params = self._merge_parameters.get(name, {})
                sources = params.get('table_names', [])
                summary += f"  {name}: {len(df)} intervals (from {len(sources)} sources)\n"
        
        if self.point_data:
            summary += "\nPoint Data:\n"
            for name, df in self.point_data.items():
                summary += f"  {name}: {len(df)} points ({df['holeid'].nunique()} holes)\n"
        
        summary += f"\nFirst 10 Holes: {holes[:10]}\n"
        summary += "========================================\n"
        
        return summary


class Drillhole:
    """
    A class representing a single drillhole.
    
    This class is typically created by DrillholeDatabase.get_drillhole()
    but can also be used standalone.
    """
    
    def __init__(
        self,
        holeid: str,
        collar: pd.Series,
        survey: pd.DataFrame,
        trajectory: Optional[Dict] = None
    ):
        """
        Initialize Drillhole with collar and survey data.
        
        Parameters:
            holeid (str): Drillhole identifier
            collar (pd.Series): Collar data (x, y, z, depth)
            survey (pd.DataFrame): Survey data (depth, dip, azimuth, dogleg_severity, ignored, x, y, z)
            trajectory (dict, optional): Pre-calculated trajectory parameters from DrillholeDatabase
        """
        self.holeid = holeid
        self.collar = collar
        self.survey = survey.copy()
        self.interval_data: Dict[str, pd.DataFrame] = {}
        self.point_data: Dict[str, pd.DataFrame] = {}
        self._trajectory = trajectory  # Shared trajectory cache from database
        
        # Ensure survey starts at depth 0 if not already
        if self.survey['depth'].iloc[0] != 0:
            first_row = pd.DataFrame({
                'depth': [0.0],
                'dip': [self.survey['dip'].iloc[0]],
                'azimuth': [self.survey['azimuth'].iloc[0]],
                'dogleg_severity': [0.0],
                'ignored': [False],
                'x': [self.collar['x']],
                'y': [self.collar['y']],
                'z': [self.collar['z']]
            })
            self.survey = pd.concat([first_row, self.survey], ignore_index=True)
        
        # Create trace from pre-calculated survey coordinates (filter out ignored/NaN points)
        valid_mask = self.survey['x'].notna()
        self.trace = pd.DataFrame({
            'holeid': self.holeid,
            'depth': self.survey.loc[valid_mask, 'depth'].values,
            'x': self.survey.loc[valid_mask, 'x'].values,
            'y': self.survey.loc[valid_mask, 'y'].values,
            'z': self.survey.loc[valid_mask, 'z'].values,
            'dip': self.survey.loc[valid_mask, 'dip'].values,
            'azimuth': self.survey.loc[valid_mask, 'azimuth'].values
        })
        
        self._pyvista_trace = None
    
    def add_interval_data(self, data: pd.DataFrame, name: str, validate: bool = True):
        """Add interval data for this drillhole."""
        df = data[data['holeid'] == self.holeid].copy()
        if len(df) > 0:
            self.interval_data[name] = df.sort_values('from').reset_index(drop=True)
    
    def add_point_data(self, data: pd.DataFrame, name: str, validate: bool = True):
        """Add point data for this drillhole."""
        df = data[data['holeid'] == self.holeid].copy()
        if len(df) > 0:
            self.point_data[name] = df.sort_values('depth').reset_index(drop=True)
    
    def calculate_hole_length(self) -> float:
        """Calculate total 3D hole length."""
        coords = self.trace[['x', 'y', 'z']].values
        deltas = np.diff(coords, axis=0)
        distances = np.sqrt(np.sum(deltas**2, axis=1))
        return np.sum(distances)
    
    def calculate_rake_geometry(self) -> Dict[str, float]:
        """Calculate rake geometry properties."""
        trace = self.trace
        coords = trace[['x', 'y', 'z']].values
        
        vertical_depth = self.collar['z'] - coords[-1, 2]
        
        dx = coords[-1, 0] - coords[0, 0]
        dy = coords[-1, 1] - coords[0, 1]
        horizontal_displacement = np.sqrt(dx**2 + dy**2)
        
        final_bearing = np.degrees(np.arctan2(dx, dy)) % 360
        
        dz = np.diff(coords[:, 2])
        segment_lengths = np.sqrt(np.sum(np.diff(coords, axis=0)**2, axis=1))
        
        upward_mask = dz < 0
        upward_sections = np.sum(segment_lengths[upward_mask])
        
        downward_mask = dz >= 0
        downward_sections = np.sum(segment_lengths[downward_mask])
        
        return {
            'vertical_depth': vertical_depth,
            'horizontal_displacement': horizontal_displacement,
            'final_bearing': final_bearing,
            'upward_sections': upward_sections,
            'downward_sections': downward_sections,
            'max_dip': trace['dip'].max(),
            'min_dip': trace['dip'].min()
        }
    
    def interpolate_at_depth(
        self,
        depth: Union[float, np.ndarray],
        attribute: str = 'xyz'
    ) -> Union[Tuple[float, float, float], np.ndarray, Dict]:
        """
        Interpolate position or attributes at specific depth(s) using minimum curvature.
        
        Uses pre-calculated trajectory parameters from DrillholeDatabase for consistency.
        
        Parameters:
            depth: Single depth or array of depths to interpolate at
            attribute: 'xyz' for coordinates, 'dip', 'azimuth', or 'all' for everything
            
        Returns:
            Interpolated values at requested depths
        """
        is_scalar = np.isscalar(depth)
        depths = np.atleast_1d(depth)
        
        # Initialize output arrays
        x_out = np.zeros(len(depths))
        y_out = np.zeros(len(depths))
        z_out = np.zeros(len(depths))
        dip_out = np.zeros(len(depths))
        azi_out = np.zeros(len(depths))
        
        # Use cached trajectory if available, otherwise calculate on-the-fly
        if self._trajectory is not None:
            # Use pre-calculated trajectory parameters (same as database)
            traj = self._trajectory
            survey_depths = traj['depths']
            intervals = traj['intervals']
            
            for idx, target_depth in enumerate(depths):
                if target_depth == 0.0:
                    # At collar (depth = 0): always use collar position
                    x_out[idx] = traj['collar_x']
                    y_out[idx] = traj['collar_y']
                    z_out[idx] = traj['collar_z']
                    dip_out[idx] = np.degrees(traj['dip'][0])
                    azi_out[idx] = np.degrees(traj['azimuth'][0])
                    
                elif target_depth < survey_depths[0]:
                    # Before first station
                    x_out[idx] = traj['collar_x']
                    y_out[idx] = traj['collar_y']
                    z_out[idx] = traj['collar_z']
                    dip_out[idx] = np.degrees(traj['dip'][0])
                    azi_out[idx] = np.degrees(traj['azimuth'][0])
                    
                elif target_depth >= survey_depths[-1]:
                    # Beyond last station: extrapolate using last survey angle
                    extra_depth = target_depth - survey_depths[-1]
                    dip_rad = traj['dip'][-1]
                    azi_rad = traj['azimuth'][-1]
                    
                    # Extrapolate from last position
                    de = extra_depth * np.cos(dip_rad) * np.sin(azi_rad)
                    dn = extra_depth * np.cos(dip_rad) * np.cos(azi_rad)
                    dv = extra_depth * np.sin(dip_rad)
                    
                    x_out[idx] = traj['x'][-1] + de
                    y_out[idx] = traj['y'][-1] + dn
                    z_out[idx] = traj['z'][-1] - dv
                    dip_out[idx] = np.degrees(traj['dip'][-1])
                    azi_out[idx] = np.degrees(traj['azimuth'][-1])
                    
                else:
                    # Within survey range - use cached interval parameters
                    interval_idx = np.searchsorted(survey_depths, target_depth) - 1
                    interval = intervals[interval_idx]
                    
                    # Calculate distance into interval
                    md_target = target_depth - interval['from_depth']
                    md_diff = interval['md_diff']
                    
                    # Get cached parameters
                    dip1 = interval['dip1']
                    dip2 = interval['dip2']
                    azi1 = interval['azi1']
                    azi2 = interval['azi2']
                    rf = interval['rf']
                    
                    # Linearly interpolate angles
                    fraction = md_target / md_diff if md_diff > 0 else 0.0
                    dip_interp = dip1 + fraction * (dip2 - dip1)
                    azi_interp = azi1 + fraction * (azi2 - azi1)
                    
                    # Minimum curvature calculation
                    dn = md_target / 2 * (np.cos(dip1) * np.cos(azi1) + 
                                          np.cos(dip_interp) * np.cos(azi_interp)) * rf
                    de = md_target / 2 * (np.cos(dip1) * np.sin(azi1) + 
                                          np.cos(dip_interp) * np.sin(azi_interp)) * rf
                    dv = md_target / 2 * (np.sin(dip1) + np.sin(dip_interp)) * rf
                    
                    x_out[idx] = interval['x0'] + de
                    y_out[idx] = interval['y0'] + dn
                    z_out[idx] = interval['z0'] - dv
                    dip_out[idx] = np.degrees(dip_interp)
                    azi_out[idx] = np.degrees(azi_interp)
        
        else:
            # Fallback: Calculate on-the-fly (for standalone Drillhole objects)
            survey_depths = self.survey['depth'].values
            
            for idx, target_depth in enumerate(depths):
                if target_depth == 0.0:
                    # At collar (depth = 0): always use collar position
                    x_out[idx] = self.collar['x']
                    y_out[idx] = self.collar['y']
                    z_out[idx] = self.collar['z']
                    dip_out[idx] = self.survey['dip'].iloc[0]
                    azi_out[idx] = self.survey['azimuth'].iloc[0]
                    
                elif target_depth < survey_depths[0]:
                    # Before first station
                    x_out[idx] = self.collar['x']
                    y_out[idx] = self.collar['y']
                    z_out[idx] = self.collar['z']
                    dip_out[idx] = self.survey['dip'].iloc[0]
                    azi_out[idx] = self.survey['azimuth'].iloc[0]
                    
                elif target_depth >= survey_depths[-1]:
                    # Beyond last station: extrapolate using last survey angle
                    i = len(survey_depths) - 1
                    extra_depth = target_depth - survey_depths[-1]
                    dip_rad = np.radians(self.survey['dip'].iloc[i])
                    azi_rad = np.radians(self.survey['azimuth'].iloc[i])
                    
                    # Extrapolate from last position
                    de = extra_depth * np.cos(dip_rad) * np.sin(azi_rad)
                    dn = extra_depth * np.cos(dip_rad) * np.cos(azi_rad)
                    dv = extra_depth * np.sin(dip_rad)
                    
                    x_out[idx] = self.trace['x'].iloc[i] + de
                    y_out[idx] = self.trace['y'].iloc[i] + dn
                    z_out[idx] = self.trace['z'].iloc[i] - dv
                    dip_out[idx] = self.survey['dip'].iloc[i]
                    azi_out[idx] = self.survey['azimuth'].iloc[i]
                    
                else:
                    i = np.searchsorted(survey_depths, target_depth) - 1
                    
                    depth1 = survey_depths[i]
                    depth2 = survey_depths[i + 1]
                    md_diff = depth2 - depth1
                    md_target = target_depth - depth1
                    
                    dip1 = np.radians(self.survey['dip'].iloc[i])
                    dip2 = np.radians(self.survey['dip'].iloc[i + 1])
                    azi1 = np.radians(self.survey['azimuth'].iloc[i])
                    azi2 = np.radians(self.survey['azimuth'].iloc[i + 1])
                    
                    cos_dogleg = (np.cos(dip2 - dip1) - 
                                 np.sin(dip1) * np.sin(dip2) * (1 - np.cos(azi2 - azi1)))
                    cos_dogleg = np.clip(cos_dogleg, -1.0, 1.0)
                    dogleg = np.arccos(cos_dogleg)
                    
                    rf = 1.0 if dogleg < 1e-6 else 2 / dogleg * np.tan(dogleg / 2)
                    
                    fraction = md_target / md_diff
                    dip_interp = dip1 + fraction * (dip2 - dip1)
                    azi_interp = azi1 + fraction * (azi2 - azi1)
                    
                    dn = md_target / 2 * (np.cos(dip1) * np.cos(azi1) + 
                                           np.cos(dip_interp) * np.cos(azi_interp)) * rf
                    de = md_target / 2 * (np.cos(dip1) * np.sin(azi1) + 
                                           np.cos(dip_interp) * np.sin(azi_interp)) * rf
                    dv = md_target / 2 * (np.sin(dip1) + np.sin(dip_interp)) * rf
                    
                    x_out[idx] = self.trace['x'].iloc[i] + de
                    y_out[idx] = self.trace['y'].iloc[i] + dn
                    z_out[idx] = self.trace['z'].iloc[i] - dv
                    dip_out[idx] = np.degrees(dip_interp)
                    azi_out[idx] = np.degrees(azi_interp)
        
        # Return requested attribute
        if attribute == 'xyz':
            if is_scalar:
                return (float(x_out[0]), float(y_out[0]), float(z_out[0]))
            return np.column_stack([x_out, y_out, z_out])
        
        elif attribute == 'dip':
            if is_scalar:
                return float(dip_out[0])
            return dip_out
        
        elif attribute == 'azimuth':
            if is_scalar:
                return float(azi_out[0])
            return azi_out
        
        elif attribute == 'all':
            result = {
                'x': x_out,
                'y': y_out,
                'z': z_out,
                'dip': dip_out,
                'azimuth': azi_out
            }
            if is_scalar:
                return {k: float(v[0]) for k, v in result.items()}
            return result
        
        else:
            raise ValueError(f"Unknown attribute: {attribute}")
    
    def get_pyvista_trace(self, point_spacing: float = 1.0, **kwargs):
        """
        Generate PyVista PolyData for 3D visualization with densified trace.
        
        Parameters:
            point_spacing: Spacing between interpolated points in meters (default 1.0m)
            **kwargs: Additional arguments passed to pv.PolyData
            
        Returns:
            pv.PolyData: Densified trace for smooth visualization
        """
        try:
            import pyvista as pv
        except ImportError:
            raise ImportError("PyVista required. Install with: pip install pyvista")
        
        if self._pyvista_trace is None:
            # Create densified trace with regular spacing
            max_depth = self.collar['depth']
            interp_depths = np.arange(0, max_depth + point_spacing, point_spacing)
            
            # Interpolate XYZ positions using minimum curvature
            xyz = self.interpolate_at_depth(interp_depths, attribute='xyz')
            dip = self.interpolate_at_depth(interp_depths, attribute='dip')
            azimuth = self.interpolate_at_depth(interp_depths, attribute='azimuth')
            
            # Create PyVista polydata
            n_points = len(interp_depths)
            lines = np.column_stack([
                np.full(n_points - 1, 2),
                np.arange(n_points - 1),
                np.arange(1, n_points)
            ]).ravel()
            
            self._pyvista_trace = pv.PolyData(xyz, lines=lines, **kwargs)
            self._pyvista_trace['depth'] = interp_depths
            self._pyvista_trace['dip'] = dip
            self._pyvista_trace['azimuth'] = azimuth

        
        return self._pyvista_trace
    
    def summary(self) -> str:
        """Generate drillhole summary."""
        rake = self.calculate_rake_geometry()
        length = self.calculate_hole_length()
        
        return f"""
========================================
Drillhole: {self.holeid}
========================================
Collar: X={self.collar['x']:.2f}, Y={self.collar['y']:.2f}, Z={self.collar['z']:.2f}
Depth: {self.collar['depth']:.2f} m
Length: {length:.2f} m
TVD: {rake['vertical_depth']:.2f} m
Horizontal Displacement: {rake['horizontal_displacement']:.2f} m
Intervals: {len(self.interval_data)}
Points: {len(self.point_data)}
========================================
"""
    
    def __repr__(self) -> str:
        return f"Drillhole(holeid='{self.holeid}', depth={self.collar['depth']:.2f}m)"
