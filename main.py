"""
KHInsider Album Downloader — Modern Tkinter GUI
Canvas-drawn track list, PIL-rendered checkboxes, dark theme, format selector.
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from PIL import Image, ImageTk, ImageDraw, ImageFilter
import threading
import concurrent.futures
import os
import re
import shutil
import traceback

from downloader import get_album_info, get_download_link, download_album_art, download_file
from metadata import embed_album_art

# ── Fonts ───────────────────────────────────────────────────────────

FF = "Segoe UI"
FONT_SM       = (FF, 9)
FONT_BASE     = (FF, 10)
FONT_BASE_B   = (FF, 10, "bold")
FONT_MD       = (FF, 11)
FONT_MD_B     = (FF, 11, "bold")
FONT_LG       = (FF, 13, "bold")
FONT_XL       = (FF, 15, "bold")

# ── Colors ──────────────────────────────────────────────────────────

T = {
    "bg":           "#0e0e14",
    "bg_secondary": "#161620",
    "bg_card":      "#161620",
    "bg_card_alt":  "#1c1c28",
    "bg_input":     "#1a1a26",
    "bg_hover":     "#242432",
    "fg":           "#e8e8ee",
    "fg_secondary": "#8888a0",
    "fg_dim":       "#55556a",
    "border":       "#2a2a38",
    "accent":       "#7c6cf7",
    "accent_hover": "#8e80ff",
    "success":      "#00d4aa",
    "success_hover":"#00eabc",
    "error":        "#ff6b6b",
    "scrollbar":    "#3a3a4e",
    "scrollbar_hover": "#5a5a72",
    "checkbox_border": "#3a3a4e",
    "progress_bg":  "#222232",
}

# ── Helpers ─────────────────────────────────────────────────────────

def safe_filename(s):
    return re.sub(r'[\\/*?:"<>|]', "", s).replace("%20", " ").replace("_", " ").strip()

def safe_foldername(s):
    return re.sub(r'[\\/*?:"<>|]', "", s).strip()

def strip_leading_number(title):
    return re.sub(r"^\s*\d+\s*[\.\-]?\s*", "", title).strip()

def format_bytes(b):
    if b < 1024 * 1024:
        return f"{b / 1024:.0f} KB"
    return f"{b / (1024 * 1024):.1f} MB"

def round_corner_image(img, radius=18):
    img = img.convert("RGBA")
    w, h = img.size
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, w, h], radius=radius, fill=255)
    img.putalpha(mask)
    return img

def add_shadow(img, offset=4, blur=10, shadow_color=(0, 0, 0, 35)):
    w, h = img.size
    pad = blur * 2
    shadow = Image.new("RGBA", (w + pad, h + pad), (0, 0, 0, 0))
    shadow.paste(Image.new("RGBA", (w, h), shadow_color), (blur + offset, blur + offset))
    shadow = shadow.filter(ImageFilter.GaussianBlur(blur))
    shadow.paste(img, (blur, blur), img)
    return shadow

def make_app_icon(accent="#6c5ce7"):
    s = 64
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([4, 4, 60, 60], radius=14, fill=accent)
    d.polygon([(24, 16), (40, 16), (40, 32), (48, 32), (32, 48), (16, 32), (24, 32)],
              fill="white")
    return img

def make_checkbox_image(size, checked, accent, border_color):
    s2 = size * 3
    img = Image.new("RGBA", (s2, s2), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if checked:
        d.rounded_rectangle([2, 2, s2 - 2, s2 - 2], radius=s2 // 5, fill=accent)
        lw = max(s2 // 8, 3)
        points = [(s2 * 0.24, s2 * 0.52), (s2 * 0.42, s2 * 0.70), (s2 * 0.76, s2 * 0.32)]
        d.line(points, fill="white", width=lw, joint="curve")
    else:
        d.rounded_rectangle([2, 2, s2 - 2, s2 - 2], radius=s2 // 5,
                            outline=border_color, width=max(s2 // 10, 2))
    return img.resize((size, size), Image.LANCZOS)


# ── Canvas-drawn track list ─────────────────────────────────────────

class TrackList(tk.Canvas):
    """High-perf canvas track list with PIL checkboxes, draggable scrollbar."""

    ROW_H = 40
    CB_SIZE = 18
    PB_H = 6
    SB_W = 6

    def __init__(self, master, **kw):
        super().__init__(master, highlightthickness=0, bd=0, bg=T["bg"], **kw)
        self._tracks = []
        self._hover_idx = -1
        self._width = 600
        self._built = False

        # Scrollbar state
        self._sb_dragging = False
        self._sb_drag_start_y = 0
        self._sb_drag_start_view = 0.0
        self._sb_hovered = False

        self._tk_checked = None
        self._tk_unchecked = None
        self._gen_cb_images()

        self.bind("<ButtonPress-1>", self._on_press)
        self.bind("<ButtonRelease-1>", self._on_release)
        self.bind("<B1-Motion>", self._on_drag)
        self.bind("<Motion>", self._on_motion)
        self.bind("<Leave>", self._on_leave)
        self.bind("<MouseWheel>", self._on_wheel)
        self.bind("<Configure>", self._on_resize)

    def _gen_cb_images(self):
        self._img_checked = make_checkbox_image(
            self.CB_SIZE, True, T["accent"], T["checkbox_border"])
        self._img_unchecked = make_checkbox_image(
            self.CB_SIZE, False, T["accent"], T["checkbox_border"])
        self._tk_checked = ImageTk.PhotoImage(self._img_checked)
        self._tk_unchecked = ImageTk.PhotoImage(self._img_unchecked)

    def set_tracks(self, tracks):
        self._tracks = [
            {"title": t["title"], "selected": True,
             "progress": 0, "status": "", "status_color": ""}
            for t in tracks
        ]
        self._hover_idx = -1
        self._built = False
        self._build()

    def _build(self):
        self.delete("all")
        w = max(self.winfo_width(), 500)
        self._width = w
        rh = self.ROW_H

        for i, tr in enumerate(self._tracks):
            y = i * rh
            bg = T["bg_card"] if i % 2 == 0 else T["bg_card_alt"]

            self.create_rectangle(0, y, w, y + rh, fill=bg, outline="",
                                  tags=(f"r{i}", f"bg{i}"))

            cb_x = 20
            cb_y = y + (rh - self.CB_SIZE) // 2
            img = self._tk_checked if tr["selected"] else self._tk_unchecked
            self.create_image(cb_x, cb_y, image=img, anchor="nw",
                              tags=(f"r{i}", f"cb{i}"))

            self.create_text(56, y + rh // 2, text=f"{i + 1:02d}",
                             font=FONT_SM, fill=T["fg_dim"],
                             anchor="e", tags=(f"r{i}", f"num{i}"))

            title_max_w = max(w - 400, 150)
            self.create_text(68, y + rh // 2, text=tr["title"],
                             font=FONT_BASE, fill=T["fg"],
                             anchor="w", width=title_max_w,
                             tags=(f"r{i}", f"ttl{i}"))

            # Progress bar (hidden) — shifted left to avoid overlap with status
            pb_x = w - 380
            pb_w = 160
            pb_y1 = y + (rh - self.PB_H) // 2
            pb_y2 = pb_y1 + self.PB_H
            self.create_rectangle(pb_x, pb_y1, pb_x + pb_w, pb_y2,
                                  fill=T["progress_bg"], outline="",
                                  tags=(f"pbbg{i}",), state="hidden")
            self.create_rectangle(pb_x, pb_y1, pb_x, pb_y2,
                                  fill=T["accent"], outline="",
                                  tags=(f"pb{i}",), state="hidden")

            # Status text (larger font for readability)
            self.create_text(w - 16, y + rh // 2, text="",
                             font=FONT_SM, fill=T["fg_dim"],
                             anchor="e", tags=(f"st{i}",))

        # Restore progress/status state after rebuild
        for i, tr in enumerate(self._tracks):
            if tr["progress"] > 0:
                self.itemconfig(f"pbbg{i}", state="normal")
                self.itemconfig(f"pb{i}", state="normal")
                pb_x = w - 380
                fill_w = int(160 * min(tr["progress"], 100) / 100)
                y = i * rh
                pb_y1 = y + (rh - self.PB_H) // 2
                pb_y2 = pb_y1 + self.PB_H
                self.coords(f"pb{i}", pb_x, pb_y1, pb_x + fill_w, pb_y2)
            if tr["status"]:
                self.itemconfig(f"st{i}", text=tr["status"],
                                fill=tr["status_color"] or T["fg_dim"])

        total_h = len(self._tracks) * rh
        self.configure(scrollregion=(0, 0, w, max(total_h, 1)))
        self._built = True
        self._draw_scrollbar()

    # ── Scrollbar ───────────────────────────────────────────────────

    def _sb_metrics(self):
        """Return (thumb_frac_y, thumb_frac_h) as fractions of visible height, or None."""
        region = self.cget("scrollregion")
        if not region:
            return None
        parts = str(region).split()
        if len(parts) < 4:
            return None
        total_h = float(parts[3])
        vis_h = self.winfo_height()
        if vis_h <= 0 or total_h <= vis_h:
            return None
        yv = self.yview()
        ratio = vis_h / total_h
        thumb_h = max(ratio * vis_h, 28)
        track_h = vis_h - 4
        thumb_y = 2 + yv[0] / (1.0 - ratio) * (track_h - thumb_h) if ratio < 1 else 2
        return thumb_y, thumb_h, vis_h, total_h

    def _draw_scrollbar(self):
        """Draw scrollbar in screen coords by offsetting for scroll position."""
        self.delete("scrollbar")
        m = self._sb_metrics()
        if not m:
            return
        thumb_y, thumb_h, vis_h, total_h = m

        # Convert to canvas coords: add the scroll offset
        scroll_offset = self.canvasy(0)
        cy1 = scroll_offset + thumb_y
        cy2 = scroll_offset + thumb_y + thumb_h

        x = self._width - 8
        w = self.SB_W
        color = T["scrollbar_hover"] if self._sb_hovered or self._sb_dragging else T["scrollbar"]

        r = w // 2
        x1, x2 = x, x + w
        pts = [x1+r, cy1, x2-r, cy1, x2, cy1, x2, cy1+r,
               x2, cy2-r, x2, cy2, x2-r, cy2, x1+r, cy2,
               x1, cy2, x1, cy2-r, x1, cy1+r, x1, cy1]
        self.create_polygon(pts, smooth=True, fill=color, outline="",
                            tags=("scrollbar",))

    def _hit_scrollbar(self, event):
        return event.x >= self._width - 18

    # ── Interaction ─────────────────────────────────────────────────

    def _on_press(self, event):
        if self._hit_scrollbar(event):
            m = self._sb_metrics()
            if not m:
                return
            thumb_y, thumb_h, vis_h, total_h = m
            if thumb_y <= event.y <= thumb_y + thumb_h:
                self._sb_dragging = True
                self._sb_drag_start_y = event.y
                self._sb_drag_start_view = self.yview()[0]
            else:
                ratio = vis_h / total_h
                track_h = vis_h - 4
                denom = track_h - thumb_h
                new_top = ((event.y - 2 - thumb_h / 2) / denom) * (1.0 - ratio) if denom > 0 else 0
                new_top = max(0.0, min(1.0 - ratio, new_top))
                self.yview_moveto(new_top)
                self.after_idle(self._draw_scrollbar)
        else:
            cy = self.canvasy(event.y)
            idx = int(cy // self.ROW_H)
            if 0 <= idx < len(self._tracks):
                tr = self._tracks[idx]
                tr["selected"] = not tr["selected"]
                img = self._tk_checked if tr["selected"] else self._tk_unchecked
                self.itemconfig(f"cb{idx}", image=img)

    def _on_release(self, _):
        self._sb_dragging = False

    def _on_drag(self, event):
        if self._sb_dragging:
            m = self._sb_metrics()
            if not m:
                return
            _, thumb_h, vis_h, total_h = m
            track_h = vis_h - 4
            dy = event.y - self._sb_drag_start_y
            denom = track_h - thumb_h
            delta_frac = (dy / denom) * (1.0 - vis_h / total_h) if denom > 0 else 0
            new_top = self._sb_drag_start_view + delta_frac
            ratio = vis_h / total_h
            new_top = max(0.0, min(1.0 - ratio, new_top))
            self.yview_moveto(new_top)
            self.after_idle(self._draw_scrollbar)

    def _on_motion(self, event):
        on_sb = self._hit_scrollbar(event)
        if on_sb != self._sb_hovered:
            self._sb_hovered = on_sb
            self._draw_scrollbar()

        if not on_sb and not self._sb_dragging:
            cy = self.canvasy(event.y)
            idx = int(cy // self.ROW_H)
            if idx < 0 or idx >= len(self._tracks):
                idx = -1
            if idx != self._hover_idx:
                if 0 <= self._hover_idx < len(self._tracks):
                    bg = T["bg_card"] if self._hover_idx % 2 == 0 else T["bg_card_alt"]
                    self.itemconfig(f"bg{self._hover_idx}", fill=bg)
                if idx >= 0:
                    self.itemconfig(f"bg{idx}", fill=T["bg_hover"])
                self._hover_idx = idx

    def _on_leave(self, _):
        if 0 <= self._hover_idx < len(self._tracks):
            bg = T["bg_card"] if self._hover_idx % 2 == 0 else T["bg_card_alt"]
            self.itemconfig(f"bg{self._hover_idx}", fill=bg)
        self._hover_idx = -1
        if self._sb_hovered:
            self._sb_hovered = False
            self._draw_scrollbar()

    def _on_wheel(self, event):
        self.yview_scroll(int(-1 * (event.delta / 120)), "units")
        self.after_idle(self._draw_scrollbar)

    def _on_resize(self, event):
        if self._built and abs(event.width - self._width) > 20:
            self._build()

    # ── Public API ──────────────────────────────────────────────────

    def select_all(self):
        for i, tr in enumerate(self._tracks):
            tr["selected"] = True
            self.itemconfig(f"cb{i}", image=self._tk_checked)

    def deselect_all(self):
        for i, tr in enumerate(self._tracks):
            tr["selected"] = False
            self.itemconfig(f"cb{i}", image=self._tk_unchecked)

    def get_selected_indices(self):
        return [i for i, tr in enumerate(self._tracks) if tr["selected"]]

    def show_progress(self, idx):
        self.itemconfig(f"pbbg{idx}", state="normal")
        self.itemconfig(f"pb{idx}", state="normal")

    def set_progress(self, idx, pct):
        w = self._width
        pb_x = w - 380
        fill_w = int(160 * min(pct, 100) / 100)
        y = idx * self.ROW_H
        pb_y1 = y + (self.ROW_H - self.PB_H) // 2
        pb_y2 = pb_y1 + self.PB_H
        self.coords(f"pb{idx}", pb_x, pb_y1, pb_x + fill_w, pb_y2)
        self._tracks[idx]["progress"] = pct

    def set_status(self, idx, text, color=None):
        self._tracks[idx]["status"] = text
        self._tracks[idx]["status_color"] = color or T["fg_dim"]
        self.itemconfig(f"st{idx}", text=text, fill=color or T["fg_dim"])


# ── Flat button ─────────────────────────────────────────────────────

class FlatButton(tk.Frame):
    def __init__(self, master, text="", command=None, width=120, height=34,
                 bg=T["accent"], fg="#ffffff", hover_bg=T["accent_hover"],
                 font=FONT_BASE_B, **kw):
        super().__init__(master, bg=bg, width=width, height=height,
                         cursor="hand2", **kw)
        self.pack_propagate(False)
        self._cmd = command
        self._bg = bg
        self._fg = fg
        self._hover = hover_bg
        self._disabled = False
        self._lbl = tk.Label(self, text=text, font=font, fg=fg, bg=bg,
                             cursor="hand2")
        self._lbl.place(relx=0.5, rely=0.5, anchor="center")
        for widget in (self, self._lbl):
            widget.bind("<Enter>", lambda _: self._enter())
            widget.bind("<Leave>", lambda _: self._leave())
            widget.bind("<ButtonRelease-1>", lambda _: self._click())

    def _enter(self):
        if not self._disabled:
            self.config(bg=self._hover)
            self._lbl.config(bg=self._hover)

    def _leave(self):
        self.config(bg=self._bg)
        self._lbl.config(bg=self._bg)

    def _click(self):
        if not self._disabled and self._cmd:
            self._cmd()

    def set_disabled(self, val):
        self._disabled = val
        self.config(cursor="" if val else "hand2")
        self._lbl.config(cursor="" if val else "hand2",
                         fg="#555" if val else self._fg)

    def set_text(self, text):
        self._lbl.config(text=text)


# ── Placeholder entry ───────────────────────────────────────────────

class PlaceholderEntry(tk.Entry):
    def __init__(self, master, placeholder="", **kw):
        self._fg = kw.get("fg", T["fg"])
        self._ph_color = T["fg_dim"]
        super().__init__(master, **kw)
        self.placeholder = placeholder
        self._showing = False
        self.bind("<FocusIn>", self._fi)
        self.bind("<FocusOut>", self._fo)
        self._show_ph()

    def _show_ph(self):
        if not self.get():
            self._showing = True
            self.insert(0, self.placeholder)
            self.config(fg=self._ph_color)

    def _fi(self, _):
        if self._showing:
            self.delete(0, tk.END)
            self.config(fg=self._fg)
            self._showing = False

    def _fo(self, _):
        if not self.get():
            self._show_ph()

    def get_value(self):
        return "" if self._showing else self.get()


# ── Main application ────────────────────────────────────────────────

class KHInsiderApp(tk.Tk):
    def __init__(self):
        super().__init__()

        self.title("KHInsider Downloader")
        self._app_icon = ImageTk.PhotoImage(make_app_icon(T["accent"]))
        self.iconphoto(True, self._app_icon)
        self.geometry("1080x750")
        self.minsize(920, 620)
        self.configure(bg=T["bg"])

        self.album_info = None
        self.album_art_path = None
        self.album_art_photo = None
        self._art_pil = None
        self.save_dir = tk.StringVar(value=os.path.join(os.path.expanduser("~"), "Music"))
        self._downloading = False

        self._build_ui()

    def _build_ui(self):
        # ── Title + URL bar ─────────────────────────────────────────
        top = tk.Frame(self, bg=T["bg"])
        top.pack(fill=tk.X, padx=28, pady=(14, 0))

        tk.Label(top, text="KHInsider Downloader", font=FONT_XL,
                 fg=T["accent"], bg=T["bg"]).pack(anchor="w")

        url_outer = tk.Frame(self, bg=T["bg"], pady=10)
        url_outer.pack(fill=tk.X, padx=28)

        # URL entry with inner padding via a wrapper frame
        url_wrap = tk.Frame(url_outer, bg=T["bg_input"],
                            highlightthickness=1, highlightbackground=T["border"],
                            highlightcolor=T["accent"])
        url_wrap.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 14))

        self.url_entry = PlaceholderEntry(
            url_wrap, placeholder="Paste album URL here...",
            font=FONT_MD, bg=T["bg_input"], fg=T["fg"],
            insertbackground=T["fg"], relief="flat", bd=0,
        )
        self.url_entry.pack(fill=tk.X, ipady=10, padx=14, pady=4)
        self.url_entry.bind("<Return>", lambda _: self._on_fetch())

        self.fetch_btn = FlatButton(url_outer, text="Fetch Album",
                                    command=self._on_fetch, width=130, height=42,
                                    font=FONT_MD_B)
        self.fetch_btn.pack(side=tk.RIGHT)

        # ── Content ─────────────────────────────────────────────────
        self._content = tk.Frame(self, bg=T["bg"])
        self._content.pack(fill=tk.BOTH, expand=True, padx=28, pady=(4, 0))
        self._content.columnconfigure(1, weight=1)
        self._content.rowconfigure(0, weight=1)

        # Left: art + info
        self._left = tk.Frame(self._content, width=280, bg=T["bg"])
        self._left.grid(row=0, column=0, sticky="ns", padx=(0, 24))
        self._left.grid_propagate(False)

        self._art_label = tk.Label(self._left, bg=T["bg"])
        self._art_label.pack(pady=(4, 16))

        self._album_title_lbl = tk.Label(self._left, text="", font=FONT_LG,
                                         fg=T["fg"], bg=T["bg"],
                                         wraplength=260, justify="center")
        self._album_title_lbl.pack()

        self._track_count_lbl = tk.Label(self._left, text="", font=FONT_MD,
                                         fg=T["fg_secondary"], bg=T["bg"])
        self._track_count_lbl.pack(pady=(6, 0))

        # Format selector (hidden until album loaded)
        self._fmt_frame = tk.Frame(self._left, bg=T["bg"])
        # Generate radio images
        self._radio_on = ImageTk.PhotoImage(
            make_checkbox_image(16, True, T["accent"], T["checkbox_border"]))
        self._radio_off = ImageTk.PhotoImage(
            make_checkbox_image(16, False, T["accent"], T["checkbox_border"]))

        self._fmt_options = []  # list of (key, label_widget, icon_widget)
        self._fmt_var = tk.StringVar(value="MP3")
        for key in ("MP3", "FLAC", "MP3 + FLAC"):
            row = tk.Frame(self._fmt_frame, bg=T["bg"], cursor="hand2")
            row.pack(anchor="w", pady=2, padx=10)
            icon = tk.Label(row, image=self._radio_on if key == "MP3" else self._radio_off,
                            bg=T["bg"], cursor="hand2")
            icon.pack(side=tk.LEFT, padx=(0, 8))
            lbl = tk.Label(row, text=key, font=FONT_BASE, fg=T["fg"],
                           bg=T["bg"], cursor="hand2")
            lbl.pack(side=tk.LEFT)
            size_lbl = tk.Label(row, text="", font=FONT_SM, fg=T["fg_dim"], bg=T["bg"])
            size_lbl.pack(side=tk.LEFT, padx=(6, 0))
            self._fmt_options.append((key, icon, lbl, size_lbl, row))
            for w in (row, icon, lbl, size_lbl):
                w.bind("<ButtonRelease-1>", lambda _, k=key: self._select_fmt(k))
        self._fmt_frame.pack_forget()

        style = ttk.Style(self)
        style.theme_use("clam")

        # Right: empty state
        self._empty = tk.Label(self._content,
                               text="Paste an album URL and press Fetch Album.",
                               font=FONT_MD, fg=T["fg_dim"], bg=T["bg"])
        self._empty.grid(row=0, column=1, sticky="nsew")

        self._track_list = None

        # ── Bottom bar ──────────────────────────────────────────────
        tk.Frame(self, height=1, bg=T["border"]).pack(fill=tk.X, side=tk.BOTTOM)

        bottom = tk.Frame(self, height=92, bg=T["bg_secondary"])
        bottom.pack(fill=tk.X, side=tk.BOTTOM)
        bottom.pack_propagate(False)

        fr = tk.Frame(bottom, bg=T["bg_secondary"])
        fr.pack(fill=tk.X, padx=28, pady=(10, 6))

        tk.Label(fr, text="Save to", font=FONT_SM,
                 fg=T["fg_secondary"], bg=T["bg_secondary"]).pack(side=tk.LEFT)

        self._folder_entry = tk.Entry(fr, textvariable=self.save_dir, font=FONT_SM,
                                      bg=T["bg_input"], fg=T["fg"],
                                      insertbackground=T["fg"], relief="flat", bd=0)
        self._folder_entry.pack(side=tk.LEFT, padx=(10, 10), ipady=5,
                                fill=tk.X, expand=True)

        FlatButton(fr, text="Browse", width=80, height=28,
                   command=self._browse, font=FONT_SM,
                   bg=T["border"], hover_bg=T["bg_hover"]).pack(side=tk.RIGHT)

        ar = tk.Frame(bottom, bg=T["bg_secondary"])
        ar.pack(fill=tk.X, padx=28, pady=(0, 10))

        FlatButton(ar, text="Select All", width=86, height=30,
                   command=self._select_all, font=FONT_SM,
                   bg=T["border"], hover_bg=T["bg_hover"]).pack(side=tk.LEFT, padx=(0, 6))

        FlatButton(ar, text="Deselect All", width=96, height=30,
                   command=self._unselect_all, font=FONT_SM,
                   bg=T["border"], hover_bg=T["bg_hover"]).pack(side=tk.LEFT, padx=(0, 18))

        self._overall_var = tk.DoubleVar(value=0)
        style.configure("Overall.Horizontal.TProgressbar",
                        troughcolor=T["progress_bg"], background=T["success"],
                        bordercolor=T["progress_bg"], lightcolor=T["success"],
                        darkcolor=T["success"], borderwidth=0, thickness=6)

        ttk.Progressbar(ar, variable=self._overall_var, maximum=100,
                        style="Overall.Horizontal.TProgressbar",
                        mode="determinate").pack(side=tk.LEFT, fill=tk.X,
                                                  expand=True, padx=(0, 14))

        self._overall_lbl = tk.Label(ar, text="0 / 0", font=FONT_SM, width=8,
                                     fg=T["fg_secondary"], bg=T["bg_secondary"])
        self._overall_lbl.pack(side=tk.LEFT, padx=(0, 18))

        self._dl_btn = FlatButton(ar, text="Download", width=130, height=34,
                                  command=self._on_download, font=FONT_MD_B,
                                  bg=T["success"], hover_bg=T["success_hover"])
        self._dl_btn.pack(side=tk.RIGHT)
        self._dl_btn.set_disabled(True)

    # ── Art ─────────────────────────────────────────────────────────

    def _render_art(self, pil_img):
        img = pil_img.copy().resize((260, 260), Image.LANCZOS)
        img = round_corner_image(img, 16)
        img = add_shadow(img, offset=3, blur=12, shadow_color=(0, 0, 0, 45))
        self.album_art_photo = ImageTk.PhotoImage(img)
        self._art_label.config(image=self.album_art_photo)

    def _browse(self):
        f = filedialog.askdirectory(initialdir=self.save_dir.get())
        if f:
            self.save_dir.set(f)

    def _select_all(self):
        if self._track_list:
            self._track_list.select_all()

    def _unselect_all(self):
        if self._track_list:
            self._track_list.deselect_all()

    def _select_fmt(self, key):
        self._fmt_var.set(key)
        for k, icon, lbl, size_lbl, row in self._fmt_options:
            icon.config(image=self._radio_on if k == key else self._radio_off)

    # ── Fetch ───────────────────────────────────────────────────────

    def _on_fetch(self):
        url = self.url_entry.get_value().strip()
        if not url:
            messagebox.showerror("Error", "Please paste an album URL.")
            return

        self.fetch_btn.set_disabled(True)
        self.fetch_btn.set_text("Fetching...")
        self._dl_btn.set_disabled(True)
        self._album_title_lbl.config(text="Loading...")
        self._track_count_lbl.config(text="")
        self._fmt_frame.pack_forget()
        for _, _, _, size_lbl, _ in self._fmt_options:
            size_lbl.config(text="")
        self._art_label.config(image="")
        self.album_art_photo = None
        self._art_pil = None
        if self._track_list:
            self._track_list.destroy()
            self._track_list = None

        def _work():
            try:
                info = get_album_info(url)
                art_path = None
                tmp_dir = os.environ.get("TEMP", os.getcwd())
                for idx, art_url in enumerate(info["art_urls"]):
                    ext = "png" if art_url.lower().endswith(".png") else "jpg"
                    tmp = os.path.join(tmp_dir, f"_khi_art_{idx}.{ext}")
                    if download_album_art(art_url, tmp):
                        art_path = tmp
                        break
                self.album_info = info
                self.album_art_path = art_path
                self.after(0, lambda: self._populate(info, art_path))
            except Exception as e:
                traceback.print_exc()
                self.after(0, lambda: messagebox.showerror("Fetch failed", str(e)))
            finally:
                self.after(0, lambda: self.fetch_btn.set_disabled(False))
                self.after(0, lambda: self.fetch_btn.set_text("Fetch Album"))

        threading.Thread(target=_work, daemon=True).start()

    def _populate(self, info, art_path):
        title = info["title"]
        tracks = info["tracks"]
        formats = info.get("formats", ["MP3"])
        sizes = info.get("format_sizes", {})

        self._album_title_lbl.config(text=title)
        self._track_count_lbl.config(text=f"{len(tracks)} tracks")

        # Update format options: show/hide based on availability, set sizes
        has_mp3 = "MP3" in formats
        has_flac = "FLAC" in formats
        mp3_size = sizes.get("MP3", "")
        flac_size = sizes.get("FLAC", "")

        # Parse MB values and add them for the combined option
        def _parse_mb(s):
            s = s.replace(",", "").replace(" ", "")
            m = re.search(r"([\d.]+)", s)
            return float(m.group(1)) if m else 0
        both_size = ""
        if mp3_size and flac_size:
            total_mb = _parse_mb(mp3_size) + _parse_mb(flac_size)
            if total_mb >= 1024:
                both_size = f"{total_mb / 1024:.1f} GB"
            else:
                both_size = f"{total_mb:,.0f} MB"

        option_visibility = {
            "MP3": has_mp3,
            "FLAC": has_flac,
            "MP3 + FLAC": has_mp3 and has_flac,
        }
        option_sizes = {
            "MP3": mp3_size,
            "FLAC": flac_size,
            "MP3 + FLAC": both_size,
        }

        for key, icon, lbl, size_lbl, row in self._fmt_options:
            if option_visibility.get(key, False):
                row.pack(anchor="w", pady=2, padx=10)
                size_lbl.config(text=f"({option_sizes[key]})" if option_sizes[key] else "")
            else:
                row.pack_forget()

        # Reset selection to MP3 if current isn't available
        if self._fmt_var.get() not in [k for k, v in option_visibility.items() if v]:
            self._select_fmt("MP3" if has_mp3 else formats[0])
        else:
            self._select_fmt(self._fmt_var.get())

        self._fmt_frame.pack(pady=(12, 0))

        if art_path and os.path.exists(art_path):
            try:
                self._art_pil = Image.open(art_path).copy()
                self._render_art(self._art_pil)
            except Exception:
                traceback.print_exc()

        self._empty.grid_remove()
        self._track_list = TrackList(self._content)
        self._track_list.grid(row=0, column=1, sticky="nsew")
        self._track_list.set_tracks(tracks)

        self._dl_btn.set_disabled(False)
        self._overall_var.set(0)
        self._overall_lbl.config(text=f"0 / {len(tracks)}")

    # ── Download ────────────────────────────────────────────────────

    def _on_download(self):
        if self._downloading or not self.album_info or not self._track_list:
            return
        selected = self._track_list.get_selected_indices()
        if not selected:
            messagebox.showwarning("Nothing selected", "Select at least one track.")
            return

        self._downloading = True
        self._dl_btn.set_disabled(True)
        self._dl_btn.set_text("Downloading...")
        self.fetch_btn.set_disabled(True)

        info = self.album_info
        title = info["title"]
        artist = info.get("artist") or ""
        base_dir = os.path.join(self.save_dir.get(), safe_foldername(title))
        os.makedirs(base_dir, exist_ok=True)
        tracks = info["tracks"]
        fmt_choice = self._fmt_var.get()
        both = fmt_choice == "MP3 + FLAC"
        fmt_list = ["MP3", "FLAC"] if both else [fmt_choice]

        # Create subfolders for dual download
        if both:
            for f in fmt_list:
                os.makedirs(os.path.join(base_dir, f.lower()), exist_ok=True)

        # Copy art
        local_art = None
        if self.album_art_path and os.path.exists(self.album_art_path):
            art_ext = os.path.splitext(self.album_art_path)[1] or ".jpg"
            local_art = os.path.join(base_dir, f"cover{art_ext}")
            try:
                shutil.copy2(self.album_art_path, local_art)
            except Exception:
                local_art = self.album_art_path

        done = {"n": 0}
        total = len(selected)
        lock = threading.Lock()
        tl = self._track_list

        def _finish():
            with lock:
                done["n"] += 1
                c = done["n"]
            pct = c / total * 100
            self.after(0, lambda: self._overall_var.set(pct))
            self.after(0, lambda: self._overall_lbl.config(text=f"{c} / {total}"))
            if c == total:
                self.after(0, self._dl_done)

        def _dl_one(idx):
            track = tracks[idx]
            self.after(0, lambda: tl.show_progress(idx))
            self.after(0, lambda: tl.set_status(idx, "waiting", T["fg_dim"]))
            try:
                num = idx + 1
                for fmt in fmt_list:
                    link = get_download_link(track["page_url"], fmt)
                    if not link:
                        if len(fmt_list) == 1:
                            self.after(0, lambda: tl.set_status(idx, "no link", T["error"]))
                        continue

                    ext = link.rsplit(".", 1)[-1].split("?")[0]
                    fname = f"{num:02d}. {safe_filename(track['title'])}.{ext}"
                    if both:
                        path = os.path.join(base_dir, fmt.lower(), fname)
                    else:
                        path = os.path.join(base_dir, fname)

                    fmt_label = f"{fmt.lower()}: " if both else ""
                    self.after(0, lambda fl=fmt_label: tl.set_status(idx, f"{fl}connecting...", T["accent"]))

                    last_pct = [-1]

                    def _prog(dl, tot, fl=fmt_label):
                        if tot > 0:
                            p = dl / tot * 100
                            if int(p) > last_pct[0] or dl >= tot:
                                last_pct[0] = int(p)
                                status = f"{fl}{p:.0f}%    {format_bytes(dl)} / {format_bytes(tot)}"
                                self.after(0, lambda: tl.set_progress(idx, p))
                                self.after(0, lambda: tl.set_status(idx, status, T["accent"]))

                    download_file(link, path, _prog)

                    if ext.lower() == "mp3" and local_art:
                        try:
                            self.after(0, lambda: tl.set_status(idx, "tagging...", T["fg_secondary"]))
                            embed_album_art(path, local_art,
                                            title=strip_leading_number(track["title"]),
                                            artist=artist, album=title,
                                            track_number=num)
                        except Exception:
                            pass

                self.after(0, lambda: tl.set_progress(idx, 100))
                self.after(0, lambda: tl.set_status(idx, "done", T["success"]))
            except Exception:
                self.after(0, lambda: tl.set_status(idx, "error", T["error"]))
            finally:
                _finish()

        def _pool():
            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
                for idx in selected:
                    ex.submit(_dl_one, idx)

        threading.Thread(target=_pool, daemon=True).start()

    def _dl_done(self):
        self._downloading = False
        self._dl_btn.set_disabled(False)
        self._dl_btn.set_text("Download")
        self.fetch_btn.set_disabled(False)
        messagebox.showinfo("Complete", "All selected tracks downloaded!")


if __name__ == "__main__":
    app = KHInsiderApp()
    app.mainloop()
