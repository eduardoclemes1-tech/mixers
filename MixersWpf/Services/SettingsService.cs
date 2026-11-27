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
    public bool MicsExpanded { get; set; } = true;
}

public class AudioProfile
{
    public float MasterVolume { get; set; } = 1.0f;
    public bool MasterMuted { get; set; }
    public Dictionary<string, AppProfileEntry> Apps { get; set; } = new();
}

public class AppProfileEntry
{
    public float Volume { get; set; } = 1.0f;
    public bool Muted { get; set; }
}

public class SettingsService
{
    private readonly string _baseDir;
    private readonly string _settingsPath;
    private readonly string _profilesPath;

    public UserSettings Settings { get; private set; } = new();
    public Dictionary<string, AudioProfile> Profiles { get; private set; } = new();

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
        _profilesPath = Path.Combine(_baseDir, "profiles.json");
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
                if (loaded != null) Settings = loaded;
            }
        }
        catch
        {
            Settings = new UserSettings();
        }

        try
        {
            if (File.Exists(_profilesPath))
            {
                string json = File.ReadAllText(_profilesPath);
                var loaded = JsonSerializer.Deserialize<Dictionary<string, AudioProfile>>(json, JsonOpts);
                if (loaded != null) Profiles = loaded;
            }
        }
        catch
        {
            Profiles = new Dictionary<string, AudioProfile>();
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

    public void SaveProfiles()
    {
        try
        {
            Directory.CreateDirectory(_baseDir);
            File.WriteAllText(_profilesPath, JsonSerializer.Serialize(Profiles, JsonOpts));
        }
        catch
        {
        }
    }
}
