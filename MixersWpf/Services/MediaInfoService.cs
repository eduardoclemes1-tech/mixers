using System;
using System.Threading.Tasks;
using Windows.Media.Control;

namespace Mixers.Services;

public static class MediaInfoService
{
    private static GlobalSystemMediaTransportControlsSessionManager? _manager;

    public static async Task<string> GetCurrentMediaTitleAsync()
    {
        try
        {
            _manager ??= await GlobalSystemMediaTransportControlsSessionManager.RequestAsync();
            var session = _manager?.GetCurrentSession();
            if (session == null) return "";

            var props = await session.TryGetMediaPropertiesAsync();
            if (props == null) return "";

            string title = (props.Title ?? "").Trim();
            string artist = (props.Artist ?? "").Trim();

            if (string.IsNullOrEmpty(title)) return "";
            if (!string.IsNullOrEmpty(artist) && !title.Contains(artist, StringComparison.OrdinalIgnoreCase))
                return $"{artist} — {title}";
            return title;
        }
        catch
        {
            return "";
        }
    }
}
