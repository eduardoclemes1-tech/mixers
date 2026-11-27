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
    private const double MinWindowHeight = 396;
    private const double MaxWindowHeight = 660;

    private static readonly SolidColorBrush PrimaryTextBrush = CreateFrozenBrush(Color.FromRgb(244, 244, 248));
    private static readonly SolidColorBrush MutedTextBrush = CreateFrozenBrush(Color.FromRgb(130, 125, 152));
    private static readonly SolidColorBrush SubtleButtonBrush = CreateFrozenBrush(Color.FromArgb(34, 255, 255, 255));
    private static readonly SolidColorBrush DangerActiveBrush = CreateFrozenBrush(Color.FromRgb(139, 38, 62));

    private static readonly HashSet<string> CallApps = new(StringComparer.OrdinalIgnoreCase)
    {
        "discord", "teams", "ms-teams", "zoom", "skype", "slack", "webex", "obs64"
    };

    private static readonly HashSet<string> MediaApps = new(StringComparer.OrdinalIgnoreCase)
    {
        "spotify", "vlc", "chrome", "msedge", "firefox", "opera", "brave", "applemusic", "tidal", "music.ui"
    };

    private static SolidColorBrush CreateFrozenBrush(Color c)
    {
        var b = new SolidColorBrush(c);
        b.Freeze();
        return b;
    }

    private readonly AudioService _audio = new();
    private readonly SettingsService _settings = new();
    private readonly HotkeyService _hotkey = new();
    private readonly TrayService _tray;
    private readonly WindowEventWatcher _windowWatcher;
    private readonly OsdWindow _osd = new();
    private FluentThemePalette _theme;

    private readonly DispatcherTimer _sessionTimer;
    private readonly DispatcherTimer _meterTimer;
    private readonly DispatcherTimer _bgMonitorTimer;
    private readonly DispatcherTimer _settingsSaveTimer;
    private readonly DispatcherTimer _realtimeRefreshTimer;

    private readonly Dictionary<string, AppRowWidgets> _appRows = new(StringComparer.OrdinalIgnoreCase);
    private readonly Dictionary<string, MicRowWidgets> _micRows = new(StringComparer.OrdinalIgnoreCase);
    private readonly HashSet<string> _seenSessionInstances = new(StringComparer.OrdinalIgnoreCase);
    private readonly HashSet<string> _knownAppIds = new(StringComparer.OrdinalIgnoreCase);
    private readonly HashSet<string> _everHadAudioApps = new(StringComparer.OrdinalIgnoreCase);
    private readonly Dictionary<string, (float Volume, bool Muted)> _activeAppOverrides = new(StringComparer.OrdinalIgnoreCase);
    private readonly Dictionary<string, DateTime> _lastAppActiveUtc = new(StringComparer.OrdinalIgnoreCase);
    private readonly Dictionary<string, float> _duckedOriginalVolumes = new(StringComparer.OrdinalIgnoreCase);
    private DateTime _lastCallSoundUtc = DateTime.MinValue;
    private bool _pendingDevicesRebuild;
    private bool _isMediaPlaying;

    private List<AppSessionInfo> _sessions = new();
    private List<MicrophoneInfo> _mics = new();

    private bool _isVisible;
    private bool _settingsOpen;
    private bool _devicesOpen;
    private bool _pinned;
    private int _recordingHotkeyId; // 0 = não gravando, OpenHotkeyId ou MicMuteHotkeyId
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

        Icon = TrayService.CreateWindowIconSource();
        ShowInTaskbar = _settings.Settings.ShowInTaskbar;

        _theme = WindowsThemeService.BuildPalette(
            WindowsThemeService.GetWindowsAccentColor(),
            _settings.Settings.TransparentGlass);
        ApplyTheme();

        VersionBadgeText.Text = $"v{App.AppVersion}";
        StatusText.Text = $"Mixers v{App.AppVersion}";
        TransparentGlassCheck.IsChecked = _settings.Settings.TransparentGlass;
        ShowInTaskbarCheck.IsChecked = _settings.Settings.ShowInTaskbar;
        AnimationsCheck.IsChecked = _settings.Settings.Animations;
        MediaControlsCheck.IsChecked = _settings.Settings.ShowMediaControls;
        ShowAllOpenAppsCheck.IsChecked = _settings.Settings.ShowAllOpenApps;
        OnlyActiveCheck.IsChecked = _settings.Settings.OnlyActiveApps;
        RememberVolCheck.IsChecked = _settings.Settings.RememberAppVolumes;
        SyncSavedStatesToAudioService();
        AutoDuckCheck.IsChecked = _settings.Settings.AutoDuckOnCall;
        AutostartCheck.IsChecked = WindowsThemeService.IsAutostartEnabled();
        PinCheck.IsChecked = false;
        MediaBar.Visibility = _settings.Settings.ShowMediaControls ? Visibility.Visible : Visibility.Collapsed;
        UpdateRestoreHiddenButton();

        int savedAlphaPct = (int)Math.Clamp(Math.Round(_settings.Settings.Alpha * 100), 65, 100);
        OpacitySlider.Value = savedAlphaPct;
        OpacityPercentText.Text = $"{savedAlphaPct}%";
        OpacitySlider.ValueChanged += OnOpacityChanged;

        MasterSlider.ValueChanged += OnMasterSliderChanged;

        // Atalhos globais (Abrir/Ocultar + Mutar Microfone + Alternar Saída)
        _hotkey.Attach(this);
        _hotkey.Register(HotkeyService.OpenHotkeyId, _settings.Settings.Hotkey, () => Dispatcher.Invoke(ToggleFlyout));
        _hotkey.Register(HotkeyService.MicMuteHotkeyId, _settings.Settings.MicMuteHotkey, () => Dispatcher.Invoke(ToggleGlobalMicMute));
        _hotkey.Register(HotkeyService.CycleOutputHotkeyId, _settings.Settings.CycleOutputHotkey, () => Dispatcher.Invoke(CycleOutputDevice));
        RefreshHotkeyButtons();

        _tray = new TrayService(
            onToggle: () => Dispatcher.Invoke(ToggleFlyout),
            onToggleMicMute: () => Dispatcher.Invoke(ToggleGlobalMicMute),
            onCycleOutput: () => Dispatcher.Invoke(CycleOutputDevice),
            onToggleAutostart: () => Dispatcher.Invoke(ToggleAutostartFromTray),
            isAutostart: WindowsThemeService.IsAutostartEnabled,
            onCheckUpdates: () => Dispatcher.Invoke(() => _ = CheckUpdatesAsync(manual: true)),
            onQuit: () => Dispatcher.Invoke(QuitApplication),
            onTrayWheelDelta: step => Dispatcher.Invoke(() => OnTrayWheelVolume(step)));

        _sessionTimer = new DispatcherTimer { Interval = TimeSpan.FromSeconds(1.8) };
        _sessionTimer.Tick += (_, _) =>
        {
            if (_isVisible && (DateTime.UtcNow - _lastSliderEdit).TotalMilliseconds > 600)
            {
                RefreshAudioState(forceRebuild: false);
            }
        };

        _realtimeRefreshTimer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(160) };
        _realtimeRefreshTimer.Tick += (_, _) =>
        {
            _realtimeRefreshTimer.Stop();
            if ((DateTime.UtcNow - _lastSliderEdit).TotalMilliseconds <= 350)
            {
                _realtimeRefreshTimer.Start();
                return;
            }

            bool rebuildDevices = _pendingDevicesRebuild;
            _pendingDevicesRebuild = false;
            if (rebuildDevices)
            {
                _audio.MarkEndpointsDirty();
            }

            if (_isVisible)
            {
                RefreshAudioState(forceRebuild: rebuildDevices);
            }
            else
            {
                RunBackgroundAudioAutomations();
            }
        };

        _audio.SessionsChanged += OnAudioSessionsChanged;
        _audio.DevicesChanged += OnAudioDevicesChanged;
        _windowWatcher = new WindowEventWatcher(OnOpenWindowsChanged);

        _meterTimer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(55) };
        _meterTimer.Tick += (_, _) =>
        {
            if (_isVisible && !_settingsOpen)
            {
                UpdateLiveMeters();
            }
        };

        // Monitor leve em segundo plano (3s) para Modo Call + Ícone dinâmico + Lembrar volume
        _bgMonitorTimer = new DispatcherTimer { Interval = TimeSpan.FromSeconds(3) };
        _bgMonitorTimer.Tick += (_, _) => RunBackgroundAudioAutomations();
        _bgMonitorTimer.Start();

        _settingsSaveTimer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(400) };
        _settingsSaveTimer.Tick += (_, _) =>
        {
            _settingsSaveTimer.Stop();
            _settings.SaveSettings();
        };

        SystemEvents.DisplaySettingsChanged += OnSystemDisplayChanged;
        SystemEvents.UserPreferenceChanged += OnSystemUserPreferenceChanged;

        SourceInitialized += (_, _) => WindowsThemeService.SetAcrylicBlur(this, _settings.Settings.TransparentGlass);
        Deactivated += (_, _) => OnWindowDeactivated();
        PreviewKeyDown += OnWindowKeyDown;

        UpdateMicsVisibilityVisual();
        RefreshAudioState(forceRebuild: true);

        if (startMinimized)
        {
            Hide();
            _isVisible = false;
        }

        _ = Task.Delay(3000).ContinueWith(_ => Dispatcher.Invoke(() => _ = CheckUpdatesAsync(manual: false)));
    }

    // ------------------------------------------------------------------
    // Tema dinâmico do Windows + Vidro Acrylic
    // ------------------------------------------------------------------
    private void ApplyTheme()
    {
        var accentBrush = CreateFrozenBrush(_theme.Accent);
        Resources["AccentBrush"] = accentBrush;

        RootBorder.BorderBrush = CreateFrozenBrush(_theme.PanelBorder);
        var headerBrush = CreateFrozenBrush(_theme.HeaderBand);
        MasterBand.Background = headerBrush;
        MicsHeaderBand.Background = headerBrush;
        SettingsHeaderBand.Background = headerBrush;

        var listBrush = CreateFrozenBrush(_theme.ListBand);
        AppsListBand.Background = listBrush;
        MicsListBand.Background = listBrush;
        SettingsBodyBand.Background = listBrush;
        SettingsFooterBand.Background = CreateFrozenBrush(Color.FromArgb(230, _theme.ListBand.R, _theme.ListBand.G, _theme.ListBand.B));

        ApplySliderPalette(MasterSlider);
        ApplySliderPalette(OpacitySlider);
        foreach (var row in _appRows.Values) ApplySliderPalette(row.Slider);
        foreach (var row in _micRows.Values) ApplySliderPalette(row.Slider);
        _osd.ApplyTheme(_theme);
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
                _theme = WindowsThemeService.BuildPalette(
                    WindowsThemeService.GetWindowsAccentColor(),
                    _settings.Settings.TransparentGlass);
                ApplyTheme();
            });
        }
    }

    private void ScheduleSaveSettings()
    {
        _settingsSaveTimer.Stop();
        _settingsSaveTimer.Start();
    }

    // ------------------------------------------------------------------
    // Posicionamento responsivo + animações GPU
    // ------------------------------------------------------------------
    private void PositionBottomRight()
    {
        Rect workArea = SystemParameters.WorkArea;
        const double margin = 12;

        double maxAllowedW = Math.Max(290, workArea.Width - margin * 2);
        Width = Math.Min(BaseWindowWidth, maxAllowedW);

        double maxAllowedH = Math.Min(MaxWindowHeight, Math.Max(320, workArea.Height - margin * 2));
        double minAllowedH = Math.Min(MinWindowHeight, maxAllowedH);
        Height = Math.Clamp(ComputeDesiredHeight(), minAllowedH, maxAllowedH);

        Left = Math.Max(workArea.Left + margin, workArea.Right - Width - margin);
        Top = Math.Max(workArea.Top + margin, workArea.Bottom - Height - margin);
    }

    private double ComputeDesiredHeight()
    {
        double h = _settings.Settings.ShowMediaControls ? 116 : 92;
        if (_devicesOpen) h += 110;
        if (UpdateBanner.Visibility == Visibility.Visible) h += 36;

        int appCount = Math.Max(1, _sessions.Count);
        h += Math.Min(appCount, 7) * 44 + 10;

        h += 38;
        if (_settings.Settings.MicsExpanded)
        {
            int micCount = Math.Max(1, _mics.Count);
            h += Math.Min(micCount, 2) * 44 + 8;
        }

        return h;
    }

    public void ToggleFlyout()
    {
        if (_isVisible) HideFlyout();
        else ShowFlyout();
    }

    public void ShowFlyout()
    {
        _isVisible = true;
        CloseOutputDevicesPanel();
        SwitchToMixerView(instant: true);
        RefreshAudioState(forceRebuild: false);
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

        _sessionTimer.Start();
        _meterTimer.Start();
    }

    public void HideFlyout()
    {
        if (!_isVisible) return;
        _isVisible = false;
        CancelRecordHotkey();
        CloseOutputDevicesPanel();
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
        if (_pinned || _recordingHotkeyId != 0 || !_isVisible) return;
        Dispatcher.BeginInvoke(DispatcherPriority.Background, async () =>
        {
            await Task.Delay(120);
            if (!_pinned && _recordingHotkeyId == 0 && _isVisible && !WindowsThemeService.IsOurProcessForeground())
            {
                HideFlyout();
            }
        });
    }

    // ------------------------------------------------------------------
    // Seletor de Dispositivo de Saída com 1 clique
    // ------------------------------------------------------------------
    private void DeviceSwitchBtn_Click(object sender, RoutedEventArgs e)
    {
        if (_devicesOpen)
        {
            CloseOutputDevicesPanel();
            PositionBottomRight();
            return;
        }

        OutputDevicesPanel.Children.Clear();
        var devices = _audio.ListOutputDevices();
        if (devices.Count == 0)
        {
            OutputDevicesPanel.Children.Add(new TextBlock
            {
                Text = "Nenhuma saída encontrada.",
                Foreground = MutedTextBrush,
                FontSize = 11.5,
                Margin = new Thickness(8, 4, 8, 4)
            });
        }
        else
        {
            foreach (var dev in devices)
            {
                var btn = new Button
                {
                    Style = (Style)FindResource("IconButtonStyle"),
                    HorizontalContentAlignment = HorizontalAlignment.Left,
                    Padding = new Thickness(8, 6, 8, 6),
                    Margin = new Thickness(0, 1, 0, 1),
                    Background = dev.IsDefault
                        ? CreateFrozenBrush(Color.FromArgb(65, _theme.Accent.R, _theme.Accent.G, _theme.Accent.B))
                        : Brushes.Transparent,
                    Content = new TextBlock
                    {
                        Text = dev.IsDefault ? $"✓  {dev.Name}" : $"    {dev.Name}",
                        Foreground = PrimaryTextBrush,
                        FontFamily = new FontFamily("Segoe UI"),
                        FontSize = 11.5,
                        FontWeight = dev.IsDefault ? FontWeights.SemiBold : FontWeights.Normal,
                        TextTrimming = TextTrimming.CharacterEllipsis
                    }
                };
                string targetId = dev.DeviceId;
                btn.Click += (_, _) =>
                {
                    _audio.SetDefaultOutputDevice(targetId);
                    CloseOutputDevicesPanel();
                    RefreshAudioState(forceRebuild: true);
                    PositionBottomRight();
                };
                OutputDevicesPanel.Children.Add(btn);
            }
        }

        _devicesOpen = true;
        OutputDevicesBand.Visibility = Visibility.Visible;
        PositionBottomRight();
    }

    private void CloseOutputDevicesPanel()
    {
        _devicesOpen = false;
        OutputDevicesBand.Visibility = Visibility.Collapsed;
    }

    // ------------------------------------------------------------------
    // Mini Controle de Mídia (⏮ ⏯ ⏭)
    // ------------------------------------------------------------------
    private void MediaPrevBtn_Click(object sender, RoutedEventArgs e)
    {
        AudioService.SendMediaKey(AudioService.VkMediaPrevTrack);
        _ = RefreshMediaAfterDelayAsync(350);
    }

    private void MediaPlayPauseBtn_Click(object sender, RoutedEventArgs e)
    {
        AudioService.SendMediaKey(AudioService.VkMediaPlayPause);
        _isMediaPlaying = !_isMediaPlaying;
        UpdateMediaPlayPauseGlyph();
        _ = RefreshMediaAfterDelayAsync(280);
    }

    private void MediaNextBtn_Click(object sender, RoutedEventArgs e)
    {
        AudioService.SendMediaKey(AudioService.VkMediaNextTrack);
        _ = RefreshMediaAfterDelayAsync(350);
    }

    private void UpdateMediaPlayPauseGlyph()
    {
        MediaPlayPauseGlyph.Text = _isMediaPlaying ? "\uE769" : "\uE768";
        MediaPlayPauseBtn.ToolTip = _isMediaPlaying ? "Pausar" : "Tocar";
    }

    private async Task RefreshMediaAfterDelayAsync(int delayMs)
    {
        await Task.Delay(delayMs);
        await RefreshMediaTitleAsync();
    }

    // ------------------------------------------------------------------
    // Notificações em tempo real (WASAPI) + Automações em segundo plano
    // ------------------------------------------------------------------
    private void SyncSavedStatesToAudioService()
    {
        if (!_settings.Settings.RememberAppVolumes) return;
        foreach (var (appId, vol) in _settings.Settings.SavedAppVolumes)
        {
            bool? muted = _settings.Settings.SavedAppMutes.TryGetValue(appId, out bool m) ? m : null;
            _audio.SetDesiredAppState(appId, vol, muted);
        }
        foreach (var (appId, muted) in _settings.Settings.SavedAppMutes)
        {
            if (!_settings.Settings.SavedAppVolumes.ContainsKey(appId))
                _audio.SetDesiredAppState(appId, null, muted);
        }
    }

    private void OnAudioSessionsChanged()
    {
        Dispatcher.BeginInvoke(() =>
        {
            _realtimeRefreshTimer.Stop();
            _realtimeRefreshTimer.Start();
        });
    }

    private void OnOpenWindowsChanged()
    {
        if (!_isVisible || !_settings.Settings.ShowAllOpenApps || _settings.Settings.OnlyActiveApps) return;
        Dispatcher.BeginInvoke(() =>
        {
            if (_isVisible && !_realtimeRefreshTimer.IsEnabled)
                _realtimeRefreshTimer.Start();
        });
    }

    private void OnAudioDevicesChanged()
    {
        Dispatcher.BeginInvoke(() =>
        {
            _pendingDevicesRebuild = true;
            _realtimeRefreshTimer.Stop();
            _realtimeRefreshTimer.Start();
        });
    }

    private void ApplySessionPolicies(List<AppSessionInfo> rawSessions, HashSet<string>? openAppIds = null)
    {
        var currentInstances = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        var currentApps = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (var s in rawSessions)
        {
            currentApps.Add(s.AppId);
            if (!s.IsSystemSounds && s.HasAudioSession)
                _everHadAudioApps.Add(s.AppId);
            foreach (var inst in s.SessionInstanceIds)
                currentInstances.Add(inst);
        }

        // Remove sessões/apps encerrados para que reabrir um app reaplique o volume salvo
        _seenSessionInstances.IntersectWith(currentInstances);
        var aliveApps = openAppIds != null
            ? new HashSet<string>(currentApps.Concat(openAppIds), StringComparer.OrdinalIgnoreCase)
            : currentApps;
        _knownAppIds.IntersectWith(aliveApps);
        foreach (var staleApp in _activeAppOverrides.Keys.Where(k => !aliveApps.Contains(k)).ToList())
        {
            _activeAppOverrides.Remove(staleApp);
            if (!_settings.Settings.RememberAppVolumes)
                _audio.ClearDesiredAppState(staleApp);
        }

        var nowUtc = DateTime.UtcNow;
        foreach (var s in rawSessions)
        {
            if (!s.HasAudioSession) continue;
            if (s.PeakLevel > 0.005f) _lastAppActiveUtc[s.AppId] = nowUtc;

            bool hasNewInstance = false;
            foreach (var inst in s.SessionInstanceIds)
            {
                if (_seenSessionInstances.Add(inst))
                    hasNewInstance = true;
            }

            if (!s.IsSystemSounds && hasNewInstance)
            {
                if (_duckedOriginalVolumes.ContainsKey(s.AppId))
                {
                    _audio.SetAppVolume(s.AppId, 0.20f);
                    s.Volume = 0.20f;
                }
                else if (_activeAppOverrides.TryGetValue(s.AppId, out var activeOverride))
                {
                    // App já aberto (ou com pré-volume configurado) criou uma nova sessão de áudio
                    _audio.SetAppVolume(s.AppId, activeOverride.Volume);
                    s.Volume = activeOverride.Volume;
                    _audio.SetAppMute(s.AppId, activeOverride.Muted);
                    s.Muted = activeOverride.Muted;
                }
                else if (_settings.Settings.RememberAppVolumes)
                {
                    if (_settings.Settings.SavedAppVolumes.TryGetValue(s.AppId, out float savedVol))
                    {
                        _audio.SetAppVolume(s.AppId, savedVol);
                        s.Volume = savedVol;
                    }
                    if (_settings.Settings.SavedAppMutes.TryGetValue(s.AppId, out bool savedMute) && savedMute)
                    {
                        _audio.SetAppMute(s.AppId, true);
                        s.Muted = true;
                    }
                }
            }

            _knownAppIds.Add(s.AppId);
        }
    }

    private void RunBackgroundAudioAutomations()
    {
        try
        {
            bool masterMuted = _audio.GetMasterMute();
            bool micsMuted = _audio.AreAllMicsMuted();
            _tray.UpdateIconState(masterMuted, micsMuted);

            if (!_settings.Settings.AutoDuckOnCall && !_settings.Settings.RememberAppVolumes)
                return;

            var sessions = _isVisible ? _sessions : _audio.RefreshAppSessions();

            // 1. Lembrar volume preferido e sincronizar novas sessões de apps recém-abertos
            if (!_isVisible)
            {
                ApplySessionPolicies(sessions);
            }

            // 2. Modo Call automático (abaixa música/navegador durante chamadas)
            if (_settings.Settings.AutoDuckOnCall)
            {
                bool callActive = sessions.Any(s =>
                    !s.Muted &&
                    CallApps.Contains(s.AppId) &&
                    s.PeakLevel > 0.02f);

                if (callActive)
                {
                    _lastCallSoundUtc = DateTime.UtcNow;
                    foreach (var s in sessions)
                    {
                        if (!MediaApps.Contains(s.AppId) || s.Muted) continue;
                        if (!_duckedOriginalVolumes.ContainsKey(s.AppId) && s.Volume > 0.22f)
                        {
                            _duckedOriginalVolumes[s.AppId] = s.Volume;
                            _audio.SetAppVolume(s.AppId, 0.20f);
                        }
                    }
                }
                else if (_duckedOriginalVolumes.Count > 0 &&
                         (DateTime.UtcNow - _lastCallSoundUtc).TotalSeconds > 4.0)
                {
                    RestoreDuckedVolumes();
                }
            }
            else if (_duckedOriginalVolumes.Count > 0)
            {
                RestoreDuckedVolumes();
            }
        }
        catch
        {
        }
    }

    private void RestoreDuckedVolumes()
    {
        foreach (var (appId, origVol) in _duckedOriginalVolumes)
        {
            _audio.SetAppVolume(appId, origVol);
        }
        _duckedOriginalVolumes.Clear();
        if (_isVisible) RefreshAudioState(forceRebuild: false);
    }

    private void ToggleGlobalMicMute()
    {
        bool nowMuted = _audio.ToggleAllMicsMute();
        _tray.UpdateIconState(_audio.GetMasterMute(), nowMuted);
        _osd.ShowMessage(nowMuted ? "\uF781" : "\uE720", nowMuted ? "Microfone mutado" : "Microfone ativo");
        if (_isVisible) RefreshAudioState(forceRebuild: false);
    }

    private void CycleOutputDevice()
    {
        var devices = _audio.ListOutputDevices();
        if (devices.Count < 2)
        {
            _osd.ShowMessage("\uE767", devices.Count == 1 ? devices[0].Name : "Sem saída de áudio");
            return;
        }
        int curIdx = devices.FindIndex(d => d.IsDefault);
        var next = devices[(curIdx + 1) % devices.Count];
        if (_audio.SetDefaultOutputDevice(next.DeviceId))
        {
            _osd.ShowMessage("\uE7F6", $"Saída: {next.Name}");
            if (_isVisible) RefreshAudioState(forceRebuild: true);
        }
    }

    private void OnTrayWheelVolume(int deltaPct)
    {
        int cur = (int)Math.Round(_audio.GetMasterVolume() * 100);
        int next = Math.Clamp(cur + deltaPct, 0, 100);
        _audio.SetMasterVolume(next / 100f);
        if (next > 0 && _audio.GetMasterMute()) _audio.SetMasterMute(false);
        _osd.ShowMessage(next == 0 ? "\uE74F" : "\uE767", $"Volume: {next}%");
        if (_isVisible)
        {
            MasterSlider.Value = next;
            MasterPercentText.Text = next.ToString();
            ApplyMasterMuteVisual(false);
        }
    }

    private async Task RefreshMediaTitleAsync()
    {
        if (!_settings.Settings.ShowMediaControls || !_isVisible) return;
        var state = await MediaInfoService.GetCurrentMediaStateAsync();
        _isMediaPlaying = state.IsPlaying;
        UpdateMediaPlayPauseGlyph();

        if (string.IsNullOrWhiteSpace(state.Title))
        {
            MediaTitleText.Visibility = Visibility.Collapsed;
        }
        else
        {
            MediaTitleText.Text = state.Title;
            MediaTitleText.Visibility = Visibility.Visible;
        }
    }

    // ------------------------------------------------------------------
    // Troca suave GPU entre Mixer e Ajustes
    // ------------------------------------------------------------------
    private void SwitchToSettingsView()
    {
        CloseOutputDevicesPanel();
        _settingsOpen = true;
        MixerView.Visibility = Visibility.Collapsed;
        SettingsView.Visibility = Visibility.Visible;
        if (_settings.Settings.Animations)
        {
            SettingsView.BeginAnimation(OpacityProperty, new DoubleAnimation(0, 1, TimeSpan.FromMilliseconds(120)));
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
            MixerView.BeginAnimation(OpacityProperty, new DoubleAnimation(0, 1, TimeSpan.FromMilliseconds(120)));
        }
        else
        {
            MixerView.BeginAnimation(OpacityProperty, null);
            MixerView.Opacity = 1;
        }
    }

    // ------------------------------------------------------------------
    // Áudio, Medidores e Microfones
    // ------------------------------------------------------------------
    private void RefreshAudioState(bool forceRebuild)
    {
        DeviceNameText.Text = _audio.GetOutputDeviceName();

        int masterPct = (int)Math.Round(_audio.GetMasterVolume() * 100);
        bool masterMuted = _audio.GetMasterMute();
        MasterSlider.Value = masterPct;
        MasterPercentText.Text = masterPct.ToString();
        ApplyMasterMuteVisual(masterMuted);

        var procSnap = OpenAppsService.CaptureProcessSnapshot();
        var rawSessions = _audio.RefreshAppSessions(procSnap);

        // Descobre também apps abertos que ainda não criaram sessão WASAPI (ou cuja sessão expirou em silêncio)
        HashSet<string>? openAppIds = null;
        if (_settings.Settings.ShowAllOpenApps && !_settings.Settings.OnlyActiveApps)
        {
            var trackedAudioApps = new HashSet<string>(_everHadAudioApps, StringComparer.OrdinalIgnoreCase);
            trackedAudioApps.UnionWith(_activeAppOverrides.Keys);
            trackedAudioApps.UnionWith(_settings.Settings.SavedAppVolumes.Keys);
            trackedAudioApps.UnionWith(_settings.Settings.SavedAppMutes.Keys);
            trackedAudioApps.UnionWith(_settings.Settings.PinnedApps);

            var openApps = OpenAppsService.ListOpenApps(trackedAudioApps, procSnap);
            openAppIds = new HashSet<string>(openApps.Select(a => a.AppId), StringComparer.OrdinalIgnoreCase);

            var existingIds = new HashSet<string>(rawSessions.Select(s => s.AppId), StringComparer.OrdinalIgnoreCase);
            foreach (var oa in openApps)
            {
                if (existingIds.Contains(oa.AppId)) continue;

                float vol = 1f;
                bool muted = false;
                if (_activeAppOverrides.TryGetValue(oa.AppId, out var ov))
                {
                    vol = ov.Volume;
                    muted = ov.Muted;
                }
                else if (_settings.Settings.RememberAppVolumes)
                {
                    if (_settings.Settings.SavedAppVolumes.TryGetValue(oa.AppId, out float savedVol))
                        vol = Math.Clamp(savedVol, 0f, 1f);
                    if (_settings.Settings.SavedAppMutes.TryGetValue(oa.AppId, out bool savedMute))
                        muted = savedMute;
                }

                rawSessions.Add(new AppSessionInfo
                {
                    AppId = oa.AppId,
                    DisplayName = oa.DisplayName,
                    ExePath = oa.ExePath,
                    Volume = vol,
                    Muted = muted,
                    PeakLevel = 0f,
                    IsActive = false,
                    HasAudioSession = false,
                    IsSystemSounds = false
                });
            }
        }

        // Aplica volume salvo automaticamente se um app/sessão nova apareceu + marca atividade
        ApplySessionPolicies(rawSessions, openAppIds);

        // Filtra ocultos, aplica modo "só tocando agora" e ordena fixados no topo
        var nowUtc = DateTime.UtcNow;
        var newSessions = rawSessions
            .Where(s => !_settings.Settings.HiddenApps.Contains(s.AppId))
            .Where(s =>
                !_settings.Settings.OnlyActiveApps ||
                _settings.Settings.PinnedApps.Contains(s.AppId) ||
                s.IsActive ||
                s.PeakLevel > 0.005f ||
                (_lastAppActiveUtc.TryGetValue(s.AppId, out var t) && (nowUtc - t).TotalSeconds < 6.0))
            .OrderByDescending(s => _settings.Settings.PinnedApps.Contains(s.AppId))
            .ThenBy(s => !s.IsSystemSounds)
            .ThenBy(s => s.DisplayName, StringComparer.OrdinalIgnoreCase)
            .ToList();

        bool appsChanged = forceRebuild ||
            newSessions.Count != _sessions.Count ||
            !newSessions.Select(s => s.AppId).SequenceEqual(_sessions.Select(s => s.AppId), StringComparer.OrdinalIgnoreCase);
        _sessions = newSessions;

        if (appsChanged) BuildAppRows();
        else SyncAppRows();

        if (_settings.Settings.ShowMediaControls && _isVisible)
        {
            _ = RefreshMediaTitleAsync();
        }

        var newMics = _audio.RefreshMicrophones();
        bool micsChanged = forceRebuild ||
            newMics.Count != _mics.Count ||
            !newMics.Select(m => m.DeviceId).SequenceEqual(_mics.Select(m => m.DeviceId), StringComparer.OrdinalIgnoreCase);
        _mics = newMics;

        if (micsChanged) BuildMicRows();
        else SyncMicRows();

        _tray.UpdateIconState(masterMuted, _audio.AreAllMicsMuted());

        if ((appsChanged || micsChanged) && _isVisible && !_settingsOpen)
        {
            PositionBottomRight();
        }
    }

    private void UpdateLiveMeters()
    {
        MasterSlider.SetPeak(_audio.GetMasterPeak(), Colors.White);

        var appPeaks = _audio.GetAppPeaks();
        var nowUtc = DateTime.UtcNow;
        foreach (var (appId, row) in _appRows)
        {
            float p = row.Session.Muted ? 0f : appPeaks.GetValueOrDefault(appId, 0f);
            if (p > 0.005f) _lastAppActiveUtc[appId] = nowUtc;
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
                Foreground = MutedTextBrush,
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

            string baseTip = session.HasAudioSession
                ? $"{session.DisplayName} (botão direito para opções)"
                : $"{session.DisplayName} (aguardando áudio — ajuste aplica ao tocar)";
            var iconBtn = new Button
            {
                Style = (Style)FindResource("IconButtonStyle"),
                Width = 34,
                Height = 34,
                Margin = new Thickness(0, 0, 6, 0),
                ToolTip = _settings.Settings.PinnedApps.Contains(session.AppId)
                    ? $"📌 {baseTip}"
                    : baseTip,
                Content = CreateAppIconContent(session),
                ContextMenu = CreateAppContextMenu(session)
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
                Foreground = session.Muted ? MutedTextBrush : PrimaryTextBrush,
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

    private ContextMenu CreateAppContextMenu(AppSessionInfo session)
    {
        string appId = session.AppId;
        bool isPinned = _settings.Settings.PinnedApps.Contains(appId);

        var menu = new ContextMenu();

        var pinItem = new MenuItem { Header = isPinned ? "Desafixar do topo" : "Fixar no topo" };
        pinItem.Click += (_, _) =>
        {
            if (!_settings.Settings.PinnedApps.Remove(appId))
                _settings.Settings.PinnedApps.Add(appId);
            _settings.SaveSettings();
            RefreshAudioState(forceRebuild: true);
        };
        menu.Items.Add(pinItem);

        var resetItem = new MenuItem { Header = "Restaurar 100%" };
        resetItem.Click += (_, _) =>
        {
            _audio.SetAppMute(appId, false);
            _audio.SetAppVolume(appId, 1f);
            if (!session.IsSystemSounds)
            {
                _activeAppOverrides[appId] = (1f, false);
                _audio.SetDesiredAppState(appId, 1f, false);
                if (_settings.Settings.RememberAppVolumes)
                {
                    _settings.Settings.SavedAppVolumes[appId] = 1f;
                    _settings.Settings.SavedAppMutes[appId] = false;
                    ScheduleSaveSettings();
                }
            }
            RefreshAudioState(forceRebuild: false);
        };
        menu.Items.Add(resetItem);

        var hideItem = new MenuItem { Header = "Ocultar aplicativo" };
        hideItem.Click += (_, _) =>
        {
            _settings.Settings.HiddenApps.Add(appId);
            _settings.SaveSettings();
            UpdateRestoreHiddenButton();
            RefreshAudioState(forceRebuild: true);
        };
        menu.Items.Add(hideItem);

        return menu;
    }

    private void UpdateRestoreHiddenButton()
    {
        int count = _settings.Settings.HiddenApps.Count;
        if (count > 0)
        {
            RestoreHiddenBtn.Content = $"Restaurar apps ocultos ({count})";
            RestoreHiddenBtn.Visibility = Visibility.Visible;
        }
        else
        {
            RestoreHiddenBtn.Visibility = Visibility.Collapsed;
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
                Foreground = session.Muted ? MutedTextBrush : PrimaryTextBrush
            };
        }

        var exeIcon = IconService.GetAppIcon(session.ExePath, session.IconPath);
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
            CornerRadius = new CornerRadius(3),
            Background = CreateFrozenBrush(Color.FromArgb(session.Muted ? (byte)90 : (byte)160, _theme.Accent.R, _theme.Accent.G, _theme.Accent.B)),
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
            bool audioStateChanged = row.Session.HasAudioSession != session.HasAudioSession;
            row.Session = session;
            if (audioStateChanged)
            {
                string baseTip = session.HasAudioSession
                    ? $"{session.DisplayName} (botão direito para opções)"
                    : $"{session.DisplayName} (aguardando áudio — ajuste aplica ao tocar)";
                row.IconBtn.ToolTip = _settings.Settings.PinnedApps.Contains(session.AppId)
                    ? $"📌 {baseTip}"
                    : baseTip;
            }
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
                Foreground = MutedTextBrush,
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
                Foreground = mic.Muted ? MutedTextBrush : PrimaryTextBrush
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
                Foreground = mic.Muted ? MutedTextBrush : PrimaryTextBrush,
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
        MasterMuteGlyph.Foreground = muted ? MutedTextBrush : PrimaryTextBrush;
        MasterSlider.IsMuted = muted;
        MasterPercentText.Foreground = muted ? MutedTextBrush : PrimaryTextBrush;
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
        _tray.UpdateIconState(newState, _audio.AreAllMicsMuted());
    }

    private void OnAppSliderChanged(string appId, int pct)
    {
        _lastSliderEdit = DateTime.UtcNow;
        float scalar = pct / 100f;
        if (_appRows.TryGetValue(appId, out var row))
        {
            row.LastVolumePct = pct;
            row.PercentText.Text = pct.ToString();
            row.Session.Volume = scalar;
            if (!row.Session.IsSystemSounds)
            {
                _activeAppOverrides[appId] = (scalar, row.Session.Muted);
                _audio.SetDesiredAppState(appId, scalar, row.Session.Muted);
                if (_settings.Settings.RememberAppVolumes)
                {
                    _settings.Settings.SavedAppVolumes[appId] = scalar;
                    ScheduleSaveSettings();
                }
            }
        }
        _audio.SetAppVolume(appId, scalar);
    }

    private void ToggleAppMute(string appId)
    {
        if (!_appRows.TryGetValue(appId, out var row)) return;
        bool newState = !row.Session.Muted;
        _audio.SetAppMute(appId, newState);
        row.Session.Muted = newState;
        row.LastMuted = newState;
        if (!row.Session.IsSystemSounds)
        {
            _activeAppOverrides[appId] = (row.Session.Volume, newState);
            _audio.SetDesiredAppState(appId, row.Session.Volume, newState);
            if (_settings.Settings.RememberAppVolumes)
            {
                _settings.Settings.SavedAppMutes[appId] = newState;
                ScheduleSaveSettings();
            }
        }
        row.Slider.IsMuted = newState;
        row.PercentText.Foreground = newState ? MutedTextBrush : PrimaryTextBrush;
        row.IconBtn.Content = CreateAppIconContent(row.Session);
    }

    private void OnMicSliderChanged(string deviceId, int pct)
    {
        _lastSliderEdit = DateTime.UtcNow;
        if (_micRows.TryGetValue(deviceId, out var row))
        {
            row.LastVolumePct = pct;
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
        row.LastMuted = newState;
        row.Slider.IsMuted = newState;
        row.PercentText.Foreground = newState ? MutedTextBrush : PrimaryTextBrush;
        row.IconGlyph.Text = newState ? "\uF781" : "\uE720";
        row.IconGlyph.Foreground = newState ? MutedTextBrush : PrimaryTextBrush;
        _tray.UpdateIconState(_audio.GetMasterMute(), _audio.AreAllMicsMuted());
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
                MicTestBtn.Background = DangerActiveBrush;
            }
        }
    }

    private void StopMicTest()
    {
        _audio.StopMicTest();
        MicTestBtn.Content = "Testar";
        MicTestBtn.Background = SubtleButtonBrush;
    }

    // ------------------------------------------------------------------
    // Ajustes, Atalhos Globais & Presets
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
        ScheduleSaveSettings();
    }

    private void TransparentGlassCheck_Click(object sender, RoutedEventArgs e)
    {
        bool glass = TransparentGlassCheck.IsChecked == true;
        _settings.Settings.TransparentGlass = glass;
        if (!glass && _settings.Settings.Alpha < 0.96)
        {
            _settings.Settings.Alpha = 0.98;
            OpacitySlider.Value = 98;
            OpacityPercentText.Text = "98%";
            BeginAnimation(OpacityProperty, null);
            Opacity = 0.98;
        }
        _theme = WindowsThemeService.BuildPalette(WindowsThemeService.GetWindowsAccentColor(), glass);
        ApplyTheme();
        WindowsThemeService.SetAcrylicBlur(this, glass);
        _settings.SaveSettings();
        StatusText.Text = glass ? "Vidro transparente ativado." : "Fundo mais opaco e visível.";
    }

    private void ShowInTaskbarCheck_Click(object sender, RoutedEventArgs e)
    {
        bool show = ShowInTaskbarCheck.IsChecked == true;
        _settings.Settings.ShowInTaskbar = show;
        ShowInTaskbar = show;
        _settings.SaveSettings();
        StatusText.Text = show
            ? "Ícone na barra de tarefas ativo (clique direito lá para fixar)."
            : "Ocultado da barra de tarefas.";
    }

    private void ShowAllOpenAppsCheck_Click(object sender, RoutedEventArgs e)
    {
        _settings.Settings.ShowAllOpenApps = ShowAllOpenAppsCheck.IsChecked == true;
        _settings.SaveSettings();
        RefreshAudioState(forceRebuild: true);
        StatusText.Text = _settings.Settings.ShowAllOpenApps
            ? "Mostrando todos os apps abertos."
            : "Mostrando só apps com sessão de áudio ativa.";
    }

    private void OnlyActiveCheck_Click(object sender, RoutedEventArgs e)
    {
        _settings.Settings.OnlyActiveApps = OnlyActiveCheck.IsChecked == true;
        _settings.SaveSettings();
        RefreshAudioState(forceRebuild: true);
        StatusText.Text = _settings.Settings.OnlyActiveApps
            ? "Mostrando só apps tocando agora."
            : "Mostrando todos os apps.";
    }

    private void RestoreHiddenBtn_Click(object sender, RoutedEventArgs e)
    {
        _settings.Settings.HiddenApps.Clear();
        _settings.SaveSettings();
        UpdateRestoreHiddenButton();
        RefreshAudioState(forceRebuild: true);
        StatusText.Text = "Apps ocultos restaurados.";
    }

    private void AnimationsCheck_Click(object sender, RoutedEventArgs e)
    {
        _settings.Settings.Animations = AnimationsCheck.IsChecked == true;
        _settings.SaveSettings();
        StatusText.Text = _settings.Settings.Animations ? "Animações ativadas." : "Modo sequinho ativo.";
    }

    private void MediaControlsCheck_Click(object sender, RoutedEventArgs e)
    {
        _settings.Settings.ShowMediaControls = MediaControlsCheck.IsChecked == true;
        MediaBar.Visibility = _settings.Settings.ShowMediaControls ? Visibility.Visible : Visibility.Collapsed;
        _settings.SaveSettings();
        StatusText.Text = _settings.Settings.ShowMediaControls ? "Controle de mídia exibido." : "Controle de mídia oculto.";
    }

    private void RememberVolCheck_Click(object sender, RoutedEventArgs e)
    {
        _settings.Settings.RememberAppVolumes = RememberVolCheck.IsChecked == true;
        _settings.SaveSettings();
        StatusText.Text = _settings.Settings.RememberAppVolumes ? "Lembrar volume ativado." : "Lembrar volume desativado.";
    }

    private void AutoDuckCheck_Click(object sender, RoutedEventArgs e)
    {
        _settings.Settings.AutoDuckOnCall = AutoDuckCheck.IsChecked == true;
        if (!_settings.Settings.AutoDuckOnCall) RestoreDuckedVolumes();
        _settings.SaveSettings();
        StatusText.Text = _settings.Settings.AutoDuckOnCall ? "Modo Call ativado." : "Modo Call desativado.";
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
            AutostartCheck.IsChecked = newVal;
    }

    private void PinCheck_Click(object sender, RoutedEventArgs e)
    {
        _pinned = PinCheck.IsChecked == true;
        StatusText.Text = _pinned ? "Painel fixado." : "Oculta ao clicar fora.";
    }

    private void OpenHotkeyBtn_Click(object sender, RoutedEventArgs e) => StartRecordingHotkey(HotkeyService.OpenHotkeyId);
    private void MicHotkeyBtn_Click(object sender, RoutedEventArgs e) => StartRecordingHotkey(HotkeyService.MicMuteHotkeyId);
    private void CycleOutputHotkeyBtn_Click(object sender, RoutedEventArgs e) => StartRecordingHotkey(HotkeyService.CycleOutputHotkeyId);

    private Button GetHotkeyButton(int id) => id switch
    {
        HotkeyService.OpenHotkeyId => OpenHotkeyBtn,
        HotkeyService.MicMuteHotkeyId => MicHotkeyBtn,
        _ => CycleOutputHotkeyBtn
    };

    private Action GetHotkeyCallback(int id) => id switch
    {
        HotkeyService.OpenHotkeyId => () => Dispatcher.Invoke(ToggleFlyout),
        HotkeyService.MicMuteHotkeyId => () => Dispatcher.Invoke(ToggleGlobalMicMute),
        _ => () => Dispatcher.Invoke(CycleOutputDevice)
    };

    private void StartRecordingHotkey(int hotkeyId)
    {
        if (_recordingHotkeyId == hotkeyId)
        {
            CancelRecordHotkey();
            return;
        }
        if (_recordingHotkeyId != 0) CancelRecordHotkey();

        _hotkey.Unregister(hotkeyId);
        _recordingHotkeyId = hotkeyId;
        var btn = GetHotkeyButton(hotkeyId);
        btn.Content = "Pressione a tecla...";
        btn.Background = CreateFrozenBrush(_theme.Accent);
        StatusText.Text = "Pressione 1 botão especial ou combinação (Esc cancela).";
    }

    private void CancelRecordHotkey()
    {
        if (_recordingHotkeyId == 0) return;
        int id = _recordingHotkeyId;
        _recordingHotkeyId = 0;

        string prev = id switch
        {
            HotkeyService.OpenHotkeyId => _settings.Settings.Hotkey,
            HotkeyService.MicMuteHotkeyId => _settings.Settings.MicMuteHotkey,
            _ => _settings.Settings.CycleOutputHotkey
        };
        if (!string.IsNullOrEmpty(prev))
            _hotkey.Register(id, prev, GetHotkeyCallback(id));

        RefreshHotkeyButtons();
    }

    private void ClearOpenHotkeyBtn_Click(object sender, RoutedEventArgs e)
    {
        _recordingHotkeyId = 0;
        _hotkey.Unregister(HotkeyService.OpenHotkeyId);
        _settings.Settings.Hotkey = "";
        _settings.SaveSettings();
        RefreshHotkeyButtons();
        StatusText.Text = "Atalho de abrir desativado.";
    }

    private void ClearMicHotkeyBtn_Click(object sender, RoutedEventArgs e)
    {
        _recordingHotkeyId = 0;
        _hotkey.Unregister(HotkeyService.MicMuteHotkeyId);
        _settings.Settings.MicMuteHotkey = "";
        _settings.SaveSettings();
        RefreshHotkeyButtons();
        StatusText.Text = "Atalho de microfone desativado.";
    }

    private void ClearCycleOutputHotkeyBtn_Click(object sender, RoutedEventArgs e)
    {
        _recordingHotkeyId = 0;
        _hotkey.Unregister(HotkeyService.CycleOutputHotkeyId);
        _settings.Settings.CycleOutputHotkey = "";
        _settings.SaveSettings();
        RefreshHotkeyButtons();
        StatusText.Text = "Atalho de troca de saída desativado.";
    }

    private void OnWindowKeyDown(object sender, KeyEventArgs e)
    {
        Key key = e.Key == Key.System ? e.SystemKey : e.Key;

        if (_recordingHotkeyId == 0)
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
            StatusText.Text = "Gravação cancelada.";
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

        int vk = KeyInterop.VirtualKeyFromKey(key);
        if (key == Key.None && vk > 0)
            keyName = $"VK_0x{vk:X2}";

        mods.Add(keyName);
        string combo = string.Join("+", mods);

        int id = _recordingHotkeyId;
        _recordingHotkeyId = 0;
        Action callback = GetHotkeyCallback(id);

        var (ok, msg) = _hotkey.Register(id, combo, callback);
        if (ok)
        {
            string saved = _hotkey.GetHotkeyLabel(id);
            if (id == HotkeyService.OpenHotkeyId) _settings.Settings.Hotkey = saved;
            else if (id == HotkeyService.MicMuteHotkeyId) _settings.Settings.MicMuteHotkey = saved;
            else _settings.Settings.CycleOutputHotkey = saved;
            _settings.SaveSettings();
            StatusText.Text = $"✓ Salvo: {saved}";
        }
        else
        {
            string prev = id switch
            {
                HotkeyService.OpenHotkeyId => _settings.Settings.Hotkey,
                HotkeyService.MicMuteHotkeyId => _settings.Settings.MicMuteHotkey,
                _ => _settings.Settings.CycleOutputHotkey
            };
            if (!string.IsNullOrEmpty(prev)) _hotkey.Register(id, prev, callback);
            StatusText.Text = msg;
        }
        RefreshHotkeyButtons();
    }

    private void RefreshHotkeyButtons()
    {
        string openLbl = _hotkey.GetHotkeyLabel(HotkeyService.OpenHotkeyId);
        OpenHotkeyBtn.Background = SubtleButtonBrush;
        OpenHotkeyBtn.Content = string.IsNullOrEmpty(openLbl) ? "Clique para definir" : openLbl;

        string micLbl = _hotkey.GetHotkeyLabel(HotkeyService.MicMuteHotkeyId);
        MicHotkeyBtn.Background = SubtleButtonBrush;
        MicHotkeyBtn.Content = string.IsNullOrEmpty(micLbl) ? "Clique para definir" : micLbl;

        string cycleLbl = _hotkey.GetHotkeyLabel(HotkeyService.CycleOutputHotkeyId);
        CycleOutputHotkeyBtn.Background = SubtleButtonBrush;
        CycleOutputHotkeyBtn.Content = string.IsNullOrEmpty(cycleLbl) ? "Clique para definir" : cycleLbl;
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
        _audio.SessionsChanged -= OnAudioSessionsChanged;
        _audio.DevicesChanged -= OnAudioDevicesChanged;
        _windowWatcher.Dispose();
        _realtimeRefreshTimer.Stop();
        _settingsSaveTimer.Stop();
        _bgMonitorTimer.Stop();
        _sessionTimer.Stop();
        _meterTimer.Stop();
        _hotkey.Dispose();
        _tray.Dispose();
        _audio.Dispose();
        try { _osd.Close(); } catch { }
        Application.Current.Shutdown();
    }
}
