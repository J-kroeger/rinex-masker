# digitizer.py
"""
Interactive digitizer for RINEX-Masker.
Allows the user to load a polar skyplot image (like obstructionMask.png)
and click points along the horizon boundary to create a profile.

The image is displayed on a polar axes. Clicks are converted from
pixel coordinates to (azimuth, elevation) using the axes coordinate system.
"""

import numpy as np
import matplotlib
matplotlib.use('TkAgg')
import matplotlib.pyplot as plt
from matplotlib.widgets import Button


class HorizonDigitizer:
    """
    Interactive matplotlib window for digitizing horizon profiles from polar images.
    
    Usage:
        digitizer = HorizonDigitizer()
        points = digitizer.run(image_path)
        # points is a list of (azimuth_deg, elevation_deg) pairs, or None if cancelled
    """
    
    def __init__(self):
        self.points = []       # List of (azimuth_deg, elevation_deg)
        self.point_artists = []
        self.line_artist = None
        self.result = None     # Final result: list of (az, el) or None
        self.fig = None
        self.ax = None
    
    def run(self, image_path=None):
        """
        Open the digitizer window. Optionally overlay a polar skyplot image.
        
        Args:
            image_path: Optional path to a polar skyplot PNG to overlay
            
        Returns:
            List of (azimuth_deg, elevation_deg) pairs, or None if cancelled
        """
        self.points = []
        self.point_artists = []
        self.result = None
        
        # Create figure
        self.fig = plt.figure(figsize=(10, 10))
        self.fig.canvas.manager.set_window_title('RINEX-Masker: Horizon Digitizer')
        
        # Main polar axes
        self.ax = self.fig.add_axes([0.1, 0.15, 0.8, 0.75], projection='polar')
        self.ax.set_theta_zero_location('N')
        self.ax.set_theta_direction(-1)
        self.ax.set_rlim(0, 90)
        self.ax.set_rgrids([0, 15, 30, 45, 60, 75, 90],
                           labels=['90', '75', '60', '45', '30', '15', '0'])
        self.ax.set_title("Click along the horizon boundary\n"
                          "(left-click = add, right-click = remove last, close = done)",
                          fontsize=11, pad=15)
        
        # Overlay image if provided
        if image_path:
            self._overlay_image(image_path)
        
        # Connect click events
        self.fig.canvas.mpl_connect('button_press_event', self._on_click)
        
        # Buttons
        ax_done = self.fig.add_axes([0.35, 0.02, 0.15, 0.04])
        ax_clear = self.fig.add_axes([0.52, 0.02, 0.15, 0.04])
        
        btn_done = Button(ax_done, 'Done', color='#4CAF50', hovercolor='#66BB6A')
        btn_done.on_clicked(self._on_done)
        btn_clear = Button(ax_clear, 'Clear All', color='#FF9800', hovercolor='#FFB74D')
        btn_clear.on_clicked(self._on_clear)
        
        # Status text
        self.status_text = self.fig.text(0.5, 0.08, "0 points | Left-click to add, right-click to undo",
                                         ha='center', fontsize=9, color='gray')
        
        plt.show()
        
        return self.result
    
    def _overlay_image(self, image_path):
        """Overlay a polar skyplot image on the axes."""
        try:
            from PIL import Image
            img = Image.open(image_path)
            img_array = np.array(img)
            
            # Display the image as background on the polar axes
            # Map the image to cover the full polar plot area
            # The image is assumed to be a polar plot with:
            #   - North at top, clockwise azimuths
            #   - Center = zenith (90 deg elevation), edge = horizon (0 deg)
            self.ax.imshow(img_array, extent=[0, 2*np.pi, 90, 0],
                          aspect='auto', alpha=0.5, zorder=0,
                          interpolation='bilinear')
        except Exception as e:
            print(f"Warning: Could not load image: {e}")
            # Just show empty polar plot — user can still click
    
    def _on_click(self, event):
        """Handle mouse click on the polar axes."""
        if event.inaxes != self.ax:
            return
        
        if event.button == 1:  # Left click — add point
            # In polar axes: event.xdata = theta (radians), event.ydata = r
            theta_rad = event.xdata
            r = event.ydata
            
            # Convert to azimuth/elevation
            azimuth = np.rad2deg(theta_rad) % 360
            elevation = 90.0 - r  # r=0 is zenith (el=90), r=90 is horizon (el=0)
            elevation = max(0, min(90, elevation))
            
            self.points.append((azimuth, elevation))
            
            # Draw point
            pt, = self.ax.plot(theta_rad, r, 'ro', markersize=6, zorder=10)
            self.point_artists.append(pt)
            
            self._update_line()
            self._update_status()
            self.fig.canvas.draw_idle()
            
        elif event.button == 3:  # Right click — remove last point
            if self.points:
                self.points.pop()
                if self.point_artists:
                    artist = self.point_artists.pop()
                    artist.remove()
                self._update_line()
                self._update_status()
                self.fig.canvas.draw_idle()
    
    def _update_line(self):
        """Update the connecting line between points."""
        if self.line_artist:
            self.line_artist.remove()
            self.line_artist = None
        
        if len(self.points) >= 2:
            # Sort points by azimuth for the line
            sorted_pts = sorted(self.points, key=lambda p: p[0])
            # Close the loop
            sorted_pts.append(sorted_pts[0])
            
            thetas = [np.deg2rad(p[0]) for p in sorted_pts]
            rs = [90.0 - p[1] for p in sorted_pts]
            
            self.line_artist, = self.ax.plot(thetas, rs, 'r-', linewidth=1.5,
                                             alpha=0.7, zorder=9)
    
    def _update_status(self):
        """Update the status text."""
        n = len(self.points)
        if n == 0:
            msg = "0 points | Left-click to add, right-click to undo"
        elif n == 1:
            msg = f"1 point | Add more points to define the boundary"
        else:
            msg = f"{n} points | Click 'Done' when finished"
        self.status_text.set_text(msg)
    
    def _on_done(self, event):
        """Finish digitizing and return the profile."""
        if len(self.points) < 2:
            self.status_text.set_text("Need at least 2 points!")
            self.status_text.set_color('red')
            self.fig.canvas.draw_idle()
            return
        
        # Sort by azimuth
        self.result = sorted(self.points, key=lambda p: p[0])
        plt.close(self.fig)
    
    def _on_clear(self, event):
        """Clear all points."""
        self.points.clear()
        for artist in self.point_artists:
            artist.remove()
        self.point_artists.clear()
        if self.line_artist:
            self.line_artist.remove()
            self.line_artist = None
        self._update_status()
        self.fig.canvas.draw_idle()


def digitize_image(image_path=None):
    """
    Convenience function to digitize a horizon profile.
    
    Args:
        image_path: Optional path to polar skyplot image
        
    Returns:
        List of (azimuth, elevation) tuples, or None
    """
    digitizer = HorizonDigitizer()
    return digitizer.run(image_path)


if __name__ == '__main__':
    import sys
    img = sys.argv[1] if len(sys.argv) > 1 else None
    result = digitize_image(img)
    if result:
        print(f"\nDigitized {len(result)} points:")
        for az, el in result:
            print(f"  Az={az:.1f}, El={el:.1f}")
    else:
        print("Cancelled.")
