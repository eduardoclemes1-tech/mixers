"""Auto-updater do Mixers via GitHub Releases (com suporte SSL/certifi + fallback Windows)."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import ssl
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
    """Converte strings como 'v0.3.1' ou '0.3.1' em tupla (0, 3, 1)."""
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


def _build_ssl_context() -> ssl.SSLContext:
    """Cria contexto SSL usando certifi + certificados padrão do sistema."""
    try:
        import certifi

        ctx = ssl.create_default_context(cafile=certifi.where())
    except Exception:
        ctx = ssl.create_default_context()
    try:
        ctx.load_default_certs(ssl.Purpose.SERVER_AUTH)
    except Exception:
        pass
    return ctx


def _fetch_json_via_powershell(url: str, timeout: float = 10.0) -> dict:
    """Fallback nativo do Windows usando pilha WinHTTP/Schannel e proxy do sistema."""
    ps_cmd = (
        "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; "
        f"$r = Invoke-WebRequest -Uri '{url}' -UseBasicParsing "
        "-Headers @{'Accept'='application/vnd.github+json'; 'User-Agent'='Mixers-Updater'} "
        f"-TimeoutSec {int(max(5, timeout))}; "
        "$r.Content"
    )
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    proc = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_cmd],
        capture_output=True,
        text=True,
        timeout=timeout + 5,
        creationflags=creationflags,
        check=True,
    )
    return json.loads(proc.stdout)


def _fetch_latest_release_json(current_version: str, timeout: float) -> dict:
    req = urllib.request.Request(
        LATEST_RELEASE_URL,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"Mixers/{current_version}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_build_ssl_context()) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        if sys.platform == "win32":
            return _fetch_json_via_powershell(LATEST_RELEASE_URL, timeout=timeout)
        raise


def _download_file(
    url: str,
    dest: Path,
    on_progress: Callable[[int], None] | None = None,
) -> None:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": f"Mixers/{__version__}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60, context=_build_ssl_context()) as resp:
            total = int(resp.headers.get("Content-Length") or 0)
            downloaded = 0
            with open(dest, "wb") as out:
                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    out.write(chunk)
                    downloaded += len(chunk)
                    if on_progress and total > 0:
                        on_progress(min(100, int(downloaded * 100 / total)))
    except Exception:
        if sys.platform != "win32":
            raise
        # Fallback nativo do Windows via PowerShell
        ps_cmd = (
            "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; "
            f"Invoke-WebRequest -Uri '{url}' -OutFile '{dest}' -UseBasicParsing"
        )
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_cmd],
            capture_output=True,
            text=True,
            timeout=120,
            creationflags=creationflags,
            check=True,
        )
        if on_progress:
            on_progress(100)


def _clean_env_for_relaunch() -> dict[str, str]:
    """Remove variáveis temporárias do PyInstaller para o novo .exe abrir limpo."""
    blocked_prefixes = ("_MEI", "_PYI")
    blocked_exact = {"TCL_LIBRARY", "TK_LIBRARY", "PYINSTALLER_RESET_ENVIRONMENT"}
    cleaned = {}
    for k, v in os.environ.items():
        if k in blocked_exact or k.startswith(blocked_prefixes):
            continue
        cleaned[k] = v
    cleaned["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    return cleaned


def check_for_update(
    current_version: str = __version__,
    timeout: float = 8.0,
) -> UpdateInfo | None:
    """Consulta a última Release no GitHub e retorna UpdateInfo se houver versão nova."""
    data = _fetch_latest_release_json(current_version=current_version, timeout=timeout)

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
    """
    is_frozen_windows = sys.platform == "win32" and getattr(sys, "frozen", False)
    if not is_frozen_windows or not update.download_url:
        webbrowser.open(update.release_url)
        return False

    current_exe = Path(sys.executable).resolve()
    new_exe = current_exe.with_suffix(".exe.new")

    _download_file(update.download_url, new_exe, on_progress=on_progress)

    # Script temporário com UTF-8 e DelayedExpansion para substituir e reabrir limpo
    bat_path = Path(tempfile.gettempdir()) / "mixers_auto_update.bat"
    bat_content = (
        "@echo off\r\n"
        "chcp 65001 > nul\r\n"
        "setlocal EnableDelayedExpansion\r\n"
        "ping 127.0.0.1 -n 3 > nul\r\n"
        "set RETRIES=0\r\n"
        ":retry\r\n"
        f'move /Y "{new_exe}" "{current_exe}" > nul 2>&1\r\n'
        "if errorlevel 1 (\r\n"
        "  set /a RETRIES+=1\r\n"
        "  if !RETRIES! LSS 20 (\r\n"
        "    ping 127.0.0.1 -n 2 > nul\r\n"
        "    goto retry\r\n"
        "  )\r\n"
        "  exit /b 1\r\n"
        ")\r\n"
        f'start "" "{current_exe}"\r\n'
        'del "%~f0"\r\n'
    )
    bat_path.write_text(bat_content, encoding="utf-8")

    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    subprocess.Popen(
        ["cmd.exe", "/c", str(bat_path)],
        creationflags=creationflags,
        env=_clean_env_for_relaunch(),
        close_fds=True,
    )
    return True
