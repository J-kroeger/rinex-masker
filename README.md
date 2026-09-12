# RINEX-Masker

Apply a real horizon to RINEX observations and see what it removes.

> **Status: release in preparation.** The program is finished and in testing.
> Downloads are published here and on Zenodo from **16 September 2026**, to
> coincide with the presentation at Frontiers of Geodetic Science (INTERGEO 2026,
> Munich). This repository currently holds the description and the licence only.

## What it does

Applies an obstruction mask to a RINEX observation file and shows what it costs
you: satellite arcs before and after masking, and the effect on DOP over the
session.

The mask can be drawn by hand, or generated automatically from a hemispherical
photograph of the site, in which case the skyline is extracted from the image
and becomes the horizon.

## Why it exists

A simple elevation cut-off angle is a poor description of a real station. Real
sites are blocked by buildings, trees and terrain in some directions and open in
others, and which satellites you actually observe follows that skyline rather
than a circle.

The exported mask is read by [PCC-Explorer](https://github.com/J-kroeger/pcc-explorer),
so an antenna calibration study can be run over the sky a station really sees
instead of the whole hemisphere.

## Features

- Obstruction masks drawn by hand, or extracted from a hemispherical photograph
- Skyplots of satellite arcs before and after masking
- DOP over the session, with and without the mask
- Receiver position from the RINEX header, or entered as ECEF or geodetic
- Optional time window and carrier-to-noise threshold filtering
- Automatic SP3 orbit download when no orbit file is supplied
- Exports the mask for use in PCC-Explorer


## Part of PCC-Suite

This program is one of seven released together as
[PCC-Suite](https://github.com/AmrFawzy-NavEng/pcc-suite), a collection of open-source programs for GNSS antenna
calibration values from the Institut für Erdmessung (IfE), Leibniz University
Hannover. Each is a standalone Windows executable, released and versioned
separately, so you can take only the one you need. No installation, no Python
required.

Archived releases and DOIs are gathered in the Zenodo community
[Open Source Software Packages for GNSS Data Processing](https://zenodo.org/communities/gnss-open-source-solutions).

## Licence

GNU General Public License v3.0 or later. Free to use, share and modify. See
[LICENSE](LICENSE).

## Citation

The method behind the suite and its validation against real PPP solutions are
described in:

> Kröger, J., Kersten, T. & Schön, S. (2026). PCC-Explorer: an open-source
> software tool to assess the impact of GNSS antenna phase center corrections on
> geodetic parameters. *GPS Solutions* **30**, 93. [https://doi.org/10.1007/s10291-026-02056-2](https://doi.org/10.1007/s10291-026-02056-2)

## Stay informed

Release announcements, and warnings when an external data source moves, go to
the institute software mailing list:

```
SOFTWARE-IFE@LISTSERV.UNI-HANNOVER.DE
```

The program offers to subscribe you on first start. You can decline, and you can
ask not to be reminded again.

## Contact

**Dr.-Ing. Johannes Kröger**
Institut für Erdmessung (IfE), Leibniz Universität Hannover
Schneiderberg 50, D-30167 Hannover

Email: [kroeger@ife.uni-hannover.de](mailto:kroeger@ife.uni-hannover.de)
Web: [www.ife.uni-hannover.de](https://www.ife.uni-hannover.de)
