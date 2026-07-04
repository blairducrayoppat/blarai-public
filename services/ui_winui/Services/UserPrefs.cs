using System.IO;
using System.Text.Json;

namespace BlarAI.Desktop.Services;

/// <summary>
/// Tiny persisted UI preference store — a JSON file in %LOCALAPPDATA%\BlarAI.
/// Unpackaged WinUI apps have no ApplicationData container, so a plain file is
/// the simplest durable home for "remember my theme across restarts".
/// </summary>
public sealed class UserPrefs
{
    public string Theme { get; set; } = "Default";  // "Light" | "Dark" | "Default"

    /// <summary>
    /// "Voice replies (BlarAI speaks)" toggle — speak assistant replies aloud
    /// (TTS, ADR-017 / #660). Persisted as DISPLAY state only: it is reflected in
    /// the settings toggle on launch, but per the always-off-at-boot rule (#660
    /// decision #3) it NEVER auto-loads the Kokoro model — the model loads only
    /// when the operator turns the toggle on in-session (voice_set_tts).
    /// </summary>
    public bool VoiceOutput { get; set; }

    /// <summary>
    /// "Microphone (BlarAI listens)" toggle — capture mic + transcribe (STT,
    /// #660). Persisted as DISPLAY state only; same always-off-at-boot rule as
    /// <see cref="VoiceOutput"/> — never auto-loads Whisper at launch.
    /// </summary>
    public bool MicEnabled { get; set; }

    /// <summary>Selected TTS voice id (e.g. "af_heart"); empty = backend default.</summary>
    public string Voice { get; set; } = "";

    private static string PrefsPath
    {
        get
        {
            string local = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
            return Path.Combine(local, "BlarAI", "ui_prefs.json");
        }
    }

    public static UserPrefs Load()
    {
        try
        {
            string path = PrefsPath;
            if (File.Exists(path))
                return JsonSerializer.Deserialize<UserPrefs>(File.ReadAllText(path)) ?? new UserPrefs();
        }
        catch { /* corrupt or unreadable — fall back to defaults */ }
        return new UserPrefs();
    }

    public void Save()
    {
        try
        {
            string path = PrefsPath;
            Directory.CreateDirectory(Path.GetDirectoryName(path)!);
            File.WriteAllText(path, JsonSerializer.Serialize(this));
        }
        catch { /* best-effort; a failed save just means the choice is not remembered */ }
    }
}
