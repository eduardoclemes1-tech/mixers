"""Widgets customizados estilo EarTrumpet (Windows 11) + ícones vetoriais nítidos via Pillow."""

from __future__ import annotations

import tkinter as tk
from typing import Callable, Dict

import customtkinter as ctk
from PIL import Image, ImageDraw, ImageFont


# Paleta inspirada no EarTrumpet / Windows 11 Fluent Violet
HEADER_BAND = "#302154"
MICS_BAND = "#261B44"
LIST_BAND = "#171324"
PANEL_BORDER = "#493B6E"
ACCENT_PURPLE = "#9353F5"
ACCENT_PURPLE_HOVER = "#A974FA"
TRACK_UNFILLED = "#463D63"
TRACK_MUTED = "#3A3352"
THUMB_MUTED = "#6E658C"
PEAK_WHITE = "#FFFFFF"
TEXT_PRIMARY = "#F6F5FA"
TEXT_MUTED = "#8B84A3"


class EarTrumpetSlider(tk.Canvas):
    """
    Slider ultra-rápido estilo EarTrumpet:
    - Trilha fina (3px) com preenchimento roxo;
    - Barra branca de nível de áudio em tempo real sobreposta na própria trilha;
    - Thumb em pílula vertical;
    - Suporte a clique, arraste suave e roda do mouse (scroll).
    """

    def __init__(
        self,
        master,
        bg_color: str,
        value: int = 100,
        muted: bool = False,
        accent_color: str = ACCENT_PURPLE,
        peak_color: str = PEAK_WHITE,
        on_change: Callable[[int], None] | None = None,
        height: int = 26,
    ) -> None:
        super().__init__(
            master,
            height=height,
            bg=bg_color,
            highlightthickness=0,
            bd=0,
            cursor="hand2",
        )
        self._bg_color = bg_color
        self._value = max(0, min(100, int(value)))
        self._muted = bool(muted)
        self._peak = 0.0
        self._accent = accent_color
        self._peak_color = peak_color
        self._on_change = on_change
        self._hovered = False
        self._dragging = False

        self.bind("<Configure>", lambda _e: self._redraw())
        self.bind("<Button-1>", self._on_press)
        self.bind("<B1-Motion>", self._on_drag)
        self.bind("<ButtonRelease-1>", self._on_release)
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<MouseWheel>", self._on_wheel)
        self.bind("<Button-4>", lambda _e: self._nudge(4))
        self.bind("<Button-5>", lambda _e: self._nudge(-4))

    def set_value(self, value: int) -> None:
        clamped = max(0, min(100, int(round(value))))
        if clamped != self._value:
            self._value = clamped
            self._redraw()

    def set_muted(self, muted: bool) -> None:
        b = bool(muted)
        if b != self._muted:
            self._muted = b
            self._redraw()

    def set_peak(self, peak: float, color: str | None = None) -> None:
        clamped = max(0.0, min(1.0, float(peak)))
        color_changed = color is not None and color != self._peak_color
        if abs(clamped - self._peak) < 0.015 and not color_changed:
            return
        self._peak = clamped
        if color is not None:
            self._peak_color = color
        self._redraw()

    def _x_to_value(self, x: float) -> int:
        w = max(1, self.winfo_width())
        pad = 8
        usable = max(1, w - 2 * pad)
        ratio = max(0.0, min(1.0, (x - pad) / usable))
        return int(round(ratio * 100))

    def _on_press(self, event) -> None:
        self._dragging = True
        self._apply_from_x(event.x)

    def _on_drag(self, event) -> None:
        if self._dragging:
            self._apply_from_x(event.x)

    def _on_release(self, _event) -> None:
        self._dragging = False
        self._redraw()

    def _on_enter(self, _event) -> None:
        self._hovered = True
        self._redraw()

    def _on_leave(self, _event) -> None:
        self._hovered = False
        self._redraw()

    def _on_wheel(self, event) -> None:
        step = 4 if event.delta > 0 else -4
        self._nudge(step)

    def _nudge(self, delta: int) -> None:
        new_val = max(0, min(100, self._value + delta))
        if new_val != self._value:
            self._value = new_val
            self._redraw()
            if self._on_change:
                self._on_change(new_val)

    def _apply_from_x(self, x: float) -> None:
        new_val = self._x_to_value(x)
        if new_val != self._value:
            self._value = new_val
            self._redraw()
            if self._on_change:
                self._on_change(new_val)

    def _redraw(self) -> None:
        self.delete("all")
        w = self.winfo_width()
        h = self.winfo_height()
        if w < 20 or h < 10:
            return

        pad = 8
        cy = h / 2
        x0 = pad
        x1 = w - pad
        usable = max(1, x1 - x0)
        ratio = self._value / 100.0
        kx = x0 + usable * ratio

        # 1. Trilha base (não preenchida)
        self.create_line(
            x0, cy, x1, cy,
            fill=TRACK_MUTED if self._muted else TRACK_UNFILLED,
            width=3,
            capstyle=tk.ROUND,
        )

        # 2. Trilha preenchida (volume atual)
        if ratio > 0:
            fill_col = THUMB_MUTED if self._muted else self._accent
            self.create_line(
                x0, cy, kx, cy,
                fill=fill_col,
                width=3,
                capstyle=tk.ROUND,
            )

        # 3. Medidor de áudio ao vivo sobreposto na própria trilha (branco estilo EarTrumpet!)
        if not self._muted and self._peak > 0.01 and ratio > 0:
            peak_end = x0 + usable * min(ratio, self._peak * ratio)
            if peak_end > x0 + 2:
                self.create_line(
                    x0, cy, peak_end, cy,
                    fill=self._peak_color,
                    width=3,
                    capstyle=tk.ROUND,
                )

        # 4. Thumb em pílula vertical (idêntico ao EarTrumpet)
        pill_w = 7 if (self._hovered or self._dragging) else 6
        pill_h = 18 if (self._hovered or self._dragging) else 16
        thumb_col = (
            THUMB_MUTED
            if self._muted
            else (ACCENT_PURPLE_HOVER if (self._hovered or self._dragging) else self._accent)
        )
        self._draw_pill(kx, cy, pill_w, pill_h, thumb_col)

    def _draw_pill(self, cx: float, cy: float, w: float, h: float, color: str) -> None:
        r = w / 2
        top = cy - h / 2
        bot = cy + h / 2
        # Caps superior e inferior + corpo central (pílula suave em Canvas)
        self.create_oval(cx - r, top, cx + r, top + w, fill=color, outline="")
        self.create_oval(cx - r, bot - w, cx + r, bot, fill=color, outline="")
        self.create_rectangle(cx - r, top + r, cx + r, bot - r, fill=color, outline="")


# ----------------------------------------------------------------------
# Gerador de ícones nítidos em alta resolução (2x supersampling com Pillow)
# ----------------------------------------------------------------------
_ICON_CACHE: Dict[str, ctk.CTkImage] = {}

APP_BRAND_COLORS = {
    "spotify": ("#1DB954", "S"),
    "chrome": ("#4285F4", "C"),
    "msedge": ("#0078D7", "E"),
    "edge": ("#0078D7", "E"),
    "firefox": ("#FF7139", "F"),
    "discord": ("#5865F2", "D"),
    "teams": ("#6264A7", "T"),
    "ms-teams": ("#6264A7", "T"),
    "vlc": ("#FF8800", "V"),
    "steam": ("#1B2838", "S"),
    "obs64": ("#302E31", "O"),
    "opera": ("#FA1E4E", "O"),
    "brave": ("#FB542B", "B"),
    "whatsapp": ("#25D366", "W"),
    "telegram": ("#26A5E4", "T"),
}


def get_speaker_icon(muted: bool = False, size: int = 24) -> ctk.CTkImage:
    key = f"speaker_{muted}_{size}"
    if key in _ICON_CACHE:
        return _ICON_CACHE[key]

    s = size * 2  # supersampling 2x
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    col = (145, 138, 170, 230) if muted else (245, 244, 252, 255)

    # Corpo do alto-falante
    d.polygon(
        [
            (s * 0.14, s * 0.38),
            (s * 0.32, s * 0.38),
            (s * 0.52, s * 0.20),
            (s * 0.52, s * 0.80),
            (s * 0.32, s * 0.62),
            (s * 0.14, s * 0.62),
        ],
        outline=col,
        width=3,
    )

    if muted:
        d.line([(s * 0.64, s * 0.36), (s * 0.86, s * 0.64)], fill=(239, 68, 68, 255), width=4)
        d.line([(s * 0.86, s * 0.36), (s * 0.64, s * 0.64)], fill=(239, 68, 68, 255), width=4)
    else:
        d.arc([s * 0.50, s * 0.32, s * 0.72, s * 0.68], start=-50, end=50, fill=col, width=3)
        d.arc([s * 0.54, s * 0.20, s * 0.86, s * 0.80], start=-50, end=50, fill=col, width=3)

    img = img.resize((size, size), Image.Resampling.LANCZOS)
    ctk_img = ctk.CTkImage(light_image=img, dark_image=img, size=(size, size))
    _ICON_CACHE[key] = ctk_img
    return ctk_img


def get_mic_icon(muted: bool = False, size: int = 22) -> ctk.CTkImage:
    key = f"mic_{muted}_{size}"
    if key in _ICON_CACHE:
        return _ICON_CACHE[key]

    s = size * 2
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    col = (145, 138, 170, 220) if muted else (245, 244, 252, 255)

    # Cápsula do microfone
    d.rounded_rectangle(
        [s * 0.36, s * 0.14, s * 0.64, s * 0.58],
        radius=s * 0.14,
        outline=col,
        width=3,
    )
    # Suporte em U + haste
    d.arc([s * 0.24, s * 0.30, s * 0.76, s * 0.72], start=0, end=180, fill=col, width=3)
    d.line([(s * 0.50, s * 0.72), (s * 0.50, s * 0.86)], fill=col, width=3)
    d.line([(s * 0.34, s * 0.86), (s * 0.66, s * 0.86)], fill=col, width=3)

    if muted:
        d.line([(s * 0.18, s * 0.18), (s * 0.82, s * 0.82)], fill=(239, 68, 68, 255), width=4)

    img = img.resize((size, size), Image.Resampling.LANCZOS)
    ctk_img = ctk.CTkImage(light_image=img, dark_image=img, size=(size, size))
    _ICON_CACHE[key] = ctk_img
    return ctk_img


def get_app_badge_icon(
    app_id: str,
    display_name: str,
    muted: bool = False,
    size: int = 24,
) -> ctk.CTkImage:
    if app_id == "__system_sounds__":
        return get_speaker_icon(muted=muted, size=size)

    key = f"app_{app_id}_{muted}_{size}"
    if key in _ICON_CACHE:
        return _ICON_CACHE[key]

    clean_key = app_id.replace(".exe", "").lower()
    hex_color, letter = APP_BRAND_COLORS.get(
        clean_key,
        ("#6D4AFF", (display_name[:1] or "A").upper()),
    )

    s = size * 2
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    if muted:
        fill = (68, 62, 92, 220)
        text_col = (160, 155, 180, 230)
    else:
        r = int(hex_color[1:3], 16)
        g = int(hex_color[3:5], 16)
        b = int(hex_color[5:7], 16)
        fill = (r, g, b, 245)
        text_col = (255, 255, 255, 255)

    d.ellipse([3, 3, s - 3, s - 3], fill=fill)

    try:
        font = ImageFont.truetype("segoeui.ttf", int(s * 0.50))
    except Exception:
        try:
            font = ImageFont.truetype("DejaVuSans-Bold.ttf", int(s * 0.48))
        except Exception:
            font = ImageFont.load_default()

    bbox = d.textbbox((0, 0), letter, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    d.text(((s - tw) / 2, (s - th) / 2 - bbox[1] * 0.5), letter, fill=text_col, font=font)

    if muted:
        d.line([(s * 0.22, s * 0.22), (s * 0.78, s * 0.78)], fill=(239, 68, 68, 255), width=4)

    img = img.resize((size, size), Image.Resampling.LANCZOS)
    ctk_img = ctk.CTkImage(light_image=img, dark_image=img, size=(size, size))
    _ICON_CACHE[key] = ctk_img
    return ctk_img
