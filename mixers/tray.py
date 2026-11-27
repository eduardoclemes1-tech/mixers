"""Ícone e menu na bandeja do sistema (System Tray) para rodar em segundo plano."""

from __future__ import annotations

import threading
from typing import Callable

from PIL import Image, ImageDraw
import pystray


def create_tray_icon_image(size: int = 64) -> Image.Image:
    """Desenha um ícone minimalista de mixer (3 barras de equalizador)."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Fundo circular escuro translúcido
    margin = 3
    draw.rounded_rectangle(
        [margin, margin, size - margin, size - margin],
        radius=16,
        fill=(18, 22, 32, 245),
        outline=(56, 189, 248, 220),
        width=2,
    )

    # Três trilhas + knobs de slider
    cols = [size * 0.28, size * 0.50, size * 0.72]
    knobs = [0.38, 0.62, 0.45]
    top_y = size * 0.22
    bot_y = size * 0.78

    for x, knob_ratio in zip(cols, knobs):
        draw.line([(x, top_y), (x, bot_y)], fill=(75, 85, 105, 255), width=4)
        ky = top_y + (bot_y - top_y) * knob_ratio
        draw.line([(x, ky), (x, bot_y)], fill=(56, 189, 248, 255), width=4)
        r = 5
        draw.ellipse([x - r, ky - r, x + r, ky + r], fill=(240, 248, 255, 255))

    return img


class TrayController:
    """Controla o ícone do Mixers na bandeja do sistema."""

    def __init__(
        self,
        on_toggle_window: Callable[[], None],
        on_focus_mode: Callable[[], None],
        on_full_volume: Callable[[], None],
        on_mute_apps: Callable[[], None],
        on_toggle_autostart: Callable[[], None],
        is_autostart: Callable[[], bool],
        on_check_updates: Callable[[], None],
        on_quit: Callable[[], None],
    ) -> None:
        self._on_toggle_window = on_toggle_window
        self._on_focus_mode = on_focus_mode
        self._on_full_volume = on_full_volume
        self._on_mute_apps = on_mute_apps
        self._on_toggle_autostart = on_toggle_autostart
        self._is_autostart = is_autostart
        self._on_check_updates = on_check_updates
        self._on_quit = on_quit
        self._icon: pystray.Icon | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        menu = pystray.Menu(
            pystray.MenuItem("Abrir / Ocultar Mixers", self._wrap(self._on_toggle_window), default=True),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("100% Tudo", self._wrap(self._on_full_volume)),
            pystray.MenuItem("Modo Foco (30%)", self._wrap(self._on_focus_mode)),
            pystray.MenuItem("Mutar Apps", self._wrap(self._on_mute_apps)),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "Iniciar com o Windows",
                self._wrap(self._on_toggle_autostart),
                checked=lambda _item: self._is_autostart(),
            ),
            pystray.MenuItem("Verificar atualizações", self._wrap(self._on_check_updates)),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Sair", self._wrap(self._on_quit)),
        )

        self._icon = pystray.Icon(
            name="Mixers",
            icon=create_tray_icon_image(),
            title="Mixers — Controle de Som por App",
            menu=menu,
        )
        self._thread = threading.Thread(target=self._icon.run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._icon is not None:
            try:
                self._icon.stop()
            except Exception:
                pass
            self._icon = None

    @staticmethod
    def _wrap(callback: Callable[[], None]):
        def _handler(_icon, _item):
            callback()

        return _handler
