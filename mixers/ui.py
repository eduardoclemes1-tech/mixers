"""Interface minimalista inspirada no EarTrumpet / Windows 11 Fluent Violet."""

from __future__ import annotations

import os
import sys
import threading
import time
from typing import Dict

import customtkinter as ctk

from mixers import __version__
from mixers.audio_backend import (
    AppAudioSession,
    AudioBackend,
    MicTestMonitor,
    MicrophoneDevice,
    classify_mic_quality,
)
from mixers.hotkeys import GlobalHotkeyManager, normalize_hotkey_label
from mixers.profiles import ProfileManager
from mixers.settings import SettingsManager
from mixers.tray import TrayController
from mixers.updater import UpdateInfo, check_for_update, download_and_apply_update
from mixers.widgets import (
    ACCENT_PURPLE,
    ACCENT_PURPLE_HOVER,
    EarTrumpetSlider,
    HEADER_BAND,
    LIST_BAND,
    MICS_BAND,
    PANEL_BORDER,
    PEAK_WHITE,
    TEXT_MUTED,
    TEXT_PRIMARY,
    get_app_badge_icon,
    get_mic_icon,
    get_speaker_icon,
)
from mixers.windows_integration import (
    apply_windows_glass_style,
    compute_bottom_right_position,
    get_work_area,
    is_autostart_enabled,
    set_autostart,
)

PILL_BG = "#2A2144"
PILL_HOVER = "#3A2E5C"
DANGER_BG = "#6E1D31"
DANGER_HOVER = "#8B263E"


class MixersApp(ctk.CTk):
    """Painel de áudio estilo EarTrumpet / Windows 11 no canto inferior direito."""

    WINDOW_WIDTH = 362
    MIN_HEIGHT = 210
    MAX_HEIGHT = 590
    SESSION_REFRESH_MS = 3000
    METER_REFRESH_MS = 140
    METER_EPSILON = 0.02

    def __init__(
        self,
        backend: AudioBackend,
        profile_manager: ProfileManager | None = None,
        settings_manager: SettingsManager | None = None,
        demo_mode: bool = False,
        start_minimized: bool = False,
        enable_tray: bool = True,
    ) -> None:
        super().__init__()

        self.backend = backend
        self.profile_manager = profile_manager or ProfileManager()
        self.settings = settings_manager or SettingsManager()
        self.demo_mode = demo_mode

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        # Preferências persistidas
        self._alpha = max(0.75, min(1.0, float(self.settings.get("alpha", 0.93))))
        self._mics_expanded = bool(self.settings.get("mics_expanded", True))
        saved_hotkey = str(self.settings.get("hotkey", "Ctrl+Alt+M"))

        self.title(f"Mixers v{__version__}")
        self.configure(fg_color=LIST_BAND)
        self.resizable(False, False)

        # Estado visual, animações e cache de desempenho
        self._pinned = False
        self._settings_open = False
        self._dialog_open = False
        self._recording_hotkey = False
        self._is_visible = not start_minimized
        self._anim_token = 0
        self._cur_height = 360
        self._target_pos: tuple[int, int] = (0, 0)

        self._session_timer_id: str | None = None
        self._meter_timer_id: str | None = None
        self._last_slider_ts: float = 0.0
        self._last_master_pct: int = -1
        self._last_master_muted: bool | None = None
        self._last_master_peak: float = -1.0
        self._last_app_pct: Dict[str, int] = {}
        self._last_app_peak: Dict[str, float] = {}
        self._last_mic_pct: Dict[str, int] = {}
        self._last_mic_peak: Dict[str, float] = {}
        self._last_mic_quality: Dict[str, str] = {}
        self._mic_monitor = MicTestMonitor()

        self._app_rows: Dict[str, dict] = {}
        self._current_sessions: Dict[str, AppAudioSession] = {}
        self._mic_rows: Dict[str, dict] = {}
        self._current_mics: Dict[str, MicrophoneDevice] = {}

        self._selected_profile = ctk.StringVar(value="Sem perfis salvos")
        self._autostart_var = ctk.BooleanVar(value=is_autostart_enabled())
        self._pending_update: UpdateInfo | None = None
        self._updating = False

        # Janela flutuante nativa do Windows (sem barra de título nem ícone na barra de tarefas)
        if sys.platform == "win32":
            self.overrideredirect(True)
            try:
                self.attributes("-toolwindow", True)
            except Exception:
                pass
        self.attributes("-topmost", True)
        try:
            self.attributes("-alpha", self._alpha)
        except Exception:
            pass

        self._build_layout()
        self._update_window_geometry()
        self._apply_native_window_effects()

        # Atalho global configurável pelo usuário
        self.hotkey_manager = GlobalHotkeyManager(
            on_trigger=lambda: self.after(0, self.toggle_visibility)
        )
        ok, msg = self.hotkey_manager.register(saved_hotkey)
        self._update_hotkey_badge(self.hotkey_manager.current_hotkey)
        if not ok and saved_hotkey:
            self._set_status(msg)

        # Eventos de teclado, foco e fechamento
        self.bind("<KeyPress>", self._on_global_key_press)
        self.bind("<FocusOut>", self._on_focus_out)
        self.protocol("WM_DELETE_WINDOW", self.hide_to_tray)

        # Bandeja do sistema (System Tray)
        self.tray: TrayController | None = None
        if enable_tray:
            try:
                self.tray = TrayController(
                    on_toggle_window=lambda: self.after(0, self.toggle_visibility),
                    on_focus_mode=lambda: self.after(0, self._preset_focus_mode),
                    on_full_volume=lambda: self.after(0, self._preset_full_volume),
                    on_mute_apps=lambda: self.after(0, self._preset_mute_all_apps),
                    on_toggle_autostart=lambda: self.after(0, self._toggle_autostart_from_tray),
                    is_autostart=is_autostart_enabled,
                    on_check_updates=lambda: self.after(0, lambda: self.check_updates_async(manual=True)),
                    on_quit=lambda: self.after(0, self.quit_app),
                )
                self.tray.start()
            except Exception:
                self.tray = None

        if start_minimized:
            self.withdraw()
        else:
            self.refresh_audio_state(force_rebuild=True)
            self._animate_open()
            self._start_live_loops()

        self.after(3000, lambda: self.check_updates_async(manual=False))

    # ------------------------------------------------------------------
    # Altura dinâmica compacta + posição fixa canto inferior direito
    # ------------------------------------------------------------------
    def _desired_height(self) -> int:
        # Faixa Master (~92px) + Apps (~48px cada) + Microfones
        h = 96
        if self._pending_update is not None:
            h += 38
        if self._settings_open:
            h += 210

        app_count = max(1, len(self._current_sessions))
        h += min(app_count, 5) * 48 + 14

        h += 40  # cabeçalho Microfones
        if self._mics_expanded:
            mic_count = max(1, len(self._current_mics))
            h += min(mic_count, 3) * 48 + 8

        return max(self.MIN_HEIGHT, min(self.MAX_HEIGHT, h))

    def _update_window_geometry(self, y_offset: int = 0) -> None:
        self._cur_height = self._desired_height()
        self.update_idletasks()
        try:
            scale = float(self._get_window_scaling())
        except Exception:
            scale = 1.0

        win_w_px = int(round(self.WINDOW_WIDTH * scale))
        win_h_px = int(round(self._cur_height * scale))
        work_area = get_work_area(self.winfo_screenwidth(), self.winfo_screenheight())
        x, y = compute_bottom_right_position(win_w_px, win_h_px, work_area, margin=12)
        self._target_pos = (x, y)
        self.geometry(f"{self.WINDOW_WIDTH}x{self._cur_height}+{x}+{y + y_offset}")

    def _animate_open(self) -> None:
        """Animação suave estilo Windows 11 (~120ms)."""
        self._anim_token += 1
        token = self._anim_token
        steps = 8
        slide_px = 14
        x, target_y = self._target_pos
        h = self._cur_height

        try:
            self.attributes("-alpha", 0.0)
        except Exception:
            return
        self.geometry(f"{self.WINDOW_WIDTH}x{h}+{x}+{target_y + slide_px}")

        def _step(i: int) -> None:
            if token != self._anim_token or not self._is_visible:
                return
            t = i / steps
            eased = 1.0 - (1.0 - t) ** 3
            cur_y = int(round(target_y + slide_px * (1.0 - eased)))
            cur_alpha = round(self._alpha * eased, 3)
            self.geometry(f"{self.WINDOW_WIDTH}x{h}+{x}+{cur_y}")
            try:
                self.attributes("-alpha", cur_alpha)
            except Exception:
                pass
            if i < steps:
                self.after(15, lambda: _step(i + 1))

        _step(1)

    def _animate_close(self) -> None:
        """Animação discreta ao recolher (~70ms)."""
        self._anim_token += 1
        token = self._anim_token
        steps = 5
        slide_px = 10
        x, target_y = self._target_pos
        h = self._cur_height

        def _step(i: int) -> None:
            if token != self._anim_token or self._is_visible:
                return
            t = i / steps
            cur_y = int(round(target_y + slide_px * t))
            cur_alpha = max(0.0, round(self._alpha * (1.0 - t), 3))
            self.geometry(f"{self.WINDOW_WIDTH}x{h}+{x}+{cur_y}")
            try:
                self.attributes("-alpha", cur_alpha)
            except Exception:
                pass
            if i < steps:
                self.after(14, lambda: _step(i + 1))
            else:
                self.withdraw()
                try:
                    self.attributes("-alpha", self._alpha)
                except Exception:
                    pass

        _step(1)

    def _apply_native_window_effects(self) -> None:
        if sys.platform != "win32":
            return
        try:
            self.update_idletasks()
            apply_windows_glass_style(self.winfo_id())
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Layout EarTrumpet / Windows 11 (2 tons de vidro escuro violeta)
    # ------------------------------------------------------------------
    def _build_layout(self) -> None:
        self.shell = ctk.CTkFrame(
            self,
            fg_color=LIST_BAND,
            border_color=PANEL_BORDER,
            border_width=1,
            corner_radius=12,
        )
        self.shell.pack(fill="both", expand=True)
        self.shell.grid_columnconfigure(0, weight=1)
        self.shell.grid_rowconfigure(3, weight=1)

        # Row 0: Faixa Master / Dispositivo de Saída (violeta translúcido, igual à referência!)
        master_band = ctk.CTkFrame(
            self.shell,
            fg_color=HEADER_BAND,
            corner_radius=10,
        )
        master_band.grid(row=0, column=0, padx=1, pady=(1, 0), sticky="ew")
        master_band.grid_columnconfigure(1, weight=1)

        # Linha 0 do Master: Nome do dispositivo + ícones discretos (⚙ e ⌄)
        top_row = ctk.CTkFrame(master_band, fg_color="transparent")
        top_row.grid(row=0, column=0, columnspan=3, padx=(14, 8), pady=(10, 4), sticky="ew")
        top_row.grid_columnconfigure(0, weight=1)

        self.device_lbl = ctk.CTkLabel(
            top_row,
            text=self._truncate(self.backend.get_output_device_name(), 34),
            font=ctk.CTkFont(family="Segoe UI", size=13, weight="normal"),
            text_color=TEXT_PRIMARY,
            anchor="w",
        )
        self.device_lbl.grid(row=0, column=0, sticky="w")

        self.settings_btn = ctk.CTkButton(
            top_row,
            text="⚙",
            width=26,
            height=24,
            corner_radius=6,
            font=ctk.CTkFont(size=13),
            fg_color="transparent",
            hover_color="#412F6E",
            text_color="#C9C1E0",
            command=self._toggle_settings_drawer,
        )
        self.settings_btn.grid(row=0, column=1, padx=(4, 2))

        ctk.CTkButton(
            top_row,
            text="⌄",
            width=26,
            height=24,
            corner_radius=6,
            font=ctk.CTkFont(size=15),
            fg_color="transparent",
            hover_color="#412F6E",
            text_color="#C9C1E0",
            command=self.hide_to_tray,
        ).grid(row=0, column=2)

        # Linha 1 do Master: [Ícone Alto-falante] [Slider EarTrumpet com barra branca] [100]
        self.master_mute_btn = ctk.CTkButton(
            master_band,
            text="",
            image=get_speaker_icon(muted=False, size=24),
            width=34,
            height=34,
            corner_radius=8,
            fg_color="transparent",
            hover_color="#412F6E",
            command=self._toggle_master_mute,
        )
        self.master_mute_btn.grid(row=1, column=0, padx=(10, 6), pady=(2, 12))

        self.master_slider = EarTrumpetSlider(
            master_band,
            bg_color=HEADER_BAND,
            value=100,
            muted=False,
            on_change=self._on_master_slider,
            height=30,
        )
        self.master_slider.grid(row=1, column=1, padx=4, pady=(2, 12), sticky="ew")

        self.master_pct_lbl = ctk.CTkLabel(
            master_band,
            text="100",
            width=36,
            anchor="e",
            font=ctk.CTkFont(family="Segoe UI", size=17, weight="normal"),
            text_color=TEXT_PRIMARY,
        )
        self.master_pct_lbl.grid(row=1, column=2, padx=(4, 14), pady=(2, 12))

        # Row 1: Banner de atualização disponível (oculto até haver versão nova)
        self.update_banner = ctk.CTkFrame(
            self.shell,
            fg_color="#231942",
            border_color=ACCENT_PURPLE,
            border_width=1,
            corner_radius=8,
        )
        self.update_banner.grid_columnconfigure(0, weight=1)

        self.update_banner_lbl = ctk.CTkLabel(
            self.update_banner,
            text="Nova versão disponível!",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            text_color=TEXT_PRIMARY,
            anchor="w",
        )
        self.update_banner_lbl.grid(row=0, column=0, padx=10, pady=6, sticky="w")

        self.update_now_btn = ctk.CTkButton(
            self.update_banner,
            text="Atualizar",
            width=74,
            height=22,
            corner_radius=6,
            font=ctk.CTkFont(size=10, weight="bold"),
            fg_color=ACCENT_PURPLE,
            hover_color=ACCENT_PURPLE_HOVER,
            text_color="#FFFFFF",
            command=self._start_update_download,
        )
        self.update_now_btn.grid(row=0, column=1, padx=(4, 8), pady=6)

        # Row 2: Gaveta de Ajustes (oculta no uso normal — abre ao clicar em ⚙)
        self.settings_drawer = ctk.CTkFrame(
            self.shell,
            fg_color="#1F1933",
            corner_radius=0,
        )
        self.settings_drawer.grid_columnconfigure(1, weight=1)

        # Transparência
        ctk.CTkLabel(
            self.settings_drawer,
            text="Opacidade",
            font=ctk.CTkFont(size=11),
            text_color=TEXT_MUTED,
        ).grid(row=0, column=0, padx=(14, 6), pady=(10, 4), sticky="w")

        self.alpha_slider = EarTrumpetSlider(
            self.settings_drawer,
            bg_color="#1F1933",
            value=int(round(self._alpha * 100)),
            on_change=self._on_alpha_change,
            height=22,
        )
        self.alpha_slider.grid(row=0, column=1, padx=4, pady=(10, 4), sticky="ew")

        self.alpha_lbl = ctk.CTkLabel(
            self.settings_drawer,
            text=f"{int(round(self._alpha * 100))}%",
            width=36,
            font=ctk.CTkFont(size=11),
            text_color=TEXT_PRIMARY,
        )
        self.alpha_lbl.grid(row=0, column=2, padx=(4, 12), pady=(10, 4))

        # Atalho global
        hk_row = ctk.CTkFrame(self.settings_drawer, fg_color="transparent")
        hk_row.grid(row=1, column=0, columnspan=3, padx=12, pady=(2, 6), sticky="ew")

        ctk.CTkLabel(
            hk_row,
            text="Atalho:",
            font=ctk.CTkFont(size=11),
            text_color=TEXT_MUTED,
        ).pack(side="left", padx=(2, 6))

        self.hotkey_badge = ctk.CTkLabel(
            hk_row,
            text="Ctrl+Alt+M",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#C4B5FD",
            fg_color=LIST_BAND,
            corner_radius=6,
            padx=8,
            pady=2,
        )
        self.hotkey_badge.pack(side="left")

        self.record_hotkey_btn = ctk.CTkButton(
            hk_row,
            text="Gravar",
            width=58,
            height=22,
            corner_radius=6,
            font=ctk.CTkFont(size=10, weight="bold"),
            fg_color=PILL_BG,
            hover_color=PILL_HOVER,
            command=self._toggle_record_hotkey,
        )
        self.record_hotkey_btn.pack(side="right", padx=(4, 0))

        ctk.CTkButton(
            hk_row,
            text="Limpar",
            width=48,
            height=22,
            corner_radius=6,
            font=ctk.CTkFont(size=10),
            fg_color="transparent",
            hover_color=DANGER_BG,
            text_color=TEXT_MUTED,
            command=self._clear_hotkey,
        ).pack(side="right")

        # Presets rápidos + Fixar
        quick_row = ctk.CTkFrame(self.settings_drawer, fg_color="transparent")
        quick_row.grid(row=2, column=0, columnspan=3, padx=12, pady=(0, 6), sticky="ew")

        ctk.CTkButton(
            quick_row,
            text="100% Tudo",
            width=72,
            height=22,
            corner_radius=6,
            font=ctk.CTkFont(size=10),
            fg_color=PILL_BG,
            hover_color=PILL_HOVER,
            command=self._preset_full_volume,
        ).pack(side="left", padx=(0, 4))

        ctk.CTkButton(
            quick_row,
            text="Foco 30%",
            width=66,
            height=22,
            corner_radius=6,
            font=ctk.CTkFont(size=10),
            fg_color=PILL_BG,
            hover_color=PILL_HOVER,
            command=self._preset_focus_mode,
        ).pack(side="left", padx=(0, 4))

        ctk.CTkButton(
            quick_row,
            text="Mutar Apps",
            width=72,
            height=22,
            corner_radius=6,
            font=ctk.CTkFont(size=10),
            fg_color=DANGER_BG,
            hover_color=DANGER_HOVER,
            command=self._preset_mute_all_apps,
        ).pack(side="left", padx=(0, 4))

        self.pin_btn = ctk.CTkButton(
            quick_row,
            text="Fixar",
            width=48,
            height=22,
            corner_radius=6,
            font=ctk.CTkFont(size=10),
            fg_color=PILL_BG,
            hover_color=PILL_HOVER,
            text_color=TEXT_MUTED,
            command=self._toggle_pin,
        )
        self.pin_btn.pack(side="right")

        # Perfis
        prof_row = ctk.CTkFrame(self.settings_drawer, fg_color="transparent")
        prof_row.grid(row=3, column=0, columnspan=3, padx=12, pady=(0, 6), sticky="ew")

        self.profile_menu = ctk.CTkOptionMenu(
            prof_row,
            variable=self._selected_profile,
            values=self._get_profile_options(),
            width=142,
            height=23,
            font=ctk.CTkFont(size=10),
            fg_color=LIST_BAND,
            button_color=PILL_BG,
            button_hover_color=ACCENT_PURPLE,
        )
        self.profile_menu.pack(side="left", padx=(0, 4))

        ctk.CTkButton(
            prof_row,
            text="Aplicar",
            width=50,
            height=23,
            corner_radius=6,
            font=ctk.CTkFont(size=10, weight="bold"),
            fg_color=ACCENT_PURPLE,
            hover_color=ACCENT_PURPLE_HOVER,
            command=self._apply_selected_profile,
        ).pack(side="left", padx=(0, 4))

        ctk.CTkButton(
            prof_row,
            text="Salvar",
            width=46,
            height=23,
            corner_radius=6,
            font=ctk.CTkFont(size=10),
            fg_color=PILL_BG,
            hover_color=PILL_HOVER,
            command=self._save_profile_dialog,
        ).pack(side="left", padx=(0, 4))

        ctk.CTkButton(
            prof_row,
            text="X",
            width=24,
            height=23,
            corner_radius=6,
            font=ctk.CTkFont(size=10, weight="bold"),
            fg_color=PILL_BG,
            hover_color=DANGER_BG,
            command=self._delete_selected_profile,
        ).pack(side="left")

        # Autostart + Update + Sair
        sys_row = ctk.CTkFrame(self.settings_drawer, fg_color="transparent")
        sys_row.grid(row=4, column=0, columnspan=3, padx=12, pady=(0, 4), sticky="ew")

        self.autostart_switch = ctk.CTkSwitch(
            sys_row,
            text="Iniciar com Windows",
            variable=self._autostart_var,
            font=ctk.CTkFont(size=11),
            progress_color=ACCENT_PURPLE,
            command=self._on_autostart_switch,
        )
        self.autostart_switch.pack(side="left")

        ctk.CTkButton(
            sys_row,
            text="Sair",
            width=44,
            height=22,
            corner_radius=6,
            font=ctk.CTkFont(size=10),
            fg_color="transparent",
            hover_color=DANGER_BG,
            text_color=TEXT_MUTED,
            command=self.quit_app,
        ).pack(side="right")

        upd_row = ctk.CTkFrame(self.settings_drawer, fg_color="transparent")
        upd_row.grid(row=5, column=0, columnspan=3, padx=12, pady=(0, 8), sticky="ew")

        self.status_lbl = ctk.CTkLabel(
            upd_row,
            text=f"Mixers v{__version__}",
            anchor="w",
            font=ctk.CTkFont(size=10),
            text_color=TEXT_MUTED,
        )
        self.status_lbl.pack(side="left", fill="x", expand=True)

        ctk.CTkButton(
            upd_row,
            text="Atualizações",
            width=82,
            height=22,
            corner_radius=6,
            font=ctk.CTkFont(size=10),
            fg_color=PILL_BG,
            hover_color=PILL_HOVER,
            command=lambda: self.check_updates_async(manual=True),
        ).pack(side="right")

        # Row 3: Lista limpa de Aplicativos (faixa escura igual à referência!)
        self.apps_scroll = ctk.CTkScrollableFrame(
            self.shell,
            fg_color=LIST_BAND,
            scrollbar_button_color="#2D2448",
            scrollbar_button_hover_color="#46396E",
            corner_radius=0,
        )
        self.apps_scroll.grid(row=3, column=0, padx=2, pady=(4, 2), sticky="nsew")
        self.apps_scroll.grid_columnconfigure(0, weight=1)

        # Row 4: Faixa de Microfones (mesmo estilo 2-tons da referência!)
        mics_header = ctk.CTkFrame(
            self.shell,
            fg_color=MICS_BAND,
            corner_radius=0,
        )
        mics_header.grid(row=4, column=0, padx=1, pady=(2, 0), sticky="ew")
        mics_header.grid_columnconfigure(0, weight=1)

        self.mics_toggle_btn = ctk.CTkButton(
            mics_header,
            text="Microfones",
            anchor="w",
            height=30,
            corner_radius=0,
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="normal"),
            fg_color="transparent",
            hover_color="#332559",
            text_color=TEXT_PRIMARY,
            command=self._toggle_mics_section,
        )
        self.mics_toggle_btn.grid(row=0, column=0, padx=(8, 4), pady=2, sticky="ew")

        self.mic_test_btn = ctk.CTkButton(
            mics_header,
            text="Testar",
            width=54,
            height=22,
            corner_radius=6,
            font=ctk.CTkFont(size=10, weight="bold"),
            fg_color="#382863",
            hover_color=ACCENT_PURPLE,
            text_color=TEXT_PRIMARY,
            command=self._toggle_mic_test,
        )
        self.mic_test_btn.grid(row=0, column=1, padx=(0, 4), pady=2)

        self.mics_arrow_lbl = ctk.CTkLabel(
            mics_header,
            text="⌄" if self._mics_expanded else "›",
            width=22,
            font=ctk.CTkFont(size=14),
            text_color="#C9C1E0",
        )
        self.mics_arrow_lbl.grid(row=0, column=2, padx=(0, 10), pady=2)
        self.mics_arrow_lbl.bind("<Button-1>", lambda _e: self._toggle_mics_section())

        self.mics_body = ctk.CTkFrame(self.shell, fg_color=LIST_BAND, corner_radius=8)
        self.mics_body.grid_columnconfigure(0, weight=1)
        if self._mics_expanded:
            self.mics_body.grid(row=5, column=0, padx=2, pady=(2, 6), sticky="ew")

    # ------------------------------------------------------------------
    # Timers (0% CPU quando oculto na bandeja)
    # ------------------------------------------------------------------
    def _start_live_loops(self) -> None:
        self._stop_live_loops()
        self._session_timer_id = self.after(
            self.SESSION_REFRESH_MS, self._schedule_session_refresh
        )
        self._meter_timer_id = self.after(
            self.METER_REFRESH_MS, self._schedule_meter_refresh
        )

    def _stop_live_loops(self) -> None:
        if self._session_timer_id is not None:
            try:
                self.after_cancel(self._session_timer_id)
            except Exception:
                pass
            self._session_timer_id = None

        if self._meter_timer_id is not None:
            try:
                self.after_cancel(self._meter_timer_id)
            except Exception:
                pass
            self._meter_timer_id = None

    # ------------------------------------------------------------------
    # Visibilidade e Bandeja
    # ------------------------------------------------------------------
    def toggle_visibility(self) -> None:
        if self._is_visible:
            self.hide_to_tray()
        else:
            self.show_from_tray()

    def show_from_tray(self) -> None:
        self._is_visible = True
        self.refresh_audio_state(force_rebuild=False)
        self._update_window_geometry(y_offset=14)
        self.deiconify()
        self.lift()
        self.focus_force()
        self._animate_open()
        self._start_live_loops()

    def hide_to_tray(self) -> None:
        if self._recording_hotkey:
            self._cancel_record_hotkey()
        self._stop_mic_test()
        if self.tray is None and not self.demo_mode:
            self.quit_app()
            return
        if not self._is_visible:
            return
        self._is_visible = False
        self._stop_live_loops()
        self._animate_close()

    def _on_focus_out(self, _event) -> None:
        if self._pinned or self._dialog_open or self._recording_hotkey or not self._is_visible:
            return
        self.after(120, self._hide_if_still_unfocused)

    def _hide_if_still_unfocused(self) -> None:
        if self._pinned or self._dialog_open or self._recording_hotkey or not self._is_visible:
            return
        try:
            if self.focus_displayof() is None:
                self.hide_to_tray()
        except Exception:
            pass

    def quit_app(self) -> None:
        self._stop_live_loops()
        self._stop_mic_test()
        self.hotkey_manager.unregister()
        if self.tray is not None:
            self.tray.stop()
        self.destroy()

    # ------------------------------------------------------------------
    # Atualização ultrarrápida (cache COM + medidor integrado no slider)
    # ------------------------------------------------------------------
    def _schedule_session_refresh(self) -> None:
        self._session_timer_id = None
        if not self._is_visible:
            return
        if time.monotonic() - self._last_slider_ts > 0.6:
            self.refresh_audio_state(force_rebuild=False)
        self._session_timer_id = self.after(
            self.SESSION_REFRESH_MS, self._schedule_session_refresh
        )

    def _schedule_meter_refresh(self) -> None:
        self._meter_timer_id = None
        if not self._is_visible:
            return
        self._update_audio_meters()
        self._meter_timer_id = self.after(
            self.METER_REFRESH_MS, self._schedule_meter_refresh
        )

    def _update_audio_meters(self) -> None:
        try:
            master_peak, app_peaks = self.backend.get_peaks()
            mic_peaks = self.backend.get_mic_peaks() if self._mics_expanded else {}
        except Exception:
            return

        if abs(master_peak - self._last_master_peak) >= self.METER_EPSILON:
            self._last_master_peak = master_peak
            self.master_slider.set_peak(master_peak, PEAK_WHITE)

        for app_id, row in self._app_rows.items():
            session = self._current_sessions.get(app_id)
            peak = 0.0 if (session and session.muted) else app_peaks.get(app_id, 0.0)
            prev = self._last_app_peak.get(app_id, -1.0)
            if abs(peak - prev) >= self.METER_EPSILON:
                self._last_app_peak[app_id] = peak
                row["slider"].set_peak(peak, PEAK_WHITE)

        if self._mics_expanded:
            for dev_id, row in self._mic_rows.items():
                mic = self._current_mics.get(dev_id)
                muted = bool(mic.muted) if mic else False
                peak = 0.0 if muted else mic_peaks.get(dev_id, 0.0)
                label, color = classify_mic_quality(peak, muted=muted)
                prev = self._last_mic_peak.get(dev_id, -1.0)
                if abs(peak - prev) >= self.METER_EPSILON or self._last_mic_quality.get(dev_id) != label:
                    self._last_mic_peak[dev_id] = peak
                    self._last_mic_quality[dev_id] = label
                    row["slider"].set_peak(peak, color)
                    row["quality_lbl"].configure(text=label, text_color=color)

    def refresh_audio_state(self, force_rebuild: bool = False) -> None:
        try:
            master_vol = int(round(self.backend.get_master_volume() * 100))
            master_muted = self.backend.get_master_mute()
            mics = self.backend.list_microphones()
            sessions = self.backend.list_app_sessions()
            dev_name = self.backend.get_output_device_name()
        except Exception as exc:
            self._set_status(f"Erro de áudio: {exc}")
            return

        self.device_lbl.configure(text=self._truncate(dev_name, 34))
        if master_vol != self._last_master_pct:
            self._last_master_pct = master_vol
            self.master_slider.set_value(master_vol)
            self.master_pct_lbl.configure(text=str(master_vol))
        if master_muted != self._last_master_muted:
            self._last_master_muted = master_muted
            self._apply_master_mute_visual(master_muted)

        new_mics = {m.device_id: m for m in mics}
        mics_changed = list(new_mics.keys()) != list(self._current_mics.keys())
        self._current_mics = new_mics
        if force_rebuild or mics_changed:
            self._render_microphones()
        else:
            self._sync_existing_mics()

        new_map = {s.app_id: s for s in sessions}
        keys_changed = list(new_map.keys()) != list(self._current_sessions.keys())
        self._current_sessions = new_map
        if force_rebuild or keys_changed:
            self._render_app_list(force_rebuild=True)
        else:
            self._sync_existing_rows()

        if (mics_changed or keys_changed) and self._is_visible:
            self._update_window_geometry()

    # ------------------------------------------------------------------
    # Renderização limpa de Aplicativos (1 linha elegante por app)
    # ------------------------------------------------------------------
    def _render_app_list(self, force_rebuild: bool = False) -> None:
        if not force_rebuild:
            return

        for child in self.apps_scroll.winfo_children():
            child.destroy()
        self._app_rows.clear()
        self._last_app_pct.clear()
        self._last_app_peak.clear()

        sessions = list(self._current_sessions.values())
        if not sessions:
            ctk.CTkLabel(
                self.apps_scroll,
                text="Nenhum aplicativo reproduzindo áudio.",
                font=ctk.CTkFont(family="Segoe UI", size=12),
                text_color=TEXT_MUTED,
            ).grid(row=0, column=0, padx=14, pady=18, sticky="w")
            return

        for idx, session in enumerate(sessions):
            row = ctk.CTkFrame(self.apps_scroll, fg_color=LIST_BAND, corner_radius=0)
            row.grid(row=idx, column=0, padx=6, pady=2, sticky="ew")
            row.grid_columnconfigure(1, weight=1)

            vol_pct = int(round(session.volume * 100))
            self._last_app_pct[session.app_id] = vol_pct

            icon_btn = ctk.CTkButton(
                row,
                text="",
                image=get_app_badge_icon(
                    session.app_id, session.display_name, muted=session.muted, size=24
                ),
                width=34,
                height=34,
                corner_radius=8,
                fg_color="transparent",
                hover_color=PILL_BG,
                command=lambda aid=session.app_id: self._toggle_app_mute(aid),
            )
            icon_btn.grid(row=0, column=0, rowspan=2, padx=(4, 6), pady=3)

            ctk.CTkLabel(
                row,
                text=self._truncate(session.display_name, 26),
                font=ctk.CTkFont(family="Segoe UI", size=10),
                text_color=TEXT_MUTED if session.muted else "#C4BDD8",
                anchor="w",
                height=14,
            ).grid(row=0, column=1, padx=(6, 4), pady=(3, 0), sticky="w")

            slider = EarTrumpetSlider(
                row,
                bg_color=LIST_BAND,
                value=vol_pct,
                muted=session.muted,
                on_change=lambda val, aid=session.app_id: self._on_app_slider(aid, val),
                height=24,
            )
            init_peak = 0.0 if session.muted else session.peak_level
            slider.set_peak(init_peak, PEAK_WHITE)
            self._last_app_peak[session.app_id] = init_peak
            slider.grid(row=1, column=1, padx=0, pady=(0, 3), sticky="ew")

            pct_lbl = ctk.CTkLabel(
                row,
                text=str(vol_pct),
                width=34,
                anchor="e",
                font=ctk.CTkFont(family="Segoe UI", size=15, weight="normal"),
                text_color=TEXT_MUTED if session.muted else TEXT_PRIMARY,
            )
            pct_lbl.grid(row=0, column=2, rowspan=2, padx=(4, 8), pady=3)

            self._app_rows[session.app_id] = {
                "icon_btn": icon_btn,
                "slider": slider,
                "pct_lbl": pct_lbl,
            }

    def _sync_existing_rows(self) -> None:
        for app_id, widgets in self._app_rows.items():
            session = self._current_sessions.get(app_id)
            if not session:
                continue
            vol_pct = int(round(session.volume * 100))
            if vol_pct != self._last_app_pct.get(app_id):
                self._last_app_pct[app_id] = vol_pct
                widgets["slider"].set_value(vol_pct)
                widgets["pct_lbl"].configure(text=str(vol_pct))
            widgets["slider"].set_muted(session.muted)
            widgets["pct_lbl"].configure(
                text_color=TEXT_MUTED if session.muted else TEXT_PRIMARY
            )
            widgets["icon_btn"].configure(
                image=get_app_badge_icon(
                    session.app_id, session.display_name, muted=session.muted, size=24
                )
            )

    # ------------------------------------------------------------------
    # Microfones (mesmo visual clean + medidor de voz na própria trilha)
    # ------------------------------------------------------------------
    def _toggle_mic_test(self) -> None:
        if self._mic_monitor.active:
            self._stop_mic_test()
        else:
            if not self._mics_expanded:
                self._toggle_mics_section()
            if self._mic_monitor.start():
                self.mic_test_btn.configure(
                    text="Parar",
                    fg_color=DANGER_BG,
                    hover_color=DANGER_HOVER,
                )

    def _stop_mic_test(self) -> None:
        if self._mic_monitor.active:
            self._mic_monitor.stop()
        if hasattr(self, "mic_test_btn"):
            self.mic_test_btn.configure(
                text="Testar",
                fg_color="#382863",
                hover_color=ACCENT_PURPLE,
            )

    def _toggle_mics_section(self) -> None:
        self._mics_expanded = not self._mics_expanded
        self.settings.set("mics_expanded", self._mics_expanded)
        self.mics_arrow_lbl.configure(text="⌄" if self._mics_expanded else "›")
        if self._mics_expanded:
            self.mics_body.grid(row=5, column=0, padx=2, pady=(2, 6), sticky="ew")
        else:
            self._stop_mic_test()
            self.mics_body.grid_forget()
        if self._is_visible:
            self._update_window_geometry()

    def _render_microphones(self) -> None:
        for child in self.mics_body.winfo_children():
            child.destroy()
        self._mic_rows.clear()
        self._last_mic_pct.clear()
        self._last_mic_peak.clear()
        self._last_mic_quality.clear()

        mics = list(self._current_mics.values())
        if not mics:
            ctk.CTkLabel(
                self.mics_body,
                text="Nenhum microfone ativo.",
                font=ctk.CTkFont(family="Segoe UI", size=11),
                text_color=TEXT_MUTED,
            ).grid(row=0, column=0, padx=14, pady=10, sticky="w")
            return

        for idx, mic in enumerate(mics):
            row = ctk.CTkFrame(self.mics_body, fg_color=LIST_BAND, corner_radius=0)
            row.grid(row=idx, column=0, padx=6, pady=2, sticky="ew")
            row.grid_columnconfigure(1, weight=1)

            vol_pct = int(round(mic.volume * 100))
            self._last_mic_pct[mic.device_id] = vol_pct
            init_peak = 0.0 if mic.muted else mic.peak_level
            q_label, q_color = classify_mic_quality(init_peak, muted=mic.muted)
            self._last_mic_peak[mic.device_id] = init_peak
            self._last_mic_quality[mic.device_id] = q_label

            icon_btn = ctk.CTkButton(
                row,
                text="",
                image=get_mic_icon(muted=mic.muted, size=22),
                width=34,
                height=34,
                corner_radius=8,
                fg_color="transparent",
                hover_color=PILL_BG,
                command=lambda did=mic.device_id: self._toggle_mic_mute(did),
            )
            icon_btn.grid(row=0, column=0, rowspan=2, padx=(4, 6), pady=3)

            meta = ctk.CTkFrame(row, fg_color="transparent")
            meta.grid(row=0, column=1, padx=(6, 4), pady=(3, 0), sticky="ew")
            meta.grid_columnconfigure(0, weight=1)

            ctk.CTkLabel(
                meta,
                text=self._truncate(mic.name, 22),
                font=ctk.CTkFont(family="Segoe UI", size=10),
                text_color=TEXT_MUTED if mic.muted else "#C4BDD8",
                anchor="w",
                height=14,
            ).grid(row=0, column=0, sticky="w")

            quality_lbl = ctk.CTkLabel(
                meta,
                text=q_label,
                font=ctk.CTkFont(family="Segoe UI", size=10, weight="bold"),
                text_color=q_color,
                height=14,
            )
            quality_lbl.grid(row=0, column=1, sticky="e")

            slider = EarTrumpetSlider(
                row,
                bg_color=LIST_BAND,
                value=vol_pct,
                muted=mic.muted,
                accent_color=ACCENT_PURPLE,
                peak_color=q_color,
                on_change=lambda val, did=mic.device_id: self._on_mic_slider(did, val),
                height=24,
            )
            slider.set_peak(init_peak, q_color)
            slider.grid(row=1, column=1, padx=0, pady=(0, 3), sticky="ew")

            pct_lbl = ctk.CTkLabel(
                row,
                text=str(vol_pct),
                width=34,
                anchor="e",
                font=ctk.CTkFont(family="Segoe UI", size=15, weight="normal"),
                text_color=TEXT_MUTED if mic.muted else TEXT_PRIMARY,
            )
            pct_lbl.grid(row=0, column=2, rowspan=2, padx=(4, 8), pady=3)

            self._mic_rows[mic.device_id] = {
                "icon_btn": icon_btn,
                "slider": slider,
                "pct_lbl": pct_lbl,
                "quality_lbl": quality_lbl,
            }

    def _sync_existing_mics(self) -> None:
        for dev_id, widgets in self._mic_rows.items():
            mic = self._current_mics.get(dev_id)
            if not mic:
                continue
            vol_pct = int(round(mic.volume * 100))
            if vol_pct != self._last_mic_pct.get(dev_id):
                self._last_mic_pct[dev_id] = vol_pct
                widgets["slider"].set_value(vol_pct)
                widgets["pct_lbl"].configure(text=str(vol_pct))
            widgets["slider"].set_muted(mic.muted)
            widgets["pct_lbl"].configure(
                text_color=TEXT_MUTED if mic.muted else TEXT_PRIMARY
            )
            widgets["icon_btn"].configure(image=get_mic_icon(muted=mic.muted, size=22))

    # ------------------------------------------------------------------
    # Eventos de áudio
    # ------------------------------------------------------------------
    def _apply_master_mute_visual(self, muted: bool) -> None:
        self.master_mute_btn.configure(image=get_speaker_icon(muted=muted, size=24))
        self.master_slider.set_muted(muted)
        self.master_pct_lbl.configure(text_color=TEXT_MUTED if muted else TEXT_PRIMARY)

    def _on_master_slider(self, pct: int) -> None:
        self._last_slider_ts = time.monotonic()
        if pct == self._last_master_pct:
            return
        self._last_master_pct = pct
        self.master_pct_lbl.configure(text=str(pct))
        self.backend.set_master_volume(pct / 100.0)

    def _toggle_master_mute(self) -> None:
        new_state = not self.backend.get_master_mute()
        self.backend.set_master_mute(new_state)
        self._last_master_muted = new_state
        self._apply_master_mute_visual(new_state)

    def _on_app_slider(self, app_id: str, pct: int) -> None:
        self._last_slider_ts = time.monotonic()
        if pct == self._last_app_pct.get(app_id):
            return
        self._last_app_pct[app_id] = pct
        if app_id in self._app_rows:
            self._app_rows[app_id]["pct_lbl"].configure(text=str(pct))
        self.backend.set_app_volume(app_id, pct / 100.0)
        if app_id in self._current_sessions:
            self._current_sessions[app_id].volume = pct / 100.0

    def _toggle_app_mute(self, app_id: str) -> None:
        session = self._current_sessions.get(app_id)
        if not session:
            return
        new_state = not session.muted
        self.backend.set_app_mute(app_id, new_state)
        session.muted = new_state
        if app_id in self._app_rows:
            row = self._app_rows[app_id]
            row["slider"].set_muted(new_state)
            row["pct_lbl"].configure(text_color=TEXT_MUTED if new_state else TEXT_PRIMARY)
            row["icon_btn"].configure(
                image=get_app_badge_icon(
                    session.app_id, session.display_name, muted=new_state, size=24
                )
            )

    def _on_mic_slider(self, device_id: str, pct: int) -> None:
        self._last_slider_ts = time.monotonic()
        if pct == self._last_mic_pct.get(device_id):
            return
        self._last_mic_pct[device_id] = pct
        if device_id in self._mic_rows:
            self._mic_rows[device_id]["pct_lbl"].configure(text=str(pct))
        self.backend.set_microphone_volume(device_id, pct / 100.0)
        if device_id in self._current_mics:
            self._current_mics[device_id].volume = pct / 100.0

    def _toggle_mic_mute(self, device_id: str) -> None:
        mic = self._current_mics.get(device_id)
        if not mic:
            return
        new_state = not mic.muted
        self.backend.set_microphone_mute(device_id, new_state)
        mic.muted = new_state
        if device_id in self._mic_rows:
            row = self._mic_rows[device_id]
            row["slider"].set_muted(new_state)
            row["pct_lbl"].configure(text_color=TEXT_MUTED if new_state else TEXT_PRIMARY)
            row["icon_btn"].configure(image=get_mic_icon(muted=new_state, size=22))
            q_label, q_color = classify_mic_quality(0.0, muted=new_state)
            row["quality_lbl"].configure(text=q_label, text_color=q_color)

    # ------------------------------------------------------------------
    # Ajustes, Atalho Global, Perfis & Presets
    # ------------------------------------------------------------------
    def _toggle_settings_drawer(self) -> None:
        self._settings_open = not self._settings_open
        if self._settings_open:
            self.settings_drawer.grid(row=2, column=0, padx=1, pady=0, sticky="ew")
            self.settings_btn.configure(fg_color=ACCENT_PURPLE, text_color="#FFFFFF")
        else:
            if self._recording_hotkey:
                self._cancel_record_hotkey()
            self.settings_drawer.grid_forget()
            self.settings_btn.configure(fg_color="transparent", text_color="#C9C1E0")
        if self._is_visible:
            self._update_window_geometry()

    def _toggle_pin(self) -> None:
        self._pinned = not self._pinned
        if self._pinned:
            self.pin_btn.configure(fg_color=ACCENT_PURPLE, text_color="#FFFFFF")
            self._set_status("Painel fixado na tela.")
        else:
            self.pin_btn.configure(fg_color=PILL_BG, text_color=TEXT_MUTED)
            self._set_status("Oculta ao clicar fora.")

    def _on_alpha_change(self, pct: int) -> None:
        clamped = max(75, min(100, int(pct)))
        self._alpha = clamped / 100.0
        self.alpha_lbl.configure(text=f"{clamped}%")
        self.settings.set("alpha", round(self._alpha, 2))
        try:
            self.attributes("-alpha", self._alpha)
        except Exception:
            pass

    def _on_autostart_switch(self) -> None:
        desired = self._autostart_var.get()
        ok = set_autostart(desired)
        if not ok and sys.platform == "win32":
            self._autostart_var.set(is_autostart_enabled())
            self._set_status("Erro ao alterar autostart.")
        else:
            self._set_status("Autostart ativado." if desired else "Autostart desativado.")

    def _toggle_autostart_from_tray(self) -> None:
        new_val = not is_autostart_enabled()
        if set_autostart(new_val):
            self._autostart_var.set(new_val)

    def _toggle_record_hotkey(self) -> None:
        if self._recording_hotkey:
            self._cancel_record_hotkey()
            return
        self._recording_hotkey = True
        self.record_hotkey_btn.configure(
            text="Cancelar", fg_color=ACCENT_PURPLE, text_color="#FFFFFF"
        )
        self.hotkey_badge.configure(text="Pressione...")
        self.focus_force()

    def _cancel_record_hotkey(self) -> None:
        self._recording_hotkey = False
        self.record_hotkey_btn.configure(
            text="Gravar", fg_color=PILL_BG, text_color=TEXT_PRIMARY
        )
        self._update_hotkey_badge(self.hotkey_manager.current_hotkey)

    def _clear_hotkey(self) -> None:
        self._recording_hotkey = False
        self.hotkey_manager.register("")
        self.settings.set("hotkey", "")
        self.record_hotkey_btn.configure(
            text="Gravar", fg_color=PILL_BG, text_color=TEXT_PRIMARY
        )
        self._update_hotkey_badge("")
        self._set_status("Atalho desativado.")

    def _on_global_key_press(self, event) -> None:
        keysym = str(getattr(event, "keysym", ""))
        if not self._recording_hotkey:
            if keysym == "Escape":
                self.hide_to_tray()
            return

        if keysym == "Escape":
            self._cancel_record_hotkey()
            return

        if keysym in (
            "Control_L", "Control_R", "Alt_L", "Alt_R",
            "Shift_L", "Shift_R", "Super_L", "Super_R", "Win_L", "Win_R",
        ):
            return

        state = int(getattr(event, "state", 0))
        mods: list[str] = []
        if state & 0x0004:
            mods.append("Ctrl")
        if state & 0x0008 or state & 0x20000:
            mods.append("Alt")
        if state & 0x0001:
            mods.append("Shift")

        key_name = keysym.upper() if len(keysym) == 1 else keysym
        combo = normalize_hotkey_label("+".join(mods + [key_name]))

        ok, msg = self.hotkey_manager.register(combo)
        self._recording_hotkey = False
        self.record_hotkey_btn.configure(
            text="Gravar", fg_color=PILL_BG, text_color=TEXT_PRIMARY
        )
        if ok:
            self.settings.set("hotkey", self.hotkey_manager.current_hotkey)
            self._update_hotkey_badge(self.hotkey_manager.current_hotkey)
            self._set_status(msg)
        else:
            prev = str(self.settings.get("hotkey", ""))
            if prev:
                self.hotkey_manager.register(prev)
            self._update_hotkey_badge(self.hotkey_manager.current_hotkey)
            self._set_status(msg)

    def _update_hotkey_badge(self, hotkey: str) -> None:
        self.hotkey_badge.configure(text=hotkey if hotkey else "Desativado")

    def _preset_full_volume(self) -> None:
        for app_id in list(self._current_sessions):
            self.backend.set_app_mute(app_id, False)
            self.backend.set_app_volume(app_id, 1.0)
        if self._is_visible:
            self.refresh_audio_state(force_rebuild=False)

    def _preset_focus_mode(self) -> None:
        for app_id in list(self._current_sessions):
            self.backend.set_app_mute(app_id, False)
            self.backend.set_app_volume(app_id, 0.30)
        if self._is_visible:
            self.refresh_audio_state(force_rebuild=False)

    def _preset_mute_all_apps(self) -> None:
        for app_id in list(self._current_sessions):
            self.backend.set_app_mute(app_id, True)
        if self._is_visible:
            self.refresh_audio_state(force_rebuild=False)

    def _get_profile_options(self) -> list[str]:
        names = self.profile_manager.list_names()
        return names if names else ["Sem perfis salvos"]

    def _refresh_profile_menu(self, select_name: str | None = None) -> None:
        options = self._get_profile_options()
        self.profile_menu.configure(values=options)
        self._selected_profile.set(select_name if (select_name in options) else options[0])

    def _save_profile_dialog(self) -> None:
        self._dialog_open = True
        try:
            dialog = ctk.CTkInputDialog(text="Nome do perfil:", title="Salvar Perfil")
            name = dialog.get_input()
        finally:
            self._dialog_open = False

        if not name or not name.strip():
            return
        clean = name.strip()
        self.profile_manager.save_from_backend(clean, self.backend)
        self._refresh_profile_menu(select_name=clean)
        self._set_status(f"Perfil '{clean}' salvo.")

    def _apply_selected_profile(self) -> None:
        name = self._selected_profile.get()
        if self.profile_manager.apply_to_backend(name, self.backend):
            self.refresh_audio_state(force_rebuild=False)
            self._set_status(f"Perfil '{name}' aplicado.")

    def _delete_selected_profile(self) -> None:
        name = self._selected_profile.get()
        if self.profile_manager.delete(name):
            self._refresh_profile_menu()
            self._set_status(f"Perfil '{name}' removido.")

    # ------------------------------------------------------------------
    # Auto-Updater via GitHub Releases
    # ------------------------------------------------------------------
    def check_updates_async(self, manual: bool = False) -> None:
        if self._updating:
            return
        if manual:
            if not self._is_visible:
                self.show_from_tray()
            self._set_status("Verificando atualizações...")

        def _worker() -> None:
            try:
                info = check_for_update(__version__)
                self.after(0, lambda: self._on_update_checked(info, manual, None))
            except Exception as exc:
                self.after(0, lambda: self._on_update_checked(None, manual, str(exc)))

        threading.Thread(target=_worker, daemon=True).start()

    def _on_update_checked(
        self,
        info: UpdateInfo | None,
        manual: bool,
        error: str | None,
    ) -> None:
        if error:
            if manual:
                self._set_status(f"Erro: {self._truncate(error.replace(chr(10), ' '), 30)}")
            return

        if info is not None:
            self._pending_update = info
            self.update_banner_lbl.configure(text=f"Nova versão v{info.version} disponível!")
            self.update_banner.grid(row=1, column=0, padx=8, pady=(6, 2), sticky="ew")
            if self._is_visible:
                self._update_window_geometry()
            self._set_status(f"v{info.version} pronta.")
        elif manual:
            self._set_status(f"Atualizado (v{__version__}).")

    def _start_update_download(self) -> None:
        if not self._pending_update or self._updating:
            return
        self._updating = True
        update = self._pending_update
        self.update_now_btn.configure(state="disabled", text="Baixando...")

        def _progress(pct: int) -> None:
            self.after(0, lambda: self.update_now_btn.configure(text=f"{pct}%"))

        def _worker() -> None:
            try:
                should_quit = download_and_apply_update(update, on_progress=_progress)
                self.after(0, lambda: self._on_update_finished(should_quit, None))
            except Exception as exc:
                self.after(0, lambda: self._on_update_finished(False, str(exc)))

        threading.Thread(target=_worker, daemon=True).start()

    def _on_update_finished(self, should_quit: bool, error: str | None) -> None:
        self._updating = False
        if error:
            self.update_now_btn.configure(state="normal", text="Atualizar")
            self._set_status(f"Erro: {self._truncate(error, 30)}")
            return
        if should_quit:
            self.after(200, self._exit_for_update)
        else:
            self.update_now_btn.configure(state="normal", text="Abrir")

    def _exit_for_update(self) -> None:
        self._stop_live_loops()
        self._stop_mic_test()
        self.hotkey_manager.unregister()
        if self.tray is not None:
            self.tray.stop()
        try:
            self.destroy()
        except Exception:
            pass
        os._exit(0)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _truncate(text: str, max_len: int) -> str:
        return text if len(text) <= max_len else text[: max_len - 1] + "…"

    def _set_status(self, message: str) -> None:
        if hasattr(self, "status_lbl"):
            self.status_lbl.configure(text=message)
