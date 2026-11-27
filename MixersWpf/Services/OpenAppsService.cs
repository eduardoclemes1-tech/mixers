using System;
using System.Collections.Generic;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;

namespace Mixers.Services;

public sealed class OpenAppInfo
{
    public string AppId { get; init; } = "";
    public string DisplayName { get; init; } = "";
    public string? ExePath { get; set; }
}

public readonly record struct ProcessSnapEntry(uint Pid, uint ParentPid, string ExeName);

/// <summary>
/// Descobre exclusivamente aplicativos com janela realmente aberta na área de trabalho /
/// barra de tarefas (sincronizado com o Alt+Tab/Taskbar do Windows, incluindo UWP),
/// evitando processos fechados em segundo plano/daemons, e resolve processo-pai para
/// sessões hospedadas (ex: msedgewebview2 -> WhatsApp, steamwebhelper -> Steam).
/// </summary>
public static class OpenAppsService
{
    private const uint Th32csSnapProcess = 0x00000002;
    private const uint ProcessQueryLimitedInformation = 0x1000;
    private const uint GwOwner = 4;
    private const int GwlExStyle = -20;
    private const int WsExToolWindow = 0x00000080;
    private const int WsExAppWindow = 0x00040000;
    private const int DwmwaCloaked = 14;

    private delegate bool EnumWindowsProc(IntPtr hWnd, IntPtr lParam);

    [StructLayout(LayoutKind.Sequential)]
    private struct Rect
    {
        public int Left;
        public int Top;
        public int Right;
        public int Bottom;
    }

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    private struct ProcessEntry32
    {
        public uint dwSize;
        public uint cntUsage;
        public uint th32ProcessID;
        public IntPtr th32DefaultHeapID;
        public uint th32ModuleID;
        public uint cntThreads;
        public uint th32ParentProcessID;
        public int pcPriClassBase;
        public uint dwFlags;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 260)]
        public string szExeFile;
    }

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern IntPtr CreateToolhelp32Snapshot(uint dwFlags, uint th32ProcessID);

    [DllImport("kernel32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
    private static extern bool Process32First(IntPtr hSnapshot, ref ProcessEntry32 lppe);

    [DllImport("kernel32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
    private static extern bool Process32Next(IntPtr hSnapshot, ref ProcessEntry32 lppe);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern IntPtr OpenProcess(uint dwDesiredAccess, bool bInheritHandle, uint dwProcessId);

    [DllImport("kernel32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
    private static extern bool QueryFullProcessImageName(IntPtr hProcess, uint dwFlags, StringBuilder lpExeName, ref uint lpdwSize);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool CloseHandle(IntPtr hObject);

    [DllImport("user32.dll")]
    private static extern bool EnumWindows(EnumWindowsProc lpEnumFunc, IntPtr lParam);

    [DllImport("user32.dll")]
    private static extern bool EnumChildWindows(IntPtr hWndParent, EnumWindowsProc lpEnumFunc, IntPtr lParam);

    [DllImport("user32.dll")]
    private static extern bool IsWindowVisible(IntPtr hWnd);

    [DllImport("user32.dll")]
    private static extern bool IsIconic(IntPtr hWnd);

    [DllImport("user32.dll")]
    private static extern bool GetWindowRect(IntPtr hWnd, out Rect lpRect);

    [DllImport("user32.dll")]
    private static extern int GetWindowTextLength(IntPtr hWnd);

    [DllImport("user32.dll")]
    private static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint lpdwProcessId);

    [DllImport("user32.dll")]
    private static extern IntPtr GetWindow(IntPtr hWnd, uint uCmd);

    [DllImport("user32.dll")]
    private static extern int GetWindowLong(IntPtr hWnd, int nIndex);

    [DllImport("dwmapi.dll")]
    private static extern int DwmGetWindowAttribute(IntPtr hwnd, int dwAttribute, out int pvAttribute, int cbAttribute);

    // Processos auxiliares cujo áudio pertence ao app pai (ex: WebView2 do WhatsApp, Steam WebHelper)
    private static readonly HashSet<string> HostedAudioHelpers = new(StringComparer.OrdinalIgnoreCase)
    {
        "msedgewebview2",
        "steamwebhelper",
        "cefsharp.browsersubprocess",
        "qtwebengineprocess",
        "webviewhost",
        "wwahost"
    };

    // Processos de infraestrutura do Windows que não são o app dono de um WebView2
    private static readonly HashSet<string> SystemHostAncestors = new(StringComparer.OrdinalIgnoreCase)
    {
        "svchost",
        "sihost",
        "explorer",
        "services",
        "wininit",
        "winlogon",
        "csrss",
        "smss",
        "system",
        "runtimebroker",
        "dllhost",
        "conhost",
        "taskhostw",
        "backgroundtaskhost"
    };

    // Processos internos do shell do Windows (ignorados tanto em sessões silenciosas quanto em janelas)
    private static readonly HashSet<string> IgnoredShellApps = new(StringComparer.OrdinalIgnoreCase)
    {
        "mixers",
        "explorer",
        "shellexperiencehost",
        "startmenuexperiencehost",
        "searchhost",
        "searchapp",
        "textinputhost",
        "lockapp",
        "applicationframehost",
        "screenclippinghost",
        "systemsettings",
        "taskmgr",
        "nvidia overlay",
        "nvcontainer",
        "widgets",
        "widgetboard",
        "crossdeviceresume",
        "phoneexperiencehost",
        "securityhealthsystray",
        "msedgewebview2"
    };

    // Utilitários sem áudio (ignorados na descoberta de janelas silenciosas, mas exibidos se tocarem som via WASAPI)
    private static readonly HashSet<string> NonAudioUtilityWindows = new(StringComparer.OrdinalIgnoreCase)
    {
        "snippingtool",
        "screensketch",
        "riotclientservices",
        "riotclientcrashhandler",
        "calculatorapp",
        "calculator",
        "notepad",
        "mspaint",
        "regedit",
        "mmc",
        "cmd",
        "conhost",
        "powershell",
        "pwsh",
        "windowsterminal",
        "openconsole",
        "perfmon",
        "resmon",
        "control"
    };

    private static readonly Dictionary<string, (string AppId, string DisplayName)> FriendlyAppAliases = new(StringComparer.OrdinalIgnoreCase)
    {
        ["whatsapp.root"] = ("whatsapp", "WhatsApp"),
        ["whatsapp"] = ("whatsapp", "WhatsApp"),
        ["discord"] = ("discord", "Discord"),
        ["discordptb"] = ("discordptb", "Discord PTB"),
        ["discordcanary"] = ("discordcanary", "Discord Canary"),
        ["ms-teams"] = ("ms-teams", "Microsoft Teams"),
        ["msedge"] = ("msedge", "Microsoft Edge"),
        ["chrome"] = ("chrome", "Google Chrome"),
        ["firefox"] = ("firefox", "Firefox"),
        ["spotify"] = ("spotify", "Spotify"),
        ["steam"] = ("steam", "Steam"),
        ["obs64"] = ("obs64", "OBS Studio"),
        ["obs32"] = ("obs32", "OBS Studio"),
        ["vlc"] = ("vlc", "VLC"),
        ["applemusic"] = ("applemusic", "Apple Music"),
        ["telegram"] = ("telegram", "Telegram"),
        ["leagueclientux"] = ("leagueclient", "League of Legends"),
        ["leagueclient"] = ("leagueclient", "League of Legends"),
        ["league of legends"] = ("league of legends", "League of Legends"),
        ["epicgameslauncher"] = ("epicgameslauncher", "Epic Games"),
        ["riotclientux"] = ("riotclient", "Riot Client"),
        ["riotclientservices"] = ("riotclientservices", "Riot Client"),
        ["xboxpcapp"] = ("xboxpcapp", "Xbox"),
        ["eadesktop"] = ("eadesktop", "EA App")
    };

    public static Dictionary<uint, ProcessSnapEntry> CaptureProcessSnapshot()
    {
        var map = new Dictionary<uint, ProcessSnapEntry>();
        IntPtr snap = CreateToolhelp32Snapshot(Th32csSnapProcess, 0);
        if (snap == IntPtr.Zero || snap == new IntPtr(-1)) return map;

        try
        {
            var entry = new ProcessEntry32 { dwSize = (uint)Marshal.SizeOf<ProcessEntry32>() };
            if (Process32First(snap, ref entry))
            {
                do
                {
                    string exeName = Path.GetFileNameWithoutExtension(entry.szExeFile ?? "");
                    map[entry.th32ProcessID] = new ProcessSnapEntry(
                        entry.th32ProcessID,
                        entry.th32ParentProcessID,
                        exeName);
                }
                while (Process32Next(snap, ref entry));
            }
        }
        catch
        {
        }
        finally
        {
            CloseHandle(snap);
        }

        return map;
    }

    public static string? GetProcessExePathSafe(uint pid)
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

    /// <summary>
    /// Se o processo for um helper hospedado (ex: msedgewebview2 do WhatsApp ou steamwebhelper da Steam),
    /// sobe na árvore de processos até encontrar o aplicativo real dono dele.
    /// </summary>
    public static (uint HostPid, string RawName, string? ExePath) ResolveHostProcess(
        uint pid,
        string? rawName,
        string? exePath,
        Dictionary<uint, ProcessSnapEntry> procSnapshot)
    {
        string currentName = rawName ?? "";
        if (string.IsNullOrWhiteSpace(currentName) && procSnapshot.TryGetValue(pid, out var selfSnap))
        {
            currentName = selfSnap.ExeName;
        }

        if (!HostedAudioHelpers.Contains(currentName))
        {
            return (pid, currentName, exePath);
        }

        uint curPid = pid;
        for (int depth = 0; depth < 8; depth++)
        {
            if (!procSnapshot.TryGetValue(curPid, out var snap)) break;
            uint parentPid = snap.ParentPid;
            if (parentPid == 0 || parentPid == curPid) break;
            if (!procSnapshot.TryGetValue(parentPid, out var parentSnap)) break;

            string pName = parentSnap.ExeName;
            if (string.IsNullOrWhiteSpace(pName) || SystemHostAncestors.Contains(pName))
                break;

            if (!HostedAudioHelpers.Contains(pName))
            {
                string? parentExe = GetProcessExePathSafe(parentPid);
                return (parentPid, pName, parentExe ?? exePath);
            }

            curPid = parentPid;
        }

        return (pid, currentName, exePath);
    }

    public static (string AppId, string DisplayName) NormalizeAppIdentity(string rawName)
    {
        string cleaned = rawName.Trim();
        if (cleaned.EndsWith(".exe", StringComparison.OrdinalIgnoreCase))
            cleaned = cleaned[..^4];

        if (FriendlyAppAliases.TryGetValue(cleaned, out var alias))
            return alias;

        if (cleaned.EndsWith(".root", StringComparison.OrdinalIgnoreCase) && cleaned.Length > 5)
            cleaned = cleaned[..^5];

        if (FriendlyAppAliases.TryGetValue(cleaned, out alias))
            return alias;

        if (string.IsNullOrEmpty(cleaned))
            return ("app", "Aplicativo");

        string appId = cleaned.ToLowerInvariant();
        string display = char.ToUpperInvariant(cleaned[0]) + cleaned[1..];
        return (appId, display);
    }

    public static bool IsIgnoredShellApp(string appId) => IgnoredShellApps.Contains(appId);

    /// <summary>
    /// Lista estritamente os aplicativos com janela aberta na área de trabalho / barra de tarefas
    /// (incluindo minimizados na barra de tarefas e apps UWP ativos, excluindo janelas ocultas/cloaked e daemons fechados).
    /// </summary>
    public static List<OpenAppInfo> ListOpenApps(Dictionary<uint, ProcessSnapEntry>? existingSnapshot = null)
    {
        var procSnap = existingSnapshot ?? CaptureProcessSnapshot();
        var result = new Dictionary<string, OpenAppInfo>(StringComparer.OrdinalIgnoreCase);
        uint ownPid = (uint)Environment.ProcessId;

        void TryAddPid(uint pid)
        {
            if (pid == 0 || pid == ownPid) return;
            if (!procSnap.TryGetValue(pid, out var snap)) return;
            if (string.IsNullOrWhiteSpace(snap.ExeName)) return;

            var (hostPid, hostRawName, hostExePath) = ResolveHostProcess(pid, snap.ExeName, null, procSnap);
            if (hostPid == ownPid || string.IsNullOrWhiteSpace(hostRawName)) return;

            var (appId, displayName) = NormalizeAppIdentity(hostRawName);
            if (IgnoredShellApps.Contains(appId) || IgnoredShellApps.Contains(hostRawName)) return;
            if (NonAudioUtilityWindows.Contains(appId) || NonAudioUtilityWindows.Contains(hostRawName)) return;

            if (!result.TryGetValue(appId, out var existing))
            {
                string? exePath = hostExePath ?? GetProcessExePathSafe(hostPid);
                result[appId] = new OpenAppInfo
                {
                    AppId = appId,
                    DisplayName = displayName,
                    ExePath = exePath
                };
            }
            else if (string.IsNullOrEmpty(existing.ExePath))
            {
                existing.ExePath = hostExePath ?? GetProcessExePathSafe(hostPid);
            }
        }

        try
        {
            EnumWindows((hWnd, _) =>
            {
                if (!IsWindowVisible(hWnd)) return true;

                int exStyle = GetWindowLong(hWnd, GwlExStyle);
                if ((exStyle & WsExToolWindow) != 0) return true;

                IntPtr owner = GetWindow(hWnd, GwOwner);
                if (owner != IntPtr.Zero && (exStyle & WsExAppWindow) == 0) return true;

                if (GetWindowTextLength(hWnd) <= 0) return true;

                // Janelas UWP fechadas ficam "cloaked" (DWMWA_CLOAKED != 0)
                if (DwmGetWindowAttribute(hWnd, DwmwaCloaked, out int cloaked, sizeof(int)) == 0 && cloaked != 0)
                    return true;

                // Ignora janelas auxiliares de tamanho 0x0 (exceto se estiverem minimizadas na barra de tarefas)
                if (!IsIconic(hWnd) && GetWindowRect(hWnd, out var rect))
                {
                    if ((rect.Right - rect.Left) <= 0 || (rect.Bottom - rect.Top) <= 0)
                        return true;
                }

                GetWindowThreadProcessId(hWnd, out uint pid);
                if (pid == 0 || pid == ownPid) return true;

                // Para apps UWP hospedados em ApplicationFrameHost, extrai o PID real da janela filha
                if (procSnap.TryGetValue(pid, out var snap) &&
                    snap.ExeName.Equals("ApplicationFrameHost", StringComparison.OrdinalIgnoreCase))
                {
                    uint uwpPid = 0;
                    EnumChildWindows(hWnd, (child, _) =>
                    {
                        GetWindowThreadProcessId(child, out uint cpid);
                        if (cpid != 0 && cpid != pid)
                        {
                            uwpPid = cpid;
                            return false;
                        }
                        return true;
                    }, IntPtr.Zero);
                    if (uwpPid == 0) return true; // Frame vazio sem app UWP real dentro
                    pid = uwpPid;
                }

                TryAddPid(pid);
                return true;
            }, IntPtr.Zero);
        }
        catch
        {
        }

        return new List<OpenAppInfo>(result.Values);
    }
}

/// <summary>
/// Monitor leve de eventos WinEvent (abertura, fechamento, ocultação e cloak/uncloak de janelas UWP)
/// para sincronizar a lista de aplicativos em tempo real com o sistema.
/// </summary>
public sealed class WindowEventWatcher : IDisposable
{
    private const uint EventSystemForeground = 0x0003;
    private const uint EventObjectDestroy = 0x8001;
    private const uint EventObjectShow = 0x8002;
    private const uint EventObjectHide = 0x8003;
    private const uint EventObjectCloaked = 0x8017;
    private const uint EventObjectUncloaked = 0x8018;
    private const uint WinEventOutOfContext = 0x0000;
    private const uint WinEventSkipOwnProcess = 0x0002;
    private const int ObjidWindow = 0;

    private delegate void WinEventDelegate(
        IntPtr hWinEventHook,
        uint eventType,
        IntPtr hwnd,
        int idObject,
        int idChild,
        uint dwEventThread,
        uint dwmsEventTime);

    [DllImport("user32.dll")]
    private static extern IntPtr SetWinEventHook(
        uint eventMin,
        uint eventMax,
        IntPtr hmodWinEventProc,
        WinEventDelegate lpfnWinEventProc,
        uint idProcess,
        uint idThread,
        uint dwFlags);

    [DllImport("user32.dll")]
    private static extern bool UnhookWinEvent(IntPtr hWinEventHook);

    private readonly Action _onAppsChanged;
    private readonly WinEventDelegate _proc;
    private IntPtr _hookForeground;
    private IntPtr _hookObjectLifecycle;
    private IntPtr _hookCloak;

    public WindowEventWatcher(Action onAppsChanged)
    {
        _onAppsChanged = onAppsChanged;
        _proc = HandleWinEvent;
        try
        {
            _hookForeground = SetWinEventHook(
                EventSystemForeground,
                EventSystemForeground,
                IntPtr.Zero,
                _proc,
                0,
                0,
                WinEventOutOfContext | WinEventSkipOwnProcess);

            _hookObjectLifecycle = SetWinEventHook(
                EventObjectDestroy,
                EventObjectHide,
                IntPtr.Zero,
                _proc,
                0,
                0,
                WinEventOutOfContext | WinEventSkipOwnProcess);

            _hookCloak = SetWinEventHook(
                EventObjectCloaked,
                EventObjectUncloaked,
                IntPtr.Zero,
                _proc,
                0,
                0,
                WinEventOutOfContext | WinEventSkipOwnProcess);
        }
        catch
        {
        }
    }

    private void HandleWinEvent(
        IntPtr hWinEventHook,
        uint eventType,
        IntPtr hwnd,
        int idObject,
        int idChild,
        uint dwEventThread,
        uint dwmsEventTime)
    {
        if (hwnd == IntPtr.Zero) return;
        if (eventType != EventSystemForeground && (idObject != ObjidWindow || idChild != 0)) return;
        _onAppsChanged();
    }

    public void Dispose()
    {
        if (_hookForeground != IntPtr.Zero)
        {
            try { UnhookWinEvent(_hookForeground); } catch { }
            _hookForeground = IntPtr.Zero;
        }
        if (_hookObjectLifecycle != IntPtr.Zero)
        {
            try { UnhookWinEvent(_hookObjectLifecycle); } catch { }
            _hookObjectLifecycle = IntPtr.Zero;
        }
        if (_hookCloak != IntPtr.Zero)
        {
            try { UnhookWinEvent(_hookCloak); } catch { }
            _hookCloak = IntPtr.Zero;
        }
    }
}
