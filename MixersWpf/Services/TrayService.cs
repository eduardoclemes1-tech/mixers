using System;
using System.Collections.Generic;
using System.Drawing;
using System.Drawing.Drawing2D;
using Forms = System.Windows.Forms;

namespace Mixers.Services;

public sealed class TrayService : IDisposable
{
    private readonly Forms.NotifyIcon _notifyIcon;
    private readonly Forms.ToolStripMenuItem _autostartItem;
    private readonly Func<bool> _isAutostart;
    private readonly Dictionary<int, Icon> _iconCache = new();
    private int _currentStateKey = -1;

    public TrayService(
        Action onToggle,
        Action onToggleMicMute,
        Action onFullVolume,
        Action onFocusMode,
        Action onMuteApps,
        Action onToggleAutostart,
        Func<bool> isAutostart,
        Action onCheckUpdates,
        Action onQuit)
    {
        _isAutostart = isAutostart;

        var menu = new Forms.ContextMenuStrip();
        menu.Items.Add("Abrir / Ocultar Mixers", null, (_, _) => onToggle());
        menu.Items.Add("Mutar / Desmutar Microfone", null, (_, _) => onToggleMicMute());
        menu.Items.Add(new Forms.ToolStripSeparator());
        menu.Items.Add("100% Tudo", null, (_, _) => onFullVolume());
        menu.Items.Add("Modo Foco (30%)", null, (_, _) => onFocusMode());
        menu.Items.Add("Mutar Apps", null, (_, _) => onMuteApps());
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

    private Icon GetOrCreateIcon(bool masterMuted, bool micMuted)
    {
        int key = (masterMuted ? 1 : 0) | (micMuted ? 2 : 0);
        if (_iconCache.TryGetValue(key, out var existing)) return existing;

        const int s = 32;
        using var bmp = new Bitmap(s, s);
        using var g = Graphics.FromImage(bmp);
        g.SmoothingMode = SmoothingMode.AntiAlias;
        g.Clear(Color.Transparent);

        Color borderCol = masterMuted
            ? Color.FromArgb(230, 220, 68, 80)
            : Color.FromArgb(225, 139, 92, 246);

        using var bgBrush = new SolidBrush(Color.FromArgb(245, 22, 20, 34));
        using var borderPen = new Pen(borderCol, 1.8f);
        g.FillEllipse(bgBrush, 2, 2, s - 4, s - 4);
        g.DrawEllipse(borderPen, 2, 2, s - 4, s - 4);

        using var trackPen = new Pen(Color.FromArgb(140, 150, 145, 175), 2f);
        using var activePen = new Pen(
            masterMuted ? Color.FromArgb(180, 135, 130, 150) : Color.FromArgb(255, 155, 115, 255),
            2f);
        using var knobBrush = new SolidBrush(masterMuted ? Color.FromArgb(180, 175, 195) : Color.White);

        float[] xs = { 10f, 16f, 22f };
        float[] ys = { 13f, 19f, 15f };
        for (int i = 0; i < 3; i++)
        {
            g.DrawLine(trackPen, xs[i], 8f, xs[i], 24f);
            g.DrawLine(activePen, xs[i], ys[i], xs[i], 24f);
            g.FillEllipse(knobBrush, xs[i] - 2.2f, ys[i] - 2.2f, 4.4f, 4.4f);
        }

        if (masterMuted)
        {
            using var slashPen = new Pen(Color.FromArgb(245, 248, 81, 73), 2.4f);
            g.DrawLine(slashPen, 7f, 7f, 25f, 25f);
        }

        if (micMuted)
        {
            // Bolinha vermelha discreta no canto inferior direito indicando microfone mutado
            using var dotBg = new SolidBrush(Color.FromArgb(255, 239, 68, 68));
            using var dotRing = new Pen(Color.FromArgb(255, 18, 16, 26), 1.5f);
            g.FillEllipse(dotBg, 20f, 20f, 10f, 10f);
            g.DrawEllipse(dotRing, 20f, 20f, 10f, 10f);
        }

        IntPtr hIcon = bmp.GetHicon();
        var ico = Icon.FromHandle(hIcon);
        _iconCache[key] = ico;
        return ico;
    }

    public void Dispose()
    {
        _notifyIcon.Visible = false;
        _notifyIcon.Dispose();
        foreach (var ico in _iconCache.Values)
        {
            try { ico.Dispose(); } catch { }
        }
        _iconCache.Clear();
    }
}
