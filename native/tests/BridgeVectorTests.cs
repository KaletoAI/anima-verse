using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
using System.Text.Json.Nodes;
using AnimaNative.Figures;
using AnimaNative.Overview;
using AnimaNative.Scatter;
using AnimaNative.Scene;
using AnimaNative.Tests.Vectors;
using Xunit;
using static AnimaNative.Tests.ScatterVectorAdapters;

namespace AnimaNative.Tests;

/// <summary>
/// The adapters of client3d/scripts/bridgeVectorDispatch.mjs (Task 31), mirrored for the native ports. Non-finite
/// INPUTS are <c>{"$number": "NaN" | "Infinity" | "-Infinity"}</c>; a <c>fields</c> argument is a property path
/// (<see cref="E3VectorAdapters.Path"/>: keys, indices, <c>length</c>).
/// </summary>
internal static class BridgeVectorAdapters
{
    /// <summary>A number argument, decoding the non-finite tags.</summary>
    public static double N(JsonNode? n)
    {
        if (n is JsonObject o && o.TryGetPropertyValue("$number", out var tag))
            return Str(tag) switch
            {
                "NaN" => double.NaN,
                "Infinity" => double.PositiveInfinity,
                "-Infinity" => double.NegativeInfinity,
                var s => throw new ArgumentException($"unknown number tag {s}"),
            };
        return VectorCompare.Num(n);
    }

    public static V3 Pt(JsonNode? n)
    {
        var a = (JsonArray)n!;
        return new V3(N(a[0]), N(a[1]), N(a[2]));
    }

    public static JsonArray Arr(V3 v) => new(v.X, v.Y, v.Z);

    public static JsonArray Nums(IEnumerable<double> values) => new(values.Select(v => (JsonNode?)v).ToArray());

    public static List<double> NumList(JsonNode? n) => ((JsonArray)n!).Select(N).ToList();

    /// <summary>A tracks object name → [[x, y, z], …] in key order.</summary>
    public static Dictionary<string, V3[]> Tracks(JsonNode? n)
        => ((JsonObject)n!).ToDictionary(e => e.Key, e => ((JsonArray)e.Value!).Select(Pt).ToArray());

    public static Dictionary<string, double> Numbers(JsonNode? n)
        => ((JsonObject)n!).ToDictionary(e => e.Key, e => N(e.Value));

    public static Dictionary<string, double[]> Weights(JsonNode? n)
        => ((JsonObject)n!).ToDictionary(e => e.Key, e => NumList(e.Value).ToArray());

    public static JsonArray PathJson(IEnumerable<(double X, double Z)> path)
        => new(path.Select(p => (JsonNode?)new JsonArray(p.X, p.Z)).ToArray());

    public static JsonObject XZ(double x, double z) => new() { ["x"] = x, ["z"] = z };

    public static P2 P2Of(JsonNode? n) => new(N(n!["x"]), N(n["z"]));

    public static float[] Floats(JsonNode? n) => NumList(n).Select(v => (float)v).ToArray();

    public static RootPath PathOf(JsonNode? n) => new(Floats(n!["times"]), Floats(n["xz"]));

    public static RootTurn TurnOf(JsonNode? n)
    {
        var pivot = n!["pivot"] is JsonArray p ? Pt(p) : V3.Zero;
        return new RootTurn(Floats(n["times"]), Floats(n["yaw"]), pivot);
    }

    /// <summary><c>constant(name)</c> over every exported constant of the Task 31 modules; unknown names throw.</summary>
    public static JsonNode? Constant(string name) => name switch
    {
        "BAND_LO_CM" => FootLock.BandLoCm,
        "BAND_HI_CM" => FootLock.BandHiCm,
        "VY_LO_CM_S" => FootLock.VyLoCmS,
        "VY_HI_CM_S" => FootLock.VyHiCmS,
        "GROUND_PCT" => FootLock.GroundPct,
        "MIN_WEIGHT" => FootLock.MinWeight,
        "FULL" => FootLock.Full,
        "CONTACT_POINTS" => new JsonArray(FootLock.ContactPoints.Select(p => (JsonNode?)p).ToArray()),
        "PIN_MIN_S" => LegPin.PinMinS,
        "PIN_FADE_S" => LegPin.PinFadeS,
        "SOLE_MIN_FRACTION" => LegPin.SoleMinFraction,
        "LIFT_RAMP_S" => BridgeLift.LiftRampS,
        "BRIDGE_FADE_IN_S" => BridgeLift.BridgeFadeInS,
        "HEADING_MIN_HORIZONTAL" => BridgeHeading.HeadingMinHorizontal,
        "STAND_ADOPT_M" => StandSettle.StandAdoptM,
        "SAME_STAND_M" => StandSettle.SameStandM,
        "STAIR_RANGE" => Stairs.StairRange,
        "RIDE_ARRIVE_M" => Stairs.RideArriveM,
        "RELOCK_MIN_GAIN_CM" => FootLockMeasure.RelockMinGainCm,
        _ => throw new ArgumentException($"Unknown constant {name}"),
    };

    public static JsonNode? Select(JsonNode? value, JsonNode? fields) => E3VectorAdapters.Path(value, (JsonArray)fields!);
}

/// <summary>
/// shared/test-vectors/foot_lock.json (hand derivations: client3d/scripts/smoke_foot_lock_math.mjs; TS
/// client3d/src/scene/footLock.ts).
/// <code>
///   TS fn          C#                               shape translation
///   ramp           FootLock.Ramp
///   footLockPath   FootLock.FootLockPath            tracks {name: [[x,y,z]…]}, weights {name: [w…]} → [[x, z]…]
///   constant       the constants of the modules     CONTACT_POINTS as a string array
///   footLockValue  GroundHeights → ContactWeights → FootLockPath, field path | drift_path | drift_zero_path
/// </code>
/// </summary>
public class FootLockVectorTests
{
    private static readonly Lazy<VectorFile> File = new(() => VectorFile.Load("foot_lock"));
    private static double N(JsonNode? n) => BridgeVectorAdapters.N(n);

    internal static readonly Dictionary<string, Func<JsonArray, JsonNode?>> Dispatch = new()
    {
        ["ramp"] = a => FootLock.Ramp(N(Arity(a, 3, 3)[0]), N(a[1]), N(a[2])),
        ["footLockPath"] = a => BridgeVectorAdapters.PathJson(FootLock.FootLockPath(BridgeVectorAdapters.Tracks(Arity(a, 2, 2)[0]),
                                                                                  BridgeVectorAdapters.Weights(a[1]))),
        ["constant"] = a => BridgeVectorAdapters.Constant(Str(Arity(a, 1, 1)[0])),
        ["footLockValue"] = a =>
        {
            Arity(a, 2, 2);
            var tracks = BridgeVectorAdapters.Tracks(a[0]!["tracks"]);
            var ground = FootLock.GroundHeights(tracks, BridgeVectorAdapters.Numbers(a[0]!["rest"]));
            var weights = FootLock.ContactWeights(tracks, ground, N(a[0]!["fps"]));
            var path = FootLock.FootLockPath(tracks, weights);
            return Str(a[1]) switch
            {
                "path" => BridgeVectorAdapters.PathJson(path),
                "drift_path" => FootLock.MaxPlantedDrift(tracks, weights, path),
                "drift_zero_path" => FootLock.MaxPlantedDrift(tracks, weights, path.Select(_ => (0.0, 0.0)).ToList()),
                var f => throw new ArgumentException($"Unknown foot-lock field {f}"),
            };
        },
    };

    public static TheoryData<string> Cases => VectorFile.Labels("foot_lock");

    [Theory]
    [MemberData(nameof(Cases))]
    public void Case(string label) => File.Value.AssertCase(label, Dispatch);

    [Fact]
    public void EveryFunctionIsDispatched() => Assert.Empty(File.Value.MissingFunctions(Dispatch));
}

/// <summary>
/// shared/test-vectors/leg_pin.json (hand derivations: client3d/scripts/smoke_leg_pin.mjs; TS client3d/src/scene/legPin.ts).
/// <code>
///   TS fn            C#                      shape translation
///   pinRuns          LegPin.PinRuns
///   soleDown         LegPin.SoleDown
///   rotationBetween  LegPin.RotationBetween  (w, x, y, z)
///   qrot             LegPin.Qrot             (w, x, y, z)
///   ikValue          LegPin.TwoBoneIk        the deltas applied with the smoke's own rotation matrix (not Qrot):
///                                            knee, ankle, kneeX, upperLength, lowerLength, finite
///   legPinConstants  {PIN_MIN_S, PIN_FADE_S}
///   constant         the module constants
/// </code>
/// </summary>
public class LegPinVectorTests
{
    private static readonly Lazy<VectorFile> File = new(() => VectorFile.Load("leg_pin"));
    private static double N(JsonNode? n) => BridgeVectorAdapters.N(n);

    private static WQuat Q(JsonNode? n)
    {
        var a = (JsonArray)n!;
        return new WQuat(N(a[0]), N(a[1]), N(a[2]), N(a[3]));
    }

    /// <summary>The smoke's independent rotation: the matrix of the unit quaternion (w, x, y, z) times v.</summary>
    private static V3 Rot(WQuat q, V3 v)
    {
        double w = q.W, x = q.X, y = q.Y, z = q.Z;
        return new V3(
            (1 - 2 * (y * y + z * z)) * v.X + 2 * (x * y - w * z) * v.Y + 2 * (x * z + w * y) * v.Z,
            2 * (x * y + w * z) * v.X + (1 - 2 * (x * x + z * z)) * v.Y + 2 * (y * z - w * x) * v.Z,
            2 * (x * z - w * y) * v.X + 2 * (y * z + w * x) * v.Y + (1 - 2 * (x * x + y * y)) * v.Z);
    }

    private static double Len(V3 v) => Math.Sqrt(v.X * v.X + v.Y * v.Y + v.Z * v.Z);

    internal static readonly Dictionary<string, Func<JsonArray, JsonNode?>> Dispatch = new()
    {
        ["pinRuns"] = a => BridgeVectorAdapters.Nums(LegPin.PinRuns(BridgeVectorAdapters.NumList(Arity(a, 2, 2)[0]), N(a[1]))),
        ["soleDown"] = a => new JsonArray(LegPin.SoleDown(BridgeVectorAdapters.NumList(Arity(a, 3, 3)[0]), BridgeVectorAdapters.NumList(a[1]), N(a[2]))
                                                .Select(b => (JsonNode?)b).ToArray()),
        ["rotationBetween"] = a =>
        {
            var q = LegPin.RotationBetween(BridgeVectorAdapters.Pt(Arity(a, 2, 2)[0]), BridgeVectorAdapters.Pt(a[1]));
            return new JsonArray(q.W, q.X, q.Y, q.Z);
        },
        ["qrot"] = a => BridgeVectorAdapters.Arr(LegPin.Qrot(Q(Arity(a, 2, 2)[0]), BridgeVectorAdapters.Pt(a[1]))),
        ["ikValue"] = a =>
        {
            Arity(a, 2, 2);
            var p = ((JsonArray)a[0]!).Select(BridgeVectorAdapters.Pt).ToArray();
            var (hip, knee, ankle) = (p[0], p[1], p[2]);
            var (upper, lower) = LegPin.TwoBoneIk(p[0], p[1], p[2], p[3], p[4]);
            var k = hip + Rot(upper, knee - hip);
            var an = k + Rot(lower, Rot(upper, ankle - knee));
            bool finite = new[] { upper.W, upper.X, upper.Y, upper.Z, lower.W, lower.X, lower.Y, lower.Z, k.X, k.Y, k.Z, an.X, an.Y, an.Z }
                .All(double.IsFinite);
            var value = new JsonObject
            {
                ["knee"] = BridgeVectorAdapters.Arr(k), ["ankle"] = BridgeVectorAdapters.Arr(an), ["kneeX"] = k.X,
                ["upperLength"] = Len(k - hip), ["lowerLength"] = Len(an - k), ["finite"] = finite,
            };
            return BridgeVectorAdapters.Select(value, a[1]);
        },
        ["legPinConstants"] = a =>
        {
            Arity(a, 0, 0);
            return new JsonObject { ["PIN_MIN_S"] = LegPin.PinMinS, ["PIN_FADE_S"] = LegPin.PinFadeS };
        },
        ["constant"] = a => BridgeVectorAdapters.Constant(Str(Arity(a, 1, 1)[0])),
    };

    public static TheoryData<string> Cases => VectorFile.Labels("leg_pin");

    [Theory]
    [MemberData(nameof(Cases))]
    public void Case(string label) => File.Value.AssertCase(label, Dispatch);

    [Fact]
    public void EveryFunctionIsDispatched() => Assert.Empty(File.Value.MissingFunctions(Dispatch));
}

/// <summary>
/// shared/test-vectors/bridge_lift.json (hand derivations: client3d/scripts/smoke_bridge_lift.mjs; TS
/// client3d/src/scene/bridgeLift.ts).
/// <code>
///   TS fn         C#                      shape translation
///   liftRamp      BridgeLift.LiftRamp     {from, to}
///   liftAt        BridgeLift.LiftAt
///   fadeCarry     BridgeLift.FadeCarry
///   finiteLiftAt  isFinite(LiftAt(…))
///   constant      the module constants
/// </code>
/// </summary>
public class BridgeLiftVectorTests
{
    private static readonly Lazy<VectorFile> File = new(() => VectorFile.Load("bridge_lift"));
    private static double N(JsonNode? n) => BridgeVectorAdapters.N(n);

    internal static readonly Dictionary<string, Func<JsonArray, JsonNode?>> Dispatch = new()
    {
        ["liftRamp"] = a =>
        {
            var (from, to) = BridgeLift.LiftRamp(N(Arity(a, 1, 1)[0]));
            return new JsonObject { ["from"] = from, ["to"] = to };
        },
        ["liftAt"] = a => BridgeLift.LiftAt(N(Arity(a, 4, 4)[0]), N(a[1]), N(a[2]), N(a[3])),
        ["fadeCarry"] = a => BridgeLift.FadeCarry(N(Arity(a, 2, 2)[0]), N(a[1])),
        ["finiteLiftAt"] = a => double.IsFinite(BridgeLift.LiftAt(N(Arity(a, 4, 4)[0]), N(a[1]), N(a[2]), N(a[3]))),
        ["constant"] = a => BridgeVectorAdapters.Constant(Str(Arity(a, 1, 1)[0])),
    };

    public static TheoryData<string> Cases => VectorFile.Labels("bridge_lift");

    [Theory]
    [MemberData(nameof(Cases))]
    public void Case(string label) => File.Value.AssertCase(label, Dispatch);

    [Fact]
    public void EveryFunctionIsDispatched() => Assert.Empty(File.Value.MissingFunctions(Dispatch));
}

/// <summary>
/// shared/test-vectors/bridge_travel.json (hand derivations: client3d/scripts/smoke_bridge_root.mjs; TS
/// client3d/src/scene/bridgeTravel.ts). Paths are <c>{times, xz}</c> (Float32 like the browser's stores).
/// <code>
///   TS fn       C#                        shape translation
///   rootPathAt  BridgeTravel.RootPathAt   {x, z}
///   travelAt    BridgeTravel.TravelAt     {x, z}
///   toWorld     BridgeTravel.ToWorld      ({x, z}, yaw) → {x, z}
/// </code>
/// </summary>
public class BridgeTravelVectorTests
{
    private static readonly Lazy<VectorFile> File = new(() => VectorFile.Load("bridge_travel"));
    private static double N(JsonNode? n) => BridgeVectorAdapters.N(n);

    internal static readonly Dictionary<string, Func<JsonArray, JsonNode?>> Dispatch = new()
    {
        ["rootPathAt"] = a =>
        {
            var (x, z) = BridgeTravel.RootPathAt(BridgeVectorAdapters.PathOf(Arity(a, 2, 2)[0]), N(a[1]));
            return BridgeVectorAdapters.XZ(x, z);
        },
        ["travelAt"] = a =>
        {
            var (x, z) = BridgeTravel.TravelAt(BridgeVectorAdapters.PathOf(Arity(a, 2, 2)[0]), N(a[1]));
            return BridgeVectorAdapters.XZ(x, z);
        },
        ["toWorld"] = a =>
        {
            var p = BridgeVectorAdapters.P2Of(Arity(a, 2, 2)[0]);
            var (x, z) = BridgeTravel.ToWorld(p.X, p.Z, N(a[1]));
            return BridgeVectorAdapters.XZ(x, z);
        },
    };

    public static TheoryData<string> Cases => VectorFile.Labels("bridge_travel");

    [Theory]
    [MemberData(nameof(Cases))]
    public void Case(string label) => File.Value.AssertCase(label, Dispatch);

    [Fact]
    public void EveryFunctionIsDispatched() => Assert.Empty(File.Value.MissingFunctions(Dispatch));
}

/// <summary>
/// shared/test-vectors/bridge_heading.json (hand derivations: client3d/scripts/smoke_bridge_heading.mjs; TS
/// client3d/src/scene/bridgeHeading.ts + bridgeTravel.ts <c>turnAt</c>).
/// <code>
///   TS fn         C#                           shape translation
///   headingTrack  BridgeHeading.HeadingTrack   [[x,y,z]…] twice → a plain array (the browser's Float32Array)
///   turnAt        BridgeTravel.TurnAt          {times, yaw, pivot}
///   constant      the module constants
/// </code>
/// </summary>
public class BridgeHeadingVectorTests
{
    private static readonly Lazy<VectorFile> File = new(() => VectorFile.Load("bridge_heading"));
    private static double N(JsonNode? n) => BridgeVectorAdapters.N(n);

    internal static readonly Dictionary<string, Func<JsonArray, JsonNode?>> Dispatch = new()
    {
        ["headingTrack"] = a => BridgeVectorAdapters.Nums(BridgeHeading.HeadingTrack(
            ((JsonArray)Arity(a, 2, 2)[0]!).Select(BridgeVectorAdapters.Pt).ToList(),
            ((JsonArray)a[1]!).Select(BridgeVectorAdapters.Pt).ToList()).Select(f => (double)f)),
        ["turnAt"] = a => BridgeTravel.TurnAt(BridgeVectorAdapters.TurnOf(Arity(a, 2, 2)[0]), N(a[1])),
        ["constant"] = a => BridgeVectorAdapters.Constant(Str(Arity(a, 1, 1)[0])),
    };

    public static TheoryData<string> Cases => VectorFile.Labels("bridge_heading");

    [Theory]
    [MemberData(nameof(Cases))]
    public void Case(string label) => File.Value.AssertCase(label, Dispatch);

    [Fact]
    public void EveryFunctionIsDispatched() => Assert.Empty(File.Value.MissingFunctions(Dispatch));
}

/// <summary>
/// shared/test-vectors/stand_settle.json (hand derivations: client3d/scripts/smoke_stand_settle.mjs; TS
/// client3d/src/scene/standSettle.ts).
/// <code>
///   TS fn         C#                        shape translation
///   settleOffset  StandSettle.SettleOffset  {x, z} points; null = walk to the point
///   constant      the module constants
/// </code>
/// </summary>
public class StandSettleVectorTests
{
    private static readonly Lazy<VectorFile> File = new(() => VectorFile.Load("stand_settle"));

    internal static readonly Dictionary<string, Func<JsonArray, JsonNode?>> Dispatch = new()
    {
        ["settleOffset"] = a =>
        {
            Arity(a, 3, 4);
            var o = Arg(a, 3) is { } tol
                ? StandSettle.SettleOffset(BridgeVectorAdapters.P2Of(a[0]), BridgeVectorAdapters.P2Of(a[1]), BridgeVectorAdapters.P2Of(a[2]), BridgeVectorAdapters.N(tol))
                : StandSettle.SettleOffset(BridgeVectorAdapters.P2Of(a[0]), BridgeVectorAdapters.P2Of(a[1]), BridgeVectorAdapters.P2Of(a[2]));
            return o is { } p ? BridgeVectorAdapters.XZ(p.X, p.Z) : null;
        },
        ["constant"] = a => BridgeVectorAdapters.Constant(Str(Arity(a, 1, 1)[0])),
    };

    public static TheoryData<string> Cases => VectorFile.Labels("stand_settle");

    [Theory]
    [MemberData(nameof(Cases))]
    public void Case(string label) => File.Value.AssertCase(label, Dispatch);

    [Fact]
    public void EveryFunctionIsDispatched() => Assert.Empty(File.Value.MissingFunctions(Dispatch));
}

/// <summary>
/// shared/test-vectors/foot_lock_measure.json (hand derivations: client3d/scripts/smoke_foot_lock_measure.mjs; TS
/// client3d/src/scene/footLockMeasure.ts <c>relockRootPaths</c>).
/// <code>
///   TS fn                   C#                              shape translation
///   relockValue             FootLockMeasure.Relock          the adapter's rig: bones {name, parent, position, quaternion?
///                                                           (x,y,z,w)} under an identity root (ProbeRig), clips {name,
///                                                           duration, tracks [{name: "node.prop", times, values}], path?}
///                                                           → {reports, paths [{times, x, z} | null], logs, samePaths,
///                                                           reportNames, untouched, emptyAndSilent, finite}, then fields
///   groundValue             FootLock.GroundHeights          then fields
///   hasGroundLiftTolerance  false                           the removed GROUND_LIFT_TOL_CM has no native twin
/// </code>
/// </summary>
public class FootLockMeasureVectorTests
{
    private static readonly Lazy<VectorFile> File = new(() => VectorFile.Load("foot_lock_measure"));
    private static double N(JsonNode? n) => BridgeVectorAdapters.N(n);

    private static ProbeRig Rig(JsonNode? bones)
    {
        var list = ((JsonArray)bones!).ToList();
        var index = list.Select((b, i) => (Str(b!["name"]), i)).ToDictionary(e => e.Item1, e => e.i);
        var nodes = list.Select(b =>
        {
            var q = b!["quaternion"] is JsonArray qa ? new Quat(N(qa[0]), N(qa[1]), N(qa[2]), N(qa[3])) : Quat.Identity;
            int parent = b["parent"] is null ? -1 : index[Str(b["parent"])];
            return new ProbeNode(Str(b["name"]), parent, true, BridgeVectorAdapters.Pt(b["position"]), q, new V3(1, 1, 1));
        }).ToList();
        return new ProbeRig(Affine.Identity, nodes);
    }

    private static ProbeClip Clip(JsonNode? c)
    {
        var tracks = ((JsonArray)c!["tracks"]!).Select(t =>
        {
            var name = Str(t!["name"]);
            int dot = name.LastIndexOf('.');
            return new ProbeTrack
            {
                Node = name[..dot], Prop = name[(dot + 1)..] == "quaternion" ? "quaternion" : "position",
                Times = BridgeVectorAdapters.Floats(t["times"]), Values = BridgeVectorAdapters.Floats(t["values"]),
            };
        }).ToList();
        return new ProbeClip
        {
            Name = Str(c["name"]), Duration = N(c["duration"]), Tracks = tracks,
            Path = c["path"] is { } p ? BridgeVectorAdapters.PathOf(p) : null,
        };
    }

    private static JsonObject ReportJson(RelockReport r)
    {
        var o = new JsonObject
        {
            ["clip"] = r.Clip, ["used"] = r.Used, ["driftCm"] = r.DriftCm, ["rebuiltDriftCm"] = r.RebuiltDriftCm,
            ["importedDriftCm"] = r.ImportedDriftCm, ["pinnedCm"] = r.PinnedCm, ["liftCm"] = r.LiftCm,
            ["travel"] = new JsonArray(r.Travel.X, r.Travel.Z), ["turnDeg"] = r.TurnDeg,
        };
        if (r.Reason is not null) o["reason"] = r.Reason;
        if (r.PinReason is not null) o["pinReason"] = r.PinReason;
        if (r.TurnReason is not null) o["turnReason"] = r.TurnReason;
        return o;
    }

    /// <summary>The smoke adapter <c>relock(m, data)</c>.</summary>
    internal static JsonObject RelockResult(JsonNode? data)
    {
        var rig = Rig(data!["bones"]);
        string Snapshot() => string.Join(";", rig.Nodes.Select(n => $"{n.Name}:{n.Position}:{n.Rotation}"));
        string before = Snapshot();
        var clips = ((JsonArray)data["clips"]!).Select(Clip).ToList();
        var prior = clips.Select(c => c.Path).ToList();
        var logs = new List<string>();
        bool turn = data["options"] is not JsonObject opts || opts["turn"] is not JsonValue tv || tv.GetValue<bool>();
        var reports = FootLockMeasure.Relock(clips, rig, N(data["unitsPerCm"]), logs.Add, turn);
        var paths = clips.Select(c => c.Path is { } p
            ? (JsonNode)new JsonObject
            {
                ["times"] = BridgeVectorAdapters.Nums(p.Times.Select(t => (double)t)),
                ["x"] = BridgeVectorAdapters.Nums(Enumerable.Range(0, p.Times.Length).Select(i => (double)p.Xz[2 * i])),
                ["z"] = BridgeVectorAdapters.Nums(Enumerable.Range(0, p.Times.Length).Select(i => (double)p.Xz[2 * i + 1])),
            }
            : null).ToArray();
        return new JsonObject
        {
            ["reports"] = new JsonArray(reports.Select(r => (JsonNode?)ReportJson(r)).ToArray()),
            ["paths"] = new JsonArray(paths),
            ["logs"] = new JsonArray(logs.Select(l => (JsonNode?)l).ToArray()),
            ["samePaths"] = new JsonArray(clips.Select((c, i) => (JsonNode?)ReferenceEquals(c.Path, prior[i])).ToArray()),
            ["reportNames"] = new JsonArray(reports.Select(r => (JsonNode?)r.Clip).ToArray()),
            ["untouched"] = before == Snapshot(),
            ["emptyAndSilent"] = reports.Count == 0 && logs.Count == 0,
            ["finite"] = reports.All(r => new[] { r.DriftCm, r.ImportedDriftCm, r.Travel.X, r.Travel.Z }.All(double.IsFinite)),
        };
    }

    internal static readonly Dictionary<string, Func<JsonArray, JsonNode?>> Dispatch = new()
    {
        ["relockValue"] = a => BridgeVectorAdapters.Select(RelockResult(Arity(a, 2, 2)[0]), a[1]),
        ["groundValue"] = a =>
        {
            Arity(a, 3, 3);
            var g = FootLock.GroundHeights(BridgeVectorAdapters.Tracks(a[0]), BridgeVectorAdapters.Numbers(a[1]));
            var o = new JsonObject();
            foreach (var (k, v) in g) o[k] = v;
            return BridgeVectorAdapters.Select(o, a[2]);
        },
        ["hasGroundLiftTolerance"] = a =>
        {
            Arity(a, 0, 0);
            return false;
        },
    };

    public static TheoryData<string> Cases => VectorFile.Labels("foot_lock_measure");

    [Theory]
    [MemberData(nameof(Cases))]
    public void Case(string label) => File.Value.AssertCase(label, Dispatch);

    [Fact]
    public void EveryFunctionIsDispatched() => Assert.Empty(File.Value.MissingFunctions(Dispatch));
}

/// <summary>
/// shared/test-vectors/stairs.json (hand derivations: client3d/scripts/smoke_walk_math.mjs; TS
/// client3d/src/game/stairs.ts). A flight is <c>{foot, head, run?: {at, dir, runM, widthM}}</c>, a landing
/// <c>{level, x, y, z}</c>; output flights are the input objects (the TS returns the same objects).
/// <code>
///   TS fn                 C#                    shape translation
///   stairChain            Stairs.Chain          landings → {level, x, y, z}; null = no route
///   stairsAt              Stairs.StairsAt       {dir, dest, dist}
///   stairY                Stairs.StairY
///   stairLegTo            Stairs.LegTo          {flight, start, end}
///   stairChainValue       Chain + fields        ["landingHeights"] = [chain[1].y, chain[2].y]
///   stairLegToValue       LegTo + fields
///   stairLegsValue        Stairs.Legs + fields
///   rideSequenceValue     Stairs.RideStep       per point, leg/armed written back; the last result + state {leg, armed, done}
///   rideArrivalClearsRun  RIDE_ARRIVE_M &lt; 0.5
///   nearestRoomAt         Elevator.NearestRoomAt
///   constant              the module constants
/// </code>
/// </summary>
public class StairsVectorTests
{
    private static readonly Lazy<VectorFile> File = new(() => VectorFile.Load("stairs"));
    private static double N(JsonNode? n) => BridgeVectorAdapters.N(n);

    /// <summary>Parsed flights with the JSON object each came from (output identity).</summary>
    private sealed class Flights
    {
        public List<StairLink> Links { get; } = new();
        public Dictionary<StairLink, JsonNode> Source { get; } = new(ReferenceEqualityComparer.Instance);
        public Dictionary<StairLanding, JsonNode> Landings { get; } = new(ReferenceEqualityComparer.Instance);
    }

    private static StairLanding Landing(JsonNode? n) => new() { Level = Int(n!["level"]), Pos = new Vec3(N(n["x"]), N(n["y"]), N(n["z"])) };

    private static StairLink Flight(JsonNode? n, Flights? into = null)
    {
        var run = n!["run"];
        var foot = Landing(n["foot"]);
        var head = Landing(n["head"]);
        var link = new StairLink
        {
            Id = 0, Foot = foot, Head = head,
            At = run is null ? new P2(0, 0) : BridgeVectorAdapters.P2Of(run["at"]),
            Dir = run is null ? new P2(0, 0) : BridgeVectorAdapters.P2Of(run["dir"]),
            RunM = run is null ? 0 : N(run["runM"]), WidthM = run is null ? 0 : N(run["widthM"]),
            Footprint = Array.Empty<P2>(),
        };
        if (into is not null)
        {
            into.Links.Add(link);
            into.Source[link] = n;
            into.Landings[foot] = n["foot"]!;
            into.Landings[head] = n["head"]!;
        }
        return link;
    }

    private static Flights FlightsOf(JsonNode? n)
    {
        var f = new Flights();
        foreach (var x in (JsonArray)n!) Flight(x, f);
        return f;
    }

    private static JsonObject LandingJson(StairLanding l) => new() { ["level"] = l.Level, ["x"] = l.Pos.X, ["y"] = l.Pos.Y, ["z"] = l.Pos.Z };

    private static JsonNode FlightJson(StairLink link, Flights f) => f.Source[link].DeepClone();

    private static JsonObject LegJson(StairLeg leg, Flights f)
        => new() { ["flight"] = FlightJson(leg.Flight, f), ["start"] = LandingJson(leg.Start), ["end"] = LandingJson(leg.End) };

    private static JsonNode? ChainJson(List<StairLanding>? chain)
        => chain is null ? null : new JsonArray(chain.Select(l => (JsonNode?)LandingJson(l)).ToArray());

    private static List<ElevatorRoom> Rooms(JsonNode? n)
        => ((JsonArray)n!).Select(r => new ElevatorRoom(Str(r!["id"]), Int(r["level"]), BridgeVectorAdapters.P2Of(r["center"]),
                                                        r["floor"] is { } fl && fl.GetValue<bool>())).ToList();

    private static StairRide Ride(JsonNode? n, Flights f)
    {
        var legs = ((JsonArray)n!["legs"]!).Select(l =>
        {
            var flight = Flight(l!["flight"], f);
            return new StairLeg(flight, Landing(l["start"]), Landing(l["end"]));
        }).ToList();
        return new StairRide { Legs = legs, Leg = Int(n["leg"]), Armed = n["armed"]!.GetValue<bool>() };
    }

    internal static readonly Dictionary<string, Func<JsonArray, JsonNode?>> Dispatch = new()
    {
        ["stairChain"] = a => ChainJson(Stairs.Chain(FlightsOf(Arity(a, 3, 3)[0]).Links, Int(a[1]), Int(a[2]))),
        ["stairChainValue"] = a =>
        {
            Arity(a, 4, 4);
            var chain = Stairs.Chain(FlightsOf(a[0]).Links, Int(a[1]), Int(a[2]));
            var fields = (JsonArray)a[3]!;
            JsonNode? value = fields.Count > 0 && fields[0] is JsonValue v && v.TryGetValue(out string? s) && s == "landingHeights"
                ? new JsonObject { ["landingHeights"] = new JsonArray(chain![1].Pos.Y, chain[2].Pos.Y) }
                : ChainJson(chain);
            return BridgeVectorAdapters.Select(value, fields);
        },
        ["stairsAt"] = a =>
        {
            Arity(a, 4, 4);
            var p = Stairs.StairsAt(BridgeVectorAdapters.P2Of(a[0]), Int(a[1]), FlightsOf(a[2]).Links, N(a[3]));
            return p is null ? null : new JsonObject { ["dir"] = p.Dir, ["dest"] = LandingJson(p.Dest), ["dist"] = p.Dist };
        },
        ["stairY"] = a => Stairs.StairY(Flight(Arity(a, 3, 3)[0]), N(a[1]), N(a[2])),
        ["stairLegTo"] = a =>
        {
            var f = FlightsOf(Arity(a, 2, 2)[0]);
            return Stairs.LegTo(f.Links, Landing(a[1])) is { } leg ? LegJson(leg, f) : null;
        },
        ["stairLegToValue"] = a =>
        {
            var f = FlightsOf(Arity(a, 3, 3)[0]);
            JsonNode? value = Stairs.LegTo(f.Links, Landing(a[1])) is { } leg ? LegJson(leg, f) : null;
            return BridgeVectorAdapters.Select(value, a[2]);
        },
        ["stairLegsValue"] = a =>
        {
            var f = FlightsOf(Arity(a, 3, 3)[0]);
            var chain = ((JsonArray)a[1]!).Select(Landing).ToList();
            var legs = Stairs.Legs(f.Links, chain);
            return BridgeVectorAdapters.Select(new JsonArray(legs.Select(l => (JsonNode?)LegJson(l, f)).ToArray()), a[2]);
        },
        ["rideArrivalClearsRun"] = a =>
        {
            Arity(a, 0, 0);
            return Stairs.RideArriveM < 0.5;
        },
        ["rideSequenceValue"] = a =>
        {
            Arity(a, 3, 3);
            var ride = Ride(a[0], new Flights());
            RideStepResult step = default;
            foreach (var pt in (JsonArray)a[1]!)
            {
                var p = BridgeVectorAdapters.Pt(pt);
                step = Stairs.RideStep(ride, p.X, p.Y, p.Z);
                ride.Leg = step.Leg;
                ride.Armed = step.Armed;
            }
            var value = new JsonObject
            {
                ["leg"] = step.Leg, ["armed"] = step.Armed, ["y"] = step.Y, ["done"] = step.Done,
                ["state"] = new JsonObject { ["leg"] = step.Leg, ["armed"] = step.Armed, ["done"] = step.Done },
            };
            return BridgeVectorAdapters.Select(value, a[2]);
        },
        ["nearestRoomAt"] = a => Elevator.NearestRoomAt(Int(Arity(a, 3, 3)[0]), BridgeVectorAdapters.P2Of(a[1]), Rooms(a[2])),
        ["constant"] = a => BridgeVectorAdapters.Constant(Str(Arity(a, 1, 1)[0])),
    };

    public static TheoryData<string> Cases => VectorFile.Labels("stairs");

    [Theory]
    [MemberData(nameof(Cases))]
    public void Case(string label) => File.Value.AssertCase(label, Dispatch);

    [Fact]
    public void EveryFunctionIsDispatched() => Assert.Empty(File.Value.MissingFunctions(Dispatch));
}
