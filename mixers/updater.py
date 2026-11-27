"""Auto-updater do Mixers via GitHub Releases (100% gratuito em repositório público)."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from typing import Callable
import urllib.request
import webbrowser

from mixers import __version__

GITHUB_OWNER = "eduardoclemes1-tech"
GITHUB_REPO = "mixers"
LATEST_RELEASE_URL = (
    f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
)


@dataclass
class UpdateInfo:
    """Informações sobre uma nova versão disponível no GitHub Releases."""

    version: str
    download_url: str | None
    release_url: str
    notes: str = ""


def parse_version(version_str: str) -> tuple[int, ...]:
    """Converte strings como 'v0.2.1' ou '0.2.1' em tupla (0, 2, 1)."""
    cleaned = version_str.strip().lstrip("vV")
    nums = [int(n) for n in re.findall(r"\d+", cleaned)]
    return tuple(nums) if nums else (0,)


def is_newer_version(latest: str, current: str = __version__) -> bool:
    """Retorna True se 'latest' for estritamente maior que 'current'."""
    a = parse_version(latest)
    b = parse_version(current)
    max_len = max(len(a), len(b))
    a_pad = a + (0,) * (max_len - len(a))
    b_pad = b + (0,) * (max_len - len(b))
    return a_pad > b_pad


def select_exe_asset_url(assets: list[dict]) -> str | None:
    """Escolhe o asset Mixers.exe (ou primeiro .exe) dentro da Release."""
    for asset in assets:
        name = str(asset.get("name", "")).lower()
        if name == "mixers.exe":
            return asset.get("browser_download_url")
    for asset in assets:
        name = str(asset.get("name", "")).lower()
        if name.endswith(".exe"):
            return asset.get("browser_download_url")
    return None


def check_for_update(
    current_version: str = __version__,
    timeout: float = 6.0,
) -> UpdateInfo | None:
    """Consulta a última Release no GitHub e retorna UpdateInfo se houver versão nova."""
    req = urllib.request.Request(
        LATEST_RELEASE_URL,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"Mixers/{current_version}",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    tag_name = str(data.get("tag_name", "")).strip()
    if not tag_name or not is_newer_version(tag_name, current_version):
        return None

    release_url = str(
        data.get("html_url")
        or f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/releases"
    )
    download_url = select_exe_asset_url(data.get("assets", []))
    notes = str(data.get("body") or "").strip()

    return UpdateInfo(
        version=tag_name.lstrip("vV"),
        download_url=download_url,
        release_url=release_url,
        notes=notes,
    )


def download_and_apply_update(
    update: UpdateInfo,
    on_progress: Callable[[int], None] | None = None,
) -> bool:
    """
    Baixa o novo Mixers.exe e agenda a substituição automática ao fechar.

    Retorna True se o aplicativo deve encerrar agora para concluir a troca do .exe.
    Se estiver rodando via Python (não compilado) ou sem asset .exe, abre a página da Release.
    """
    is_frozen_windows = sys.platform == "win32" and getattr(sys, "frozen", False)
    if not is_frozen_windows or not update.download_url:
        webbrowser.open(update.release_url)
        return False

    current_exe = Path(sys.executable).resolve()
    new_exe = current_exe.with_suffix(".exe.new")

    req = urllib.request.Request(
        update.download_url,
        headers={"User-Agent": f"Mixers/{__version__}"},
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        total = int(resp.headers.get("Content-Length") or 0)
        downloaded = 0
        with open(new_exe, "wb") as out:
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                out.write(chunk)
                downloaded += len(chunk)
                if on_progress and total > 0:
                    pct = min(100, int(downloaded * 100 / total))
                    on_progress(pct)

    # Script temporário silencioso que espera o Mixers fechar, substitui o .exe e reabre
    bat_path = Path(tempfile.gettempdir()) / "mixers_auto_update.bat"
    bat_content = (
        "@echo off\n"
        "setlocal\n"
        "ping 127.0.0.1 -n 3 > nul\n"
        "set RETRIES=0\n"
        ":retry\n"
        f'move /Y "{new_exe}" "{current_exe}" > nul 2>&1\n'
        "if errorlevel 1 (\n"
        "  set /a RETRIES+=1\n"
        "  if %RETRIES% LSS 15 (\n"
        "    ping 127.0.0.1 -n 2 > nul\n"
        "    goto retry\n"
        "  )\n"
        "  exit /b 1\n"
        ")\n"
        f'start "" "{current_exe}"\n'
        'del "%~f0"\n'
    )
    bat_path.write_text(bat_content, encoding="utf-8")

    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    subprocess.Popen(
        ["cmd.exe", "/c", str(bat_path)],
        creationflags=creationflags,
        close_fds=True,
    )
    return True
