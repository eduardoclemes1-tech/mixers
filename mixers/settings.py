"""Persistência de preferências do usuário (atalho global, transparência, etc.)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


DEFAULT_SETTINGS: dict[str, Any] = {
    "alpha": 0.93,
    "hotkey": "Ctrl+Alt+M",
    "mics_expanded": True,
}


def default_settings_path() -> Path:
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / "Mixers" / "settings.json"
    return Path.home() / ".mixers" / "settings.json"


class SettingsManager:
    """Carrega e salva preferências em %APPDATA%/Mixers/settings.json."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or default_settings_path()
        self._data: dict[str, Any] = dict(DEFAULT_SETTINGS)
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                self._data.update(raw)
        except Exception:
            pass

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps(self._data, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception:
            pass

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self._data[key] = value
        self._save()
