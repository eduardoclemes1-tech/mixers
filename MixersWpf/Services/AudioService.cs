using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Runtime.InteropServices;
using System.Text;
using NAudio.CoreAudioApi;
using NAudio.CoreAudioApi.Interfaces;
using NAudio.Wave;

namespace Mixers.Services;

public sealed class AppSessionInfo
{
    public string AppId { get; init; } = "";
    public string DisplayName { get; init; } = "";
    public string? ExePath { get; set; }
    public string? IconPath { get; set; }
    public float Volume { get; set; }
    public bool Muted { get; set; }
    public float PeakLevel { get; set; }
    public bool IsActive { get; set; }
    public bool HasAudioSession { get; set; } = true;
    public bool IsSystemSounds { get; init; }
    public List<string> SessionInstanceIds { get; } = new();
}

public sealed class OutputDeviceInfo
{
    public string DeviceId { get; init; } = "";
    public string Name { get; init; } = "";
    public bool IsDefault { get; init; }
}

public sealed class MicrophoneInfo
{
    public string DeviceId { get; init; } = "";
    public string Name { get; init; } = "";
    public float Volume { get; set; }
    public bool Muted { get; set; }
    public float PeakLevel { get; set; }
}

[ComImport]
[Guid("f8679f50-850a-41cf-9c72-430f290290c8")]
[InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
internal interface IPolicyConfig
{
    int GetMixFormat(string pszDeviceName, IntPtr ppFormat);
    int GetDeviceFormat(string pszDeviceName, bool bDefault, IntPtr ppFormat);
    int ResetDeviceFormat(string pszDeviceName);
    int SetDeviceFormat(string pszDeviceName, IntPtr pEndpointFormat, IntPtr mixFormat);
    int GetProcessingPeriod(string pszDeviceName, bool bDefault, IntPtr pmftDefaultPeriod, IntPtr pmftMinimumPeriod);
    int SetProcessingPeriod(string pszDeviceName, IntPtr pmftPeriod);
    int GetShareMode(string pszDeviceName, IntPtr pMode);
    int SetShareMode(string pszDeviceName, IntPtr mode);
    int GetPropertyValue(string pszDeviceName, bool bFxStore, IntPtr key, IntPtr pv);
    int SetPropertyValue(string pszDeviceName, bool bFxStore, IntPtr key, IntPtr pv);
    int SetDefaultEndpoint([MarshalAs(UnmanagedType.LPWStr)] string pszDeviceId, int role);
}

[ComImport]
[Guid("87CE5498-68D6-44E5-9215-6DA47EF883D8")]
[InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
internal interface ISimpleAudioVolumeCom
{
    int SetMasterVolume(float fLevel, ref Guid eventContext);
    int GetMasterVolume(out float pfLevel);
    int SetMute([MarshalAs(UnmanagedType.Bool)] bool bMute, ref Guid eventContext);
    int GetMute([MarshalAs(UnmanagedType.Bool)] out bool pbMute);
}

public sealed class AudioService : IDisposable
{
    public const string SystemSoundsId = "__system_sounds__";
    private const uint ProcessQueryLimitedInformation = 0x1000;

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern IntPtr OpenProcess(uint dwDesiredAccess, bool bInheritHandle, uint dwProcessId);

    [DllImport("kernel32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
    private static extern bool QueryFullProcessImageName(IntPtr hProcess, uint dwFlags, StringBuilder lpExeName, ref uint lpdwSize);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool CloseHandle(IntPtr hObject);

    [DllImport("kernel32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
    private static extern uint QueryDosDevice(string lpDeviceName, StringBuilder lpTargetPath, uint ucchMax);

    [DllImport("user32.dll")]
    private static extern void keybd_event(byte bVk, byte bScan, uint dwFlags, UIntPtr dwExtraInfo);

    public const byte VkMediaNextTrack = 0xB0;
    public const byte VkMediaPrevTrack = 0xB1;
    public const byte VkMediaPlayPause = 0xB3;

    public event Action? SessionsChanged;
    public event Action? DevicesChanged;

    private sealed class RenderEndpointEntry : IDisposable
    {
        public required string DeviceId { get; init; }
        public required MMDevice Device { get; init; }
        public required AudioSessionManager Manager { get; init; }
        public bool IsDefault { get; init; }
        public AudioSessionManager.SessionCreatedDelegate? SessionCreatedHandler { get; set; }

        public void Dispose()
        {
            try
            {
                if (SessionCreatedHandler != null)
                {
                    Manager.OnSessionCreated -= SessionCreatedHandler;
                    SessionCreatedHandler = null;
                }
            }
            catch { }
            try { Manager.Dispose(); } catch { }
            try { Device.Dispose(); } catch { }
        }
    }

    private sealed class EndpointNotificationClient : IMMNotificationClient
    {
        private readonly Action _onChanged;

        public EndpointNotificationClient(Action onChanged) => _onChanged = onChanged;

        public void OnDeviceStateChanged(string deviceId, DeviceState newState) => _onChanged();
        public void OnDeviceAdded(string pwstrDeviceId) => _onChanged();
        public void OnDeviceRemoved(string deviceId) => _onChanged();
        public void OnDefaultDeviceChanged(DataFlow flow, Role role, string defaultDeviceId)
        {
            if (flow == DataFlow.Render || flow == DataFlow.Capture)
                _onChanged();
        }
        public void OnPropertyValueChanged(string pwstrDeviceId, PropertyKey key) { }
    }

    public static void SendMediaKey(byte vk)
    {
        try
        {
            keybd_event(vk, 0, 0, UIntPtr.Zero);
            keybd_event(vk, 0, 2, UIntPtr.Zero); // KEYEVENTF_KEYUP = 2
        }
        catch
        {
        }
    }

    private static readonly Dictionary<string, string> DevicePrefixToDriveMap = BuildDevicePrefixMap();

    private static Dictionary<string, string> BuildDevicePrefixMap()
    {
        var map = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        try
        {
            var sb = new StringBuilder(512);
            foreach (string drive in Directory.GetLogicalDrives())
            {
                string dosName = drive.TrimEnd('\\');
                sb.Clear();
                if (QueryDosDevice(dosName, sb, (uint)sb.Capacity) > 0)
                {
                    string ntPrefix = sb.ToString();
                    if (!string.IsNullOrEmpty(ntPrefix))
                        map[ntPrefix] = dosName;
                }
            }
        }
        catch
        {
        }
        return map;
    }

    private static string? ConvertNtPathToDosPath(string? ntPath)
    {
        if (string.IsNullOrWhiteSpace(ntPath)) return null;
        if (ntPath.Length >= 2 && ntPath[1] == ':') return ntPath;

        foreach (var (ntPrefix, drive) in DevicePrefixToDriveMap)
        {
            if (ntPath.StartsWith(ntPrefix, StringComparison.OrdinalIgnoreCase))
            {
                return drive + ntPath[ntPrefix.Length..];
            }
        }
        return null;
    }

    private static (string? ExePath, string? RawName) ParseSessionIdentifier(string? sessionId)
    {
        if (string.IsNullOrWhiteSpace(sessionId)) return (null, null);

        // Formato WASAPI típico:
        // {endpoint}|\Device\HarddiskVolume3\...\App.exe%b{guid}
        // ou UWP: {endpoint}|#...!<AppId>%b{guid}
        int pipeIdx = sessionId.IndexOf('|');
        if (pipeIdx < 0 || pipeIdx + 1 >= sessionId.Length) return (null, null);

        string payload = sessionId[(pipeIdx + 1)..];
        int pctIdx = payload.IndexOf("%b", StringComparison.OrdinalIgnoreCase);
        if (pctIdx >= 0) payload = payload[..pctIdx];
        payload = payload.Trim();

        if (string.IsNullOrEmpty(payload) || payload == "#") return (null, null);

        // Caminho de executável NT (\Device\HarddiskVolumeX\...\app.exe) ou DOS (C:\...\app.exe)
        if (payload.EndsWith(".exe", StringComparison.OrdinalIgnoreCase) || payload.Contains('\\'))
        {
            string? dosPath = ConvertNtPathToDosPath(payload);
            string candidate = dosPath ?? payload;
            try
            {
                string fileName = Path.GetFileNameWithoutExtension(candidate);
                if (!string.IsNullOrWhiteSpace(fileName))
                    return (dosPath, fileName);
            }
            catch
            {
            }
        }

        // Fallback UWP/Store (#...\PackageFamilyName!App)
        int bangIdx = payload.LastIndexOf('!');
        if (bangIdx > 0)
        {
            string pkgPart = payload[..bangIdx];
            int slash = Math.Max(pkgPart.LastIndexOf('\\'), pkgPart.LastIndexOf('/'));
            if (slash >= 0 && slash + 1 < pkgPart.Length) pkgPart = pkgPart[(slash + 1)..];
            pkgPart = pkgPart.TrimStart('#');
            int under = pkgPart.IndexOf('_');
            if (under > 0) pkgPart = pkgPart[..under];
            int dot = pkgPart.LastIndexOf('.');
            if (dot >= 0 && dot + 1 < pkgPart.Length) pkgPart = pkgPart[(dot + 1)..];
            if (!string.IsNullOrWhiteSpace(pkgPart))
                return (null, pkgPart);
        }

        return (null, null);
    }

    private static string? GetProcessExePathSafe(uint pid)
    {
        IntPtr hProc = OpenProcess(ProcessQueryLimitedInformation, false, pid);
        if (hProc == IntPtr.Zero) return null;
        try
        {
            var sb = new StringBuilder(1024);
            uint size = (uint)sb.Capacity;
            if (QueryFullProcessImageName(hProc, 0, sb, ref size) && size > 0)
            {
                return sb.ToString();
            }
        }
        catch
        {
        }
        finally
        {
            CloseHandle(hProc);
        }
        return null;
    }

    private readonly MMDeviceEnumerator _enumerator = new();
    private readonly EndpointNotificationClient _notificationClient;
    private readonly List<RenderEndpointEntry> _renderEndpoints = new();
    private MMDevice? _defaultOutput;
    private string _defaultOutputId = "";
    private volatile bool _endpointsDirty = true;

    private readonly Dictionary<string, List<AudioSessionControl>> _sessionCache = new(StringComparer.OrdinalIgnoreCase);
    private readonly Dictionary<(uint Pid, string SessionId), (string AppId, string DisplayName, string? ExePath)> _sessionMetaCache = new();
    private readonly ConcurrentDictionary<string, (float? Volume, bool? Muted)> _desiredAppStates = new(StringComparer.OrdinalIgnoreCase);
    private readonly Dictionary<string, MMDevice> _micCache = new(StringComparer.OrdinalIgnoreCase);
    private WasapiCapture? _micTestCapture;

    public bool IsMicTesting => _micTestCapture != null;

    public void SetDesiredAppState(string appId, float? volume, bool? muted)
    {
        if (string.IsNullOrWhiteSpace(appId) || appId == SystemSoundsId) return;
        _desiredAppStates.AddOrUpdate(
            appId,
            _ => (volume.HasValue ? Math.Clamp(volume.Value, 0f, 1f) : null, muted),
            (_, prev) => (volume.HasValue ? Math.Clamp(volume.Value, 0f, 1f) : prev.Volume, muted ?? prev.Muted));
    }

    public void ClearDesiredAppState(string appId)
    {
        if (string.IsNullOrWhiteSpace(appId)) return;
        _desiredAppStates.TryRemove(appId, out _);
    }

    private void ApplyDesiredStateToNewSession(IAudioSessionControl? newSession)
    {
        if (newSession == null || _desiredAppStates.IsEmpty) return;
        try
        {
            if (newSession is not IAudioSessionControl2 ctrl2) return;
            if (ctrl2.IsSystemSoundsSession() == 0) return;

            ctrl2.GetProcessId(out uint pid);
            if (pid == 0) return;

            ctrl2.GetSessionIdentifier(out string sessionId);
            var procSnap = OpenAppsService.CaptureProcessSnapshot();
            var (appId, _, _) = ResolveAppMetadata(pid, sessionId ?? "", null, procSnap);

            if (_desiredAppStates.TryGetValue(appId, out var desired) &&
                newSession is ISimpleAudioVolumeCom simpleVol)
            {
                Guid ctx = Guid.Empty;
                if (desired.Volume.HasValue)
                    simpleVol.SetMasterVolume(Math.Clamp(desired.Volume.Value, 0f, 1f), ref ctx);
                if (desired.Muted.HasValue)
                    simpleVol.SetMute(desired.Muted.Value, ref ctx);
            }
        }
        catch
        {
        }
    }

    public AudioService()
    {
        _notificationClient = new EndpointNotificationClient(() =>
        {
            _endpointsDirty = true;
            DevicesChanged?.Invoke();
        });
        try
        {
            _enumerator.RegisterEndpointNotificationCallback(_notificationClient);
        }
        catch
        {
        }
        RebuildRenderEndpoints();
    }

    public void MarkEndpointsDirty()
    {
        _endpointsDirty = true;
    }

    private void RebuildRenderEndpoints()
    {
        _endpointsDirty = false;
        DisposeSessionCache();

        foreach (var ep in _renderEndpoints)
        {
            ep.Dispose();
        }
        _renderEndpoints.Clear();
        _defaultOutput = null;
        _defaultOutputId = "";

        try
        {
            using var def = _enumerator.GetDefaultAudioEndpoint(DataFlow.Render, Role.Multimedia);
            _defaultOutputId = def?.ID ?? "";
        }
        catch
        {
            _defaultOutputId = "";
        }

        try
        {
            var devices = _enumerator.EnumerateAudioEndPoints(DataFlow.Render, DeviceState.Active);
            foreach (var dev in devices)
            {
                bool isDefault = string.Equals(dev.ID, _defaultOutputId, StringComparison.OrdinalIgnoreCase);
                try
                {
                    var mgr = dev.AudioSessionManager;
                    AudioSessionManager.SessionCreatedDelegate handler = (_, newSession) =>
                    {
                        ApplyDesiredStateToNewSession(newSession);
                        SessionsChanged?.Invoke();
                    };
                    try
                    {
                        mgr.OnSessionCreated += handler;
                    }
                    catch
                    {
                        handler = null!;
                    }

                    var entry = new RenderEndpointEntry
                    {
                        DeviceId = dev.ID,
                        Device = dev,
                        Manager = mgr,
                        IsDefault = isDefault,
                        SessionCreatedHandler = handler
                    };
                    _renderEndpoints.Add(entry);
                    if (isDefault)
                    {
                        _defaultOutput = dev;
                    }
                }
                catch
                {
                    try { dev.Dispose(); } catch { }
                }
            }
        }
        catch
        {
        }

        if (_defaultOutput == null && _renderEndpoints.Count > 0)
        {
            _defaultOutput = _renderEndpoints[0].Device;
            _defaultOutputId = _renderEndpoints[0].DeviceId;
        }
    }

    private void EnsureEndpointsReady()
    {
        if (_endpointsDirty || _renderEndpoints.Count == 0 || _defaultOutput == null)
        {
            RebuildRenderEndpoints();
        }
    }

    public List<OutputDeviceInfo> ListOutputDevices()
    {
        var list = new List<OutputDeviceInfo>();
        string defaultId = "";
        try
        {
            using var def = _enumerator.GetDefaultAudioEndpoint(DataFlow.Render, Role.Multimedia);
            defaultId = def?.ID ?? "";
            var devices = _enumerator.EnumerateAudioEndPoints(DataFlow.Render, DeviceState.Active);
            foreach (var dev in devices)
            {
                try
                {
                    list.Add(new OutputDeviceInfo
                    {
                        DeviceId = dev.ID,
                        Name = dev.FriendlyName,
                        IsDefault = string.Equals(dev.ID, defaultId, StringComparison.OrdinalIgnoreCase)
                    });
                }
                finally
                {
                    dev.Dispose();
                }
            }
        }
        catch
        {
        }
        return list.OrderByDescending(d => d.IsDefault).ThenBy(d => d.Name, StringComparer.OrdinalIgnoreCase).ToList();
    }

    public bool SetDefaultOutputDevice(string deviceId)
    {
        try
        {
            var clsid = new Guid("870af99c-171d-4f9e-af0d-e63df40c2bc9");
            var type = Type.GetTypeFromCLSID(clsid);
            if (type == null) return false;
            var policy = Activator.CreateInstance(type) as IPolicyConfig;
            if (policy == null) return false;

            policy.SetDefaultEndpoint(deviceId, 0); // eConsole
            policy.SetDefaultEndpoint(deviceId, 1); // eMultimedia
            policy.SetDefaultEndpoint(deviceId, 2); // eCommunications
            RebuildRenderEndpoints();
            return true;
        }
        catch
        {
            return false;
        }
    }

    public bool ToggleAllMicsMute()
    {
        if (_micCache.Count == 0) RefreshMicrophones();
        if (_micCache.Count == 0) return false;

        bool anyUnmuted = false;
        foreach (var dev in _micCache.Values)
        {
            try
            {
                if (!dev.AudioEndpointVolume.Mute) { anyUnmuted = true; break; }
            }
            catch { }
        }

        bool targetMute = anyUnmuted;
        foreach (var dev in _micCache.Values)
        {
            try { dev.AudioEndpointVolume.Mute = targetMute; } catch { }
        }
        return targetMute;
    }

    public bool AreAllMicsMuted()
    {
        if (_micCache.Count == 0) return false;
        foreach (var dev in _micCache.Values)
        {
            try
            {
                if (!dev.AudioEndpointVolume.Mute) return false;
            }
            catch { }
        }
        return true;
    }

    public string GetOutputDeviceName()
    {
        try
        {
            EnsureEndpointsReady();
            return _defaultOutput?.FriendlyName ?? "Saída Padrão";
        }
        catch
        {
            _endpointsDirty = true;
            return "Saída Padrão";
        }
    }

    public float GetMasterVolume()
    {
        try
        {
            EnsureEndpointsReady();
            return Math.Clamp(_defaultOutput?.AudioEndpointVolume.MasterVolumeLevelScalar ?? 1f, 0f, 1f);
        }
        catch
        {
            RebuildRenderEndpoints();
            return Math.Clamp(_defaultOutput?.AudioEndpointVolume.MasterVolumeLevelScalar ?? 1f, 0f, 1f);
        }
    }

    public void SetMasterVolume(float volume)
    {
        float v = Math.Clamp(volume, 0f, 1f);
        try
        {
            EnsureEndpointsReady();
            if (_defaultOutput != null) _defaultOutput.AudioEndpointVolume.MasterVolumeLevelScalar = v;
        }
        catch
        {
            RebuildRenderEndpoints();
            if (_defaultOutput != null) _defaultOutput.AudioEndpointVolume.MasterVolumeLevelScalar = v;
        }
    }

    public bool GetMasterMute()
    {
        try
        {
            EnsureEndpointsReady();
            return _defaultOutput?.AudioEndpointVolume.Mute ?? false;
        }
        catch
        {
            RebuildRenderEndpoints();
            return _defaultOutput?.AudioEndpointVolume.Mute ?? false;
        }
    }

    public void SetMasterMute(bool muted)
    {
        try
        {
            EnsureEndpointsReady();
            if (_defaultOutput != null) _defaultOutput.AudioEndpointVolume.Mute = muted;
        }
        catch
        {
            RebuildRenderEndpoints();
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

    public List<AppSessionInfo> RefreshAppSessions(Dictionary<uint, ProcessSnapEntry>? procSnapshot = null)
    {
        EnsureEndpointsReady();
        var procSnap = procSnapshot ?? OpenAppsService.CaptureProcessSnapshot();

        var grouped = new Dictionary<string, AppSessionInfo>(StringComparer.OrdinalIgnoreCase);
        var groupPriority = new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase);
        var newCache = new Dictionary<string, List<AudioSessionControl>>(StringComparer.OrdinalIgnoreCase);

        foreach (var endpoint in _renderEndpoints)
        {
            try
            {
                // CRÍTICO: NAudio mantém cache estático em AudioSessionManager.Sessions.
                // Sem RefreshSessions(), nenhum app novo aberto depois do início aparece!
                endpoint.Manager.RefreshSessions();
                var sessions = endpoint.Manager.Sessions;
                if (sessions == null) continue;

                for (int i = 0; i < sessions.Count; i++)
                {
                    AudioSessionControl s;
                    AudioSessionState state;
                    try
                    {
                        s = sessions[i];
                        state = s.State;
                        if (state == AudioSessionState.AudioSessionStateExpired)
                        {
                            try { s.Dispose(); } catch { }
                            continue;
                        }
                    }
                    catch
                    {
                        continue;
                    }

                    bool isSys = false;
                    uint pid = 0;
                    string sessionId = "";
                    string instanceId = "";
                    string? sessionDisplayName = null;
                    string? iconPath = null;

                    try { isSys = s.IsSystemSoundsSession; } catch { }
                    try { pid = s.GetProcessID; } catch { }
                    try { sessionId = s.GetSessionIdentifier ?? ""; } catch { }
                    try { instanceId = s.GetSessionInstanceIdentifier ?? ""; } catch { }
                    try { sessionDisplayName = s.DisplayName; } catch { }
                    try { iconPath = s.IconPath; } catch { }

                    if (string.IsNullOrEmpty(instanceId))
                        instanceId = $"{endpoint.DeviceId}|{pid}|{sessionId}|{i}";

                    string appId;
                    string displayName;
                    string? exePath = null;

                    if (isSys || pid == 0)
                    {
                        // Sons do Sistema: controla apenas o endpoint padrão para evitar duplicação
                        if (!endpoint.IsDefault)
                        {
                            try { s.Dispose(); } catch { }
                            continue;
                        }
                        isSys = true;
                        appId = SystemSoundsId;
                        displayName = "Sons do Sistema";
                    }
                    else
                    {
                        // Remove sessões "zumbis" (Inactive) cujo processo já foi encerrado pelo usuário
                        if (state != AudioSessionState.AudioSessionStateActive && !procSnap.ContainsKey(pid))
                        {
                            try { s.Dispose(); } catch { }
                            continue;
                        }

                        var metaKey = (pid, sessionId);
                        if (_sessionMetaCache.TryGetValue(metaKey, out var cachedMeta))
                        {
                            appId = cachedMeta.AppId;
                            displayName = cachedMeta.DisplayName;
                            exePath = cachedMeta.ExePath;
                        }
                        else
                        {
                            (appId, displayName, exePath) = ResolveAppMetadata(pid, sessionId, sessionDisplayName, procSnap);
                            _sessionMetaCache[metaKey] = (appId, displayName, exePath);
                        }
                    }

                    // Ignora processos internos silenciosos do shell (ex: WebView2 do SearchHost)
                    if (!isSys && OpenAppsService.IsIgnoredShellApp(appId) && state != AudioSessionState.AudioSessionStateActive)
                    {
                        try { s.Dispose(); } catch { }
                        continue;
                    }

                    float vol;
                    bool muted;
                    float peak = 0f;
                    bool isActive = state == AudioSessionState.AudioSessionStateActive;
                    try
                    {
                        vol = Math.Clamp(s.SimpleAudioVolume.Volume, 0f, 1f);
                        muted = s.SimpleAudioVolume.Mute;
                        if (!muted) peak = Math.Clamp(s.AudioMeterInformation.MasterPeakValue, 0f, 1f);
                    }
                    catch
                    {
                        try { s.Dispose(); } catch { }
                        continue;
                    }

                    if (!newCache.TryGetValue(appId, out var list))
                    {
                        list = new List<AudioSessionControl>();
                        newCache[appId] = list;
                    }
                    list.Add(s);

                    // Prioridade para escolher qual sessão representa Volume/Mute na UI quando um app tem várias sessões
                    int priority = (isActive ? 4 : 0) + (peak > 0.005f ? 2 : 0) + (endpoint.IsDefault ? 1 : 0);

                    if (!grouped.TryGetValue(appId, out var info))
                    {
                        info = new AppSessionInfo
                        {
                            AppId = appId,
                            DisplayName = displayName,
                            ExePath = exePath,
                            IconPath = iconPath,
                            Volume = vol,
                            Muted = muted,
                            PeakLevel = peak,
                            IsActive = isActive,
                            IsSystemSounds = isSys
                        };
                        info.SessionInstanceIds.Add(instanceId);
                        grouped[appId] = info;
                        groupPriority[appId] = priority;
                    }
                    else
                    {
                        info.SessionInstanceIds.Add(instanceId);
                        info.IsActive |= isActive;
                        if (string.IsNullOrEmpty(info.ExePath) && !string.IsNullOrEmpty(exePath))
                            info.ExePath = exePath;
                        if (string.IsNullOrEmpty(info.IconPath) && !string.IsNullOrEmpty(iconPath))
                            info.IconPath = iconPath;
                        if (peak > info.PeakLevel)
                            info.PeakLevel = peak;

                        if (priority > groupPriority[appId])
                        {
                            groupPriority[appId] = priority;
                            info.Volume = vol;
                            info.Muted = muted;
                        }
                    }
                }
            }
            catch
            {
                _endpointsDirty = true;
            }
        }

        DisposeSessionCache();
        foreach (var kv in newCache) _sessionCache[kv.Key] = kv.Value;
        if (_sessionMetaCache.Count > 256) _sessionMetaCache.Clear();

        return grouped.Values
            .OrderBy(a => !a.IsSystemSounds)
            .ThenBy(a => a.DisplayName, StringComparer.OrdinalIgnoreCase)
            .ToList();
    }

    private static (string AppId, string DisplayName, string? ExePath) ResolveAppMetadata(
        uint pid,
        string sessionId,
        string? sessionDisplayName,
        Dictionary<uint, ProcessSnapEntry> procSnapshot)
    {
        string? exePath = GetProcessExePathSafe(pid);
        string? rawName = null;

        if (!string.IsNullOrEmpty(exePath))
        {
            rawName = Path.GetFileNameWithoutExtension(exePath);
        }

        if (string.IsNullOrWhiteSpace(rawName) && procSnapshot.TryGetValue(pid, out var snapEntry))
        {
            rawName = snapEntry.ExeName;
        }

        if (string.IsNullOrWhiteSpace(rawName))
        {
            try
            {
                using var proc = Process.GetProcessById((int)pid);
                rawName = proc.ProcessName;
                if (string.IsNullOrEmpty(exePath))
                {
                    try { exePath = proc.MainModule?.FileName; } catch { }
                }
            }
            catch
            {
            }
        }

        // Fallback essencial para jogos com anti-cheat (Vanguard/EAC) e apps elevados como Administrador:
        // o identificador WASAPI contém o caminho do executável mesmo quando OpenProcess retorna ACCESS_DENIED.
        if (string.IsNullOrWhiteSpace(rawName) || string.IsNullOrEmpty(exePath))
        {
            var (parsedExe, parsedName) = ParseSessionIdentifier(sessionId);
            if (string.IsNullOrEmpty(exePath) && !string.IsNullOrEmpty(parsedExe))
                exePath = parsedExe;
            if (string.IsNullOrWhiteSpace(rawName) && !string.IsNullOrWhiteSpace(parsedName))
                rawName = parsedName;
        }

        // Atribui processos auxiliares (ex: msedgewebview2 do WhatsApp, steamwebhelper da Steam) ao app pai real
        if (!string.IsNullOrWhiteSpace(rawName))
        {
            var (_, hostRawName, hostExePath) = OpenAppsService.ResolveHostProcess(pid, rawName, exePath, procSnapshot);
            if (!string.IsNullOrWhiteSpace(hostRawName))
            {
                rawName = hostRawName;
                if (!string.IsNullOrEmpty(hostExePath))
                    exePath = hostExePath;
            }
        }

        string? cleanSessionName = !string.IsNullOrWhiteSpace(sessionDisplayName) && !sessionDisplayName.TrimStart().StartsWith("@")
            ? sessionDisplayName.Trim()
            : null;

        if (string.IsNullOrWhiteSpace(rawName))
        {
            if (!string.IsNullOrEmpty(cleanSessionName))
                return (cleanSessionName.ToLowerInvariant(), cleanSessionName, exePath);
            return ($"pid_{pid}", $"Aplicativo ({pid})", exePath);
        }

        var (appId, displayName) = OpenAppsService.NormalizeAppIdentity(rawName);

        // Para apps UWP / hospedados (ex: ApplicationFrameHost / WWAHost), prefira o DisplayName legível da sessão
        if (!string.IsNullOrEmpty(cleanSessionName) &&
            (appId is "applicationframehost" or "wwahost" or "backgroundtaskhost" or "runtimebroker"))
        {
            displayName = cleanSessionName;
        }

        return (appId, displayName, exePath);
    }

    private void DisposeSessionCache()
    {
        foreach (var oldList in _sessionCache.Values)
        {
            foreach (var oldCtrl in oldList)
            {
                try { oldCtrl.Dispose(); } catch { }
            }
        }
        _sessionCache.Clear();
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
        try
        {
            _enumerator.UnregisterEndpointNotificationCallback(_notificationClient);
        }
        catch
        {
        }
        DisposeSessionCache();
        foreach (var ep in _renderEndpoints)
        {
            ep.Dispose();
        }
        _renderEndpoints.Clear();
        _defaultOutput = null;
        foreach (var dev in _micCache.Values)
        {
            try { dev.Dispose(); } catch { }
        }
        _micCache.Clear();
        _enumerator.Dispose();
    }
}
