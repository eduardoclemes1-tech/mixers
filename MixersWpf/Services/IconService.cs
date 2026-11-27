using System;
using System.Collections.Generic;
using System.Drawing;
using System.IO;
using System.Windows;
using System.Windows.Interop;
using System.Windows.Media;
using System.Windows.Media.Imaging;

namespace Mixers.Services;

public static class IconService
{
    private static readonly Dictionary<string, ImageSource?> Cache = new(StringComparer.OrdinalIgnoreCase);

    public static ImageSource? GetExeIcon(string? exePath)
    {
        if (string.IsNullOrWhiteSpace(exePath)) return null;
        if (Cache.TryGetValue(exePath, out var cached)) return cached;

        try
        {
            if (!File.Exists(exePath))
            {
                Cache[exePath] = null;
                return null;
            }

            using Icon? icon = Icon.ExtractAssociatedIcon(exePath);
            if (icon == null)
            {
                Cache[exePath] = null;
                return null;
            }

            var source = Imaging.CreateBitmapSourceFromHIcon(
                icon.Handle,
                Int32Rect.Empty,
                BitmapSizeOptions.FromWidthAndHeight(24, 24));
            source.Freeze();
            Cache[exePath] = source;
            return source;
        }
        catch
        {
            Cache[exePath] = null;
            return null;
        }
    }
}
