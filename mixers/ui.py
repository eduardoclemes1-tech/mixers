"""Interface gráfica moderna do Mixers usando CustomTkinter."""

from __future__ import annotations

from typing import Dict

import customtkinter as ctk

from mixers import __version__
from mixers.audio_backend import AppAudioSession, AudioBackend
from mixers.profiles import ProfileManager


class MixersApp(ctk.CTk):
    """Janela principal do gerenciador de som por aplicativo."""

    REFRESH_INTERVAL_MS = 2500

    def __init__(
        self,
        backend: AudioBackend,
        profile_manager: ProfileManager | None = None,
        demo_mode: bool = False,
    ) -> None:
        super().__init__()

        self.backend = backend
        self.profile_manager = profile_manager or ProfileManager()
        self.demo_mode = demo_mode

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        title = f"Mixers v{__version__}"
        if demo_mode:
            title += " (Modo Demo)"
        self.title(title)
        self.geometry("680x640")
        self.minsize(560, 480)

        self._app_rows: Dict[str, dict] = {}
        self._current_sessions: Dict[str, AppAudioSession] = {}
        self._search_var = ctk.StringVar(value="")
        self._search_var.trace_add("write", lambda *_: self._render_app_list(force_rebuild=True))
        self._selected_profile = ctk.StringVar(value="Selecionar perfil...")

        self._build_layout()
        self.refresh_audio_state(force_rebuild=True)
        self.after(self.REFRESH_INTERVAL_MS, self._schedule_refresh)

    def _build_layout(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)

        # 1. Cabeçalho
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, padx=18, pady=(16, 8), sticky="ew")
        header.grid_columnconfigure(1, weight=1)

        title_lbl = ctk.CTkLabel(
            header,
            text="Mixers",
            font=ctk.CTkFont(size=24, weight="bold"),
        )
        title_lbl.grid(row=0, column=0, sticky="w")

        subtitle_text = (
            "Modo demonstração (simulado)"
            if self.demo_mode
            else "Controle de volume por aplicativo • Windows"
        )
        subtitle_lbl = ctk.CTkLabel(
            header,
            text=subtitle_text,
            font=ctk.CTkFont(size=12),
            text_color=("gray40", "gray65"),
        )
        subtitle_lbl.grid(row=1, column=0, columnspan=2, sticky="w")

        refresh_btn = ctk.CTkButton(
            header,
            text="Atualizar",
            width=100,
            command=lambda: self.refresh_audio_state(force_rebuild=True),
        )
        refresh_btn.grid(row=0, column=2, rowspan=2, sticky="e")

        # 2. Card de Volume Geral (Master)
        master_card = ctk.CTkFrame(self, corner_radius=12)
        master_card.grid(row=1, column=0, padx=18, pady=6, sticky="ew")
        master_card.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            master_card,
            text="Volume Geral (Master)",
            font=ctk.CTkFont(size=15, weight="bold"),
        ).grid(row=0, column=0, columnspan=3, padx=14, pady=(12, 4), sticky="w")

        self.master_mute_btn = ctk.CTkButton(
            master_card,
            text="Som",
            width=76,
            command=self._toggle_master_mute,
        )
        self.master_mute_btn.grid(row=1, column=0, padx=(14, 10), pady=(4, 14))

        self.master_slider = ctk.CTkSlider(
            master_card,
            from_=0,
            to=100,
            number_of_steps=100,
            command=self._on_master_slider,
        )
        self.master_slider.grid(row=1, column=1, padx=6, pady=(4, 14), sticky="ew")

        self.master_pct_lbl = ctk.CTkLabel(
            master_card,
            text="100%",
            width=48,
            font=ctk.CTkFont(size=14, weight="bold"),
        )
        self.master_pct_lbl.grid(row=1, column=2, padx=(6, 14), pady=(4, 14))

        # 3. Barra de Ações Rápidas, Perfis e Busca
        controls_card = ctk.CTkFrame(self, corner_radius=12)
        controls_card.grid(row=2, column=0, padx=18, pady=6, sticky="ew")
        controls_card.grid_columnconfigure(0, weight=1)

        quick_row = ctk.CTkFrame(controls_card, fg_color="transparent")
        quick_row.grid(row=0, column=0, padx=12, pady=(10, 6), sticky="ew")

        ctk.CTkButton(
            quick_row,
            text="100% Tudo",
            width=96,
            height=30,
            command=self._preset_full_volume,
        ).pack(side="left", padx=(0, 6))

        ctk.CTkButton(
            quick_row,
            text="Modo Foco (30%)",
            width=128,
            height=30,
            command=self._preset_focus_mode,
        ).pack(side="left", padx=(0, 6))

        ctk.CTkButton(
            quick_row,
            text="Mutar Apps",
            width=100,
            height=30,
            fg_color="#8B2635",
            hover_color="#A83244",
            command=self._preset_mute_all_apps,
        ).pack(side="left", padx=(0, 6))

        self.search_entry = ctk.CTkEntry(
            quick_row,
            placeholder_text="Filtrar aplicativo...",
            textvariable=self._search_var,
            height=30,
        )
        self.search_entry.pack(side="right", fill="x", expand=True, padx=(10, 0))

        profile_row = ctk.CTkFrame(controls_card, fg_color="transparent")
        profile_row.grid(row=1, column=0, padx=12, pady=(2, 10), sticky="ew")

        self.profile_menu = ctk.CTkOptionMenu(
            profile_row,
            variable=self._selected_profile,
            values=self._get_profile_options(),
            width=190,
            height=28,
        )
        self.profile_menu.pack(side="left", padx=(0, 6))

        ctk.CTkButton(
            profile_row,
            text="Aplicar",
            width=76,
            height=28,
            command=self._apply_selected_profile,
        ).pack(side="left", padx=(0, 6))

        ctk.CTkButton(
            profile_row,
            text="Salvar Perfil",
            width=105,
            height=28,
            fg_color="gray30",
            hover_color="gray40",
            command=self._save_profile_dialog,
        ).pack(side="left", padx=(0, 6))

        ctk.CTkButton(
            profile_row,
            text="Excluir",
            width=70,
            height=28,
            fg_color="gray25",
            hover_color="#8B2635",
            command=self._delete_selected_profile,
        ).pack(side="left")

        # 4. Lista rolável de aplicativos
        self.apps_scroll = ctk.CTkScrollableFrame(
            self,
            corner_radius=12,
            label_text="Aplicativos Ativos",
        )
        self.apps_scroll.grid(row=3, column=0, padx=18, pady=(6, 8), sticky="nsew")
        self.apps_scroll.grid_columnconfigure(0, weight=1)

        # 5. Barra de status
        self.status_lbl = ctk.CTkLabel(
            self,
            text="Pronto.",
            anchor="w",
            font=ctk.CTkFont(size=12),
            text_color=("gray40", "gray65"),
        )
        self.status_lbl.grid(row=4, column=0, padx=20, pady=(0, 10), sticky="ew")

    # ------------------------------------------------------------------
    # Atualização de estado
    # ------------------------------------------------------------------
    def _schedule_refresh(self) -> None:
        self.refresh_audio_state(force_rebuild=False)
        self.after(self.REFRESH_INTERVAL_MS, self._schedule_refresh)

    def refresh_audio_state(self, force_rebuild: bool = False) -> None:
        try:
            master_vol = int(round(self.backend.get_master_volume() * 100))
            master_muted = self.backend.get_master_mute()
            sessions = self.backend.list_app_sessions()
        except Exception as exc:
            self._set_status(f"Erro ao ler áudio do sistema: {exc}")
            return

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

        self._set_status(f"{len(sessions)} aplicativo(s) com áudio ativo.")

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
            empty_msg = (
                "Nenhum aplicativo encontrado para essa busca."
                if query
                else "Nenhum aplicativo reproduzindo áudio no momento.\n"
                "Abra um navegador, música ou jogo e clique em Atualizar."
            )
            ctk.CTkLabel(
                self.apps_scroll,
                text=empty_msg,
                text_color=("gray45", "gray60"),
                justify="center",
            ).grid(row=0, column=0, padx=16, pady=36)
            return

        for idx, session in enumerate(filtered):
            card = ctk.CTkFrame(self.apps_scroll, corner_radius=10)
            card.grid(row=idx, column=0, padx=6, pady=5, sticky="ew")
            card.grid_columnconfigure(1, weight=1)

            pids_txt = (
                f"PID: {', '.join(str(p) for p in session.pids[:3])}"
                if session.pids
                else "Sistema"
            )
            ctk.CTkLabel(
                card,
                text=session.display_name,
                font=ctk.CTkFont(size=14, weight="bold"),
                anchor="w",
            ).grid(row=0, column=0, columnspan=2, padx=12, pady=(10, 0), sticky="w")

            ctk.CTkLabel(
                card,
                text=pids_txt,
                font=ctk.CTkFont(size=11),
                text_color=("gray45", "gray60"),
                anchor="e",
            ).grid(row=0, column=2, padx=12, pady=(10, 0), sticky="e")

            mute_btn = ctk.CTkButton(
                card,
                text="Mudo" if session.muted else "Som",
                width=72,
                height=28,
                command=lambda aid=session.app_id: self._toggle_app_mute(aid),
            )
            self._style_mute_button(mute_btn, session.muted)
            mute_btn.grid(row=1, column=0, padx=(12, 8), pady=(6, 12))

            vol_pct = int(round(session.volume * 100))
            slider = ctk.CTkSlider(
                card,
                from_=0,
                to=100,
                number_of_steps=100,
                command=lambda val, aid=session.app_id: self._on_app_slider(aid, val),
            )
            slider.set(vol_pct)
            slider.grid(row=1, column=1, padx=6, pady=(6, 12), sticky="ew")

            pct_lbl = ctk.CTkLabel(
                card,
                text=f"{vol_pct}%",
                width=46,
                font=ctk.CTkFont(size=13, weight="bold"),
            )
            pct_lbl.grid(row=1, column=2, padx=(6, 12), pady=(6, 12))

            self._app_rows[session.app_id] = {
                "mute_btn": mute_btn,
                "slider": slider,
                "pct_lbl": pct_lbl,
            }

    def _sync_existing_rows(self) -> None:
        for app_id, widgets in self._app_rows.items():
            session = self._current_sessions.get(app_id)
            if not session:
                continue
            vol_pct = int(round(session.volume * 100))
            widgets["slider"].set(vol_pct)
            widgets["pct_lbl"].configure(text=f"{vol_pct}%")
            self._style_mute_button(widgets["mute_btn"], session.muted)

    # ------------------------------------------------------------------
    # Eventos de áudio
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

    # ------------------------------------------------------------------
    # Presets rápidos e perfis
    # ------------------------------------------------------------------
    def _preset_full_volume(self) -> None:
        for app_id in self._current_sessions:
            self.backend.set_app_mute(app_id, False)
            self.backend.set_app_volume(app_id, 1.0)
        self.refresh_audio_state(force_rebuild=False)
        self._set_status("Todos os aplicativos restaurados para 100%.")

    def _preset_focus_mode(self) -> None:
        for app_id in self._current_sessions:
            self.backend.set_app_mute(app_id, False)
            self.backend.set_app_volume(app_id, 0.30)
        self.refresh_audio_state(force_rebuild=False)
        self._set_status("Modo Foco aplicado: todos os aplicativos em 30%.")

    def _preset_mute_all_apps(self) -> None:
        for app_id in self._current_sessions:
            self.backend.set_app_mute(app_id, True)
        self.refresh_audio_state(force_rebuild=False)
        self._set_status("Todos os aplicativos foram mutados.")

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
        dialog = ctk.CTkInputDialog(
            text="Digite um nome para salvar o perfil atual:",
            title="Salvar Perfil",
        )
        name = dialog.get_input()
        if not name or not name.strip():
            return
        clean = name.strip()
        self.profile_manager.save_from_backend(clean, self.backend)
        self._refresh_profile_menu(select_name=clean)
        self._set_status(f"Perfil '{clean}' salvo com sucesso!")

    def _apply_selected_profile(self) -> None:
        name = self._selected_profile.get()
        if self.profile_manager.apply_to_backend(name, self.backend):
            self.refresh_audio_state(force_rebuild=False)
            self._set_status(f"Perfil '{name}' aplicado!")
        else:
            self._set_status("Selecione um perfil válido para aplicar.")

    def _delete_selected_profile(self) -> None:
        name = self._selected_profile.get()
        if self.profile_manager.delete(name):
            self._refresh_profile_menu()
            self._set_status(f"Perfil '{name}' removido.")
        else:
            self._set_status("Nenhum perfil selecionado para excluir.")

    # ------------------------------------------------------------------
    # Helpers visuais
    # ------------------------------------------------------------------
    @staticmethod
    def _style_mute_button(btn: ctk.CTkButton, muted: bool) -> None:
        if muted:
            btn.configure(text="Mudo", fg_color="#8B2635", hover_color="#A83244")
        else:
            btn.configure(text="Som", fg_color="#1F6AA5", hover_color="#144870")

    def _set_status(self, message: str) -> None:
        self.status_lbl.configure(text=message)
