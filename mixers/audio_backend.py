"""Camada de controle de áudio (Windows Core Audio / WASAPI via pycaw)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
import sys
from typing import Dict, List


def clamp_volume(volume: float) -> float:
    """Garante que o volume esteja sempre entre 0.0 e 1.0."""
    return max(0.0, min(1.0, float(volume)))


def format_app_name(process_name: str) -> str:
    """Transforma nomes como 'chrome.exe' em 'Chrome'."""
    cleaned = process_name.strip()
    if cleaned.lower().endswith(".exe"):
        cleaned = cleaned[:-4]
    if not cleaned:
        return "Aplicativo"
    return cleaned[0].upper() + cleaned[1:]


@dataclass
class AppAudioSession:
    """Representa um aplicativo com sessão de áudio ativa."""

    app_id: str
    display_name: str
    volume: float  # 0.0 a 1.0
    muted: bool
    pids: List[int]


class AudioBackend(ABC):
    """Interface abstrata para backends de áudio."""

    @abstractmethod
    def get_master_volume(self) -> float:
        """Retorna o volume geral do sistema (0.0 a 1.0)."""

    @abstractmethod
    def set_master_volume(self, volume: float) -> None:
        """Define o volume geral do sistema (0.0 a 1.0)."""

    @abstractmethod
    def get_master_mute(self) -> bool:
        """Retorna se o áudio geral está mutado."""

    @abstractmethod
    def set_master_mute(self, muted: bool) -> None:
        """Ativa ou desativa o mudo geral."""

    @abstractmethod
    def list_app_sessions(self) -> List[AppAudioSession]:
        """Lista todos os aplicativos com sessão de áudio ativa."""

    @abstractmethod
    def set_app_volume(self, app_id: str, volume: float) -> None:
        """Define o volume (0.0 a 1.0) para todas as sessões do aplicativo."""

    @abstractmethod
    def set_app_mute(self, app_id: str, muted: bool) -> None:
        """Ativa ou desativa o mudo para todas as sessões do aplicativo."""


class WindowsAudioBackend(AudioBackend):
    """Backend oficial para Windows usando WASAPI via pycaw."""

    SYSTEM_SOUNDS_ID = "__system_sounds__"

    def __init__(self) -> None:
        if sys.platform != "win32":
            raise RuntimeError(
                "WindowsAudioBackend requer Windows (win32). "
                "Use '--demo' para testar em outros sistemas."
            )

        from ctypes import POINTER, cast
        import comtypes
        from comtypes import CLSCTX_ALL
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

        self._comtypes = comtypes
        self._AudioUtilities = AudioUtilities
        self._IAudioEndpointVolume = IAudioEndpointVolume
        self._CLSCTX_ALL = CLSCTX_ALL
        self._POINTER = POINTER
        self._cast = cast

        comtypes.CoInitialize()
        self._master = self._init_master_endpoint()

    def _init_master_endpoint(self):
        devices = self._AudioUtilities.GetSpeakers()
        if hasattr(devices, "EndpointVolume"):
            return devices.EndpointVolume
        interface = devices.Activate(
            self._IAudioEndpointVolume._iid_, self._CLSCTX_ALL, None
        )
        return self._cast(interface, self._POINTER(self._IAudioEndpointVolume))

    def get_master_volume(self) -> float:
        try:
            return clamp_volume(self._master.GetMasterVolumeLevelScalar())
        except Exception:
            self._master = self._init_master_endpoint()
            return clamp_volume(self._master.GetMasterVolumeLevelScalar())

    def set_master_volume(self, volume: float) -> None:
        level = clamp_volume(volume)
        try:
            self._master.SetMasterVolumeLevelScalar(level, None)
        except Exception:
            self._master = self._init_master_endpoint()
            self._master.SetMasterVolumeLevelScalar(level, None)

    def get_master_mute(self) -> bool:
        try:
            return bool(self._master.GetMute())
        except Exception:
            self._master = self._init_master_endpoint()
            return bool(self._master.GetMute())

    def set_master_mute(self, muted: bool) -> None:
        val = 1 if muted else 0
        try:
            self._master.SetMute(val, None)
        except Exception:
            self._master = self._init_master_endpoint()
            self._master.SetMute(val, None)

    def _get_session_app_id(self, session) -> tuple[str, str, int | None]:
        proc = session.Process
        if proc is None:
            return self.SYSTEM_SOUNDS_ID, "Sons do Sistema", None
        try:
            raw_name = proc.name()
            pid = proc.pid
            return raw_name.lower(), format_app_name(raw_name), pid
        except Exception:
            return self.SYSTEM_SOUNDS_ID, "Sons do Sistema", None

    def list_app_sessions(self) -> List[AppAudioSession]:
        grouped: Dict[str, AppAudioSession] = {}
        for session in self._AudioUtilities.GetAllSessions():
            simple_vol = getattr(session, "SimpleAudioVolume", None)
            if simple_vol is None:
                continue

            app_id, display_name, pid = self._get_session_app_id(session)
            try:
                vol = clamp_volume(simple_vol.GetMasterVolume())
                muted = bool(simple_vol.GetMute())
            except Exception:
                continue

            if app_id not in grouped:
                grouped[app_id] = AppAudioSession(
                    app_id=app_id,
                    display_name=display_name,
                    volume=vol,
                    muted=muted,
                    pids=[pid] if pid is not None else [],
                )
            else:
                if pid is not None and pid not in grouped[app_id].pids:
                    grouped[app_id].pids.append(pid)

        return sorted(
            grouped.values(),
            key=lambda item: (item.app_id == self.SYSTEM_SOUNDS_ID, item.display_name.lower()),
        )

    def set_app_volume(self, app_id: str, volume: float) -> None:
        level = clamp_volume(volume)
        for session in self._AudioUtilities.GetAllSessions():
            simple_vol = getattr(session, "SimpleAudioVolume", None)
            if simple_vol is None:
                continue
            sid, _, _ = self._get_session_app_id(session)
            if sid == app_id:
                try:
                    simple_vol.SetMasterVolume(level, None)
                except Exception:
                    pass

    def set_app_mute(self, app_id: str, muted: bool) -> None:
        val = 1 if muted else 0
        for session in self._AudioUtilities.GetAllSessions():
            simple_vol = getattr(session, "SimpleAudioVolume", None)
            if simple_vol is None:
                continue
            sid, _, _ = self._get_session_app_id(session)
            if sid == app_id:
                try:
                    simple_vol.SetMute(val, None)
                except Exception:
                    pass


class DemoAudioBackend(AudioBackend):
    """Backend simulado para testes e pré-visualização sem áudio do Windows."""

    def __init__(self) -> None:
        self._master_volume = 0.75
        self._master_muted = False
        self._apps: Dict[str, AppAudioSession] = {
            "chrome.exe": AppAudioSession("chrome.exe", "Chrome", 0.80, False, [4120, 4188]),
            "spotify.exe": AppAudioSession("spotify.exe", "Spotify", 0.55, False, [6210]),
            "discord.exe": AppAudioSession("discord.exe", "Discord", 0.90, False, [7304]),
            "vlc.exe": AppAudioSession("vlc.exe", "Vlc", 0.40, True, [8901]),
        }

    def get_master_volume(self) -> float:
        return self._master_volume

    def set_master_volume(self, volume: float) -> None:
        self._master_volume = clamp_volume(volume)

    def get_master_mute(self) -> bool:
        return self._master_muted

    def set_master_mute(self, muted: bool) -> None:
        self._master_muted = bool(muted)

    def list_app_sessions(self) -> List[AppAudioSession]:
        return sorted(
            [
                AppAudioSession(
                    app_id=a.app_id,
                    display_name=a.display_name,
                    volume=a.volume,
                    muted=a.muted,
                    pids=list(a.pids),
                )
                for a in self._apps.values()
            ],
            key=lambda item: item.display_name.lower(),
        )

    def set_app_volume(self, app_id: str, volume: float) -> None:
        if app_id in self._apps:
            self._apps[app_id].volume = clamp_volume(volume)

    def set_app_mute(self, app_id: str, muted: bool) -> None:
        if app_id in self._apps:
            self._apps[app_id].muted = bool(muted)


def create_audio_backend(demo: bool = False) -> AudioBackend:
    """Cria o backend apropriado (Windows oficial ou Demo)."""
    if demo:
        return DemoAudioBackend()
    return WindowsAudioBackend()
