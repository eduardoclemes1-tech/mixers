using System;
using System.Diagnostics;
using System.IO;
using System.Net.Http;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading.Tasks;

namespace Mixers.Services;

public sealed class UpdateInfo
{
    public string Version { get; init; } = "";
    public string DownloadUrl { get; init; } = "";
    public string ReleaseUrl { get; init; } = "";
}

public static class UpdateService
{
    private const string Owner = "eduardoclemes1-tech";
    private const string Repo = "mixers";
    private const string LatestWebUrl = $"https://github.com/{Owner}/{Repo}/releases/latest";

    private static readonly HttpClient Http = new(new HttpClientHandler
    {
        AllowAutoRedirect = true
    })
    {
        Timeout = TimeSpan.FromSeconds(12)
    };

    static UpdateService()
    {
        Http.DefaultRequestHeaders.UserAgent.ParseAdd($"Mixers/{App.AppVersion}");
    }

    public static async Task<UpdateInfo?> CheckForUpdateAsync()
    {
        using var req = new HttpRequestMessage(HttpMethod.Get, LatestWebUrl);
        using var resp = await Http.SendAsync(req, HttpCompletionOption.ResponseHeadersRead);
        resp.EnsureSuccessStatusCode();

        string finalUrl = resp.RequestMessage?.RequestUri?.ToString() ?? "";
        var match = Regex.Match(finalUrl, @"/releases/tag/([^/?#]+)");
        if (!match.Success) return null;

        string tag = match.Groups[1].Value.Trim();
        string cleanLatest = tag.TrimStart('v', 'V');

        if (!IsNewer(cleanLatest, App.AppVersion)) return null;

        return new UpdateInfo
        {
            Version = cleanLatest,
            ReleaseUrl = finalUrl,
            DownloadUrl = $"https://github.com/{Owner}/{Repo}/releases/download/{tag}/Mixers.exe"
        };
    }

    public static async Task<bool> DownloadAndApplyAsync(UpdateInfo update, Action<int>? onProgress = null)
    {
        string currentExe = Process.GetCurrentProcess().MainModule?.FileName ?? Environment.ProcessPath ?? "";
        if (string.IsNullOrEmpty(currentExe) || !currentExe.EndsWith(".exe", StringComparison.OrdinalIgnoreCase))
        {
            Process.Start(new ProcessStartInfo(update.ReleaseUrl) { UseShellExecute = true });
            return false;
        }

        string newExe = currentExe + ".new";
        using var downloadClient = new HttpClient { Timeout = TimeSpan.FromMinutes(3) };
        downloadClient.DefaultRequestHeaders.UserAgent.ParseAdd($"Mixers/{App.AppVersion}");

        using (var resp = await downloadClient.GetAsync(update.DownloadUrl, HttpCompletionOption.ResponseHeadersRead))
        {
            resp.EnsureSuccessStatusCode();
            long total = resp.Content.Headers.ContentLength ?? -1;
            await using var stream = await resp.Content.ReadAsStreamAsync();
            await using var file = File.Create(newExe);

            var buffer = new byte[65536];
            long readTotal = 0;
            int read;
            while ((read = await stream.ReadAsync(buffer)) > 0)
            {
                await file.WriteAsync(buffer.AsMemory(0, read));
                readTotal += read;
                if (total > 0 && onProgress != null)
                {
                    onProgress((int)Math.Min(100, readTotal * 100 / total));
                }
            }
        }

        string batPath = Path.Combine(Path.GetTempPath(), "mixers_auto_update.bat");
        string bat =
            "@echo off\r\n" +
            "chcp 65001 > nul\r\n" +
            "setlocal EnableDelayedExpansion\r\n" +
            "ping 127.0.0.1 -n 3 > nul\r\n" +
            "set RETRIES=0\r\n" +
            ":retry\r\n" +
            $"move /Y \"{newExe}\" \"{currentExe}\" > nul 2>&1\r\n" +
            "if errorlevel 1 (\r\n" +
            "  set /a RETRIES+=1\r\n" +
            "  if !RETRIES! LSS 20 (\r\n" +
            "    ping 127.0.0.1 -n 2 > nul\r\n" +
            "    goto retry\r\n" +
            "  )\r\n" +
            "  exit /b 1\r\n" +
            ")\r\n" +
            $"start \"\" \"{currentExe}\"\r\n" +
            "del \"%~f0\"\r\n";

        File.WriteAllText(batPath, bat, new UTF8Encoding(false));

        Process.Start(new ProcessStartInfo("cmd.exe", $"/c \"{batPath}\"")
        {
            CreateNoWindow = true,
            UseShellExecute = false
        });
        return true;
    }

    private static bool IsNewer(string latest, string current)
    {
        if (Version.TryParse(NormalizeVer(latest), out var vLatest) &&
            Version.TryParse(NormalizeVer(current), out var vCurr))
        {
            return vLatest > vCurr;
        }
        return false;
    }

    private static string NormalizeVer(string v)
    {
        var parts = v.Split('.');
        return parts.Length == 2 ? $"{v}.0" : v;
    }
}
