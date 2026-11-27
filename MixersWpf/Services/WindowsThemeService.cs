using System;
using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Windows;
using System.Windows.Interop;
using System.Windows.Media;
using Microsoft.Win32;

namespace Mixers.Services;

public class FluentThemePalette
{
    public Color Accent { get; init; }
    public Color AccentHover { get; init; }
    public Color HeaderBand { get; init; }
    public Color ListBand { get; init; }
    public Color PanelBorder { get; init; }
    public Color TrackUnfilled { get; init; }
    public Color TrackMuted { get; init; }
    public Color ThumbMuted { get; init; }
}

public static class WindowsThemeService
{
    private const string RunKeyPath = @"Software\Microsoft\Windows\CurrentVersion\Run";
    private const string DwmKeyPath = @"Software\Microsoft\Windows\DWM";
    private const string AppRegName = "MixersAudioApp";

    [StructLayout(LayoutKind.Sequential)]
    private struct AccentPolicy
    {
        public int AccentState;
        public int AccentFlags;
        public uint GradientColor;
        public int AnimationId;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct WindowCompositionAttributeData
    {
        public int Attribute;
        public IntPtr Data;
        public int SizeOfData;
    }

    [DllImport("user32.dll")]
    private static extern int SetWindowCompositionAttribute(IntPtr hwnd, ref WindowCompositionAttributeData data);

    [DllImport("dwmapi.dll")]
    private static extern int DwmSetWindowAttribute(IntPtr hwnd, int attr, ref int attrValue, int attrSize);

    [DllImport("user32.dll")]
    private static extern IntPtr GetForegroundWindow();

    [DllImport("user32.dll")]
    private static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint lpdwProcessId);

    public static Color GetWindowsAccentColor()
    {
        try
        {
            using var key = Registry.CurrentUser.OpenSubKey(DwmKeyPath);
            if (key != null)
            {
                object? valObj = key.GetValue("AccentColor");
                if (valObj is int intVal)
                {
                    uint u = unchecked((uint)intVal);
                    byte r = (byte)(u & 0xFF);
                    byte g = (byte)((u >> 8) & 0xFF);
                    byte b = (byte)((u >> 16) & 0xFF);
                    return Color.FromRgb(r, g, b);
                }
            }
        }
        catch
        {
        }
        return Color.FromRgb(139, 92, 246); // Violeta Fluent padrão
    }

    private static Color Mix(Color a, Color b, double ratio)
    {
        byte r = (byte)Math.Clamp(Math.Round(a.R * (1 - ratio) + b.R * ratio), 0, 255);
        byte g = (byte)Math.Clamp(Math.Round(a.G * (1 - ratio) + b.G * ratio), 0, 255);
        byte bl = (byte)Math.Clamp(Math.Round(a.B * (1 - ratio) + b.B * ratio), 0, 255);
        return Color.FromRgb(r, g, bl);
    }

    public static FluentThemePalette BuildPalette(Color systemAccent)
    {
        double lum = 0.299 * systemAccent.R + 0.587 * systemAccent.G + 0.114 * systemAccent.B;
        Color accent = lum < 95 ? Mix(systemAccent, Colors.White, 0.28) : systemAccent;
        Color accentHover = Mix(accent, Colors.White, 0.22);

        // Cores com transparência real para combinar com o vidro Acrylic do Windows 11!
        Color headerBase = Mix(Color.FromRgb(22, 20, 32), accent, 0.30);
        Color listBase = Mix(Color.FromRgb(16, 15, 22), accent, 0.08);
        Color borderBase = Mix(Color.FromRgb(75, 72, 94), accent, 0.32);

        return new FluentThemePalette
        {
            Accent = accent,
            AccentHover = accentHover,
            HeaderBand = Color.FromArgb(206, headerBase.R, headerBase.G, headerBase.B),
            ListBand = Color.FromArgb(218, listBase.R, listBase.G, listBase.B),
            PanelBorder = Color.FromArgb(165, borderBase.R, borderBase.G, borderBase.B),
            TrackUnfilled = Color.FromArgb(135, 165, 160, 190),
            TrackMuted = Color.FromArgb(90, 130, 126, 150),
            ThumbMuted = Color.FromRgb(115, 110, 138),
        };
    }

    public static void EnableAcrylicBlur(Window window)
    {
        try
        {
            var helper = new WindowInteropHelper(window);
            IntPtr hwnd = helper.Handle;
            if (hwnd == IntPtr.Zero) return;

            int dark = 1;
            DwmSetWindowAttribute(hwnd, 20, ref dark, sizeof(int));

            int squareCorners = 1; // DWMWCP_DONOTROUND (cantos retos/quadrados)
            DwmSetWindowAttribute(hwnd, 33, ref squareCorners, sizeof(int));

            // ACCENT_ENABLE_ACRYLICBLURBEHIND = 4 (vidro fosco real do Windows 10/11!)
            var accent = new AccentPolicy
            {
                AccentState = 4,
                AccentFlags = 2,
                GradientColor = 0x01101018 // tint mínimo (o próprio XAML controla o tom 2-faixas)
            };
            int size = Marshal.SizeOf(accent);
            IntPtr ptr = Marshal.AllocHGlobal(size);
            try
            {
                Marshal.StructureToPtr(accent, ptr, false);
                var data = new WindowCompositionAttributeData
                {
                    Attribute = 19, // WCA_ACCENT_POLICY
                    SizeOfData = size,
                    Data = ptr
                };
                SetWindowCompositionAttribute(hwnd, ref data);
            }
            finally
            {
                Marshal.FreeHGlobal(ptr);
            }
        }
        catch
        {
        }
    }

    public static bool IsOurProcessForeground()
    {
        try
        {
            IntPtr fg = GetForegroundWindow();
            if (fg == IntPtr.Zero) return false;
            GetWindowThreadProcessId(fg, out uint pid);
            return pid == (uint)Environment.ProcessId;
        }
        catch
        {
            return true;
        }
    }

    public static bool IsAutostartEnabled()
    {
        try
        {
            using var key = Registry.CurrentUser.OpenSubKey(RunKeyPath, false);
            return key?.GetValue(AppRegName) != null;
        }
        catch
        {
            return false;
        }
    }

    public static bool SetAutostart(bool enabled)
    {
        try
        {
            using var key = Registry.CurrentUser.OpenSubKey(RunKeyPath, true);
            if (key == null) return false;
            if (enabled)
            {
                string exePath = Process.GetCurrentProcess().MainModule?.FileName ?? Environment.ProcessPath ?? "";
                if (string.IsNullOrEmpty(exePath)) return false;
                key.SetValue(AppRegName, $"\"{exePath}\" --minimized");
            }
            else
            {
                key.DeleteValue(AppRegName, false);
            }
            return true;
        }
        catch
        {
            return false;
        }
    }
}
