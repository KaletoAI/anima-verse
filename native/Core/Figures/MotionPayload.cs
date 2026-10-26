using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace AnimaNative.Figures;

/// <summary>
/// One resolved motion group of the server's motion payload (secondaryMotion.ts <c>MotionGroup</c>; worldmap
/// <c>characters[].motion.groups</c> / model3d <c>motion.groups</c>, built by <c>extension_rig.motion_payload</c>).
/// Every number the browser reads with a fallback (<c>?? x</c>) is nullable here, so the fallback stays at the reader
/// exactly as in the browser; a number the browser reads WITHOUT a fallback is NaN when absent (JS <c>undefined</c>
/// in arithmetic).
/// </summary>
public sealed record MotionGroup
{
    public IReadOnlyList<string> Bones { get; init; } = Array.Empty<string>();
    public double? FreqHz { get; init; }
    public double? Zeta { get; init; }
    public double? Spill { get; init; }
    public double? Translate { get; init; }
    public double? Flatten { get; init; }
    public double? Stretch { get; init; }
    public double? Spread { get; init; }
    public double? FlattenFloor { get; init; }
    public double? Length { get; init; }
    public double? Girth { get; init; }
    /// <summary><c>'centroid' | 'bone'</c>; null = centroid.</summary>
    public string? ScaleAxis { get; init; }
    public double? RigidTail { get; init; }
    public double? GravityScale { get; init; }
    public double? SagMaxDeg { get; init; }
    public double? SpillMaxDeg { get; init; }
    public double? HeadSag { get; init; }
    public double? Gravity { get; init; }
    public (double X, double Y, double Z)? AxisGain { get; init; }
    public double? Gain { get; init; }
    public double MaxDeg { get; init; } = double.NaN;
    public (double Min, double Max) Squash { get; init; } = (double.NaN, double.NaN);
    public double RestDeg { get; init; } = double.NaN;
    public double RestMaxDeg { get; init; } = double.NaN;
    public double? StraightenDeg { get; init; }
    public double? FreetextClothingGain { get; init; }

    /// <summary>The fields <c>blendMotionParams</c> eases (secondaryMotion.ts <c>BLENDED_FIELDS</c>), in its order.</summary>
    public static readonly string[] BlendedFields =
        { "gravity", "freq_hz", "zeta", "gain", "flatten", "stretch", "spread", "flatten_floor", "spill", "translate", "head_sag", "length", "girth" };

    public double? Get(string field) => field switch
    {
        "gravity" => Gravity, "freq_hz" => FreqHz, "zeta" => Zeta, "gain" => Gain, "flatten" => Flatten, "stretch" => Stretch,
        "spread" => Spread, "flatten_floor" => FlattenFloor, "spill" => Spill, "translate" => Translate, "head_sag" => HeadSag,
        "length" => Length, "girth" => Girth,
        _ => throw new ArgumentException($"not a blended motion field: {field}"),
    };

    public MotionGroup With(string field, double v) => field switch
    {
        "gravity" => this with { Gravity = v }, "freq_hz" => this with { FreqHz = v }, "zeta" => this with { Zeta = v },
        "gain" => this with { Gain = v }, "flatten" => this with { Flatten = v }, "stretch" => this with { Stretch = v },
        "spread" => this with { Spread = v }, "flatten_floor" => this with { FlattenFloor = v }, "spill" => this with { Spill = v },
        "translate" => this with { Translate = v }, "head_sag" => this with { HeadSag = v }, "length" => this with { Length = v },
        "girth" => this with { Girth = v },
        _ => throw new ArgumentException($"not a blended motion field: {field}"),
    };

    /// <summary>A group from its JSON object (unknown keys ignored, non-numbers absent).</summary>
    public static MotionGroup Parse(JsonElement g)
    {
        double? Num(string k) => g.TryGetProperty(k, out var v) && v.ValueKind == JsonValueKind.Number ? v.GetDouble() : null;
        (double, double, double)? axis = null;
        if (g.TryGetProperty("axis_gain", out var ag) && ag.ValueKind == JsonValueKind.Array && ag.GetArrayLength() >= 3)
            axis = (ag[0].GetDouble(), ag[1].GetDouble(), ag[2].GetDouble());
        var squash = (double.NaN, double.NaN);
        if (g.TryGetProperty("squash", out var sq) && sq.ValueKind == JsonValueKind.Array && sq.GetArrayLength() >= 2)
            squash = (sq[0].GetDouble(), sq[1].GetDouble());
        var bones = g.TryGetProperty("bones", out var b) && b.ValueKind == JsonValueKind.Array
            ? b.EnumerateArray().Where(e => e.ValueKind == JsonValueKind.String).Select(e => e.GetString()!).ToList()
            : new List<string>();
        return new MotionGroup
        {
            Bones = bones, FreqHz = Num("freq_hz"), Zeta = Num("zeta"), Spill = Num("spill"), Translate = Num("translate"),
            Flatten = Num("flatten"), Stretch = Num("stretch"), Spread = Num("spread"), FlattenFloor = Num("flatten_floor"),
            Length = Num("length"), Girth = Num("girth"),
            ScaleAxis = g.TryGetProperty("scale_axis", out var sa) && sa.ValueKind == JsonValueKind.String ? sa.GetString() : null,
            RigidTail = Num("rigid_tail"), GravityScale = Num("gravity_scale"), SagMaxDeg = Num("sag_max_deg"),
            SpillMaxDeg = Num("spill_max_deg"), HeadSag = Num("head_sag"), Gravity = Num("gravity"), AxisGain = axis,
            Gain = Num("gain"), MaxDeg = Num("max_deg") ?? double.NaN, Squash = squash, RestDeg = Num("rest_deg") ?? double.NaN,
            RestMaxDeg = Num("rest_max_deg") ?? double.NaN, StraightenDeg = Num("straighten_deg"),
            FreetextClothingGain = Num("freetext_clothing_gain"),
        };
    }

    /// <summary>The group as JSON (absent fields left out) — the vector adapters compare its keys.</summary>
    public JsonObject ToJson()
    {
        var o = new JsonObject { ["bones"] = new JsonArray(Bones.Select(x => (JsonNode?)x).ToArray()) };
        void Put(string k, double? v) { if (v is { } d) o[k] = d; }
        Put("freq_hz", FreqHz); Put("zeta", Zeta); Put("spill", Spill); Put("translate", Translate); Put("flatten", Flatten);
        Put("stretch", Stretch); Put("spread", Spread); Put("flatten_floor", FlattenFloor); Put("length", Length);
        Put("girth", Girth); Put("rigid_tail", RigidTail); Put("gravity_scale", GravityScale); Put("sag_max_deg", SagMaxDeg);
        Put("spill_max_deg", SpillMaxDeg); Put("head_sag", HeadSag); Put("gravity", Gravity); Put("gain", Gain);
        Put("straighten_deg", StraightenDeg); Put("freetext_clothing_gain", FreetextClothingGain);
        if (!double.IsNaN(MaxDeg)) o["max_deg"] = MaxDeg;
        if (!double.IsNaN(RestDeg)) o["rest_deg"] = RestDeg;
        if (!double.IsNaN(RestMaxDeg)) o["rest_max_deg"] = RestMaxDeg;
        if (!double.IsNaN(Squash.Min)) o["squash"] = new JsonArray(Squash.Min, Squash.Max);
        if (AxisGain is { } a) o["axis_gain"] = new JsonArray(a.X, a.Y, a.Z);
        if (ScaleAxis is { } s) o["scale_axis"] = s;
        return o;
    }
}

/// <summary>
/// The resolved motion payload (<c>SecondaryMotionPayload</c>: <c>{rev, groups}</c>); groups keep the JSON order
/// (JS <c>Object.values</c>).
/// </summary>
public sealed record MotionPayload(string Rev, IReadOnlyList<(string Name, MotionGroup Group)> Groups)
{
    /// <summary>A payload object, or null when it is not one (absent / null field).</summary>
    public static MotionPayload? Parse(JsonElement p)
    {
        if (p.ValueKind != JsonValueKind.Object) return null;
        var rev = p.TryGetProperty("rev", out var r) && r.ValueKind == JsonValueKind.String ? r.GetString()! : "";
        var groups = new List<(string, MotionGroup)>();
        if (p.TryGetProperty("groups", out var gs) && gs.ValueKind == JsonValueKind.Object)
            foreach (var g in gs.EnumerateObject())
                if (g.Value.ValueKind == JsonValueKind.Object) groups.Add((g.Name, MotionGroup.Parse(g.Value)));
        return new MotionPayload(rev, groups);
    }

    /// <summary>The <c>motion</c> property of an object (worldmap row / model3d answer); null when absent or not an object.</summary>
    public static MotionPayload? Of(JsonElement owner)
        => owner.ValueKind == JsonValueKind.Object && owner.TryGetProperty("motion", out var m) ? Parse(m) : null;

    /// <summary>Every bone name of every group, normalised (<see cref="BoneNames.Norm"/>).</summary>
    public HashSet<string> BoneKeys() => Groups.SelectMany(g => g.Group.Bones.Select(BoneNames.Norm)).ToHashSet();
}
