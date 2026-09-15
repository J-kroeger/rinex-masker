# image_mask.py
"""
Automatic obstruction-mask generation from sky images for RINEX-Masker.

This module turns a photograph of the sky into a horizon profile — the list of
(azimuth, elevation) pairs that `elevation_mask.ElevationMask` already consumes.
It is the missing link between the hemispherical images produced by the IPI
project-seminar group and the mask machinery that RINEX-Masker already has.

Pipeline
--------
    1. Load the image (hemispherical/fisheye, or equirectangular 360 panorama).
    2. Optionally project equirectangular -> hemispherical fisheye.
    3. Segment sky vs. obstacle.
    4. Trace the skyline and convert it to (azimuth, elevation).

Projection model (shared with the IPI group's pipeline)
------------------------------------------------------
Equidistant fisheye, north-at-bottom:

    theta = 90 deg - elevation          (zenith angle)
    r     = f * theta                   (f in px/rad)
    u     = cx + r * sin(azimuth)
    v     = cy + r * cos(azimuth)

For a 1024 px wide, 180 deg image this gives f = 512 / (pi/2) ~= 325.95 px/rad,
matching the value used by the IPI group. The inverse mapping used here is:

    r         = hypot(u - cx, v - cy)
    elevation = 90 deg - degrees(r / f)
    azimuth   = degrees(atan2(u - cx, v - cy))

Segmentation
------------
A deliberately lightweight *classical* sky detector is used rather than a neural
network: embedding a segmentation model (e.g. VLTSeg) would pull in PyTorch and
CLIP weights and grow the standalone build from tens of MB to several GB. The
classical detector is adequate for the daytime, open-sky images that static
setups need. For hard cases (night, dense canopy) the intended workflow is to
import an externally segmented label image via `profile_from_label_image`, or to
correct the generated profile by hand in the existing digitizer.

The generated profile is a *starting point*, not a final answer: the IPI group's
own evaluation reports a skyline error of ~18.5 px mean / 34.5 px RMSE by day,
which at f ~= 326 px/rad is roughly 3.3 deg mean / 6.1 deg RMSE. It should always
be reviewed before use.
"""

from typing import List, Optional, Sequence, Tuple

import numpy as np

# A satellite azimuth/elevation pair, in degrees.
ProfilePoint = Tuple[float, float]

DEFAULT_FOV_DEG = 180.0
DEFAULT_AZ_STEP_DEG = 5.0

#: Minimum blob size kept during mask cleaning, as a fraction of image area.
_MIN_BLOB_AREA_FRAC = 0.0005

#: Sky colour of the Cityscapes palette, used by most semantic-segmentation
#: pipelines (including the IPI group's VLTSeg colour output).
CITYSCAPES_SKY_RGB = (70, 130, 180)

#: Colours counted as distinct before an image stops being considered binary.
_MAX_BINARY_COLOURS = 2

#: Elevation the camera's optical axis points at in the standard setup: the
#: zenith, i.e. a camera looking straight up over a horizontal antenna.
DEFAULT_CAMERA_ELEVATION_DEG = 90.0


def apply_camera_tilt(azimuth,
                      elevation,
                      camera_elevation_deg: float = DEFAULT_CAMERA_ELEVATION_DEG,
                      tilt_azimuth_deg: float = 0.0,
                      inverse: bool = False):
    """Re-reference directions read off a tilted camera to the local horizon.

    The image geometry assumes the optical axis points at the zenith, which
    covers the normal case: a camera levelled over a horizontal antenna. When
    the camera leans — a kinematic setup, or a receiver on a slope — every
    direction taken from the image is rotated by the same amount, and the mask
    is wrong by that angle until it is corrected.

    The lean is entered by the user rather than derived from IMU data: the
    recording is often unavailable, and making the tool depend on it would buy
    little for what is a single number the operator usually knows.

    Args:
        azimuth: Azimuths in degrees, as measured in the image frame.
        elevation: Elevations in degrees, as measured in the image frame.
        camera_elevation_deg: Elevation the optical axis actually points at.
            90 (the default) means straight up and leaves directions unchanged.
        tilt_azimuth_deg: Azimuth the camera leans towards. Only has an effect
            when `camera_elevation_deg` differs from 90.
        inverse: Undo the tilt instead of applying it.

    Returns:
        Tuple of (azimuth, elevation) arrays in degrees, azimuth in [0, 360).
    """
    tilt = 90.0 - float(camera_elevation_deg)
    az_arr = np.asarray(azimuth, dtype=float)
    el_arr = np.asarray(elevation, dtype=float)
    if abs(tilt) < 1e-12:
        return az_arr % 360.0, el_arr
    if inverse:
        tilt = -tilt

    az = np.deg2rad(az_arr)
    el = np.deg2rad(el_arr)

    # Direction vectors in a local frame: x east, y north, z up, with azimuth
    # measured from north (+y) towards east (+x).
    cos_el = np.cos(el)
    v = np.stack([cos_el * np.sin(az), cos_el * np.cos(az), np.sin(el)], axis=-1)

    # Rotate about the horizontal axis perpendicular to the lean direction, so
    # the optical axis swings from the zenith towards `tilt_azimuth_deg`.
    a = np.deg2rad(float(tilt_azimuth_deg))
    u = np.array([-np.cos(a), np.sin(a), 0.0])

    t = np.deg2rad(tilt)
    rotated = (v * np.cos(t)
               + np.cross(u, v) * np.sin(t)
               + u * np.sum(v * u, axis=-1, keepdims=True) * (1.0 - np.cos(t)))

    out_az = np.rad2deg(np.arctan2(rotated[..., 0], rotated[..., 1])) % 360.0
    out_el = np.rad2deg(np.arcsin(np.clip(rotated[..., 2], -1.0, 1.0)))
    return out_az, out_el


def load_image(path: str) -> np.ndarray:
    """Load an image as an RGB array.

    Args:
        path: Path to a PNG/JPEG/BMP image.

    Returns:
        Array of shape (H, W, 3), dtype uint8.

    Raises:
        ImportError: If Pillow is unavailable.
        OSError: If the file cannot be read as an image.
    """
    from PIL import Image

    with Image.open(path) as img:
        return np.asarray(img.convert('RGB'), dtype=np.uint8)


def is_equirectangular(img: np.ndarray, tolerance: float = 0.25) -> bool:
    """Guess whether an image is an equirectangular 360 panorama.

    Equirectangular frames have a 2:1 aspect ratio; hemispherical frames are
    approximately square.

    Args:
        img: Image array (H, W, 3).
        tolerance: Allowed relative deviation from the ideal 2:1 ratio.

    Returns:
        True if the aspect ratio is close to 2:1.
    """
    height, width = img.shape[:2]
    if height == 0:
        return False
    return abs((width / height) - 2.0) <= 2.0 * tolerance


def equirect_to_fisheye(img: np.ndarray,
                        out_size: int = 1024,
                        fov_deg: float = DEFAULT_FOV_DEG) -> np.ndarray:
    """Project an equirectangular 360 panorama to an equidistant fisheye image.

    This is the closed-form projection used by the IPI group, applied in the
    forward direction (output pixel -> direction -> source pixel) so that it can
    be evaluated without iteration.

    The panorama is assumed to cover 360 deg horizontally and 180 deg vertically,
    with the horizon on the centre row and the zenith on the top row.

    Args:
        img: Equirectangular image (H, W, 3), ideally with W = 2 * H.
        out_size: Side length of the square output image, in pixels.
        fov_deg: Field of view of the output image (180 = full hemisphere).

    Returns:
        Fisheye image of shape (out_size, out_size, 3), dtype uint8. Pixels
        outside the image circle are black.
    """
    height, width = img.shape[:2]
    radius = out_size / 2.0
    f_px = focal_length_px(radius, fov_deg)

    yy, xx = np.mgrid[0:out_size, 0:out_size].astype(np.float64)
    dx = xx - radius
    dy = yy - radius
    r = np.hypot(dx, dy)

    inside = r <= radius
    theta = np.divide(r, f_px, out=np.zeros_like(r), where=inside)  # zenith angle [rad]
    azimuth = np.arctan2(dx, dy)  # north-at-bottom convention

    elevation = np.pi / 2.0 - theta

    # Equirectangular sampling coordinates.
    src_x = ((azimuth / (2.0 * np.pi)) % 1.0) * (width - 1)
    src_y = ((np.pi / 2.0 - elevation) / np.pi) * (height - 1)

    src_x = np.clip(np.rint(src_x), 0, width - 1).astype(np.int32)
    src_y = np.clip(np.rint(src_y), 0, height - 1).astype(np.int32)

    out = img[src_y, src_x]
    out[~inside] = 0
    return out.astype(np.uint8)


def focal_length_px(radius_px: float, fov_deg: float = DEFAULT_FOV_DEG) -> float:
    """Return the equidistant-fisheye scale factor f, in px/rad.

    Args:
        radius_px: Radius of the image circle, in pixels.
        fov_deg: Field of view covered by that circle, in degrees.

    Returns:
        f such that r = f * theta.
    """
    return radius_px / np.deg2rad(fov_deg / 2.0)


def detect_sky(img: np.ndarray,
               blue_threshold: float = 0.02,
               min_brightness: float = 0.20) -> np.ndarray:
    """Segment sky pixels using a classical colour rule.

    Sky (blue or overcast) is bluer than it is red; buildings, vegetation and
    ground are not. The normalised difference (B - R) / (B + R) separates the two
    robustly across exposures, and a brightness floor removes dark shadow pixels
    that can be incidentally blue-ish.

    Args:
        img: RGB image (H, W, 3).
        blue_threshold: Minimum normalised blue-red difference for sky.
            Raise it if bright facades are being taken for sky; lower it for
            overcast scenes.
        min_brightness: Minimum per-pixel brightness (0-1) for sky.

    Returns:
        Boolean array (H, W); True where the pixel is classified as sky.
    """
    rgb = img.astype(np.float64) / 255.0
    red = rgb[..., 0]
    blue = rgb[..., 2]

    denom = red + blue
    blueness = np.divide(blue - red, denom, out=np.zeros_like(denom), where=denom > 1e-6)
    brightness = rgb.max(axis=2)

    return (blueness > blue_threshold) & (brightness > min_brightness)


def clean_mask(sky: np.ndarray, min_area_frac: float = _MIN_BLOB_AREA_FRAC) -> np.ndarray:
    """Remove speckle from a binary sky mask.

    Small isolated blobs — a bright window read as sky, a thin branch read as
    obstacle — would otherwise dominate the skyline at their azimuth, because the
    profile takes the *highest* obstacle per azimuth bin.

    Args:
        sky: Boolean sky mask (H, W).
        min_area_frac: Minimum blob area to keep, as a fraction of image area.

    Returns:
        Cleaned boolean mask of the same shape.
    """
    from scipy import ndimage

    min_area = max(1, int(min_area_frac * sky.size))
    cleaned = sky.copy()

    # Drop small sky islands, then small obstacle islands.
    for value in (True, False):
        target = cleaned if value else ~cleaned
        labels, count = ndimage.label(target)
        if count == 0:
            continue
        sizes = ndimage.sum(target, labels, index=np.arange(1, count + 1))
        too_small = np.isin(labels, np.nonzero(sizes < min_area)[0] + 1)
        cleaned[too_small] = not value

    return cleaned


def extract_horizon_profile(sky: np.ndarray,
                            az_step_deg: float = DEFAULT_AZ_STEP_DEG,
                            fov_deg: float = DEFAULT_FOV_DEG,
                            north_offset_deg: float = 0.0,
                            center: Optional[Tuple[float, float]] = None,
                            radius_px: Optional[float] = None,
                            camera_elevation_deg: float = DEFAULT_CAMERA_ELEVATION_DEG,
                            tilt_azimuth_deg: float = 0.0) -> List[ProfilePoint]:
    """Convert a hemispherical sky mask into a horizon profile.

    For each azimuth bin the horizon elevation is the elevation of the *highest*
    obstacle pixel in that bin — i.e. the top of whatever blocks the sky in that
    direction. Bins with no obstacle get 0 deg (open to the horizon).

    Args:
        sky: Boolean sky mask (H, W) from a fisheye image.
        az_step_deg: Azimuth bin width, in degrees.
        fov_deg: Field of view of the image circle, in degrees.
        north_offset_deg: Rotation applied to align the camera's azimuth frame
            with true north. The image convention is north-at-bottom; this offset
            absorbs both that convention and the camera heading.
        center: (cx, cy) of the image circle. Defaults to the image centre.
        radius_px: Radius of the image circle. Defaults to half the smaller side.
        camera_elevation_deg: Elevation the camera's optical axis points at.
            90 (the default) is a camera looking straight up.
        tilt_azimuth_deg: Azimuth the camera leans towards when tilted.

    Returns:
        List of (azimuth, elevation) in degrees, sorted by azimuth, azimuth in
        [0, 360). Suitable for `ElevationMask.set_horizon_profile`.

    Raises:
        ValueError: If `az_step_deg` does not yield at least 2 bins.
    """
    if not 0 < az_step_deg <= 180.0:
        raise ValueError(f"az_step_deg must be in (0, 180], got {az_step_deg}")

    height, width = sky.shape[:2]
    cx, cy = center if center is not None else (width / 2.0, height / 2.0)
    radius = radius_px if radius_px is not None else min(width, height) / 2.0
    f_px = focal_length_px(radius, fov_deg)

    yy, xx = np.mgrid[0:height, 0:width].astype(np.float64)
    dx = xx - cx
    dy = yy - cy
    r = np.hypot(dx, dy)

    inside = r <= radius
    elevation = 90.0 - np.rad2deg(r / f_px)
    azimuth = (np.rad2deg(np.arctan2(dx, dy)) + north_offset_deg) % 360.0

    # A tilted camera rotates every direction it recorded; undo that before the
    # directions are binned, so the profile is referenced to the true horizon.
    azimuth, elevation = apply_camera_tilt(azimuth, elevation,
                                           camera_elevation_deg=camera_elevation_deg,
                                           tilt_azimuth_deg=tilt_azimuth_deg)

    obstacle = inside & ~sky & (elevation >= 0.0)

    n_bins = int(round(360.0 / az_step_deg))
    bin_index = np.minimum((azimuth / az_step_deg).astype(np.int32), n_bins - 1)

    profile: List[ProfilePoint] = []
    for i in range(n_bins):
        in_bin = obstacle & (bin_index == i)
        el = float(elevation[in_bin].max()) if in_bin.any() else 0.0
        profile.append(((i + 0.5) * az_step_deg % 360.0, float(np.clip(el, 0.0, 90.0))))

    profile.sort(key=lambda p: p[0])
    return profile


def profile_from_image(path: str,
                       az_step_deg: float = DEFAULT_AZ_STEP_DEG,
                       north_offset_deg: float = 0.0,
                       fov_deg: float = DEFAULT_FOV_DEG,
                       blue_threshold: float = 0.02,
                       force_kind: Optional[str] = None,
                       camera_elevation_deg: float = DEFAULT_CAMERA_ELEVATION_DEG,
                       tilt_azimuth_deg: float = 0.0) -> Tuple[List[ProfilePoint], np.ndarray, np.ndarray]:
    """Generate a horizon profile from a sky photograph.

    Equirectangular input is projected to a hemispherical view first; square
    input is assumed to be hemispherical already.

    Args:
        path: Path to the image.
        az_step_deg: Azimuth bin width, in degrees.
        north_offset_deg: Rotation to align azimuths with true north.
        fov_deg: Field of view of the hemispherical image circle.
        blue_threshold: Sky-detector sensitivity; see `detect_sky`.
        force_kind: 'fisheye' or 'equirect' to override auto-detection.
        camera_elevation_deg: Elevation the camera's optical axis points at;
            90 (the default) is a camera looking straight up.
        tilt_azimuth_deg: Azimuth the camera leans towards when tilted.

    Returns:
        Tuple of (profile, fisheye_image, sky_mask), so that callers can display
        what the profile was derived from.

    Raises:
        ValueError: If `force_kind` is not a recognised value.
    """
    if force_kind not in (None, 'fisheye', 'equirect'):
        raise ValueError(f"force_kind must be 'fisheye', 'equirect' or None, got {force_kind!r}")

    img = load_image(path)

    kind = force_kind or ('equirect' if is_equirectangular(img) else 'fisheye')
    fisheye = equirect_to_fisheye(img, fov_deg=fov_deg) if kind == 'equirect' else img

    sky = clean_mask(detect_sky(fisheye, blue_threshold=blue_threshold))
    profile = extract_horizon_profile(sky,
                                      az_step_deg=az_step_deg,
                                      fov_deg=fov_deg,
                                      north_offset_deg=north_offset_deg,
                                      camera_elevation_deg=camera_elevation_deg,
                                      tilt_azimuth_deg=tilt_azimuth_deg)
    return profile, fisheye, sky


def classify_label_image(img: np.ndarray) -> str:
    """Decide how a pre-segmented image encodes its sky class.

    Segmentation tools export masks in two shapes, and they need opposite
    treatment: a *binary* mask paints sky and obstacle in two arbitrary tones
    (typically white and black), while a *colour* label image paints each
    semantic class in its palette colour and the sky must be picked out by that
    colour.

    Args:
        img: Image array (H, W, 3).

    Returns:
        'binary' if the image holds at most two distinct colours, 'greyscale'
        if it is grey everywhere but with more tones than that (an anti-aliased
        or JPEG-compressed binary mask), and 'colour' otherwise.
    """
    channels = img.reshape(-1, 3).astype(np.int16)
    is_grey = bool((np.ptp(channels, axis=1) <= 8).all())

    packed = (img[..., 0].astype(np.uint32) << 16 |
              img[..., 1].astype(np.uint32) << 8 |
              img[..., 2].astype(np.uint32))
    n_colours = len(np.unique(packed))

    if n_colours <= _MAX_BINARY_COLOURS:
        return 'binary'
    return 'greyscale' if is_grey else 'colour'


def sky_mask_from_label_image(img: np.ndarray,
                              sky_rgb: Optional[Sequence[int]] = None,
                              tolerance: int = 30,
                              invert: bool = False) -> np.ndarray:
    """Extract the sky class from a pre-segmented image.

    Args:
        img: Segmented image (H, W, 3) — a binary mask or a colour label image.
        sky_rgb: RGB colour of the sky class. `None` (the default) picks the
            rule automatically from `classify_label_image`: the brighter tone
            for binary/greyscale masks, the Cityscapes sky colour otherwise.
        tolerance: Per-channel tolerance when matching a colour.
        invert: Swap sky and obstacle. Needed for binary masks that paint the
            sky dark rather than light.

    Returns:
        Boolean array (H, W); True where the pixel is sky.
    """
    if sky_rgb is None and classify_label_image(img) in ('binary', 'greyscale'):
        # Two-tone mask: split on brightness rather than on an exact colour, so
        # white-on-black, black-on-white and 8-bit label ids (0/1) all work.
        brightness = img.max(axis=2).astype(np.int16)
        low, high = int(brightness.min()), int(brightness.max())
        if low == high:
            # Uniform image — no boundary to trace either way.
            sky = np.zeros(img.shape[:2], dtype=bool)
        else:
            sky = brightness > (low + high) // 2
    else:
        target = np.asarray(sky_rgb if sky_rgb is not None else CITYSCAPES_SKY_RGB,
                            dtype=np.int16)
        sky = (np.abs(img.astype(np.int16) - target) <= tolerance).all(axis=2)

    return ~sky if invert else sky


def profile_from_label_image(path: str,
                             sky_rgb: Optional[Sequence[int]] = None,
                             tolerance: int = 30,
                             az_step_deg: float = DEFAULT_AZ_STEP_DEG,
                             north_offset_deg: float = 0.0,
                             fov_deg: float = DEFAULT_FOV_DEG,
                             invert: bool = False,
                             camera_elevation_deg: float = DEFAULT_CAMERA_ELEVATION_DEG,
                             tilt_azimuth_deg: float = 0.0) -> Tuple[List[ProfilePoint], np.ndarray, np.ndarray]:
    """Generate a horizon profile from an externally segmented image.

    This is the intended path for masks produced by a real segmentation model
    (e.g. the IPI group's VLTSeg output): the sky class is read straight out of
    the supplied mask, so no detection happens inside RINEX-Masker. Both export
    shapes are accepted — a binary sky/no-sky mask and a colour label image.

    Args:
        path: Path to a hemispherical segmented image.
        sky_rgb: RGB colour of the sky class, or `None` to choose automatically.
        tolerance: Per-channel tolerance when matching `sky_rgb`.
        az_step_deg: Azimuth bin width, in degrees.
        north_offset_deg: Rotation to align azimuths with true north.
        fov_deg: Field of view of the hemispherical image circle.
        invert: Swap sky and obstacle; for binary masks with a dark sky.
        camera_elevation_deg: Elevation the camera's optical axis points at;
            90 (the default) is a camera looking straight up.
        tilt_azimuth_deg: Azimuth the camera leans towards when tilted.

    Returns:
        Tuple of (profile, label_image, sky_mask).
    """
    img = load_image(path)
    sky = sky_mask_from_label_image(img, sky_rgb=sky_rgb,
                                    tolerance=tolerance, invert=invert)
    profile = extract_horizon_profile(sky,
                                      az_step_deg=az_step_deg,
                                      fov_deg=fov_deg,
                                      north_offset_deg=north_offset_deg,
                                      camera_elevation_deg=camera_elevation_deg,
                                      tilt_azimuth_deg=tilt_azimuth_deg)
    return profile, img, sky
