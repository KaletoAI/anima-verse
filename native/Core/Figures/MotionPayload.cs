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
    /// <summary>
    /// A HairDeck spring chain (<c>app/core/hair_motion.py</c>): its tips collide with the hair capsules
    /// (<see cref="Collision.HairChainCapsules"/>) and it swings on top of today's skin (HAIR CHAINS).
    /// </summary>
    public bool Hair { get; init; }
    /// <summary>
    /// Hair only: per chain joint (the group's bones and its carried, rigid ones) the body joints today's hair skin
    /// rides there, with their shares, in JSON order; a share that is no number reads NaN (JS <c>Number(x)</c> of an
    /// object) and is dropped by the reader. Null = absent.
    /// </summary>
    public IReadOnlyList<(string Bone, IReadOnlyList<(string Joint, double Share)>? Row)>? AnchorBlend { get; init; }
    /// <summary>Hair only: the body bone the chain hangs from (Head); its share of a row is how much of the swing shows.</summary>
    public string? AnchorFrom { get; init; }

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
            // JS truthiness of `group.hair`: a non-empty string or a non-zero number counts too.
            Hair = g.TryGetProperty("hair", out var h) && (h.ValueKind == JsonValueKind.True
                || (h.ValueKind == JsonValueKind.Number && h.GetDouble() != 0) || (h.ValueKind == JsonValueKind.String && h.GetString()!.Length > 0)),
            AnchorBlend = ParseAnchorBlend(g),
            AnchorFrom = g.TryGetProperty("anchor_from", out var af) && af.ValueKind == JsonValueKind.String ? af.GetString() : null,
        };
    }

    /// <summary>JS <c>Number(share)</c> for the JSON kinds a row can hold.</summary>
    private static double JsNumber(JsonElement v) => v.ValueKind switch
    {
        JsonValueKind.Number => v.GetDouble(),
        JsonValueKind.True => 1,
        JsonValueKind.False or JsonValueKind.Null => 0,
        JsonValueKind.String => v.GetString()!.Trim() is var s && s.Length == 0 ? 0
            : double.TryParse(s, System.Globalization.NumberStyles.Float, System.Globalization.CultureInfo.InvariantCulture, out var d) ? d : double.NaN,
        _ => double.NaN,
    };

    private static IReadOnlyList<(string, IReadOnlyList<(string, double)>?)>? ParseAnchorBlend(JsonElement g)
    {
        if (!g.TryGetProperty("anchor_blend", out var ab) || ab.ValueKind != JsonValueKind.Object) return null;
        var rows = new List<(string, IReadOnlyList<(string, double)>?)>();
        foreach (var row in ab.EnumerateObject())
        {
            // A row that is no object reads as no blend (`anchorEntries` returns undefined).
            IReadOnlyList<(string, double)>? entries = row.Value.ValueKind == JsonValueKind.Object
                ? row.Value.EnumerateObject().Select(e => (e.Name, JsNumber(e.Value))).ToList() : null;
            rows.Add((row.Name, entries));
        }
        return rows;
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
        if (Hair) o["hair"] = true;
        if (AnchorFrom is { } from) o["anchor_from"] = from;
        if (AnchorBlend is { } rows)
        {
            var ab = new JsonObject();
            foreach (var (bone, row) in rows)
            {
                var r = new JsonObject();
                foreach (var (joint, share) in row ?? Array.Empty<(string, double)>()) if (double.IsFinite(share)) r[joint] = share;
                ab[bone] = r;
            }
            o["anchor_blend"] = ab;
        }
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

    /// <summary>
    /// The factory's <c>groupBones</c>: every group's bones AND the joints of its <c>anchor_blend</c> rows (a hair
    /// group's carried joints count as its bones — a rows-only group activates the motion), normalised.
    /// </summary>
    public HashSet<string> MatchKeys()
        => Groups.SelectMany(g => g.Group.Bones.Concat(g.Group.AnchorBlend?.Select(r => r.Bone) ?? Enumerable.Empty<string>()))
                 .Select(BoneNames.Norm).ToHashSet();
}
