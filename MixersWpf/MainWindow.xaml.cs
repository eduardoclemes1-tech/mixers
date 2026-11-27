using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Media.Animation;
using System.Windows.Threading;
using Microsoft.Win32;
using Mixers.Controls;
using Mixers.Services;

namespace Mixers;

public partial class MainWindow : Window
{
    private const double BaseWindowWidth = 356;
    private const double MinWindowHeight = 384;
    private const double MaxWindowHeight = 560;

    private static readonly SolidColorBrush PrimaryTextBrush = CreateFrozenBrush(Color.FromRgb(244, 244, 248));
    private static readonly SolidColorBrush MutedTextBrush = CreateFrozenBrush(Color.FromRgb(130, 125, 152));
    private static readonly SolidColorBrush SubtleButtonBrush = CreateFrozenBrush(Color.FromArgb(34, 255, 255, 255));
    private static readonly SolidColorBrush DangerActiveBrush = CreateFrozenBrush(Color.FromRgb(139, 38, 62));

    private static SolidColorBrush CreateFrozenBrush(Color c)
    {
        var b = new SolidColorBrush(c);
        b.Freeze();
        return b;
    }

    private readonly AudioService _audio = new();
    private readonly SettingsService _settings = new();
    private readonly HotkeyService _hotkey;
    private readonly TrayService _tray;
    private FluentThemePalette _theme;

    private readonly DispatcherTimer _sessionTimer;
    private readonly DispatcherTimer _meterTimer;
    private readonly DispatcherTimer _opacitySaveTimer;

    private readonly Dictionary<string, AppRowWidgets> _appRows = new(StringComparer.OrdinalIgnoreCase);
    private readonly Dictionary<string, MicRowWidgets> _micRows = new(StringComparer.OrdinalIgnoreCase);
    private List<AppSessionInfo> _sessions = new();
    private List<MicrophoneInfo> _mics = new();

    private bool _isVisible;
    private bool _settingsOpen;
    private bool _pinned;
    private bool _recordingHotkey;
    private bool _updating;
    private UpdateInfo? _pendingUpdate;
    private DateTime _lastSliderEdit = DateTime.MinValue;

    private sealed class AppRowWidgets
    {
        public required AppSessionInfo Session { get; set; }
        public required Button IconBtn { get; init; }
        public required VolumeSliderControl Slider { get; init; }
        public required TextBlock PercentText { get; init; }
        public bool LastMuted { get; set; }
        public int LastVolumePct { get; set; }
    }

    private sealed class MicRowWidgets
    {
        public required MicrophoneInfo Mic { get; set; }
        public required Button IconBtn { get; init; }
        public required TextBlock IconGlyph { get; init; }
        public required VolumeSliderControl Slider { get; init; }
        public required TextBlock PercentText { get; init; }
        public bool LastMuted { get; set; }
        public int LastVolumePct { get; set; }
        public string LastQualityLabel { get; set; } = "";
    }

    public MainWindow(bool startMinimized)
    {
        InitializeComponent();

        _theme = WindowsThemeService.BuildPalette(WindowsThemeService.GetWindowsAccentColor());
        ApplyTheme();

        VersionBadgeText.Text = $"v{App.AppVersion}";
        StatusText.Text = $"Mixers v{App.AppVersion}";
        AnimationsCheck.IsChecked = _settings.Settings.Animations;
        AutostartCheck.IsChecked = WindowsThemeService.IsAutostartEnabled();
        PinCheck.IsChecked = false;

        int savedAlphaPct = (int)Math.Clamp(Math.Round(_settings.Settings.Alpha * 100), 65, 100);
        OpacitySlider.Value = savedAlphaPct;
        OpacityPercentText.Text = $"{savedAlphaPct}%";
        OpacitySlider.ValueChanged += OnOpacityChanged;

        MasterSlider.ValueChanged += OnMasterSliderChanged;

        _hotkey = new HotkeyService(() => Dispatcher.Invoke(ToggleFlyout));
        _hotkey.Attach(this);
        var (_, hkMsg) = _hotkey.Register(_settings.Settings.Hotkey);
        UpdateHotkeyBadge(_hotkey.CurrentHotkey);
        if (!string.IsNullOrEmpty(hkMsg)) StatusText.Text = hkMsg;

        _tray = new TrayService(
            onToggle: () => Dispatcher.Invoke(ToggleFlyout),
            onFullVolume: () => Dispatcher.Invoke(ApplyPresetFull),
            onFocusMode: () => Dispatcher.Invoke(ApplyPresetFocus),
            onMuteApps: () => Dispatcher.Invoke(ApplyPresetMute),
            onToggleAutostart: () => Dispatcher.Invoke(ToggleAutostartFromTray),
            isAutostart: WindowsThemeService.IsAutostartEnabled,
            onCheckUpdates: () => Dispatcher.Invoke(() => _ = CheckUpdatesAsync(manual: true)),
            onQuit: () => Dispatcher.Invoke(QuitApplication));

        _sessionTimer = new DispatcherTimer { Interval = TimeSpan.FromSeconds(2.5) };
        _sessionTimer.Tick += (_, _) =>
        {
            if (_isVisible && (DateTime.UtcNow - _lastSliderEdit).TotalMilliseconds > 600)
            {
                RefreshAudioState(forceRebuild: false);
            }
        };

        _meterTimer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(55) };
        _meterTimer.Tick += (_, _) =>
        {
            if (_isVisible && !_settingsOpen)
            {
                UpdateLiveMeters();
            }
        };

        _opacitySaveTimer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(350) };
        _opacitySaveTimer.Tick += (_, _) =>
        {
            _opacitySaveTimer.Stop();
            _settings.SaveSettings();
        };

        SystemEvents.DisplaySettingsChanged += OnSystemDisplayChanged;
        SystemEvents.UserPreferenceChanged += OnSystemUserPreferenceChanged;

        SourceInitialized += (_, _) => WindowsThemeService.EnableAcrylicBlur(this);
        Deactivated += (_, _) => OnWindowDeactivated();
        PreviewKeyDown += OnWindowKeyDown;

        UpdateMicsVisibilityVisual();
        RefreshAudioState(forceRebuild: true);

        if (startMinimized)
        {
            Hide();
            _isVisible = false;
        }

        // Checa atualização silenciosamente 3 segundos após abrir
        _ = Task.Delay(3000).ContinueWith(_ => Dispatcher.Invoke(() => _ = CheckUpdatesAsync(manual: false)));
    }

    // ------------------------------------------------------------------
    // Tema dinâmico baseado na cor de destaque do Windows + Vidro Acrylic
    // ------------------------------------------------------------------
    private void ApplyTheme()
    {
        var accentBrush = new SolidColorBrush(_theme.Accent);
        Resources["AccentBrush"] = accentBrush;

        RootBorder.BorderBrush = new SolidColorBrush(_theme.PanelBorder);
        MasterBand.Background = new SolidColorBrush(_theme.HeaderBand);
        MicsHeaderBand.Background = new SolidColorBrush(_theme.HeaderBand);
        SettingsHeaderBand.Background = new SolidColorBrush(_theme.HeaderBand);

        var listBrush = new SolidColorBrush(_theme.ListBand);
        AppsListBand.Background = listBrush;
        MicsListBand.Background = listBrush;
        SettingsBodyBand.Background = listBrush;
        SettingsFooterBand.Background = new SolidColorBrush(Color.FromArgb(230, _theme.ListBand.R, _theme.ListBand.G, _theme.ListBand.B));

        ApplySliderPalette(MasterSlider);
        ApplySliderPalette(OpacitySlider);
        foreach (var row in _appRows.Values) ApplySliderPalette(row.Slider);
        foreach (var row in _micRows.Values) ApplySliderPalette(row.Slider);
    }

    private void OnSystemDisplayChanged(object? sender, EventArgs e)
    {
        Dispatcher.BeginInvoke(() =>
        {
            if (_isVisible) PositionBottomRight();
        });
    }

    private void OnSystemUserPreferenceChanged(object sender, UserPreferenceChangedEventArgs e)
    {
        if (e.Category is UserPreferenceCategory.General or UserPreferenceCategory.Color or UserPreferenceCategory.VisualStyle)
        {
            Dispatcher.BeginInvoke(() =>
            {
                _theme = WindowsThemeService.BuildPalette(WindowsThemeService.GetWindowsAccentColor());
                ApplyTheme();
            });
        }
    }

    private void ApplySliderPalette(VolumeSliderControl slider)
    {
        slider.ApplyColors(
            _theme.Accent,
            _theme.AccentHover,
            _theme.TrackUnfilled,
            _theme.TrackMuted,
            _theme.ThumbMuted);
    }

    // ------------------------------------------------------------------
    // Posicionamento canto inferior direito + animações GPU (DirectX 60/144Hz)
    // ------------------------------------------------------------------
    private void PositionBottomRight()
    {
        Rect workArea = SystemParameters.WorkArea;
        const double margin = 12;

        double maxAllowedW = Math.Max(290, workArea.Width - margin * 2);
        Width = Math.Min(BaseWindowWidth, maxAllowedW);

        double maxAllowedH = Math.Min(MaxWindowHeight, Math.Max(310, workArea.Height - margin * 2));
        double minAllowedH = Math.Min(MinWindowHeight, maxAllowedH);
        Height = Math.Clamp(ComputeDesiredHeight(), minAllowedH, maxAllowedH);

        Left = Math.Max(workArea.Left + margin, workArea.Right - Width - margin);
        Top = Math.Max(workArea.Top + margin, workArea.Bottom - Height - margin);
    }

    private double ComputeDesiredHeight()
    {
        double h = 92; // Master band
        if (UpdateBanner.Visibility == Visibility.Visible) h += 36;

        int appCount = Math.Max(1, _sessions.Count);
        h += Math.Min(appCount, 5) * 44 + 10;

        h += 38; // Mics header
        if (_settings.Settings.MicsExpanded)
        {
            int micCount = Math.Max(1, _mics.Count);
            h += Math.Min(micCount, 2) * 44 + 8;
        }

        return Math.Clamp(h, MinWindowHeight, MaxWindowHeight);
    }

    public void ToggleFlyout()
    {
        if (_isVisible) HideFlyout();
        else ShowFlyout();
    }

    public void ShowFlyout()
    {
        _isVisible = true;
        SwitchToMixerView(instant: true);
        PositionBottomRight();

        double targetAlpha = Math.Clamp(_settings.Settings.Alpha, 0.65, 1.0);

        if (_settings.Settings.Animations)
        {
            Opacity = 0;
            RootTranslate.Y = 12;
            Show();
            Activate();

            var ease = new CubicEase { EasingMode = EasingMode.EaseOut };
            var fade = new DoubleAnimation(0, targetAlpha, TimeSpan.FromMilliseconds(150)) { EasingFunction = ease };
            var slide = new DoubleAnimation(12, 0, TimeSpan.FromMilliseconds(160)) { EasingFunction = ease };
            BeginAnimation(OpacityProperty, fade);
            RootTranslate.BeginAnimation(TranslateTransform.YProperty, slide);
        }
        else
        {
            BeginAnimation(OpacityProperty, null);
            RootTranslate.BeginAnimation(TranslateTransform.YProperty, null);
            Opacity = targetAlpha;
            RootTranslate.Y = 0;
            Show();
            Activate();
        }

        // Atualiza sessões sem travar a abertura
        Dispatcher.BeginInvoke(DispatcherPriority.Background, () => RefreshAudioState(forceRebuild: false));
        _sessionTimer.Start();
        _meterTimer.Start();
    }

    public void HideFlyout()
    {
        if (!_isVisible) return;
        _isVisible = false;
        CancelRecordHotkey();
        StopMicTest();
        _sessionTimer.Stop();
        _meterTimer.Stop();

        if (_settings.Settings.Animations)
        {
            var ease = new CubicEase { EasingMode = EasingMode.EaseIn };
            var fade = new DoubleAnimation(Opacity, 0, TimeSpan.FromMilliseconds(100)) { EasingFunction = ease };
            var slide = new DoubleAnimation(0, 8, TimeSpan.FromMilliseconds(100)) { EasingFunction = ease };
            fade.Completed += (_, _) =>
            {
                if (!_isVisible) Hide();
            };
            BeginAnimation(OpacityProperty, fade);
            RootTranslate.BeginAnimation(TranslateTransform.YProperty, slide);
        }
        else
        {
            BeginAnimation(OpacityProperty, null);
            RootTranslate.BeginAnimation(TranslateTransform.YProperty, null);
            Hide();
        }
    }

    private void OnWindowDeactivated()
    {
        if (_pinned || _recordingHotkey || !_isVisible) return;
        Dispatcher.BeginInvoke(DispatcherPriority.Background, async () =>
        {
            await Task.Delay(120);
            if (!_pinned && !_recordingHotkey && _isVisible && !WindowsThemeService.IsOurProcessForeground())
            {
                HideFlyout();
            }
        });
    }

    // ------------------------------------------------------------------
    // Troca suave GPU entre Mixer e Ajustes (ZERO redimensionamento / pixelação)
    // ------------------------------------------------------------------
    private void SwitchToSettingsView()
    {
        _settingsOpen = true;
        MixerView.Visibility = Visibility.Collapsed;
        SettingsView.Visibility = Visibility.Visible;
        if (_settings.Settings.Animations)
        {
            var fade = new DoubleAnimation(0, 1, TimeSpan.FromMilliseconds(120));
            SettingsView.BeginAnimation(OpacityProperty, fade);
        }
        else
        {
            SettingsView.BeginAnimation(OpacityProperty, null);
            SettingsView.Opacity = 1;
        }
    }

    private void SwitchToMixerView(bool instant = false)
    {
        _settingsOpen = false;
        CancelRecordHotkey();
        SettingsView.Visibility = Visibility.Collapsed;
        MixerView.Visibility = Visibility.Visible;
        if (!instant && _settings.Settings.Animations)
        {
            var fade = new DoubleAnimation(0, 1, TimeSpan.FromMilliseconds(120));
            MixerView.BeginAnimation(OpacityProperty, fade);
        }
        else
        {
            MixerView.BeginAnimation(OpacityProperty, null);
            MixerView.Opacity = 1;
        }
    }

    // ------------------------------------------------------------------
    // Áudio, Medidores 60fps e Microfones
    // ------------------------------------------------------------------
    private void RefreshAudioState(bool forceRebuild)
    {
        DeviceNameText.Text = _audio.GetOutputDeviceName();

        int masterPct = (int)Math.Round(_audio.GetMasterVolume() * 100);
        bool masterMuted = _audio.GetMasterMute();
        MasterSlider.Value = masterPct;
        MasterPercentText.Text = masterPct.ToString();
        ApplyMasterMuteVisual(masterMuted);

        var newSessions = _audio.RefreshAppSessions();
        bool appsChanged = forceRebuild ||
            newSessions.Count != _sessions.Count ||
            !newSessions.Select(s => s.AppId).SequenceEqual(_sessions.Select(s => s.AppId), StringComparer.OrdinalIgnoreCase);
        _sessions = newSessions;

        if (appsChanged) BuildAppRows();
        else SyncAppRows();

        var newMics = _audio.RefreshMicrophones();
        bool micsChanged = forceRebuild ||
            newMics.Count != _mics.Count ||
            !newMics.Select(m => m.DeviceId).SequenceEqual(_mics.Select(m => m.DeviceId), StringComparer.OrdinalIgnoreCase);
        _mics = newMics;

        if (micsChanged) BuildMicRows();
        else SyncMicRows();

        if ((appsChanged || micsChanged) && _isVisible && !_settingsOpen)
        {
            PositionBottomRight();
        }
    }

    private void UpdateLiveMeters()
    {
        MasterSlider.SetPeak(_audio.GetMasterPeak(), Colors.White);

        var appPeaks = _audio.GetAppPeaks();
        foreach (var (appId, row) in _appRows)
        {
            float p = row.Session.Muted ? 0f : appPeaks.GetValueOrDefault(appId, 0f);
            row.Slider.SetPeak(p, Colors.White);
        }

        if (_settings.Settings.MicsExpanded)
        {
            var micPeaks = _audio.GetMicPeaks();
            foreach (var (devId, row) in _micRows)
            {
                float p = row.Mic.Muted ? 0f : micPeaks.GetValueOrDefault(devId, 0f);
                var (label, col) = AudioService.ClassifyMicQuality(p, row.Mic.Muted);
                row.Slider.SetPeak(p, col);
                if (!string.Equals(row.LastQualityLabel, label, StringComparison.Ordinal))
                {
                    row.LastQualityLabel = label;
                    row.IconBtn.ToolTip = $"{row.Mic.Name}  •  {label}";
                }
            }
        }
    }

    private void BuildAppRows()
    {
        AppsPanel.Children.Clear();
        _appRows.Clear();

        if (_sessions.Count == 0)
        {
            AppsPanel.Children.Add(new TextBlock
            {
                Text = "Nenhum aplicativo reproduzindo áudio.",
                Foreground = new SolidColorBrush(Color.FromRgb(140, 136, 162)),
                FontFamily = new FontFamily("Segoe UI"),
                FontSize = 12,
                Margin = new Thickness(16, 14, 16, 14)
            });
            return;
        }

        foreach (var session in _sessions)
        {
            var grid = new Grid { Height = 44, Margin = new Thickness(10, 0, 12, 0) };
            grid.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
            grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(36) });

            int pct = (int)Math.Round(session.Volume * 100);

            var iconBtn = new Button
            {
                Style = (Style)FindResource("IconButtonStyle"),
                Width = 34,
                Height = 34,
                Margin = new Thickness(0, 0, 6, 0),
                ToolTip = session.DisplayName,
                Content = CreateAppIconContent(session)
            };
            iconBtn.Click += (_, _) => ToggleAppMute(session.AppId);
            Grid.SetColumn(iconBtn, 0);

            var slider = new VolumeSliderControl
            {
                Value = pct,
                IsMuted = session.Muted,
                VerticalAlignment = VerticalAlignment.Center,
                Margin = new Thickness(2, 0, 4, 0)
            };
            ApplySliderPalette(slider);
            slider.SetPeak(session.Muted ? 0f : session.PeakLevel, Colors.White);
            slider.ValueChanged += val => OnAppSliderChanged(session.AppId, val);
            Grid.SetColumn(slider, 1);

            var pctText = new TextBlock
            {
                Text = pct.ToString(),
                Foreground = new SolidColorBrush(session.Muted ? Color.FromRgb(130, 125, 152) : Color.FromRgb(244, 244, 248)),
                FontFamily = new FontFamily("Segoe UI"),
                FontSize = 15,
                HorizontalAlignment = HorizontalAlignment.Right,
                VerticalAlignment = VerticalAlignment.Center
            };
            Grid.SetColumn(pctText, 2);

            grid.Children.Add(iconBtn);
            grid.Children.Add(slider);
            grid.Children.Add(pctText);
            AppsPanel.Children.Add(grid);

            _appRows[session.AppId] = new AppRowWidgets
            {
                Session = session,
                IconBtn = iconBtn,
                Slider = slider,
                PercentText = pctText,
                LastMuted = session.Muted,
                LastVolumePct = pct
            };
        }
    }

    private object CreateAppIconContent(AppSessionInfo session)
    {
        if (session.IsSystemSounds)
        {
            return new TextBlock
            {
                Text = session.Muted ? "\uE74F" : "\uE767",
                FontFamily = new FontFamily("Segoe MDL2 Assets"),
                FontSize = 17,
                Foreground = new SolidColorBrush(session.Muted ? Color.FromRgb(130, 125, 152) : Color.FromRgb(240, 240, 246))
            };
        }

        var exeIcon = IconService.GetExeIcon(session.ExePath);
        if (exeIcon != null)
        {
            return new Image
            {
                Source = exeIcon,
                Width = 22,
                Height = 22,
                Opacity = session.Muted ? 0.45 : 1.0
            };
        }

        return new Border
        {
            Width = 22,
            Height = 22,
            CornerRadius = new CornerRadius(5),
            Background = new SolidColorBrush(Color.FromArgb(session.Muted ? (byte)90 : (byte)160, _theme.Accent.R, _theme.Accent.G, _theme.Accent.B)),
            Child = new TextBlock
            {
                Text = string.IsNullOrEmpty(session.DisplayName) ? "A" : session.DisplayName[..1].ToUpperInvariant(),
                Foreground = Brushes.White,
                FontFamily = new FontFamily("Segoe UI"),
                FontSize = 11,
                FontWeight = FontWeights.SemiBold,
                HorizontalAlignment = HorizontalAlignment.Center,
                VerticalAlignment = VerticalAlignment.Center
            }
        };
    }

    private void SyncAppRows()
    {
        foreach (var session in _sessions)
        {
            if (!_appRows.TryGetValue(session.AppId, out var row)) continue;
            row.Session = session;
            int pct = (int)Math.Round(session.Volume * 100);
            if (pct != row.LastVolumePct)
            {
                row.LastVolumePct = pct;
                row.Slider.Value = pct;
                row.PercentText.Text = pct.ToString();
            }
            if (session.Muted != row.LastMuted)
            {
                row.LastMuted = session.Muted;
                row.Slider.IsMuted = session.Muted;
                row.PercentText.Foreground = session.Muted ? MutedTextBrush : PrimaryTextBrush;
                row.IconBtn.Content = CreateAppIconContent(session);
            }
        }
    }

    private void BuildMicRows()
    {
        MicsPanel.Children.Clear();
        _micRows.Clear();

        if (_mics.Count == 0)
        {
            MicsPanel.Children.Add(new TextBlock
            {
                Text = "Nenhum microfone ativo.",
                Foreground = new SolidColorBrush(Color.FromRgb(140, 136, 162)),
                FontFamily = new FontFamily("Segoe UI"),
                FontSize = 11.5,
                Margin = new Thickness(16, 10, 16, 10)
            });
            return;
        }

        foreach (var mic in _mics)
        {
            var grid = new Grid { Height = 44, Margin = new Thickness(10, 0, 12, 0) };
            grid.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
            grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(36) });

            int pct = (int)Math.Round(mic.Volume * 100);
            var (label, col) = AudioService.ClassifyMicQuality(mic.PeakLevel, mic.Muted);

            var glyph = new TextBlock
            {
                Text = mic.Muted ? "\uF781" : "\uE720",
                FontFamily = new FontFamily("Segoe MDL2 Assets"),
                FontSize = 16,
                Foreground = new SolidColorBrush(mic.Muted ? Color.FromRgb(130, 125, 152) : Color.FromRgb(244, 244, 248))
            };

            var iconBtn = new Button
            {
                Style = (Style)FindResource("IconButtonStyle"),
                Width = 34,
                Height = 34,
                Margin = new Thickness(0, 0, 6, 0),
                ToolTip = $"{mic.Name}  •  {label}",
                Content = glyph
            };
            iconBtn.Click += (_, _) => ToggleMicMute(mic.DeviceId);
            Grid.SetColumn(iconBtn, 0);

            var slider = new VolumeSliderControl
            {
                Value = pct,
                IsMuted = mic.Muted,
                VerticalAlignment = VerticalAlignment.Center,
                Margin = new Thickness(2, 0, 4, 0)
            };
            ApplySliderPalette(slider);
            slider.SetPeak(mic.Muted ? 0f : mic.PeakLevel, col);
            slider.ValueChanged += val => OnMicSliderChanged(mic.DeviceId, val);
            Grid.SetColumn(slider, 1);

            var pctText = new TextBlock
            {
                Text = pct.ToString(),
                Foreground = new SolidColorBrush(mic.Muted ? Color.FromRgb(130, 125, 152) : Color.FromRgb(244, 244, 248)),
                FontFamily = new FontFamily("Segoe UI"),
                FontSize = 15,
                HorizontalAlignment = HorizontalAlignment.Right,
                VerticalAlignment = VerticalAlignment.Center
            };
            Grid.SetColumn(pctText, 2);

            grid.Children.Add(iconBtn);
            grid.Children.Add(slider);
            grid.Children.Add(pctText);
            MicsPanel.Children.Add(grid);

            _micRows[mic.DeviceId] = new MicRowWidgets
            {
                Mic = mic,
                IconBtn = iconBtn,
                IconGlyph = glyph,
                Slider = slider,
                PercentText = pctText,
                LastMuted = mic.Muted,
                LastVolumePct = pct,
                LastQualityLabel = label
            };
        }
    }

    private void SyncMicRows()
    {
        foreach (var mic in _mics)
        {
            if (!_micRows.TryGetValue(mic.DeviceId, out var row)) continue;
            row.Mic = mic;
            int pct = (int)Math.Round(mic.Volume * 100);
            if (pct != row.LastVolumePct)
            {
                row.LastVolumePct = pct;
                row.Slider.Value = pct;
                row.PercentText.Text = pct.ToString();
            }
            if (mic.Muted != row.LastMuted)
            {
                row.LastMuted = mic.Muted;
                row.Slider.IsMuted = mic.Muted;
                row.PercentText.Foreground = mic.Muted ? MutedTextBrush : PrimaryTextBrush;
                row.IconGlyph.Text = mic.Muted ? "\uF781" : "\uE720";
                row.IconGlyph.Foreground = mic.Muted ? MutedTextBrush : PrimaryTextBrush;
            }
        }
    }

    // ------------------------------------------------------------------
    // Eventos de Controle de Áudio
    // ------------------------------------------------------------------
    private void ApplyMasterMuteVisual(bool muted)
    {
        MasterMuteGlyph.Text = muted ? "\uE74F" : "\uE767";
        MasterMuteGlyph.Foreground = new SolidColorBrush(muted ? Color.FromRgb(140, 135, 162) : Color.FromRgb(244, 244, 248));
        MasterSlider.IsMuted = muted;
        MasterPercentText.Foreground = new SolidColorBrush(muted ? Color.FromRgb(140, 135, 162) : Color.FromRgb(244, 244, 248));
    }

    private void OnMasterSliderChanged(int pct)
    {
        _lastSliderEdit = DateTime.UtcNow;
        MasterPercentText.Text = pct.ToString();
        _audio.SetMasterVolume(pct / 100f);
    }

    private void MasterMuteBtn_Click(object sender, RoutedEventArgs e)
    {
        bool newState = !_audio.GetMasterMute();
        _audio.SetMasterMute(newState);
        ApplyMasterMuteVisual(newState);
    }

    private void OnAppSliderChanged(string appId, int pct)
    {
        _lastSliderEdit = DateTime.UtcNow;
        if (_appRows.TryGetValue(appId, out var row))
        {
            row.PercentText.Text = pct.ToString();
            row.Session.Volume = pct / 100f;
        }
        _audio.SetAppVolume(appId, pct / 100f);
    }

    private void ToggleAppMute(string appId)
    {
        if (!_appRows.TryGetValue(appId, out var row)) return;
        bool newState = !row.Session.Muted;
        _audio.SetAppMute(appId, newState);
        row.Session.Muted = newState;
        row.Slider.IsMuted = newState;
        row.PercentText.Foreground = new SolidColorBrush(newState ? Color.FromRgb(130, 125, 152) : Color.FromRgb(244, 244, 248));
        row.IconBtn.Content = CreateAppIconContent(row.Session);
    }

    private void OnMicSliderChanged(string deviceId, int pct)
    {
        _lastSliderEdit = DateTime.UtcNow;
        if (_micRows.TryGetValue(deviceId, out var row))
        {
            row.PercentText.Text = pct.ToString();
            row.Mic.Volume = pct / 100f;
        }
        _audio.SetMicVolume(deviceId, pct / 100f);
    }

    private void ToggleMicMute(string deviceId)
    {
        if (!_micRows.TryGetValue(deviceId, out var row)) return;
        bool newState = !row.Mic.Muted;
        _audio.SetMicMute(deviceId, newState);
        row.Mic.Muted = newState;
        row.Slider.IsMuted = newState;
        row.PercentText.Foreground = new SolidColorBrush(newState ? Color.FromRgb(130, 125, 152) : Color.FromRgb(244, 244, 248));
        row.IconGlyph.Text = newState ? "\uF781" : "\uE720";
        row.IconGlyph.Foreground = new SolidColorBrush(newState ? Color.FromRgb(130, 125, 152) : Color.FromRgb(244, 244, 248));
    }

    private void MicsHeader_Click(object sender, MouseButtonEventArgs e)
    {
        if (e.OriginalSource is DependencyObject dep && IsChildOf(dep, MicTestBtn)) return;
        _settings.Settings.MicsExpanded = !_settings.Settings.MicsExpanded;
        _settings.SaveSettings();
        if (!_settings.Settings.MicsExpanded) StopMicTest();
        UpdateMicsVisibilityVisual();
        PositionBottomRight();
    }

    private static bool IsChildOf(DependencyObject child, DependencyObject target)
    {
        DependencyObject? cur = child;
        while (cur != null)
        {
            if (cur == target) return true;
            cur = VisualTreeHelper.GetParent(cur);
        }
        return false;
    }

    private void UpdateMicsVisibilityVisual()
    {
        MicsListBand.Visibility = _settings.Settings.MicsExpanded ? Visibility.Visible : Visibility.Collapsed;
        MicsChevron.Text = _settings.Settings.MicsExpanded ? "\uE70D" : "\uE76C";
    }

    private void MicTestBtn_Click(object sender, RoutedEventArgs e)
    {
        e.Handled = true;
        if (_audio.IsMicTesting)
        {
            StopMicTest();
        }
        else
        {
            if (!_settings.Settings.MicsExpanded)
            {
                _settings.Settings.MicsExpanded = true;
                _settings.SaveSettings();
                UpdateMicsVisibilityVisual();
                PositionBottomRight();
            }
            if (_audio.StartMicTest())
            {
                MicTestBtn.Content = "Parar";
                MicTestBtn.Background = new SolidColorBrush(Color.FromRgb(139, 38, 62));
            }
        }
    }

    private void StopMicTest()
    {
        _audio.StopMicTest();
        MicTestBtn.Content = "Testar";
        MicTestBtn.Background = new SolidColorBrush(Color.FromArgb(34, 255, 255, 255));
    }

    // ------------------------------------------------------------------
    // Ajustes, Atalho Global, Perfis & Presets
    // ------------------------------------------------------------------
    private void SettingsBtn_Click(object sender, RoutedEventArgs e) => SwitchToSettingsView();
    private void BackToMixerBtn_Click(object sender, RoutedEventArgs e) => SwitchToMixerView();
    private void HideBtn_Click(object sender, RoutedEventArgs e) => HideFlyout();

    private void OnOpacityChanged(int pct)
    {
        int clamped = Math.Clamp(pct, 65, 100);
        OpacityPercentText.Text = $"{clamped}%";
        _settings.Settings.Alpha = clamped / 100.0;
        BeginAnimation(OpacityProperty, null);
        Opacity = _settings.Settings.Alpha;
        _opacitySaveTimer.Stop();
        _opacitySaveTimer.Start();
    }

    private void AnimationsCheck_Click(object sender, RoutedEventArgs e)
    {
        _settings.Settings.Animations = AnimationsCheck.IsChecked == true;
        _settings.SaveSettings();
        StatusText.Text = _settings.Settings.Animations ? "Animações ativadas." : "Modo sequinho ativo.";
    }

    private void AutostartCheck_Click(object sender, RoutedEventArgs e)
    {
        bool desired = AutostartCheck.IsChecked == true;
        if (!WindowsThemeService.SetAutostart(desired))
        {
            AutostartCheck.IsChecked = WindowsThemeService.IsAutostartEnabled();
            StatusText.Text = "Erro ao alterar autostart.";
        }
        else
        {
            StatusText.Text = desired ? "Iniciar com Windows ativado." : "Autostart desativado.";
        }
    }

    private void ToggleAutostartFromTray()
    {
        bool newVal = !WindowsThemeService.IsAutostartEnabled();
        if (WindowsThemeService.SetAutostart(newVal))
        {
            AutostartCheck.IsChecked = newVal;
        }
    }

    private void PinCheck_Click(object sender, RoutedEventArgs e)
    {
        _pinned = PinCheck.IsChecked == true;
        StatusText.Text = _pinned ? "Painel fixado." : "Oculta ao clicar fora.";
    }

    private void RecordHotkeyBtn_Click(object sender, RoutedEventArgs e)
    {
        if (_recordingHotkey)
        {
            CancelRecordHotkey();
            return;
        }
        // Pausa o atalho atual durante a gravação para o Windows não interceptar a tecla!
        _hotkey.Unregister();
        _recordingHotkey = true;
        HotkeyRecordBtn.Content = "Pressione as teclas...";
        HotkeyRecordBtn.Background = new SolidColorBrush(_theme.Accent);
        StatusText.Text = "Pressione a combinação (ex: Ctrl+Alt+M) ou Esc.";
    }

    private void CancelRecordHotkey()
    {
        if (!_recordingHotkey) return;
        _recordingHotkey = false;
        if (!string.IsNullOrEmpty(_settings.Settings.Hotkey))
        {
            _hotkey.Register(_settings.Settings.Hotkey);
        }
        UpdateHotkeyBadge(_hotkey.CurrentHotkey);
        StatusText.Text = "Gravação cancelada.";
    }

    private void ClearHotkeyBtn_Click(object sender, RoutedEventArgs e)
    {
        _recordingHotkey = false;
        _hotkey.Unregister();
        _settings.Settings.Hotkey = "";
        _settings.SaveSettings();
        UpdateHotkeyBadge("");
        StatusText.Text = "Atalho desativado.";
    }

    private void OnWindowKeyDown(object sender, KeyEventArgs e)
    {
        Key key = e.Key == Key.System ? e.SystemKey : e.Key;

        if (!_recordingHotkey)
        {
            if (key == Key.Escape)
            {
                if (_settingsOpen) SwitchToMixerView();
                else HideFlyout();
                e.Handled = true;
            }
            return;
        }

        e.Handled = true;
        if (key == Key.Escape)
        {
            CancelRecordHotkey();
            return;
        }

        if (key is Key.LeftCtrl or Key.RightCtrl or Key.LeftAlt or Key.RightAlt
            or Key.LeftShift or Key.RightShift or Key.LWin or Key.RWin)
        {
            return;
        }

        var mods = new List<string>();
        if (Keyboard.Modifiers.HasFlag(ModifierKeys.Control)) mods.Add("Ctrl");
        if (Keyboard.Modifiers.HasFlag(ModifierKeys.Alt)) mods.Add("Alt");
        if (Keyboard.Modifiers.HasFlag(ModifierKeys.Shift)) mods.Add("Shift");

        string keyName = key.ToString();
        if (keyName.Length == 2 && keyName[0] == 'D' && char.IsDigit(keyName[1]))
            keyName = keyName[1].ToString();

        mods.Add(keyName);
        string combo = string.Join("+", mods);

        var (ok, msg) = _hotkey.Register(combo);
        _recordingHotkey = false;
        if (ok)
        {
            _settings.Settings.Hotkey = _hotkey.CurrentHotkey;
            _settings.SaveSettings();
            StatusText.Text = $"✓ Atalho salvo: {_hotkey.CurrentHotkey}";
        }
        else
        {
            if (!string.IsNullOrEmpty(_settings.Settings.Hotkey))
                _hotkey.Register(_settings.Settings.Hotkey);
            StatusText.Text = msg;
        }
        UpdateHotkeyBadge(_hotkey.CurrentHotkey);
    }

    private void UpdateHotkeyBadge(string hk)
    {
        HotkeyRecordBtn.Background = SubtleButtonBrush;
        HotkeyRecordBtn.Content = string.IsNullOrEmpty(hk) ? "Clique para definir atalho" : hk;
    }

    private void PresetFullBtn_Click(object sender, RoutedEventArgs e) => ApplyPresetFull();
    private void PresetFocusBtn_Click(object sender, RoutedEventArgs e) => ApplyPresetFocus();
    private void PresetMuteBtn_Click(object sender, RoutedEventArgs e) => ApplyPresetMute();

    private void ApplyPresetFull()
    {
        foreach (var s in _sessions)
        {
            _audio.SetAppMute(s.AppId, false);
            _audio.SetAppVolume(s.AppId, 1f);
        }
        if (_isVisible) RefreshAudioState(forceRebuild: false);
        StatusText.Text = "Apps em 100%.";
    }

    private void ApplyPresetFocus()
    {
        foreach (var s in _sessions)
        {
            _audio.SetAppMute(s.AppId, false);
            _audio.SetAppVolume(s.AppId, 0.30f);
        }
        if (_isVisible) RefreshAudioState(forceRebuild: false);
        StatusText.Text = "Modo Foco (30%).";
    }

    private void ApplyPresetMute()
    {
        foreach (var s in _sessions) _audio.SetAppMute(s.AppId, true);
        if (_isVisible) RefreshAudioState(forceRebuild: false);
        StatusText.Text = "Apps mutados.";
    }

    // ------------------------------------------------------------------
    // Auto-Updater via GitHub Releases
    // ------------------------------------------------------------------
    private void CheckUpdatesBtn_Click(object sender, RoutedEventArgs e) => _ = CheckUpdatesAsync(manual: true);

    private async Task CheckUpdatesAsync(bool manual)
    {
        if (_updating) return;
        if (manual)
        {
            if (!_isVisible) ShowFlyout();
            StatusText.Text = "Verificando atualizações...";
        }

        try
        {
            var info = await UpdateService.CheckForUpdateAsync();
            if (info != null)
            {
                _pendingUpdate = info;
                UpdateBannerText.Text = $"Nova versão v{info.Version} disponível!";
                UpdateBanner.Visibility = Visibility.Visible;
                if (_isVisible && !_settingsOpen) PositionBottomRight();
                StatusText.Text = $"v{info.Version} disponível.";
            }
            else if (manual)
            {
                StatusText.Text = $"Atualizado (v{App.AppVersion}).";
            }
        }
        catch (Exception ex)
        {
            if (manual)
            {
                StatusText.Text = $"Erro: {ex.Message}";
                StatusText.ToolTip = ex.Message;
            }
        }
    }

    private async void UpdateNowBtn_Click(object sender, RoutedEventArgs e)
    {
        if (_pendingUpdate == null || _updating) return;
        _updating = true;
        UpdateNowBtn.IsEnabled = false;
        UpdateNowBtn.Content = "Baixando...";

        try
        {
            bool shouldExit = await UpdateService.DownloadAndApplyAsync(
                _pendingUpdate,
                pct => Dispatcher.Invoke(() => UpdateNowBtn.Content = $"{pct}%"));

            if (shouldExit)
            {
                QuitApplication();
            }
            else
            {
                UpdateNowBtn.IsEnabled = true;
                UpdateNowBtn.Content = "Abrir";
            }
        }
        catch (Exception ex)
        {
            UpdateNowBtn.IsEnabled = true;
            UpdateNowBtn.Content = "Atualizar";
            StatusText.Text = $"Erro: {ex.Message}";
            StatusText.ToolTip = ex.Message;
        }
        finally
        {
            _updating = false;
        }
    }

    private void QuitBtn_Click(object sender, RoutedEventArgs e) => QuitApplication();

    private void QuitApplication()
    {
        SystemEvents.DisplaySettingsChanged -= OnSystemDisplayChanged;
        SystemEvents.UserPreferenceChanged -= OnSystemUserPreferenceChanged;
        _opacitySaveTimer.Stop();
        _sessionTimer.Stop();
        _meterTimer.Stop();
        _hotkey.Dispose();
        _tray.Dispose();
        _audio.Dispose();
        Application.Current.Shutdown();
    }
}
