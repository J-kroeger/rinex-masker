# profile_editor.py
"""
Interactive fine-tuning of a horizon profile for RINEX-Masker.

An automatically generated obstruction mask is a first estimate, not an answer.
Segmentation models confuse classes that block signals differently — a tree
standing in front of a tall building is the standard failure, and it moves the
skyline by tens of degrees — so the generated points have to be correctable by
hand before the mask is applied.

This module opens the profile on top of the image it came from and lets the
user drag individual points onto the true skyline, add points where the
boundary is under-sampled, and delete points that landed on nothing.

Geometry
--------
Points are held as (azimuth, elevation) in degrees, the representation
`elevation_mask.ElevationMask` consumes, and drawn in the pixel frame of the
equidistant fisheye image they were extracted from — the same projection
`image_mask.extract_horizon_profile` inverts:

    r = f * (90 deg - elevation)          [f in px/rad]
    u = cx + r * sin(azimuth - north_offset)
    v = cy + r * cos(azimuth - north_offset)

Working in the image frame is what makes the correction possible: the user
sees the photograph, not an abstraction of it, and drags the boundary onto the
roofline they can see.

Orientation
-------------------------------------------
That projection puts north at the *bottom*, which is surprising for
the auto-mask preview: comparing the image with the resulting skyplot means
mentally flipping one of them. The preview was turned north-up; this editor is
the window where the points are actually dragged, so it has to agree with it.

The fix is a display flip only: `_flip_v` mirrors the vertical pixel axis for
everything that is drawn, and mirrors mouse coordinates back before they are
interpreted. `to_pixel` / `to_azel` still speak the image's own frame, so the
profile that leaves the editor is unchanged and no other module has to know.
"""

import numpy as np
import matplotlib
matplotlib.use('TkAgg')
import matplotlib.pyplot as plt
from matplotlib.patches import PathPatch
from matplotlib.path import Path
from matplotlib.widgets import Button

DEFAULT_FOV_DEG = 180.0

#: Canvas size used when the profile is edited without a background image.
_BLANK_CANVAS_PX = 900

#: How close a click must be to a point, in pixels, to grab it.
_PICK_RADIUS_PX = 14

#: Elevation rings drawn as orientation guides.
_GUIDE_ELEVATIONS = (0, 15, 30, 45, 60, 75)

_COMPASS = ((0.0, 'N'), (90.0, 'E'), (180.0, 'S'), (270.0, 'W'))


class HorizonProfileEditor:
    """Drag-to-correct editor for a horizon profile.

    Usage:
        editor = HorizonProfileEditor(points, background=fisheye_image)
        corrected = editor.run()   # list of (az, el), or None if cancelled

    Args:
        points: Starting profile as (azimuth_deg, elevation_deg) pairs. May be
            empty, in which case the editor works as a plain digitizer.
        background: Optional fisheye image (H, W, 3) the profile was derived
            from. Without it the points are edited against the guide rings only.
        north_offset_deg: North offset that was applied when the profile was
            generated, so that screen positions and azimuths stay consistent.
        fov_deg: Field of view of the image circle, in degrees.
        title: Optional subtitle, normally the source image's file name.
    """

    def __init__(self, points, background=None, north_offset_deg=0.0,
                 fov_deg=DEFAULT_FOV_DEG, title=None,
                 camera_elevation_deg=90.0, tilt_azimuth_deg=0.0):
        self.points = [(float(az), float(el)) for az, el in (points or [])]
        self.original = list(self.points)
        self.background = background
        self.north_offset = float(north_offset_deg)
        self.fov_deg = float(fov_deg)
        self.camera_elevation = float(camera_elevation_deg)
        self.tilt_azimuth = float(tilt_azimuth_deg)
        self.title = title

        if background is not None:
            height, width = background.shape[:2]
            self.radius = min(width, height) / 2.0
            self.cx, self.cy = width / 2.0, height / 2.0
            # np.flipud maps row v to row (H-1-v); the overlays are mirrored
            # about the same axis so image and drawing cannot drift apart.
            self._flip_axis = float(height - 1)
        else:
            self.radius = _BLANK_CANVAS_PX / 2.0
            self.cx = self.cy = self.radius
            self._flip_axis = 2.0 * self.cy
        self.f_px = self.radius / np.deg2rad(self.fov_deg / 2.0)

        self.result = None
        self._drag_index = None
        self.fig = None
        self.ax = None

    # ---- Projection ----

    def _tilt(self, az, el, inverse):
        """Apply the camera tilt, matching `image_mask.extract_horizon_profile`."""
        from image_mask import apply_camera_tilt
        return apply_camera_tilt(az, el,
                                 camera_elevation_deg=self.camera_elevation,
                                 tilt_azimuth_deg=self.tilt_azimuth,
                                 inverse=inverse)

    def to_pixel(self, az, el):
        """Project (azimuth, elevation) in degrees to (u, v) image pixels."""
        # Back into the camera's own frame: undo the tilt, then the heading.
        az_img, el_img = self._tilt(az, el, inverse=True)
        r = self.f_px * np.deg2rad(90.0 - el_img)
        theta = np.deg2rad(az_img - self.north_offset)
        return self.cx + r * np.sin(theta), self.cy + r * np.cos(theta)

    def _flip_v(self, v):
        """
        Mirror the vertical pixel axis.

        Its own inverse, so the same call converts image -> screen for drawing
        and screen -> image for a mouse position. Everything the user sees goes
        through it; nothing the user gets back does.
        """
        return self._flip_axis - np.asarray(v, dtype=float)

    def to_screen(self, az, el):
        """`to_pixel`, mirrored for display: north ends up at the top."""
        u, v = self.to_pixel(az, el)
        return u, self._flip_v(v)

    def to_azel(self, u, v):
        """Invert `to_pixel`: image pixels back to (azimuth, elevation) in degrees."""
        du, dv = u - self.cx, v - self.cy
        el_img = 90.0 - np.rad2deg(np.hypot(du, dv) / self.f_px)
        az_img = np.rad2deg(np.arctan2(du, dv)) + self.north_offset
        az, el = self._tilt(az_img, el_img, inverse=False)
        return float(az) % 360.0, float(np.clip(el, 0.0, 90.0))

    # ---- Window ----

    def run(self):
        """Open the editor and block until it is closed.

        Returns:
            The corrected list of (azimuth, elevation) pairs sorted by azimuth,
            or None if the user cancelled.
        """
        self.result = None
        self.fig = plt.figure(figsize=(9.5, 9.5))
        self.fig.canvas.manager.set_window_title('RINEX-Masker: Fine-Tune Obstruction Points')
        self.ax = self.fig.add_axes([0.06, 0.13, 0.88, 0.74])

        if self.background is not None:
            # Shown north-up, like the auto-mask preview and the
            # skyplot. The array on disk is untouched.
            self.ax.imshow(np.flipud(self.background))
        else:
            self.ax.set_facecolor('#2b2b2b')
        span = self.radius * 1.04
        self.ax.set_xlim(self.cx - span, self.cx + span)
        self.ax.set_ylim(self.cy + span, self.cy - span)  # image row order
        self.ax.set_aspect('equal')
        self.ax.axis('off')

        self._draw_guides()

        self.blocked_patch = None
        self.line_artist, = self.ax.plot([], [], '-', color='#ff3b30', lw=1.8, zorder=8)
        self.point_artist, = self.ax.plot([], [], 'o', color='#ff3b30',
                                          markersize=6, markeredgecolor='white',
                                          markeredgewidth=0.8, zorder=10, picker=False)
        self._redraw_profile()

        heading = "Drag a point to correct it   |   click empty space = add   |   right-click a point = delete"
        # Same wording as the auto-mask preview, so the two windows
        # explain themselves the same way.
        note = "Shown north-up to match the skyplot (the photo itself is north-at-bottom and is not modified)."
        # An axes title is offset from the axes in points, so in a window
        # the user has made short and wide the top of a three line caption
        # runs off the edge. Anchored to the figure it cannot, at any
        # window shape or text scaling.
        self.fig.text(0.5, 0.985,
                      f"{heading}\n{self.title}\n{note}" if self.title
                      else f"{heading}\n{note}",
                      ha='center', va='top', fontsize=10)

        self.status_text = self.fig.text(0.5, 0.075, "", ha='center', fontsize=9.5,
                                         color='#555555')
        self._update_status()

        self.fig.canvas.mpl_connect('button_press_event', self._on_press)
        self.fig.canvas.mpl_connect('motion_notify_event', self._on_motion)
        self.fig.canvas.mpl_connect('button_release_event', self._on_release)

        self._buttons = []
        for x, label, colour, hover, handler in (
                (0.29, 'Apply', '#4CAF50', '#66BB6A', self._on_apply),
                (0.44, 'Reset', '#FF9800', '#FFB74D', self._on_reset),
                (0.59, 'Cancel', '#9E9E9E', '#BDBDBD', self._on_cancel)):
            btn = Button(self.fig.add_axes([x, 0.02, 0.12, 0.042]), label,
                         color=colour, hovercolor=hover)
            btn.on_clicked(handler)
            self._buttons.append(btn)  # keep alive; matplotlib does not

        plt.show()
        return self.result

    def _draw_guides(self):
        """Draw elevation rings and compass labels for orientation.

        The rings are drawn as projected curves rather than circles: under a
        camera tilt, lines of constant elevation are no longer concentric.
        """
        ring_az = np.linspace(0.0, 360.0, 181)
        for el in _GUIDE_ELEVATIONS:
            ru, rv = self.to_screen(ring_az, np.full_like(ring_az, float(el)))
            self.ax.plot(ru, rv, color='#ffffff', alpha=0.35, lw=0.8, zorder=5)
            label_u, label_v = self.to_screen(0.0, float(el))
            self.ax.text(float(label_u), float(label_v), f"{el}°", color='white',
                         fontsize=7.5, ha='center', va='bottom', alpha=0.7, zorder=6)

        for az, label in _COMPASS:
            u, v = self.to_screen(az, -4.0)
            self.ax.text(float(u), float(v), label, color='#ffd166', fontsize=12,
                         weight='bold', ha='center', va='center', zorder=6)

    # ---- Drawing ----

    def _sorted_points(self):
        return sorted(self.points, key=lambda p: p[0])

    def _redraw_profile(self):
        """Refresh the points, the skyline and the shaded obstructed region."""
        if self.points:
            u, v = self.to_screen([p[0] for p in self.points],
                                  [p[1] for p in self.points])
            self.point_artist.set_data(u, v)
        else:
            self.point_artist.set_data([], [])

        ordered = self._sorted_points()
        if len(ordered) >= 2:
            closed = ordered + [ordered[0]]
            lu, lv = self.to_screen([p[0] for p in closed], [p[1] for p in closed])
            self.line_artist.set_data(lu, lv)
        else:
            self.line_artist.set_data([], [])

        if self.blocked_patch is not None:
            self.blocked_patch.remove()
            self.blocked_patch = None
        if len(ordered) >= 3:
            self.blocked_patch = self._make_blocked_patch(ordered)
            self.ax.add_patch(self.blocked_patch)

    def _make_blocked_patch(self, ordered):
        """Build the ring between the skyline and the horizon: what is blocked."""
        horizon_az = np.linspace(0.0, 360.0, 181)
        hu, hv = self.to_screen(horizon_az, np.zeros_like(horizon_az))
        su, sv = self.to_screen([p[0] for p in ordered], [p[1] for p in ordered])

        # Matplotlib fills compound paths by the non-zero winding rule, so the
        # skyline has to be wound against the horizon circle for it to punch a
        # hole. Then only the obstructed ring is shaded, and the sky stays clear.
        inner = list(zip(su, sv))[::-1]
        verts = list(zip(hu, hv)) + [(hu[0], hv[0])] + inner + [inner[0]]
        codes = ([Path.MOVETO] + [Path.LINETO] * (len(hu) - 1) + [Path.CLOSEPOLY] +
                 [Path.MOVETO] + [Path.LINETO] * (len(su) - 1) + [Path.CLOSEPOLY])
        return PathPatch(Path(verts, codes), facecolor='#ff3b30', alpha=0.18,
                         edgecolor='none', zorder=7)

    def _update_status(self, extra=None):
        n = len(self.points)
        if extra:
            msg = extra
        elif n == 0:
            msg = "No points — click along the skyline to build the profile"
        else:
            blocked = sum(1 for _, el in self.points if el > 0.0)
            highest = max(el for _, el in self.points)
            msg = (f"{n} point{'s' if n != 1 else ''}   |   {blocked} obstructed   |   "
                   f"highest horizon {highest:.1f}°")
        self.status_text.set_text(msg)

    # ---- Interaction ----

    def _nearest_point(self, u, v):
        """Index of the point within the pick radius of image pixel (u, v), else None."""
        if not self.points:
            return None
        pu, pv = self.to_pixel([p[0] for p in self.points],
                               [p[1] for p in self.points])
        distances = np.hypot(pu - u, pv - v)
        index = int(np.argmin(distances))
        # The pick radius is in screen pixels; the axes are in image pixels.
        scale = self._image_px_per_screen_px()
        return index if distances[index] <= _PICK_RADIUS_PX * scale else None

    def _image_px_per_screen_px(self):
        """Image pixels covered by one screen pixel, for hit-testing."""
        bbox = self.ax.get_window_extent()
        if bbox.width <= 0:
            return 1.0
        x0, x1 = self.ax.get_xlim()
        return abs(x1 - x0) / bbox.width

    def _on_press(self, event):
        if event.inaxes != self.ax or event.xdata is None:
            return

        # The canvas is mirrored for display; come back to the
        # image frame first, so a click lands on the azimuth it looks like.
        v_img = float(self._flip_v(event.ydata))
        index = self._nearest_point(event.xdata, v_img)

        if event.button == 1:
            if index is not None:
                self._drag_index = index
                az, el = self.points[index]
                self._update_status(f"Moving point — Az {az:.1f}°  El {el:.1f}°")
            else:
                az, el = self.to_azel(event.xdata, v_img)
                self.points.append((az, el))
                self._redraw_profile()
                self._update_status(
                    f"Added Az {az:.1f}°  El {el:.1f}°"
                    f"{self._neighbour_note(az)}")
            self.fig.canvas.draw_idle()

        elif event.button == 3 and index is not None:
            az, el = self.points.pop(index)
            self._redraw_profile()
            self._update_status(f"Deleted Az {az:.1f}°  El {el:.1f}°")
            self.fig.canvas.draw_idle()

    def _neighbour_note(self, az):
        """
        Which points a newly added one sits between, in azimuth.

        A new point could be connected to
        another line then I would have expected. My initial guess would be that
        it is added to the line with the smallest distance."

        It cannot be: the skyline is a horizon profile, one elevation per
        azimuth, so it is always drawn in azimuth order and a new point joins
        its azimuth neighbours, not whatever segment happens to be nearest on
        screen. A point clicked well inside the sky therefore shows as a spike,
        which is correct but does not look it. Naming the neighbours at least
        makes it obvious where the point went.
        """
        try:
            others = sorted(p[0] for p in self.points[:-1])
            if not others:
                return ""
            before = max((a for a in others if a <= az), default=others[-1])
            after = min((a for a in others if a >= az), default=others[0])
            return f"  (in the skyline between Az {before:.1f}° and {after:.1f}°)"
        except Exception:
            return ""

    def _on_motion(self, event):
        if self._drag_index is None or event.inaxes != self.ax or event.xdata is None:
            return
        az, el = self.to_azel(event.xdata, float(self._flip_v(event.ydata)))
        self.points[self._drag_index] = (az, el)
        self._redraw_profile()
        self._update_status(f"Moving point — Az {az:.1f}°  El {el:.1f}°")
        self.fig.canvas.draw_idle()

    def _on_release(self, event):
        if self._drag_index is None:
            return
        self._drag_index = None
        self._update_status()
        self.fig.canvas.draw_idle()

    # ---- Buttons ----

    def _on_apply(self, event):
        if len(self.points) < 2:
            self._update_status("A profile needs at least 2 points")
            self.status_text.set_color('#c62828')
            self.fig.canvas.draw_idle()
            return
        self.result = self._sorted_points()
        plt.close(self.fig)

    def _on_reset(self, event):
        self.points = list(self.original)
        self._drag_index = None
        self._redraw_profile()
        self.status_text.set_color('#555555')
        self._update_status("Reset to the generated profile")
        self.fig.canvas.draw_idle()

    def _on_cancel(self, event):
        self.result = None
        plt.close(self.fig)


def edit_profile(points, background=None, north_offset_deg=0.0,
                 fov_deg=DEFAULT_FOV_DEG, title=None):
    """Convenience wrapper around `HorizonProfileEditor`.

    Returns:
        The corrected list of (azimuth, elevation) pairs, or None if cancelled.
    """
    editor = HorizonProfileEditor(points, background=background,
                                  north_offset_deg=north_offset_deg,
                                  fov_deg=fov_deg, title=title)
    return editor.run()
