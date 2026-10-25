using System;
using System.Text.Json;
using System.Text.Json.Nodes;
using AnimaNative.Scatter;

namespace AnimaNative.Overview;

/// <summary>
/// What <see cref="ScatterPrefs.Check"/> answers: either the finished prefs, or why they were not
/// taken — <c>"number"</c> (a value that is no finite number) or <c>"order"</c> (near &lt; far &lt;
/// cull does not hold after clamping). The TS <c>ScatterPrefsCheck</c> union.
/// </summary>
public readonly record struct ScatterPrefsCheck(ScatterPrefs? Prefs, string? Error)
{
    public bool Ok => Prefs is not null;
}

/// <summary>
/// Port of the scatter detail distances of client3d/src/game/prefs.ts: three metre values
/// (full mesh up to near, cheap mesh up to far, thinned out to cull). In the native client the
/// HUD's menu checks what the player typed and sends <c>applyScatterPrefs</c> over the bridge;
/// the scene runs the same <see cref="Check"/> on that message before it touches the LOD, so a
/// malformed message cannot invert the band. Vectors: shared/test-vectors/overview_hud.json [J3]/[J4].
/// </summary>
public readonly record struct ScatterPrefs(double ScatterNearM, double ScatterFarM, double ScatterCullM)
{
    /// <summary>Lowest distance a pref may be (metres).</summary>
    public const double MinM = 5;
    /// <summary>Highest distance a pref may be (metres).</summary>
    public const double MaxM = 2000;

    /// <summary><c>DEFAULT_SCATTER_PREFS</c> — the same three numbers as <c>SCATTER_LOD_DEFAULTS</c>.</summary>
    public static readonly ScatterPrefs Defaults = new(35, 45, 120);

    /// <summary>A distance out of range is clamped, never refused.</summary>
    private static double ClampM(double v) => Math.Min(MaxM, Math.Max(MinM, v));

    /// <summary>near &lt; far &lt; cull, strictly.</summary>
    public bool Ordered => ScatterNearM < ScatterFarM && ScatterFarM < ScatterCullM;

    /// <summary>
    /// <c>checkScatterPrefs</c>: each value must be a finite number (null stands for the TS's
    /// non-number), is clamped to [<see cref="MinM"/>, <see cref="MaxM"/>], and the clamped triple
    /// must climb strictly — so 2500 / 3000 / 4000 collide at the ceiling and are refused.
    /// </summary>
    public static ScatterPrefsCheck Check(double? near, double? far, double? cull)
    {
        Span<double> metres = stackalloc double[3];
        double?[] raw = { near, far, cull };
        for (int i = 0; i < 3; i++)
        {
            if (raw[i] is not double v || !double.IsFinite(v)) return new ScatterPrefsCheck(null, "number");
            metres[i] = ClampM(v);
        }
        var prefs = new ScatterPrefs(metres[0], metres[1], metres[2]);
        return prefs.Ordered ? new ScatterPrefsCheck(prefs, null) : new ScatterPrefsCheck(null, "order");
    }

    /// <summary>
    /// <c>loadScatterPrefs(raw)</c>: the stored string (<c>av3d.view.scatter.v1</c>) → three usable distances; never
    /// throws, never half a setting. Field by field first (a finite NUMBER, clamped; anything else is that field's
    /// default), then the triple as a whole: one that does not climb falls back to <see cref="Defaults"/> completely.
    /// Not JSON, not an object, an array, null: the defaults.
    /// </summary>
    public static ScatterPrefs Load(string? raw)
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
        static double Distance(JsonNode? node, double fallback)
            => node is JsonValue v && v.GetValueKind() == JsonValueKind.Number
               && v.TryGetValue<double>(out var d) && double.IsFinite(d) ? ClampM(d) : fallback;
        var prefs = new ScatterPrefs(Distance(p["scatterNearM"], Defaults.ScatterNearM),
                                     Distance(p["scatterFarM"], Defaults.ScatterFarM),
                                     Distance(p["scatterCullM"], Defaults.ScatterCullM));
        return prefs.Ordered ? prefs : Defaults;
    }

    /// <summary><c>scatterLodCfgOf</c>: the stored fields → the cfg the LOD maths takes.</summary>
    public static ScatterLodCfg LodCfgOf(ScatterPrefs p) => new(p.ScatterNearM, p.ScatterFarM, p.ScatterCullM);
}
