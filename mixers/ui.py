"""Interface clean, transparente e flutuante do Mixers (estilo painel do Windows 11)."""

from __future__ import annotations

import sys
from typing import Dict

import customtkinter as ctk

from mixers import __version__
from mixers.audio_backend import AppAudioSession, AudioBackend
from mixers.profiles import ProfileManager
from mixers.tray import TrayController
from mixers.windows_integration import (
    apply_windows_glass_style,
    get_work_area,
    is_autostart_enabled,
    set_autostart,
)

# Paleta clean escura translúcida
BG_SURFACE = "#0E1117"
CARD_SURFACE = "#161B26"
CARD_BORDER = "#242C3D"
ACCENT = "#38BDF8"
ACCENT_HOVER = "#0EA5E9"
MUTED_BG = "#7F1D2D"
MUTED_HOVER = "#991B1B"
TEXT_PRIMARY = "#F1F5F9"
TEXT_SECONDARY = "#94A3B8"


class MixersApp(ctk.CTk):
    """Painel flutuante clean e transparente que roda em segundo plano na bandeja."""

    WINDOW_WIDTH = 390
    WINDOW_HEIGHT = 560
    SESSION_REFRESH_MS = 2000
    METER_REFRESH_MS = 180

    def __init__(
        self,
        backend: AudioBackend,
        profile_manager: ProfileManager | None = None,
        demo_mode: bool = False,
        start_minimized: bool = False,
        enable_tray: bool = True,
    ) -> None:
        super().__init__()

        self.backend = backend
        self.profile_manager = profile_manager or ProfileManager()
        self.demo_mode = demo_mode

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.title(f"Mixers v{__version__}")
        self.configure(fg_color=BG_SURFACE)
        self.resizable(False, False)

        # Estado visual e interativo
        self._alpha = 0.90
        self._pinned = False
        self._settings_open = False
        self._dialog_open = False
        self._is_visible = not start_minimized
        self._drag_origin: tuple[int, int] | None = None

        self._app_rows: Dict[str, dict] = {}
        self._current_sessions: Dict[str, AppAudioSession] = {}
        self._search_var = ctk.StringVar(value="")
        self._search_var.trace_add("write", lambda *_: self._render_app_list(force_rebuild=True))
        self._selected_profile = ctk.StringVar(value="Sem perfis salvos")
        self._autostart_var = ctk.BooleanVar(value=is_autostart_enabled())

        # Estilo flutuante transparente (Windows)
        if sys.platform == "win32":
            self.overrideredirect(True)
        self.attributes("-topmost", True)
        try:
            self.attributes("-alpha", self._alpha)
        except Exception:
            pass

        self._build_layout()
        self._position_bottom_right()
        self._apply_native_window_effects()

        # Eventos de foco e fechamento (minimiza para bandeja em vez de encerrar)
        self.bind("<Escape>", lambda _e: self.hide_to_tray())
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
                    on_quit=lambda: self.after(0, self.quit_app),
                )
                self.tray.start()
            except Exception:
                self.tray = None

        if start_minimized:
            self.withdraw()
        else:
            self.refresh_audio_state(force_rebuild=True)

        self.after(self.SESSION_REFRESH_MS, self._schedule_session_refresh)
        self.after(self.METER_REFRESH_MS, self._schedule_meter_refresh)

    # ------------------------------------------------------------------
    # Posicionamento e visual nativo
    # ------------------------------------------------------------------
    def _position_bottom_right(self) -> None:
        self.update_idletasks()
        left, top, right, bottom = get_work_area(
            self.winfo_screenwidth(), self.winfo_screenheight()
        )
        margin = 14
        x = max(left + margin, right - self.WINDOW_WIDTH - margin)
        y = max(top + margin, bottom - self.WINDOW_HEIGHT - margin)
        self.geometry(f"{self.WINDOW_WIDTH}x{self.WINDOW_HEIGHT}+{x}+{y}")

    def _apply_native_window_effects(self) -> None:
        if sys.platform != "win32":
            return
        try:
            self.update_idletasks()
            hwnd = self.winfo_id()
            apply_windows_glass_style(hwnd)
        except Exception:
            pass

    def _start_drag(self, event) -> None:
        self._drag_origin = (event.x_root - self.winfo_x(), event.y_root - self.winfo_y())

    def _on_drag(self, event) -> None:
        if self._drag_origin is None:
            return
        dx, dy = self._drag_origin
        self.geometry(f"+{event.x_root - dx}+{event.y_root - dy}")

    # ------------------------------------------------------------------
    # Layout Clean & Transparente
    # ------------------------------------------------------------------
    def _build_layout(self) -> None:
        # Container principal com borda sutil (efeito vidro)
        self.shell = ctk.CTkFrame(
            self,
            fg_color=BG_SURFACE,
            border_color=CARD_BORDER,
            border_width=1,
            corner_radius=14,
        )
        self.shell.pack(fill="both", expand=True)
        self.shell.grid_columnconfigure(0, weight=1)
        self.shell.grid_rowconfigure(4, weight=1)

        # 1. Cabeçalho compacto (arrastável)
        header = ctk.CTkFrame(self.shell, fg_color="transparent")
        header.grid(row=0, column=0, padx=14, pady=(12, 6), sticky="ew")
        header.grid_columnconfigure(0, weight=1)
        header.bind("<Button-1>", self._start_drag)
        header.bind("<B1-Motion>", self._on_drag)

        title_row = ctk.CTkFrame(header, fg_color="transparent")
        title_row.grid(row=0, column=0, sticky="w")
        title_row.bind("<Button-1>", self._start_drag)
        title_row.bind("<B1-Motion>", self._on_drag)

        title_lbl = ctk.CTkLabel(
            title_row,
            text="Mixers",
            font=ctk.CTkFont(size=18, weight="bold"),
            text_color=TEXT_PRIMARY,
        )
        title_lbl.pack(anchor="w")
        title_lbl.bind("<Button-1>", self._start_drag)
        title_lbl.bind("<B1-Motion>", self._on_drag)

        self.device_lbl = ctk.CTkLabel(
            title_row,
            text=self._truncate(self.backend.get_output_device_name(), 30),
            font=ctk.CTkFont(size=11),
            text_color=TEXT_SECONDARY,
        )
        self.device_lbl.pack(anchor="w")

        btn_group = ctk.CTkFrame(header, fg_color="transparent")
        btn_group.grid(row=0, column=1, sticky="e")

        self.pin_btn = ctk.CTkButton(
            btn_group,
            text="Fixar",
            width=48,
            height=26,
            corner_radius=8,
            font=ctk.CTkFont(size=11),
            fg_color=CARD_SURFACE,
            hover_color=CARD_BORDER,
            text_color=TEXT_SECONDARY,
            command=self._toggle_pin,
        )
        self.pin_btn.pack(side="left", padx=(0, 4))

        self.settings_btn = ctk.CTkButton(
            btn_group,
            text="Ajustes",
            width=56,
            height=26,
            corner_radius=8,
            font=ctk.CTkFont(size=11),
            fg_color=CARD_SURFACE,
            hover_color=CARD_BORDER,
            text_color=TEXT_SECONDARY,
            command=self._toggle_settings_drawer,
        )
        self.settings_btn.pack(side="left", padx=(0, 4))

        ctk.CTkButton(
            btn_group,
            text="—",
            width=28,
            height=26,
            corner_radius=8,
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color=CARD_SURFACE,
            hover_color=CARD_BORDER,
            text_color=TEXT_PRIMARY,
            command=self.hide_to_tray,
        ).pack(side="left")

        # 2. Gaveta retrátil de Ajustes (Transparência, Autostart e Perfis)
        self.settings_drawer = ctk.CTkFrame(
            self.shell,
            fg_color=CARD_SURFACE,
            border_color=CARD_BORDER,
            border_width=1,
            corner_radius=12,
        )
        self.settings_drawer.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            self.settings_drawer,
            text="Transparência",
            font=ctk.CTkFont(size=12),
            text_color=TEXT_SECONDARY,
        ).grid(row=0, column=0, padx=(12, 8), pady=(10, 4), sticky="w")

        self.alpha_slider = ctk.CTkSlider(
            self.settings_drawer,
            from_=65,
            to=100,
            number_of_steps=35,
            progress_color=ACCENT,
            button_color=TEXT_PRIMARY,
            button_hover_color=ACCENT,
            command=self._on_alpha_change,
        )
        self.alpha_slider.set(int(self._alpha * 100))
        self.alpha_slider.grid(row=0, column=1, padx=6, pady=(10, 4), sticky="ew")

        self.alpha_lbl = ctk.CTkLabel(
            self.settings_drawer,
            text=f"{int(self._alpha * 100)}%",
            width=38,
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=TEXT_PRIMARY,
        )
        self.alpha_lbl.grid(row=0, column=2, padx=(4, 12), pady=(10, 4))

        self.autostart_switch = ctk.CTkSwitch(
            self.settings_drawer,
            text="Iniciar com o Windows",
            variable=self._autostart_var,
            font=ctk.CTkFont(size=12),
            progress_color=ACCENT,
            command=self._on_autostart_switch,
        )
        self.autostart_switch.grid(
            row=1, column=0, columnspan=3, padx=12, pady=(4, 6), sticky="w"
        )

        # Perfis dentro da gaveta para manter a tela principal bem limpa
        prof_row = ctk.CTkFrame(self.settings_drawer, fg_color="transparent")
        prof_row.grid(row=2, column=0, columnspan=3, padx=10, pady=(2, 10), sticky="ew")

        self.profile_menu = ctk.CTkOptionMenu(
            prof_row,
            variable=self._selected_profile,
            values=self._get_profile_options(),
            width=145,
            height=26,
            font=ctk.CTkFont(size=11),
            fg_color=BG_SURFACE,
            button_color=CARD_BORDER,
            button_hover_color=ACCENT,
        )
        self.profile_menu.pack(side="left", padx=(0, 4))

        ctk.CTkButton(
            prof_row,
            text="Aplicar",
            width=54,
            height=26,
            font=ctk.CTkFont(size=11),
            fg_color=ACCENT,
            hover_color=ACCENT_HOVER,
            text_color="#0B1120",
            command=self._apply_selected_profile,
        ).pack(side="left", padx=(0, 4))

        ctk.CTkButton(
            prof_row,
            text="Salvar",
            width=52,
            height=26,
            font=ctk.CTkFont(size=11),
            fg_color=CARD_BORDER,
            hover_color="#334155",
            command=self._save_profile_dialog,
        ).pack(side="left", padx=(0, 4))

        ctk.CTkButton(
            prof_row,
            text="X",
            width=28,
            height=26,
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color=CARD_BORDER,
            hover_color=MUTED_BG,
            command=self._delete_selected_profile,
        ).pack(side="left")

        # 3. Card Master Volume (clean + medidor em tempo real)
        master_card = ctk.CTkFrame(
            self.shell,
            fg_color=CARD_SURFACE,
            border_color=CARD_BORDER,
            border_width=1,
            corner_radius=12,
        )
        master_card.grid(row=2, column=0, padx=14, pady=6, sticky="ew")
        master_card.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            master_card,
            text="Volume Geral",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=TEXT_PRIMARY,
        ).grid(row=0, column=0, columnspan=2, padx=12, pady=(10, 2), sticky="w")

        self.master_pct_lbl = ctk.CTkLabel(
            master_card,
            text="100%",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=ACCENT,
        )
        self.master_pct_lbl.grid(row=0, column=2, padx=12, pady=(10, 2), sticky="e")

        self.master_mute_btn = ctk.CTkButton(
            master_card,
            text="Som",
            width=54,
            height=26,
            corner_radius=8,
            font=ctk.CTkFont(size=11, weight="bold"),
            command=self._toggle_master_mute,
        )
        self.master_mute_btn.grid(row=1, column=0, padx=(12, 8), pady=(4, 6))

        self.master_slider = ctk.CTkSlider(
            master_card,
            from_=0,
            to=100,
            number_of_steps=100,
            height=16,
            progress_color=ACCENT,
            button_color=TEXT_PRIMARY,
            button_hover_color=ACCENT,
            command=self._on_master_slider,
        )
        self.master_slider.grid(row=1, column=1, columnspan=2, padx=(0, 12), pady=(4, 6), sticky="ew")

        self.master_meter = ctk.CTkProgressBar(
            master_card,
            height=4,
            corner_radius=2,
            fg_color="#0F172A",
            progress_color=ACCENT,
        )
        self.master_meter.set(0)
        self.master_meter.grid(row=2, column=0, columnspan=3, padx=12, pady=(0, 10), sticky="ew")

        # 4. Barra compacta de ações rápidas + filtro
        quick_row = ctk.CTkFrame(self.shell, fg_color="transparent")
        quick_row.grid(row=3, column=0, padx=14, pady=(2, 4), sticky="ew")

        ctk.CTkButton(
            quick_row,
            text="100%",
            width=48,
            height=26,
            corner_radius=8,
            font=ctk.CTkFont(size=11),
            fg_color=CARD_SURFACE,
            hover_color=CARD_BORDER,
            command=self._preset_full_volume,
        ).pack(side="left", padx=(0, 4))

        ctk.CTkButton(
            quick_row,
            text="Foco 30%",
            width=68,
            height=26,
            corner_radius=8,
            font=ctk.CTkFont(size=11),
            fg_color=CARD_SURFACE,
            hover_color=CARD_BORDER,
            command=self._preset_focus_mode,
        ).pack(side="left", padx=(0, 4))

        ctk.CTkButton(
            quick_row,
            text="Mutar",
            width=54,
            height=26,
            corner_radius=8,
            font=ctk.CTkFont(size=11),
            fg_color=MUTED_BG,
            hover_color=MUTED_HOVER,
            command=self._preset_mute_all_apps,
        ).pack(side="left", padx=(0, 6))

        self.search_entry = ctk.CTkEntry(
            quick_row,
            placeholder_text="Buscar app...",
            textvariable=self._search_var,
            height=26,
            corner_radius=8,
            font=ctk.CTkFont(size=11),
            fg_color=CARD_SURFACE,
            border_color=CARD_BORDER,
        )
        self.search_entry.pack(side="right", fill="x", expand=True)

        # 5. Lista limpa e rolável de aplicativos
        self.apps_scroll = ctk.CTkScrollableFrame(
            self.shell,
            fg_color="transparent",
            scrollbar_button_color=CARD_BORDER,
            scrollbar_button_hover_color="#334155",
        )
        self.apps_scroll.grid(row=4, column=0, padx=10, pady=(2, 4), sticky="nsew")
        self.apps_scroll.grid_columnconfigure(0, weight=1)

        # 6. Rodapé minimalista
        footer = ctk.CTkFrame(self.shell, fg_color="transparent")
        footer.grid(row=5, column=0, padx=14, pady=(2, 10), sticky="ew")
        footer.grid_columnconfigure(0, weight=1)

        self.status_lbl = ctk.CTkLabel(
            footer,
            text="Rodando em segundo plano",
            anchor="w",
            font=ctk.CTkFont(size=11),
            text_color=TEXT_SECONDARY,
        )
        self.status_lbl.grid(row=0, column=0, sticky="w")

        ctk.CTkButton(
            footer,
            text="Sair",
            width=44,
            height=22,
            corner_radius=6,
            font=ctk.CTkFont(size=10),
            fg_color="transparent",
            hover_color=MUTED_BG,
            text_color=TEXT_SECONDARY,
            command=self.quit_app,
        ).grid(row=0, column=1, sticky="e")

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
        self._position_bottom_right()
        self.deiconify()
        self.lift()
        self.focus_force()
        self.refresh_audio_state(force_rebuild=True)

    def hide_to_tray(self) -> None:
        if self.tray is None and not self.demo_mode:
            self.quit_app()
            return
        self._is_visible = False
        self.withdraw()

    def _on_focus_out(self, _event) -> None:
        if self._pinned or self._dialog_open or not self._is_visible:
            return
        # Pequeno atraso para evitar esconder ao clicar em widgets internos
        self.after(120, self._hide_if_still_unfocused)

    def _hide_if_still_unfocused(self) -> None:
        if self._pinned or self._dialog_open or not self._is_visible:
            return
        try:
            focused = self.focus_displayof()
            if focused is None:
                self.hide_to_tray()
        except Exception:
            pass

    def quit_app(self) -> None:
        if self.tray is not None:
            self.tray.stop()
        self.destroy()

    # ------------------------------------------------------------------
    # Atualização em tempo real (somente quando visível)
    # ------------------------------------------------------------------
    def _schedule_session_refresh(self) -> None:
        if self._is_visible:
            self.refresh_audio_state(force_rebuild=False)
        self.after(self.SESSION_REFRESH_MS, self._schedule_session_refresh)

    def _schedule_meter_refresh(self) -> None:
        if self._is_visible:
            self._update_audio_meters()
        self.after(self.METER_REFRESH_MS, self._schedule_meter_refresh)

    def _update_audio_meters(self) -> None:
        try:
            self.master_meter.set(self.backend.get_master_peak())
            sessions = self.backend.list_app_sessions()
            for session in sessions:
                row = self._app_rows.get(session.app_id)
                if row:
                    row["meter"].set(0.0 if session.muted else session.peak_level)
        except Exception:
            pass

    def refresh_audio_state(self, force_rebuild: bool = False) -> None:
        try:
            master_vol = int(round(self.backend.get_master_volume() * 100))
            master_muted = self.backend.get_master_mute()
            sessions = self.backend.list_app_sessions()
            dev_name = self.backend.get_output_device_name()
        except Exception as exc:
            self._set_status(f"Erro de áudio: {exc}")
            return

        self.device_lbl.configure(text=self._truncate(dev_name, 32))
        self.master_slider.set(master_vol)
        self.master_pct_lbl.configure(text=f"{master_vol}%")
        self._style_mute_button(self.master_mute_btn, master_muted)

        new_map = {s.app_id: s for s in sessions}
        keys_changed = list(new_map.keys()) != list(self._current_sessions.keys())
        self._current_sessions = new_map

        if force_rebuild or keys_changed:
            self._render_app_list(force_rebuild=True)
        else:
            self._sync_existing_rows()

        self._set_status(f"{len(sessions)} app(s) com áudio • segundo plano ativo")

    def _render_app_list(self, force_rebuild: bool = False) -> None:
        if not force_rebuild:
            return

        for child in self.apps_scroll.winfo_children():
            child.destroy()
        self._app_rows.clear()

        query = self._search_var.get().strip().lower()
        filtered = [
            s
            for s in self._current_sessions.values()
            if not query or query in s.display_name.lower() or query in s.app_id.lower()
        ]

        if not filtered:
            msg = (
                "Nenhum app encontrado."
                if query
                else "Nenhum aplicativo tocando som agora.\nAbra um navegador, música ou jogo."
            )
            ctk.CTkLabel(
                self.apps_scroll,
                text=msg,
                font=ctk.CTkFont(size=12),
                text_color=TEXT_SECONDARY,
                justify="center",
            ).grid(row=0, column=0, padx=12, pady=40)
            return

        for idx, session in enumerate(filtered):
            card = ctk.CTkFrame(
                self.apps_scroll,
                fg_color=CARD_SURFACE,
                border_color=CARD_BORDER,
                border_width=1,
                corner_radius=12,
            )
            card.grid(row=idx, column=0, padx=4, pady=4, sticky="ew")
            card.grid_columnconfigure(1, weight=1)

            vol_pct = int(round(session.volume * 100))

            ctk.CTkLabel(
                card,
                text=self._truncate(session.display_name, 26),
                font=ctk.CTkFont(size=13, weight="bold"),
                text_color=TEXT_PRIMARY,
                anchor="w",
            ).grid(row=0, column=0, columnspan=2, padx=10, pady=(8, 2), sticky="w")

            pct_lbl = ctk.CTkLabel(
                card,
                text=f"{vol_pct}%",
                font=ctk.CTkFont(size=12, weight="bold"),
                text_color=TEXT_SECONDARY if session.muted else ACCENT,
            )
            pct_lbl.grid(row=0, column=2, padx=10, pady=(8, 2), sticky="e")

            mute_btn = ctk.CTkButton(
                card,
                text="Mudo" if session.muted else "Som",
                width=52,
                height=24,
                corner_radius=7,
                font=ctk.CTkFont(size=11, weight="bold"),
                command=lambda aid=session.app_id: self._toggle_app_mute(aid),
            )
            self._style_mute_button(mute_btn, session.muted)
            mute_btn.grid(row=1, column=0, padx=(10, 6), pady=(2, 6))

            slider = ctk.CTkSlider(
                card,
                from_=0,
                to=100,
                number_of_steps=100,
                height=15,
                progress_color=ACCENT,
                button_color=TEXT_PRIMARY,
                button_hover_color=ACCENT,
                command=lambda val, aid=session.app_id: self._on_app_slider(aid, val),
            )
            slider.set(vol_pct)
            slider.grid(row=1, column=1, columnspan=2, padx=(0, 10), pady=(2, 6), sticky="ew")

            meter = ctk.CTkProgressBar(
                card,
                height=3,
                corner_radius=2,
                fg_color="#0F172A",
                progress_color=ACCENT,
            )
            meter.set(0.0 if session.muted else session.peak_level)
            meter.grid(row=2, column=0, columnspan=3, padx=10, pady=(0, 8), sticky="ew")

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
            widgets["slider"].set(vol_pct)
            widgets["pct_lbl"].configure(
                text=f"{vol_pct}%",
                text_color=TEXT_SECONDARY if session.muted else ACCENT,
            )
            self._style_mute_button(widgets["mute_btn"], session.muted)

    # ------------------------------------------------------------------
    # Eventos de áudio e ajustes
    # ------------------------------------------------------------------
    def _on_master_slider(self, value: float) -> None:
        pct = int(round(value))
        self.master_pct_lbl.configure(text=f"{pct}%")
        self.backend.set_master_volume(pct / 100.0)

    def _toggle_master_mute(self) -> None:
        new_state = not self.backend.get_master_mute()
        self.backend.set_master_mute(new_state)
        self._style_mute_button(self.master_mute_btn, new_state)

    def _on_app_slider(self, app_id: str, value: float) -> None:
        pct = int(round(value))
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
            self.pin_btn.configure(fg_color=CARD_SURFACE, text_color=TEXT_SECONDARY)
            self._set_status("Oculta automaticamente ao clicar fora.")

    def _toggle_settings_drawer(self) -> None:
        self._settings_open = not self._settings_open
        if self._settings_open:
            self.settings_drawer.grid(row=1, column=0, padx=14, pady=(2, 6), sticky="ew")
            self.settings_btn.configure(fg_color=ACCENT, text_color="#0B1120")
        else:
            self.settings_drawer.grid_forget()
            self.settings_btn.configure(fg_color=CARD_SURFACE, text_color=TEXT_SECONDARY)

    def _on_alpha_change(self, value: float) -> None:
        pct = int(round(value))
        self._alpha = pct / 100.0
        self.alpha_lbl.configure(text=f"{pct}%")
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
                fg_color="#1E293B",
                hover_color="#334155",
                text_color=ACCENT,
            )

    @staticmethod
    def _truncate(text: str, max_len: int) -> str:
        return text if len(text) <= max_len else text[: max_len - 1] + "…"

    def _set_status(self, message: str) -> None:
        self.status_lbl.configure(text=message)
