using System;
using System.Runtime.InteropServices;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Interop;
using System.Windows.Media;
using System.Windows.Media.Animation;
using System.Windows.Threading;
using Mixers.Services;

namespace Mixers.Controls;

/// <summary>
/// Mini aviso flutuante (OSD) discreto e click-through no canto inferior direito
/// que não rouba foco de jogos ou aplicativos em tela cheia.
/// </summary>
public sealed class OsdWindow : Window
{
    private const int GwlExStyle = -20;
    private const int WsExTransparent = 0x00000020;
    private const int WsExToolWindow = 0x00000080;
    private const int WsExNoActivate = 0x08000000;

    [DllImport("user32.dll")]
    private static extern int GetWindowLong(IntPtr hwnd, int index);

    [DllImport("user32.dll")]
    private static extern int SetWindowLong(IntPtr hwnd, int index, int newStyle);

    private readonly Border _border;
    private readonly TextBlock _iconText;
    private readonly TextBlock _msgText;
    private readonly DispatcherTimer _hideTimer;

    public OsdWindow()
    {
        WindowStyle = WindowStyle.None;
        AllowsTransparency = true;
        Background = Brushes.Transparent;
        Topmost = true;
        ShowInTaskbar = false;
        ShowActivated = false;
        Focusable = false;
        SizeToContent = SizeToContent.WidthAndHeight;
        ResizeMode = ResizeMode.NoResize;

        _iconText = new TextBlock
        {
            FontFamily = new FontFamily("Segoe MDL2 Assets"),
            FontSize = 15,
            Foreground = Brushes.White,
            VerticalAlignment = VerticalAlignment.Center,
            Margin = new Thickness(0, 0, 8, 0)
        };

        _msgText = new TextBlock
        {
            FontFamily = new FontFamily("Segoe UI"),
            FontSize = 12.5,
            FontWeight = FontWeights.SemiBold,
            Foreground = Brushes.White,
            MaxWidth = 260,
            TextTrimming = TextTrimming.CharacterEllipsis,
            VerticalAlignment = VerticalAlignment.Center
        };

        var panel = new StackPanel { Orientation = Orientation.Horizontal };
        panel.Children.Add(_iconText);
        panel.Children.Add(_msgText);

        _border = new Border
        {
            Background = new SolidColorBrush(Color.FromArgb(238, 22, 20, 32)),
            BorderBrush = new SolidColorBrush(Color.FromArgb(200, 139, 92, 246)),
            BorderThickness = new Thickness(1),
            CornerRadius = new CornerRadius(0),
            Padding = new Thickness(14, 9, 14, 9),
            Child = panel
        };

        Content = _border;

        SourceInitialized += (_, _) =>
        {
            IntPtr hwnd = new WindowInteropHelper(this).Handle;
            int ex = GetWindowLong(hwnd, GwlExStyle);
            SetWindowLong(hwnd, GwlExStyle, ex | WsExTransparent | WsExToolWindow | WsExNoActivate);
        };

        _hideTimer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(1450) };
        _hideTimer.Tick += (_, _) =>
        {
            _hideTimer.Stop();
            var fade = new DoubleAnimation(Opacity, 0, TimeSpan.FromMilliseconds(160));
            fade.Completed += (_, _) =>
            {
                if (!_hideTimer.IsEnabled) Hide();
            };
            BeginAnimation(OpacityProperty, fade);
        };
    }

    public void ApplyTheme(FluentThemePalette theme)
    {
        var bg = new SolidColorBrush(Color.FromArgb(242, theme.HeaderBand.R, theme.HeaderBand.G, theme.HeaderBand.B));
        bg.Freeze();
        var bd = new SolidColorBrush(theme.Accent);
        bd.Freeze();
        _border.Background = bg;
        _border.BorderBrush = bd;
    }

    public void ShowMessage(string mdl2Glyph, string text)
    {
        _hideTimer.Stop();
        BeginAnimation(OpacityProperty, null);

        _iconText.Text = mdl2Glyph;
        _msgText.Text = text;

        Opacity = 0.96;
        Show();
        UpdateLayout();

        Rect workArea = SystemParameters.WorkArea;
        Left = workArea.Right - ActualWidth - 14;
        Top = workArea.Bottom - ActualHeight - 14;

        _hideTimer.Start();
    }
}
