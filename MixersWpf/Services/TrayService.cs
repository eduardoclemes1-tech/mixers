using System;
using System.Drawing;
using System.Drawing.Drawing2D;
using Forms = System.Windows.Forms;

namespace Mixers.Services;

public sealed class TrayService : IDisposable
{
    private readonly Forms.NotifyIcon _notifyIcon;
    private readonly Forms.ToolStripMenuItem _autostartItem;
    private readonly Func<bool> _isAutostart;

    public TrayService(
        Action onToggle,
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
            Icon = CreateTrayIcon(),
            Text = "Mixers — Controle de Som",
            ContextMenuStrip = menu,
            Visible = true
        };

        _notifyIcon.MouseClick += (_, e) =>
        {
            if (e.Button == Forms.MouseButtons.Left)
            {
                onToggle();
            }
        };
    }

    private static Icon CreateTrayIcon()
    {
        const int s = 32;
        using var bmp = new Bitmap(s, s);
        using var g = Graphics.FromImage(bmp);
        g.SmoothingMode = SmoothingMode.AntiAlias;
        g.Clear(Color.Transparent);

        using var bgBrush = new SolidBrush(Color.FromArgb(245, 24, 20, 38));
        using var borderPen = new Pen(Color.FromArgb(220, 139, 92, 246), 1.8f);
        g.FillEllipse(bgBrush, 2, 2, s - 4, s - 4);
        g.DrawEllipse(borderPen, 2, 2, s - 4, s - 4);

        using var trackPen = new Pen(Color.FromArgb(140, 150, 145, 175), 2f);
        using var activePen = new Pen(Color.FromArgb(255, 155, 115, 255), 2f);
        using var knobBrush = new SolidBrush(Color.White);

        float[] xs = { 10f, 16f, 22f };
        float[] ys = { 13f, 19f, 15f };

        for (int i = 0; i < 3; i++)
        {
            g.DrawLine(trackPen, xs[i], 8f, xs[i], 24f);
            g.DrawLine(activePen, xs[i], ys[i], xs[i], 24f);
            g.FillEllipse(knobBrush, xs[i] - 2.2f, ys[i] - 2.2f, 4.4f, 4.4f);
        }

        IntPtr hIcon = bmp.GetHicon();
        return Icon.FromHandle(hIcon);
    }

    public void Dispose()
    {
        _notifyIcon.Visible = false;
        _notifyIcon.Dispose();
    }
}
