using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json.Nodes;

namespace AnimaNative.Audio;

/// <summary>Task 59: pure soundtrack.ts rules consumed by all audio.json groups. Task 60 owns the live driver.</summary>
public sealed record AudioManifest(string[] Day, string[] Night, Dictionary<string, string[]> Ambient)
{
    public static AudioManifest Read(JsonNode? raw)
    {
        static string[] Urls(JsonNode? n) => n is JsonArray a ? a.OfType<JsonValue>()
            .Where(v => v.TryGetValue<string>(out var s) && s.Length > 0).Select(v => v.GetValue<string>()).ToArray() : [];
        var music = (raw as JsonObject)?["music"] as JsonObject;
        var ambient = new Dictionary<string, string[]>();
        if ((raw as JsonObject)?["ambient"] is JsonObject a)
            foreach (var (key, value) in a)
                if (Urls(value) is { Length: > 0 } files) ambient[key] = files;
        return new(Urls(music?["day"]), Urls(music?["night"]), ambient);
    }
    public string[] PickMusic(bool night) => night ? Night : Day;
    public string[] PickAmbient(string terrain)
    {
        if (terrain.Length == 0) return [];
        if (Ambient.TryGetValue(terrain, out var exact)) return exact;
        return Ambient.FirstOrDefault(p => p.Key.ToLowerInvariant() == terrain.ToLowerInvariant()).Value ?? [];
    }
    public JsonObject ToJson()
    {
        var ambient = new JsonObject();
        foreach (var (key, urls) in Ambient) ambient[key] = new JsonArray(urls.Select(s => (JsonNode?)JsonValue.Create(s)).ToArray());
        return new() { ["music"] = new JsonObject { ["day"] = new JsonArray(Day.Select(s => (JsonNode?)JsonValue.Create(s)).ToArray()),
            ["night"] = new JsonArray(Night.Select(s => (JsonNode?)JsonValue.Create(s)).ToArray()) }, ["ambient"] = ambient };
    }
}

/// <summary>Task 59 / audio.json: hysteresis, whose terrain, and the first-terrain exception to the five-second hold.</summary>
public static class SoundtrackRules
{
    public const double NightOn = .8, NightOff = .2, HoldMs = 5000;
    public static bool NightForMusic(bool previous, double factor) => factor > NightOn || (factor >= NightOff || double.IsNaN(factor)) && previous;
    public static string AmbientTerrainFor(string mode, (double X, double Z)? avatar, (double X, double Z)? camera,
        Func<double, double, string> terrainAt)
    {
        var at = mode == "embodied" ? avatar : camera;
        return at is { } p ? terrainAt(p.X, p.Z).Trim().ToLowerInvariant() : "";
    }
    public static TerrainSwitch Switch(TerrainSwitch state, string candidate, double now, double holdMs = HoldMs)
    {
        if (!state.Started) return candidate.Length == 0 ? state : new(candidate, candidate, now, true);
        if (candidate == state.Applied) return new(state.Applied, state.Applied, now, true);
        if (candidate != state.Pending) return new(state.Applied, candidate, now, true);
        return now - state.Since >= holdMs ? new(candidate, candidate, now, true) : state;
    }
}

/// <summary>Task 59: immutable debounce state, with Started distinguishing initial silence from applied silence.</summary>
public sealed record TerrainSwitch(string Applied = "", string Pending = "", double Since = 0, bool Started = false);
