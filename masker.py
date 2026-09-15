# masker.py
"""
Core masking logic for RINEX-Masker.
Orchestrates: SP3 loading -> RINEX parsing -> az/el computation -> filtering -> output.
"""

import os
import sys
import copy
from datetime import datetime
from collections import defaultdict

import numpy as np

from satellite_position import load_sp3, get_satellite_azel
from rinex_handler import parse_rinex, iterate_epochs, write_rinex, Epoch, SatObs
from elevation_mask import ElevationMask
from config import CONSTELLATION_NAMES
import re


def apply_mask(rinex_path, sp3_path_or_date, mask, output_path,
               generate_skyplot=False, skyplot_epoch_index=0,
               log_callback=None, progress_callback=None,
               manual_position=None, time_start=None, time_end=None,
               cn0_threshold=0.0, cn0_obs_code=None,
               cn0_per_signal=None):
    """
    Apply an elevation/azimuth mask to a RINEX observation file.
    
    Args:
        rinex_path: Path to input RINEX observation file
        sp3_path_or_date: Path to SP3 file, or datetime for auto-download, or None for auto
        mask: ElevationMask object defining the obstruction zones
        output_path: Path for the filtered output RINEX file
        generate_skyplot: If True, generate before/after skyplot
        skyplot_epoch_index: Which epoch to use for skyplot (default: first epoch)
        log_callback: Optional function(str) to send log messages to GUI
        progress_callback: Optional function(float) to update progress bar (0.0-1.0)
        manual_position: Optional [X, Y, Z] ECEF in metres to override RINEX header
        time_start: Optional datetime - only process epochs >= this time
        time_end: Optional datetime - only process epochs <= this time
        cn0_threshold: Optional float - minimum C/N0 value in dB-Hz (0 = disabled)
        cn0_obs_code: Optional str - which S-observable to use (e.g., 'S1C', 'S2W')
                      If None and cn0_threshold > 0, auto-detect first S-type observable
        cn0_per_signal: Optional dict - per-signal overrides {(sys_char, obs_code): threshold}
                        e.g. {('G', 'S2W'): 20.0, ('E', 'S5Q'): 18.0}
                        These override cn0_threshold for their specific signal.
        
    Returns:
        dict with summary statistics
    """
    def log(msg):
        if log_callback:
            log_callback(msg)
        else:
            print(msg)
    
    def progress(frac):
        if progress_callback:
            progress_callback(frac)
    
    # --- 1. Parse RINEX ---
    progress(0.0)
    log(f"Parsing RINEX file: {rinex_path}")
    header, lines, header_end_idx = parse_rinex(rinex_path)
    
    # Use manual position if provided, otherwise from RINEX header
    if manual_position is not None:
        station_xyz = np.array(manual_position, dtype=float)
        log(f"  Station: {header.marker_name}")
        log(f"  Position (MANUAL): X={station_xyz[0]:.3f}, Y={station_xyz[1]:.3f}, Z={station_xyz[2]:.3f}")
    else:
        station_xyz = np.array(header.station_xyz)
        log(f"  Station: {header.marker_name}")
        log(f"  Position (RINEX header): X={station_xyz[0]:.3f}, Y={station_xyz[1]:.3f}, Z={station_xyz[2]:.3f}")
    
    log(f"  Interval: {header.interval}s")
    log(f"  Systems: {', '.join(header.obs_types.keys())}")
    log(f"  Mask: {mask}")
    log(f"  {mask.summary()}")
    
    if time_start or time_end:
        ts_str = time_start.strftime("%Y-%m-%d %H:%M:%S") if time_start else "start"
        te_str = time_end.strftime("%Y-%m-%d %H:%M:%S") if time_end else "end"
        log(f"  Time filter: {ts_str} to {te_str}")
    
    # C/N0 filtering setup
    cn0_active = cn0_threshold > 0.0
    cn0_per_signal = cn0_per_signal or {}
    if cn0_per_signal:
        cn0_active = True  # Enable if any per-signal thresholds provided
    if cn0_active:
        log(f"  C/N0 threshold: >= {cn0_threshold:.1f} dB-Hz (global)")
        if cn0_per_signal:
            for (sc, oc), thr in cn0_per_signal.items():
                log(f"    Per-signal override: {sc}/{oc} >= {thr:.1f} dB-Hz")
        # Determine S-observable index for each system
        cn0_obs_indices = {}  # {sys_char: [(obs_code, index, threshold)]}
        for sys_char, obs_list in header.obs_types.items():
            entries = []
            # Check for per-signal overrides first
            for (sc, oc), thr in cn0_per_signal.items():
                if sc == sys_char and oc in obs_list:
                    entries.append((oc, obs_list.index(oc), thr))
            # If no per-signal override and global is active, use first S-type
            if not entries and cn0_threshold > 0.0:
                if cn0_obs_code and cn0_obs_code in obs_list:
                    entries.append((cn0_obs_code, obs_list.index(cn0_obs_code), cn0_threshold))
                else:
                    for idx, ot in enumerate(obs_list):
                        if ot.startswith('S'):
                            entries.append((ot, idx, cn0_threshold))
                            break
            if entries:
                cn0_obs_indices[sys_char] = entries
        if cn0_obs_indices:
            log(f"  C/N0 observable indices: {cn0_obs_indices}")
        else:
            log(f"  WARNING: No S-type observables found, C/N0 filter disabled")
            cn0_active = False
    
    progress(0.05)
    
    # --- 2. Load SP3 orbit data ---
    log("\nLoading SP3 orbit data...")
    if isinstance(sp3_path_or_date, str):
        sp3_data = load_sp3(sp3_path_or_date)
    elif isinstance(sp3_path_or_date, datetime):
        sp3_data = load_sp3(sp3_path_or_date)
    else:
        # Auto-detect date from RINEX header
        if header.first_obs_time:
            log(f"  Auto-downloading SP3 for {header.first_obs_time.date()}")
            sp3_data = load_sp3(header.first_obs_time)
        else:
            raise ValueError("Cannot determine date for SP3 download. "
                           "Provide SP3 path or date explicitly.")
    
    # Report SP3 content
    orbits = sp3_data.get('orbits', {})
    for sys_code, sats in orbits.items():
        sys_name = {'G': 'GPS', 'R': 'GLONASS', 'E': 'Galileo',
                    'C': 'BeiDou', 'J': 'QZSS'}.get(sys_code, sys_code)
        log(f"  SP3: {len(sats)} {sys_name} satellites")
    
    progress(0.15)
    
    # --- 3. Count total epochs for progress ---
    log("\nCounting epochs...")
    total_epoch_count = sum(1 for _ in iterate_epochs(lines, header_end_idx))
    log(f"  Total epochs: {total_epoch_count}")
    
    progress(0.20)
    
    # --- 4. Process epochs ---
    log("\nProcessing epochs...")
    filtered_epochs = []
    
    # Statistics
    stats = {
        'total_epochs': 0,
        'total_sats_original': 0,
        'total_sats_kept': 0,
        'total_sats_removed': 0,
        'sats_no_sp3': 0,
        'sats_cn0_removed': 0,
        'epochs_skipped_time': 0,
        'per_constellation_original': defaultdict(int),
        'per_constellation_kept': defaultdict(int),
        'per_constellation_removed': defaultdict(int),
        'per_constellation_no_sp3': defaultdict(int),   # obs kept because sat absent from SP3
        'no_sp3_prns': defaultdict(int),                # {sat_id: obs count} for those sats
        'station_name': header.marker_name,
        'station_xyz': station_xyz.tolist(),
        'epoch_timestamps': [],  # real datetime for DOP x-axis
    }
    
    # For skyplot: collect ALL positions across ALL epochs for full arcs
    skyplot_all_arcs = defaultdict(list)       # {sat_id: [(az, el), ...]}
    skyplot_visible_arcs = defaultdict(list)   # {sat_id: [(az, el), ...]}
    # For azi/elev CSV export (PCC-Explorer LoS format)
    los_observations = []  # [(epoch_utc_str, prn, elevation_deg, azimuth_deg), ...]
    first_epoch_time = None
    last_epoch_time = None
    
    for epoch in iterate_epochs(lines, header_end_idx):
        stats['total_epochs'] += 1
        
        # --- Time filter ---
        if time_start and epoch.timestamp < time_start:
            stats['epochs_skipped_time'] += 1
            continue
        if time_end and epoch.timestamp > time_end:
            stats['epochs_skipped_time'] += 1
            continue
        
        # Track time span
        if first_epoch_time is None:
            first_epoch_time = epoch.timestamp
        last_epoch_time = epoch.timestamp
        
        kept_satellites = []
        
        # Track epoch timestamp for DOP x-axis
        stats['epoch_timestamps'].append(epoch.timestamp)
        
        # Temporary lists to hold azimuth/elevation for DOP calculation at this epoch
        epoch_sats_before = []
        epoch_sats_after = []
        
        for sat_obs in epoch.satellites:
            sat_id = sat_obs.sat_id
            sys_char = sat_id[0] if sat_id else '?'
            stats['total_sats_original'] += 1
            stats['per_constellation_original'][sys_char] += 1
            
            # C/N0 check (before az/el computation)
            if cn0_active and sys_char in cn0_obs_indices:
                removed_by_cn0 = False
                for obs_code, s_idx, threshold in cn0_obs_indices[sys_char]:
                    cn0_val = _extract_obs_value(sat_obs.raw_line, s_idx)
                    if cn0_val is not None and cn0_val < threshold:
                        removed_by_cn0 = True
                        break
                if removed_by_cn0:
                    stats['total_sats_removed'] += 1
                    stats['per_constellation_removed'][sys_char] += 1
                    stats['sats_cn0_removed'] += 1
                    continue
            
            azel = get_satellite_azel(sp3_data, station_xyz, epoch.timestamp, sat_id)
            
            if azel is None:
                kept_satellites.append(sat_obs)
                stats['total_sats_kept'] += 1
                stats['per_constellation_kept'][sys_char] += 1
                stats['sats_no_sp3'] += 1
                stats['per_constellation_no_sp3'][sys_char] += 1
                stats['no_sp3_prns'][sat_id] += 1
                continue
            
            az, el = azel
            epoch_sats_before.append((az, el, sys_char))
            
            # Collect for azi/elev CSV export (all observations)
            epoch_str = epoch.timestamp.strftime('%Y-%m-%d %H:%M:%S')
            los_observations.append((epoch_str, sat_id, el, az))
            
            # Collect for full-arc skyplot (all epochs)
            if generate_skyplot:
                skyplot_all_arcs[sat_id].append((az, el))
                if not mask.is_obstructed(az, el):
                    skyplot_visible_arcs[sat_id].append((az, el))
            
            if mask.is_obstructed(az, el):
                stats['total_sats_removed'] += 1
                stats['per_constellation_removed'][sys_char] += 1
            else:
                kept_satellites.append(sat_obs)
                stats['total_sats_kept'] += 1
                stats['per_constellation_kept'][sys_char] += 1
                epoch_sats_after.append((az, el, sys_char))
                
        # Calculate DOP for the epoch using the design matrix method
        from satellite_position import compute_dop
        dop_before = compute_dop(epoch_sats_before)
        if dop_before:
            if 'dop_before' not in stats:
                stats['dop_before'] = {'PDOP': [], 'VDOP': [], 'time': []}
            stats['dop_before']['PDOP'].append(dop_before['PDOP'])
            stats['dop_before']['VDOP'].append(dop_before['VDOP'])
            # Keep a timestamp per DOP sample so the plot stays on real time even
            # when weak-geometry epochs produce no DOP (arrays would otherwise
            # desync from epoch_timestamps and mis-place the curve).
            stats['dop_before']['time'].append(epoch.timestamp)

        dop_after = compute_dop(epoch_sats_after)
        if dop_after:
            if 'dop_after' not in stats:
                stats['dop_after'] = {'PDOP': [], 'VDOP': [], 'time': []}
            stats['dop_after']['PDOP'].append(dop_after['PDOP'])
            stats['dop_after']['VDOP'].append(dop_after['VDOP'])
            stats['dop_after']['time'].append(epoch.timestamp)
        
        filtered_epoch = Epoch(
            timestamp=epoch.timestamp,
            flag=epoch.flag,
            num_sats=len(kept_satellites),
            raw_epoch_line=epoch.raw_epoch_line,
            satellites=kept_satellites
        )
        filtered_epochs.append(filtered_epoch)
        
        # Progress: 20% to 85% for epoch processing
        if total_epoch_count > 0:
            epoch_frac = 0.20 + 0.65 * (stats['total_epochs'] / total_epoch_count)
            if stats['total_epochs'] % 100 == 0:
                progress(epoch_frac)
        
        if stats['total_epochs'] % 500 == 0:
            log(f"  Processed {stats['total_epochs']}/{total_epoch_count} epochs...")
    
    progress(0.85)
    
    # Store time span
    stats['first_epoch'] = first_epoch_time
    stats['last_epoch'] = last_epoch_time
    
    # --- 5. Create result folder and write outputs ---
    # Create a timestamped results subfolder next to the output file
    output_dir = os.path.dirname(output_path) or '.'
    output_name = os.path.basename(output_path)
    timestamp_str = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    station_name = header.marker_name.strip() if header.marker_name else "unknown"
    result_folder = os.path.join(output_dir, "results",
                                 f"{timestamp_str}_{station_name}")
    os.makedirs(result_folder, exist_ok=True)
    
    # Redirect output path into result folder
    output_path = os.path.join(result_folder, output_name)
    stats['result_folder'] = result_folder
    
    log(f"\nResult folder: {result_folder}")
    log(f"Writing filtered RINEX to: {output_path}")
    mask_info = mask.summary()
    write_rinex(output_path, header, filtered_epochs, mask_info=mask_info,
                first_epoch=first_epoch_time, last_epoch=last_epoch_time)
    log(f"  Written {len(filtered_epochs)} epochs.")
    
    # Save processing summary
    summary_path = os.path.join(result_folder, "processing_summary.txt")
    with open(summary_path, 'w') as f:
        f.write(f"RINEX-Masker Processing Summary\n")
        f.write(f"{'='*50}\n")
        f.write(f"Processing Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"Input File: {rinex_path}\n")
        f.write(f"Output File: {output_path}\n")
        f.write(f"Station: {station_name}\n")
        f.write(f"Position (ECEF): {station_xyz.tolist()}\n")
        f.write(f"Mask: {mask_info}\n")
        if cn0_active:
            f.write(f"C/N0 Threshold: {cn0_threshold:.1f} dB-Hz\n")
        if time_start or time_end:
            f.write(f"Time Filter: {time_start} to {time_end}\n")
        f.write(f"\nStatistics:\n")
        f.write(f"  Total epochs: {stats['total_epochs']}\n")
        f.write(f"  First epoch: {first_epoch_time}\n")
        f.write(f"  Last epoch: {last_epoch_time}\n")
        f.write(f"  Observations kept: {stats.get('total_sats_kept', 'N/A')}\n")
        f.write(f"  Observations removed: {stats.get('total_sats_removed', 'N/A')}\n")
    
    # Save mask definition
    mask_json_path = os.path.join(result_folder, "mask_definition.json")
    mask.save_json(mask_json_path)
    log(f"  Mask saved to: {mask_json_path}")
    
    # Save azi/elev CSV in PCC-Explorer LoS format
    if los_observations:
        import csv
        los_csv_path = os.path.join(result_folder, "los_observations.csv")
        with open(los_csv_path, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['epoch_utc', 'prn', 'elevation_deg', 'azimuth_deg'])
            for epoch_str, prn, el, az in los_observations:
                writer.writerow([epoch_str, prn, f'{el:.6f}', f'{az:.6f}'])
        log(f"  LoS observations CSV: {los_csv_path} ({len(los_observations)} obs)")
        stats['los_csv_path'] = los_csv_path
    
    progress(0.90)
    
    # --- 6. Print summary ---
    summary = _format_summary(stats)
    log(summary)
    
    # --- 7. Generate skyplot ---
    if generate_skyplot and skyplot_all_arcs:
        log("\nGenerating skyplot...")
        from skyplot import plot_before_after
        skyplot_save = output_path.rsplit('.', 1)[0] + '_skyplot.png'
        # In GUI mode (log_callback set), only save the file -- don't plt.show()
        # from a background thread. The GUI will show it on the main thread.
        should_show = (log_callback is None)
        
        # Build metadata for skyplot annotation
        skyplot_meta = {
            'station': header.marker_name,
            'first_epoch': first_epoch_time,
            'last_epoch': last_epoch_time,
            'position': station_xyz.tolist(),
        }
        
        plot_before_after(skyplot_all_arcs, skyplot_visible_arcs, mask=mask,
                         save_path=skyplot_save, show=should_show,
                         metadata=skyplot_meta)
        log(f"Skyplot saved to: {skyplot_save}")
        stats['skyplot_path'] = skyplot_save

    if 'dop_before' in stats:
        from skyplot import plot_dop_timeseries
        dop_save = output_path.rsplit('.', 1)[0] + '_dop.png'
        should_show = (log_callback is None)
        plot_dop_timeseries(stats, save_path=dop_save, show=should_show)
        stats['dop_plot_path'] = dop_save
    
    progress(1.0)
    log("\n[OK] Done!")
    
    # Store skyplot data in stats for GUI access
    stats['skyplot_all'] = dict(skyplot_all_arcs)
    stats['skyplot_visible'] = dict(skyplot_visible_arcs)
    
    return stats


def _extract_obs_value(raw_line: str, obs_index: int) -> float:
    """
    Extract an observation value from a RINEX 3.x satellite data line.
    
    Each observation occupies 16 characters (14.3f + 2 flags), starting at col 3.
    
    Args:
        raw_line: Raw satellite observation line
        obs_index: 0-based index of the observable in the system's obs type list
        
    Returns:
        float value or None if blank/unparseable
    """
    start = 3 + obs_index * 16
    end = start + 14
    if end > len(raw_line):
        return None
    val_str = raw_line[start:end].strip()
    if not val_str:
        return None
    try:
        return float(val_str)
    except ValueError:
        return None


def _format_summary(stats):
    """Format a summary of the masking results."""
    lines = []
    lines.append("\n" + "=" * 60)
    lines.append("RINEX-Masker Summary")
    lines.append("=" * 60)
    lines.append(f"  Epochs processed:     {stats['total_epochs']}")
    lines.append(f"  Total observations:   {stats['total_sats_original']}")
    lines.append(f"  Kept:                 {stats['total_sats_kept']} "
                 f"({100 * stats['total_sats_kept'] / max(1, stats['total_sats_original']):.1f}%)")
    lines.append(f"  Removed:              {stats['total_sats_removed']} "
                 f"({100 * stats['total_sats_removed'] / max(1, stats['total_sats_original']):.1f}%)")
    
    if stats['sats_no_sp3'] > 0:
        lines.append(f"  Not in SP3 (kept):    {stats['sats_no_sp3']}")
        lines.append(f"      -> observations whose satellite has no orbit in the SP3 file, so")
        lines.append(f"        azimuth/elevation cannot be computed. They are KEPT unchanged")
        lines.append(f"        (the mask cannot be applied without a satellite position).")

        # Break the count down by constellation + PRN so it is obvious WHICH
        # satellites are missing (typically SBAS, which precise orbit products do
        # not contain, and a few excluded/geostationary PRNs).
        per_sys = stats.get('per_constellation_no_sp3', {})
        prns = stats.get('no_sp3_prns', {})
        by_sys_prns = defaultdict(list)
        for prn in sorted(prns):
            by_sys_prns[prn[0]].append(prn)
        for sys_char in sorted(per_sys):
            name = CONSTELLATION_NAMES.get(sys_char, sys_char)
            note = "  (no precise orbits exist for SBAS)" if sys_char == 'S' else ""
            plist = ", ".join(by_sys_prns.get(sys_char, []))
            lines.append(f"        - {name:<8} {per_sys[sys_char]:>8}  [{plist}]{note}")

    if stats.get('epochs_skipped_time', 0) > 0:
        lines.append(f"  Epochs outside time:  {stats['epochs_skipped_time']} (excluded from output)")
        
    if stats.get('sats_cn0_removed', 0) > 0:
        lines.append(f"  C/N0 removed:         {stats['sats_cn0_removed']}")
    
    # --- DOP Information ---
    if 'dop_before' in stats and stats['dop_before']['PDOP']:
        pdop_b = sum(stats['dop_before']['PDOP']) / len(stats['dop_before']['PDOP'])
        vdop_b = sum(stats['dop_before']['VDOP']) / len(stats['dop_before']['VDOP'])
        lines.append(f"\n  Average DOP Before:   PDOP={pdop_b:.2f}, VDOP={vdop_b:.2f}")
    if 'dop_after' in stats and stats['dop_after']['PDOP']:
        pdop_a = sum(stats['dop_after']['PDOP']) / len(stats['dop_after']['PDOP'])
        vdop_a = sum(stats['dop_after']['VDOP']) / len(stats['dop_after']['VDOP'])
        lines.append(f"  Average DOP After:    PDOP={pdop_a:.2f}, VDOP={vdop_a:.2f}")
    elif 'dop_before' in stats and stats['dop_before']['PDOP']:
        lines.append(f"  Average DOP After:    Geometric configuration too weak (Insufficient Sats)")
    
    lines.append(f"\n  {'System':<12} {'Original':>10} {'Kept':>10} {'Removed':>10}")
    lines.append(f"  {'-'*12} {'-'*10} {'-'*10} {'-'*10}")
    
    all_systems = sorted(set(
        list(stats['per_constellation_original'].keys()) +
        list(stats['per_constellation_kept'].keys())
    ))
    
    for sys_char in all_systems:
        name = CONSTELLATION_NAMES.get(sys_char, sys_char)
        orig = stats['per_constellation_original'].get(sys_char, 0)
        kept = stats['per_constellation_kept'].get(sys_char, 0)
        removed = stats['per_constellation_removed'].get(sys_char, 0)
        lines.append(f"  {name:<12} {orig:>10} {kept:>10} {removed:>10}")
    
    lines.append("=" * 60)
    return "\n".join(lines)


def _print_summary(stats):
    """Print a summary of the masking results."""
    print(_format_summary(stats))
