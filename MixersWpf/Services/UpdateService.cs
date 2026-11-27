using System;
using System.Diagnostics;
using System.IO;
using System.Net;
using System.Net.Http;
using System.Text;
using System.Text.Json;
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
    private const string ApiLatestUrl = $"https://api.github.com/repos/{Owner}/{Repo}/releases/latest";
    private const string WebLatestUrl = $"https://github.com/{Owner}/{Repo}/releases/latest";

    private static HttpClient CreateClient(bool allowAutoRedirect, TimeSpan timeout)
    {
        var handler = new HttpClientHandler
        {
            AllowAutoRedirect = allowAutoRedirect,
            UseProxy = true,
            DefaultProxyCredentials = CredentialCache.DefaultCredentials,
            AutomaticDecompression = DecompressionMethods.All
        };
        var client = new HttpClient(handler) { Timeout = timeout };
        client.DefaultRequestHeaders.UserAgent.ParseAdd($"Mixers/{App.AppVersion}");
        return client;
    }

    public static async Task<UpdateInfo?> CheckForUpdateAsync()
    {
        Exception? apiError = null;

        // 1. Principal: GitHub REST API oficial (rápida e retorna URL exata do asset)
        try
        {
            return await CheckViaApiAsync();
        }
        catch (Exception ex)
        {
            apiError = ex;
            App.LogError("UpdateService.CheckViaApiAsync", ex);
        }

        // 2. Fallback: redirect /releases/latest sem baixar HTML
        try
        {
            return await CheckViaWebRedirectAsync();
        }
        catch (Exception ex)
        {
            App.LogError("UpdateService.CheckViaWebRedirectAsync", ex);
            throw apiError ?? ex;
        }
    }

    private static async Task<UpdateInfo?> CheckViaApiAsync()
    {
        using var client = CreateClient(allowAutoRedirect: true, timeout: TimeSpan.FromSeconds(12));
        using var req = new HttpRequestMessage(HttpMethod.Get, ApiLatestUrl);
        req.Headers.Accept.ParseAdd("application/vnd.github+json");
        req.Headers.Add("X-GitHub-Api-Version", "2022-11-28");

        using var resp = await client.SendAsync(req);
        if (!resp.IsSuccessStatusCode)
        {
            throw new HttpRequestException($"HTTP {(int)resp.StatusCode} ({resp.ReasonPhrase})");
        }

        string json = await resp.Content.ReadAsStringAsync();
        using var doc = JsonDocument.Parse(json);
        var root = doc.RootElement;

        string tag = root.TryGetProperty("tag_name", out var tagEl) ? (tagEl.GetString() ?? "").Trim() : "";
        if (string.IsNullOrEmpty(tag)) return null;

        string cleanLatest = tag.TrimStart('v', 'V');
        if (!IsNewer(cleanLatest, App.AppVersion)) return null;

        string releaseUrl = root.TryGetProperty("html_url", out var htmlEl)
            ? (htmlEl.GetString() ?? $"https://github.com/{Owner}/{Repo}/releases")
            : $"https://github.com/{Owner}/{Repo}/releases";

        string downloadUrl = $"https://github.com/{Owner}/{Repo}/releases/download/{tag}/Mixers.exe";
        if (root.TryGetProperty("assets", out var assetsEl) && assetsEl.ValueKind == JsonValueKind.Array)
        {
            foreach (var asset in assetsEl.EnumerateArray())
            {
                string name = asset.TryGetProperty("name", out var nEl) ? (nEl.GetString() ?? "") : "";
                string dl = asset.TryGetProperty("browser_download_url", out var uEl) ? (uEl.GetString() ?? "") : "";
                if (name.Equals("Mixers.exe", StringComparison.OrdinalIgnoreCase) && !string.IsNullOrEmpty(dl))
                {
                    downloadUrl = dl;
                    break;
                }
            }
        }

        return new UpdateInfo
        {
            Version = cleanLatest,
            ReleaseUrl = releaseUrl,
            DownloadUrl = downloadUrl
        };
    }

    private static async Task<UpdateInfo?> CheckViaWebRedirectAsync()
    {
        using var client = CreateClient(allowAutoRedirect: false, timeout: TimeSpan.FromSeconds(10));
        using var req = new HttpRequestMessage(HttpMethod.Head, WebLatestUrl);
        using var resp = await client.SendAsync(req);

        string finalUrl = "";
        if ((int)resp.StatusCode is >= 300 and < 400 && resp.Headers.Location != null)
        {
            finalUrl = resp.Headers.Location.IsAbsoluteUri
                ? resp.Headers.Location.ToString()
                : $"https://github.com{resp.Headers.Location}";
        }
        else if (!resp.IsSuccessStatusCode)
        {
            throw new HttpRequestException($"HTTP {(int)resp.StatusCode} ({resp.ReasonPhrase})");
        }

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
        using var downloadClient = CreateClient(allowAutoRedirect: true, timeout: TimeSpan.FromMinutes(3));

        using (var resp = await downloadClient.GetAsync(update.DownloadUrl, HttpCompletionOption.ResponseHeadersRead))
        {
            if (!resp.IsSuccessStatusCode)
            {
                throw new HttpRequestException($"HTTP {(int)resp.StatusCode} ({resp.ReasonPhrase})");
            }

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
