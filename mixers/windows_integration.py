"""Integrações nativas do Windows: cor de destaque do sistema, vidro Acrylic, DPI e autostart."""

from __future__ import annotations

import os
import sys

APP_REG_NAME = "MixersAudioApp"
RUN_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
DWM_KEY_PATH = r"Software\Microsoft\Windows\DWM"


def _clamp_byte(v: float) -> int:
    return max(0, min(255, int(round(v))))


def _rgb_to_hex(rgb: tuple[int, int, int]) -> str:
    return f"#{_clamp_byte(rgb[0]):02X}{_clamp_byte(rgb[1]):02X}{_clamp_byte(rgb[2]):02X}"


def _mix_rgb(
    base: tuple[int, int, int],
    tint: tuple[int, int, int],
    ratio: float,
) -> tuple[int, int, int]:
    return (
        _clamp_byte(base[0] * (1.0 - ratio) + tint[0] * ratio),
        _clamp_byte(base[1] * (1.0 - ratio) + tint[1] * ratio),
        _clamp_byte(base[2] * (1.0 - ratio) + tint[2] * ratio),
    )


def get_windows_accent_rgb() -> tuple[int, int, int]:
    """Lê a cor de destaque (Accent Color) configurada no Windows 10/11."""
    default_rgb = (139, 92, 246)  # Violeta Fluent padrão (fallback)
    if sys.platform != "win32":
        return default_rgb

    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, DWM_KEY_PATH, 0, winreg.KEY_READ) as key:
            # AccentColor no Windows é DWORD em formato 0xAABBGGRR
            try:
                val, _ = winreg.QueryValueEx(key, "AccentColor")
                r = val & 0xFF
                g = (val >> 8) & 0xFF
                b = (val >> 16) & 0xFF
                return (r, g, b)
            except FileNotFoundError:
                val, _ = winreg.QueryValueEx(key, "ColorizationColor")
                r = (val >> 16) & 0xFF
                g = (val >> 8) & 0xFF
                b = val & 0xFF
                return (r, g, b)
    except Exception:
        return default_rgb


def derive_theme_from_accent(accent_rgb: tuple[int, int, int]) -> dict[str, str]:
    """Gera uma paleta Fluent Windows 11 completa e harmônica a partir da cor do sistema."""
    r, g, b = accent_rgb
    # Garante legibilidade do slider mesmo se o usuário escolher uma cor muito escura
    luminance = 0.299 * r + 0.587 * g + 0.114 * b
    if luminance < 95:
        accent_rgb = _mix_rgb((r, g, b), (255, 255, 255), 0.30)

    accent_hover = _mix_rgb(accent_rgb, (255, 255, 255), 0.22)
    header_band = _mix_rgb((18, 18, 24), accent_rgb, 0.24)
    list_band = _mix_rgb((16, 16, 22), accent_rgb, 0.06)
    drawer_band = _mix_rgb((20, 20, 28), accent_rgb, 0.10)
    panel_border = _mix_rgb((46, 46, 58), accent_rgb, 0.28)
    track_unfilled = _mix_rgb((56, 56, 70), accent_rgb, 0.16)
    track_muted = _mix_rgb((46, 46, 56), accent_rgb, 0.08)
    thumb_muted = _mix_rgb((96, 96, 112), accent_rgb, 0.12)
    pill_bg = _mix_rgb((34, 34, 46), accent_rgb, 0.18)
    pill_hover = _mix_rgb((48, 48, 64), accent_rgb, 0.28)
    header_hover = _mix_rgb(header_band, (255, 255, 255), 0.12)
    row_hover = _mix_rgb(list_band, (255, 255, 255), 0.08)
    badge_fg = _mix_rgb(accent_rgb, (255, 255, 255), 0.45)

    return {
        "accent": _rgb_to_hex(accent_rgb),
        "accent_hover": _rgb_to_hex(accent_hover),
        "header_band": _rgb_to_hex(header_band),
        "mics_band": _rgb_to_hex(header_band),
        "list_band": _rgb_to_hex(list_band),
        "drawer_band": _rgb_to_hex(drawer_band),
        "panel_border": _rgb_to_hex(panel_border),
        "track_unfilled": _rgb_to_hex(track_unfilled),
        "track_muted": _rgb_to_hex(track_muted),
        "thumb_muted": _rgb_to_hex(thumb_muted),
        "pill_bg": _rgb_to_hex(pill_bg),
        "pill_hover": _rgb_to_hex(pill_hover),
        "header_hover": _rgb_to_hex(header_hover),
        "row_hover": _rgb_to_hex(row_hover),
        "badge_fg": _rgb_to_hex(badge_fg),
        "text_primary": "#F4F4F8",
        "text_muted": "#8A889B",
    }


def apply_windows_glass_style(hwnd: int) -> None:
    """Aplica modo escuro, cantos arredondados e backdrop Acrylic nativo do Windows 11."""
    if sys.platform != "win32" or not hwnd:
        return

    try:
        import ctypes
        from ctypes import byref, c_int, sizeof

        dwmapi = ctypes.windll.dwmapi

        # Modo escuro na janela (DWMWA_USE_IMMERSIVE_DARK_MODE = 20)
        dark = c_int(1)
        dwmapi.DwmSetWindowAttribute(hwnd, 20, byref(dark), sizeof(dark))

        # Cantos arredondados no Windows 11 (DWMWA_WINDOW_CORNER_PREFERENCE = 33, DWMWCP_ROUND = 2)
        round_corners = c_int(2)
        dwmapi.DwmSetWindowAttribute(hwnd, 33, byref(round_corners), sizeof(round_corners))

        # Backdrop Acrylic nativo do Windows 11 (DWMWA_SYSTEMBACKDROP_TYPE = 38, DWMSBT_TRANSIENTWINDOW = 3)
        acrylic = c_int(3)
        dwmapi.DwmSetWindowAttribute(hwnd, 38, byref(acrylic), sizeof(acrylic))
    except Exception:
        pass


def get_work_area(screen_w: int, screen_h: int) -> tuple[int, int, int, int]:
    """Retorna a área útil da tela (left, top, right, bottom) descontando a barra de tarefas."""
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes

            rect = wintypes.RECT()
            if ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0):
                return rect.left, rect.top, rect.right, rect.bottom
        except Exception:
            pass
    return 0, 0, screen_w, screen_h - 48


def compute_bottom_right_position(
    win_w_px: int,
    win_h_px: int,
    work_area: tuple[int, int, int, int],
    margin: int = 12,
) -> tuple[int, int]:
    """Calcula (x, y) exatos no canto inferior direito acima da barra de tarefas."""
    left, top, right, bottom = work_area
    x = max(left + margin, right - win_w_px - margin)
    y = max(top + margin, bottom - win_h_px - margin)
    return int(x), int(y)


def _get_autostart_command() -> str:
    """Monta o comando para iniciar o Mixers minimizado junto com o Windows."""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" --minimized'

    main_script = os.path.abspath(sys.argv[0])
    python_exe = sys.executable
    if python_exe.lower().endswith("python.exe"):
        pythonw = python_exe[:-10] + "pythonw.exe"
        if os.path.exists(pythonw):
            python_exe = pythonw
    return f'"{python_exe}" "{main_script}" --minimized'


def is_autostart_enabled() -> bool:
    """Verifica se o Mixers está configurado para abrir com o Windows."""
    if sys.platform != "win32":
        return False
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0, winreg.KEY_READ) as key:
            winreg.QueryValueEx(key, APP_REG_NAME)
            return True
    except Exception:
        return False


def set_autostart(enabled: bool) -> bool:
    """Ativa ou desativa a inicialização automática com o Windows."""
    if sys.platform != "win32":
        return False
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0, winreg.KEY_SET_VALUE) as key:
            if enabled:
                winreg.SetValueEx(key, APP_REG_NAME, 0, winreg.REG_SZ, _get_autostart_command())
            else:
                try:
                    winreg.DeleteValue(key, APP_REG_NAME)
                except FileNotFoundError:
                    pass
        return True
    except Exception:
        return False
