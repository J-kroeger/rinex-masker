# main_gui.py
"""
RINEX-Masker graphical user interface.
Built with tkinter/ttkbootstrap, matching PCC-Explorer's visual style.
"""

import tkinter as tk
import ttkbootstrap as ttk
from ttkbootstrap.constants import *
from tkinter import filedialog, messagebox
import os
import sys
import threading
from datetime import datetime

# Shared opt-in dialog for the IfE software mailing list. Never let a missing
# copy stop the program from starting; the canonical file is in shared/.
try:
    import mailing_list
except Exception:
    mailing_list = None

# Version and release date, from this tool's own tool_version.py. The same pair
# sits in the README tag that the PCC-Suite launcher reads, so the launcher no
# longer has to guess a release from a file timestamp.
try:
    import tool_version
    import version_info
    VERSION_TEXT = version_info.about_line(tool_version)
except Exception:
    VERSION_TEXT = "Version: unknown"

# --- PATH HELPER FOR EXE ---
def resource_path(relative_path):
    """Get absolute path to resource, works for dev and PyInstaller."""
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, relative_path)


class CreateToolTip:
    """Create a tooltip for a given widget."""
    def __init__(self, widget, text='widget info'):
        self.waittime = 500
        self.wraplength = 300
        self.widget = widget
        self.text = text
        self.widget.bind("<Enter>", self.enter)
        self.widget.bind("<Leave>", self.leave)
        self.widget.bind("<ButtonPress>", self.leave)
        self.id = None
        self.tw = None

    def enter(self, event=None):
        self.unschedule()
        self.id = self.widget.after(self.waittime, self.showtip)

    def leave(self, event=None):
        self.unschedule()
        if self.tw:
            self.tw.destroy()
            self.tw = None

    def unschedule(self):
        _id = self.id
        self.id = None
        if _id:
            self.widget.after_cancel(_id)

    def showtip(self, event=None):
        x, y, _, _ = self.widget.bbox("insert")
        x += self.widget.winfo_rootx() + 25
        y += self.widget.winfo_rooty() + 20
        self.tw = tk.Toplevel(self.widget)
        self.tw.wm_overrideredirect(True)
        self.tw.wm_geometry(f"+{x}+{y}")
        label = tk.Label(self.tw, text=self.text, justify='left',
                         background="#ffffe0", relief='solid', borderwidth=1,
                         wraplength=self.wraplength)
        label.pack(ipadx=1)


def _show_ife_contact(parent):
    """
    IfE contact dialog with clickable e-mail and web links.

    Same content and layout as PCC-Explorer's, so every tool in the suite
    presents its contact details identically.
    """
    import webbrowser

    dialog = tk.Toplevel(parent)
    dialog.title("Contact Information")
    dialog.geometry("460x300")
    dialog.resizable(False, False)
    dialog.transient(parent)
    dialog.grab_set()

    frame = ttk.Frame(dialog, padding=20)
    frame.pack(fill="both", expand=True)

    ttk.Label(frame, text="Institut für Erdmessung (IfE)",
              font=("Helvetica", 12, "bold")).pack(anchor="w")
    ttk.Label(frame, text="Leibniz Universität Hannover").pack(anchor="w")
    ttk.Label(frame, text="Schneiderberg 50").pack(anchor="w")
    ttk.Label(frame, text="D-30167 Hannover").pack(anchor="w", pady=(0, 15))

    ttk.Label(frame, text="Contact: Dr.-Ing. Johannes Kröger",
              font=("Helvetica", 10, "bold")).pack(anchor="w")

    email_frame = ttk.Frame(frame)
    email_frame.pack(anchor="w", pady=2)
    ttk.Label(email_frame, text="Email: ").pack(side="left")
    email_link = ttk.Label(email_frame, text="kroeger@ife.uni-hannover.de",
                           foreground="#4da6ff", cursor="hand2")
    email_link.pack(side="left")
    email_link.bind("<Button-1>",
                    lambda e: webbrowser.open("mailto:kroeger@ife.uni-hannover.de"))

    web_frame = ttk.Frame(frame)
    web_frame.pack(anchor="w", pady=2)
    ttk.Label(web_frame, text="Web: ").pack(side="left")
    web_link = ttk.Label(web_frame, text="www.ife.uni-hannover.de",
                         foreground="#4da6ff", cursor="hand2")
    web_link.pack(side="left")
    web_link.bind("<Button-1>",
                  lambda e: webbrowser.open("https://www.ife.uni-hannover.de"))

    def _open_mailing_list():
        # Close first. Two stacked modal dialogs each take the grab, and the
        # inner one releasing it would leave this window unresponsive.
        dialog.destroy()
        try:
            parent._show_mailing_list()
        except Exception:
            pass

    buttons = ttk.Frame(frame)
    buttons.pack(pady=(20, 0))
    ttk.Button(buttons, text="Mailing list", command=_open_mailing_list,
               bootstyle="outline-info").pack(side="left", padx=4)
    ttk.Button(buttons, text="Close", command=dialog.destroy,
               bootstyle="secondary").pack(side="left", padx=4)

    # Size to the content, with 460x300 as the minimum: a fixed size would cut
    # the buttons off on systems with larger fonts or display scaling.
    dialog.update_idletasks()
    dialog.geometry("%dx%d" % (max(460, dialog.winfo_reqwidth()),
                               max(300, dialog.winfo_reqheight())))


class App(ttk.Window):
    def __init__(self):
        super().__init__(themename="darkly")
        self.azimuth_masks_list = []
        self.last_stats = None
        self.is_running = False

        self._setup_window()
        self._create_widgets()
        self._fit_top_bar()
        self.protocol("WM_DELETE_WINDOW", self._on_closing)

    def _fit_top_bar(self):
        """
        Widen the window if the header row does not fit in it.

        The window size is set in pixels while the fonts follow the system
        text scaling, so with larger system text the header row can run off the
        edge and truncate its buttons. Measuring what the row needs is the only
        thing that holds on any display.
        """
        try:
            bar = getattr(self, "_top_bar", None)
            if bar is None:
                return
            self.update_idletasks()
            need = bar.winfo_reqwidth() + 8
            if need <= self.winfo_width():
                return
            height = self.winfo_height()
            self.geometry("%dx%d" % (need, height))
            min_w, min_h = self.minsize()
            if need > min_w:
                self.minsize(need, min_h)
        except Exception as exc:
            print("[WARNING] Could not fit the header row: %s" % exc)

    def _get_results_dir(self):
        """Get (and create) the results output folder next to the exe/script."""
        try:
            base = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__))
        except Exception:
            base = os.getcwd()
        results_dir = os.path.join(base, 'results')
        os.makedirs(results_dir, exist_ok=True)
        return results_dir

    def _setup_window(self):
        self.title("RINEX-Masker")
        self.geometry("900x950")
        self.minsize(750, 800)

    def _on_closing(self):
        if self.is_running:
            if messagebox.askokcancel("Quit", "Processing is still running. Quit anyway?"):
                self.destroy()
        else:
            self.destroy()

    # ----------------------------------------------------------------
    # Widget Creation
    # ----------------------------------------------------------------
    def _create_widgets(self):
        # === TOP BAR ===
        top_bar = ttk.Frame(self, padding=10)
        top_bar.pack(fill="x")
        # Kept so the window can be widened if this row does not fit.
        self._top_bar = top_bar

        # Left: IfE logo + title
        left_frame = ttk.Frame(top_bar)
        left_frame.pack(side="left")

        self.logo_img = None
        ife_logo_path = resource_path(os.path.join('assets', 'ife_logo.png'))
        if os.path.exists(ife_logo_path):
            try:
                from PIL import Image, ImageTk
                pil_image = Image.open(ife_logo_path)
                aspect = pil_image.width / pil_image.height
                h = 45
                resized = pil_image.resize((int(h * aspect), h), Image.Resampling.LANCZOS)
                self.logo_img = ImageTk.PhotoImage(resized)
                ttk.Label(left_frame, image=self.logo_img).pack(side="left", padx=(0, 12))
            except Exception:
                pass

        text_frame = ttk.Frame(left_frame)
        text_frame.pack(side="left")
        ttk.Label(text_frame, text="RINEX-Masker", font=("Helvetica", 18, "bold")).pack(anchor="w")
        ttk.Label(text_frame, text="Institut für Erdmessung (IfE)", font=("Helvetica", 10), bootstyle="light").pack(anchor="w")

        # Right: LUH logo
        self.luh_logo_img = None
        luh_logo_path = resource_path(os.path.join('assets', 'luh_logo.png'))
        if os.path.exists(luh_logo_path):
            try:
                from PIL import Image, ImageTk
                pil_luh = Image.open(luh_logo_path)
                h = 50
                aspect = pil_luh.width / pil_luh.height
                resized_luh = pil_luh.resize((int(h * aspect), h), Image.Resampling.LANCZOS)
                self.luh_logo_img = ImageTk.PhotoImage(resized_luh)
                luh_frame = ttk.Frame(top_bar)
                luh_frame.pack(side="right", padx=(10, 0))
                ttk.Label(luh_frame, image=self.luh_logo_img).pack(side="right")
            except Exception:
                pass

        # Info & Contact buttons
        btn_frame = ttk.Frame(top_bar)
        btn_frame.pack(side="right", padx=15)
        ttk.Button(btn_frame, text="Contact", command=self._show_contact, bootstyle="outline-info").pack(side="left", padx=3)
        ttk.Button(btn_frame, text="Information", command=self._show_about, bootstyle="outline-secondary").pack(side="left", padx=3)

        ttk.Separator(self, orient='horizontal').pack(fill='x', pady=(0, 5))

        # === MAIN SCROLLABLE AREA ===
        main_container = ttk.Frame(self)
        main_container.pack(fill="both", expand=True, padx=10, pady=2)

        canvas = tk.Canvas(main_container, highlightthickness=0)
        scrollbar = ttk.Scrollbar(main_container, orient="vertical", command=canvas.yview)
        scrollable = ttk.Frame(canvas)

        scrollable.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scrollable, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        canvas.bind_all("<MouseWheel>", _on_mousewheel)

        content = ttk.Frame(scrollable, padding=10)
        content.pack(fill="both", expand=True)

        # --- Input Files ---
        self._create_file_widgets(content)
        # --- Receiver Position ---
        self._create_position_widgets(content)
        # --- Time Filter ---
        self._create_time_filter_widgets(content)
        # --- Signal Quality (C/N₀) ---
        self._create_cn0_widgets(content)
        # --- Obstruction Mask ---
        self._create_mask_widgets(content)
        # --- Output ---
        self._create_output_widgets(content)
        # --- Progress / Log ---
        self._create_progress_widgets(content)

        # === BOTTOM BUTTONS ===
        btn_bar = ttk.Frame(self, padding=10)
        btn_bar.pack(side="bottom", fill="x")

        self.run_btn = ttk.Button(btn_bar, text="Run Masking", command=self._run_masking, bootstyle="success")
        self.run_btn.pack(side="left", padx=5)
        ttk.Button(btn_bar, text="Show Last Skyplot", command=self._show_skyplot, bootstyle="info-outline").pack(side="left", padx=5)
        ttk.Button(btn_bar, text="Close Figures", command=self._close_figures, bootstyle="warning-outline").pack(side="left", padx=5)
        ttk.Button(btn_bar, text="Quit", command=self._on_closing, bootstyle="danger-outline").pack(side="right", padx=5)

    # --- File selection ---
    def _create_file_widgets(self, parent):
        frame = ttk.LabelFrame(parent, text="Input Files", padding=10)
        frame.pack(fill="x", pady=(0, 8))

        # RINEX
        ttk.Label(frame, text="RINEX File:").grid(row=0, column=0, sticky="w", padx=5, pady=3)
        self.rinex_path = tk.StringVar()
        ttk.Entry(frame, textvariable=self.rinex_path, width=55).grid(row=0, column=1, padx=5, pady=3, sticky="ew")
        ttk.Button(frame, text="Browse…", command=lambda: self._browse_file(self.rinex_path, "RINEX"), bootstyle="outline-primary").grid(row=0, column=2, padx=5, pady=3)

        # SP3
        ttk.Label(frame, text="SP3 File:").grid(row=1, column=0, sticky="w", padx=5, pady=3)
        self.sp3_path = tk.StringVar()
        self.sp3_entry = ttk.Entry(frame, textvariable=self.sp3_path, width=55)
        self.sp3_entry.grid(row=1, column=1, padx=5, pady=3, sticky="ew")
        ttk.Button(frame, text="Browse…", command=lambda: self._browse_file(self.sp3_path, "SP3"), bootstyle="outline-primary").grid(row=1, column=2, padx=5, pady=3)

        self.auto_sp3_var = tk.BooleanVar(value=True)
        cb = ttk.Checkbutton(frame, text="Auto-download SP3 from AIUB/CODE (if not provided above)",
                             variable=self.auto_sp3_var, command=self._toggle_sp3)
        cb.grid(row=2, column=0, columnspan=3, sticky="w", padx=5, pady=2)
        CreateToolTip(cb, "When checked, SP3 orbits are automatically downloaded\n"
                         "from AIUB FTP (CODE MGEX) based on the RINEX date.\n"
                         "No login required.")

        frame.columnconfigure(1, weight=1)
        self._toggle_sp3()

    def _toggle_sp3(self):
        state = "disabled" if self.auto_sp3_var.get() else "normal"
        self.sp3_entry.configure(state=state)

    # --- Receiver Position ---
    def _create_position_widgets(self, parent):
        frame = ttk.LabelFrame(parent, text="Receiver Position", padding=10)
        frame.pack(fill="x", pady=(0, 8))

        # Radio: Auto / ECEF / Lat-Lon-H
        self.pos_mode_var = tk.StringVar(value="auto")
        radio_row = ttk.Frame(frame)
        radio_row.pack(fill="x", pady=3)
        ttk.Radiobutton(radio_row, text="Auto (from RINEX header)",
                        variable=self.pos_mode_var, value="auto",
                        command=self._toggle_pos).pack(side="left", padx=5)
        ttk.Radiobutton(radio_row, text="ECEF (X, Y, Z)",
                        variable=self.pos_mode_var, value="ecef",
                        command=self._toggle_pos).pack(side="left", padx=15)
        ttk.Radiobutton(radio_row, text="Lat / Lon / Height",
                        variable=self.pos_mode_var, value="llh",
                        command=self._toggle_pos).pack(side="left", padx=15)

        # ECEF row
        ecef_row = ttk.Frame(frame)
        ecef_row.pack(fill="x", pady=3)
        ttk.Label(ecef_row, text="X [m]:").pack(side="left", padx=(15, 2))
        self.pos_x_var = tk.StringVar()
        self.pos_x_entry = ttk.Entry(ecef_row, textvariable=self.pos_x_var, width=14, state="disabled")
        self.pos_x_entry.pack(side="left")
        ttk.Label(ecef_row, text="Y [m]:").pack(side="left", padx=(10, 2))
        self.pos_y_var = tk.StringVar()
        self.pos_y_entry = ttk.Entry(ecef_row, textvariable=self.pos_y_var, width=14, state="disabled")
        self.pos_y_entry.pack(side="left")
        ttk.Label(ecef_row, text="Z [m]:").pack(side="left", padx=(10, 2))
        self.pos_z_var = tk.StringVar()
        self.pos_z_entry = ttk.Entry(ecef_row, textvariable=self.pos_z_var, width=14, state="disabled")
        self.pos_z_entry.pack(side="left")

        # LLH row
        llh_row = ttk.Frame(frame)
        llh_row.pack(fill="x", pady=3)
        ttk.Label(llh_row, text="Lat [deg]:").pack(side="left", padx=(15, 2))
        self.pos_lat_var = tk.StringVar()
        self.pos_lat_entry = ttk.Entry(llh_row, textvariable=self.pos_lat_var, width=14, state="disabled")
        self.pos_lat_entry.pack(side="left")
        ttk.Label(llh_row, text="Lon [deg]:").pack(side="left", padx=(10, 2))
        self.pos_lon_var = tk.StringVar()
        self.pos_lon_entry = ttk.Entry(llh_row, textvariable=self.pos_lon_var, width=14, state="disabled")
        self.pos_lon_entry.pack(side="left")
        ttk.Label(llh_row, text="H [m]:").pack(side="left", padx=(10, 2))
        self.pos_h_var = tk.StringVar()
        self.pos_h_entry = ttk.Entry(llh_row, textvariable=self.pos_h_var, width=14, state="disabled")
        self.pos_h_entry.pack(side="left")

    def _toggle_pos(self):
        mode = self.pos_mode_var.get()
        ecef_state = "normal" if mode == "ecef" else "disabled"
        llh_state = "normal" if mode == "llh" else "disabled"
        for w in (self.pos_x_entry, self.pos_y_entry, self.pos_z_entry):
            w.configure(state=ecef_state)
        for w in (self.pos_lat_entry, self.pos_lon_entry, self.pos_h_entry):
            w.configure(state=llh_state)

    def _get_manual_position(self):
        """Return [X, Y, Z] ECEF list if manual position is set, else None."""
        mode = self.pos_mode_var.get()
        if mode == "auto":
            return None
        elif mode == "ecef":
            try:
                x = float(self.pos_x_var.get())
                y = float(self.pos_y_var.get())
                z = float(self.pos_z_var.get())
                return [x, y, z]
            except ValueError:
                messagebox.showerror("Error", "Invalid ECEF coordinates. Enter numeric X, Y, Z in metres.")
                return "error"
        elif mode == "llh":
            try:
                lat = float(self.pos_lat_var.get())
                lon = float(self.pos_lon_var.get())
                h = float(self.pos_h_var.get())
                # Convert LLH to ECEF
                import pyproj
                ecef_proj = pyproj.Proj(proj='geocent', ellps='WGS84', datum='WGS84')
                lla_proj = pyproj.Proj(proj='latlong', ellps='WGS84', datum='WGS84')
                transformer = pyproj.Transformer.from_proj(lla_proj, ecef_proj, always_xy=True)
                x, y, z = transformer.transform(lon, lat, h)
                return [x, y, z]
            except ValueError:
                messagebox.showerror("Error", "Invalid coordinates. Enter numeric Lat [deg], Lon [deg], H [m].")
                return "error"
        return None

    # --- Time Filter ---
    def _create_time_filter_widgets(self, parent):
        frame = ttk.LabelFrame(parent, text="Time Filter (optional)", padding=10)
        frame.pack(fill="x", pady=(0, 8))

        self.time_filter_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(frame, text="Enable time filter",
                        variable=self.time_filter_var,
                        command=self._toggle_time_filter).pack(anchor="w", padx=5, pady=2)

        time_row = ttk.Frame(frame)
        time_row.pack(fill="x", pady=3)
        ttk.Label(time_row, text="Start:").pack(side="left", padx=(15, 2))
        self.time_start_var = tk.StringVar(value="")
        self.time_start_entry = ttk.Entry(time_row, textvariable=self.time_start_var, width=22, state="disabled")
        self.time_start_entry.pack(side="left")
        ttk.Label(time_row, text="End:").pack(side="left", padx=(15, 2))
        self.time_end_var = tk.StringVar(value="")
        self.time_end_entry = ttk.Entry(time_row, textvariable=self.time_end_var, width=22, state="disabled")
        self.time_end_entry.pack(side="left")

        ttk.Label(frame, text="Format: YYYY-MM-DD HH:MM:SS  (leave blank for no limit)",
                  font=("Helvetica", 8), bootstyle="light").pack(anchor="w", padx=15, pady=(0, 2))

    def _toggle_time_filter(self):
        state = "normal" if self.time_filter_var.get() else "disabled"
        self.time_start_entry.configure(state=state)
        self.time_end_entry.configure(state=state)

    def _create_cn0_widgets(self, parent):
        """C/N₀ Signal Quality Filter — with overall + per-signal thresholds."""
        frame = ttk.LabelFrame(parent, text="Signal Quality Filter", padding=10)
        frame.pack(fill="x", pady=(0, 8))

        # --- Overall threshold row ---
        cn0_row = ttk.Frame(frame)
        cn0_row.pack(fill="x", pady=2)

        self.cn0_active_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(cn0_row, text="C/N\u2080 threshold filter:",
                        variable=self.cn0_active_var,
                        command=self._update_cn0_state).pack(side="left")
        self.cn0_threshold_var = tk.StringVar(value="15.0")
        self.cn0_entry = ttk.Entry(cn0_row, textvariable=self.cn0_threshold_var,
                                   width=6, state="disabled")
        self.cn0_entry.pack(side="left", padx=5)
        ttk.Label(cn0_row, text="dB-Hz").pack(side="left")
        ttk.Label(cn0_row, text="(Recommended: 15 dB-Hz)",
                  font=("Helvetica", 8), bootstyle="info").pack(side="left", padx=(10, 0))

        ttk.Label(frame,
                  text="Remove observations with signal strength below the threshold.\n"
                       "Uses the first S-type observable per constellation. Typical range: 15\u201335 dB-Hz.",
                  font=("Helvetica", 8), bootstyle="light", wraplength=500,
                  justify="left").pack(anchor="w", padx=5, pady=(2, 0))

        # --- Advanced: Per-signal thresholds ---
        ttk.Separator(frame, orient='horizontal').pack(fill='x', pady=6)

        self.cn0_advanced_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(frame, text="Advanced: Per-signal C/N\u2080 thresholds",
                        variable=self.cn0_advanced_var,
                        command=self._toggle_cn0_advanced,
                        bootstyle="warning").pack(anchor="w", padx=5)

        ttk.Label(frame,
                  text="\u26A0  Expert setting \u2014 override the global threshold for specific signal types.",
                  font=("Helvetica", 8), bootstyle="warning", wraplength=500,
                  justify="left").pack(anchor="w", padx=5, pady=(1, 3))

        # Per-signal frame (hidden by default)
        self.cn0_per_signal_frame = ttk.Frame(frame)
        # Not packed initially — shown when checkbox toggled

        # Define default signal types grouped by system (fallback if no RINEX loaded)
        self.cn0_signal_entries = {}  # {signal_code: (tk.StringVar, ttk.Entry)}
        self._cn0_signal_groups = {
            'GPS':     ['G_S1C', 'G_S2W', 'G_S2L', 'G_S5Q'],
            'Galileo': ['E_S1C', 'E_S5Q', 'E_S6C', 'E_S7Q', 'E_S8Q'],
            'GLONASS': ['R_S1C', 'R_S2P'],
            'BDS':     ['C_S2I', 'C_S6I', 'C_S7I'],
        }
        self._build_cn0_per_signal_grid()

        ttk.Label(self.cn0_per_signal_frame,
                  text="Leave empty to use global threshold. Enter a value (dB-Hz) to override.",
                  font=("Helvetica", 8), bootstyle="light").grid(
                      row=1, column=0, columnspan=4, padx=5, pady=(4, 0), sticky='w')

    def _create_mask_widgets(self, parent):
        frame = ttk.LabelFrame(parent, text="Obstruction Mask", padding=10)
        frame.pack(fill="x", pady=(0, 8))

        # Uniform cutoff (shared across both tabs)
        el_row = ttk.Frame(frame)
        el_row.pack(fill="x", pady=3)
        ttk.Label(el_row, text="Uniform elevation cutoff:").pack(side="left", padx=5)
        self.cutoff_var = tk.StringVar(value="5.0")
        ttk.Entry(el_row, textvariable=self.cutoff_var, width=6).pack(side="left")
        ttk.Label(el_row, text="[deg]").pack(side="left", padx=(3, 0))

        ttk.Separator(frame, orient='horizontal').pack(fill='x', pady=8)

        # === NOTEBOOK (tabs) ===
        self.mask_notebook = ttk.Notebook(frame)
        self.mask_notebook.pack(fill="x", pady=3)

        # --- Tab 1: Sector Masks ---
        sector_tab = ttk.Frame(self.mask_notebook, padding=5)
        self.mask_notebook.add(sector_tab, text="  Sector Masks  ")
        self._create_sector_tab(sector_tab)

        # --- Tab 2: Horizon Profile ---
        profile_tab = ttk.Frame(self.mask_notebook, padding=5)
        self.mask_notebook.add(profile_tab, text="  Horizon Profile  ")
        self._create_profile_tab(profile_tab)

        # --- Mask JSON Import/Export ---
        ttk.Separator(frame, orient='horizontal').pack(fill='x', pady=6)
        mask_io_row = ttk.Frame(frame)
        mask_io_row.pack(fill="x", pady=3)
        ttk.Button(mask_io_row, text="Export Mask (JSON)",
                   command=self._export_mask_json,
                   bootstyle="outline-secondary").pack(side="left", padx=5, expand=True, fill="x")
        ttk.Button(mask_io_row, text="Import Mask (JSON)",
                   command=self._import_mask_json,
                   bootstyle="outline-secondary").pack(side="left", padx=5, expand=True, fill="x")

    def _create_sector_tab(self, parent):
        """Sector mask UI (original Phase 1 functionality)."""
        self.az_mask_active_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(parent, text="Azimuth sector mask(s) active",
                        variable=self.az_mask_active_var,
                        command=self._update_az_state).pack(anchor="w", padx=5, pady=3)

        input_row = ttk.Frame(parent)
        input_row.pack(fill="x", pady=3)
        ttk.Label(input_row, text="From:").pack(side="left", padx=(15, 2))
        self.az_from_var = tk.StringVar(value="0")
        self.az_from_entry = ttk.Entry(input_row, textvariable=self.az_from_var, width=6, state="disabled")
        self.az_from_entry.pack(side="left")
        ttk.Label(input_row, text="To:").pack(side="left", padx=(10, 2))
        self.az_to_var = tk.StringVar(value="90")
        self.az_to_entry = ttk.Entry(input_row, textvariable=self.az_to_var, width=6, state="disabled")
        self.az_to_entry.pack(side="left")
        ttk.Label(input_row, text="[deg],  El <").pack(side="left", padx=(10, 2))
        self.az_el_var = tk.StringVar(value="30")
        self.az_el_entry = ttk.Entry(input_row, textvariable=self.az_el_var, width=6, state="disabled")
        self.az_el_entry.pack(side="left")
        ttk.Label(input_row, text="[deg]").pack(side="left", padx=(3, 0))

        btn_row = ttk.Frame(parent)
        btn_row.pack(fill="x", pady=3)
        self.add_btn = ttk.Button(btn_row, text="Add Mask Sector", command=self._add_az_mask, state="disabled")
        self.add_btn.pack(side="left", padx=(15, 5))
        self.remove_btn = ttk.Button(btn_row, text="Remove Selected", command=self._remove_az_mask, state="disabled", bootstyle="warning")
        self.remove_btn.pack(side="left", padx=5)

        list_frame = ttk.Frame(parent)
        list_frame.pack(fill="x", padx=15, pady=3)
        self.az_listbox = tk.Listbox(list_frame, height=4, exportselection=False, state="disabled")
        lb_scroll = ttk.Scrollbar(list_frame, orient="vertical", command=self.az_listbox.yview)
        self.az_listbox.configure(yscrollcommand=lb_scroll.set)
        lb_scroll.pack(side="right", fill="y")
        self.az_listbox.pack(side="left", fill="both", expand=True)

        file_row = ttk.Frame(parent)
        file_row.pack(fill="x", pady=(6, 3))
        ttk.Button(file_row, text="Load Mask File", command=self._load_mask_file, bootstyle="outline-info").pack(side="left", padx=(15, 5))
        ttk.Button(file_row, text="Save Mask File", command=self._save_mask_file, bootstyle="outline-info").pack(side="left", padx=5)

    def _create_profile_tab(self, parent):
        """Horizon profile UI (Phase 2 + 3)."""
        self.horizon_profile_list = []  # List of (azimuth, elevation) tuples

        info = ttk.Label(parent, text="Define the horizon boundary as (azimuth, elevation) pairs.",
                         font=("Helvetica", 9), bootstyle="light")
        info.pack(anchor="w", padx=5, pady=(0, 5))

        # Manual input row
        input_row = ttk.Frame(parent)
        input_row.pack(fill="x", pady=3)
        ttk.Label(input_row, text="Az:").pack(side="left", padx=(5, 2))
        self.prof_az_var = tk.StringVar(value="0")
        ttk.Entry(input_row, textvariable=self.prof_az_var, width=6).pack(side="left")
        ttk.Label(input_row, text="[deg]  El:").pack(side="left", padx=(10, 2))
        self.prof_el_var = tk.StringVar(value="10")
        ttk.Entry(input_row, textvariable=self.prof_el_var, width=6).pack(side="left")
        ttk.Label(input_row, text="[deg]").pack(side="left", padx=(3, 0))

        btn_row = ttk.Frame(parent)
        btn_row.pack(fill="x", pady=3)
        ttk.Button(btn_row, text="Add Point", command=self._add_profile_point).pack(side="left", padx=(5, 5))
        ttk.Button(btn_row, text="Remove Selected", command=self._remove_profile_point, bootstyle="warning").pack(side="left", padx=5)
        ttk.Button(btn_row, text="Clear All", command=self._clear_profile, bootstyle="danger-outline").pack(side="left", padx=5)

        # Listbox for profile points
        list_frame = ttk.Frame(parent)
        list_frame.pack(fill="x", padx=5, pady=3)
        self.profile_listbox = tk.Listbox(list_frame, height=5, exportselection=False)
        pl_scroll = ttk.Scrollbar(list_frame, orient="vertical", command=self.profile_listbox.yview)
        self.profile_listbox.configure(yscrollcommand=pl_scroll.set)
        pl_scroll.pack(side="right", fill="y")
        self.profile_listbox.pack(side="left", fill="both", expand=True)

        # Profile count label
        self.profile_count_var = tk.StringVar(value="0 points defined")
        ttk.Label(parent, textvariable=self.profile_count_var, font=("Helvetica", 9),
                  bootstyle="light").pack(anchor="w", padx=5, pady=2)

        # Action buttons
        action_row = ttk.Frame(parent)
        action_row.pack(fill="x", pady=(6, 3))
        auto_btn = ttk.Button(action_row, text="Auto-Mask from Image...",
                              command=self._auto_mask_from_image, bootstyle="success")
        auto_btn.pack(side="left", padx=(5, 5))
        CreateToolTip(auto_btn,
                      "Generate the horizon profile automatically from a hemispherical (fisheye) "
                      "or equirectangular 360 sky image, or from a pre-segmented mask produced "
                      "by a segmentation model. The result is a starting point: review and "
                      "correct it with 'Fine-Tune Points...' before use.")
        tune_btn = ttk.Button(action_row, text="Fine-Tune Points...",
                              command=self._fine_tune_profile, bootstyle="success")
        tune_btn.pack(side="left", padx=5)
        CreateToolTip(tune_btn,
                      "Correct the profile by hand: drag points onto the true skyline, "
                      "add points where the boundary is under-sampled, right-click to delete. "
                      "Opens on the source image when the profile came from one.")
        ttk.Button(action_row, text="Digitize from Image...", command=self._digitize_from_image,
                   bootstyle="success-outline").pack(side="left", padx=5)
        ttk.Button(action_row, text="Preview Profile", command=self._preview_profile,
                   bootstyle="info-outline").pack(side="left", padx=5)

        file_row2 = ttk.Frame(parent)
        file_row2.pack(fill="x", pady=(3, 3))
        ttk.Button(file_row2, text="Load Profile File", command=self._load_profile_file, bootstyle="outline-info").pack(side="left", padx=(5, 5))
        ttk.Button(file_row2, text="Save Profile File", command=self._save_profile_file, bootstyle="outline-info").pack(side="left", padx=5)

    # ---- Sector mask interaction methods ----

    def _update_az_state(self):
        state = "normal" if self.az_mask_active_var.get() else "disabled"
        for w in (self.az_from_entry, self.az_to_entry, self.az_el_entry, self.add_btn, self.remove_btn, self.az_listbox):
            w.configure(state=state)

    def _add_az_mask(self):
        try:
            az_from = float(self.az_from_var.get())
            az_to = float(self.az_to_var.get())
            el_limit = float(self.az_el_var.get())
            if not (0 <= az_from <= 360 and 0 <= az_to <= 360 and 0 <= el_limit <= 90):
                messagebox.showerror("Invalid", "Azimuth: 0-360, Elevation: 0-90")
                return
            self.azimuth_masks_list.append((az_from, az_to, el_limit))
            self.az_listbox.insert(tk.END, f"Az {az_from:.0f} - {az_to:.0f} deg,  El < {el_limit:.0f} deg")
        except ValueError:
            messagebox.showerror("Invalid", "Please enter valid numbers.")

    def _remove_az_mask(self):
        sel = self.az_listbox.curselection()
        if sel:
            idx = sel[0]
            self.az_listbox.delete(idx)
            self.azimuth_masks_list.pop(idx)

    def _load_mask_file(self):
        path = filedialog.askopenfilename(title="Load Mask File",
                                          filetypes=[("Text files", "*.txt"), ("All", "*.*")])
        if path:
            from elevation_mask import ElevationMask
            try:
                mask = ElevationMask.from_file(path)
                self.cutoff_var.set(str(mask.uniform_cutoff))
                self.azimuth_masks_list = list(mask.sectors)
                self.az_listbox.delete(0, tk.END)
                for az_from, az_to, el_limit in mask.sectors:
                    self.az_listbox.insert(tk.END, f"Az {az_from:.0f} - {az_to:.0f} deg,  El < {el_limit:.0f} deg")
                if mask.sectors:
                    self.az_mask_active_var.set(True)
                    self._update_az_state()
                # Also load horizon profile if present
                if mask.horizon_profile:
                    self.horizon_profile_list = list(mask.horizon_profile)
                    self._mask_source_image = None
                    self._mask_source_name = None
                    self._mask_source_is_label = False
                    self._mask_camera_elevation = 90.0
                    self._mask_tilt_azimuth = 0.0
                    # No automatic profile behind this one, so a later
                    # correction has nothing to be a correction OF.
                    self._mask_source_path = None
                    self._mask_auto_profile = None
                    self._refresh_profile_listbox()
                    self.mask_notebook.select(1)  # Switch to Profile tab
                messagebox.showinfo("Loaded", f"Mask loaded from: {os.path.basename(path)}")
            except Exception as e:
                messagebox.showerror("Error", f"Could not load mask file:\n{e}")

    def _save_mask_file(self):
        path = filedialog.asksaveasfilename(title="Save Mask File", defaultextension=".txt",
                                            filetypes=[("Text files", "*.txt")])
        if path:
            try:
                with open(path, 'w') as f:
                    f.write("# RINEX-Masker obstruction mask\n")
                    f.write(f"# Uniform cutoff: {self.cutoff_var.get()} deg\n")
                    f.write("# Format: azimuth_start, azimuth_end, elevation_cutoff\n")
                    for az_from, az_to, el_limit in self.azimuth_masks_list:
                        f.write(f"{az_from}, {az_to}, {el_limit}\n")
                messagebox.showinfo("Saved", f"Mask saved to: {os.path.basename(path)}")
            except Exception as e:
                messagebox.showerror("Error", f"Could not save mask file:\n{e}")

    # ---- Horizon profile interaction methods ----

    def _add_profile_point(self):
        try:
            az = float(self.prof_az_var.get())
            el = float(self.prof_el_var.get())
            if not (0 <= az <= 360 and 0 <= el <= 90):
                messagebox.showerror("Invalid", "Azimuth: 0-360, Elevation: 0-90")
                return
            self.horizon_profile_list.append((az, el))
            self.horizon_profile_list.sort(key=lambda p: p[0])
            self._refresh_profile_listbox()
        except ValueError:
            messagebox.showerror("Invalid", "Please enter valid numbers.")

    def _remove_profile_point(self):
        sel = self.profile_listbox.curselection()
        if sel:
            idx = sel[0]
            self.profile_listbox.delete(idx)
            self.horizon_profile_list.pop(idx)
            self._update_profile_count()

    def _clear_profile(self):
        self.horizon_profile_list.clear()
        self.profile_listbox.delete(0, tk.END)
        self._update_profile_count()

    def _refresh_profile_listbox(self):
        self.profile_listbox.delete(0, tk.END)
        for az, el in self.horizon_profile_list:
            self.profile_listbox.insert(tk.END, f"Az {az:.1f} deg  ->  El {el:.1f} deg")
        self._update_profile_count()

    def _update_profile_count(self):
        n = len(self.horizon_profile_list)
        self.profile_count_var.set(f"{n} point{'s' if n != 1 else ''} defined")

    def _digitize_from_image(self):
        """Open a polar skyplot image and let the user click to trace the horizon."""
        # Offer choice: default image or user-selected
        choice = messagebox.askyesnocancel(
            "Digitize from Image",
            "Use the bundled default panoramic image?\n\n"
            "Yes = Use default image\n"
            "No = Select your own image\n"
            "Cancel = Abort")
        if choice is None:
            return  # Cancel

        if choice:  # Yes = default image
            default_img = resource_path(os.path.join('assets', 'default_skyplot.png'))
            if os.path.exists(default_img):
                img_path = default_img
            else:
                # No default image bundled — fall back to empty polar plot
                img_path = None
        else:  # No = browse
            img_path = filedialog.askopenfilename(
                title="Select Polar Skyplot Image",
                filetypes=[("Images", "*.png *.jpg *.jpeg *.bmp"), ("All", "*.*")])
            if not img_path:
                return

        from digitizer import HorizonDigitizer
        digitizer = HorizonDigitizer()
        points = digitizer.run(img_path)

        if points and len(points) >= 2:
            self.horizon_profile_list = points
            self._refresh_profile_listbox()
            messagebox.showinfo("Digitized", f"Profile created with {len(points)} points.")
        elif points is not None:
            messagebox.showinfo("Cancelled", "Not enough points were placed.")

    def _auto_mask_from_image(self):
        """Generate a horizon profile automatically from a sky image.

        Accepts a hemispherical (fisheye) photo, an equirectangular 360 panorama,
        or a pre-segmented mask from a segmentation model — either a binary
        sky/no-sky image or a colour label image. The generated profile replaces
        the current one and can then be corrected point by point.
        """
        img_path = filedialog.askopenfilename(
            title="Select Sky Image (hemispherical, 360 panorama, or segmentation mask)",
            filetypes=[("Images", "*.png *.jpg *.jpeg *.bmp *.tif *.tiff"), ("All", "*.*")])
        if not img_path:
            return

        opts = self._ask_auto_mask_options(img_path)
        if opts is None:
            return

        try:
            import image_mask
        except ImportError as exc:
            messagebox.showerror("Missing Module", f"Could not import image_mask:\n{exc}")
            return

        try:
            if opts['label_mode']:
                profile, fisheye, sky = image_mask.profile_from_label_image(
                    img_path,
                    sky_rgb=opts['sky_rgb'],
                    invert=opts['invert'],
                    az_step_deg=opts['az_step'],
                    north_offset_deg=opts['north_offset'],
                    camera_elevation_deg=opts['camera_elevation'],
                    tilt_azimuth_deg=opts['tilt_azimuth'])
                kind = image_mask.classify_label_image(fisheye)
                source = {'binary': "binary segmentation mask",
                          'greyscale': "greyscale segmentation mask",
                          'colour': "colour label image"}[kind]
            else:
                profile, fisheye, sky = image_mask.profile_from_image(
                    img_path,
                    az_step_deg=opts['az_step'],
                    north_offset_deg=opts['north_offset'],
                    blue_threshold=opts['sensitivity'],
                    camera_elevation_deg=opts['camera_elevation'],
                    tilt_azimuth_deg=opts['tilt_azimuth'])
                source = "photo (built-in sky detector)"
        except (OSError, ValueError) as exc:
            messagebox.showerror("Auto-Mask Failed", f"Could not process the image:\n{exc}")
            return

        if len(profile) < 2:
            messagebox.showwarning("Auto-Mask", "No horizon could be extracted from this image.")
            return

        self.horizon_profile_list = profile
        self._refresh_profile_listbox()

        # Remember the geometry so the profile can be fine-tuned on its source.
        self._mask_source_image = fisheye
        self._mask_source_name = os.path.basename(img_path)
        self._mask_north_offset = opts['north_offset']
        self._mask_source_is_label = opts['label_mode']
        self._mask_camera_elevation = opts['camera_elevation']
        self._mask_tilt_azimuth = opts['tilt_azimuth']

        # Kept for the training feedback: the file itself, so a correction can
        # be stored against the exact image the segmentation saw, and the
        # automatic profile, because the difference to the corrected one is the
        # label. See mask_feedback.py.
        self._mask_source_path = img_path
        self._mask_auto_profile = list(profile)
        self._mask_options = dict(opts)
        self._mask_source_kind = kind if opts['label_mode'] else 'photo'
        self._mask_fisheye_shape = tuple(fisheye.shape[:2])

        self._show_auto_mask_preview(fisheye, sky, profile, img_path,
                                     north_offset_deg=opts['north_offset'],
                                     camera_elevation_deg=opts['camera_elevation'],
                                     tilt_azimuth_deg=opts['tilt_azimuth'])

        blocked = [el for _, el in profile if el > 0.0]
        tune = messagebox.askyesno(
            "Auto-Mask Created",
            f"Horizon profile generated with {len(profile)} points.\n"
            f"Source: {source}\n\n"
            f"Obstructed azimuth bins: {len(blocked)} of {len(profile)}\n"
            f"Max horizon elevation: {max(el for _, el in profile):.1f} deg\n\n"
            "This is an automatic first estimate. Segmentation can misjudge which "
            "object blocks a direction — a tree in front of a building is the "
            "classic case — so the points should be checked before masking.\n\n"
            "Fine-tune the points on the image now?")
        if tune:
            self._fine_tune_profile()

    def _ask_auto_mask_options(self, img_path):
        """Ask for the auto-mask parameters. Returns a dict, or None if cancelled."""
        dlg = tk.Toplevel(self)
        dlg.title("Auto-Mask Options")
        dlg.transient(self)
        dlg.resizable(False, False)
        dlg.grab_set()

        frm = ttk.Frame(dlg, padding=12)
        frm.pack(fill="both", expand=True)

        ttk.Label(frm, text=os.path.basename(img_path), font=("Helvetica", 9, "bold")).grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))

        # Name the accepted picture. "Photo" alone did not say that a
        # hemispherical (fisheye) shot or a 360 deg panorama is what belongs
        # here - a 360 deg equirectangular image is converted automatically by
        # image_mask.equirect_to_fisheye.
        PHOTO_MODE = "Photo - detect the sky automatically"
        SEG_MODE = "Pre-segmented mask (binary or colour label)"

        north_var = tk.StringVar(value="0")
        zenith_var = tk.StringVar(value="90")
        tilt_az_var = tk.StringVar(value="0")
        step_var = tk.StringVar(value="5")
        sens_var = tk.StringVar(value="0.02")
        type_var = tk.StringVar(value=PHOTO_MODE)
        sky_rgb_var = tk.StringVar(value="auto")
        invert_var = tk.BooleanVar(value=False)

        type_lbl = ttk.Label(frm, text="Image type:")
        type_lbl.grid(row=1, column=0, sticky="w", pady=3)
        type_box = ttk.Combobox(frm, textvariable=type_var, width=34, state="readonly",
                                values=[PHOTO_MODE, SEG_MODE])
        type_box.grid(row=1, column=1, sticky="w", padx=(8, 0))
        CreateToolTip(type_lbl,
                      "Photo: RINEX-Masker finds the sky itself (daytime, open sky only).\n"
                      "Pre-segmented: the sky is read straight from a mask produced\n"
                      "elsewhere, e.g. by the IPI segmentation pipeline. This is the\n"
                      "accurate path - no detection happens here.")
        # State the accepted picture next to the box rather than only
        # in the readme, which is where it lived until now.
        ttk.Label(frm, text="Hemispherical (fisheye) photo, or a 360° panorama "
                            "(converted automatically).",
                  font=("Helvetica", 8), bootstyle="secondary",
                  wraplength=330, justify="left").grid(
            row=2, column=1, sticky="w", padx=(8, 0), pady=(0, 4))

        rows = [
            ("North offset [deg]:", north_var,
             "Rotates the mask so image azimuths align with true north.\n"
             "The image convention is north-at-bottom; this absorbs that\n"
             "and the camera heading. A wrong value rotates the whole mask."),
            ("Camera zenith angle [deg]:", zenith_var,
             "Elevation the camera actually pointed at.\n"
             "90 = straight up, the standard setup for a horizontal antenna.\n"
             "Enter a different value only for a known tilt, e.g. a kinematic\n"
             "run on a slope. The tilt is not read from IMU data."),
            ("Tilt towards azimuth [deg]:", tilt_az_var,
             "Direction the camera leans, in the same azimuth frame as the\n"
             "mask. Only has an effect when the zenith angle is not 90."),
            ("Azimuth step [deg]:", step_var, "Width of each azimuth bin."),
            ("Sky sensitivity:", sens_var,
             "Photo mode only. Normalised blue-red threshold for sky detection.\n"
             "Raise if bright facades are read as sky; lower for overcast."),
            ("Sky class colour:", sky_rgb_var,
             "Pre-segmented mode only. 'auto' handles both shapes: a binary\n"
             "mask is split on brightness, a colour label image is matched\n"
             "against the Cityscapes sky colour 70,130,180. Enter R,G,B to\n"
             "name a different sky class."),
        ]
        entries = {}
        for i, (text, var, tip) in enumerate(rows, start=3):   # row 2 = the format hint
            lbl = ttk.Label(frm, text=text)
            lbl.grid(row=i, column=0, sticky="w", pady=3)
            ent = ttk.Entry(frm, textvariable=var, width=12)
            ent.grid(row=i, column=1, sticky="w", padx=(8, 0))
            CreateToolTip(lbl, tip)
            entries[text] = ent

        chk = ttk.Checkbutton(frm, text="Sky is the dark class (invert the mask)",
                              variable=invert_var)
        chk.grid(row=9, column=0, columnspan=2, sticky="w", pady=(8, 0))
        CreateToolTip(chk,
                      "Pre-segmented mode only. Tick for binary masks that paint\n"
                      "the sky black and the obstacles white.")

        def on_type_change(*_):
            segmented = type_var.get() == SEG_MODE
            entries["Sky sensitivity:"].configure(state="disabled" if segmented else "normal")
            entries["Sky class colour:"].configure(state="normal" if segmented else "disabled")
            chk.configure(state="normal" if segmented else "disabled")

        type_var.trace_add("write", on_type_change)
        on_type_change()

        result = {}

        def on_ok():
            try:
                result['north_offset'] = float(north_var.get())
                result['az_step'] = float(step_var.get())
                result['sensitivity'] = float(sens_var.get())
                result['camera_elevation'] = float(zenith_var.get())
                result['tilt_azimuth'] = float(tilt_az_var.get())
            except ValueError:
                messagebox.showerror("Invalid", "Please enter numeric values.", parent=dlg)
                return
            if not 0 < result['az_step'] <= 180:
                messagebox.showerror("Invalid", "Azimuth step must be in (0, 180].", parent=dlg)
                return
            if not 0 <= result['camera_elevation'] <= 90:
                messagebox.showerror(
                    "Invalid",
                    "Camera zenith angle must be 0-90 deg (90 = straight up).",
                    parent=dlg)
                return

            result['label_mode'] = type_var.get() == SEG_MODE
            result['invert'] = invert_var.get()
            result['sky_rgb'] = None
            raw = sky_rgb_var.get().strip()
            if result['label_mode'] and raw and raw.lower() != "auto":
                try:
                    channels = [int(v) for v in raw.replace(';', ',').split(',')]
                except ValueError:
                    channels = []
                if len(channels) != 3 or not all(0 <= v <= 255 for v in channels):
                    messagebox.showerror(
                        "Invalid",
                        "Sky class colour must be 'auto' or three values 0-255, e.g. 70,130,180.",
                        parent=dlg)
                    return
                result['sky_rgb'] = tuple(channels)
            dlg.destroy()

        btn_row = ttk.Frame(frm)
        btn_row.grid(row=10, column=0, columnspan=2, pady=(12, 0), sticky="e")
        ttk.Button(btn_row, text="Generate", command=on_ok, bootstyle="success").pack(side="left", padx=4)
        ttk.Button(btn_row, text="Cancel", command=dlg.destroy, bootstyle="secondary").pack(side="left")

        dlg.wait_window()
        return result or None

    def _fine_tune_profile(self):
        """Correct the horizon profile by hand, on the image it came from.

        Automatic segmentation cannot always tell which object blocks a given
        direction, so every generated point has to be movable before the mask
        is applied.
        """
        try:
            from profile_editor import HorizonProfileEditor
        except ImportError as exc:
            messagebox.showerror("Missing Module", f"Could not import profile_editor:\n{exc}")
            return

        background = getattr(self, '_mask_source_image', None)
        name = getattr(self, '_mask_source_name', None)
        # If the user swaps the backdrop for the original photograph, that is
        # the image they actually judged against, so it is worth keeping too.
        corrected_on_photo = None

        if background is None and not self.horizon_profile_list:
            messagebox.showinfo(
                "Nothing to Fine-Tune",
                "Generate a profile with 'Auto-Mask from Image...' first, or add "
                "points manually — then fine-tune them here.")
            return

        # A profile extracted from a segmentation mask is best corrected against
        # the photograph it was segmented from: the errors worth fixing are the
        # ones only the photo reveals, such as a tree taken for the building
        # behind it. Offer to swap the backdrop for the original image.
        if background is not None and getattr(self, '_mask_source_is_label', False):
            use_photo = messagebox.askyesno(
                "Fine-Tune on the Original Photo?",
                "This profile came from a segmentation mask.\n\n"
                "Correcting it is easier on the original photograph, where you "
                "can see what each obstacle actually is.\n\n"
                "Yes = choose the original image\n"
                "No = stay on the segmentation mask")
            if use_photo:
                photo_path = filedialog.askopenfilename(
                    title="Select the Original Hemispherical Image",
                    filetypes=[("Images", "*.png *.jpg *.jpeg *.bmp *.tif *.tiff"),
                               ("All", "*.*")])
                if photo_path:
                    try:
                        import image_mask
                        photo = image_mask.load_image(photo_path)
                    except (OSError, ImportError) as exc:
                        messagebox.showerror("Could Not Load Image", str(exc))
                        photo = None
                    if photo is not None:
                        corrected_on_photo = photo_path
                        if photo.shape[:2] != background.shape[:2]:
                            messagebox.showwarning(
                                "Different Image Size",
                                f"The photo is {photo.shape[1]}x{photo.shape[0]} but the "
                                f"mask is {background.shape[1]}x{background.shape[0]}.\n\n"
                                "The points are placed by angle, not by pixel, so they "
                                "still land correctly as long as both images use the same "
                                "fisheye projection.")
                        background = photo
                        name = os.path.basename(photo_path)

        elif background is None:
            pick = messagebox.askyesno(
                "Background Image",
                "No source image is loaded for this profile.\n\n"
                "Yes = open it on a hemispherical image\n"
                "No = edit on the elevation grid only")
            if pick:
                photo_path = filedialog.askopenfilename(
                    title="Select a Hemispherical Image",
                    filetypes=[("Images", "*.png *.jpg *.jpeg *.bmp *.tif *.tiff"),
                               ("All", "*.*")])
                if photo_path:
                    try:
                        import image_mask
                        background = image_mask.load_image(photo_path)
                        name = os.path.basename(photo_path)
                    except (OSError, ImportError) as exc:
                        messagebox.showerror("Could Not Load Image", str(exc))

        before = list(self.horizon_profile_list)
        editor = HorizonProfileEditor(
            before,
            background=background,
            north_offset_deg=getattr(self, '_mask_north_offset', 0.0),
            camera_elevation_deg=getattr(self, '_mask_camera_elevation', 90.0),
            tilt_azimuth_deg=getattr(self, '_mask_tilt_azimuth', 0.0),
            title=name)
        corrected = editor.run()

        if corrected is None:
            return

        changed = sum(1 for p in corrected if p not in before)
        self.horizon_profile_list = corrected
        self._refresh_profile_listbox()

        stored = self._store_mask_correction(before, corrected,
                                             photo_path=corrected_on_photo)
        note = ""
        if stored:
            # Name the folder, not the absolute path: a message box wraps a long
            # path mid-word, and the user only needs to know where to look.
            short = os.path.join(os.path.basename(os.path.dirname(stored)),
                                 os.path.basename(stored))
            note = ("\n\nA copy of the image and both profiles was kept in\n"
                    f"    {short}\n"
                    "next to RINEX-Masker, so the automatic masking can learn "
                    "from your correction.\nIt stays on this computer; nothing "
                    "is uploaded.")

        messagebox.showinfo(
            "Profile Updated",
            f"Horizon profile now has {len(corrected)} points "
            f"(was {len(before)}; {changed} new or moved).{note}")

    def _store_mask_correction(self, before, corrected, photo_path=None):
        """
        Keep a corrected mask so the segmentation can be retrained on it.

        Only corrections to an
        automatically generated profile are worth anything, because the label
        is the difference between what the model produced and what the person
        moved it to, so a hand-drawn profile with no source image is skipped.
        Never let this interrupt the user: the mask itself is already applied.
        """
        source_path = getattr(self, '_mask_source_path', None)
        automatic = getattr(self, '_mask_auto_profile', None)
        if not source_path or not automatic:
            return None
        try:
            import mask_feedback
        except ImportError:
            return None

        opts = getattr(self, '_mask_options', {}) or {}
        try:
            version = {"name": "RINEX-Masker",
                       "version": tool_version.VERSION,
                       "release_date": tool_version.RELEASE_DATE}
        except Exception:
            version = {"name": "RINEX-Masker"}

        return mask_feedback.save_sample(
            source_path=source_path,
            corrected=corrected,
            automatic=automatic,
            edited_from=before,
            photo_path=photo_path,
            geometry={
                "north_offset_deg": getattr(self, '_mask_north_offset', 0.0),
                "camera_elevation_deg": getattr(self, '_mask_camera_elevation', 90.0),
                "tilt_azimuth_deg": getattr(self, '_mask_tilt_azimuth', 0.0),
                "az_step_deg": opts.get('az_step'),
            },
            extraction={
                "label_mode": opts.get('label_mode'),
                "sky_rgb": list(opts['sky_rgb']) if opts.get('sky_rgb') else None,
                "invert": opts.get('invert'),
                "sensitivity": opts.get('sensitivity'),
            },
            source_info={
                "kind": getattr(self, '_mask_source_kind', None),
                "fisheye_height": (getattr(self, '_mask_fisheye_shape', (None, None)) or (None, None))[0],
                "fisheye_width": (getattr(self, '_mask_fisheye_shape', (None, None)) or (None, None))[1],
            },
            program=version)

    def _show_auto_mask_preview(self, fisheye, sky, profile, img_path,
                                north_offset_deg=0.0, camera_elevation_deg=90.0,
                                tilt_azimuth_deg=0.0):
        """
        Show what the automatic mask was derived from, for visual checking.

        The panels are drawn NORTH-UP. The fisheye convention this
        tool shares with the IPI pipeline is north-at-BOTTOM
        (u = cx + r*sin(az), v = cy + r*cos(az), v growing downwards), so the
        raw picture puts South at the top, which is misleading, and it
        makes the preview impossible to compare with the skyplot. Mirroring the
        display vertically maps north to the top while leaving east on the right,
        i.e. exactly the skyplot convention (N up, E right, azimuth clockwise).
        Only the *view* is mirrored; the image file and the extracted profile are
        untouched. The cardinal labels are drawn from the same formula, so they
        stay correct for any north offset.

        The caller blocks until this window closes, which was not
        obvious, so there is now a Continue button and it says so.
        """
        import numpy as np
        import matplotlib.pyplot as plt
        from matplotlib.colors import ListedColormap
        from matplotlib.widgets import Button

        radius = min(fisheye.shape[:2]) / 2.0
        import image_mask
        f_px = image_mask.focal_length_px(radius)
        height = fisheye.shape[0]

        def north_up(img):
            """Mirror vertically so north is at the top (view only)."""
            return np.flipud(img)

        def to_view_y(y):
            """Same mirror, applied to plotted y coordinates."""
            return (height - 1) - np.asarray(y)

        fig, axes = plt.subplots(1, 3, figsize=(13, 4.8))
        fig.canvas.manager.set_window_title("RINEX-Masker: Auto-Mask Preview")

        axes[0].imshow(north_up(fisheye))
        axes[0].set_title("Input image", fontsize=10)

        axes[1].imshow(north_up(sky), cmap=ListedColormap(['#4a4a4a', '#8ecae6']))
        axes[1].set_title("Sky (light) vs obstacle (dark)", fontsize=10)

        axes[2].imshow(north_up(fisheye))
        # Undo the camera tilt and the north offset to get back to the image's
        # own frame, so the traced skyline lands on the pixels it came from.
        closed = profile + [profile[0]]
        az_img, el_img = image_mask.apply_camera_tilt(
            [p[0] for p in closed], [p[1] for p in closed],
            camera_elevation_deg=camera_elevation_deg,
            tilt_azimuth_deg=tilt_azimuth_deg, inverse=True)
        az = np.deg2rad(az_img - north_offset_deg)
        r = f_px * np.deg2rad(90.0 - el_img)
        axes[2].plot(radius + r * np.sin(az),
                     to_view_y(radius + r * np.cos(az)), 'r-', lw=2)
        axes[2].set_title("Extracted skyline", fontsize=10)

        # Cardinal directions, placed with the projection the extraction uses so
        # they remain right when a north offset rotates the frame.
        cx = fisheye.shape[1] / 2.0
        cy = height / 2.0
        for name, bearing in (("N", 0.0), ("E", 90.0), ("S", 180.0), ("W", 270.0)):
            a = np.deg2rad(bearing - north_offset_deg)
            rr = radius * 0.94
            for ax in axes:
                ax.text(cx + rr * np.sin(a), to_view_y(cy + rr * np.cos(a)),
                        name, color="#ffcc00", fontsize=11, fontweight="bold",
                        ha="center", va="center",
                        bbox=dict(boxstyle="circle,pad=0.15", fc="black", alpha=0.55, lw=0))

        for ax in axes:
            ax.axis('off')

        fig.suptitle(f"Auto-mask preview — {os.path.basename(img_path)}", fontsize=11)
        fig.text(0.5, 0.045,
                 "Shown north-up to match the skyplot (the photo itself is "
                 "north-at-bottom and is not modified).",
                 ha="center", fontsize=8, color="#555555")
        fig.tight_layout(rect=(0, 0.10, 1, 1))

        # An explicit way out. Closing the window still works.
        btn_ax = fig.add_axes((0.86, 0.02, 0.12, 0.065))
        cont = Button(btn_ax, "Continue →")
        cont.on_clicked(lambda _evt: plt.close(fig))
        fig._rinex_masker_continue = cont      # keep a reference alive

        plt.show()

    def _preview_profile(self):
        """Show a preview of the current horizon profile on a polar plot."""
        if not self.horizon_profile_list or len(self.horizon_profile_list) < 2:
            messagebox.showinfo("No Profile", "Add at least 2 profile points first.")
            return

        from elevation_mask import ElevationMask
        import matplotlib
        matplotlib.use('TkAgg')
        import matplotlib.pyplot as plt
        import numpy as np

        mask = ElevationMask(uniform_cutoff=float(self.cutoff_var.get()))
        mask.set_horizon_profile(self.horizon_profile_list)

        fig = plt.figure(figsize=(8, 8))
        ax = fig.add_subplot(111, projection='polar')
        ax.set_theta_zero_location('N')
        ax.set_theta_direction(-1)
        ax.set_rlim(0, 90)
        ax.set_rgrids([0, 15, 30, 45, 60, 75, 90],
                       labels=['90', '75', '60', '45', '30', '15', '0'])

        # Draw profile
        az_steps = np.linspace(0, 360, 361)
        profile_el = [mask.get_profile_elevation(az) for az in az_steps]
        theta_vals = np.deg2rad(az_steps)
        r_profile = [90.0 - el for el in profile_el]

        ax.fill_between(theta_vals, r_profile, 90.0, color='red', alpha=0.12)
        ax.plot(theta_vals, r_profile, color='#cc0000', linewidth=1.5, alpha=0.8)

        # Mark the profile points
        for az, el in self.horizon_profile_list:
            ax.plot(np.deg2rad(az), 90.0 - el, 'ro', markersize=5)

        ax.set_title(f"Horizon Profile Preview ({len(self.horizon_profile_list)} points)",
                     pad=15, fontsize=12)
        plt.tight_layout()
        plt.show()

    def _load_profile_file(self):
        path = filedialog.askopenfilename(title="Load Profile File",
                                          filetypes=[("Text files", "*.txt"), ("All", "*.*")])
        if path:
            from elevation_mask import ElevationMask
            try:
                mask = ElevationMask.from_file(path)
                loaded_something = False
                if mask.horizon_profile:
                    self.horizon_profile_list = list(mask.horizon_profile)
                    # A profile from file has no source image; drop any earlier
                    # one so fine-tuning cannot draw it over an unrelated photo.
                    self._mask_source_image = None
                    self._mask_source_name = None
                    self._mask_source_is_label = False
                    self._mask_camera_elevation = 90.0
                    self._mask_tilt_azimuth = 0.0
                    # No automatic profile behind this one, so a later
                    # correction has nothing to be a correction OF.
                    self._mask_source_path = None
                    self._mask_auto_profile = None
                    self._refresh_profile_listbox()
                    self.cutoff_var.set(str(mask.uniform_cutoff))
                    messagebox.showinfo("Loaded", f"Profile loaded: {len(mask.horizon_profile)} points")
                    loaded_something = True
                if mask.sectors and not loaded_something:
                    # File contains sector masks but no profile points
                    # Offer to load as sector masks instead
                    load_sectors = messagebox.askyesno(
                        "No Profile Found",
                        f"This file contains {len(mask.sectors)} sector mask(s) but no profile points.\n\n"
                        "Load as sector masks instead?")
                    if load_sectors:
                        self.azimuth_masks_list = list(mask.sectors)
                        self.az_listbox.delete(0, tk.END)
                        for az_from, az_to, el_limit in mask.sectors:
                            self.az_listbox.insert(tk.END, f"Az {az_from:.0f} - {az_to:.0f} deg,  El < {el_limit:.0f} deg")
                        self.az_mask_active_var.set(True)
                        self._update_az_state()
                        self.cutoff_var.set(str(mask.uniform_cutoff))
                        self.mask_notebook.select(0)  # Switch to Sector tab
                        messagebox.showinfo("Loaded", f"Loaded {len(mask.sectors)} sector mask(s)")
                elif not loaded_something:
                    messagebox.showinfo("No Data",
                        "File does not contain profile points (2 values: azimuth, elevation)\n"
                        "or sector masks (3 values: az_from, az_to, elevation).")
            except Exception as e:
                messagebox.showerror("Error", f"Could not load file:\n{e}")

    def _save_profile_file(self):
        if not self.horizon_profile_list:
            messagebox.showinfo("No Profile", "No profile points to save.")
            return
        path = filedialog.asksaveasfilename(title="Save Profile File", defaultextension=".txt",
                                            filetypes=[("Text files", "*.txt")])
        if path:
            from elevation_mask import ElevationMask
            try:
                mask = ElevationMask(uniform_cutoff=float(self.cutoff_var.get()))
                mask.set_horizon_profile(self.horizon_profile_list)
                mask.save_profile(path)
                messagebox.showinfo("Saved", f"Profile saved: {len(self.horizon_profile_list)} points")
            except Exception as e:
                messagebox.showerror("Error", f"Could not save file:\n{e}")

    # --- Output ---
    def _create_output_widgets(self, parent):
        frame = ttk.LabelFrame(parent, text="Output", padding=10)
        frame.pack(fill="x", pady=(0, 8))

        ttk.Label(frame, text="Output File:").grid(row=0, column=0, sticky="w", padx=5, pady=3)
        self.output_path = tk.StringVar()
        ttk.Entry(frame, textvariable=self.output_path, width=55).grid(row=0, column=1, padx=5, pady=3, sticky="ew")
        ttk.Button(frame, text="Browse…", command=self._browse_output, bootstyle="outline-primary").grid(row=0, column=2, padx=5, pady=3)

        self.skyplot_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(frame, text="Generate before/after skyplot", variable=self.skyplot_var).grid(
            row=1, column=0, columnspan=3, sticky="w", padx=5, pady=3)

        frame.columnconfigure(1, weight=1)

    # --- Progress / Log ---
    def _create_progress_widgets(self, parent):
        frame = ttk.LabelFrame(parent, text="Progress", padding=10)
        frame.pack(fill="x", pady=(0, 8))

        self.progress_var = tk.DoubleVar(value=0.0)
        self.progress_bar = ttk.Progressbar(frame, variable=self.progress_var, maximum=1.0, bootstyle="success-striped")
        self.progress_bar.pack(fill="x", pady=(0, 5))

        self.status_var = tk.StringVar(value="Ready.")
        ttk.Label(frame, textvariable=self.status_var, font=("Helvetica", 9)).pack(anchor="w", pady=(0, 5))

        log_frame = ttk.Frame(frame)
        log_frame.pack(fill="both", expand=True)
        self.log_text = tk.Text(log_frame, height=10, wrap="word", state="disabled",
                                bg="#1a1a2e", fg="#e0e0e0", font=("Consolas", 9))
        log_scroll = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_scroll.set)
        log_scroll.pack(side="right", fill="y")
        self.log_text.pack(side="left", fill="both", expand=True)

    # ----------------------------------------------------------------
    # File browsing
    # ----------------------------------------------------------------
    def _browse_file(self, var, kind):
        ftypes = [("All files", "*.*")]
        if kind == "RINEX":
            # Include the classic RINEX-2 short-name observation extensions
            # *.yyo / *.yyO (e.g. *.26o) alongside the modern *.rnx/*.obs.
            ftypes = [("RINEX files",
                       "*.rnx *.obs *.RNX *.OBS *.??o *.??O *.??d *.??D"),
                      ("All", "*.*")]
        elif kind == "SP3":
            ftypes = [("SP3 files", "*.sp3 *.SP3 *.EPH *.eph"), ("All", "*.*")]
        path = filedialog.askopenfilename(title=f"Select {kind} File", filetypes=ftypes)
        if path:
            var.set(path)
            if kind == "RINEX":
                if not self.output_path.get():
                    # Put output in results/ folder
                    results_dir = self._get_results_dir()
                    basename = os.path.basename(path)
                    name, ext = os.path.splitext(basename)
                    self.output_path.set(os.path.join(results_dir, f"{name}_masked{ext}"))
                # Parse header to update C/N₀ signal list dynamically
                self._update_cn0_from_rinex_header(path)

    def _browse_output(self):
        results_dir = self._get_results_dir()
        # Preserve the masked file's extension: keep whatever
        # extension the suggested output already carries (which mirrors the input
        # RINEX, e.g. *.26o) instead of forcing *.rnx.
        current = self.output_path.get()
        init_file = os.path.basename(current) if current else ""
        init_dir = os.path.dirname(current) if current else results_dir
        ext = os.path.splitext(current)[1] if current else ".rnx"
        path = filedialog.asksaveasfilename(title="Save Output RINEX",
                                            initialdir=init_dir or results_dir,
                                            initialfile=init_file,
                                            defaultextension=ext,
                                            filetypes=[("RINEX / observation",
                                                        "*.rnx *.obs *.??o *.??O"),
                                                       ("All", "*.*")])
        if path:
            self.output_path.set(path)

    # ----------------------------------------------------------------
    # Info & Contact dialogs
    # ----------------------------------------------------------------
    def _show_about(self):
        # Credit for the sky segmentation. "Auto-Mask from Image" consumes
        # segmentation masks produced in the IPI/IfE project seminar (summer
        # semester 2026); Ali Habib Nezhad built the segmentation that
        # RINEX-Masker reads.
        messagebox.showinfo("Information - RINEX-Masker",
                            "RINEX-Masker\n" + VERSION_TEXT + "\n\n"
                            "Applies azimuth/elevation obstruction masks to\n"
                            "RINEX 3.x / 4.x observation files. Satellite\n"
                            "positions computed from SP3 precise ephemeris.\n\n"
                            "Institut f\u00fcr Erdmessung (IfE)\n"
                            "Leibniz Universit\u00e4t Hannover\n\n"
                            "License: GNU General Public License v3 (GPLv3)\n\n"
                            "Developers:\n"
                            "  Amr Fawzy, M.Sc.\n"
                            "  Dr.-Ing. Johannes Kr\u00f6ger\n\n"
                            # Written as an Acknowledgement, in the
                            # shape PCC-Explorer uses for Mareike Brekenkamp,
                            # rather than as a list of names under a heading.
                            "Acknowledgement:\n"
                            "The authors thank the Image Analysis sub-group of\n"
                            "the IPI/IfE project seminar (SoSe 2026), supervised\n"
                            "by Max Meyer (IPI) and Kai Baasch (IfE), for the sky\n"
                            "segmentation behind Auto-Mask from Image, and in\n"
                            "particular Ali Habib Nezhad, who developed and\n"
                            "trained the segmentation pipeline.\n\n"
                            "The segmentation masks consumed by Auto-Mask from\n"
                            "Image are produced by that pipeline; RINEX-Masker\n"
                            "only converts them into a horizon profile.")

    def _show_contact(self):
        _show_ife_contact(self)

    def _show_mailing_list(self):
        """The mailing list dialog, on request, whatever was answered before."""
        if mailing_list is None:
            messagebox.showwarning(
                "IfE software mailing list",
                "This installation is missing mailing_list.py, so the "
                "subscription dialog cannot be shown. Please report it to "
                "the IfE, the Contact button has the address.")
            return
        mailing_list.show_on_request(self, "RINEX-Masker")

    # ----------------------------------------------------------------
    # C/N0 dynamic signal grid
    # ----------------------------------------------------------------
    def _build_cn0_per_signal_grid(self):
        """Build the per-signal C/N₀ threshold entries from _cn0_signal_groups."""
        # Clear existing widgets
        for widget in self.cn0_per_signal_frame.winfo_children():
            widget.destroy()
        self.cn0_signal_entries.clear()

        SYSTEM_CHAR_MAP = {'GPS': 'G', 'Galileo': 'E', 'GLONASS': 'R', 'BDS': 'C',
                           'QZSS': 'J', 'SBAS': 'S'}

        col = 0
        for sys_name, signals in self._cn0_signal_groups.items():
            sys_frame = ttk.LabelFrame(self.cn0_per_signal_frame, text=sys_name, padding=4)
            sys_frame.grid(row=0, column=col, padx=4, pady=2, sticky='nsew')
            for row_idx, sig_key in enumerate(signals):
                # Display as e.g. "S1C" instead of "G_S1C"
                display_name = sig_key.split('_')[1] if '_' in sig_key else sig_key
                ttk.Label(sys_frame, text=f"{display_name}:", width=5).grid(
                    row=row_idx, column=0, padx=(2, 4), pady=1, sticky='w')
                var = tk.StringVar(value="")  # Empty = use global threshold
                entry = ttk.Entry(sys_frame, textvariable=var, width=5, state="disabled")
                entry.grid(row=row_idx, column=1, padx=2, pady=1)
                # Unit label so it is clear the thresholds are in dB-Hz
                ttk.Label(sys_frame, text="dB-Hz").grid(
                    row=row_idx, column=2, padx=(2, 2), pady=1, sticky='w')
                self.cn0_signal_entries[sig_key] = (var, entry)
            col += 1

    def _update_cn0_from_rinex_header(self, rinex_path):
        """Parse RINEX header and update C/N₀ per-signal entries from actual S-type obs."""
        try:
            with open(rinex_path, 'r', encoding='ascii', errors='ignore') as f:
                lines = f.readlines()

            from rinex_handler import parse_header
            header, _ = parse_header(lines)

            SYSTEM_NAME_MAP = {'G': 'GPS', 'E': 'Galileo', 'R': 'GLONASS',
                               'C': 'BDS', 'J': 'QZSS', 'S': 'SBAS'}

            new_groups = {}
            for sys_char, obs_list in header.obs_types.items():
                sys_name = SYSTEM_NAME_MAP.get(sys_char, sys_char)
                s_types = [f"{sys_char}_{obs}" for obs in obs_list if obs.startswith('S')]
                if s_types:
                    new_groups[sys_name] = s_types

            if new_groups:
                self._cn0_signal_groups = new_groups
                self._build_cn0_per_signal_grid()
                # Re-add the info label at bottom
                ttk.Label(self.cn0_per_signal_frame,
                          text="Signals from RINEX header. Leave empty to use global threshold.",
                          font=("Helvetica", 8), bootstyle="light").grid(
                              row=1, column=0, columnspan=len(new_groups), padx=5, pady=(4, 0), sticky='w')
                # If advanced panel is currently shown, refresh it
                if hasattr(self, 'cn0_advanced_var') and self.cn0_advanced_var.get():
                    self._toggle_cn0_advanced()

        except Exception as e:
            print(f"Warning: Could not parse RINEX header for C/N₀ signals: {e}")

    # ----------------------------------------------------------------
    # C/N0 toggle
    # ----------------------------------------------------------------
    def _update_cn0_state(self):
        """Enable/disable the C/N0 threshold entry based on checkbox."""
        state = "normal" if self.cn0_active_var.get() else "disabled"
        self.cn0_entry.configure(state=state)
        # Also update advanced entries if advanced mode is active
        if hasattr(self, 'cn0_advanced_var') and self.cn0_advanced_var.get():
            self._toggle_cn0_advanced()

    def _toggle_cn0_advanced(self):
        """Show/hide per-signal threshold entries."""
        if self.cn0_advanced_var.get() and self.cn0_active_var.get():
            self.cn0_per_signal_frame.pack(fill="x", padx=5, pady=(3, 0))
            for sig_key, (var, entry) in self.cn0_signal_entries.items():
                entry.configure(state="normal")
        else:
            self.cn0_per_signal_frame.pack_forget()
            for sig_key, (var, entry) in self.cn0_signal_entries.items():
                entry.configure(state="disabled")

    def _get_per_signal_cn0_thresholds(self):
        """Build dict of per-signal C/N0 thresholds from the advanced entries.
        Returns: dict {obs_code: threshold_float} for non-empty entries, e.g. {'S1C': 20.0}
        """
        thresholds = {}
        if not (hasattr(self, 'cn0_advanced_var') and self.cn0_advanced_var.get()):
            return thresholds
        for sig_key, (var, entry) in self.cn0_signal_entries.items():
            val = var.get().strip()
            if val:
                try:
                    # sig_key is like 'G_S1C' -> sys_char='G', obs_code='S1C'
                    parts = sig_key.split('_')
                    sys_char = parts[0]
                    obs_code = parts[1]
                    thresholds[(sys_char, obs_code)] = float(val)
                except ValueError:
                    pass
        return thresholds

    # ----------------------------------------------------------------
    # Mask JSON export/import
    # ----------------------------------------------------------------
    def _export_mask_json(self):
        """Export current mask settings to a JSON file."""
        from elevation_mask import ElevationMask
        try:
            cutoff = float(self.cutoff_var.get())
        except ValueError:
            cutoff = 0.0

        mask = ElevationMask(uniform_cutoff=cutoff)
        if hasattr(self, 'azimuth_masks_list'):
            for az_from, az_to, el_limit in self.azimuth_masks_list:
                mask.add_sector(az_from, az_to, el_limit)
        if hasattr(self, 'horizon_profile_list') and len(self.horizon_profile_list) >= 2:
            mask.set_horizon_profile(self.horizon_profile_list)

        path = filedialog.asksaveasfilename(
            title="Export Mask Definition",
            defaultextension=".json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
            initialdir=self._get_results_dir())
        if path:
            try:
                mask.save_json(path)
                messagebox.showinfo("Export Complete",
                                    f"Mask exported to:\n{path}\n\n"
                                    f"{mask.summary()}")
            except Exception as e:
                messagebox.showerror("Export Error", str(e))

    def _import_mask_json(self):
        """Import mask settings from a JSON file."""
        from elevation_mask import ElevationMask
        path = filedialog.askopenfilename(
            title="Import Mask Definition",
            filetypes=[("JSON files", "*.json"), ("Mask files", "*.txt *.json"), ("All files", "*.*")],
            initialdir=self._get_results_dir())
        if not path:
            return
        try:
            mask = ElevationMask.load_json(path)

            # Apply to GUI
            self.cutoff_var.set(str(mask.uniform_cutoff))

            # Clear existing sectors
            if hasattr(self, 'azimuth_masks_list'):
                self.azimuth_masks_list.clear()
            if hasattr(self, 'mask_listbox'):
                self.mask_listbox.delete(0, tk.END)

            # Add imported sectors
            for az_from, az_to, el_limit in mask.sectors:
                self.azimuth_masks_list.append((az_from, az_to, el_limit))
                if hasattr(self, 'mask_listbox'):
                    self.mask_listbox.insert(tk.END,
                        f"Az {az_from:.0f}-{az_to:.0f} deg, El < {el_limit:.0f} deg")

            # Apply horizon profile
            if mask.horizon_profile:
                self.horizon_profile_list = list(mask.horizon_profile)
                if hasattr(self, 'profile_text'):
                    self.profile_text.configure(state="normal")
                    self.profile_text.delete("1.0", tk.END)
                    for az, el in mask.horizon_profile:
                        self.profile_text.insert(tk.END, f"{az:.1f}, {el:.1f}\n")
                    self.profile_text.configure(state="disabled")

            messagebox.showinfo("Import Complete",
                                f"Mask imported from:\n{os.path.basename(path)}\n\n"
                                f"{mask.summary()}")
        except Exception as e:
            messagebox.showerror("Import Error", f"Failed to import mask:\n{e}")

    # ----------------------------------------------------------------
    # Run masking
    # ----------------------------------------------------------------
    def _run_masking(self):
        # Validate inputs
        rinex = self.rinex_path.get().strip()
        if not rinex or not os.path.exists(rinex):
            messagebox.showerror("Error", "Please select a valid RINEX file.")
            return

        output = self.output_path.get().strip()
        if not output:
            messagebox.showerror("Error", "Please specify an output file path.")
            return

        try:
            cutoff = float(self.cutoff_var.get())
        except ValueError:
            messagebox.showerror("Error", "Invalid elevation cutoff value.")
            return

        # Build mask
        from elevation_mask import ElevationMask
        mask = ElevationMask(uniform_cutoff=cutoff)
        if self.az_mask_active_var.get():
            for az_from, az_to, el_limit in self.azimuth_masks_list:
                mask.add_sector(az_from, az_to, el_limit)
        # Add horizon profile if defined
        if hasattr(self, 'horizon_profile_list') and len(self.horizon_profile_list) >= 2:
            mask.set_horizon_profile(self.horizon_profile_list)

        # Manual position
        manual_pos = self._get_manual_position()
        if manual_pos == "error":
            return  # validation failed

        # Time filter
        time_start = None
        time_end = None
        if self.time_filter_var.get():
            ts = self.time_start_var.get().strip()
            te = self.time_end_var.get().strip()
            if ts:
                try:
                    time_start = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    messagebox.showerror("Error", "Invalid start time format.\nUse: YYYY-MM-DD HH:MM:SS")
                    return
            if te:
                try:
                    time_end = datetime.strptime(te, "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    messagebox.showerror("Error", "Invalid end time format.\nUse: YYYY-MM-DD HH:MM:SS")
                    return

        # SP3 source
        sp3_src = None
        if not self.auto_sp3_var.get():
            sp3 = self.sp3_path.get().strip()
            if not sp3 or not os.path.exists(sp3):
                messagebox.showerror("Error", "Please select a valid SP3 file or enable auto-download.")
                return
            sp3_src = sp3

        skyplot = self.skyplot_var.get()

        # C/N0 threshold
        cn0_threshold = 0.0
        cn0_per_signal = {}
        if self.cn0_active_var.get():
            try:
                cn0_threshold = float(self.cn0_threshold_var.get())
            except ValueError:
                messagebox.showerror("Error", "Invalid C/N\u2080 threshold value.")
                return
            # Collect per-signal overrides
            cn0_per_signal = self._get_per_signal_cn0_thresholds()

        # Clear log
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", tk.END)
        self.log_text.configure(state="disabled")
        self.progress_var.set(0.0)
        self.status_var.set("Starting...")

        # Disable run button
        self.run_btn.configure(state="disabled")
        self.is_running = True

        # Run in background thread
        def _worker():
            try:
                from masker import apply_mask
                stats = apply_mask(
                    rinex_path=rinex,
                    sp3_path_or_date=sp3_src,
                    mask=mask,
                    output_path=output,
                    generate_skyplot=skyplot,
                    log_callback=self._log_from_thread,
                    progress_callback=self._progress_from_thread,
                    manual_position=manual_pos,
                    time_start=time_start,
                    time_end=time_end,
                    cn0_threshold=cn0_threshold,
                    cn0_per_signal=cn0_per_signal,
                )
                self.last_stats = stats
                self.after(0, lambda: self.status_var.set("Done!"))
                # Auto-show skyplot on the main thread (background thread only saved to file)
                if skyplot and stats.get('skyplot_all'):
                    self.after(100, self._show_skyplot)
                self.after(0, lambda: messagebox.showinfo("Complete",
                    f"Masking complete!\n\n"
                    f"Kept: {stats['total_sats_kept']} / {stats['total_sats_original']} observations\n"
                    f"Removed: {stats['total_sats_removed']}\n\n"
                    f"Output: {output}"))
            except Exception as e:
                import traceback
                tb = traceback.format_exc()
                e_msg = str(e)
                self.after(0, lambda m=e_msg, t=tb: self._log_from_thread(f"\nERROR: {m}\n{t}"))
                self.after(0, lambda m=e_msg: self.status_var.set(f"Error: {m}"))
                self.after(0, lambda m=e_msg: messagebox.showerror("Error", m))
            finally:
                self.after(0, lambda: self.run_btn.configure(state="normal"))
                self.is_running = False

        thread = threading.Thread(target=_worker, daemon=True)
        thread.start()

    def _log_from_thread(self, msg):
        """Thread-safe log append."""
        def _append():
            self.log_text.configure(state="normal")
            self.log_text.insert(tk.END, msg + "\n")
            self.log_text.see(tk.END)
            self.log_text.configure(state="disabled")
        self.after(0, _append)

    def _progress_from_thread(self, frac):
        """Thread-safe progress update."""
        def _update():
            self.progress_var.set(frac)
            pct = int(frac * 100)
            self.status_var.set(f"Processing... {pct}%")
        self.after(0, _update)

    # ----------------------------------------------------------------
    # Skyplot
    # ----------------------------------------------------------------
    def _show_skyplot(self):
        if not self.last_stats:
            messagebox.showinfo("No Data", "Run masking first to generate skyplot data.")
            return
        skyplot_all = self.last_stats.get('skyplot_all', {})
        skyplot_visible = self.last_stats.get('skyplot_visible', {})
        if not skyplot_all:
            messagebox.showinfo("No Data", "No skyplot data available from last run.")
            return

        from elevation_mask import ElevationMask
        mask = ElevationMask(uniform_cutoff=float(self.cutoff_var.get()))
        if self.az_mask_active_var.get():
            for az_from, az_to, el_limit in self.azimuth_masks_list:
                mask.add_sector(az_from, az_to, el_limit)
        if hasattr(self, 'horizon_profile_list') and len(self.horizon_profile_list) >= 2:
            mask.set_horizon_profile(self.horizon_profile_list)

        # Build metadata from last run stats
        metadata = {
            'station': self.last_stats.get('station_name', ''),
            'position': self.last_stats.get('station_xyz', []),
            'first_epoch': self.last_stats.get('first_epoch'),
            'last_epoch': self.last_stats.get('last_epoch'),
        }

        from skyplot import plot_before_after
        plot_before_after(skyplot_all, skyplot_visible, mask=mask,
                         show=True, metadata=metadata)

    def _close_figures(self):
        import matplotlib.pyplot as plt
        n = len(plt.get_fignums())
        if n == 0:
            messagebox.showinfo("Close Figures", "No figure windows open.")
        else:
            plt.close('all')
            messagebox.showinfo("Close Figures", f"Closed {n} figure(s).")


if __name__ == '__main__':
    app = App()
    if mailing_list is not None:
        mailing_list.maybe_show(app, "RINEX-Masker")
    app.mainloop()
