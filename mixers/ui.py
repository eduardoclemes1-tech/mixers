"""Interface repaginada: fundo transparente, cards flutuantes discretos e controles 100% nítidos."""

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
from mixers.windows_integration import (
    apply_windows_glass_style,
    compute_bottom_right_position,
    get_work_area,
    is_autostart_enabled,
    set_autostart,
)

# Cor-chave escura para transparência real do fundo no Windows (sem halo claro nas bordas)
CHROMA_KEY = "#010203"
SOLID_BG = "#0B0E14"

# Paleta clean e discreta (controles 100% nítidos)
CARD_SURFACE = "#121722"
CARD_INNER = "#0D111A"
CARD_BORDER = "#263044"
PILL_BG = "#1A2233"
PILL_HOVER = "#26324A"
ACCENT = "#38BDF8"
ACCENT_HOVER = "#0EA5E9"
MIC_ACCENT = "#34D399"
MUTED_BG = "#7F1D2D"
MUTED_HOVER = "#991B1B"
TEXT_PRIMARY = "#F8FAFC"
TEXT_SECONDARY = "#94A3B8"


class MixersApp(ctk.CTk):
    """Painel flutuante clean com fundo transparente e controles nítidos no canto inferior direito."""

    WINDOW_WIDTH = 368
    WINDOW_HEIGHT = 576
    SESSION_REFRESH_MS = 3000
    METER_REFRESH_MS = 160
    METER_EPSILON = 0.025

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
        self._transparent_bg = bool(self.settings.get("transparent_bg", True))
        self._alpha = max(0.75, min(1.0, float(self.settings.get("alpha", 1.0))))
        self._mics_expanded = bool(self.settings.get("mics_expanded", True))
        saved_hotkey = str(self.settings.get("hotkey", "Ctrl+Alt+M"))

        self._surface_bg = (
            CHROMA_KEY if (self._transparent_bg and sys.platform == "win32") else SOLID_BG
        )

        self.title(f"Mixers v{__version__}")
        self.configure(fg_color=self._surface_bg)
        self.resizable(False, False)

        # Estado visual, animações e otimização
        self._pinned = False
        self._settings_open = False
        self._dialog_open = False
        self._recording_hotkey = False
        self._is_visible = not start_minimized
        self._anim_token = 0
        self._target_pos: tuple[int, int] = (0, 0)

        self._session_timer_id: str | None = None
        self._meter_timer_id: str | None = None
        self._last_slider_ts: float = 0.0
        self._last_master_pct: int = -1
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

        self._search_var = ctk.StringVar(value="")
        self._search_var.trace_add("write", lambda *_: self._render_app_list(force_rebuild=True))
        self._selected_profile = ctk.StringVar(value="Sem perfis salvos")
        self._autostart_var = ctk.BooleanVar(value=is_autostart_enabled())
        self._transparent_bg_var = ctk.BooleanVar(value=self._transparent_bg)
        self._pending_update: UpdateInfo | None = None
        self._updating = False

        # Estilo flyout nativo do Windows (sem borda e sem ícone extra na barra de tarefas)
        if sys.platform == "win32":
            self.overrideredirect(True)
            try:
                self.attributes("-toolwindow", True)
            except Exception:
                pass
        self.attributes("-topmost", True)
        self._apply_transparency_mode()

        self._build_layout()
        self._compute_and_set_position()
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

        # Verifica atualização 3s após iniciar (em background)
        self.after(3000, lambda: self.check_updates_async(manual=False))

    # ------------------------------------------------------------------
    # Transparência real do fundo + posicionamento fixo + animações
    # ------------------------------------------------------------------
    def _apply_transparency_mode(self) -> None:
        use_chroma = self._transparent_bg and sys.platform == "win32"
        self._surface_bg = CHROMA_KEY if use_chroma else SOLID_BG

        try:
            self.configure(fg_color=self._surface_bg)
        except Exception:
            pass

        if sys.platform == "win32":
            try:
                self.wm_attributes("-transparentcolor", CHROMA_KEY if use_chroma else "")
            except Exception:
                pass

        try:
            self.attributes("-alpha", self._alpha)
        except Exception:
            pass

        if hasattr(self, "shell"):
            self.shell.configure(
                fg_color=self._surface_bg,
                border_width=0 if use_chroma else 1,
            )
        if hasattr(self, "apps_scroll"):
            self.apps_scroll.configure(fg_color=self._surface_bg)

    def _compute_and_set_position(self, y_offset: int = 0) -> None:
        self.update_idletasks()
        try:
            scale = float(self._get_window_scaling())
        except Exception:
            scale = 1.0

        win_w_px = int(round(self.WINDOW_WIDTH * scale))
        win_h_px = int(round(self.WINDOW_HEIGHT * scale))
        work_area = get_work_area(self.winfo_screenwidth(), self.winfo_screenheight())
        x, y = compute_bottom_right_position(win_w_px, win_h_px, work_area, margin=12)
        self._target_pos = (x, y)
        self.geometry(f"{self.WINDOW_WIDTH}x{self.WINDOW_HEIGHT}+{x}+{y + y_offset}")

    def _animate_open(self) -> None:
        """Animação sutil estilo Windows 11: desliza 14px para cima com fade-in (~120ms)."""
        self._anim_token += 1
        token = self._anim_token
        steps = 8
        slide_px = 14
        x, target_y = self._target_pos

        try:
            self.attributes("-alpha", 0.0)
        except Exception:
            return
        self.geometry(f"{self.WINDOW_WIDTH}x{self.WINDOW_HEIGHT}+{x}+{target_y + slide_px}")

        def _step(i: int) -> None:
            if token != self._anim_token or not self._is_visible:
                return
            t = i / steps
            eased = 1.0 - (1.0 - t) ** 3
            cur_y = int(round(target_y + slide_px * (1.0 - eased)))
            cur_alpha = round(self._alpha * eased, 3)
            self.geometry(f"{self.WINDOW_WIDTH}x{self.WINDOW_HEIGHT}+{x}+{cur_y}")
            try:
                self.attributes("-alpha", cur_alpha)
            except Exception:
                pass
            if i < steps:
                self.after(15, lambda: _step(i + 1))

        _step(1)

    def _animate_close(self) -> None:
        """Animação rápida e discreta ao recolher para a bandeja (~70ms)."""
        self._anim_token += 1
        token = self._anim_token
        steps = 5
        slide_px = 10
        x, target_y = self._target_pos

        def _step(i: int) -> None:
            if token != self._anim_token or self._is_visible:
                return
            t = i / steps
            cur_y = int(round(target_y + slide_px * t))
            cur_alpha = max(0.0, round(self._alpha * (1.0 - t), 3))
            self.geometry(f"{self.WINDOW_WIDTH}x{self.WINDOW_HEIGHT}+{x}+{cur_y}")
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
    # Layout Repaginado: Cards Flutuantes Discretos sobre Fundo Transparente
    # ------------------------------------------------------------------
    def _build_layout(self) -> None:
        use_chroma = self._transparent_bg and sys.platform == "win32"

        self.shell = ctk.CTkFrame(
            self,
            fg_color=self._surface_bg,
            border_color=CARD_BORDER,
            border_width=0 if use_chroma else 1,
            corner_radius=0 if use_chroma else 14,
        )
        self.shell.pack(fill="both", expand=True)
        self.shell.grid_columnconfigure(0, weight=1)
        self.shell.grid_rowconfigure(6, weight=1)

        # Row 0: Cabeçalho flutuante minimalista
        header = ctk.CTkFrame(
            self.shell,
            fg_color=CARD_SURFACE,
            border_color=CARD_BORDER,
            border_width=1,
            corner_radius=12,
        )
        header.grid(row=0, column=0, padx=6, pady=(6, 4), sticky="ew")
        header.grid_columnconfigure(0, weight=1)

        title_row = ctk.CTkFrame(header, fg_color="transparent")
        title_row.grid(row=0, column=0, padx=(12, 6), pady=7, sticky="w")

        ctk.CTkLabel(
            title_row,
            text="Mixers",
            font=ctk.CTkFont(size=15, weight="bold"),
            text_color=TEXT_PRIMARY,
        ).pack(anchor="w")

        self.device_lbl = ctk.CTkLabel(
            title_row,
            text=self._truncate(self.backend.get_output_device_name(), 28),
            font=ctk.CTkFont(size=10),
            text_color=TEXT_SECONDARY,
        )
        self.device_lbl.pack(anchor="w")

        btn_group = ctk.CTkFrame(header, fg_color="transparent")
        btn_group.grid(row=0, column=1, padx=(0, 8), pady=7, sticky="e")

        self.pin_btn = ctk.CTkButton(
            btn_group,
            text="Fixar",
            width=44,
            height=24,
            corner_radius=7,
            font=ctk.CTkFont(size=10, weight="bold"),
            fg_color=PILL_BG,
            hover_color=PILL_HOVER,
            text_color=TEXT_SECONDARY,
            command=self._toggle_pin,
        )
        self.pin_btn.pack(side="left", padx=(0, 4))

        self.settings_btn = ctk.CTkButton(
            btn_group,
            text="Ajustes",
            width=52,
            height=24,
            corner_radius=7,
            font=ctk.CTkFont(size=10, weight="bold"),
            fg_color=PILL_BG,
            hover_color=PILL_HOVER,
            text_color=TEXT_SECONDARY,
            command=self._toggle_settings_drawer,
        )
        self.settings_btn.pack(side="left", padx=(0, 4))

        ctk.CTkButton(
            btn_group,
            text="—",
            width=26,
            height=24,
            corner_radius=7,
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color=PILL_BG,
            hover_color=PILL_HOVER,
            text_color=TEXT_PRIMARY,
            command=self.hide_to_tray,
        ).pack(side="left")

        # Row 1: Gaveta retrátil de Ajustes
        self.settings_drawer = ctk.CTkFrame(
            self.shell,
            fg_color=CARD_SURFACE,
            border_color=CARD_BORDER,
            border_width=1,
            corner_radius=12,
        )
        self.settings_drawer.grid_columnconfigure(1, weight=1)

        self.transparent_bg_switch = ctk.CTkSwitch(
            self.settings_drawer,
            text="Fundo transparente (cards flutuantes)",
            variable=self._transparent_bg_var,
            font=ctk.CTkFont(size=11, weight="bold"),
            progress_color=ACCENT,
            command=self._on_transparent_bg_switch,
        )
        self.transparent_bg_switch.grid(
            row=0, column=0, columnspan=3, padx=12, pady=(10, 4), sticky="w"
        )

        ctk.CTkLabel(
            self.settings_drawer,
            text="Opacidade cards",
            font=ctk.CTkFont(size=11),
            text_color=TEXT_SECONDARY,
        ).grid(row=1, column=0, padx=(12, 6), pady=(2, 4), sticky="w")

        self.alpha_slider = ctk.CTkSlider(
            self.settings_drawer,
            from_=75,
            to=100,
            number_of_steps=25,
            height=14,
            progress_color=ACCENT,
            button_color=TEXT_PRIMARY,
            button_hover_color=ACCENT,
            command=self._on_alpha_change,
        )
        self.alpha_slider.set(int(round(self._alpha * 100)))
        self.alpha_slider.grid(row=1, column=1, padx=4, pady=(2, 4), sticky="ew")

        self.alpha_lbl = ctk.CTkLabel(
            self.settings_drawer,
            text=f"{int(round(self._alpha * 100))}%",
            width=36,
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=TEXT_PRIMARY,
        )
        self.alpha_lbl.grid(row=1, column=2, padx=(4, 10), pady=(2, 4))

        # Atalho global
        hk_row = ctk.CTkFrame(self.settings_drawer, fg_color="transparent")
        hk_row.grid(row=2, column=0, columnspan=3, padx=10, pady=(2, 6), sticky="ew")

        ctk.CTkLabel(
            hk_row,
            text="Atalho:",
            font=ctk.CTkFont(size=11),
            text_color=TEXT_SECONDARY,
        ).pack(side="left", padx=(2, 6))

        self.hotkey_badge = ctk.CTkLabel(
            hk_row,
            text="Ctrl+Alt+M",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=ACCENT,
            fg_color=CARD_INNER,
            corner_radius=6,
            padx=8,
            pady=2,
        )
        self.hotkey_badge.pack(side="left", padx=(0, 6))

        self.record_hotkey_btn = ctk.CTkButton(
            hk_row,
            text="Gravar",
            width=60,
            height=23,
            corner_radius=7,
            font=ctk.CTkFont(size=10, weight="bold"),
            fg_color=PILL_BG,
            hover_color=PILL_HOVER,
            command=self._toggle_record_hotkey,
        )
        self.record_hotkey_btn.pack(side="right", padx=(4, 0))

        ctk.CTkButton(
            hk_row,
            text="Limpar",
            width=50,
            height=23,
            corner_radius=7,
            font=ctk.CTkFont(size=10),
            fg_color="transparent",
            hover_color=MUTED_BG,
            text_color=TEXT_SECONDARY,
            command=self._clear_hotkey,
        ).pack(side="right")

        self.autostart_switch = ctk.CTkSwitch(
            self.settings_drawer,
            text="Iniciar com o Windows",
            variable=self._autostart_var,
            font=ctk.CTkFont(size=11),
            progress_color=ACCENT,
            command=self._on_autostart_switch,
        )
        self.autostart_switch.grid(
            row=3, column=0, columnspan=3, padx=12, pady=(2, 6), sticky="w"
        )

        prof_row = ctk.CTkFrame(self.settings_drawer, fg_color="transparent")
        prof_row.grid(row=4, column=0, columnspan=3, padx=10, pady=(2, 6), sticky="ew")

        self.profile_menu = ctk.CTkOptionMenu(
            prof_row,
            variable=self._selected_profile,
            values=self._get_profile_options(),
            width=136,
            height=24,
            font=ctk.CTkFont(size=11),
            fg_color=CARD_INNER,
            button_color=PILL_BG,
            button_hover_color=ACCENT,
        )
        self.profile_menu.pack(side="left", padx=(0, 4))

        ctk.CTkButton(
            prof_row,
            text="Aplicar",
            width=52,
            height=24,
            font=ctk.CTkFont(size=10, weight="bold"),
            fg_color=ACCENT,
            hover_color=ACCENT_HOVER,
            text_color="#0B1120",
            command=self._apply_selected_profile,
        ).pack(side="left", padx=(0, 4))

        ctk.CTkButton(
            prof_row,
            text="Salvar",
            width=48,
            height=24,
            font=ctk.CTkFont(size=10),
            fg_color=PILL_BG,
            hover_color=PILL_HOVER,
            command=self._save_profile_dialog,
        ).pack(side="left", padx=(0, 4))

        ctk.CTkButton(
            prof_row,
            text="X",
            width=26,
            height=24,
            font=ctk.CTkFont(size=10, weight="bold"),
            fg_color=PILL_BG,
            hover_color=MUTED_BG,
            command=self._delete_selected_profile,
        ).pack(side="left")

        upd_row = ctk.CTkFrame(self.settings_drawer, fg_color="transparent")
        upd_row.grid(row=5, column=0, columnspan=3, padx=10, pady=(0, 9), sticky="ew")

        ctk.CTkLabel(
            upd_row,
            text=f"Versão v{__version__}",
            font=ctk.CTkFont(size=10),
            text_color=TEXT_SECONDARY,
        ).pack(side="left", padx=(2, 0))

        self.check_update_btn = ctk.CTkButton(
            upd_row,
            text="Verificar atualização",
            width=130,
            height=23,
            corner_radius=7,
            font=ctk.CTkFont(size=10, weight="bold"),
            fg_color=PILL_BG,
            hover_color=PILL_HOVER,
            command=lambda: self.check_updates_async(manual=True),
        )
        self.check_update_btn.pack(side="right")

        # Row 2: Banner de atualização disponível (oculto por padrão)
        self.update_banner = ctk.CTkFrame(
            self.shell,
            fg_color="#0C2D48",
            border_color=ACCENT,
            border_width=1,
            corner_radius=11,
        )
        self.update_banner.grid_columnconfigure(0, weight=1)

        self.update_banner_lbl = ctk.CTkLabel(
            self.update_banner,
            text="Nova versão disponível!",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=TEXT_PRIMARY,
            anchor="w",
        )
        self.update_banner_lbl.grid(row=0, column=0, padx=10, pady=6, sticky="w")

        self.update_now_btn = ctk.CTkButton(
            self.update_banner,
            text="Atualizar",
            width=78,
            height=23,
            corner_radius=7,
            font=ctk.CTkFont(size=10, weight="bold"),
            fg_color=ACCENT,
            hover_color=ACCENT_HOVER,
            text_color="#0B1120",
            command=self._start_update_download,
        )
        self.update_now_btn.grid(row=0, column=1, padx=(4, 8), pady=6)

        # Row 3: Card Volume Geral (Master)
        master_card = ctk.CTkFrame(
            self.shell,
            fg_color=CARD_SURFACE,
            border_color=CARD_BORDER,
            border_width=1,
            corner_radius=12,
        )
        master_card.grid(row=3, column=0, padx=6, pady=(0, 4), sticky="ew")
        master_card.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            master_card,
            text="Volume Geral",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=TEXT_PRIMARY,
        ).grid(row=0, column=0, columnspan=2, padx=11, pady=(8, 1), sticky="w")

        self.master_pct_lbl = ctk.CTkLabel(
            master_card,
            text="100%",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=ACCENT,
        )
        self.master_pct_lbl.grid(row=0, column=2, padx=11, pady=(8, 1), sticky="e")

        self.master_mute_btn = ctk.CTkButton(
            master_card,
            text="Som",
            width=48,
            height=24,
            corner_radius=7,
            font=ctk.CTkFont(size=10, weight="bold"),
            command=self._toggle_master_mute,
        )
        self.master_mute_btn.grid(row=1, column=0, padx=(11, 8), pady=(3, 5))

        self.master_slider = ctk.CTkSlider(
            master_card,
            from_=0,
            to=100,
            number_of_steps=100,
            height=15,
            progress_color=ACCENT,
            button_color=TEXT_PRIMARY,
            button_hover_color=ACCENT,
            command=self._on_master_slider,
        )
        self.master_slider.grid(row=1, column=1, columnspan=2, padx=(0, 11), pady=(3, 5), sticky="ew")

        self.master_meter = ctk.CTkProgressBar(
            master_card,
            height=3,
            corner_radius=2,
            fg_color=CARD_INNER,
            progress_color=ACCENT,
        )
        self.master_meter.set(0)
        self.master_meter.grid(row=2, column=0, columnspan=3, padx=11, pady=(0, 8), sticky="ew")

        # Row 4: Card de Microfones
        self.mics_card = ctk.CTkFrame(
            self.shell,
            fg_color=CARD_SURFACE,
            border_color=CARD_BORDER,
            border_width=1,
            corner_radius=12,
        )
        self.mics_card.grid(row=4, column=0, padx=6, pady=(0, 4), sticky="ew")
        self.mics_card.grid_columnconfigure(0, weight=1)

        mics_header = ctk.CTkFrame(self.mics_card, fg_color="transparent")
        mics_header.grid(row=0, column=0, padx=6, pady=(4, 2), sticky="ew")
        mics_header.grid_columnconfigure(0, weight=1)

        self.mics_toggle_btn = ctk.CTkButton(
            mics_header,
            text="Microfones (0)  ▾",
            anchor="w",
            height=25,
            corner_radius=8,
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color="transparent",
            hover_color=PILL_BG,
            text_color=TEXT_PRIMARY,
            command=self._toggle_mics_section,
        )
        self.mics_toggle_btn.grid(row=0, column=0, sticky="ew")

        self.mic_test_btn = ctk.CTkButton(
            mics_header,
            text="Testar",
            width=56,
            height=22,
            corner_radius=7,
            font=ctk.CTkFont(size=10, weight="bold"),
            fg_color="#132A23",
            hover_color="#1E3F35",
            text_color=MIC_ACCENT,
            command=self._toggle_mic_test,
        )
        self.mic_test_btn.grid(row=0, column=1, padx=(4, 4), sticky="e")

        self.mics_body = ctk.CTkFrame(self.mics_card, fg_color="transparent")
        self.mics_body.grid_columnconfigure(0, weight=1)
        if self._mics_expanded:
            self.mics_body.grid(row=1, column=0, padx=8, pady=(0, 7), sticky="ew")

        # Row 5: Barra compacta flutuante de ações rápidas + busca
        quick_card = ctk.CTkFrame(
            self.shell,
            fg_color=CARD_SURFACE,
            border_color=CARD_BORDER,
            border_width=1,
            corner_radius=11,
        )
        quick_card.grid(row=5, column=0, padx=6, pady=(0, 4), sticky="ew")

        quick_row = ctk.CTkFrame(quick_card, fg_color="transparent")
        quick_row.pack(fill="x", padx=6, pady=5)

        ctk.CTkButton(
            quick_row,
            text="100%",
            width=44,
            height=24,
            corner_radius=7,
            font=ctk.CTkFont(size=10, weight="bold"),
            fg_color=PILL_BG,
            hover_color=PILL_HOVER,
            command=self._preset_full_volume,
        ).pack(side="left", padx=(0, 4))

        ctk.CTkButton(
            quick_row,
            text="Foco",
            width=46,
            height=24,
            corner_radius=7,
            font=ctk.CTkFont(size=10, weight="bold"),
            fg_color=PILL_BG,
            hover_color=PILL_HOVER,
            command=self._preset_focus_mode,
        ).pack(side="left", padx=(0, 4))

        ctk.CTkButton(
            quick_row,
            text="Mutar",
            width=48,
            height=24,
            corner_radius=7,
            font=ctk.CTkFont(size=10, weight="bold"),
            fg_color=MUTED_BG,
            hover_color=MUTED_HOVER,
            command=self._preset_mute_all_apps,
        ).pack(side="left", padx=(0, 6))

        self.search_entry = ctk.CTkEntry(
            quick_row,
            placeholder_text="Filtrar app...",
            textvariable=self._search_var,
            height=24,
            corner_radius=7,
            font=ctk.CTkFont(size=11),
            fg_color=CARD_INNER,
            border_color=CARD_BORDER,
        )
        self.search_entry.pack(side="right", fill="x", expand=True)

        # Row 6: Lista rolável de cards flutuantes (fundo transparente entre os cards)
        self.apps_scroll = ctk.CTkScrollableFrame(
            self.shell,
            fg_color=self._surface_bg,
            scrollbar_button_color=CARD_BORDER,
            scrollbar_button_hover_color="#3B4A66",
        )
        self.apps_scroll.grid(row=6, column=0, padx=2, pady=(0, 4), sticky="nsew")
        self.apps_scroll.grid_columnconfigure(0, weight=1)

        # Row 7: Rodapé flutuante discreto
        footer = ctk.CTkFrame(
            self.shell,
            fg_color=CARD_SURFACE,
            border_color=CARD_BORDER,
            border_width=1,
            corner_radius=10,
        )
        footer.grid(row=7, column=0, padx=6, pady=(0, 6), sticky="ew")
        footer.grid_columnconfigure(0, weight=1)

        self.status_lbl = ctk.CTkLabel(
            footer,
            text="Pronto • segundo plano ativo",
            anchor="w",
            font=ctk.CTkFont(size=10),
            text_color=TEXT_SECONDARY,
        )
        self.status_lbl.grid(row=0, column=0, padx=(10, 4), pady=5, sticky="w")

        ctk.CTkButton(
            footer,
            text="Sair",
            width=38,
            height=20,
            corner_radius=6,
            font=ctk.CTkFont(size=10),
            fg_color="transparent",
            hover_color=MUTED_BG,
            text_color=TEXT_SECONDARY,
            command=self.quit_app,
        ).grid(row=0, column=1, padx=(0, 6), pady=4, sticky="e")

    # ------------------------------------------------------------------
    # Timers (0% CPU quando oculto)
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
    # Visibilidade e Bandeja (Segundo Plano)
    # ------------------------------------------------------------------
    def toggle_visibility(self) -> None:
        if self._is_visible:
            self.hide_to_tray()
        else:
            self.show_from_tray()

    def show_from_tray(self) -> None:
        self._is_visible = True
        self._compute_and_set_position(y_offset=14)
        self.deiconify()
        self.lift()
        self.focus_force()
        self.refresh_audio_state(force_rebuild=False)
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
    # Atualização ultrarrápida (cache COM + delta threshold)
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
            self.master_meter.set(master_peak)

        for app_id, row in self._app_rows.items():
            session = self._current_sessions.get(app_id)
            peak = 0.0 if (session and session.muted) else app_peaks.get(app_id, 0.0)
            prev = self._last_app_peak.get(app_id, -1.0)
            if abs(peak - prev) >= self.METER_EPSILON:
                self._last_app_peak[app_id] = peak
                row["meter"].set(peak)

        if self._mics_expanded:
            for dev_id, row in self._mic_rows.items():
                mic = self._current_mics.get(dev_id)
                muted = bool(mic.muted) if mic else False
                peak = 0.0 if muted else mic_peaks.get(dev_id, 0.0)
                prev = self._last_mic_peak.get(dev_id, -1.0)
                if abs(peak - prev) >= self.METER_EPSILON:
                    self._last_mic_peak[dev_id] = peak
                    row["meter"].set(peak)

                label, color = classify_mic_quality(peak, muted=muted)
                if self._last_mic_quality.get(dev_id) != label:
                    self._last_mic_quality[dev_id] = label
                    row["quality_lbl"].configure(text=label, text_color=color)
                    row["meter"].configure(progress_color=color)

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

        self.device_lbl.configure(text=self._truncate(dev_name, 30))
        if master_vol != self._last_master_pct:
            self._last_master_pct = master_vol
            self.master_slider.set(master_vol)
            self.master_pct_lbl.configure(text=f"{master_vol}%")
        self._style_mute_button(self.master_mute_btn, master_muted)

        # Microfones
        new_mics = {m.device_id: m for m in mics}
        mics_changed = list(new_mics.keys()) != list(self._current_mics.keys())
        self._current_mics = new_mics
        arrow = "▾" if self._mics_expanded else "▸"
        self.mics_toggle_btn.configure(text=f"Microfones ({len(mics)})  {arrow}")
        if force_rebuild or mics_changed:
            self._render_microphones()
        else:
            self._sync_existing_mics()

        # Aplicativos
        new_map = {s.app_id: s for s in sessions}
        keys_changed = list(new_map.keys()) != list(self._current_sessions.keys())
        self._current_sessions = new_map

        if force_rebuild or keys_changed:
            self._render_app_list(force_rebuild=True)
        else:
            self._sync_existing_rows()

        hk = self.hotkey_manager.current_hotkey
        hk_hint = f" • {hk}" if hk else ""
        self._set_status(f"{len(sessions)} app(s) • {len(mics)} mic(s){hk_hint}")

    # ------------------------------------------------------------------
    # Microfones (Sensibilidade, Mudo & Medidor de Voz)
    # ------------------------------------------------------------------
    def _toggle_mic_test(self) -> None:
        if self._mic_monitor.active:
            self._stop_mic_test()
            self._set_status("Teste de microfone parado.")
        else:
            if not self._mics_expanded:
                self._toggle_mics_section()
            if self._mic_monitor.start():
                self.mic_test_btn.configure(
                    text="Parar",
                    fg_color=MUTED_BG,
                    hover_color=MUTED_HOVER,
                    text_color=TEXT_PRIMARY,
                )
                self._set_status("Fale no microfone para ver o nível de captação.")
            else:
                self._set_status("Não foi possível iniciar o teste de microfone.")

    def _stop_mic_test(self) -> None:
        if self._mic_monitor.active:
            self._mic_monitor.stop()
        if hasattr(self, "mic_test_btn"):
            self.mic_test_btn.configure(
                text="Testar",
                fg_color="#132A23",
                hover_color="#1E3F35",
                text_color=MIC_ACCENT,
            )

    def _toggle_mics_section(self) -> None:
        self._mics_expanded = not self._mics_expanded
        self.settings.set("mics_expanded", self._mics_expanded)
        arrow = "▾" if self._mics_expanded else "▸"
        self.mics_toggle_btn.configure(
            text=f"Microfones ({len(self._current_mics)})  {arrow}"
        )
        if self._mics_expanded:
            self.mics_body.grid(row=1, column=0, padx=8, pady=(0, 7), sticky="ew")
        else:
            self._stop_mic_test()
            self.mics_body.grid_forget()

    def _render_microphones(self) -> None:
        for child in self.mics_body.winfo_children():
            child.destroy()
        self._mic_rows.clear()
        self._last_mic_pct.clear()
        self._last_mic_peak.clear()
        self._last_mic_quality.clear()

        if not self._current_mics:
            ctk.CTkLabel(
                self.mics_body,
                text="Nenhum microfone ativo detectado.",
                font=ctk.CTkFont(size=11),
                text_color=TEXT_SECONDARY,
            ).grid(row=0, column=0, padx=6, pady=6, sticky="w")
            return

        for idx, mic in enumerate(self._current_mics.values()):
            row_frame = ctk.CTkFrame(
                self.mics_body,
                fg_color=CARD_INNER,
                corner_radius=9,
            )
            row_frame.grid(row=idx, column=0, pady=2, sticky="ew")
            row_frame.grid_columnconfigure(1, weight=1)

            vol_pct = int(round(mic.volume * 100))
            self._last_mic_pct[mic.device_id] = vol_pct
            init_peak = 0.0 if mic.muted else mic.peak_level
            q_label, q_color = classify_mic_quality(init_peak, muted=mic.muted)
            self._last_mic_peak[mic.device_id] = init_peak
            self._last_mic_quality[mic.device_id] = q_label

            ctk.CTkLabel(
                row_frame,
                text=self._truncate(mic.name, 21),
                font=ctk.CTkFont(size=11, weight="bold"),
                text_color=TEXT_PRIMARY,
                anchor="w",
            ).grid(row=0, column=0, columnspan=2, padx=8, pady=(5, 1), sticky="w")

            right_meta = ctk.CTkFrame(row_frame, fg_color="transparent")
            right_meta.grid(row=0, column=2, padx=8, pady=(5, 1), sticky="e")

            quality_lbl = ctk.CTkLabel(
                right_meta,
                text=q_label,
                font=ctk.CTkFont(size=10, weight="bold"),
                text_color=q_color,
            )
            quality_lbl.pack(side="left", padx=(0, 6))

            pct_lbl = ctk.CTkLabel(
                right_meta,
                text=f"{vol_pct}%",
                font=ctk.CTkFont(size=11, weight="bold"),
                text_color=TEXT_SECONDARY if mic.muted else MIC_ACCENT,
            )
            pct_lbl.pack(side="left")

            mute_btn = ctk.CTkButton(
                row_frame,
                text="Mudo" if mic.muted else "Mic",
                width=44,
                height=21,
                corner_radius=6,
                font=ctk.CTkFont(size=10, weight="bold"),
                command=lambda did=mic.device_id: self._toggle_mic_mute(did),
            )
            self._style_mic_mute_button(mute_btn, mic.muted)
            mute_btn.grid(row=1, column=0, padx=(8, 6), pady=(2, 4))

            slider = ctk.CTkSlider(
                row_frame,
                from_=0,
                to=100,
                number_of_steps=100,
                height=14,
                progress_color=MIC_ACCENT,
                button_color=TEXT_PRIMARY,
                button_hover_color=MIC_ACCENT,
                command=lambda val, did=mic.device_id: self._on_mic_slider(did, val),
            )
            slider.set(vol_pct)
            slider.grid(row=1, column=1, columnspan=2, padx=(0, 8), pady=(2, 4), sticky="ew")

            meter = ctk.CTkProgressBar(
                row_frame,
                height=3,
                corner_radius=2,
                fg_color="#172033",
                progress_color=q_color,
            )
            meter.set(init_peak)
            meter.grid(row=2, column=0, columnspan=3, padx=8, pady=(0, 6), sticky="ew")

            self._mic_rows[mic.device_id] = {
                "mute_btn": mute_btn,
                "slider": slider,
                "pct_lbl": pct_lbl,
                "quality_lbl": quality_lbl,
                "meter": meter,
            }

    def _sync_existing_mics(self) -> None:
        for dev_id, widgets in self._mic_rows.items():
            mic = self._current_mics.get(dev_id)
            if not mic:
                continue
            vol_pct = int(round(mic.volume * 100))
            if vol_pct != self._last_mic_pct.get(dev_id):
                self._last_mic_pct[dev_id] = vol_pct
                widgets["slider"].set(vol_pct)
                widgets["pct_lbl"].configure(text=f"{vol_pct}%")
            widgets["pct_lbl"].configure(
                text_color=TEXT_SECONDARY if mic.muted else MIC_ACCENT
            )
            self._style_mic_mute_button(widgets["mute_btn"], mic.muted)

    def _on_mic_slider(self, device_id: str, value: float) -> None:
        pct = int(round(value))
        self._last_slider_ts = time.monotonic()
        if pct == self._last_mic_pct.get(device_id):
            return
        self._last_mic_pct[device_id] = pct
        if device_id in self._mic_rows:
            self._mic_rows[device_id]["pct_lbl"].configure(text=f"{pct}%")
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
            self._style_mic_mute_button(self._mic_rows[device_id]["mute_btn"], new_state)
            self._mic_rows[device_id]["pct_lbl"].configure(
                text_color=TEXT_SECONDARY if new_state else MIC_ACCENT
            )

    # ------------------------------------------------------------------
    # Lista de Aplicativos
    # ------------------------------------------------------------------
    def _render_app_list(self, force_rebuild: bool = False) -> None:
        if not force_rebuild:
            return

        for child in self.apps_scroll.winfo_children():
            child.destroy()
        self._app_rows.clear()
        self._last_app_pct.clear()
        self._last_app_peak.clear()

        query = self._search_var.get().strip().lower()
        filtered = [
            s
            for s in self._current_sessions.values()
            if not query or query in s.display_name.lower() or query in s.app_id.lower()
        ]

        if not filtered:
            empty_card = ctk.CTkFrame(
                self.apps_scroll,
                fg_color=CARD_SURFACE,
                border_color=CARD_BORDER,
                border_width=1,
                corner_radius=12,
            )
            empty_card.grid(row=0, column=0, padx=4, pady=4, sticky="ew")
            msg = (
                "Nenhum app encontrado."
                if query
                else "Nenhum aplicativo tocando som agora.\nAbra um navegador, música ou jogo."
            )
            ctk.CTkLabel(
                empty_card,
                text=msg,
                font=ctk.CTkFont(size=11),
                text_color=TEXT_SECONDARY,
                justify="center",
            ).pack(padx=12, pady=24)
            return

        for idx, session in enumerate(filtered):
            card = ctk.CTkFrame(
                self.apps_scroll,
                fg_color=CARD_SURFACE,
                border_color=CARD_BORDER,
                border_width=1,
                corner_radius=11,
            )
            card.grid(row=idx, column=0, padx=4, pady=3, sticky="ew")
            card.grid_columnconfigure(1, weight=1)

            vol_pct = int(round(session.volume * 100))
            self._last_app_pct[session.app_id] = vol_pct

            ctk.CTkLabel(
                card,
                text=self._truncate(session.display_name, 25),
                font=ctk.CTkFont(size=12, weight="bold"),
                text_color=TEXT_PRIMARY,
                anchor="w",
            ).grid(row=0, column=0, columnspan=2, padx=10, pady=(7, 1), sticky="w")

            pct_lbl = ctk.CTkLabel(
                card,
                text=f"{vol_pct}%",
                font=ctk.CTkFont(size=12, weight="bold"),
                text_color=TEXT_SECONDARY if session.muted else ACCENT,
            )
            pct_lbl.grid(row=0, column=2, padx=10, pady=(7, 1), sticky="e")

            mute_btn = ctk.CTkButton(
                card,
                text="Mudo" if session.muted else "Som",
                width=46,
                height=22,
                corner_radius=7,
                font=ctk.CTkFont(size=10, weight="bold"),
                command=lambda aid=session.app_id: self._toggle_app_mute(aid),
            )
            self._style_mute_button(mute_btn, session.muted)
            mute_btn.grid(row=1, column=0, padx=(10, 6), pady=(2, 5))

            slider = ctk.CTkSlider(
                card,
                from_=0,
                to=100,
                number_of_steps=100,
                height=14,
                progress_color=ACCENT,
                button_color=TEXT_PRIMARY,
                button_hover_color=ACCENT,
                command=lambda val, aid=session.app_id: self._on_app_slider(aid, val),
            )
            slider.set(vol_pct)
            slider.grid(row=1, column=1, columnspan=2, padx=(0, 10), pady=(2, 5), sticky="ew")

            meter = ctk.CTkProgressBar(
                card,
                height=3,
                corner_radius=2,
                fg_color=CARD_INNER,
                progress_color=ACCENT,
            )
            init_peak = 0.0 if session.muted else session.peak_level
            meter.set(init_peak)
            self._last_app_peak[session.app_id] = init_peak
            meter.grid(row=2, column=0, columnspan=3, padx=10, pady=(0, 7), sticky="ew")

            self._app_rows[session.app_id] = {
                "mute_btn": mute_btn,
                "slider": slider,
                "pct_lbl": pct_lbl,
                "meter": meter,
            }

    def _sync_existing_rows(self) -> None:
        for app_id, widgets in self._app_rows.items():
            session = self._current_sessions.get(app_id)
            if not session:
                continue
            vol_pct = int(round(session.volume * 100))
            if vol_pct != self._last_app_pct.get(app_id):
                self._last_app_pct[app_id] = vol_pct
                widgets["slider"].set(vol_pct)
                widgets["pct_lbl"].configure(text=f"{vol_pct}%")
            widgets["pct_lbl"].configure(
                text_color=TEXT_SECONDARY if session.muted else ACCENT
            )
            self._style_mute_button(widgets["mute_btn"], session.muted)

    # ------------------------------------------------------------------
    # Eventos de áudio e ajustes
    # ------------------------------------------------------------------
    def _on_master_slider(self, value: float) -> None:
        pct = int(round(value))
        self._last_slider_ts = time.monotonic()
        if pct == self._last_master_pct:
            return
        self._last_master_pct = pct
        self.master_pct_lbl.configure(text=f"{pct}%")
        self.backend.set_master_volume(pct / 100.0)

    def _toggle_master_mute(self) -> None:
        new_state = not self.backend.get_master_mute()
        self.backend.set_master_mute(new_state)
        self._style_mute_button(self.master_mute_btn, new_state)

    def _on_app_slider(self, app_id: str, value: float) -> None:
        pct = int(round(value))
        self._last_slider_ts = time.monotonic()
        if pct == self._last_app_pct.get(app_id):
            return
        self._last_app_pct[app_id] = pct
        if app_id in self._app_rows:
            self._app_rows[app_id]["pct_lbl"].configure(text=f"{pct}%")
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
            self._style_mute_button(self._app_rows[app_id]["mute_btn"], new_state)
            self._app_rows[app_id]["pct_lbl"].configure(
                text_color=TEXT_SECONDARY if new_state else ACCENT
            )

    def _toggle_pin(self) -> None:
        self._pinned = not self._pinned
        if self._pinned:
            self.pin_btn.configure(fg_color=ACCENT, text_color="#0B1120")
            self._set_status("Painel fixado na tela.")
        else:
            self.pin_btn.configure(fg_color=PILL_BG, text_color=TEXT_SECONDARY)
            self._set_status("Oculta automaticamente ao clicar fora.")

    def _toggle_settings_drawer(self) -> None:
        self._settings_open = not self._settings_open
        if self._settings_open:
            self.settings_drawer.grid(row=1, column=0, padx=6, pady=(0, 4), sticky="ew")
            self.settings_btn.configure(fg_color=ACCENT, text_color="#0B1120")
        else:
            if self._recording_hotkey:
                self._cancel_record_hotkey()
            self.settings_drawer.grid_forget()
            self.settings_btn.configure(fg_color=PILL_BG, text_color=TEXT_SECONDARY)

    def _on_transparent_bg_switch(self) -> None:
        self._transparent_bg = bool(self._transparent_bg_var.get())
        self.settings.set("transparent_bg", self._transparent_bg)
        self._apply_transparency_mode()
        self._set_status(
            "Fundo transparente ativado." if self._transparent_bg else "Fundo sólido ativado."
        )

    def _on_alpha_change(self, value: float) -> None:
        pct = int(round(value))
        self._alpha = pct / 100.0
        self.alpha_lbl.configure(text=f"{pct}%")
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
            self._set_status("Não foi possível alterar a inicialização automática.")
        else:
            self._set_status(
                "Iniciar com o Windows ativado." if desired else "Iniciar com o Windows desativado."
            )

    def _toggle_autostart_from_tray(self) -> None:
        new_val = not is_autostart_enabled()
        if set_autostart(new_val):
            self._autostart_var.set(new_val)

    # ------------------------------------------------------------------
    # Gravação de Atalho Global definido pelo usuário
    # ------------------------------------------------------------------
    def _toggle_record_hotkey(self) -> None:
        if self._recording_hotkey:
            self._cancel_record_hotkey()
            return
        self._recording_hotkey = True
        self.record_hotkey_btn.configure(
            text="Cancelar", fg_color=ACCENT, text_color="#0B1120"
        )
        self.hotkey_badge.configure(text="Pressione teclas...")
        self._set_status("Pressione o atalho desejado (ex: Ctrl+Alt+M) ou Esc.")
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
        self._set_status("Atalho global desativado.")

    def _on_global_key_press(self, event) -> None:
        keysym = str(getattr(event, "keysym", ""))
        if not self._recording_hotkey:
            if keysym == "Escape":
                self.hide_to_tray()
            return

        if keysym == "Escape":
            self._cancel_record_hotkey()
            self._set_status("Gravação de atalho cancelada.")
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

    # ------------------------------------------------------------------
    # Presets e Perfis
    # ------------------------------------------------------------------
    def _preset_full_volume(self) -> None:
        for app_id in list(self._current_sessions):
            self.backend.set_app_mute(app_id, False)
            self.backend.set_app_volume(app_id, 1.0)
        if self._is_visible:
            self.refresh_audio_state(force_rebuild=False)
            self._set_status("Todos os apps restaurados para 100%.")

    def _preset_focus_mode(self) -> None:
        for app_id in list(self._current_sessions):
            self.backend.set_app_mute(app_id, False)
            self.backend.set_app_volume(app_id, 0.30)
        if self._is_visible:
            self.refresh_audio_state(force_rebuild=False)
            self._set_status("Modo Foco aplicado (30%).")

    def _preset_mute_all_apps(self) -> None:
        for app_id in list(self._current_sessions):
            self.backend.set_app_mute(app_id, True)
        if self._is_visible:
            self.refresh_audio_state(force_rebuild=False)
            self._set_status("Todos os apps foram mutados.")

    def _get_profile_options(self) -> list[str]:
        names = self.profile_manager.list_names()
        return names if names else ["Sem perfis salvos"]

    def _refresh_profile_menu(self, select_name: str | None = None) -> None:
        options = self._get_profile_options()
        self.profile_menu.configure(values=options)
        if select_name and select_name in options:
            self._selected_profile.set(select_name)
        else:
            self._selected_profile.set(options[0])

    def _save_profile_dialog(self) -> None:
        self._dialog_open = True
        try:
            dialog = ctk.CTkInputDialog(
                text="Nome do perfil:",
                title="Salvar Perfil",
            )
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
        else:
            self._set_status("Selecione um perfil válido.")

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
                short_err = self._truncate(error.replace("\n", " "), 42)
                self._set_status(f"Erro ao verificar: {short_err}")
            return

        if info is not None:
            self._pending_update = info
            self.update_banner_lbl.configure(text=f"Nova versão v{info.version} disponível!")
            self.update_banner.grid(row=2, column=0, padx=6, pady=(0, 4), sticky="ew")
            self._set_status(f"Atualização v{info.version} pronta para instalar.")
        elif manual:
            self._set_status(f"Você já está na versão mais recente (v{__version__}).")

    def _start_update_download(self) -> None:
        if not self._pending_update or self._updating:
            return
        self._updating = True
        update = self._pending_update
        self.update_now_btn.configure(state="disabled", text="Baixando...")
        self._set_status(f"Baixando Mixers v{update.version}...")

        def _progress(pct: int) -> None:
            self.after(
                0,
                lambda: self.update_now_btn.configure(text=f"{pct}%"),
            )

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
            self._set_status(f"Erro ao atualizar: {error}")
            return
        if should_quit:
            self._set_status("Reiniciando para concluir a atualização...")
            self.after(200, self._exit_for_update)
        else:
            self.update_now_btn.configure(state="normal", text="Abrir")
            self._set_status("Página de download aberta no navegador.")

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
    def _style_mute_button(btn: ctk.CTkButton, muted: bool) -> None:
        if muted:
            btn.configure(
                text="Mudo",
                fg_color=MUTED_BG,
                hover_color=MUTED_HOVER,
                text_color=TEXT_PRIMARY,
            )
        else:
            btn.configure(
                text="Som",
                fg_color=PILL_BG,
                hover_color=PILL_HOVER,
                text_color=ACCENT,
            )

    @staticmethod
    def _style_mic_mute_button(btn: ctk.CTkButton, muted: bool) -> None:
        if muted:
            btn.configure(
                text="Mudo",
                fg_color=MUTED_BG,
                hover_color=MUTED_HOVER,
                text_color=TEXT_PRIMARY,
            )
        else:
            btn.configure(
                text="Mic",
                fg_color="#132A23",
                hover_color="#1E3F35",
                text_color=MIC_ACCENT,
            )

    @staticmethod
    def _truncate(text: str, max_len: int) -> str:
        return text if len(text) <= max_len else text[: max_len - 1] + "…"

    def _set_status(self, message: str) -> None:
        self.status_lbl.configure(text=message)
