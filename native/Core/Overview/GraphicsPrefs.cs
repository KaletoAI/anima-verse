using System;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace AnimaNative.Overview;

/// <summary>
/// What <see cref="GraphicsPrefs.Check"/> answers: either the finished prefs, or WHICH field was refused —
/// <c>"antiAliasing"</c> (checked first) or <c>"shadows"</c>. The TS <c>GraphicsPrefsCheck</c> union.
/// </summary>
public readonly record struct GraphicsPrefsCheck(GraphicsPrefs? Prefs, string? Error)
{
    public bool Ok => Prefs is not null;
}

/// <summary>
/// Port of the graphics prefs of client3d/src/game/prefs.ts (Task 26d, the menu's Graphics tab): the anti-aliasing
/// level (<c>"off"</c> / <c>"2x"</c> / <c>"4x"</c>), sun shadows and render resolution. Stored under <see cref="Key"/>
/// (the HUD's localStorage, mirrored to <c>user://hud_storage.json</c>); the scene reads it at start with
/// <see cref="Load"/> and takes every change from the HUD's <c>applyGraphicsPrefs</c> through <see cref="Check"/>,
/// so a malformed message leaves the picture alone. Vectors: shared/test-vectors/graphics_prefs.json.
/// </summary>
public readonly record struct GraphicsPrefs(string AntiAliasing, bool Shadows, double? RenderScale = null)
{
    /// <summary><c>GRAPHICS_PREFS_KEY</c>.</summary>
    public const string Key = "av3d.view.graphics.v1";

    /// <summary><c>ANTI_ALIASING_LEVELS</c>, in menu order.</summary>
    public static readonly string[] Levels = { "off", "2x", "4x" };

    /// <summary><c>DEFAULT_GRAPHICS_PREFS</c>: 2× (4× costs ~6 ms/frame on the iGPU it was measured on), shadows on.</summary>
    public static readonly GraphicsPrefs Defaults = new("2x", true);

    /// <summary><c>antiAliasingOf</c>: a JSON string that is exactly one of the levels (case-sensitive), else null.</summary>
    private static string? LevelOf(JsonNode? node)
        => node is JsonValue v && v.GetValueKind() == JsonValueKind.String && Array.IndexOf(Levels, v.GetValue<string>()) >= 0
            ? v.GetValue<string>() : null;

    /// <summary><c>flag</c>: a real JSON boolean, else null (the string "false" and 0 are not one).</summary>
    private static bool? FlagOf(JsonNode? node)
        => node is JsonValue v && v.GetValueKind() is JsonValueKind.True or JsonValueKind.False ? v.GetValue<bool>() : null;

    /// <summary>
    /// <c>checkGraphicsPrefs(antiAliasing, shadows)</c>: values from outside (a bridge message) → the prefs, or the
    /// refused field. The level is checked first; missing or invalid renderScale defaults to auto.
    /// </summary>
    public static GraphicsPrefsCheck Check(JsonNode? antiAliasing, JsonNode? shadows, JsonNode? renderScale = null)
    {
        if (LevelOf(antiAliasing) is not { } aa) return new GraphicsPrefsCheck(null, "antiAliasing");
        if (FlagOf(shadows) is not { } on) return new GraphicsPrefsCheck(null, "shadows");
        return new GraphicsPrefsCheck(new GraphicsPrefs(aa, on, RenderScaleOf(renderScale)), null);
    }

    /// <summary>
    /// <c>loadGraphicsPrefs(raw)</c>: the stored string → complete prefs; never throws. Field by field — a bad level
    /// does not switch the shadows back on. Not JSON, not an object, an array, null: the defaults.
    /// </summary>
    public static GraphicsPrefs Load(string? raw)
    {
        if (string.IsNullOrEmpty(raw)) return Defaults;
        JsonNode? parsed;
        try
        {
            parsed = JsonNode.Parse(raw);
        }
        catch (JsonException)
        {
            return Defaults;
        }
        if (parsed is not JsonObject p) return Defaults;
        return new GraphicsPrefs(LevelOf(p["antiAliasing"]) ?? Defaults.AntiAliasing, FlagOf(p["shadows"]) ?? Defaults.Shadows, RenderScaleOf(p["renderScale"]));
    }

    /// <summary><c>saveGraphicsPrefs</c>: fixed key order, no spaces — the same bytes the HUD writes.</summary>
    public static string Save(GraphicsPrefs p)
        => new JsonObject { ["antiAliasing"] = p.AntiAliasing, ["shadows"] = p.Shadows, ["renderScale"] = RenderScaleJson(p.RenderScale) }.ToJsonString();

    public const int RenderPixelBudget = 1920 * 1080;
    // Null represents "auto"; fixed values stay JSON numbers on the shared wire.
    public static readonly double?[] RenderScales = { null, 1, 0.85, 0.75, 0.66, 0.5 };
    public static double? RenderScaleOf(JsonNode? node)
        => node is JsonValue v && v.GetValueKind() == JsonValueKind.Number
            && v.TryGetValue<double>(out var scale) && Array.IndexOf(RenderScales, (double?)scale) >= 0 ? scale : null;

    public static JsonNode RenderScaleJson(double? scale)
        => scale is { } s ? JsonValue.Create(s)! : JsonValue.Create("auto")!;

    public static double AutoRenderScale(double widthPx, double heightPx)
    {
        double pixels = widthPx * heightPx;
        if (pixels <= RenderPixelBudget) return 1;
        return Math.Clamp(Math.Floor(Math.Sqrt(RenderPixelBudget / pixels) * 20) / 20, 0.5, 1);
    }

    public static double EffectiveRenderScale(double? pref, double widthPx, double heightPx)
        => pref ?? AutoRenderScale(widthPx, heightPx);

    /// <summary><c>msaaSamplesOf</c>: the MSAA sample count a level asks for (0 = disabled).</summary>
    public static int MsaaSamplesOf(string antiAliasing) => antiAliasing switch
    {
        "4x" => 4,
        "2x" => 2,
        _ => 0,
    };

    /// <summary><c>browserAntialias</c> (the browser's one bit; ported for the vector file, unused natively).</summary>
    public static bool BrowserAntialias(GraphicsPrefs p) => p.AntiAliasing != "off";

    /// <summary><c>pickBrowserAntiAliasing</c> (the browser menu's Off / On; ported for the vector file, unused natively).</summary>
    public static string PickBrowserAntiAliasing(bool on, string current)
        => !on ? "off" : current == "off" ? Defaults.AntiAliasing : current;
}
