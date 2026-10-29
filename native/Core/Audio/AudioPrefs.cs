using System;
using System.Text.Json;
using System.Globalization;
using System.Text.Json.Nodes;

namespace AnimaNative.Audio;

/// <summary>Task 59: prefs.ts field-by-field parsing, including zero volume and strict boolean/string types.
/// The HUD owns ttsOn and persistence; the scene reads the same av3d.audio.v1 storage mirror at boot.</summary>
public sealed record AudioPrefs(double Master = .8, double Music = .5, double Ambient = .6, double Tts = 1,
                                bool MusicOn = true, bool AmbientOn = true, string TtsOn = "auto")
{
    public const string Key = "av3d.audio.v1";
    public static readonly AudioPrefs Defaults = new();
    public static AudioPrefs Load(string? raw)
    {
        try
        {
            using var document = JsonDocument.Parse(raw ?? "null");
            if (document.RootElement.ValueKind != JsonValueKind.Object) return Defaults;
            // JSON.parse accepts duplicate properties, last value wins. JsonObject materialization throws,
            // so select the known fields through JsonDocument before constructing the typed prefs (Task 59).
            var fields = new JsonObject();
            foreach (var key in new[] { "master", "music", "ambient", "tts", "musicOn", "ambientOn", "ttsOn" })
                if (document.RootElement.TryGetProperty(key, out var value)) fields[key] = JsonNode.Parse(value.GetRawText());
            return From(fields);
        }
        catch (JsonException) { return Defaults; }
    }
    public static AudioPrefs From(JsonNode? node)
    {
        if (node is not JsonObject p) return Defaults;
        double Volume(string key, double fallback) => TryVolume(p[key], out var n)
            ? AudioMath.ClampVolume(n) : fallback;
        bool Flag(string key) => p[key] is JsonValue v && v.TryGetValue<bool>(out var b) ? b : true;
        string tts = p["ttsOn"] is JsonValue s && s.TryGetValue<string>(out var mode) && mode is "auto" or "on" or "off" ? mode : "auto";
        return new(Volume("master", .8), Volume("music", .5), Volume("ambient", .6), Volume("tts", 1), Flag("musicOn"), Flag("ambientOn"), tts);
    }
    /// <summary>Task 59: accept numeric JSON, including programmatic integer nodes; reject strings and non-finite values.</summary>
    public static bool TryVolume(JsonNode? node, out double value)
    {
        value = 0;
        return node is JsonValue v && (v.TryGetValue<double>(out value)
            || double.TryParse(v.ToJsonString(), NumberStyles.Float, CultureInfo.InvariantCulture, out value)) && double.IsFinite(value);
    }
    public JsonObject ToJson() => new() { ["master"] = Master, ["music"] = Music, ["ambient"] = Ambient, ["tts"] = Tts,
        ["musicOn"] = MusicOn, ["ambientOn"] = AmbientOn, ["ttsOn"] = TtsOn };
    public string Save() => ToJson().ToJsonString();
}

/// <summary>Task 59: changing a target cancels its old ramp at its current gain; repeated targets do not postpone it.</summary>
public sealed class VolumeRamp(double initial)
{
    private double _from = initial, _target = initial, _at = double.NegativeInfinity;
    public double At(double now) => AudioMath.RampGainAt(_from, _target, _at, now);
    public void Set(double target, double now)
    {
        target = AudioMath.ClampVolume(target);
        if (target == _target) return;
        _from = At(now); _target = target; _at = now;
    }
}
