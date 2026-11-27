using System;
using System.Collections.Generic;
using System.IO;
using System.Text.Json;

namespace Mixers.Services;

public class UserSettings
{
    public double Alpha { get; set; } = 0.90;
    public bool Animations { get; set; } = true;
    public string Hotkey { get; set; } = "Ctrl+Alt+M";
    public string MicMuteHotkey { get; set; } = "";
    public bool MicsExpanded { get; set; } = true;
    public bool ShowMediaControls { get; set; } = true;
    public bool AutoDuckOnCall { get; set; } = false;
    public bool RememberAppVolumes { get; set; } = true;
    public Dictionary<string, float> SavedAppVolumes { get; set; } = new(StringComparer.OrdinalIgnoreCase);
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
