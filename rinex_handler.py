# rinex_handler.py
"""
RINEX 3.x observation file parser and writer for RINEX-Masker.

This is entirely new code — PCC-Explorer does not parse RINEX observation files.
The parser is designed for memory efficiency, yielding one epoch at a time.
"""

import re
from datetime import datetime
from dataclasses import dataclass, field
from typing import List, Tuple, Generator


@dataclass
class RINEXHeader:
    """Parsed RINEX header information."""
    version: float = 3.04
    marker_name: str = ""
    station_xyz: list = field(default_factory=lambda: [0.0, 0.0, 0.0])  # APPROX POSITION XYZ [m]
    obs_types: dict = field(default_factory=dict)   # {system_char: [obs_type_strings]}
    interval: float = 30.0       # Observation interval [s]
    header_lines: list = field(default_factory=list) # Raw header lines (preserved verbatim)
    first_obs_time: datetime = None
    

@dataclass
class SatObs:
    """One satellite's observation data within an epoch."""
    sat_id: str       # e.g., "G10", "E01", "R03", "C21"
    raw_line: str     # Raw observation line (preserved for output)


@dataclass 
class Epoch:
    """One epoch of RINEX observations."""
    timestamp: datetime
    flag: int               # Epoch flag (0 = OK)
    num_sats: int           # Number of satellites in this epoch
    raw_epoch_line: str     # Raw epoch header line (e.g., "> 2020 08 05 ...")
    satellites: List[SatObs] = field(default_factory=list)


def parse_header(lines):
    """
    Parse the RINEX 3.x header.
    
    Args:
        lines: List of file lines (or iterable)
        
    Returns:
        (RINEXHeader, header_end_index)
    """
    header = RINEXHeader()
    header_end_idx = 0
    
    i = 0
    while i < len(lines):
        line = lines[i]
        header.header_lines.append(line)
        
        # Extract label (columns 60+)
        label = line[60:].strip() if len(line) > 60 else ""
        
        if 'RINEX VERSION' in label:
            try:
                header.version = float(line[:20].strip())
            except ValueError:
                pass
                
        elif 'MARKER NAME' in label:
            header.marker_name = line[:60].strip()
            
        elif 'APPROX POSITION XYZ' in label:
            try:
                parts = line[:60].split()
                header.station_xyz = [float(parts[0]), float(parts[1]), float(parts[2])]
            except (ValueError, IndexError):
                pass
                
        elif 'SYS / # / OBS TYPES' in label:
            # First line of obs types for a system
            system_char = line[0].strip()
            if system_char:
                try:
                    num_obs = int(line[3:6])
                except ValueError:
                    num_obs = 0
                    
                # Parse observation type codes (columns 7-58, 4 chars each)
                obs_types = []
                raw = line[6:58]
                for j in range(0, len(raw), 4):
                    ot = raw[j:j+4].strip()
                    if ot:
                        obs_types.append(ot)
                
                # Handle continuation lines (more than 13 obs types)
                while len(obs_types) < num_obs and (i + 1) < len(lines):
                    next_line = lines[i + 1]
                    next_label = next_line[60:].strip() if len(next_line) > 60 else ""
                    if 'SYS / # / OBS TYPES' in next_label and next_line[0] == ' ':
                        i += 1
                        header.header_lines.append(lines[i])
                        raw = lines[i][6:58]
                        for j in range(0, len(raw), 4):
                            ot = raw[j:j+4].strip()
                            if ot:
                                obs_types.append(ot)
                    else:
                        break
                
                header.obs_types[system_char] = obs_types[:num_obs]
                
        elif 'INTERVAL' in label:
            try:
                header.interval = float(line[:20].strip())
            except ValueError:
                pass
                
        elif 'TIME OF FIRST OBS' in label:
            try:
                parts = line[:60].split()
                header.first_obs_time = datetime(
                    int(parts[0]), int(parts[1]), int(parts[2]),
                    int(parts[3]), int(parts[4]), int(float(parts[5]))
                )
            except (ValueError, IndexError):
                pass
                
        elif 'END OF HEADER' in label:
            header_end_idx = i + 1
            break
        
        i += 1
    
    return header, header_end_idx


def iterate_epochs(lines, header_end_idx):
    """
    Generator that yields Epoch objects one at a time.
    Memory-efficient: doesn't store all epochs simultaneously.
    
    Args:
        lines: List of file lines
        header_end_idx: Index where data starts (after header)
        
    Yields:
        Epoch objects
    """
    i = header_end_idx
    
    while i < len(lines):
        line = lines[i]
        
        # Epoch line starts with '>'
        if line.startswith('>'):
            try:
                # Parse epoch line: > YYYY MM DD HH MM SS.SSSSSSS  flag numSat
                year = int(line[2:6])
                month = int(line[7:9])
                day = int(line[10:12])
                hour = int(line[13:15])
                minute = int(line[16:18])
                sec_full = float(line[19:29])
                sec = int(sec_full)
                micro = int(round((sec_full - sec) * 1e6))
                
                flag = int(line[31:32].strip() or '0')
                num_sats = int(line[32:35].strip())
                
                timestamp = datetime(year, month, day, hour, minute, sec, micro)
                
                epoch = Epoch(
                    timestamp=timestamp,
                    flag=flag,
                    num_sats=num_sats,
                    raw_epoch_line=line
                )
                
                # Read satellite lines
                for j in range(num_sats):
                    sat_idx = i + 1 + j
                    if sat_idx < len(lines):
                        sat_line = lines[sat_idx]
                        sat_id = sat_line[0:3].strip()
                        epoch.satellites.append(SatObs(sat_id=sat_id, raw_line=sat_line))
                
                i += 1 + num_sats
                yield epoch
                
            except (ValueError, IndexError) as e:
                # Skip malformed epoch
                i += 1
                continue
        else:
            i += 1


def parse_rinex(filepath):
    """
    Parse a complete RINEX file.
    
    Args:
        filepath: Path to the RINEX observation file
        
    Returns:
        (RINEXHeader, list_of_lines, header_end_idx) for use with iterate_epochs
    """
    print(f"\nParsing RINEX file: {filepath}")
    
    with open(filepath, 'r', encoding='ascii', errors='ignore') as f:
        lines = f.readlines()
    
    header, header_end_idx = parse_header(lines)
    
    print(f"  Version: {header.version}")
    print(f"  Station: {header.marker_name}")
    print(f"  Position: X={header.station_xyz[0]:.3f}, Y={header.station_xyz[1]:.3f}, Z={header.station_xyz[2]:.3f}")
    print(f"  Interval: {header.interval}s")
    print(f"  Systems: {', '.join(header.obs_types.keys())}")
    
    return header, lines, header_end_idx


def _rebuild_time_of_obs_line(dt, time_system, label):
    """
    Build a RINEX 3.x 'TIME OF FIRST/LAST OBS' header record for datetime `dt`.

    Format (RINEX 3.x): 5I6, F13.7, 5X, A3  ->  Y M D H M, seconds, time system,
    with the descriptor label starting at column 61 (0-based 60).
    """
    sec = dt.second + dt.microsecond / 1e6
    data = (f"{dt.year:6d}{dt.month:6d}{dt.day:6d}"
            f"{dt.hour:6d}{dt.minute:6d}{sec:13.7f}"
            f"     {time_system:<3}")
    return f"{data:<60}{label:<20}\n"


def write_rinex(output_path, header, filtered_epochs, mask_info=None,
                first_epoch=None, last_epoch=None):
    """
    Write a filtered RINEX file.

    Args:
        output_path: Path to write the output file
        header: RINEXHeader (header lines are preserved verbatim)
        filtered_epochs: List of Epoch objects (with satellites already filtered)
        mask_info: Optional string describing the mask applied (inserted as COMMENT)
        first_epoch: Optional datetime of the first epoch actually written. When
                     given, the 'TIME OF FIRST OBS' header record is updated to match.
        last_epoch: Optional datetime of the last epoch actually written. When given,
                    the 'TIME OF LAST OBS' record is updated (or inserted if absent).
    """
    print(f"\nWriting filtered RINEX to: {output_path}")

    # Determine the time system from the existing TIME OF FIRST OBS record so any
    # rebuilt/inserted epoch records keep the file's own time scale (GPS/GAL/...).
    time_system = 'GPS'
    has_last_obs = False
    for line in header.header_lines:
        lbl = line[60:].strip() if len(line) > 60 else ""
        if 'TIME OF FIRST OBS' in lbl:
            ts = line[48:51].strip()
            if ts:
                time_system = ts
        elif 'TIME OF LAST OBS' in lbl:
            has_last_obs = True
    
    # Build manipulation comment lines (RINEX COMMENT records)
    from datetime import datetime as _dt
    now_str = _dt.now().strftime("%Y-%m-%d %H:%M")
    comment_lines = [
        f"{'RINEX-Masker v1.0 - Modified file':<60}COMMENT\n",
        f"{'Processed: ' + now_str:<60}COMMENT\n",
    ]
    if mask_info:
        # Split mask_info by lines, then fit each into 60-char COMMENT records
        for info_line in mask_info.strip().split('\n'):
            info_line = info_line.strip()
            if not info_line:
                continue
            text = info_line[:54]
            comment_lines.append(f"{text:<60}COMMENT\n")
    
    with open(output_path, 'w', encoding='ascii') as f:
        # Write header, inserting comments before END OF HEADER and updating the
        # epoch-span records to reflect what is actually written out.
        for line in header.header_lines:
            label = line[60:].strip() if len(line) > 60 else ""

            if first_epoch is not None and 'TIME OF FIRST OBS' in label:
                f.write(_rebuild_time_of_obs_line(first_epoch, time_system,
                                                  'TIME OF FIRST OBS'))
                # If the file had no TIME OF LAST OBS record, add one right after
                # FIRST OBS (the conventional position).
                if last_epoch is not None and not has_last_obs:
                    f.write(_rebuild_time_of_obs_line(last_epoch, time_system,
                                                      'TIME OF LAST OBS'))
                continue

            if last_epoch is not None and 'TIME OF LAST OBS' in label:
                f.write(_rebuild_time_of_obs_line(last_epoch, time_system,
                                                  'TIME OF LAST OBS'))
                continue

            if 'END OF HEADER' in label:
                for cl in comment_lines:
                    f.write(cl)
            f.write(line)
        
        # Write epochs
        for epoch in filtered_epochs:
            num_sats = len(epoch.satellites)
            
            if num_sats == 0:
                continue  # Skip empty epochs
            
            # Reconstruct epoch line with updated satellite count
            # Format: > YYYY MM DD HH MM SS.SSSSSSS  flag numSat
            ts = epoch.timestamp
            epoch_line = (
                f"> {ts.year:4d} {ts.month:02d} {ts.day:02d} "
                f"{ts.hour:02d} {ts.minute:02d} "
                f"{ts.second:2d}.{ts.microsecond:07d}  "
                f"{epoch.flag:d}{num_sats:3d}\n"
            )
            f.write(epoch_line)
            
            # Write satellite observation lines
            for sat_obs in epoch.satellites:
                f.write(sat_obs.raw_line)
    
    print(f"  Done. Written {len(filtered_epochs)} epochs.")

