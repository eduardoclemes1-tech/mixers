using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Windows;
using System.Windows.Input;
using System.Windows.Interop;

namespace Mixers.Services;

public sealed class HotkeyService : IDisposable
{
    public const int OpenHotkeyId = 0x4D49;        // "MI"
    public const int MicMuteHotkeyId = 0x4D4D;     // "MM"
    public const int CycleOutputHotkeyId = 0x4D4F; // "MO"

    private const int WmHotkey = 0x0312;
    private const uint ModAlt = 0x0001;
    private const uint ModControl = 0x0002;
    private const uint ModShift = 0x0004;
    private const uint ModWin = 0x0008;
    private const uint ModNoRepeat = 0x4000;

    [DllImport("user32.dll", SetLastError = true)]
    private static extern bool RegisterHotKey(IntPtr hWnd, int id, uint fsModifiers, uint vk);

    [DllImport("user32.dll", SetLastError = true)]
    private static extern bool UnregisterHotKey(IntPtr hWnd, int id);

    private readonly Dictionary<int, Action> _callbacks = new();
    private readonly Dictionary<int, string> _registeredLabels = new();
    private HwndSource? _source;
    private IntPtr _hwnd;

    public void Attach(Window window)
    {
        var helper = new WindowInteropHelper(window);
        _hwnd = helper.EnsureHandle();
        _source = HwndSource.FromHwnd(_hwnd);
        _source?.AddHook(WndProc);
    }

    public string GetHotkeyLabel(int id)
        => _registeredLabels.TryGetValue(id, out var lbl) ? lbl : "";

    public (bool Ok, string Message) Register(int id, string hotkeyStr, Action callback)
    {
        Unregister(id);
        _callbacks[id] = callback;

        string clean = (hotkeyStr ?? "").Trim();
        if (string.IsNullOrEmpty(clean))
        {
            return (true, "Atalho desativado.");
        }

        if (!TryParseHotkey(clean, out uint mods, out uint vk, out string normalized))
            return (false, "Atalho inválido.");

        if (_hwnd == IntPtr.Zero)
            return (false, "Janela ainda não inicializada.");

        if (!RegisterHotKey(_hwnd, id, mods | ModNoRepeat, vk))
            return (false, "Tecla já em uso por outro app.");

        _registeredLabels[id] = normalized;
        return (true, $"Atalho ativo: {normalized}");
    }

    public void Unregister(int id)
    {
        if (_registeredLabels.ContainsKey(id) && _hwnd != IntPtr.Zero)
        {
            UnregisterHotKey(_hwnd, id);
        }
        _registeredLabels.Remove(id);
    }

    public void UnregisterAll()
    {
        foreach (int id in new List<int>(_registeredLabels.Keys))
        {
            if (_hwnd != IntPtr.Zero) UnregisterHotKey(_hwnd, id);
        }
        _registeredLabels.Clear();
    }

    private IntPtr WndProc(IntPtr hwnd, int msg, IntPtr wParam, IntPtr lParam, ref bool handled)
    {
        if (msg == WmHotkey)
        {
            int id = wParam.ToInt32();
            if (_callbacks.TryGetValue(id, out var cb))
            {
                cb();
                handled = true;
            }
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
                    if (raw.StartsWith("VK_0x", StringComparison.OrdinalIgnoreCase) &&
                        uint.TryParse(raw[5..], System.Globalization.NumberStyles.HexNumber, null, out uint rawVk) &&
                        rawVk > 0)
                    {
                        vk = rawVk;
                        keyLabel = $"VK_0x{rawVk:X2}";
                    }
                    else if (Enum.TryParse<Key>(raw, true, out Key key) && key != Key.None)
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

        modLabels.Add(keyLabel);
        normalized = string.Join("+", modLabels);
        return true;
    }

    public void Dispose()
    {
        UnregisterAll();
        _source?.RemoveHook(WndProc);
    }
}
