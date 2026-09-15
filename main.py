# main.py
"""
RINEX-Masker — CLI entry point.

Applies azimuth/elevation obstruction masks to RINEX 3.x observation files,
removing satellites in blocked sky regions. Satellite positions computed from
SP3 precise ephemeris files (auto-downloaded from AIUB/CODE if not provided).

Usage:
    python main.py -r input.rnx -m mask.txt --skyplot
    python main.py -r input.rnx -s orbit.sp3 -c 10 -o output.rnx
"""

import argparse
import os
import sys
from datetime import datetime

from elevation_mask import ElevationMask
from masker import apply_mask


def main():
    parser = argparse.ArgumentParser(
        description="RINEX-Masker: Apply obstruction masks to RINEX observation files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # With mask file (auto-downloads SP3):
  python main.py -r input.rnx -m mask.txt --skyplot

  # With explicit SP3 file and elevation cutoff:
  python main.py -r input.rnx -s orbit.sp3 -c 10 -o output.rnx

  # Simple elevation cutoff only:
  python main.py -r input.rnx -c 15

Mask file format (CSV, one sector per line):
  # azimuth_start, azimuth_end, elevation_cutoff
  180, 270, 45
  270, 360, 30
  0, 90, 15
        """
    )
    
    parser.add_argument('-r', '--rinex', required=True,
                        help='Path to input RINEX observation file')
    parser.add_argument('-s', '--sp3', default=None,
                        help='Path to SP3 precise ephemeris file (auto-downloads if not provided)')
    parser.add_argument('-m', '--mask', default=None,
                        help='Path to mask definition file')
    parser.add_argument('-c', '--cutoff', type=float, default=5.0,
                        help='Uniform elevation cutoff in degrees (default: 5.0)')
    parser.add_argument('-o', '--output', default=None,
                        help='Path to output RINEX file (default: <input>_masked.rnx)')
    parser.add_argument('--skyplot', action='store_true',
                        help='Generate before/after skyplot visualization')
    parser.add_argument('--skyplot-epoch', type=int, default=0,
                        help='Epoch index to use for skyplot (default: 0 = first epoch)')
    
    args = parser.parse_args()
    
    # --- Validate inputs ---
    if not os.path.exists(args.rinex):
        print(f"Error: RINEX file not found: {args.rinex}")
        sys.exit(1)
    
    if args.sp3 and not os.path.exists(args.sp3):
        print(f"Error: SP3 file not found: {args.sp3}")
        sys.exit(1)
    
    if args.mask and not os.path.exists(args.mask):
        print(f"Error: Mask file not found: {args.mask}")
        sys.exit(1)
    
    # --- Build elevation mask ---
    if args.mask:
        mask = ElevationMask.from_file(args.mask, uniform_cutoff=args.cutoff)
        print(f"Loaded mask from: {args.mask}")
    else:
        mask = ElevationMask(uniform_cutoff=args.cutoff)
        print(f"Using uniform elevation cutoff: {args.cutoff}°")
    
    print(mask.summary())
    
    # --- Determine output path ---
    if args.output:
        output_path = args.output
    else:
        base, ext = os.path.splitext(args.rinex)
        output_path = f"{base}_masked{ext}"
    
    # --- Determine SP3 source ---
    sp3_source = args.sp3 if args.sp3 else 'auto'
    
    # --- Run masking ---
    print("\n" + "=" * 60)
    print("RINEX-Masker")
    print("=" * 60)
    print(f"  Input:    {args.rinex}")
    print(f"  Output:   {output_path}")
    print(f"  SP3:      {sp3_source}")
    print(f"  Cutoff:   {args.cutoff}°")
    if args.mask:
        print(f"  Mask:     {args.mask}")
    print("=" * 60)
    
    stats = apply_mask(
        rinex_path=args.rinex,
        sp3_path_or_date=args.sp3 if args.sp3 else None,  # None triggers auto-download
        mask=mask,
        output_path=output_path,
        generate_skyplot=args.skyplot,
        skyplot_epoch_index=args.skyplot_epoch,
    )
    
    print(f"\nDone! Output written to: {output_path}")


if __name__ == '__main__':
    main()
