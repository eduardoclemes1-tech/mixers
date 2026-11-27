using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Windows;
using System.Windows.Input;
using System.Windows.Interop;

namespace Mixers.Services;

public sealed class HotkeyService : IDisposable
{
    private const int WmHotkey = 0x0312;
    private const int HotkeyId = 0x4D49; // "MI"
    private const uint ModAlt = 0x0001;
    private const uint ModControl = 0x0002;
    private const uint ModShift = 0x0004;
    private const uint ModWin = 0x0008;
    private const uint ModNoRepeat = 0x4000;

    [DllImport("user32.dll", SetLastError = true)]
    private static extern bool RegisterHotKey(IntPtr hWnd, int id, uint fsModifiers, uint vk);

    [DllImport("user32.dll", SetLastError = true)]
    private static extern bool UnregisterHotKey(IntPtr hWnd, int id);

    private readonly Action _onTriggered;
    private HwndSource? _source;
    private IntPtr _hwnd;
    private bool _registered;

    public string CurrentHotkey { get; private set; } = "";

    public HotkeyService(Action onTriggered)
    {
        _onTriggered = onTriggered;
    }

    public void Attach(Window window)
    {
        var helper = new WindowInteropHelper(window);
        _hwnd = helper.EnsureHandle();
        _source = HwndSource.FromHwnd(_hwnd);
        _source?.AddHook(WndProc);
    }

    public (bool Ok, string Message) Register(string hotkeyStr)
    {
        Unregister();

        string clean = (hotkeyStr ?? "").Trim();
        if (string.IsNullOrEmpty(clean))
        {
            CurrentHotkey = "";
            return (true, "Atalho desativado.");
        }

        if (!TryParseHotkey(clean, out uint mods, out uint vk, out string normalized))
            return (false, "Atalho inválido (use ex: Ctrl+Alt+M).");

        if (_hwnd == IntPtr.Zero)
            return (false, "Janela ainda não inicializada.");

        if (!RegisterHotKey(_hwnd, HotkeyId, mods | ModNoRepeat, vk))
            return (false, "Atalho já em uso por outro app.");

        _registered = true;
        CurrentHotkey = normalized;
        return (true, $"Atalho ativo: {normalized}");
    }

    public void Unregister()
    {
        if (_registered && _hwnd != IntPtr.Zero)
        {
            UnregisterHotKey(_hwnd, HotkeyId);
            _registered = false;
        }
        CurrentHotkey = "";
    }

    private IntPtr WndProc(IntPtr hwnd, int msg, IntPtr wParam, IntPtr lParam, ref bool handled)
    {
        if (msg == WmHotkey && wParam.ToInt32() == HotkeyId)
        {
            _onTriggered();
            handled = true;
        }
        return IntPtr.Zero;
    }

    public static bool TryParseHotkey(string input, out uint mods, out uint vk, out string normalized)
    {
        mods = 0;
        vk = 0;
        normalized = "";

        var parts = input.Split('+', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries);
        if (parts.Length == 0) return false;

        var modLabels = new List<string>();
        string keyLabel = "";

        foreach (string raw in parts)
        {
            string p = raw.ToLowerInvariant();
            switch (p)
            {
                case "ctrl":
                case "control":
                    mods |= ModControl;
                    if (!modLabels.Contains("Ctrl")) modLabels.Add("Ctrl");
                    break;
                case "alt":
                    mods |= ModAlt;
                    if (!modLabels.Contains("Alt")) modLabels.Add("Alt");
                    break;
                case "shift":
                    mods |= ModShift;
                    if (!modLabels.Contains("Shift")) modLabels.Add("Shift");
                    break;
                case "win":
                case "super":
                    mods |= ModWin;
                    if (!modLabels.Contains("Win")) modLabels.Add("Win");
                    break;
                default:
                    if (Enum.TryParse<Key>(raw, true, out Key key) && key != Key.None)
                    {
                        vk = (uint)KeyInterop.VirtualKeyFromKey(key);
                        keyLabel = raw.Length == 1 ? raw.ToUpperInvariant() : key.ToString();
                    }
                    else if (raw.Length == 1 && char.IsLetterOrDigit(raw[0]))
                    {
                        vk = char.ToUpperInvariant(raw[0]);
                        keyLabel = raw.ToUpperInvariant();
                    }
                    else
                    {
                        return false;
                    }
                    break;
            }
        }

        if (vk == 0) return false;
        bool isFunctionKey = vk >= 0x70 && vk <= 0x87;
        if (mods == 0 && !isFunctionKey) return false;

        modLabels.Add(keyLabel);
        normalized = string.Join("+", modLabels);
        return true;
    }

    public void Dispose()
    {
        Unregister();
        _source?.RemoveHook(WndProc);
    }
}
