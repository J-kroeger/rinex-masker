# satellite_position.py
"""
Satellite position computation for RINEX-Masker.
Adapted from PCC-Explorer's geodesy.py, data_io.py, and orbit_utils.py.

Provides:
- SP3 file loading (local path or auto-download)
- Satellite ECEF interpolation
- Azimuth/elevation computation from ECEF station + satellite positions
"""

import os
import sys
import gzip
import shutil
import math
from ftplib import FTP
from datetime import datetime, timedelta

import numpy as np
import pyproj

# --- Coordinate transform setup (from PCC-Explorer geodesy.py) ---
_ecef_proj = pyproj.Proj(proj='geocent', ellps='WGS84', datum='WGS84')
_lla_proj = pyproj.Proj(proj='latlong', ellps='WGS84', datum='WGS84')
_transformer_ecef_to_lla = pyproj.Transformer.from_proj(_ecef_proj, _lla_proj, always_xy=True)


def ecef_to_ell(x, y, z):
    """Convert ECEF (x, y, z) to ellipsoidal (lat_rad, lon_rad, h)."""
    lon_deg, lat_deg, h = _transformer_ecef_to_lla.transform(x, y, z)
    return np.radians(lat_deg), np.radians(lon_deg), h


def ecef_to_topocentric(station_ecef, target_ecef):
    """
    Calculate azimuth and elevation from station to target in ECEF.
    
    Args:
        station_ecef: np.ndarray [x, y, z] of station in ECEF [m]
        target_ecef: np.ndarray [x, y, z] of satellite in ECEF [m]
        
    Returns:
        (azimuth_deg, elevation_deg)
    """
    lat_rad, lon_rad, _ = ecef_to_ell(station_ecef[0], station_ecef[1], station_ecef[2])
    vec_ecef = target_ecef - station_ecef
    
    sin_lat = np.sin(lat_rad)
    cos_lat = np.cos(lat_rad)
    sin_lon = np.sin(lon_rad)
    cos_lon = np.cos(lon_rad)
    
    # Rotation matrix ECEF -> NEU (North-East-Up)
    R = np.array([
        [-sin_lon,           cos_lon,             0],
        [-sin_lat * cos_lon, -sin_lat * sin_lon,  cos_lat],
        [ cos_lat * cos_lon,  cos_lat * sin_lon,  sin_lat]
    ])
    
    vec_neu = R.dot(vec_ecef)
    n, e, u = vec_neu[0], vec_neu[1], vec_neu[2]
    horizontal_dist = np.sqrt(n**2 + e**2)
    
    if horizontal_dist < 1e-9:
        azimuth_rad = 0.0
        elevation_rad = np.pi / 2.0
    else:
        azimuth_rad = np.arctan2(n, e)
        elevation_rad = np.arctan2(u, horizontal_dist)
    
    azimuth_deg = np.degrees(azimuth_rad) % 360.0
    return azimuth_deg, np.degrees(elevation_rad)


# --- Time utilities (from PCC-Explorer time_utils.py) ---

def _datetime_to_mjd(dt_obj):
    """Convert datetime to Modified Julian Date."""
    from astropy.time import Time
    t = Time(dt_obj, scale='utc')
    return t.mjd


def _mjd_to_gps_week(mjd):
    """Convert MJD to (GPS_week, day_of_week)."""
    gps_days = math.floor(mjd - 44244)
    gps_week = gps_days // 7
    day_of_week = gps_days % 7
    return gps_week, day_of_week


# --- SP3 Download (from PCC-Explorer data_io.py) ---

def _local_decompressed_name(download_dir, target_file):
    """Path the SP3 will have on disk once `target_file` is decompressed."""
    if target_file.endswith('.Z'):
        base = target_file[:-2]
    elif target_file.endswith('.gz'):
        base = target_file[:-3]
    else:
        base = target_file
    return os.path.join(download_dir, base)


def _decompress_sp3(local_compressed, local_final, download_dir):
    """
    Decompress a downloaded .gz/.Z SP3 into `local_final`.
    Returns local_final on success, else None (and cleans up the archive).
    """
    try:
        if local_compressed.endswith('.gz'):
            with gzip.open(local_compressed, 'rb') as f_in, open(local_final, 'wb') as f_out:
                shutil.copyfileobj(f_in, f_out)
            os.remove(local_compressed)
            return local_final if os.path.exists(local_final) else None

        if local_compressed.endswith('.Z'):
            import subprocess
            seven_z_path = shutil.which("7z") or shutil.which("7za")
            if not seven_z_path:
                for p in [r"C:\Program Files\7-Zip\7z.exe", r"C:\Program Files (x86)\7-Zip\7z.exe"]:
                    if os.path.exists(p):
                        seven_z_path = p
                        break
            if not seven_z_path:
                print("  Warning: 7-Zip not found. Cannot decompress .Z file.")
                if os.path.exists(local_compressed):
                    os.remove(local_compressed)
                return None
            subprocess.run([seven_z_path, "x", f"-o{download_dir}", "-y", local_compressed],
                           check=True, capture_output=True)
            os.remove(local_compressed)
            return local_final if os.path.exists(local_final) else None

        # Already uncompressed.
        return local_compressed
    except Exception as e:
        print(f"  Decompression failed: {e}")
        if os.path.exists(local_compressed):
            os.remove(local_compressed)
        return None


def _fetch_http(url, local_path, timeout=60):
    """
    Anonymous HTTP(S) download via the standard library (no extra dependency).
    Works in the frozen .exe; HTTPS uses the Windows system certificate store,
    and any TLS/404 error is caught so the caller just tries the next source.
    Returns True only when a plausibly-real file (>10 kB) was written.
    """
    import urllib.request
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'RINEX-Masker'})
        with urllib.request.urlopen(req, timeout=timeout) as r, open(local_path, 'wb') as f:
            shutil.copyfileobj(r, f)
        if os.path.getsize(local_path) > 10000:
            return True
    except Exception:
        pass
    if os.path.exists(local_path):
        try:
            os.remove(local_path)
        except OSError:
            pass
    return False


def _fetch_cddis(url, local_path, timeout=90):
    """
    CDDIS download. It requires an Earthdata login (stored in ~/_netrc), which a
    plain distributed build usually does not have, so this is BEST-EFFORT: it is
    used only if `requests` is importable (it handles the netrc + OAuth redirect
    that urllib does not), and any failure just falls through to the next source.
    """
    try:
        import requests
    except ImportError:
        return False
    try:
        r = requests.get(url, timeout=timeout, stream=True)
        try:
            if r.status_code == 200:
                with open(local_path, 'wb') as f:
                    for chunk in r.iter_content(65536):
                        f.write(chunk)
        finally:
            r.close()
        if os.path.exists(local_path) and os.path.getsize(local_path) > 10000:
            return True
    except Exception:
        pass
    if os.path.exists(local_path):
        try:
            os.remove(local_path)
        except OSError:
            pass
    return False


def _fetch_ftp(host, remote_dir, filename, local_path, conns, cwds, timeout=30):
    """
    Anonymous FTP download, reusing one connection per host across candidates.
    A host that refuses the connection (e.g. IGN throttling) is remembered as
    dead for the rest of the call so we do not keep retrying it.
    """
    if host not in conns:
        try:
            c = FTP(host, timeout=timeout)
            c.login()  # anonymous
            conns[host] = c
            cwds[host] = None
        except Exception as e:
            print(f"  {host}: cannot connect ({e}) - skipping this source")
            conns[host] = None
    ftp = conns.get(host)
    if ftp is None:
        return False
    try:
        if cwds.get(host) != remote_dir:
            ftp.cwd(remote_dir)
            cwds[host] = remote_dir
        with open(local_path, 'wb') as f:
            ftp.retrbinary(f"RETR {filename}", f.write)
        return True
    except Exception:
        if os.path.exists(local_path):
            try:
                os.remove(local_path)
            except OSError:
                pass
        return False


def download_sp3(dt_obj, download_dir):
    """
    Download a MULTI-GNSS SP3 precise orbit file for a given date, trying several
    sources in turn (a fallback chain, like PCC-Explorer) so no single server
    being moved, frozen, or throttled can break it.

    Products are tried latency-ordered (all multi-GNSS, G/R/E/C[/J]):
        finals (most accurate) -> rapids (~1 day) -> ultra-rapid (predicted,
        usable almost immediately after a measurement).
    For each product these sources are tried, most-reliable-anonymous first:
        1. AIUB  http://www.aiub.unibe.ch/download/CODE_MGEX/CODE/<year>/  (CODE
           finals; anonymous HTTP)
        2. IGN   ftp://igs.ign.fr/pub/igs/products/<week>/  (all products;
           anonymous FTP, but rate-limits under heavy use)
        3. CDDIS https://cddis.nasa.gov/archive/gnss/products/<week>/  (all
           products; needs an Earthdata login, so best-effort only)
    GFZ's legacy GBM archive is kept last for older (pre-2023) dates.

    Args:
        dt_obj: datetime for the desired date
        download_dir: directory to save the file to

    Returns:
        Path to the downloaded/existing SP3 file, or None
    """
    os.makedirs(download_dir, exist_ok=True)

    mjd_val = _datetime_to_mjd(dt_obj)
    gps_week, _day_of_week = _mjd_to_gps_week(mjd_val)
    year_full = dt_obj.strftime('%Y')
    day_of_year = dt_obj.strftime('%j')

    def _fn(ac, campaign):
        # Modern IGS long-name SP3, e.g. GFZ0MGXRAP_20261950000_01D_05M_ORB.SP3.gz
        return f"{ac}0{campaign}_{year_full}{day_of_year}0000_01D_05M_ORB.SP3.gz"

    ign_dir = f"/pub/igs/products/{gps_week}"

    # Products in latency order; the first analysis centre of each row that has
    # a file wins. All are multi-GNSS.
    products = [
        ('COD', 'MGXFIN'), ('GRG', 'MGXFIN'), ('WUM', 'MGXFIN'),   # finals
        ('GFZ', 'MGXRAP'), ('HUS', 'MGXRAP'), ('SHA', 'MGXRAP'),   # rapids
        ('HUS', 'MGXULT'),                                          # ultra-rapid
    ]

    # Candidate list: (source_label, kind, location, filename). For each product,
    # try AIUB (CODE only) -> IGN -> CDDIS.
    candidates = []
    for ac, camp in products:
        fn = _fn(ac, camp)
        if ac == 'COD':   # AIUB only hosts CODE's own MGEX products
            candidates.append(('AIUB', 'http',
                f"http://www.aiub.unibe.ch/download/CODE_MGEX/CODE/{year_full}/{fn}", fn))
        candidates.append(('IGN', 'ftp', ('igs.ign.fr', ign_dir), fn))
        candidates.append(('CDDIS', 'cddis',
            f"https://cddis.nasa.gov/archive/gnss/products/{gps_week}/{fn}", fn))
    # Legacy GBM (pre-2023 dates): GFZ archive, then IGN.
    gbm = f"GBM0MGXRAP_{year_full}{day_of_year}0000_01D_05M_ORB.SP3.gz"
    candidates.append(('GFZ-legacy', 'ftp',
                       ('ftp.gfz-potsdam.de', f"/GNSS/products/mgex/{gps_week:04d}"), gbm))
    candidates.append(('IGN', 'ftp', ('igs.ign.fr', ign_dir), gbm))

    print(f"\nLooking for SP3 orbit file for {dt_obj.date()}...")

    # Check local cache first (any candidate already downloaded for this day).
    for _label, _kind, _loc, fn in candidates:
        local_final = _local_decompressed_name(download_dir, fn)
        if os.path.exists(local_final):
            print(f"  Using existing file: {local_final}")
            return local_final

    print("  Attempting download (finals -> rapids -> ultra-rapid; AIUB / IGN / CDDIS)...")
    ftp_conns, ftp_cwds = {}, {}   # reused across candidates, closed at the end
    try:
        for label, kind, loc, fn in candidates:
            local_compressed = os.path.join(download_dir, fn)
            local_final = _local_decompressed_name(download_dir, fn)
            print(f"  Trying {label}: {fn} ...")

            if kind == 'http':
                ok = _fetch_http(loc, local_compressed)
            elif kind == 'cddis':
                ok = _fetch_cddis(loc, local_compressed)
            else:  # ftp
                host, remote_dir = loc
                ok = _fetch_ftp(host, remote_dir, fn, local_compressed, ftp_conns, ftp_cwds)

            if not ok:
                continue

            print(f"  Download successful from {label}. Decompressing...")
            result = _decompress_sp3(local_compressed, local_final, download_dir)
            if result:
                return result
    finally:
        for c in ftp_conns.values():
            if c:
                try:
                    c.quit()
                except Exception:
                    pass

    print("  All SP3 download attempts failed (tried AIUB, IGN, CDDIS).")
    return None


# --- SP3 Parser (from PCC-Explorer data_io.py) ---

def read_sp3(filename):
    """
    Read an SP3 precise orbit file.
    
    Args:
        filename: Path to SP3 (.sp3 / .SP3) file
        
    Returns:
        dict: {'orbits': {system_char: {prn_int: [(datetime, np.ndarray), ...]}}}
    """
    orbit_data = {}
    current_epoch = None
    
    with open(filename, 'r') as f:
        for line in f:
            if line.startswith('*'):
                # Epoch line: *  2020  8  5  0  0  0.00000000
                try:
                    year = int(line[3:7])
                    mo = int(line[8:10])
                    day = int(line[11:13])
                    hr = int(line[14:16])
                    mn = int(line[17:19])
                    sec_full = float(line[20:31])
                    sec = int(sec_full)
                    micro = int(round((sec_full - sec) * 1e6))
                    current_epoch = datetime(year, mo, day, hr, mn, sec, micro)
                except (ValueError, IndexError):
                    continue
                    
            elif line.startswith('P') and current_epoch is not None:
                # Position line: PG01  15600.123456  -7894.123456  20314.123456  ...
                try:
                    system_char = line[1]
                    prn = int(line[2:4])
                    x = float(line[4:18]) * 1000.0   # km -> m
                    y = float(line[18:32]) * 1000.0
                    z = float(line[32:46]) * 1000.0
                    
                    # Skip bad positions (999999 = not available)
                    if abs(x) < 999999000.0:
                        if system_char not in orbit_data:
                            orbit_data[system_char] = {}
                        if prn not in orbit_data[system_char]:
                            orbit_data[system_char][prn] = []
                        orbit_data[system_char][prn].append(
                            (current_epoch, np.array([x, y, z], dtype=float))
                        )
                except (ValueError, IndexError):
                    continue
    
    # Summary
    summary_parts = []
    for sys_code, sats in orbit_data.items():
        sys_name = {'G': 'GPS', 'R': 'GLONASS', 'E': 'Galileo',
                    'C': 'BeiDou', 'J': 'QZSS'}.get(sys_code, sys_code)
        summary_parts.append(f"{len(sats)} {sys_name}")
    
    print(f"Parsed SP3: {', '.join(summary_parts) if summary_parts else 'No satellites found'}")
    return {'orbits': orbit_data}


# --- Orbit Interpolation (from PCC-Explorer orbit_utils.py) ---

def interpolate_orbit(orbit_records, target_time):
    """
    Linear interpolation of satellite position from SP3 records.
    
    Args:
        orbit_records: List of (datetime, position_array) tuples (sorted by time)
        target_time: datetime to interpolate to
        
    Returns:
        np.ndarray [x, y, z] or None if not enough data
    """
    if not orbit_records or len(orbit_records) < 2:
        return None

    before_record = None
    after_record = None

    for record in orbit_records:
        if record[0] <= target_time:
            before_record = record
        elif record[0] > target_time:
            after_record = record
            break

    # Normal case: target is bracketed by two nodes -> linear interpolation.
    if before_record and after_record:
        t_before, pos_before = before_record
        t_after, pos_after = after_record
        total_time_diff = (t_after - t_before).total_seconds()
        if total_time_diff == 0:
            return pos_before
        weight = (target_time - t_before).total_seconds() / total_time_diff
        return pos_before + weight * (pos_after - pos_before)

    # Boundary case: the SP3 grid does not reach this epoch (typically the last
    # few RINEX epochs of the day, because a daily SP3 ends ~5 min before 24:00).
    # Linearly EXTRAPOLATE from the two nearest nodes, but only within a small
    # tolerance (one sampling interval). This is accurate enough for an
    # elevation-mask decision and avoids dropping the final minutes as
    # "Not in SP3". Beyond the tolerance we still return None.
    MAX_EXTRAPOLATE_S = 360.0  # ~ one 5-min SP3 step
    recs = orbit_records
    if after_record is None and before_record is not None:
        gap = (target_time - recs[-1][0]).total_seconds()
        if 0 <= gap <= MAX_EXTRAPOLATE_S:
            t0, p0 = recs[-2]
            t1, p1 = recs[-1]
            dt = (t1 - t0).total_seconds()
            if dt == 0:
                return p1
            weight = (target_time - t0).total_seconds() / dt
            return p0 + weight * (p1 - p0)
    if before_record is None and after_record is not None:
        gap = (recs[0][0] - target_time).total_seconds()
        if 0 <= gap <= MAX_EXTRAPOLATE_S:
            t0, p0 = recs[0]
            t1, p1 = recs[1]
            dt = (t1 - t0).total_seconds()
            if dt == 0:
                return p0
            weight = (target_time - t0).total_seconds() / dt
            return p0 + weight * (p1 - p0)

    return None


# --- High-level API ---

def load_sp3(date_or_path, download_dir=None):
    """
    Load SP3 data from a file path or auto-download for a given date.
    
    Args:
        date_or_path: Either a datetime object (triggers download) or path to SP3 file
        download_dir: Directory for downloaded files (default: ./orbits/)
        
    Returns:
        dict: SP3 orbit data structure
    """
    if isinstance(date_or_path, datetime):
        if download_dir is None:
            download_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'orbits')
        sp3_path = download_sp3(date_or_path, download_dir)
        if sp3_path is None:
            raise FileNotFoundError(f"Could not download SP3 file for {date_or_path.date()}")
        return read_sp3(sp3_path)
    else:
        # Assume it's a file path
        if not os.path.exists(date_or_path):
            raise FileNotFoundError(f"SP3 file not found: {date_or_path}")
        return read_sp3(date_or_path)


def get_satellite_azel(sp3_data, station_xyz, epoch, sat_id):
    """
    Compute azimuth/elevation for a single satellite at a given epoch.
    
    Args:
        sp3_data: SP3 data dict from load_sp3()
        station_xyz: np.ndarray [x, y, z] of station in ECEF [m]
        epoch: datetime of the observation
        sat_id: Satellite ID string, e.g. "G10", "E01", "R03"
        
    Returns:
        (azimuth_deg, elevation_deg) or None if satellite not found
    """
    system_char = sat_id[0]
    prn = int(sat_id[1:])
    
    orbits = sp3_data.get('orbits', {})
    if system_char not in orbits or prn not in orbits[system_char]:
        return None
    
    records = orbits[system_char][prn]
    sat_pos = interpolate_orbit(records, epoch)
    
    if sat_pos is None:
        return None
    
    az, el = ecef_to_topocentric(station_xyz, sat_pos)
    return az, el


def get_all_satellite_azel(sp3_data, station_xyz, epoch, sat_ids):
    """
    Compute azimuth/elevation for multiple satellites at a given epoch.
    
    Args:
        sp3_data: SP3 data dict
        station_xyz: Station ECEF position
        epoch: datetime of observation
        sat_ids: List of satellite ID strings
        
    Returns:
        dict: {sat_id: (azimuth_deg, elevation_deg)} for satellites found in SP3
    """
    results = {}
    for sat_id in sat_ids:
        azel = get_satellite_azel(sp3_data, station_xyz, epoch, sat_id)
        if azel is not None:
            results[sat_id] = azel
    return results

def compute_dop(sat_azels):
    """
    Compute DOP values (GDOP, PDOP, HDOP, VDOP) for a given set of satellites.
    Uses multi-GNSS design matrix formulation with independent receiver clock state per constellation.
    
    Args:
        sat_azels: list of tuples (azimuth_deg, elevation_deg, constellation_char)
        
    Returns: 
        dict {'GDOP': float, 'PDOP': float, 'HDOP': float, 'VDOP': float} or None if geometry too weak.
    """
    if not sat_azels:
        return None
        
    systems = list(set(sat_info[2] for sat_info in sat_azels))
    num_systems = len(systems)
    num_sats = len(sat_azels)
    
    # We need at least 3 spatial coordinates + 1 clock per system
    if num_sats < 3 + num_systems:
        return None
        
    # Design matrix H: [n_sats x (3 + num_systems)]
    # State: [East, North, Up, c*dt_1, c*dt_2, ...]
    H = np.zeros((num_sats, 3 + num_systems))
    
    for i, (az_deg, el_deg, sys_char) in enumerate(sat_azels):
        az_rad = np.radians(az_deg)
        el_rad = np.radians(el_deg)
        
        # Unit vector pointing from receiver TO satellite (topocentric ENU)
        e_E = np.cos(el_rad) * np.sin(az_rad)
        e_N = np.cos(el_rad) * np.cos(az_rad)
        e_U = np.sin(el_rad)
        
        # Design matrix row (derivatives of rho w.r.t receiver pos)
        H[i, 0] = -e_E
        H[i, 1] = -e_N
        H[i, 2] = -e_U
        
        # Clock parameter flag (1 for the corresponding system clock)
        sys_idx = systems.index(sys_char)
        H[i, 3 + sys_idx] = 1.0
        
    try:
        Q = np.linalg.inv(H.T @ H)
        
        # Geometric DOP combines all states (position + clocks).
        # Multi-GNSS GDOP includes trace of all diagonal elements (PDOP^2 + sum(TDOP^2))
        gdop = np.sqrt(np.trace(Q))
        
        pdop = np.sqrt(Q[0, 0] + Q[1, 1] + Q[2, 2])
        hdop = np.sqrt(Q[0, 0] + Q[1, 1])
        vdop = np.sqrt(Q[2, 2])
        
        return {'GDOP': float(gdop), 'PDOP': float(pdop), 'HDOP': float(hdop), 'VDOP': float(vdop)}
        
    except np.linalg.LinAlgError:
        # Singular matrix (bad geometry)
        return None
