"""Extração nativa de ícones reais de aplicativos (.exe) no Windows via Win32 API."""

from __future__ import annotations

import sys
from typing import Dict

from PIL import Image

_EXE_ICON_CACHE: Dict[str, Image.Image | None] = {}


def extract_exe_icon_pil(exe_path: str | None, size: int = 24) -> Image.Image | None:
    """
    Extrai o ícone real (RGBA) de um arquivo .exe no Windows usando ExtractIconExW + GetDIBits.
    Retorna None fora do Windows ou se o executável não tiver ícone acessível.
    """
    if sys.platform != "win32" or not exe_path:
        return None

    cache_key = f"{exe_path.lower()}_{size}"
    if cache_key in _EXE_ICON_CACHE:
        return _EXE_ICON_CACHE[cache_key]

    try:
        import ctypes
        from ctypes import Structure, byref, c_int, c_long, c_uint, c_ulong, c_ushort, c_void_p, create_string_buffer

        shell32 = ctypes.windll.shell32
        user32 = ctypes.windll.user32
        gdi32 = ctypes.windll.gdi32

        class ICONINFO(Structure):
            _fields_ = [
                ("fIcon", c_int),
                ("xHotspot", c_ulong),
                ("yHotspot", c_ulong),
                ("hbmMask", c_void_p),
                ("hbmColor", c_void_p),
            ]

        class BITMAP(Structure):
            _fields_ = [
                ("bmType", c_long),
                ("bmWidth", c_long),
                ("bmHeight", c_long),
                ("bmWidthBytes", c_long),
                ("bmPlanes", c_ushort),
                ("bmBitsPixel", c_ushort),
                ("bmBits", c_void_p),
            ]

        class BITMAPINFOHEADER(Structure):
            _fields_ = [
                ("biSize", c_ulong),
                ("biWidth", c_long),
                ("biHeight", c_long),
                ("biPlanes", c_ushort),
                ("biBitCount", c_ushort),
                ("biCompression", c_ulong),
                ("biSizeImage", c_ulong),
                ("biXPelsPerMeter", c_long),
                ("biYPelsPerMeter", c_long),
                ("biClrUsed", c_ulong),
                ("biClrImportant", c_ulong),
            ]

        hicon_large = c_void_p()
        hicon_small = c_void_p()
        count = shell32.ExtractIconExW(exe_path, 0, byref(hicon_large), byref(hicon_small), 1)
        hicon = hicon_large.value or hicon_small.value
        if count <= 0 or not hicon:
            _EXE_ICON_CACHE[cache_key] = None
            return None

        try:
            icon_info = ICONINFO()
            if not user32.GetIconInfo(c_void_p(hicon), byref(icon_info)):
                _EXE_ICON_CACHE[cache_key] = None
                return None

            try:
                if not icon_info.hbmColor:
                    _EXE_ICON_CACHE[cache_key] = None
                    return None

                bmp = BITMAP()
                gdi32.GetObjectW(c_void_p(icon_info.hbmColor), ctypes.sizeof(bmp), byref(bmp))
                w = int(bmp.bmWidth)
                h = int(bmp.bmHeight)
                if w <= 0 or h <= 0 or w > 256 or h > 256:
                    _EXE_ICON_CACHE[cache_key] = None
                    return None

                bmi = BITMAPINFOHEADER()
                bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
                bmi.biWidth = w
                bmi.biHeight = -h  # top-down DIB
                bmi.biPlanes = 1
                bmi.biBitCount = 32
                bmi.biCompression = 0  # BI_RGB

                buf = create_string_buffer(w * h * 4)
                hdc = user32.GetDC(None)
                try:
                    lines = gdi32.GetDIBits(
                        c_void_p(hdc),
                        c_void_p(icon_info.hbmColor),
                        0,
                        c_uint(h),
                        buf,
                        byref(bmi),
                        0,  # DIB_RGB_COLORS
                    )
                finally:
                    user32.ReleaseDC(None, c_void_p(hdc))

                if lines == 0:
                    _EXE_ICON_CACHE[cache_key] = None
                    return None

                img = Image.frombuffer("RGBA", (w, h), buf.raw, "raw", "BGRA", 0, 1).copy()
                if img.size != (size, size):
                    img = img.resize((size, size), Image.Resampling.LANCZOS)

                _EXE_ICON_CACHE[cache_key] = img
                return img
            finally:
                if icon_info.hbmColor:
                    gdi32.DeleteObject(c_void_p(icon_info.hbmColor))
                if icon_info.hbmMask:
                    gdi32.DeleteObject(c_void_p(icon_info.hbmMask))
        finally:
            if hicon_large.value:
                user32.DestroyIcon(hicon_large)
            if hicon_small.value:
                user32.DestroyIcon(hicon_small)
    except Exception:
        _EXE_ICON_CACHE[cache_key] = None
        return None
