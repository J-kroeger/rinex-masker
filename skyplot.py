# skyplot.py
"""
Skyplot visualization for RINEX-Masker.
Adapted from PCC-Explorer's plotting.py plot_skyplot() function.

Generates polar skyplots showing satellite positions/arcs and obstruction masks.
"""

import numpy as np
import matplotlib
matplotlib.use('TkAgg')  # Force interactive backend (required for PyInstaller)
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap
from config import CONSTELLATION_COLORS, CONSTELLATION_NAMES


def build_satellite_colors(sat_ids):
    """
    Assign a unique, stable colour to every individual satellite (PRN).

    A per-constellation 3-colour scheme makes it
    impossible to tell individual satellites apart, so give each satellite its
    own colour from a large qualitative palette. The mapping is built once from
    the full set of satellites and reused for the before/after plots so a given
    satellite keeps the same colour on both sides.

    Args:
        sat_ids: iterable of satellite IDs (e.g. 'G01', 'E12').

    Returns:
        dict {sat_id: (r, g, b, a)} colour for each satellite.
    """
    sat_ids = sorted(sat_ids)
    n = len(sat_ids)
    if n == 0:
        return {}

    # Concatenate the three 20-colour qualitative maps (60 distinct colours);
    # for anything beyond that, sample the continuous 'gist_ncar' map so even
    # 100+ satellites stay visually distinct.
    base = []
    for name in ('tab20', 'tab20b', 'tab20c'):
        base.extend(plt.get_cmap(name).colors)
    if n <= len(base):
        colors = base[:n]
    else:
        cmap = plt.get_cmap('gist_ncar')
        colors = [cmap(i / max(1, n - 1)) for i in range(n)]

    return {sat_id: colors[i] for i, sat_id in enumerate(sat_ids)}


def _plot_satellites(ax, sat_positions, sat_colors=None):
    """
    Plot satellites on a polar axes. Handles both single positions and arcs.

    Args:
        ax: matplotlib polar axes
        sat_positions: dict {sat_id: (az, el)}  -- single point
                    or dict {sat_id: [(az, el), ...]}  -- arc/track
        sat_colors: optional dict {sat_id: colour} for a unique colour per
                    satellite. Falls back to the per-constellation colour when
                    a satellite is missing from the map.
    """
    constellation_counts = {}

    for sat_id, positions in sat_positions.items():
        system = sat_id[0]
        if sat_colors is not None and sat_id in sat_colors:
            color = sat_colors[sat_id]
        else:
            color = CONSTELLATION_COLORS.get(system, '#999999')

        if system not in constellation_counts:
            constellation_counts[system] = 0
        constellation_counts[system] += 1
        
        if isinstance(positions, tuple) and len(positions) == 2:
            # Single position: (az, el)
            az, el = positions
            az_rad = np.deg2rad(az)
            r = 90.0 - el
            ax.scatter(az_rad, r, c=color, s=30, alpha=0.8, zorder=5)
            ax.annotate(sat_id, (az_rad, r), fontsize=5, ha='center', va='bottom',
                       xytext=(0, 3), textcoords='offset points', color=color)
        elif isinstance(positions, list) and len(positions) > 0:
            # Arc: list of (az, el) tuples
            azimuths = [np.deg2rad(p[0]) for p in positions]
            radii = [90.0 - p[1] for p in positions]
            
            # Draw the track as tiny dots rather than a connecting line — a line
            # would falsely bridge gaps where the satellite is below the horizon
            # or otherwise invisible, drawing fake trajectories across those arcs.
            ax.scatter(azimuths, radii, c=color, s=3, alpha=0.5, zorder=4)

            # Mark start and end with dots
            ax.scatter(azimuths[0], radii[0], c=color, s=15, alpha=0.7, zorder=5, marker='o')
            ax.scatter(azimuths[-1], radii[-1], c=color, s=15, alpha=0.7, zorder=5, marker='s')
            
            # Label at midpoint
            mid = len(azimuths) // 2
            ax.annotate(sat_id, (azimuths[mid], radii[mid]), fontsize=5,
                       ha='center', va='bottom', xytext=(0, 3),
                       textcoords='offset points', color=color, alpha=0.9)
    
    return constellation_counts


def plot_skyplot(sat_positions, mask=None, title="Satellite Skyplot",
                 save_path=None, show=True, metadata=None):
    """
    Generate a polar skyplot of satellite positions.
    """
    if not sat_positions:
        print("Warning: No satellite positions to plot")
        return
    
    fig = plt.figure(figsize=(12, 9))
    ax = fig.add_subplot(111, polar=True)
    
    ax.set_theta_zero_location('N')
    ax.set_theta_direction(-1)
    ax.set_rlim(0, 90)
    ax.set_rgrids([0, 15, 30, 45, 60, 75, 90],
                  labels=['90', '75', '60', '45', '30', '15', '0'])
    
    if mask is not None:
        _draw_mask(ax, mask)

    sat_colors = build_satellite_colors(sat_positions.keys())
    constellation_counts = _plot_satellites(ax, sat_positions, sat_colors=sat_colors)

    ax.set_title(title, pad=20, fontsize=14)
    
    # Legend
    total = sum(constellation_counts.values())
    legend_lines = []
    for sys_char in sorted(constellation_counts.keys()):
        name = CONSTELLATION_NAMES.get(sys_char, sys_char)
        count = constellation_counts[sys_char]
        legend_lines.append(f"{name}: {count}")
    
    stats_text = f"Total: {total} satellites\n" + "\n".join(legend_lines)
    fig.text(0.82, 0.92, stats_text,
             verticalalignment='top', horizontalalignment='left',
             bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.6),
             fontsize=9, family='monospace', weight='bold')
    
    plt.subplots_adjust(right=0.78)
    
    if save_path:
        plt.savefig(save_path, dpi=150, bbox_inches='tight')
        print(f"Skyplot saved to: {save_path}")
    
    if show:
        plt.show()
    else:
        plt.close()


def plot_before_after(sat_positions_all, sat_positions_visible, mask=None,
                      save_path=None, show=True, metadata=None):
    """
    Side-by-side skyplots: before masking (all sats) and after masking (visible only).
    
    Args:
        sat_positions_all: dict {sat_id: (az, el) or [(az,el),...]}
        sat_positions_visible: dict {sat_id: (az, el) or [(az,el),...]}
        mask: Optional ElevationMask for shading
        save_path: Optional path to save the figure
        show: Whether to display
        metadata: Optional dict with 'station', 'first_epoch', 'last_epoch', 'position'
    """
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(20, 10),
                                    subplot_kw={'projection': 'polar'})

    # One colour per satellite, built from the full (before-masking) set so the
    # same satellite keeps its colour on both panels.
    sat_colors = build_satellite_colors(sat_positions_all.keys())

    for ax, positions, subtitle in [
        (ax1, sat_positions_all, "Before Masking"),
        (ax2, sat_positions_visible, "After Masking")
    ]:
        ax.set_theta_zero_location('N')
        ax.set_theta_direction(-1)
        ax.set_rlim(0, 90)
        ax.set_rgrids([0, 15, 30, 45, 60, 75, 90],
                      labels=['90', '75', '60', '45', '30', '15', '0'])

        if mask is not None:
            _draw_mask(ax, mask)

        _plot_satellites(ax, positions, sat_colors=sat_colors)

        # Each satellite contributes exactly one arc/track over the period, so
        # this count is "number of satellite arcs" (= distinct PRNs shown).
        count = len(positions)
        ax.set_title(f"{subtitle}\n({count} satellite arcs)", pad=14, fontsize=12)

    # Title with removal count. These are whole satellite arcs that became fully
    # obstructed (disappear entirely after masking); satellites that are only
    # partially obstructed still appear, with their arc trimmed. This is NOT the
    # observation-level count -- see the text summary for observations removed.
    # Kept on two lines (bold headline + smaller note) so it never collides with
    # the per-panel "Before/After Masking" headings.
    removed = len(sat_positions_all) - len(sat_positions_visible)
    total = len(sat_positions_all)
    fig.suptitle(
        f"RINEX-Masker: {removed} of {total} satellite arcs fully removed by obstruction mask",
        fontsize=14, y=0.995)
    fig.text(0.5, 0.95,
             "(partially-masked arcs are trimmed, not counted here — see the text "
             "summary for the observation-level totals)",
             ha='center', va='top', fontsize=9, style='italic')
    
    # Add station and time annotation if metadata is provided
    if metadata:
        info_parts = []
        if metadata.get('station'):
            info_parts.append(f"Station: {metadata['station']}")
        if metadata.get('position'):
            pos = metadata['position']
            info_parts.append(f"ECEF: ({pos[0]:.1f}, {pos[1]:.1f}, {pos[2]:.1f}) m")
        if metadata.get('first_epoch') and metadata.get('last_epoch'):
            t1 = metadata['first_epoch'].strftime("%Y-%m-%d %H:%M")
            t2 = metadata['last_epoch'].strftime("%H:%M")
            date_str = metadata['first_epoch'].strftime("%Y-%m-%d")
            info_parts.append(f"Period: {date_str}  {t1.split(' ')[1]} - {t2} UTC")
        
        if info_parts:
            info_text = "\n".join(info_parts)
            fig.text(0.5, 0.02, info_text, ha='center', va='bottom',
                     fontsize=9, family='monospace',
                     bbox=dict(boxstyle='round', facecolor='lightyellow', alpha=0.8))
    
    plt.tight_layout(rect=[0, 0.06, 1, 0.90])

    if save_path:
        plt.savefig(save_path, dpi=150, bbox_inches='tight')
        print(f"Skyplot saved to: {save_path}")

    if show:
        plt.show()
    else:
        plt.close()


def _draw_mask(ax, mask):
    """
    Draw mask regions on a polar axes.
    Supports uniform cutoff, sector masks, and horizon profiles.
    """
    # Draw uniform cutoff ring
    if mask.uniform_cutoff > 0:
        r_inner = 90.0 - mask.uniform_cutoff
        theta_range = np.linspace(0, 2 * np.pi, 100)
        r_outer = 90.0
        ax.fill_between(theta_range, r_inner, r_outer,
                        color='gray', alpha=0.15, zorder=1)
        ax.plot(theta_range, [r_inner] * len(theta_range),
                color='gray', linewidth=1.0, linestyle='--', alpha=0.5)
    
    # Draw sector masks
    for az_from, az_to, el_limit in mask.sectors:
        theta1 = np.deg2rad(az_from)
        theta2 = np.deg2rad(az_to)
        r_inner = 90.0 - el_limit
        r_outer = 90.0
        
        if theta1 > theta2:
            width1 = (2 * np.pi) - theta1
            ax.bar(theta1, r_outer - r_inner, width=width1, bottom=r_inner,
                   color='red', alpha=0.15, align='edge', edgecolor='red',
                   linewidth=0.5, zorder=2)
            width2 = theta2
            ax.bar(0, r_outer - r_inner, width=width2, bottom=r_inner,
                   color='red', alpha=0.15, align='edge', edgecolor='red',
                   linewidth=0.5, zorder=2)
        else:
            width = theta2 - theta1
            ax.bar(theta1, r_outer - r_inner, width=width, bottom=r_inner,
                   color='red', alpha=0.15, align='edge', edgecolor='red',
                   linewidth=0.5, zorder=2)
    
    # Draw horizon profile (smooth polygon boundary)
    if hasattr(mask, 'horizon_profile') and mask.horizon_profile:
        az_steps = np.linspace(0, 360, 361)
        profile_el = [mask.get_profile_elevation(az) for az in az_steps]
        
        theta_vals = np.deg2rad(az_steps)
        r_profile = [90.0 - el for el in profile_el]
        r_outer = 90.0
        
        # Fill the obstructed region (profile boundary to outer edge)
        ax.fill_between(theta_vals, r_profile, r_outer,
                        color='red', alpha=0.12, zorder=2)
        # Draw the profile boundary line
        ax.plot(theta_vals, r_profile,
                color='#cc0000', linewidth=1.5, alpha=0.8, zorder=3)


def plot_dop_timeseries(stats, save_path=None, show=False):
    """
    Generate a time-series plot comparing PDOP and VDOP before and after masking.

    Each DOP sample carries its own UTC timestamp (stats['dop_*']['time']), so
    the 'before' and 'after' curves are plotted against real time even when some
    epochs had no solvable DOP (weak geometry) and the two series differ in
    length. Falls back to epoch indices only for older runs without timestamps.
    """
    before = stats.get('dop_before')
    if not before or not before.get('PDOP'):
        return

    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates

    after = stats.get('dop_after')

    def _xaxis(series):
        """Real timestamps for this series if they line up, else None."""
        t = series.get('time')
        if t and len(t) == len(series['PDOP']):
            return t, True
        return list(range(len(series['PDOP']))), False

    xb, use_time = _xaxis(before)

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8), sharex=True)
    fig.suptitle('Dilution of Precision (DOP) Before & After Masking', fontsize=14)

    ax1.plot(xb, before['PDOP'], label='PDOP (Original)', color='royalblue', alpha=0.7)
    ax2.plot(xb, before['VDOP'], label='VDOP (Original)', color='royalblue', alpha=0.7)

    if after and after.get('PDOP'):
        xa, xa_time = _xaxis(after)
        # Only overlay 'after' if its x-axis type matches 'before' (both time or
        # both index); mixing datetime and integer x would raise.
        if xa_time == use_time:
            ax1.plot(xa, after['PDOP'], label='PDOP (Masked)', color='crimson', linewidth=2)
            ax2.plot(xa, after['VDOP'], label='VDOP (Masked)', color='crimson', linewidth=2)

    ax1.set_ylabel('PDOP')
    ax1.grid(True, linestyle='--', alpha=0.6)
    ax1.legend()
    ax2.set_ylabel('VDOP')
    ax2.grid(True, linestyle='--', alpha=0.6)
    ax2.legend()

    # Format x-axis with timestamps
    if use_time and len(xb) >= 2:
        time_span = (xb[-1] - xb[0]).total_seconds()
        if time_span < 7200:        # < 2 hours
            fmt = mdates.DateFormatter('%H:%M:%S')
        elif time_span < 86400:     # < 1 day
            fmt = mdates.DateFormatter('%H:%M')
        else:
            fmt = mdates.DateFormatter('%Y-%m-%d %H:%M')

        ax2.xaxis.set_major_formatter(fmt)
        fig.autofmt_xdate(rotation=30)
        ax2.set_xlabel('UTC Time')

        # Add date as subtitle
        date_str = xb[0].strftime('%Y-%m-%d')
        fig.text(0.5, 0.93, date_str, ha='center', fontsize=10, style='italic')
    else:
        ax2.set_xlabel('Epoch Index')
    
    plt.tight_layout()
    
    if save_path:
        plt.savefig(save_path, dpi=150, bbox_inches='tight')
        print(f"DOP plot saved to: {save_path}")
        
    if show:
        plt.show()
    else:
        plt.close()
