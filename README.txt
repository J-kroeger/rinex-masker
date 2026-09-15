RINEX-Masker v1.0
==================

Version: 1.0
Release date: 2026-09-01

A tool to apply azimuth/elevation obstruction masks to RINEX 3.x / 4.x
observation files. Removes satellite observations blocked by user-defined
horizon profiles or sector masks.

Part of the PCC software suite developed at the Institut für Erdmessung (IfE),
Leibniz Universität Hannover.

Developers:
  Amr Fawzy, M.Sc.
  Dr.-Ing. Johannes Kröger


CITATION
--------
If you use this software, please cite:

  Kröger, J., Kersten, T. & Schön, S. PCC-Explorer: An open-source software
  tool to assess the impact of GNSS antenna phase center corrections on
  geodetic parameters. GPS Solut 30, 93 (2026).
  https://doi.org/10.1007/s10291-026-02056-2

A DOI for this program itself is planned with the v2.0 release of the suite;
until then please cite the paper above.


ACKNOWLEDGEMENT - SKY SEGMENTATION
----------------------------------
The "Auto-Mask from Image" feature consumes segmentation masks produced by the
Image Analysis (IPI) sub-group of the IPI/IfE project seminar, SoSe 2026:
Ali Habib Nezhad, supervised by Max Meyer (IPI) and Kai Baasch (IfE).

RINEX-Masker itself contains no segmentation model - it converts such a mask,
or a plain photograph classified by a simple colour rule, into a horizon
profile.


QUICK START
-----------
1. Double-click  launch_gui.bat  (or RINEX-Masker.exe)
2. Select a RINEX observation file
3. Define an obstruction mask (see below)
4. Click "Run Masking"
5. Results are saved to the  results\  folder


INPUT FILES
-----------
  RINEX File:   Select a RINEX 3.x or 4.x observation file (.rnx, .obs)

  SP3 File:     Two options:
                - "Auto-download" (default): multi-GNSS SP3 orbits are
                  downloaded automatically based on the RINEX file date. It
                  tries several public sources in turn (see below), so no
                  single server being down breaks it. Files are cached in
                  the  orbits\  folder.
                - Manual: Uncheck auto-download and browse for a local
                  SP3 file (.sp3, .EPH)


RECEIVER POSITION
-----------------
  The receiver position is used to compute satellite azimuth and elevation.

  Three modes:
  - Auto (default):   Uses APPROX POSITION XYZ from the RINEX header.
  - ECEF (X, Y, Z):   Enter coordinates in metres (WGS84 ECEF).
  - Lat / Lon / H:    Enter geodetic coordinates in degrees and metres.
                       Automatically converted to ECEF internally.

  Use manual input when the RINEX header position is missing or inaccurate.


TIME FILTER
-----------
  Optionally restrict processing to a specific time window:
  - Check "Enable time filter"
  - Enter Start and/or End times in format: YYYY-MM-DD HH:MM:SS
  - Leave either field blank for no limit on that side
  - Epochs outside the window are kept in the file but not masked


OBSTRUCTION MASK
----------------
  The mask defines which parts of the sky are blocked (e.g., buildings,
  trees). Satellites in blocked zones are removed from the output.

  Uniform Elevation Cutoff:
    Applies everywhere. Satellites below this elevation are removed.
    Default: 5 degrees.

The mask section has two tabs:

  ### Tab 1: Sector Masks
  Rectangular azimuth/elevation sectors. Each sector blocks satellites
  within an azimuth range below a given elevation.

    - Check "Azimuth sector mask(s) active" to enable
    - Enter From/To azimuth (0-360 deg) and elevation limit
    - Click "Add Mask Sector"
    - "Remove Selected" removes the highlighted sector
    - "Load Mask File" / "Save Mask File" for reuse

  Sector mask file format (one line per sector):
    # azimuth_start, azimuth_end, elevation_cutoff
    180, 270, 40
    340, 20, 15

  ### Tab 2: Horizon Profile
  A continuous boundary defined by (azimuth, elevation) pairs.
  The tool linearly interpolates between points. On the polar skyplot,
  these straight-line segments appear curved due to the polar projection.

    - Enter azimuth and elevation, click "Add Point"
    - Points are auto-sorted by azimuth
    - "Remove Selected" / "Clear All" to edit
    - "Preview Profile" shows a polar plot of the boundary
    - "Load Profile File" / "Save Profile File" for reuse

  >> Digitize from Image:
     Click "Digitize from Image..." to load a polar skyplot image
     (e.g., obstructionMask.png). A window opens where you can:
       - Left-click along the horizon boundary to add points
       - Right-click to undo the last point
       - Click "Done" when finished
     The traced points become the horizon profile.

  >> Auto-Mask from Image:
     Click "Auto-Mask from Image..." to build the profile automatically
     from a sky image. Two kinds of input are accepted:

       - Photo: a hemispherical (fisheye) photo or an equirectangular
         360 panorama. RINEX-Masker finds the sky itself with a simple
         colour rule. Daytime, open-sky scenes only.

       - Pre-segmented mask: an image already segmented by a segmentation
         model. Both export shapes work and are detected automatically:
           * binary mask   - sky and obstacle in two tones (e.g. white sky
                             on black). Tick "Sky is the dark class" if the
                             sky is the darker one.
           * colour label  - each class in its palette colour; the sky is
                             matched against the Cityscapes sky colour
                             70,130,180. Enter R,G,B for a different class.
         Nothing is detected inside RINEX-Masker on this path, so the mask
         is exactly as good as the segmentation that produced it. Use this
         for night scenes, where the built-in colour rule fails.

     Options:
       North offset [deg]        Aligns image azimuths with true north. The
                                 image convention is north-at-bottom; this
                                 absorbs that and the camera heading. A wrong
                                 value rotates the whole mask.
       Camera zenith angle [deg] Elevation the camera actually pointed at.
                                 90 (default) = straight up, the standard
                                 setup for a horizontal antenna. Enter a
                                 different value only for a known tilt, such
                                 as a kinematic run on a slope. The tilt is
                                 NOT read from IMU data.
       Tilt towards azimuth      Direction the camera leans. Only has an
                                 effect when the zenith angle is not 90.
       Azimuth step [deg]        Width of each azimuth bin.
       Sky sensitivity           Photo mode only; raise it if bright facades
                                 are read as sky, lower it for overcast.

     A preview window shows the input, the sky/obstacle split and the
     extracted skyline, so the result can be checked before it is used.

  >> Fine-Tune Points:
     An automatic mask is a first estimate, not an answer. Segmentation
     cannot always tell which object blocks a direction - a tree standing in
     front of a tall building is the standard failure, and the two block
     signals very differently - so every generated point can be corrected.

     Click "Fine-Tune Points..." to open the profile on the image it came
     from:
       - Drag a point to move it onto the true skyline
       - Left-click empty space to add a point
       - Right-click a point to delete it
       - "Reset" restores the generated profile, "Apply" keeps the changes
     The shaded ring shows what the current profile blocks. If the profile
     came from a segmentation mask, RINEX-Masker offers to open it on the
     ORIGINAL PHOTOGRAPH instead, where it is visible what each obstacle
     actually is.

     The button also works without a source image: it will offer to open a
     hemispherical image, or edit the points on the elevation grid alone.

     YOUR CORRECTIONS ARE KEPT, LOCALLY
     When you change a generated profile and apply it, RINEX-Masker stores
     the image together with the automatic profile and your corrected one in
       mask_feedback\
     next to the program. The difference between the two profiles is exactly
     what the sky segmentation needs in order to learn from the cases it got
     wrong, and corrections from real sites are the most useful training data
     there is.

     It stays on this computer. Nothing is uploaded, nothing is sent
     anywhere, and the program never reads what is already in that folder.
     Delete it if you would rather not keep it. If you are willing to share
     it, send the folder to the address in the Contact dialog. A profile you
     drew by hand is not stored, because there is no automatic profile for it
     to be a correction of.

  Profile file format (one line per point):
    # azimuth, elevation
    0, 80
    30, 20
    90, 10
    180, 25
    270, 15
    360, 80


OUTPUT
------
  Output File:    Automatically set to  results\<input>_masked.rnx
                  You can change this with "Browse..."

  Generate Skyplot:  When checked (default), a before/after skyplot
                     image is saved alongside the output. The skyplot
                     shows full satellite arcs over the entire observation
                     period, annotated with station name and time span.

  The output RINEX file contains added COMMENT lines in the header,
  marking it as a manipulated file with the applied mask description
  and processing timestamp.


BUTTONS (Bottom Bar)
--------------------
  Run Masking:       Start processing (runs in background)
  Show Last Skyplot: Re-display the skyplot from the last run
  Close Figures:     Close all open matplotlib windows
  Quit:              Exit the application


PROGRESS LOG
------------
  The progress bar and log window show real-time status:
  - RINEX parsing
  - SP3 orbit loading (or download progress)
  - Epoch-by-epoch processing
  - Summary statistics (kept/removed per constellation)


FOLDER STRUCTURE
----------------
  RINEX-Masker\
  +-- RINEX-Masker.exe    Main application
  +-- launch_gui.bat      Launcher script
  +-- README.txt          This file
  +-- orbits\             Cached SP3 orbit files (auto-downloaded)
  +-- masks\              Example mask files
  +-- results\            Output RINEX files and skyplots


SUPPORTED SYSTEMS
-----------------
  GPS (G), GLONASS (R), Galileo (E), BeiDou (C), QZSS (J)

  RINEX versions 3.x and 4.x are supported (same epoch/data format).

  Multi-GNSS SP3 orbits are downloaded automatically, trying several public
  sources in turn so that no single server going down can break it:
    1. AIUB   http://www.aiub.unibe.ch/download/CODE_MGEX/CODE/<year>/
              (CODE final orbits; no login)
    2. IGN    ftp://igs.ign.fr/pub/igs/products/<week>/
              (final, rapid and ultra-rapid; no login)
    3. CDDIS  https://cddis.nasa.gov/archive/gnss/products/<week>/
              (needs a free NASA Earthdata login; used only if 1 and 2 fail)
  For each day the products are tried best-quality first:
    final (most accurate) -> rapid (~1 day old) -> ultra-rapid (same day).
  This means a file measured today can be masked immediately, and older data
  still gets the precise final orbit.


TIPS
----
  - Use a meaningful mask to see results. A 5-degree cutoff alone
    usually removes nothing (receivers already track above ~5 deg).
  - Increase cutoff to 15-25 deg or add sector/profile masks.
  - The horizon profile is more realistic than rectangular sectors.
  - Profile files can be shared between users for the same station.
  - The "Info" button shows version and developer information.
  - Use the time filter to restrict masking to a specific period.
  - Set the receiver position manually if the RINEX header is wrong.

STAY INFORMED
-------------

  The Institut für Erdmessung runs a moderated mailing list for its GNSS
  software. It announces new releases and warns you about changes that can
  break your work, for example when a server for satellite orbit products
  moves to a new address. Every program in the suite offers this once when it
  first starts, and the Contact dialog can open it again at any time.

  Subscribe (web form):
    https://listserv.uni-hannover.de/cgi-bin/wa?SUBED1=SOFTWARE-IFE&A=1

  Subscribe by e-mail:
    send the single line   subscribe software-ife
    to                     listserv@listserv.uni-hannover.de

  Send that command line on its own. LISTSERV reads the message body line by
  line, so a signature added by your mail program can stop it.

  List address: SOFTWARE-IFE@LISTSERV.UNI-HANNOVER.DE

  LISTSERV answers with a confirmation mail. The subscription becomes active
  only after you reply to it and a moderator approves the request. Subscribing
  is voluntary and you can leave the list at any time.
