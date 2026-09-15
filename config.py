# config.py
"""
Constants and configuration for RINEX-Masker.
"""

# --- WGS84 Ellipsoid Parameters ---
WGS84_A = 6378137.0              # Semi-major axis [m]
WGS84_F = 1 / 298.257223563     # Flattening
WGS84_E2 = WGS84_F * (2 - WGS84_F)  # First eccentricity squared

# --- GNSS Constellation Identifiers ---
CONSTELLATION_NAMES = {
    'G': 'GPS',
    'R': 'GLONASS',
    'E': 'Galileo',
    'C': 'BeiDou',
    'J': 'QZSS',
    'S': 'SBAS',
}

# Colors for skyplot visualization (per constellation)
CONSTELLATION_COLORS = {
    'G': '#1f77b4',   # Blue - GPS
    'R': '#d62728',   # Red - GLONASS
    'E': '#2ca02c',   # Green - Galileo
    'C': '#ff7f0e',   # Orange - BeiDou
    'J': '#9467bd',   # Purple - QZSS
    'S': '#8c564b',   # Brown - SBAS
}

# --- Default Processing Parameters ---
DEFAULT_ELEVATION_CUTOFF = 5.0   # degrees
SP3_INTERPOLATION_POINTS = 2    # Linear interpolation (matching PCC-Explorer)
