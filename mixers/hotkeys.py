"""Atalho global nativo do Windows via RegisterHotKey (0% CPU, sem permissões admin)."""

from __future__ import annotations

import sys
import threading
from typing import Callable

# Flags Win32 RegisterHotKey
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000

WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
HOTKEY_ID = 1

MODIFIER_MAP = {
    "ctrl": MOD_CONTROL,
    "control": MOD_CONTROL,
    "alt": MOD_ALT,
    "shift": MOD_SHIFT,
    "win": MOD_WIN,
    "super": MOD_WIN,
}

SPECIAL_VK_MAP = {
    "space": 0x20,
    "tab": 0x09,
    "enter": 0x0D,
    "return": 0x0D,
    "backspace": 0x08,
    "delete": 0x2E,
    "insert": 0x2D,
    "home": 0x24,
    "end": 0x23,
    "pageup": 0x21,
    "pagedown": 0x22,
    "up": 0x26,
    "down": 0x28,
    "left": 0x25,
    "right": 0x27,
    "plus": 0xBB,
    "minus": 0xBD,
}


def parse_hotkey(hotkey_str: str) -> tuple[int, int] | None:
    """
    Converte strings como 'Ctrl+Alt+M' ou 'Ctrl+Shift+F9' em (modifiers, vk_code).
    Retorna None se o formato for inválido ou sem tecla principal.
    """
    if not hotkey_str or not hotkey_str.strip():
        return None

    parts = [p.strip().lower() for p in hotkey_str.split("+") if p.strip()]
    if not parts:
        return None

    modifiers = 0
    vk_code: int | None = None

    for part in parts:
        if part in MODIFIER_MAP:
            modifiers |= MODIFIER_MAP[part]
        elif len(part) == 1 and part.isalnum():
            vk_code = ord(part.upper())
        elif part.startswith("f") and part[1:].isdigit():
            f_num = int(part[1:])
            if 1 <= f_num <= 24:
                vk_code = 0x6F + f_num  # VK_F1 = 0x70
        elif part in SPECIAL_VK_MAP:
            vk_code = SPECIAL_VK_MAP[part]
        else:
            return None

    # Exige ao menos um modificador (ou tecla de função F1-F24) + tecla principal
    if vk_code is None:
        return None
    if modifiers == 0 and not (0x70 <= vk_code <= 0x87):
        return None

    return modifiers | MOD_NOREPEAT, vk_code


def normalize_hotkey_label(hotkey_str: str) -> str:
    """Padroniza a exibição do atalho (ex: 'ctrl+alt+m' -> 'Ctrl+Alt+M')."""
    parts = [p.strip() for p in hotkey_str.split("+") if p.strip()]
    ordered_mods = []
    mod_names = {"ctrl": "Ctrl", "control": "Ctrl", "alt": "Alt", "shift": "Shift", "win": "Win"}
    key_part = ""
    for p in parts:
        low = p.lower()
        if low in mod_names:
            label = mod_names[low]
            if label not in ordered_mods:
                ordered_mods.append(label)
        else:
            key_part = p.upper() if len(p) == 1 or (low.startswith("f") and low[1:].isdigit()) else p.capitalize()
    return "+".join(ordered_mods + ([key_part] if key_part else []))


class GlobalHotkeyManager:
    """Registra e escuta um atalho global no Windows em uma thread dedicada."""

    def __init__(self, on_trigger: Callable[[], None]) -> None:
        self._on_trigger = on_trigger
        self._thread: threading.Thread | None = None
        self._win_thread_id: int | None = None
        self._current_hotkey: str = ""
        self._registered_ok = threading.Event()
        self._last_error: str | None = None

    @property
    def current_hotkey(self) -> str:
        return self._current_hotkey

    def register(self, hotkey_str: str) -> tuple[bool, str]:
        """Registra (ou substitui) o atalho global. Retorna (sucesso, mensagem)."""
        self.unregister()

        clean = hotkey_str.strip()
        if not clean:
            self._current_hotkey = ""
            return True, "Atalho desativado."

        parsed = parse_hotkey(clean)
        if parsed is None:
            return False, "Atalho inválido. Use ex: Ctrl+Alt+M."

        normalized = normalize_hotkey_label(clean)
        self._current_hotkey = normalized

        if sys.platform != "win32":
            return True, f"Atalho salvo: {normalized}"

        modifiers, vk_code = parsed
        self._registered_ok.clear()
        self._last_error = None

        self._thread = threading.Thread(
            target=self._win32_loop,
            args=(modifiers, vk_code),
            daemon=True,
        )
        self._thread.start()
        self._registered_ok.wait(timeout=1.5)

        if self._last_error:
            self._current_hotkey = ""
            return False, self._last_error
        return True, f"Atalho ativo: {normalized}"

    def unregister(self) -> None:
        if sys.platform == "win32" and self._win_thread_id:
            try:
                import ctypes
                from ctypes import c_uint, c_ulong, c_void_p

                user32 = ctypes.windll.user32
                user32.PostThreadMessageW.argtypes = [c_ulong, c_uint, c_void_p, c_void_p]
                user32.PostThreadMessageW(c_ulong(self._win_thread_id), c_uint(WM_QUIT), None, None)
            except Exception:
                pass
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        self._thread = None
        self._win_thread_id = None

    def _win32_loop(self, modifiers: int, vk_code: int) -> None:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        user32.RegisterHotKey.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_uint, ctypes.c_uint]
        user32.UnregisterHotKey.argtypes = [ctypes.c_void_p, ctypes.c_int]
        self._win_thread_id = kernel32.GetCurrentThreadId()

        if not user32.RegisterHotKey(None, HOTKEY_ID, modifiers, vk_code):
            self._last_error = "Atalho já está em uso por outro programa."
            self._registered_ok.set()
            return

        self._registered_ok.set()
        msg = wintypes.MSG()
        try:
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message == WM_HOTKEY and msg.wParam == HOTKEY_ID:
                    try:
                        self._on_trigger()
                    except Exception:
                        pass
        finally:
            try:
                user32.UnregisterHotKey(None, HOTKEY_ID)
            except Exception:
                pass
