"""Widgets minimalistas fiéis ao Windows 11 / EarTrumpet + ícones reais de aplicativos."""

from __future__ import annotations

import tkinter as tk
from typing import Callable, Dict

import customtkinter as ctk
from PIL import Image, ImageDraw, ImageEnhance, ImageFont

from mixers.win_icons import extract_exe_icon_pil

# Paleta refinada e sutil (estilo vidro fosco escuro do Windows 11)
HEADER_BAND = "#271F40"
MICS_BAND = "#271F40"
LIST_BAND = "#161420"
DRAWER_BAND = "#1B1729"
PANEL_BORDER = "#3B3354"
ACCENT_PURPLE = "#8B5CF6"
ACCENT_PURPLE_HOVER = "#A78BFA"
TRACK_UNFILLED = "#423B59"
TRACK_MUTED = "#353048"
THUMB_MUTED = "#655E7D"
PEAK_WHITE = "#FFFFFF"
TEXT_PRIMARY = "#F3F2F8"
TEXT_MUTED = "#7F7A94"


class HoverTooltip:
    """Tooltip discreto estilo Windows 11 ao passar o mouse sobre o ícone do aplicativo."""

    def __init__(self, widget, text: str) -> None:
        self._widget = widget
        self._text = text
        self._tip: tk.Toplevel | None = None
        self._after_id: str | None = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def update_text(self, text: str) -> None:
        self._text = text

    def _schedule(self, _event=None) -> None:
        self._cancel()
        self._after_id = self._widget.after(350, self._show)

    def _cancel(self) -> None:
        if self._after_id:
            try:
                self._widget.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None

    def _show(self) -> None:
        if not self._text or self._tip is not None:
            return
        try:
            x = self._widget.winfo_rootx() + 30
            y = self._widget.winfo_rooty() - 4
            tip = tk.Toplevel(self._widget)
            tip.wm_overrideredirect(True)
            tip.attributes("-topmost", True)
            tip.configure(bg=PANEL_BORDER)
            lbl = tk.Label(
                tip,
                text=self._text,
                bg="#1E1A2E",
                fg=TEXT_PRIMARY,
                font=("Segoe UI", 9),
                padx=8,
                pady=3,
            )
            lbl.pack(padx=1, pady=1)
            tip.wm_geometry(f"+{x}+{y}")
            self._tip = tip
        except Exception:
            self._tip = None

    def _hide(self, _event=None) -> None:
        self._cancel()
        if self._tip is not None:
            try:
                self._tip.destroy()
            except Exception:
                pass
            self._tip = None


class EarTrumpetSlider(tk.Canvas):
    """
    Slider ultrafino estilo EarTrumpet (Windows 11):
    - Trilha delicada de 2px;
    - Barra branca de nível de áudio ao vivo sobreposta na própria trilha;
    - Pílula vertical slim (4x15px);
    - Arraste suave + scroll do mouse.
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
        height: int = 28,
    ) -> None:
        super().__init__(
            master,
            height=height,
            bg=bg_color,
            highlightthickness=0,
            bd=0,
            cursor="hand2",
        )
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
        pad = 6
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
        self._nudge(4 if event.delta > 0 else -4)

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

        pad = 6
        cy = h / 2
        x0 = pad
        x1 = w - pad
        usable = max(1, x1 - x0)
        ratio = self._value / 100.0
        kx = x0 + usable * ratio

        # 1. Trilha base fina (2px)
        self.create_line(
            x0, cy, x1, cy,
            fill=TRACK_MUTED if self._muted else TRACK_UNFILLED,
            width=2,
            capstyle=tk.ROUND,
        )

        # 2. Trilha preenchida (2px)
        if ratio > 0:
            fill_col = THUMB_MUTED if self._muted else self._accent
            self.create_line(
                x0, cy, kx, cy,
                fill=fill_col,
                width=2,
                capstyle=tk.ROUND,
            )

        # 3. Medidor branco de áudio ao vivo sobreposto na trilha (exatamente como na foto!)
        if not self._muted and self._peak > 0.01 and ratio > 0:
            peak_end = x0 + usable * min(ratio, self._peak * ratio)
            if peak_end > x0 + 2:
                self.create_line(
                    x0, cy, peak_end, cy,
                    fill=self._peak_color,
                    width=2,
                    capstyle=tk.ROUND,
                )

        # 4. Pílula vertical bem delicada e slim (4x15px)
        pill_w = 5 if (self._hovered or self._dragging) else 4
        pill_h = 17 if (self._hovered or self._dragging) else 15
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
        self.create_oval(cx - r, top, cx + r, top + w, fill=color, outline="")
        self.create_oval(cx - r, bot - w, cx + r, bot, fill=color, outline="")
        self.create_rectangle(cx - r, top + r, cx + r, bot - r, fill=color, outline="")


# ----------------------------------------------------------------------
# Ícones refinados (traço fino Fluent + ícones reais .exe do Windows)
# ----------------------------------------------------------------------
_ICON_CACHE: Dict[str, ctk.CTkImage] = {}


def get_speaker_icon(muted: bool = False, size: int = 22) -> ctk.CTkImage:
    key = f"speaker_thin_{muted}_{size}"
    if key in _ICON_CACHE:
        return _ICON_CACHE[key]

    s = size * 3  # supersampling 3x para traço superfino e nítido
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    col = (135, 130, 155, 220) if muted else (240, 239, 246, 255)
    lw = 3

    d.polygon(
        [
            (s * 0.14, s * 0.39),
            (s * 0.30, s * 0.39),
            (s * 0.49, s * 0.22),
            (s * 0.49, s * 0.78),
            (s * 0.30, s * 0.61),
            (s * 0.14, s * 0.61),
        ],
        outline=col,
        width=lw,
    )

    if muted:
        d.line([(s * 0.62, s * 0.38), (s * 0.84, s * 0.62)], fill=col, width=lw)
        d.line([(s * 0.84, s * 0.38), (s * 0.62, s * 0.62)], fill=col, width=lw)
    else:
        d.arc([s * 0.48, s * 0.35, s * 0.66, s * 0.65], start=-52, end=52, fill=col, width=lw)
        d.arc([s * 0.51, s * 0.25, s * 0.77, s * 0.75], start=-52, end=52, fill=col, width=lw)
        d.arc([s * 0.54, s * 0.15, s * 0.88, s * 0.85], start=-52, end=52, fill=col, width=lw)

    img = img.resize((size, size), Image.Resampling.LANCZOS)
    ctk_img = ctk.CTkImage(light_image=img, dark_image=img, size=(size, size))
    _ICON_CACHE[key] = ctk_img
    return ctk_img


def get_mic_icon(muted: bool = False, size: int = 20) -> ctk.CTkImage:
    key = f"mic_thin_{muted}_{size}"
    if key in _ICON_CACHE:
        return _ICON_CACHE[key]

    s = size * 3
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    col = (135, 130, 155, 220) if muted else (240, 239, 246, 255)
    lw = 3

    d.rounded_rectangle(
        [s * 0.37, s * 0.15, s * 0.63, s * 0.56],
        radius=s * 0.13,
        outline=col,
        width=lw,
    )
    d.arc([s * 0.25, s * 0.30, s * 0.75, s * 0.70], start=0, end=180, fill=col, width=lw)
    d.line([(s * 0.50, s * 0.70), (s * 0.50, s * 0.85)], fill=col, width=lw)
    d.line([(s * 0.35, s * 0.85), (s * 0.65, s * 0.85)], fill=col, width=lw)

    if muted:
        d.line([(s * 0.20, s * 0.20), (s * 0.80, s * 0.80)], fill=col, width=lw + 1)

    img = img.resize((size, size), Image.Resampling.LANCZOS)
    ctk_img = ctk.CTkImage(light_image=img, dark_image=img, size=(size, size))
    _ICON_CACHE[key] = ctk_img
    return ctk_img


def get_app_icon(
    app_id: str,
    display_name: str,
    exe_path: str | None = None,
    muted: bool = False,
    size: int = 22,
) -> ctk.CTkImage:
    """Usa o ícone REAL do executável .exe no Windows; cai em um ícone sutil caso indisponível."""
    if app_id == "__system_sounds__":
        return get_speaker_icon(muted=muted, size=size)

    key = f"real_app_{app_id}_{exe_path or ''}_{muted}_{size}"
    if key in _ICON_CACHE:
        return _ICON_CACHE[key]

    pil_img = extract_exe_icon_pil(exe_path, size=size)
    if pil_img is not None:
        img = pil_img.copy()
        if muted:
            # Escurece levemente quando mutado (exatamente como no EarTrumpet)
            alpha = img.getchannel("A")
            img = ImageEnhance.Brightness(img).enhance(0.55)
            img = ImageEnhance.Color(img).enhance(0.35)
            img.putalpha(alpha)
    else:
        # Fallback discreto em vidro fosco com inicial fina (nada chamativo)
        s = size * 3
        img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        bg = (45, 40, 66, 210) if muted else (60, 52, 88, 235)
        fg = (135, 130, 155, 220) if muted else (238, 236, 246, 255)
        d.rounded_rectangle([3, 3, s - 3, s - 3], radius=s * 0.26, fill=bg)
        letter = (display_name[:1] or "A").upper()
        try:
            font = ImageFont.truetype("segoeui.ttf", int(s * 0.48))
        except Exception:
            try:
                font = ImageFont.truetype("DejaVuSans.ttf", int(s * 0.46))
            except Exception:
                font = ImageFont.load_default()
        bbox = d.textbbox((0, 0), letter, font=font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        d.text(((s - tw) / 2, (s - th) / 2 - bbox[1] * 0.5), letter, fill=fg, font=font)
        img = img.resize((size, size), Image.Resampling.LANCZOS)

    ctk_img = ctk.CTkImage(light_image=img, dark_image=img, size=(size, size))
    _ICON_CACHE[key] = ctk_img
    return ctk_img
