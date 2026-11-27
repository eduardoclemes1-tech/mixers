using System;
using System.Collections.Generic;
using System.Drawing;
using System.IO;
using System.Runtime.InteropServices;
using System.Windows;
using System.Windows.Interop;
using System.Windows.Media;
using System.Windows.Media.Imaging;

namespace Mixers.Services;

/// <summary>
/// Extrator de ícones reais em 3 camadas:
/// 1) IconPath WASAPI (.png/.ico de apps UWP/Microsoft Store ou @dll,-id);
/// 2) SHGetFileInfoW (ícone oficial do .exe em alta definição);
/// 3) Icon.ExtractAssociatedIcon (fallback clássico).
/// </summary>
public static class IconService
{
    private const uint ShgfiIcon = 0x000000100;
    private const uint ShgfiLargeIcon = 0x000000000;

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    private struct ShFileInfo
    {
        public IntPtr hIcon;
        public int iIcon;
        public uint dwAttributes;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 260)]
        public string szDisplayName;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 80)]
        public string szTypeName;
    }

    [DllImport("shell32.dll", CharSet = CharSet.Unicode)]
    private static extern IntPtr SHGetFileInfo(
        string pszPath,
        uint dwFileAttributes,
        out ShFileInfo psfi,
        uint cbFileInfo,
        uint uFlags);

    [DllImport("shell32.dll", CharSet = CharSet.Unicode)]
    private static extern uint ExtractIconEx(
        string lpszFile,
        int nIconIndex,
        out IntPtr phiconLarge,
        out IntPtr phiconSmall,
        uint nIcons);

    [DllImport("user32.dll", SetLastError = true)]
    private static extern bool DestroyIcon(IntPtr hIcon);

    private static readonly Dictionary<string, ImageSource?> Cache = new(StringComparer.OrdinalIgnoreCase);

    public static ImageSource? GetAppIcon(string? exePath, string? sessionIconPath)
    {
        string cacheKey = $"{exePath ?? ""}|{sessionIconPath ?? ""}";
        if (string.IsNullOrEmpty(cacheKey.Trim('|'))) return null;
        if (Cache.TryGetValue(cacheKey, out var cached)) return cached;

        ImageSource? result =
            TryLoadSessionIconPath(sessionIconPath) ??
            TryLoadAppxManifestIcon(exePath) ??
            TryExtractShellIcon(exePath) ??
            TryExtractAssociatedIcon(exePath);

        Cache[cacheKey] = result;
        return result;
    }

    private static ImageSource? TryLoadAppxManifestIcon(string? exePath)
    {
        if (string.IsNullOrWhiteSpace(exePath)) return null;
        try
        {
            string? dir = Path.GetDirectoryName(exePath);
            if (string.IsNullOrEmpty(dir)) return null;
            string manifestPath = Path.Combine(dir, "AppxManifest.xml");
            if (!File.Exists(manifestPath)) return null;

            string xml = File.ReadAllText(manifestPath);
            string[] attrNames = { "Square44x44Logo=\"", "Square150x150Logo=\"", "<Logo>" };
            foreach (string marker in attrNames)
            {
                int idx = xml.IndexOf(marker, StringComparison.OrdinalIgnoreCase);
                if (idx < 0) continue;
                int start = idx + marker.Length;
                int end = marker.StartsWith("<")
                    ? xml.IndexOf("</Logo>", start, StringComparison.OrdinalIgnoreCase)
                    : xml.IndexOf('"', start);
                if (end <= start) continue;

                string relPath = xml[start..end].Trim().Replace('/', '\\');
                string? candidate = ResolveScaledAssetPath(dir, relPath);
                if (candidate != null)
                {
                    var img = TryLoadSessionIconPath(candidate);
                    if (img != null) return img;
                }
            }
        }
        catch
        {
        }
        return null;
    }

    private static string? ResolveScaledAssetPath(string baseDir, string relPath)
    {
        string exact = Path.Combine(baseDir, relPath);
        if (File.Exists(exact)) return exact;

        try
        {
            string? assetDir = Path.GetDirectoryName(exact);
            string stem = Path.GetFileNameWithoutExtension(exact);
            string ext = Path.GetExtension(exact);
            if (string.IsNullOrEmpty(assetDir) || !Directory.Exists(assetDir)) return null;

            string[] preferredSuffixes =
            {
                ".targetsize-32",
                ".targetsize-48",
                ".targetsize-24",
                ".scale-100",
                ".scale-125",
                ".scale-150",
                ".scale-200"
            };
            var files = Directory.GetFiles(assetDir, $"{stem}*{ext}");
            foreach (string suf in preferredSuffixes)
            {
                foreach (string f in files)
                {
                    if (f.Contains(suf, StringComparison.OrdinalIgnoreCase) &&
                        !f.Contains("contrast-", StringComparison.OrdinalIgnoreCase))
                    {
                        return f;
                    }
                }
            }
            if (files.Length > 0) return files[0];
        }
        catch
        {
        }
        return null;
    }

    private static ImageSource? TryLoadSessionIconPath(string? rawIconPath)
    {
        if (string.IsNullOrWhiteSpace(rawIconPath)) return null;

        try
        {
            string expanded = Environment.ExpandEnvironmentVariables(rawIconPath.Trim().Trim('"'));
            if (expanded.StartsWith("@")) expanded = expanded[1..];

            // Caso 1: arquivo de imagem direto (.png / .jpg / .ico — muito comum em apps UWP/Store)
            if (File.Exists(expanded))
            {
                string ext = Path.GetExtension(expanded).ToLowerInvariant();
                if (ext is ".png" or ".jpg" or ".jpeg" or ".bmp")
                {
                    var bmp = new BitmapImage();
                    bmp.BeginInit();
                    bmp.CacheOption = BitmapCacheOption.OnLoad;
                    bmp.DecodePixelWidth = 32;
                    bmp.UriSource = new Uri(expanded, UriKind.Absolute);
                    bmp.EndInit();
                    bmp.Freeze();
                    return bmp;
                }
                if (ext == ".ico")
                {
                    using var ico = new Icon(expanded, 32, 32);
                    return HIconToImageSource(ico.Handle);
                }
            }

            // Caso 2: caminho com índice de recurso (ex: C:\Windows\System32\AudioSrv.Dll,-203)
            int commaIdx = expanded.LastIndexOf(',');
            if (commaIdx > 0)
            {
                string filePart = expanded[..commaIdx].Trim().Trim('"');
                string idxPart = expanded[(commaIdx + 1)..].Trim();
                if (File.Exists(filePart) && int.TryParse(idxPart, out int iconIndex))
                {
                    uint count = ExtractIconEx(filePart, iconIndex, out IntPtr hLarge, out IntPtr hSmall, 1);
                    IntPtr hIcon = hLarge != IntPtr.Zero ? hLarge : hSmall;
                    try
                    {
                        if (count > 0 && hIcon != IntPtr.Zero)
                            return HIconToImageSource(hIcon);
                    }
                    finally
                    {
                        if (hLarge != IntPtr.Zero) DestroyIcon(hLarge);
                        if (hSmall != IntPtr.Zero) DestroyIcon(hSmall);
                    }
                }
            }
        }
        catch
        {
        }

        return null;
    }

    private static ImageSource? TryExtractShellIcon(string? exePath)
    {
        if (string.IsNullOrWhiteSpace(exePath) || !File.Exists(exePath)) return null;

        try
        {
            IntPtr res = SHGetFileInfo(
                exePath,
                0,
                out ShFileInfo shfi,
                (uint)Marshal.SizeOf<ShFileInfo>(),
                ShgfiIcon | ShgfiLargeIcon);

            if (res != IntPtr.Zero && shfi.hIcon != IntPtr.Zero)
            {
                try
                {
                    return HIconToImageSource(shfi.hIcon);
                }
                finally
                {
                    DestroyIcon(shfi.hIcon);
                }
            }
        }
        catch
        {
        }

        return null;
    }

    private static ImageSource? TryExtractAssociatedIcon(string? exePath)
    {
        if (string.IsNullOrWhiteSpace(exePath) || !File.Exists(exePath)) return null;

        try
        {
            using Icon? icon = Icon.ExtractAssociatedIcon(exePath);
            if (icon == null) return null;
            return HIconToImageSource(icon.Handle);
        }
        catch
        {
            return null;
        }
    }

    private static ImageSource HIconToImageSource(IntPtr hIcon)
    {
        var source = Imaging.CreateBitmapSourceFromHIcon(
            hIcon,
            Int32Rect.Empty,
            BitmapSizeOptions.FromWidthAndHeight(32, 32));
        source.Freeze();
        return source;
    }
}
