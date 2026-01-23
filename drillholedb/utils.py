import numpy as np

def dip_az_to_unit_vector(dip, azimuth):
    """
    Convert dip and azimuth angles to a unit direction vector.
    
    Parameters:
    -----------
    dip : float
        Dip angle in degrees (0 = horizontal, 90 = vertical downward)
    azimuth : float
        Azimuth angle in degrees (0 = North, 90 = East, 180 = South, 270 = West)
    
    Returns:
    --------
    numpy.ndarray
        Unit vector [x, y, z] where:
        - x points East
        - y points North
        - z points Down
    
    Examples:
    ---------
    >>> dip_az_to_unit_vector(0, 0)    # Horizontal North
    array([0., 1., 0.])
    >>> dip_az_to_unit_vector(0, 90)   # Horizontal East
    array([1., 0., 0.])
    >>> dip_az_to_unit_vector(90, 0)   # Vertical Down
    array([0., 0., 1.])
    """
    # Convert to radians
    dip_rad = np.radians(dip)
    az_rad = np.radians(azimuth)
    
    # Calculate unit vector components
    # Horizontal component magnitude
    horizontal = np.cos(dip_rad)
    
    # X (East), Y (North), Z (Down)
    x = horizontal * np.sin(az_rad)
    y = horizontal * np.cos(az_rad)
    z = np.sin(dip_rad)
    
    return np.array([x, y, z]).T