"""Interface fiel ao EarTrumpet / Windows 11: troca de tela limpa (sem pixelar) e fade suave."""

from __future__ import annotations

import os
import sys
import threading
import time
import tkinter as tk
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
    EarTrumpetSlider,
    HoverTooltip,
    PEAK_WHITE,
    get_app_icon,
    get_mic_icon,
    get_speaker_icon,
)
from mixers.windows_integration import (
    apply_windows_glass_style,
    compute_bottom_right_position,
    derive_theme_from_accent,
    get_windows_accent_rgb,
    get_work_area,
    is_autostart_enabled,
    is_our_process_foreground,
    set_autostart,
)

DANGER_BG = "#6E1D31"
DANGER_HOVER = "#8B263E"


class MixersApp(ctk.CTk):
    """Painel minimalista estilo EarTrumpet com cor do sistema e animações naturais."""

    WINDOW_WIDTH = 356
    MIN_HEIGHT = 330
    MAX_HEIGHT = 540
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

        # Paleta automática baseada na cor de destaque configurada no Windows
        self.theme = derive_theme_from_accent(get_windows_accent_rgb())

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        # Preferências persistidas
        self._alpha = max(0.65, min(1.0, float(self.settings.get("alpha", 0.86))))
        self._animations_enabled = bool(self.settings.get("animations", True))
        self._mics_expanded = bool(self.settings.get("mics_expanded", True))
        saved_hotkey = str(self.settings.get("hotkey", "Ctrl+Alt+M"))

        self.title(f"Mixers v{__version__}")
        self.configure(fg_color=self.theme["list_band"])
        self.resizable(False, False)

        # Estado visual e cache de performance
        self._pinned = False
        self._settings_open = False
        self._dialog_open = False
        self._recording_hotkey = False
        self._is_visible = not start_minimized
        self._anim_token = 0
        self._cur_height = 360

        self._session_timer_id: str | None = None
        self._meter_timer_id: str | None = None
        self._alpha_save_timer_id: str | None = None
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
        self._animations_var = ctk.BooleanVar(value=self._animations_enabled)
        self._pinned_var = ctk.BooleanVar(value=False)
        self._pending_update: UpdateInfo | None = None
        self._updating = False

        if sys.platform == "win32":
            self.overrideredirect(True)
            try:
                self.attributes("-toolwindow", True)
            except Exception:
                pass
        self.attributes("-topmost", True)
        try:
            self.attributes("-alpha", 0.0 if (not start_minimized and self._animations_enabled) else self._alpha)
        except Exception:
            pass

        self._build_layout()
        self._update_window_geometry()
        self._apply_native_window_effects()

        self.hotkey_manager = GlobalHotkeyManager(
            on_trigger=lambda: self.after(0, self.toggle_visibility)
        )
        ok, msg = self.hotkey_manager.register(saved_hotkey)
        self._update_hotkey_badge(self.hotkey_manager.current_hotkey)
        if not ok and saved_hotkey:
            self._set_status(msg)

        self.bind("<KeyPress>", self._on_global_key_press)
        self.bind("<FocusOut>", self._on_focus_out)
        self.protocol("WM_DELETE_WINDOW", self.hide_to_tray)

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
            self.after(200, lambda: self.refresh_audio_state(force_rebuild=True))
        else:
            self.refresh_audio_state(force_rebuild=True)
            if self._animations_enabled:
                self._animate_fade(0.0, self._alpha, duration_ms=95)
            self._start_live_loops()

        self.after(3000, lambda: self.check_updates_async(manual=False))

    # ------------------------------------------------------------------
    # Helper para criar sliders com a cor do Windows
    # ------------------------------------------------------------------
    def _make_slider(
        self,
        parent,
        bg_color: str,
        value: int,
        muted: bool = False,
        peak_color: str = PEAK_WHITE,
        on_change=None,
        height: int = 32,
    ) -> EarTrumpetSlider:
        return EarTrumpetSlider(
            parent,
            bg_color=bg_color,
            value=value,
            muted=muted,
            accent_color=self.theme["accent"],
            accent_hover=self.theme["accent_hover"],
            track_unfilled=self.theme["track_unfilled"],
            track_muted=self.theme["track_muted"],
            thumb_muted=self.theme["thumb_muted"],
            peak_color=peak_color,
            on_change=on_change,
            height=height,
        )

    # ------------------------------------------------------------------
    # Geometria estável + Fade natural baseado em tempo real (sem pixelar!)
    # ------------------------------------------------------------------
    def _desired_height(self) -> int:
        # Altura fixa mínima de 330px garante que a tela de Ajustes caiba SEM redimensionar a janela!
        h = 92
        if self._pending_update is not None:
            h += 34

        app_count = max(1, len(self._current_sessions))
        h += min(app_count, 5) * 44 + 10

        h += 38
        if self._mics_expanded:
            mic_count = max(1, len(self._current_mics))
            h += min(mic_count, 2) * 44 + 8

        return max(self.MIN_HEIGHT, min(self.MAX_HEIGHT, h))

    def _update_window_geometry(self) -> None:
        new_h = self._desired_height()
        self._cur_height = new_h
        try:
            scale = float(self._get_window_scaling())
        except Exception:
            scale = 1.0

        win_w_px = int(round(self.WINDOW_WIDTH * scale))
        win_h_px = int(round(new_h * scale))
        work_area = get_work_area(self.winfo_screenwidth(), self.winfo_screenheight())
        x, y = compute_bottom_right_position(win_w_px, win_h_px, work_area, margin=10)
        self.geometry(f"{self.WINDOW_WIDTH}x{new_h}+{x}+{y}")

    def _animate_fade(
        self,
        start_alpha: float,
        end_alpha: float,
        duration_ms: int,
        on_done=None,
    ) -> None:
        """Fade suave baseado em relógio real (ease-out cúbico, zero geometry() / zero pixelação)."""
        self._anim_token += 1
        token = self._anim_token
        t0 = time.perf_counter()
        dur_s = max(0.02, duration_ms / 1000.0)

        try:
            self.attributes("-alpha", round(start_alpha, 3))
        except Exception:
            if on_done:
                on_done()
            return

        def _tick() -> None:
            if token != self._anim_token:
                return
            progress = min(1.0, (time.perf_counter() - t0) / dur_s)
            # Curva ease-out suave e natural
            eased = 1.0 - (1.0 - progress) ** 3
            val = start_alpha + (end_alpha - start_alpha) * eased
            try:
                self.attributes("-alpha", max(0.0, min(1.0, round(val, 3))))
            except Exception:
                pass
            if progress < 1.0:
                self.after(12, _tick)
            elif on_done:
                on_done()

        self.after(10, _tick)

    def _apply_native_window_effects(self) -> None:
        if sys.platform != "win32":
            return
        try:
            self.update_idletasks()
            apply_windows_glass_style(self.winfo_id())
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Layout com 2 views sobrepostas (Mixer <-> Ajustes) sem esticar a janela!
    # ------------------------------------------------------------------
    def _build_layout(self) -> None:
        t = self.theme

        self.outer = tk.Frame(self, bg=t["panel_border"], bd=0)
        self.outer.pack(fill="both", expand=True)

        self.stage = tk.Frame(self.outer, bg=t["list_band"], bd=0)
        self.stage.pack(fill="both", expand=True, padx=1, pady=1)
        self.stage.grid_columnconfigure(0, weight=1)
        self.stage.grid_rowconfigure(0, weight=1)

        # === VIEW 1: MIXER PRINCIPAL ===
        self.mixer_view = tk.Frame(self.stage, bg=t["list_band"], bd=0)
        self.mixer_view.grid(row=0, column=0, sticky="nsew")
        self.mixer_view.grid_columnconfigure(0, weight=1)
        self.mixer_view.grid_rowconfigure(2, weight=1)

        # Faixa Master
        master_band = tk.Frame(self.mixer_view, bg=t["header_band"], bd=0)
        master_band.grid(row=0, column=0, sticky="ew")
        master_band.grid_columnconfigure(1, weight=1)

        top_row = tk.Frame(master_band, bg=t["header_band"], bd=0)
        top_row.grid(row=0, column=0, columnspan=3, padx=(16, 10), pady=(11, 2), sticky="ew")
        top_row.grid_columnconfigure(0, weight=1)

        self.device_lbl = tk.Label(
            top_row,
            text=self._truncate(self.backend.get_output_device_name(), 34),
            font=("Segoe UI", 10),
            bg=t["header_band"],
            fg=t["text_primary"],
            anchor="w",
        )
        self.device_lbl.grid(row=0, column=0, sticky="w")

        self.settings_btn = ctk.CTkButton(
            top_row,
            text="⚙",
            width=24,
            height=22,
            corner_radius=6,
            font=ctk.CTkFont(size=12),
            fg_color="transparent",
            hover_color=t["header_hover"],
            text_color="#C8C4D8",
            command=self._open_settings_view,
        )
        self.settings_btn.grid(row=0, column=1, padx=(4, 2))

        ctk.CTkButton(
            top_row,
            text="⌄",
            width=24,
            height=22,
            corner_radius=6,
            font=ctk.CTkFont(size=14),
            fg_color="transparent",
            hover_color=t["header_hover"],
            text_color="#C8C4D8",
            command=self.hide_to_tray,
        ).grid(row=0, column=2)

        self.master_mute_btn = ctk.CTkButton(
            master_band,
            text="",
            image=get_speaker_icon(muted=False, size=22),
            width=36,
            height=36,
            corner_radius=6,
            fg_color="transparent",
            hover_color=t["header_hover"],
            command=self._toggle_master_mute,
        )
        self.master_mute_btn.grid(row=1, column=0, padx=(10, 6), pady=(4, 12))

        self.master_slider = self._make_slider(
            master_band,
            bg_color=t["header_band"],
            value=100,
            muted=False,
            on_change=self._on_master_slider,
            height=32,
        )
        self.master_slider.grid(row=1, column=1, padx=4, pady=(4, 12), sticky="ew")

        self.master_pct_lbl = tk.Label(
            master_band,
            text="100",
            width=3,
            anchor="e",
            font=("Segoe UI", 14),
            bg=t["header_band"],
            fg=t["text_primary"],
        )
        self.master_pct_lbl.grid(row=1, column=2, padx=(6, 16), pady=(4, 12))

        # Banner discreto de atualização disponível
        self.update_banner = tk.Frame(self.mixer_view, bg=t["drawer_band"], bd=0)
        self.update_banner.grid_columnconfigure(0, weight=1)

        self.update_banner_lbl = tk.Label(
            self.update_banner,
            text="Nova versão disponível!",
            font=("Segoe UI", 9, "bold"),
            bg=t["drawer_band"],
            fg=t["text_primary"],
            anchor="w",
        )
        self.update_banner_lbl.grid(row=0, column=0, padx=14, pady=5, sticky="w")

        self.update_now_btn = ctk.CTkButton(
            self.update_banner,
            text="Atualizar",
            width=72,
            height=22,
            corner_radius=6,
            font=ctk.CTkFont(size=10, weight="bold"),
            fg_color=t["accent"],
            hover_color=t["accent_hover"],
            text_color="#FFFFFF",
            command=self._start_update_download,
        )
        self.update_now_btn.grid(row=0, column=1, padx=(4, 12), pady=5)

        # Lista limpa de Apps (sem barra de rolagem visível)
        self.apps_canvas = tk.Canvas(
            self.mixer_view,
            bg=t["list_band"],
            highlightthickness=0,
            bd=0,
        )
        self.apps_canvas.grid(row=2, column=0, sticky="nsew", pady=(4, 4))

        self.apps_inner = tk.Frame(self.apps_canvas, bg=t["list_band"], bd=0)
        self.apps_inner.grid_columnconfigure(0, weight=1)
        self._apps_canvas_win = self.apps_canvas.create_window(
            (0, 0), window=self.apps_inner, anchor="nw"
        )
        self.apps_inner.bind(
            "<Configure>",
            lambda _e: self.apps_canvas.configure(scrollregion=self.apps_canvas.bbox("all")),
        )
        self.apps_canvas.bind(
            "<Configure>",
            lambda e: self.apps_canvas.itemconfigure(self._apps_canvas_win, width=e.width),
        )
        self.apps_canvas.bind("<MouseWheel>", self._on_apps_wheel)

        # Segunda faixa: Microfones
        mics_header = tk.Frame(self.mixer_view, bg=t["mics_band"], bd=0)
        mics_header.grid(row=3, column=0, sticky="ew")
        mics_header.grid_columnconfigure(0, weight=1)

        mics_title = tk.Label(
            mics_header,
            text="Microfones",
            font=("Segoe UI", 10),
            bg=t["mics_band"],
            fg=t["text_primary"],
            anchor="w",
            cursor="hand2",
        )
        mics_title.grid(row=0, column=0, padx=(16, 4), pady=8, sticky="ew")
        mics_title.bind("<Button-1>", lambda _e: self._toggle_mics_section())

        self.mic_test_btn = ctk.CTkButton(
            mics_header,
            text="Testar",
            width=50,
            height=21,
            corner_radius=6,
            font=ctk.CTkFont(size=10),
            fg_color=t["header_hover"],
            hover_color=t["accent"],
            text_color=t["text_primary"],
            command=self._toggle_mic_test,
        )
        self.mic_test_btn.grid(row=0, column=1, padx=(0, 4), pady=6)

        self.mics_arrow_lbl = tk.Label(
            mics_header,
            text="⌄" if self._mics_expanded else "›",
            width=2,
            font=("Segoe UI", 12),
            bg=t["mics_band"],
            fg="#C8C4D8",
            cursor="hand2",
        )
        self.mics_arrow_lbl.grid(row=0, column=2, padx=(0, 12), pady=6)
        self.mics_arrow_lbl.bind("<Button-1>", lambda _e: self._toggle_mics_section())

        self.mics_body = tk.Frame(self.mixer_view, bg=t["list_band"], bd=0)
        self.mics_body.grid_columnconfigure(0, weight=1)
        if self._mics_expanded:
            self.mics_body.grid(row=4, column=0, pady=(4, 6), sticky="ew")

        # === VIEW 2: AJUSTES (troca instantânea no mesmo espaço, ZERO pixelação!) ===
        self.settings_view = tk.Frame(self.stage, bg=t["list_band"], bd=0)
        self.settings_view.grid(row=0, column=0, sticky="nsew")
        self.settings_view.grid_columnconfigure(0, weight=1)
        self.settings_view.grid_rowconfigure(1, weight=1)

        # Cabeçalho de Ajustes com botão Voltar (←)
        set_header = tk.Frame(self.settings_view, bg=t["header_band"], bd=0)
        set_header.grid(row=0, column=0, sticky="ew")
        set_header.grid_columnconfigure(1, weight=1)

        ctk.CTkButton(
            set_header,
            text="←",
            width=28,
            height=26,
            corner_radius=6,
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color="transparent",
            hover_color=t["header_hover"],
            text_color=t["text_primary"],
            command=self._close_settings_view,
        ).grid(row=0, column=0, padx=(10, 4), pady=8)

        tk.Label(
            set_header,
            text="Ajustes",
            font=("Segoe UI", 11, "bold"),
            bg=t["header_band"],
            fg=t["text_primary"],
            anchor="w",
        ).grid(row=0, column=1, pady=8, sticky="w")

        tk.Label(
            set_header,
            text=f"v{__version__}",
            font=("Segoe UI", 9),
            bg=t["header_band"],
            fg="#C8C4D8",
        ).grid(row=0, column=2, padx=(4, 14), pady=8, sticky="e")

        # Corpo limpo de Ajustes
        set_body = tk.Frame(self.settings_view, bg=t["list_band"], bd=0)
        set_body.grid(row=1, column=0, padx=14, pady=10, sticky="nsew")
        set_body.grid_columnconfigure(1, weight=1)

        # Opacidade
        tk.Label(
            set_body, text="Opacidade", font=("Segoe UI", 9),
            bg=t["list_band"], fg=t["text_muted"],
        ).grid(row=0, column=0, pady=(2, 8), sticky="w")

        self.alpha_slider = self._make_slider(
            set_body,
            bg_color=t["list_band"],
            value=int(round(self._alpha * 100)),
            on_change=self._on_alpha_change,
            height=22,
        )
        self.alpha_slider.grid(row=0, column=1, padx=8, pady=(2, 8), sticky="ew")

        self.alpha_lbl = tk.Label(
            set_body, text=f"{int(round(self._alpha * 100))}%", width=4,
            font=("Segoe UI", 9), bg=t["list_band"], fg=t["text_primary"],
        )
        self.alpha_lbl.grid(row=0, column=2, pady=(2, 8), sticky="e")

        # Switches (Animações, Autostart, Fixar)
        self.animations_switch = ctk.CTkSwitch(
            set_body,
            text="Animações suaves ao abrir/fechar",
            variable=self._animations_var,
            font=ctk.CTkFont(size=11),
            progress_color=t["accent"],
            command=self._on_animations_switch,
        )
        self.animations_switch.grid(row=1, column=0, columnspan=3, pady=(0, 8), sticky="w")

        self.autostart_switch = ctk.CTkSwitch(
            set_body,
            text="Iniciar com o Windows",
            variable=self._autostart_var,
            font=ctk.CTkFont(size=11),
            progress_color=t["accent"],
            command=self._on_autostart_switch,
        )
        self.autostart_switch.grid(row=2, column=0, columnspan=3, pady=(0, 8), sticky="w")

        self.pin_switch = ctk.CTkSwitch(
            set_body,
            text="Fixar painel na tela",
            variable=self._pinned_var,
            font=ctk.CTkFont(size=11),
            progress_color=t["accent"],
            command=self._on_pin_switch,
        )
        self.pin_switch.grid(row=3, column=0, columnspan=3, pady=(0, 10), sticky="w")

        # Atalho global
        hk_row = tk.Frame(set_body, bg=t["list_band"], bd=0)
        hk_row.grid(row=4, column=0, columnspan=3, pady=(0, 10), sticky="ew")

        tk.Label(
            hk_row, text="Atalho:", font=("Segoe UI", 9), bg=t["list_band"], fg=t["text_muted"]
        ).pack(side="left", padx=(0, 6))

        self.hotkey_badge = tk.Label(
            hk_row,
            text="Ctrl+Alt+M",
            font=("Segoe UI", 9, "bold"),
            bg=t["drawer_band"],
            fg=t["badge_fg"],
            padx=7,
            pady=2,
        )
        self.hotkey_badge.pack(side="left")

        self.record_hotkey_btn = ctk.CTkButton(
            hk_row, text="Gravar", width=58, height=22, corner_radius=6,
            font=ctk.CTkFont(size=10, weight="bold"),
            fg_color=t["pill_bg"], hover_color=t["pill_hover"],
            command=self._toggle_record_hotkey,
        )
        self.record_hotkey_btn.pack(side="right", padx=(4, 0))

        ctk.CTkButton(
            hk_row, text="Limpar", width=48, height=22, corner_radius=6,
            font=ctk.CTkFont(size=10), fg_color="transparent", hover_color=DANGER_BG,
            text_color=t["text_muted"], command=self._clear_hotkey,
        ).pack(side="right")

        # Presets rápidos
        quick_row = tk.Frame(set_body, bg=t["list_band"], bd=0)
        quick_row.grid(row=5, column=0, columnspan=3, pady=(0, 8), sticky="ew")

        ctk.CTkButton(
            quick_row, text="100% Tudo", width=80, height=23, corner_radius=6,
            font=ctk.CTkFont(size=10), fg_color=t["pill_bg"], hover_color=t["pill_hover"],
            command=self._preset_full_volume,
        ).pack(side="left", padx=(0, 6))

        ctk.CTkButton(
            quick_row, text="Foco 30%", width=74, height=23, corner_radius=6,
            font=ctk.CTkFont(size=10), fg_color=t["pill_bg"], hover_color=t["pill_hover"],
            command=self._preset_focus_mode,
        ).pack(side="left", padx=(0, 6))

        ctk.CTkButton(
            quick_row, text="Mutar Apps", width=80, height=23, corner_radius=6,
            font=ctk.CTkFont(size=10), fg_color=DANGER_BG, hover_color=DANGER_HOVER,
            command=self._preset_mute_all_apps,
        ).pack(side="left")

        # Perfis
        prof_row = tk.Frame(set_body, bg=t["list_band"], bd=0)
        prof_row.grid(row=6, column=0, columnspan=3, pady=(0, 10), sticky="ew")

        self.profile_menu = ctk.CTkOptionMenu(
            prof_row,
            variable=self._selected_profile,
            values=self._get_profile_options(),
            width=142,
            height=23,
            font=ctk.CTkFont(size=10),
            fg_color=t["drawer_band"],
            button_color=t["pill_bg"],
            button_hover_color=t["accent"],
        )
        self.profile_menu.pack(side="left", padx=(0, 4))

        ctk.CTkButton(
            prof_row, text="Aplicar", width=50, height=23, corner_radius=6,
            font=ctk.CTkFont(size=10, weight="bold"),
            fg_color=t["accent"], hover_color=t["accent_hover"],
            command=self._apply_selected_profile,
        ).pack(side="left", padx=(0, 4))

        ctk.CTkButton(
            prof_row, text="Salvar", width=46, height=23, corner_radius=6,
            font=ctk.CTkFont(size=10), fg_color=t["pill_bg"], hover_color=t["pill_hover"],
            command=self._save_profile_dialog,
        ).pack(side="left", padx=(0, 4))

        ctk.CTkButton(
            prof_row, text="X", width=24, height=23, corner_radius=6,
            font=ctk.CTkFont(size=10, weight="bold"), fg_color=t["pill_bg"], hover_color=DANGER_BG,
            command=self._delete_selected_profile,
        ).pack(side="left")

        # Rodapé de Ajustes: status + atualizações + sair
        foot_row = tk.Frame(self.settings_view, bg=t["drawer_band"], bd=0)
        foot_row.grid(row=2, column=0, sticky="ew")
        foot_row.grid_columnconfigure(0, weight=1)

        self.status_lbl = tk.Label(
            foot_row,
            text=f"Mixers v{__version__}",
            anchor="w",
            font=("Segoe UI", 9),
            bg=t["drawer_band"],
            fg=t["text_muted"],
        )
        self.status_lbl.grid(row=0, column=0, padx=(14, 4), pady=8, sticky="ew")

        ctk.CTkButton(
            foot_row, text="Atualizações", width=80, height=22, corner_radius=6,
            font=ctk.CTkFont(size=10), fg_color=t["pill_bg"], hover_color=t["pill_hover"],
            command=lambda: self.check_updates_async(manual=True),
        ).grid(row=0, column=1, padx=(0, 6), pady=7)

        ctk.CTkButton(
            foot_row, text="Sair", width=42, height=22, corner_radius=6,
            font=ctk.CTkFont(size=10), fg_color="transparent", hover_color=DANGER_BG,
            text_color=t["text_muted"], command=self.quit_app,
        ).grid(row=0, column=2, padx=(0, 10), pady=7)

        # Inicia mostrando o Mixer por cima
        self.mixer_view.tkraise()

    def _on_apps_wheel(self, event) -> None:
        bbox = self.apps_canvas.bbox("all")
        if bbox and bbox[3] > self.apps_canvas.winfo_height():
            self.apps_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    # ------------------------------------------------------------------
    # Troca limpa de telas (Mixer <-> Ajustes) sem redimensionar janela
    # ------------------------------------------------------------------
    def _open_settings_view(self) -> None:
        self._settings_open = True
        self.settings_view.tkraise()

    def _close_settings_view(self) -> None:
        self._settings_open = False
        if self._recording_hotkey:
            self._cancel_record_hotkey()
        self.mixer_view.tkraise()

    # ------------------------------------------------------------------
    # Timers (0% CPU em segundo plano)
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
    # Visibilidade (abertura instantânea + fade suave opcional)
    # ------------------------------------------------------------------
    def toggle_visibility(self) -> None:
        if self._is_visible:
            self.hide_to_tray()
        else:
            self.show_from_tray()

    def show_from_tray(self) -> None:
        self._is_visible = True
        self._anim_token += 1
        # Sempre abre na tela principal do Mixer
        if self._settings_open:
            self._close_settings_view()
        self._update_window_geometry()
        try:
            self.attributes("-alpha", 0.0 if self._animations_enabled else self._alpha)
        except Exception:
            pass
        self.deiconify()
        self.lift()
        self.focus_force()
        if self._animations_enabled:
            self._animate_fade(0.0, self._alpha, duration_ms=95)
        self.after(20, lambda: self.refresh_audio_state(force_rebuild=False))
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
        if self._animations_enabled:
            def _finish_hide() -> None:
                if not self._is_visible:
                    self.withdraw()
                    try:
                        self.attributes("-alpha", self._alpha)
                    except Exception:
                        pass

            self._animate_fade(self._alpha, 0.0, duration_ms=65, on_done=_finish_hide)
        else:
            self._anim_token += 1
            self.withdraw()

    def _on_focus_out(self, _event) -> None:
        if self._pinned or self._dialog_open or self._recording_hotkey or not self._is_visible:
            return
        self.after(160, self._hide_if_still_unfocused)

    def _hide_if_still_unfocused(self) -> None:
        if self._pinned or self._dialog_open or self._recording_hotkey or not self._is_visible:
            return
        try:
            if is_our_process_foreground():
                return
            px, py = self.winfo_pointerxy()
            wx, wy = self.winfo_rootx(), self.winfo_rooty()
            ww, wh = self.winfo_width(), self.winfo_height()
            if wx <= px <= wx + ww and wy <= py <= wy + wh:
                return
            self.hide_to_tray()
        except Exception:
            pass

    def report_callback_exception(self, exc, val, tb) -> None:
        try:
            import traceback
            from pathlib import Path

            log_dir = Path(os.environ.get("APPDATA") or Path.home()) / "Mixers"
            log_dir.mkdir(parents=True, exist_ok=True)
            with open(log_dir / "mixers.log", "a", encoding="utf-8") as f:
                f.write("".join(traceback.format_exception(exc, val, tb)) + "\n")
        except Exception:
            pass
        self._set_status(f"Aviso: {self._truncate(str(val), 30)}")

    def quit_app(self) -> None:
        self._stop_live_loops()
        self._stop_mic_test()
        self.hotkey_manager.unregister()
        if self.tray is not None:
            self.tray.stop()
        self.destroy()

    # ------------------------------------------------------------------
    # Atualização ultrarrápida
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
        if not self._settings_open:
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
                    bar_col = PEAK_WHITE if label == "Silêncio" else color
                    row["slider"].set_peak(peak, bar_col)
                    if mic:
                        row["tooltip"].update_text(f"{mic.name}  •  {label}")

    def refresh_audio_state(self, force_rebuild: bool = False) -> None:
        try:
            master_vol = int(round(self.backend.get_master_volume() * 100))
            master_muted = self.backend.get_master_mute()
            mics = self.backend.list_microphones()
            sessions = self.backend.list_app_sessions()
            dev_name = self.backend.get_output_device_name()
        except Exception as exc:
            self._set_status(f"Erro: {exc}")
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

        if (mics_changed or keys_changed) and self._is_visible and not self._settings_open:
            if self._desired_height() != self._cur_height:
                self._update_window_geometry()

    # ------------------------------------------------------------------
    # Linhas de Aplicativos
    # ------------------------------------------------------------------
    def _render_app_list(self, force_rebuild: bool = False) -> None:
        if not force_rebuild:
            return
        t = self.theme

        for child in self.apps_inner.winfo_children():
            child.destroy()
        self._app_rows.clear()
        self._last_app_pct.clear()
        self._last_app_peak.clear()

        sessions = list(self._current_sessions.values())
        if not sessions:
            tk.Label(
                self.apps_inner,
                text="Nenhum aplicativo reproduzindo áudio.",
                font=("Segoe UI", 10),
                bg=t["list_band"],
                fg=t["text_muted"],
            ).grid(row=0, column=0, padx=16, pady=14, sticky="w")
            return

        for idx, session in enumerate(sessions):
            row = tk.Frame(self.apps_inner, bg=t["list_band"], bd=0)
            row.grid(row=idx, column=0, sticky="ew")
            row.grid_columnconfigure(1, weight=1)

            vol_pct = int(round(session.volume * 100))
            self._last_app_pct[session.app_id] = vol_pct

            icon_btn = ctk.CTkButton(
                row,
                text="",
                image=get_app_icon(
                    session.app_id,
                    session.display_name,
                    exe_path=session.exe_path,
                    muted=session.muted,
                    size=22,
                ),
                width=36,
                height=36,
                corner_radius=6,
                fg_color="transparent",
                hover_color=t["row_hover"],
                command=lambda aid=session.app_id: self._toggle_app_mute(aid),
            )
            icon_btn.grid(row=0, column=0, padx=(10, 6), pady=4)
            HoverTooltip(icon_btn, session.display_name)

            slider = self._make_slider(
                row,
                bg_color=t["list_band"],
                value=vol_pct,
                muted=session.muted,
                on_change=lambda val, aid=session.app_id: self._on_app_slider(aid, val),
                height=32,
            )
            init_peak = 0.0 if session.muted else session.peak_level
            slider.set_peak(init_peak, PEAK_WHITE)
            self._last_app_peak[session.app_id] = init_peak
            slider.grid(row=0, column=1, padx=4, pady=4, sticky="ew")

            pct_lbl = tk.Label(
                row,
                text=str(vol_pct),
                width=3,
                anchor="e",
                font=("Segoe UI", 13),
                bg=t["list_band"],
                fg=t["text_muted"] if session.muted else t["text_primary"],
            )
            pct_lbl.grid(row=0, column=2, padx=(6, 16), pady=4)

            self._app_rows[session.app_id] = {
                "icon_btn": icon_btn,
                "slider": slider,
                "pct_lbl": pct_lbl,
            }

    def _sync_existing_rows(self) -> None:
        t = self.theme
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
                fg=t["text_muted"] if session.muted else t["text_primary"]
            )
            widgets["icon_btn"].configure(
                image=get_app_icon(
                    session.app_id,
                    session.display_name,
                    exe_path=session.exe_path,
                    muted=session.muted,
                    size=22,
                )
            )

    # ------------------------------------------------------------------
    # Microfones
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
                fg_color=self.theme["header_hover"],
                hover_color=self.theme["accent"],
            )

    def _toggle_mics_section(self) -> None:
        self._mics_expanded = not self._mics_expanded
        self.settings.set("mics_expanded", self._mics_expanded)
        self.mics_arrow_lbl.configure(text="⌄" if self._mics_expanded else "›")
        if self._mics_expanded:
            self.mics_body.grid(row=4, column=0, pady=(4, 6), sticky="ew")
        else:
            self._stop_mic_test()
            self.mics_body.grid_forget()

    def _render_microphones(self) -> None:
        t = self.theme
        for child in self.mics_body.winfo_children():
            child.destroy()
        self._mic_rows.clear()
        self._last_mic_pct.clear()
        self._last_mic_peak.clear()
        self._last_mic_quality.clear()

        mics = list(self._current_mics.values())
        if not mics:
            tk.Label(
                self.mics_body,
                text="Nenhum microfone ativo.",
                font=("Segoe UI", 10),
                bg=t["list_band"],
                fg=t["text_muted"],
            ).grid(row=0, column=0, padx=16, pady=10, sticky="w")
            return

        for idx, mic in enumerate(mics):
            row = tk.Frame(self.mics_body, bg=t["list_band"], bd=0)
            row.grid(row=idx, column=0, sticky="ew")
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
                image=get_mic_icon(muted=mic.muted, size=20),
                width=36,
                height=36,
                corner_radius=6,
                fg_color="transparent",
                hover_color=t["row_hover"],
                command=lambda did=mic.device_id: self._toggle_mic_mute(did),
            )
            icon_btn.grid(row=0, column=0, padx=(10, 6), pady=4)
            tooltip = HoverTooltip(icon_btn, f"{mic.name}  •  {q_label}")

            bar_col = PEAK_WHITE if q_label == "Silêncio" else q_color
            slider = self._make_slider(
                row,
                bg_color=t["list_band"],
                value=vol_pct,
                muted=mic.muted,
                peak_color=bar_col,
                on_change=lambda val, did=mic.device_id: self._on_mic_slider(did, val),
                height=32,
            )
            slider.set_peak(init_peak, bar_col)
            slider.grid(row=0, column=1, padx=4, pady=4, sticky="ew")

            pct_lbl = tk.Label(
                row,
                text=str(vol_pct),
                width=3,
                anchor="e",
                font=("Segoe UI", 13),
                bg=t["list_band"],
                fg=t["text_muted"] if mic.muted else t["text_primary"],
            )
            pct_lbl.grid(row=0, column=2, padx=(6, 16), pady=4)

            self._mic_rows[mic.device_id] = {
                "icon_btn": icon_btn,
                "slider": slider,
                "pct_lbl": pct_lbl,
                "tooltip": tooltip,
            }

    def _sync_existing_mics(self) -> None:
        t = self.theme
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
                fg=t["text_muted"] if mic.muted else t["text_primary"]
            )
            widgets["icon_btn"].configure(image=get_mic_icon(muted=mic.muted, size=20))

    # ------------------------------------------------------------------
    # Eventos de áudio
    # ------------------------------------------------------------------
    def _apply_master_mute_visual(self, muted: bool) -> None:
        self.master_mute_btn.configure(image=get_speaker_icon(muted=muted, size=22))
        self.master_slider.set_muted(muted)
        self.master_pct_lbl.configure(
            fg=self.theme["text_muted"] if muted else self.theme["text_primary"]
        )

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
            row["pct_lbl"].configure(
                fg=self.theme["text_muted"] if new_state else self.theme["text_primary"]
            )
            row["icon_btn"].configure(
                image=get_app_icon(
                    session.app_id,
                    session.display_name,
                    exe_path=session.exe_path,
                    muted=new_state,
                    size=22,
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
            row["pct_lbl"].configure(
                fg=self.theme["text_muted"] if new_state else self.theme["text_primary"]
            )
            row["icon_btn"].configure(image=get_mic_icon(muted=new_state, size=20))
            q_label, _ = classify_mic_quality(0.0, muted=new_state)
            row["tooltip"].update_text(f"{mic.name}  •  {q_label}")

    # ------------------------------------------------------------------
    # Ajustes, Animações, Atalho Global, Perfis & Presets
    # ------------------------------------------------------------------
    def _on_animations_switch(self) -> None:
        self._animations_enabled = bool(self._animations_var.get())
        self.settings.set("animations", self._animations_enabled)
        self._set_status(
            "Animações ativadas." if self._animations_enabled else "Modo sequinho ativo."
        )

    def _on_pin_switch(self) -> None:
        self._pinned = bool(self._pinned_var.get())
        self._set_status("Painel fixado." if self._pinned else "Oculta ao clicar fora.")

    def _on_alpha_change(self, pct: int) -> None:
        clamped = max(65, min(100, int(pct)))
        self._alpha = clamped / 100.0
        self.alpha_lbl.configure(text=f"{clamped}%")
        try:
            self.attributes("-alpha", self._alpha)
        except Exception:
            pass
        if self._alpha_save_timer_id is not None:
            try:
                self.after_cancel(self._alpha_save_timer_id)
            except Exception:
                pass
        self._alpha_save_timer_id = self.after(
            350, lambda: self.settings.set("alpha", round(self._alpha, 2))
        )

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
            text="Cancelar", fg_color=self.theme["accent"], text_color="#FFFFFF"
        )
        self.hotkey_badge.configure(text="Pressione...")
        self.focus_force()

    def _cancel_record_hotkey(self) -> None:
        self._recording_hotkey = False
        self.record_hotkey_btn.configure(
            text="Gravar", fg_color=self.theme["pill_bg"], text_color=self.theme["text_primary"]
        )
        self._update_hotkey_badge(self.hotkey_manager.current_hotkey)

    def _clear_hotkey(self) -> None:
        self._recording_hotkey = False
        self.hotkey_manager.register("")
        self.settings.set("hotkey", "")
        self.record_hotkey_btn.configure(
            text="Gravar", fg_color=self.theme["pill_bg"], text_color=self.theme["text_primary"]
        )
        self._update_hotkey_badge("")
        self._set_status("Atalho desativado.")

    def _on_global_key_press(self, event) -> None:
        keysym = str(getattr(event, "keysym", ""))
        if not self._recording_hotkey:
            if keysym == "Escape":
                if self._settings_open:
                    self._close_settings_view()
                else:
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
            text="Gravar", fg_color=self.theme["pill_bg"], text_color=self.theme["text_primary"]
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
            self._set_status("Apps em 100%.")

    def _preset_focus_mode(self) -> None:
        for app_id in list(self._current_sessions):
            self.backend.set_app_mute(app_id, False)
            self.backend.set_app_volume(app_id, 0.30)
        if self._is_visible:
            self.refresh_audio_state(force_rebuild=False)
            self._set_status("Modo Foco (30%).")

    def _preset_mute_all_apps(self) -> None:
        for app_id in list(self._current_sessions):
            self.backend.set_app_mute(app_id, True)
        if self._is_visible:
            self.refresh_audio_state(force_rebuild=False)
            self._set_status("Apps mutados.")

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
    # Auto-Updater
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
            self.update_banner.grid(row=1, column=0, sticky="ew")
            if self._is_visible and not self._settings_open:
                self._update_window_geometry()
            self._set_status(f"v{info.version} pronta (volte ao Mixer).")
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
