# elevation_mask.py
"""
Elevation mask module for RINEX-Masker.
Supports two mask types:
  1. Sector masks: (az_from, az_to, el_limit) rectangular sectors
  2. Horizon profile: list of (azimuth, elevation) pairs forming a smooth boundary

Mask file format:
  # Lines with 3 values = sector: azimuth_start, azimuth_end, elevation_cutoff
  # Lines with 2 values = horizon profile point: azimuth, elevation
"""

import numpy as np


class ElevationMask:
    """
    Manages azimuth/elevation obstruction masks.
    
    Supports both rectangular sector masks and continuous horizon profiles.
    When both are defined, a satellite is obstructed if blocked by EITHER.
    """
    
    def __init__(self, uniform_cutoff=0.0):
        self.uniform_cutoff = uniform_cutoff
        self.sectors = []           # List of (az_from, az_to, el_limit) tuples
        self.horizon_profile = []   # List of (azimuth, elevation) sorted by azimuth
    
    # ---- Sector mask methods (Phase 1) ----
    
    def add_sector(self, az_from, az_to, elevation_limit):
        if not (0 <= az_from <= 360):
            raise ValueError(f"az_from must be 0-360, got {az_from}")
        if not (0 <= az_to <= 360):
            raise ValueError(f"az_to must be 0-360, got {az_to}")
        if not (0 <= elevation_limit <= 90):
            raise ValueError(f"elevation_limit must be 0-90, got {elevation_limit}")
        self.sectors.append((az_from, az_to, elevation_limit))
    
    # ---- Horizon profile methods (Phase 2) ----
    
    def set_horizon_profile(self, points):
        """
        Set the horizon profile from a list of (azimuth, elevation) pairs.
        Points are sorted by azimuth. The profile wraps around 360->0.
        
        Args:
            points: list of (azimuth_deg, elevation_deg) tuples
        """
        if len(points) < 2:
            raise ValueError("Horizon profile needs at least 2 points")
        
        # Validate
        for az, el in points:
            if not (0 <= az <= 360):
                raise ValueError(f"Azimuth must be 0-360, got {az}")
            if not (0 <= el <= 90):
                raise ValueError(f"Elevation must be 0-90, got {el}")
        
        # Sort by azimuth
        self.horizon_profile = sorted(points, key=lambda p: p[0])
    
    def get_profile_elevation(self, azimuth):
        """
        Get the horizon elevation at a given azimuth by linear interpolation.
        
        Args:
            azimuth: Azimuth in degrees [0, 360)
            
        Returns:
            Elevation in degrees (satellite must be above this to be visible)
        """
        if not self.horizon_profile:
            return 0.0
        
        azimuth = azimuth % 360
        azimuths = [p[0] for p in self.horizon_profile]
        elevations = [p[1] for p in self.horizon_profile]
        
        # Handle wrap-around: extend the profile so interpolation works at 0/360
        # Add a copy of the last point shifted by -360 and the first shifted by +360
        az_ext = [azimuths[-1] - 360] + azimuths + [azimuths[0] + 360]
        el_ext = [elevations[-1]] + elevations + [elevations[0]]
        
        return float(np.interp(azimuth, az_ext, el_ext))
    
    # ---- Core obstruction check ----
    
    def is_obstructed(self, azimuth, elevation):
        """
        Check if a satellite at the given azimuth/elevation is obstructed.
        
        Returns True if blocked by uniform cutoff, any sector, OR horizon profile.
        """
        # 1. Uniform cutoff
        if elevation < self.uniform_cutoff:
            return True
        
        # 2. Sector masks
        for az_from, az_to, el_limit in self.sectors:
            if self._azimuth_in_range(azimuth, az_from, az_to):
                if elevation < el_limit:
                    return True
        
        # 3. Horizon profile
        if self.horizon_profile:
            profile_el = self.get_profile_elevation(azimuth)
            if elevation < profile_el:
                return True
        
        return False
    
    def get_min_elevation(self, azimuth):
        """Get the minimum visible elevation at a given azimuth."""
        min_el = self.uniform_cutoff
        
        for az_from, az_to, el_limit in self.sectors:
            if self._azimuth_in_range(azimuth, az_from, az_to):
                min_el = max(min_el, el_limit)
        
        if self.horizon_profile:
            profile_el = self.get_profile_elevation(azimuth)
            min_el = max(min_el, profile_el)
        
        return min_el
    
    @staticmethod
    def _azimuth_in_range(azimuth, az_from, az_to):
        azimuth = azimuth % 360
        if az_from <= az_to:
            return az_from <= azimuth <= az_to
        else:
            return azimuth >= az_from or azimuth <= az_to
    
    # ---- File I/O ----
    
    @classmethod
    def from_file(cls, filepath, uniform_cutoff=0.0):
        """
        Parse a mask definition file.
        Lines with 3 values = sector (az_start, az_end, el_cutoff).
        Lines with 2 values = horizon profile point (azimuth, elevation).
        """
        mask = cls(uniform_cutoff=uniform_cutoff)
        profile_points = []
        
        with open(filepath, 'r') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    # Check for uniform cutoff in comments
                    if line.startswith('# Uniform cutoff:'):
                        try:
                            val = float(line.split(':')[1].strip().replace('deg', '').strip())
                            mask.uniform_cutoff = val
                        except (ValueError, IndexError):
                            pass
                    continue
                
                # PCC-Explorer format: "180-270,45"
                if '-' in line.split(',')[0]:
                    parts = line.split(',')
                    if len(parts) >= 2:
                        range_part = parts[0].strip()
                        el_part = parts[1].strip()
                        az_from_str, az_to_str = range_part.split('-', 1)
                        mask.add_sector(float(az_from_str), float(az_to_str), float(el_part))
                    continue
                
                parts = [p.strip() for p in line.split(',')]
                if len(parts) >= 3:
                    # Sector: az_from, az_to, elevation
                    mask.add_sector(float(parts[0]), float(parts[1]), float(parts[2]))
                elif len(parts) == 2:
                    # Horizon profile point: azimuth, elevation
                    profile_points.append((float(parts[0]), float(parts[1])))
        
        if profile_points:
            mask.set_horizon_profile(profile_points)
        
        return mask
    
    @classmethod
    def from_string(cls, text, uniform_cutoff=0.0):
        """Parse mask definition from a string."""
        mask = cls(uniform_cutoff=uniform_cutoff)
        profile_points = []
        
        lines = text.replace(';', '\n').split('\n')
        for line in lines:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            
            if '-' in line.split(',')[0]:
                parts = line.split(',')
                if len(parts) >= 2:
                    range_part = parts[0].strip()
                    el_part = parts[1].strip()
                    az_from_str, az_to_str = range_part.split('-', 1)
                    mask.add_sector(float(az_from_str), float(az_to_str), float(el_part))
                continue
            
            parts = [p.strip() for p in line.split(',')]
            if len(parts) >= 3:
                mask.add_sector(float(parts[0]), float(parts[1]), float(parts[2]))
            elif len(parts) == 2:
                profile_points.append((float(parts[0]), float(parts[1])))
        
        if profile_points:
            mask.set_horizon_profile(profile_points)
        
        return mask
    
    def save_profile(self, filepath):
        """Save the horizon profile to a file."""
        with open(filepath, 'w') as f:
            f.write("# RINEX-Masker Horizon Profile\n")
            f.write(f"# Uniform cutoff: {self.uniform_cutoff} deg\n")
            if self.horizon_profile:
                f.write("# Format: azimuth, elevation\n")
                for az, el in self.horizon_profile:
                    f.write(f"{az:.1f}, {el:.1f}\n")
            if self.sectors:
                f.write("# Sector masks (azimuth_start, azimuth_end, elevation_cutoff)\n")
                for az_from, az_to, el_limit in self.sectors:
                    f.write(f"{az_from:.1f}, {az_to:.1f}, {el_limit:.1f}\n")
    
    # ---- Display ----
    
    def __repr__(self):
        parts = [f"ElevationMask(cutoff={self.uniform_cutoff}"]
        if self.sectors:
            parts.append(f", {len(self.sectors)} sector(s)")
        if self.horizon_profile:
            parts.append(f", {len(self.horizon_profile)}-point profile")
        parts.append(")")
        return "".join(parts)
    
    def summary(self):
        lines = [f"Uniform cutoff: {self.uniform_cutoff} deg"]
        for i, (az_from, az_to, el_limit) in enumerate(self.sectors, 1):
            lines.append(f"  Sector {i}: Az {az_from:.0f}-{az_to:.0f} deg, El < {el_limit:.0f} deg blocked")
        if self.horizon_profile:
            lines.append(f"  Horizon profile: {len(self.horizon_profile)} points")
            el_vals = [p[1] for p in self.horizon_profile]
            lines.append(f"    Elevation range: {min(el_vals):.0f}-{max(el_vals):.0f} deg")
        return "\n".join(lines)

    # ---- JSON Import/Export (cross-tool compatible) ----

    def to_dict(self):
        """Serialize mask to a dictionary (JSON-compatible)."""
        d = {
            'format': 'pcc-mask-v1',
            'uniform_cutoff_deg': self.uniform_cutoff,
            'sectors': [
                {'az_from': s[0], 'az_to': s[1], 'el_limit': s[2]}
                for s in self.sectors
            ],
            'horizon_profile': [
                {'azimuth': p[0], 'elevation': p[1]}
                for p in self.horizon_profile
            ],
        }
        return d

    @classmethod
    def from_dict(cls, d):
        """Deserialize mask from a dictionary."""
        mask = cls(uniform_cutoff=d.get('uniform_cutoff_deg', 0.0))
        for s in d.get('sectors', []):
            mask.add_sector(s['az_from'], s['az_to'], s['el_limit'])
        profile = d.get('horizon_profile', [])
        if len(profile) >= 2:
            mask.set_horizon_profile([(p['azimuth'], p['elevation']) for p in profile])
        return mask

    def save_json(self, filepath):
        """Save the complete mask definition to a JSON file."""
        import json
        with open(filepath, 'w') as f:
            json.dump(self.to_dict(), f, indent=2)

    @classmethod
    def load_json(cls, filepath):
        """Load a mask definition from a JSON file."""
        import json
        with open(filepath, 'r') as f:
            d = json.load(f)
        if d.get('format') != 'pcc-mask-v1':
            raise ValueError(f"Unknown mask format: {d.get('format')}")
        return cls.from_dict(d)

