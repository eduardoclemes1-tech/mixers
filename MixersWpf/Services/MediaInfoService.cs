using System;
using System.Threading.Tasks;
using Windows.Media.Control;

namespace Mixers.Services;

public readonly record struct MediaStateInfo(string Title, bool IsPlaying);

public static class MediaInfoService
{
    private static GlobalSystemMediaTransportControlsSessionManager? _manager;

    public static async Task<MediaStateInfo> GetCurrentMediaStateAsync()
    {
        try
        {
            _manager ??= await GlobalSystemMediaTransportControlsSessionManager.RequestAsync();
            var session = _manager?.GetCurrentSession();
            if (session == null) return new MediaStateInfo("", false);

            bool isPlaying = false;
            try
            {
                var playback = session.GetPlaybackInfo();
                isPlaying = playback?.PlaybackStatus == GlobalSystemMediaTransportControlsSessionPlaybackStatus.Playing;
            }
            catch
            {
            }

            string displayTitle = "";
            try
            {
                var props = await session.TryGetMediaPropertiesAsync();
                if (props != null)
                {
                    string title = (props.Title ?? "").Trim();
                    string artist = (props.Artist ?? "").Trim();
                    if (!string.IsNullOrEmpty(title))
                    {
                        displayTitle = !string.IsNullOrEmpty(artist) && !title.Contains(artist, StringComparison.OrdinalIgnoreCase)
                            ? $"{artist} — {title}"
                            : title;
                    }
                }
            }
            catch
            {
            }

            return new MediaStateInfo(displayTitle, isPlaying);
        }
        catch
        {
            return new MediaStateInfo("", false);
        }
    }

    public static async Task<string> GetCurrentMediaTitleAsync()
        => (await GetCurrentMediaStateAsync()).Title;
}
