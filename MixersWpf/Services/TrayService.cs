using System;
using System.Collections.Generic;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Runtime.InteropServices;
using System.Windows;
using System.Windows.Interop;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using Forms = System.Windows.Forms;

namespace Mixers.Services;

public sealed class TrayService : IDisposable
{
    private const int WhMouseLl = 14;
    private const int WmMouseWheel = 0x020A;

    private delegate IntPtr LowLevelMouseProc(int nCode, IntPtr wParam, IntPtr lParam);

    [StructLayout(LayoutKind.Sequential)]
    private struct PointStruct
    {
        public int X;
        public int Y;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct MsLlHookStruct
    {
        public PointStruct Pt;
        public uint MouseData;
        public uint Flags;
        public uint Time;
        public IntPtr DwExtraInfo;
    }

    [DllImport("user32.dll", SetLastError = true)]
    private static extern IntPtr SetWindowsHookEx(int idHook, LowLevelMouseProc lpfn, IntPtr hMod, uint dwThreadId);

    [DllImport("user32.dll", SetLastError = true)]
    private static extern bool UnhookWindowsHookEx(IntPtr hhk);

    [DllImport("user32.dll")]
    private static extern IntPtr CallNextHookEx(IntPtr hhk, int nCode, IntPtr wParam, IntPtr lParam);

    private readonly Forms.NotifyIcon _notifyIcon;
    private readonly Forms.ToolStripMenuItem _autostartItem;
    private readonly Func<bool> _isAutostart;
    private readonly Action<int>? _onTrayWheelDelta;
    private readonly Dictionary<int, Icon> _iconCache = new();
    private int _currentStateKey = -1;

    private DateTime _lastHoverUtc = DateTime.MinValue;
    private System.Drawing.Point _lastHoverPt;
    private readonly LowLevelMouseProc _mouseProc;
    private IntPtr _mouseHook = IntPtr.Zero;

    public TrayService(
        Action onToggle,
        Action onToggleMicMute,
        Action onCycleOutput,
        Action onToggleAutostart,
        Func<bool> isAutostart,
        Action onCheckUpdates,
        Action onQuit,
        Action<int>? onTrayWheelDelta = null)
    {
        _isAutostart = isAutostart;
        _onTrayWheelDelta = onTrayWheelDelta;

        var menu = new Forms.ContextMenuStrip();
        menu.Items.Add("Abrir / Ocultar Mixers", null, (_, _) => onToggle());
        menu.Items.Add("Mutar / Desmutar Microfone", null, (_, _) => onToggleMicMute());
        menu.Items.Add("Alternar saída de áudio", null, (_, _) => onCycleOutput());
        menu.Items.Add(new Forms.ToolStripSeparator());

        _autostartItem = new Forms.ToolStripMenuItem("Iniciar com o Windows")
        {
            Checked = isAutostart()
        };
        _autostartItem.Click += (_, _) =>
        {
            onToggleAutostart();
            _autostartItem.Checked = _isAutostart();
        };
        menu.Items.Add(_autostartItem);
        menu.Items.Add("Verificar atualizações", null, (_, _) => onCheckUpdates());
        menu.Items.Add(new Forms.ToolStripSeparator());
        menu.Items.Add("Sair", null, (_, _) => onQuit());

        menu.Opening += (_, _) => _autostartItem.Checked = _isAutostart();

        _notifyIcon = new Forms.NotifyIcon
        {
            Icon = GetOrCreateIcon(false, false),
            Text = "Mixers — Controle de Som",
            ContextMenuStrip = menu,
            Visible = true
        };
        _currentStateKey = 0;

        _notifyIcon.MouseClick += (_, e) =>
        {
            if (e.Button == Forms.MouseButtons.Left)
            {
                onToggle();
            }
        };

        _notifyIcon.MouseMove += (_, _) =>
        {
            _lastHoverUtc = DateTime.UtcNow;
            _lastHoverPt = Forms.Cursor.Position;
        };

        _mouseProc = MouseHookCallback;
        if (_onTrayWheelDelta != null)
        {
            try
            {
                _mouseHook = SetWindowsHookEx(WhMouseLl, _mouseProc, IntPtr.Zero, 0);
            }
            catch
            {
                _mouseHook = IntPtr.Zero;
            }
        }
    }

    private IntPtr MouseHookCallback(int nCode, IntPtr wParam, IntPtr lParam)
    {
        if (nCode >= 0 && wParam.ToInt32() == WmMouseWheel && _onTrayWheelDelta != null)
        {
            if ((DateTime.UtcNow - _lastHoverUtc).TotalMilliseconds < 1300)
            {
                var info = Marshal.PtrToStructure<MsLlHookStruct>(lParam);
                int dx = Math.Abs(info.Pt.X - _lastHoverPt.X);
                int dy = Math.Abs(info.Pt.Y - _lastHoverPt.Y);
                if (dx <= 26 && dy <= 26)
                {
                    short wheelDelta = (short)((info.MouseData >> 16) & 0xFFFF);
                    int step = wheelDelta > 0 ? 4 : -4;
                    _lastHoverUtc = DateTime.UtcNow;
                    _onTrayWheelDelta(step);
                }
            }
        }
        return CallNextHookEx(_mouseHook, nCode, wParam, lParam);
    }

    public void UpdateIconState(bool masterMuted, bool micMuted)
    {
        int key = (masterMuted ? 1 : 0) | (micMuted ? 2 : 0);
        if (key == _currentStateKey) return;
        _currentStateKey = key;

        _notifyIcon.Icon = GetOrCreateIcon(masterMuted, micMuted);

        if (masterMuted && micMuted) _notifyIcon.Text = "Mixers — Som e Mic mutados";
        else if (masterMuted) _notifyIcon.Text = "Mixers — Som geral mutado";
        else if (micMuted) _notifyIcon.Text = "Mixers — Microfone mutado";
        else _notifyIcon.Text = "Mixers — Controle de Som";
    }

    public static ImageSource CreateWindowIconSource()
    {
        using var bmp = RenderIconBitmap(false, false, 64);
        IntPtr hIcon = bmp.GetHicon();
        try
        {
            var src = Imaging.CreateBitmapSourceFromHIcon(
                hIcon,
                Int32Rect.Empty,
                BitmapSizeOptions.FromWidthAndHeight(64, 64));
            src.Freeze();
            return src;
        }
        finally
        {
            DestroyIcon(hIcon);
        }
    }

    [DllImport("user32.dll", SetLastError = true)]
    private static extern bool DestroyIcon(IntPtr hIcon);

    private static Bitmap RenderIconBitmap(bool masterMuted, bool micMuted, int s)
    {
        var bmp = new Bitmap(s, s);
        using var g = Graphics.FromImage(bmp);
        g.SmoothingMode = SmoothingMode.AntiAlias;
        g.Clear(System.Drawing.Color.Transparent);

        float scale = s / 32f;
        var borderCol = masterMuted
            ? System.Drawing.Color.FromArgb(230, 220, 68, 80)
            : System.Drawing.Color.FromArgb(225, 139, 92, 246);

        using var bgBrush = new SolidBrush(System.Drawing.Color.FromArgb(245, 22, 20, 34));
        using var borderPen = new System.Drawing.Pen(borderCol, 1.8f * scale);
        g.FillEllipse(bgBrush, 2 * scale, 2 * scale, (s - 4 * scale), (s - 4 * scale));
        g.DrawEllipse(borderPen, 2 * scale, 2 * scale, (s - 4 * scale), (s - 4 * scale));

        using var trackPen = new System.Drawing.Pen(System.Drawing.Color.FromArgb(140, 150, 145, 175), 2f * scale);
        using var activePen = new System.Drawing.Pen(
            masterMuted ? System.Drawing.Color.FromArgb(180, 135, 130, 150) : System.Drawing.Color.FromArgb(255, 155, 115, 255),
            2f * scale);
        using var knobBrush = new SolidBrush(masterMuted ? System.Drawing.Color.FromArgb(180, 175, 195) : System.Drawing.Color.White);

        float[] xs = { 10f * scale, 16f * scale, 22f * scale };
        float[] ys = { 13f * scale, 19f * scale, 15f * scale };
        float r = 2.2f * scale;
        for (int i = 0; i < 3; i++)
        {
            g.DrawLine(trackPen, xs[i], 8f * scale, xs[i], 24f * scale);
            g.DrawLine(activePen, xs[i], ys[i], xs[i], 24f * scale);
            g.FillEllipse(knobBrush, xs[i] - r, ys[i] - r, r * 2, r * 2);
        }

        if (masterMuted)
        {
            using var slashPen = new System.Drawing.Pen(System.Drawing.Color.FromArgb(245, 248, 81, 73), 2.4f * scale);
            g.DrawLine(slashPen, 7f * scale, 7f * scale, 25f * scale, 25f * scale);
        }

        if (micMuted)
        {
            using var dotBg = new SolidBrush(System.Drawing.Color.FromArgb(255, 239, 68, 68));
            using var dotRing = new System.Drawing.Pen(System.Drawing.Color.FromArgb(255, 18, 16, 26), 1.5f * scale);
            g.FillEllipse(dotBg, 20f * scale, 20f * scale, 10f * scale, 10f * scale);
            g.DrawEllipse(dotRing, 20f * scale, 20f * scale, 10f * scale, 10f * scale);
        }

        return bmp;
    }

    private Icon GetOrCreateIcon(bool masterMuted, bool micMuted)
    {
        int key = (masterMuted ? 1 : 0) | (micMuted ? 2 : 0);
        if (_iconCache.TryGetValue(key, out var existing)) return existing;

        using var bmp = RenderIconBitmap(masterMuted, micMuted, 32);
        IntPtr hIcon = bmp.GetHicon();
        var ico = Icon.FromHandle(hIcon);
        _iconCache[key] = ico;
        return ico;
    }

    public void Dispose()
    {
        if (_mouseHook != IntPtr.Zero)
        {
            UnhookWindowsHookEx(_mouseHook);
            _mouseHook = IntPtr.Zero;
        }
        _notifyIcon.Visible = false;
        _notifyIcon.Dispose();
        foreach (var ico in _iconCache.Values)
        {
            try { ico.Dispose(); } catch { }
        }
        _iconCache.Clear();
    }
}
