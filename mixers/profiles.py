"""Gerenciamento de perfis de volume salvos pelo usuário."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict

from mixers.audio_backend import AudioBackend, clamp_volume


def default_profiles_path() -> Path:
    """Retorna o caminho padrão para salvar perfis no Windows (%APPDATA%/Mixers)."""
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / "Mixers" / "profiles.json"
    return Path.home() / ".mixers" / "profiles.json"


class ProfileManager:
    """Salva, carrega e aplica perfis de volume."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or default_profiles_path()
        self._profiles: Dict[str, dict] = self._load()

    def _load(self) -> Dict[str, dict]:
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _persist(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(self._profiles, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def list_names(self) -> list[str]:
        return sorted(self._profiles.keys())

    def save_from_backend(self, name: str, backend: AudioBackend) -> None:
        clean_name = name.strip()
        if not clean_name:
            raise ValueError("O nome do perfil não pode ficar vazio.")

        apps_snapshot = {}
        for app in backend.list_app_sessions():
            apps_snapshot[app.app_id] = {
                "volume": clamp_volume(app.volume),
                "muted": bool(app.muted),
            }

        self._profiles[clean_name] = {
            "master_volume": clamp_volume(backend.get_master_volume()),
            "master_muted": bool(backend.get_master_mute()),
            "apps": apps_snapshot,
        }
        self._persist()

    def apply_to_backend(self, name: str, backend: AudioBackend) -> bool:
        profile = self._profiles.get(name)
        if not profile:
            return False

        if "master_volume" in profile:
            backend.set_master_volume(profile["master_volume"])
        if "master_muted" in profile:
            backend.set_master_mute(profile["master_muted"])

        apps_cfg = profile.get("apps", {})
        for app_id, cfg in apps_cfg.items():
            if "volume" in cfg:
                backend.set_app_volume(app_id, cfg["volume"])
            if "muted" in cfg:
                backend.set_app_mute(app_id, cfg["muted"])
        return True

    def delete(self, name: str) -> bool:
        if name in self._profiles:
            del self._profiles[name]
            self._persist()
            return True
        return False
