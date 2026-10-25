using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
using System.Text.Json.Nodes;
using AnimaNative.Scatter;
using AnimaNative.Tests.Vectors;

namespace AnimaNative.Tests;

/// <summary>
/// Shape adapters between the TS shapes of shared/test-vectors/scatter.json and the C# types of
/// <see cref="ScatterMath"/> / <see cref="ScatterLod"/>. They translate shapes only and never
/// reinterpret a value. Conventions (shared/test-vectors/README.md, header of
/// client3d/scripts/smoke_scatter_math.mjs):
/// <list type="bullet">
/// <item>An omitted trailing argument or option key is JS <c>undefined</c>, JSON <c>null</c> is JS
/// <c>null</c>; both mean "not given" and become C# <c>null</c>. Where the C# parameter is a
/// non-nullable <c>double</c> (the TS parameter is a plain <c>number</c>), "not given" becomes
/// <c>NaN</c> — the reading of <c>Number(undefined)</c> that the port documents for absent values.</item>
/// <item>A sampler's <c>rng</c> is a list of numbers, fed in order; drawing past its end throws.</item>
/// <item>An unknown option key or a surplus argument throws: a shape the adapter does not know
/// must fail the case, never be dropped silently.</item>
/// </list>
/// </summary>
internal static class ScatterVectorAdapters
{
    // ---- arguments ----------------------------------------------------------------------------

    /// <summary>Throw unless the call has between <paramref name="min"/> and <paramref name="max"/> arguments.</summary>
    public static JsonArray Arity(JsonArray args, int min, int max)
        => args.Count >= min && args.Count <= max
            ? args
            : throw new ArgumentException($"expected {min}..{max} arguments, got {args.Count}");

    /// <summary>Argument <paramref name="i"/>; an omitted trailing argument reads as null.</summary>
    public static JsonNode? Arg(JsonArray args, int i) => i < args.Count ? args[i] : null;

    /// <summary>A number, or NaN when not given (a non-nullable C# double, see the class remarks).</summary>
    public static double NumOrNaN(JsonNode? node) => node is null ? double.NaN : VectorCompare.Num(node);

    /// <summary>A number that the C# side types as an integer; a fractional or out-of-range value throws.</summary>
    public static int Int(JsonNode? node)
    {
        double d = VectorCompare.Num(node);
        return d == Math.Floor(d) && d >= int.MinValue && d <= int.MaxValue
            ? (int)d
            : throw new ArgumentException($"expected an integer, got {VectorCompare.Show(node)}");
    }

    public static int? IntOrNull(JsonNode? node) => node is null ? null : Int(node);

    /// <summary>The LOD tier (0 full, 1 low, 2 hidden) as the C# byte.</summary>
    public static byte Tier(JsonNode? node)
    {
        int t = Int(node);
        return t is >= 0 and <= 2 ? (byte)t : throw new ArgumentException($"expected a tier 0..2, got {t}");
    }

    public static string Str(JsonNode? node)
        => node is JsonValue v && v.TryGetValue(out JsonElement el) && el.ValueKind == JsonValueKind.String
            ? el.GetString()!
            : throw new ArgumentException($"expected a string, got {VectorCompare.Show(node)}");

    public static string? StrOrNull(JsonNode? node) => node is null ? null : Str(node);

    // ---- shapes -------------------------------------------------------------------------------

    /// <summary><c>[x, z]</c> → <see cref="P2"/>.</summary>
    public static P2 Point(JsonNode? node)
        => node is JsonArray xz && xz.Count == 2
            ? new P2(VectorCompare.Num(xz[0]), VectorCompare.Num(xz[1]))
            : throw new ArgumentException($"expected a point [x, z], got {VectorCompare.Show(node)}");

    /// <summary><c>[[x, z], …]</c> → points.</summary>
    public static List<P2> Ring(JsonNode? node)
        => node is JsonArray a
            ? a.Select(Point).ToList()
            : throw new ArgumentException($"expected a ring, got {VectorCompare.Show(node)}");

    public static List<P2>? RingOrNull(JsonNode? node) => node is null ? null : Ring(node);

    /// <summary>A TS <c>ScatterFootprint</c> <c>{points}</c> → its points (null when the key is absent).</summary>
    public static List<P2>? Footprint(JsonNode? node)
    {
        var o = Object(node, "footprint", "points");
        return RingOrNull(o["points"]);
    }

    /// <summary>A list of footprints <c>[{points}, …]</c>.</summary>
    public static List<IReadOnlyList<P2>>? FootprintsOrNull(JsonNode? node)
        => node is null ? null : List(node, "footprints").Select(n => (IReadOnlyList<P2>)Footprint(n)!).ToList();

    /// <summary>A list of rings <c>[[[x, z], …], …]</c>.</summary>
    public static List<IReadOnlyList<P2>>? RingsOrNull(JsonNode? node)
        => node is null ? null : List(node, "occluders").Select(n => (IReadOnlyList<P2>)Ring(n)).ToList();

    public static JsonArray PointsJson(IEnumerable<P2> pts)
        => new(pts.Select(p => (JsonNode?)new JsonArray(p.X, p.Z)).ToArray());

    /// <summary>A TS <c>ScatterLodCfg</c> <c>{nearM, farM, cullM}</c>.</summary>
    public static ScatterLodCfg Cfg(JsonNode? node)
    {
        var o = Object(node, "LOD cfg", "nearM", "farM", "cullM");
        return new ScatterLodCfg(VectorCompare.Num(o["nearM"]), VectorCompare.Num(o["farM"]), VectorCompare.Num(o["cullM"]));
    }

    /// <summary>
    /// <c>propBoxFootprint(box)</c>: the TS <c>ScatterPropBox</c> <c>{x, z, yaw_deg, half_w, half_d}</c>
    /// spread over the C# parameters; a key that is not given is <c>NaN</c>, as <c>Number(undefined)</c>
    /// reads it in the TS. <c>id</c> (the server row's id, carried by the fixture) is not read by the TS
    /// function and is not passed. The result is <c>{points}</c> or null.
    /// </summary>
    public static JsonNode? PropBoxFootprint(JsonNode? node)
    {
        var o = Object(node, "prop box", "id", "x", "z", "yaw_deg", "half_w", "half_d");
        var pts = ScatterMath.PropBoxFootprint(
            NumOrNaN(o["x"]), NumOrNaN(o["z"]), NumOrNaN(o["yaw_deg"]), NumOrNaN(o["half_w"]), NumOrNaN(o["half_d"]));
        return pts is null ? null : new JsonObject { ["points"] = PointsJson(pts) };
    }

    /// <summary><c>propGroundFit</c> result shape <c>{scale, offsetY}</c>.</summary>
    public static JsonObject GroundFitJson((double Scale, double OffsetY) fit)
        => new() { ["scale"] = fit.Scale, ["offsetY"] = fit.OffsetY };

    /// <summary>A TS <c>ScatterViewCone</c> <c>{fwdX, fwdZ, cosHalf}</c>.</summary>
    public static JsonObject ViewConeJson(ScatterViewCone c)
        => new() { ["fwdX"] = c.FwdX, ["fwdZ"] = c.FwdZ, ["cosHalf"] = c.CosHalf };

    /// <summary>
    /// A TS <c>ScatterInstance</c> list. <c>variant</c> is present only where the C# value has one
    /// (the TS key is ABSENT, not null, when the caller asked for no mix).
    /// </summary>
    public static JsonArray InstancesJson(IEnumerable<ScatterInstance> list)
        => new(list.Select(p =>
        {
            var o = new JsonObject { ["x"] = p.X, ["z"] = p.Z, ["yaw"] = p.Yaw };
            if (p.Variant is int v) o["variant"] = v;
            return (JsonNode?)o;
        }).ToArray());

    // ---- sampler options ----------------------------------------------------------------------

    private static readonly string[] SampleKeys =
    {
        "ring", "areaM2", "densityPer100m2", "seed", "footprints", "clearM", "occluders", "minSpacingM",
        "maxPoints", "variantCount", "variant", "triesPerPoint", "rng", "yawMode", "yawDeg",
    };

    private static readonly string[] CellKeys =
    {
        "ring", "cx", "cz", "densityPer100m2", "seed", "footprints", "clearM", "occluders", "minSpacingM",
        "maxPoints", "variantCount", "variant", "rng", "yawMode", "yawDeg",
    };

    /// <summary>The TS <c>ScatterSampleOptions</c> object → <see cref="ScatterMath.SampleOptions"/>.</summary>
    public static ScatterMath.SampleOptions SampleOptions(JsonNode? node)
    {
        var o = Object(node, "sampler options", SampleKeys);
        return new ScatterMath.SampleOptions
        {
            Ring = RingOrNull(o["ring"]) ?? new List<P2>(),
            AreaM2 = NumOrNaN(o["areaM2"]),
            DensityPer100m2 = NumOrNaN(o["densityPer100m2"]),
            Seed = Str(o["seed"]),
            Footprints = FootprintsOrNull(o["footprints"]),
            ClearM = VectorCompare.NumOrNull(o["clearM"]),
            Occluders = RingsOrNull(o["occluders"]),
            MinSpacingM = VectorCompare.NumOrNull(o["minSpacingM"]),
            MaxPoints = IntOrNull(o["maxPoints"]),
            VariantCount = VectorCompare.NumOrNull(o["variantCount"]),
            Variant = VectorCompare.NumOrNull(o["variant"]),
            TriesPerPoint = IntOrNull(o["triesPerPoint"]),
            Rng = Feed(o["rng"]),
            YawMode = StrOrNull(o["yawMode"]),
            YawDeg = VectorCompare.NumOrNull(o["yawDeg"]),
        };
    }

    /// <summary>The TS <c>ScatterCellOptions</c> object → <see cref="ScatterMath.CellOptions"/>.</summary>
    public static ScatterMath.CellOptions CellOptions(JsonNode? node)
    {
        var o = Object(node, "cell sampler options", CellKeys);
        return new ScatterMath.CellOptions
        {
            Ring = RingOrNull(o["ring"]) ?? new List<P2>(),
            Cx = Int(o["cx"]),
            Cz = Int(o["cz"]),
            DensityPer100m2 = NumOrNaN(o["densityPer100m2"]),
            Seed = Str(o["seed"]),
            Footprints = FootprintsOrNull(o["footprints"]),
            ClearM = VectorCompare.NumOrNull(o["clearM"]),
            Occluders = RingsOrNull(o["occluders"]),
            MinSpacingM = VectorCompare.NumOrNull(o["minSpacingM"]),
            MaxPoints = IntOrNull(o["maxPoints"]),
            VariantCount = VectorCompare.NumOrNull(o["variantCount"]),
            Variant = VectorCompare.NumOrNull(o["variant"]),
            Rng = Feed(o["rng"]),
            YawMode = StrOrNull(o["yawMode"]),
            YawDeg = VectorCompare.NumOrNull(o["yawDeg"]),
        };
    }

    /// <summary>
    /// The smoke's <c>stream()</c>: the listed numbers in order, then a throw — running past the end
    /// is a broken expectation, never a wrap-around. Not given → null (the sampler seeds its own).
    /// </summary>
    public static Func<double>? Feed(JsonNode? node)
    {
        if (node is null) return null;
        var values = VectorCompare.NumList(node);
        int i = 0;
        return () =>
        {
            if (i >= values.Count) throw new InvalidOperationException("scatter drew more numbers than the case feeds");
            return values[i++];
        };
    }

    // ---- helpers ------------------------------------------------------------------------------

    private static JsonObject Object(JsonNode? node, string what, params string[] keys)
    {
        if (node is not JsonObject o) throw new ArgumentException($"expected a {what} object, got {VectorCompare.Show(node)}");
        var unknown = o.Select(kv => kv.Key).Where(k => !keys.Contains(k)).ToList();
        if (unknown.Count > 0) throw new ArgumentException($"{what}: unknown key(s) {string.Join(", ", unknown)}");
        return o;
    }

    private static JsonArray List(JsonNode? node, string what)
        => node as JsonArray ?? throw new ArgumentException($"expected a {what} list, got {VectorCompare.Show(node)}");
}
