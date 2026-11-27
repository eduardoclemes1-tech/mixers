"""Integrações nativas do Windows: vidro/cantos arredondados, posição e autostart."""

from __future__ import annotations

import os
import sys

APP_REG_NAME = "MixersAudioApp"
RUN_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"


def apply_windows_glass_style(hwnd: int) -> None:
    """Aplica cantos arredondados e modo escuro nativo do Windows 11 (quando suportado)."""
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
    except Exception:
        pass


def get_work_area(screen_w: int, screen_h: int) -> tuple[int, int, int, int]:
    """Retorna a área útil da tela (left, top, right, bottom) descontando a barra de tarefas."""
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes

            rect = wintypes.RECT()
            # SPI_GETWORKAREA = 0x0030
            if ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0):
                return rect.left, rect.top, rect.right, rect.bottom
        except Exception:
            pass
    return 0, 0, screen_w, screen_h - 48


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
