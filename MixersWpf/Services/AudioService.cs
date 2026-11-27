using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Linq;
using NAudio.CoreAudioApi;
using NAudio.CoreAudioApi.Interfaces;
using NAudio.Wave;

namespace Mixers.Services;

public sealed class AppSessionInfo
{
    public string AppId { get; init; } = "";
    public string DisplayName { get; init; } = "";
    public string? ExePath { get; set; }
    public float Volume { get; set; }
    public bool Muted { get; set; }
    public float PeakLevel { get; set; }
    public bool IsSystemSounds { get; init; }
}

public sealed class MicrophoneInfo
{
    public string DeviceId { get; init; } = "";
    public string Name { get; init; } = "";
    public float Volume { get; set; }
    public bool Muted { get; set; }
    public float PeakLevel { get; set; }
}

public sealed class AudioService : IDisposable
{
    public const string SystemSoundsId = "__system_sounds__";

    private readonly MMDeviceEnumerator _enumerator = new();
    private MMDevice? _defaultOutput;
    private readonly Dictionary<string, List<AudioSessionControl>> _sessionCache = new(StringComparer.OrdinalIgnoreCase);
    private readonly Dictionary<uint, (string AppId, string DisplayName, string? ExePath)> _pidMetaCache = new();
    private readonly Dictionary<string, MMDevice> _micCache = new(StringComparer.OrdinalIgnoreCase);
    private WasapiCapture? _micTestCapture;

    public bool IsMicTesting => _micTestCapture != null;

    public AudioService()
    {
        RefreshDefaultOutput();
    }

    private void RefreshDefaultOutput()
    {
        try
        {
            _defaultOutput?.Dispose();
            _defaultOutput = _enumerator.GetDefaultAudioEndpoint(DataFlow.Render, Role.Multimedia);
        }
        catch
        {
            _defaultOutput = null;
        }
    }

    public string GetOutputDeviceName()
    {
        try
        {
            if (_defaultOutput == null) RefreshDefaultOutput();
            return _defaultOutput?.FriendlyName ?? "Saída Padrão";
        }
        catch
        {
            return "Saída Padrão";
        }
    }

    public float GetMasterVolume()
    {
        try
        {
            if (_defaultOutput == null) RefreshDefaultOutput();
            return Math.Clamp(_defaultOutput?.AudioEndpointVolume.MasterVolumeLevelScalar ?? 1f, 0f, 1f);
        }
        catch
        {
            RefreshDefaultOutput();
            return Math.Clamp(_defaultOutput?.AudioEndpointVolume.MasterVolumeLevelScalar ?? 1f, 0f, 1f);
        }
    }

    public void SetMasterVolume(float volume)
    {
        float v = Math.Clamp(volume, 0f, 1f);
        try
        {
            if (_defaultOutput == null) RefreshDefaultOutput();
            if (_defaultOutput != null) _defaultOutput.AudioEndpointVolume.MasterVolumeLevelScalar = v;
        }
        catch
        {
            RefreshDefaultOutput();
            if (_defaultOutput != null) _defaultOutput.AudioEndpointVolume.MasterVolumeLevelScalar = v;
        }
    }

    public bool GetMasterMute()
    {
        try
        {
            if (_defaultOutput == null) RefreshDefaultOutput();
            return _defaultOutput?.AudioEndpointVolume.Mute ?? false;
        }
        catch
        {
            RefreshDefaultOutput();
            return _defaultOutput?.AudioEndpointVolume.Mute ?? false;
        }
    }

    public void SetMasterMute(bool muted)
    {
        try
        {
            if (_defaultOutput == null) RefreshDefaultOutput();
            if (_defaultOutput != null) _defaultOutput.AudioEndpointVolume.Mute = muted;
        }
        catch
        {
            RefreshDefaultOutput();
            if (_defaultOutput != null) _defaultOutput.AudioEndpointVolume.Mute = muted;
        }
    }

    public float GetMasterPeak()
    {
        try
        {
            if (_defaultOutput == null || _defaultOutput.AudioEndpointVolume.Mute) return 0f;
            return Math.Clamp(_defaultOutput.AudioMeterInformation.MasterPeakValue, 0f, 1f);
        }
        catch
        {
            return 0f;
        }
    }

    public List<AppSessionInfo> RefreshAppSessions()
    {
        var grouped = new Dictionary<string, AppSessionInfo>(StringComparer.OrdinalIgnoreCase);
        var newCache = new Dictionary<string, List<AudioSessionControl>>(StringComparer.OrdinalIgnoreCase);

        try
        {
            if (_defaultOutput == null) RefreshDefaultOutput();
            var sessions = _defaultOutput?.AudioSessionManager.Sessions;
            if (sessions != null)
            {
                for (int i = 0; i < sessions.Count; i++)
                {
                    AudioSessionControl s;
                    try
                    {
                        s = sessions[i];
                        if (s.State == AudioSessionState.AudioSessionStateExpired) continue;
                    }
                    catch
                    {
                        continue;
                    }

                    bool isSys = s.IsSystemSoundsSession;
                    string appId;
                    string displayName;
                    string? exePath = null;

                    if (isSys)
                    {
                        appId = SystemSoundsId;
                        displayName = "Sons do Sistema";
                    }
                    else
                    {
                        uint pid = s.GetProcessID;
                        if (pid == 0)
                        {
                            appId = SystemSoundsId;
                            displayName = "Sons do Sistema";
                            isSys = true;
                        }
                        else
                        {
                            if (_pidMetaCache.TryGetValue(pid, out var cachedMeta))
                            {
                                appId = cachedMeta.AppId;
                                displayName = cachedMeta.DisplayName;
                                exePath = cachedMeta.ExePath;
                            }
                            else
                            {
                                try
                                {
                                    using var proc = Process.GetProcessById((int)pid);
                                    string rawName = proc.ProcessName;
                                    appId = rawName.ToLowerInvariant();
                                    displayName = FormatAppName(rawName);
                                    try
                                    {
                                        exePath = proc.MainModule?.FileName;
                                    }
                                    catch
                                    {
                                    }
                                    _pidMetaCache[pid] = (appId, displayName, exePath);
                                }
                                catch
                                {
                                    continue;
                                }
                            }
                        }
                    }

                    float vol;
                    bool muted;
                    float peak = 0f;
                    try
                    {
                        vol = Math.Clamp(s.SimpleAudioVolume.Volume, 0f, 1f);
                        muted = s.SimpleAudioVolume.Mute;
                        if (!muted) peak = Math.Clamp(s.AudioMeterInformation.MasterPeakValue, 0f, 1f);
                    }
                    catch
                    {
                        continue;
                    }

                    if (!newCache.TryGetValue(appId, out var list))
                    {
                        list = new List<AudioSessionControl>();
                        newCache[appId] = list;
                    }
                    list.Add(s);

                    if (!grouped.TryGetValue(appId, out var info))
                    {
                        grouped[appId] = new AppSessionInfo
                        {
                            AppId = appId,
                            DisplayName = displayName,
                            ExePath = exePath,
                            Volume = vol,
                            Muted = muted,
                            PeakLevel = peak,
                            IsSystemSounds = isSys
                        };
                    }
                    else
                    {
                        if (string.IsNullOrEmpty(info.ExePath) && !string.IsNullOrEmpty(exePath))
                            info.ExePath = exePath;
                        if (peak > info.PeakLevel)
                            info.PeakLevel = peak;
                    }
                }
            }
        }
        catch
        {
            RefreshDefaultOutput();
        }

        foreach (var oldList in _sessionCache.Values)
        {
            foreach (var oldCtrl in oldList)
            {
                try { oldCtrl.Dispose(); } catch { }
            }
        }
        _sessionCache.Clear();
        foreach (var kv in newCache) _sessionCache[kv.Key] = kv.Value;
        if (_pidMetaCache.Count > 128) _pidMetaCache.Clear();

        return grouped.Values
            .OrderBy(a => !a.IsSystemSounds)
            .ThenBy(a => a.DisplayName, StringComparer.OrdinalIgnoreCase)
            .ToList();
    }

    public Dictionary<string, float> GetAppPeaks()
    {
        var peaks = new Dictionary<string, float>(StringComparer.OrdinalIgnoreCase);
        foreach (var (appId, controls) in _sessionCache)
        {
            float best = 0f;
            foreach (var c in controls)
            {
                try
                {
                    if (c.SimpleAudioVolume.Mute) continue;
                    float p = Math.Clamp(c.AudioMeterInformation.MasterPeakValue, 0f, 1f);
                    if (p > best) best = p;
                }
                catch
                {
                }
            }
            peaks[appId] = best;
        }
        return peaks;
    }

    public void SetAppVolume(string appId, float volume)
    {
        float v = Math.Clamp(volume, 0f, 1f);
        if (!_sessionCache.TryGetValue(appId, out var controls)) return;
        foreach (var c in controls)
        {
            try
            {
                c.SimpleAudioVolume.Volume = v;
            }
            catch
            {
            }
        }
    }

    public void SetAppMute(string appId, bool muted)
    {
        if (!_sessionCache.TryGetValue(appId, out var controls)) return;
        foreach (var c in controls)
        {
            try
            {
                c.SimpleAudioVolume.Mute = muted;
            }
            catch
            {
            }
        }
    }

    public List<MicrophoneInfo> RefreshMicrophones()
    {
        var list = new List<MicrophoneInfo>();
        var newCache = new Dictionary<string, MMDevice>(StringComparer.OrdinalIgnoreCase);

        try
        {
            var devices = _enumerator.EnumerateAudioEndPoints(DataFlow.Capture, DeviceState.Active);
            foreach (var dev in devices)
            {
                try
                {
                    float vol = Math.Clamp(dev.AudioEndpointVolume.MasterVolumeLevelScalar, 0f, 1f);
                    bool muted = dev.AudioEndpointVolume.Mute;
                    float peak = muted ? 0f : Math.Clamp(dev.AudioMeterInformation.MasterPeakValue, 0f, 1f);

                    newCache[dev.ID] = dev;
                    list.Add(new MicrophoneInfo
                    {
                        DeviceId = dev.ID,
                        Name = dev.FriendlyName,
                        Volume = vol,
                        Muted = muted,
                        PeakLevel = peak
                    });
                }
                catch
                {
                    dev.Dispose();
                }
            }
        }
        catch
        {
        }

        foreach (var old in _micCache.Values)
        {
            try { old.Dispose(); } catch { }
        }
        _micCache.Clear();
        foreach (var kv in newCache) _micCache[kv.Key] = kv.Value;

        return list.OrderBy(m => m.Name, StringComparer.OrdinalIgnoreCase).ToList();
    }

    public Dictionary<string, float> GetMicPeaks()
    {
        var peaks = new Dictionary<string, float>(StringComparer.OrdinalIgnoreCase);
        foreach (var (id, dev) in _micCache)
        {
            try
            {
                peaks[id] = dev.AudioEndpointVolume.Mute
                    ? 0f
                    : Math.Clamp(dev.AudioMeterInformation.MasterPeakValue, 0f, 1f);
            }
            catch
            {
                peaks[id] = 0f;
            }
        }
        return peaks;
    }

    public void SetMicVolume(string deviceId, float volume)
    {
        if (!_micCache.TryGetValue(deviceId, out var dev)) return;
        try
        {
            dev.AudioEndpointVolume.MasterVolumeLevelScalar = Math.Clamp(volume, 0f, 1f);
        }
        catch
        {
        }
    }

    public void SetMicMute(string deviceId, bool muted)
    {
        if (!_micCache.TryGetValue(deviceId, out var dev)) return;
        try
        {
            dev.AudioEndpointVolume.Mute = muted;
        }
        catch
        {
        }
    }

    public bool StartMicTest()
    {
        if (_micTestCapture != null) return true;
        try
        {
            _micTestCapture = new WasapiCapture();
            _micTestCapture.StartRecording();
            return true;
        }
        catch
        {
            StopMicTest();
            return false;
        }
    }

    public void StopMicTest()
    {
        if (_micTestCapture == null) return;
        try
        {
            _micTestCapture.StopRecording();
            _micTestCapture.Dispose();
        }
        catch
        {
        }
        _micTestCapture = null;
    }

    public static (string Label, System.Windows.Media.Color Color) ClassifyMicQuality(float peak, bool muted)
    {
        if (muted) return ("Mutado", System.Windows.Media.Color.FromRgb(148, 163, 184));
        if (peak < 0.02f) return ("Silêncio", System.Windows.Media.Colors.White);
        if (peak < 0.14f) return ("Baixo", System.Windows.Media.Color.FromRgb(251, 191, 36));
        if (peak <= 0.78f) return ("Ideal", System.Windows.Media.Color.FromRgb(52, 211, 153));
        return ("Alto!", System.Windows.Media.Color.FromRgb(248, 113, 113));
    }

    private static string FormatAppName(string raw)
    {
        string cleaned = raw.Trim();
        if (cleaned.EndsWith(".exe", StringComparison.OrdinalIgnoreCase))
            cleaned = cleaned[..^4];
        if (string.IsNullOrEmpty(cleaned)) return "Aplicativo";
        return char.ToUpperInvariant(cleaned[0]) + cleaned[1..];
    }

    public void Dispose()
    {
        StopMicTest();
        foreach (var dev in _micCache.Values)
        {
            try { dev.Dispose(); } catch { }
        }
        _micCache.Clear();
        _defaultOutput?.Dispose();
        _enumerator.Dispose();
    }
}
