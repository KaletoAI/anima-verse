using System.Text.Json;
using AnimaNative.Scatter;
using AnimaNative.Scene;

namespace AnimaNative.World;

/// <summary>Task 40 (E4-T5), worldProps.ts: the landmark bands, standing bottom and § B2 scene spec.
/// Kept Godot-free so all world_props.json cases exercise the production placement inputs.</summary>
public static class WorldPropMath
{
    public const double LodScale = 3;
    public static ScatterLodCfg LodCfg(ScatterLodCfg c) => new(c.NearM * LodScale, c.FarM * LodScale, c.CullM * LodScale);
    public static double Bottom(JsonElement wp, double groundY)
        => groundY + FiniteOffset(wp, "offset_y") + FiniteOffset(wp, "ground_offset_m");
    private static double FiniteOffset(JsonElement wp, string key)
    {
        double n = wp.TryGetProperty(key, out var v) ? Scene.Js.Number(v) : 0;
        return double.IsFinite(n) ? n : 0;
    }
    public static SceneModelSpec SceneSpec(JsonElement wp, double bottom)
        => ScenePayload.ParseModel(wp) with
        {
            Role = "prop", Id = Json.Str(wp, "prop_id"), Level = 0, Measure = "xyz",
            MaxM = Scene.Js.Or(Json.Num(wp, "max_m"), 1), AnchorX = Json.Num(wp, "x"), AnchorZ = Json.Num(wp, "z"),
            BottomY = bottom, SizeM = null,
        };
}
