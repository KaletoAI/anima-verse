using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json.Nodes;
using AnimaNative.Figures;
using AnimaNative.Tests.Vectors;
using Xunit;
using static AnimaNative.Tests.ScatterVectorAdapters;

namespace AnimaNative.Tests;

/// <summary>
/// shared/test-vectors/hips_tracks.json against <see cref="HipsTrack"/> (derivations:
/// client3d/scripts/smoke_rig_stand_ref.mjs [R1]–[R9]).
/// <code>
///   standingHipsRef → HipsTrack.StandingRef     clipHipsDrop → HipsTrack.Drop
///   hipsTrackMedian → HipsTrack.Median          mapHipsTrack → HipsTrack.Map
/// </code>
/// </summary>
public class HipsTracksVectorTests
{
    private static readonly Lazy<VectorFile> File = new(() => VectorFile.Load("hips_tracks"));

    private static double? NumOrNull(JsonNode? n) => n is null ? null : VectorCompare.Num(n);
    private static double[] Nums(JsonNode? n) => ((JsonArray)n!).Select(VectorCompare.Num).ToArray();
    private static JsonArray Json(IEnumerable<float> v) => new(v.Select(x => (JsonNode?)(double)x).ToArray());

    private static readonly Dictionary<string, Func<JsonArray, JsonNode?>> Dispatch = new()
    {
        ["standingHipsRef"] = a =>
        {
            var (r, source) = HipsTrack.StandingRef(NumOrNull(Arity(a, 2, 2)[0]), NumOrNull(a[1]));
            return new JsonObject { ["ref"] = r, ["source"] = source };
        },
        ["clipHipsDrop"] = a => HipsTrack.Drop(NumOrNull(Arity(a, 3, 3)[0]), NumOrNull(a[1]), NumOrNull(a[2])),
        ["hipsTrackMedian"] = a =>
        {
            var clip = Arity(a, 1, 1)[0];
            var tracks = clip is JsonObject o && o["tracks"] is JsonArray ts
                ? ts.Select(t => (Str(t!["name"]), (IReadOnlyList<double>)Nums(t["values"]))).ToList()
                : null;
            return HipsTrack.Median(tracks);
        },
        ["mapHipsTrack"] = a =>
        {
            var o = (JsonObject)Arity(a, 3, 3)[2]!;
            var rest = Nums(o["rest"]);
            var (values, path) = HipsTrack.Map(Nums(a[0]), Nums(a[1]), new HipsTrackOptions(
                VectorCompare.Num(o["sourceRest"]), VectorCompare.Num(o["median"]), VectorCompare.Num(o["hipsPosScale"]),
                Nums(o["parentInverse"]), new V3(rest[0], rest[1], rest[2]),
                SceneVectorAdapters.Bool(o["rootMotion"]), SceneVectorAdapters.Bool(o["rigKnown"])));
            return new JsonObject
            {
                ["values"] = Json(values),
                ["rootPath"] = path is null ? null : new JsonObject { ["times"] = Json(path.Times), ["xz"] = Json(path.Xz) },
            };
        },
    };

    public static TheoryData<string> Cases => VectorFile.Labels("hips_tracks");

    [Theory]
    [MemberData(nameof(Cases))]
    public void Case(string label) => File.Value.AssertCase(label, Dispatch);

    [Fact]
    public void EveryFunctionIsDispatched() => Assert.Empty(File.Value.MissingFunctions(Dispatch));

    [Fact]
    public void AllSeventeenCasesAreConsumed() => Assert.Equal(17, File.Value.Cases.Count);

    /// <summary>The no-rig cluster fallback (no shared vector, see <see cref="HipsTrack.ClusterRest"/>), hand-derived from figures.ts:
    /// medians {211, 110, 108, 62}: descending 211, 110 (110 &lt; 0.7·211 = 147.7, no confirmation), 110 → 108 ≥ 77 → cap 110;
    /// cluster [77, 110] = {108, 110} ascending, element 1 → 110. One median 50 → itself. None → 0.</summary>
    [Fact]
    public void ClusterRestByHand()
    {
        Assert.Equal(110, HipsTrack.ClusterRest(new double[] { 62, 211, 110, 108 }));
        Assert.Equal(50, HipsTrack.ClusterRest(new double[] { 50 }));
        Assert.Equal(0, HipsTrack.ClusterRest(Array.Empty<double>()));
    }
}

/// <summary>
/// shared/test-vectors/clip_commit.json against <see cref="ClipLibraryRules.CommitInListOrder"/> (derivations:
/// client3d/scripts/smoke_clip_order.mjs). The ops are the smoke's: flags <c>{loop, rootMotion}</c>, pair = <c>__a/__b</c>,
/// root = <c>"root:" + id</c>, rename = a copy carrying the kind as <c>name</c>; the third argument is the path read
/// out of <c>{index, pairRoots}</c> (or <c>["hasKind", kind]</c>).
/// </summary>
public class ClipCommitVectorTests
{
    private static readonly Lazy<VectorFile> File = new(() => VectorFile.Load("clip_commit"));

    private sealed class FakeClip
    {
        public string Id = "";
        public string Name = "";
        public bool? Loop;
        public bool RootMotion;
    }

    private sealed class Ops : IClipCommitOps<FakeClip>
    {
        public void SetFlags(FakeClip c, ClipSourceEntry s) { c.Loop = s.Loop; c.RootMotion = s.RootMotion; }
        public bool IsPair(string kind) => ClipLibraryRules.IsPairName(kind);
        public object? PairRoot(FakeClip c) => "root:" + c.Id;
        public FakeClip Rename(FakeClip c, string kind) => new() { Id = c.Id, Name = kind, Loop = c.Loop, RootMotion = c.RootMotion };
    }

    private static List<ClipSourceEntry> Sources(JsonNode? n)
        => ((JsonArray)n!).Select(s => new ClipSourceEntry(Str(s!["kind"]), Str(s["set"]), Str(s["url"]),
                                                             s["loop"] is null ? null : SceneVectorAdapters.Bool(s["loop"]),
                                                             s["rootMotion"] is not null && SceneVectorAdapters.Bool(s["rootMotion"]))).ToList();

    private static List<FakeClip?> Results(JsonNode? n)
        => ((JsonArray)n!).Select(r => r!["clip"] is JsonObject c ? new FakeClip { Id = Str(c["id"]) } : null).ToList();

    private static JsonNode? Read(ClipIndex<FakeClip> index, List<string> path)
    {
        if (path[0] == "hasKind") return index.HasKind(path[1]);
        if (path[0] == "pairRoots") return index.PairRoots.TryGetValue(path[1], out var r) ? (string?)r : null;
        if (path[0] != "index" || !index.BySet.TryGetValue(path[1], out var bySet) || !bySet.TryGetValue(path[2], out var clip))
            return null;
        return path.Skip(3).ToList() switch
        {
            ["id"] => clip.Id,
            ["name"] => clip.Name,
            ["flags", "loop"] => clip.Loop is { } l ? l : null,
            ["flags", "rootMotion"] => clip.RootMotion,
            var rest => throw new ArgumentException($"unknown path {string.Join(".", rest)}"),
        };
    }

    private static readonly Dictionary<string, Func<JsonArray, JsonNode?>> Dispatch = new()
    {
        ["commitInListOrderValue"] = a => Read(ClipLibraryRules.CommitInListOrder(Sources(Arity(a, 3, 3)[0]), Results(a[1]), new Ops()),
                                               ((JsonArray)a[2]!).Select(Str).ToList()),
    };

    public static TheoryData<string> Cases => VectorFile.Labels("clip_commit");

    [Theory]
    [MemberData(nameof(Cases))]
    public void Case(string label) => File.Value.AssertCase(label, Dispatch);

    [Fact]
    public void EveryFunctionIsDispatched() => Assert.Empty(File.Value.MissingFunctions(Dispatch));

    [Fact]
    public void AllElevenCasesAreConsumed() => Assert.Equal(11, File.Value.Cases.Count);
}

/// <summary>
/// shared/test-vectors/clip_coverage.json against <see cref="FigureClips"/> (derivations:
/// client3d/scripts/smoke_clip_coverage.mjs). An omitted pose table is the browser's module default
/// (<see cref="PoseClips.Default"/>); <c>animatablePool</c> answers the names of the kept entries.
/// </summary>
public class ClipCoverageVectorTests
{
    private static readonly Lazy<VectorFile> File = new(() => VectorFile.Load("clip_coverage"));

    private static List<string> Strs(JsonNode? n) => ((JsonArray)n!).Select(x => Str(x)).ToList();
    private static JsonArray StrsJson(IEnumerable<string> l) => new(l.Select(s => (JsonNode?)s).ToArray());

    private static PoseClips Poses(JsonNode? node)
        => node is JsonObject o
            ? PoseClips.Of(o.ToDictionary(kv => kv.Key, kv => new PoseClip(Str(kv.Value!["kind"]), Str(kv.Value["publicKind"]))))
            : node is null ? PoseClips.Default : throw new ArgumentException($"expected a pose table, got {VectorCompare.Show(node)}");

    private static readonly Dictionary<string, Func<JsonArray, JsonNode?>> Dispatch = new()
    {
        ["missingClipKinds"] = a => StrsJson(FigureClips.MissingClipKinds(Strs(Arity(a, 2, 2)[0]), Strs(a[1]))),
        ["resolveClipName"] = a => FigureClips.ResolveClipName(Strs(Arity(a, 2, 2)[0]), Strs(a[1])),
        ["animFamily"] = a => FigureClips.AnimFamily(StrOrNull(Arity(a, 1, 1)[0])),
        ["matchAnimKind"] = a => FigureClips.MatchAnimKind(Strs(Arity(a, 2, 2)[0]), Str(a[1])),
        ["clipKindChain"] = a => StrsJson(FigureClips.ClipKindChain(Str(Arity(a, 1, 2)[0]), Poses(Arg(a, 1)))),
        ["resolveClipKind"] = a => FigureClips.ResolveClipKind(Str(Arity(a, 2, 3)[0]), Strs(a[1]), Poses(Arg(a, 2))),
        ["proceduralGait"] = a => FigureClips.ProceduralGait(StrOrNull(Arity(a, 1, 2)[0]), Poses(Arg(a, 1))),
        ["animatablePool"] = a =>
        {
            var pool = ((JsonArray)Arity(a, 1, 1)[0]!).Select(m => (Name: Str(m!["name"]), Fits: SceneVectorAdapters.Bool(m["libraryFits"]))).ToList();
            return StrsJson(FigureClips.AnimatablePool(pool, m => m.Fits).Select(m => m.Name));
        },
    };

    public static TheoryData<string> Cases => VectorFile.Labels("clip_coverage");

    [Theory]
    [MemberData(nameof(Cases))]
    public void Case(string label) => File.Value.AssertCase(label, Dispatch);

    [Fact]
    public void EveryFunctionIsDispatched() => Assert.Empty(File.Value.MissingFunctions(Dispatch));

    [Fact]
    public void AllEightySevenCasesAreConsumed() => Assert.Equal(87, File.Value.Cases.Count);
}
