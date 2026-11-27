using System;
using System.Collections.Generic;
using System.IO;
using System.Text.Json;

namespace Mixers.Services;

public class UserSettings
{
    public double Alpha { get; set; } = 0.94;
    public bool TransparentGlass { get; set; } = true;
    public bool Animations { get; set; } = true;
    public string Hotkey { get; set; } = "Ctrl+Alt+M";
    public string MicMuteHotkey { get; set; } = "";
    public string CycleOutputHotkey { get; set; } = "";
    public bool MicsExpanded { get; set; } = true;
    public bool ShowMediaControls { get; set; } = true;
    public bool AutoDuckOnCall { get; set; } = false;
    public bool RememberAppVolumes { get; set; } = true;
    public bool OnlyActiveApps { get; set; } = false;
    public bool ShowAllOpenApps { get; set; } = true;
    public bool ShowInTaskbar { get; set; } = false;
    public Dictionary<string, float> SavedAppVolumes { get; set; } = new(StringComparer.OrdinalIgnoreCase);
    public Dictionary<string, bool> SavedAppMutes { get; set; } = new(StringComparer.OrdinalIgnoreCase);
    public HashSet<string> PinnedApps { get; set; } = new(StringComparer.OrdinalIgnoreCase);
    public HashSet<string> HiddenApps { get; set; } = new(StringComparer.OrdinalIgnoreCase);
}

public class SettingsService
{
    private readonly string _baseDir;
    private readonly string _settingsPath;

    public UserSettings Settings { get; private set; } = new();

    private static readonly JsonSerializerOptions JsonOpts = new()
    {
        WriteIndented = true,
        PropertyNameCaseInsensitive = true
    };

    public SettingsService()
    {
        _baseDir = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
            "Mixers");
        _settingsPath = Path.Combine(_baseDir, "settings.json");
        Load();
    }

    public void Load()
    {
        try
        {
            if (File.Exists(_settingsPath))
            {
                string json = File.ReadAllText(_settingsPath);
                var loaded = JsonSerializer.Deserialize<UserSettings>(json, JsonOpts);
                if (loaded != null)
                {
                    loaded.SavedAppVolumes ??= new Dictionary<string, float>(StringComparer.OrdinalIgnoreCase);
                    loaded.SavedAppMutes ??= new Dictionary<string, bool>(StringComparer.OrdinalIgnoreCase);
                    loaded.PinnedApps ??= new HashSet<string>(StringComparer.OrdinalIgnoreCase);
                    loaded.HiddenApps ??= new HashSet<string>(StringComparer.OrdinalIgnoreCase);
                    Settings = loaded;
                }
            }
        }
        catch
        {
            Settings = new UserSettings();
        }
    }

    public void SaveSettings()
    {
        try
        {
            Directory.CreateDirectory(_baseDir);
            File.WriteAllText(_settingsPath, JsonSerializer.Serialize(Settings, JsonOpts));
        }
        catch
        {
        }
    }
}
