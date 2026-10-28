using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json.Nodes;
using AnimaNative.Scatter;
using AnimaNative.Tests.Vectors;
using static AnimaNative.Tests.ScatterVectorAdapters;

namespace AnimaNative.Tests;

/// <summary>Task 39: shape-only twin of client3d/scripts/e4VectorDispatch.mjs. Finite streams throw
/// on exhaustion; unknown keys fail, and occupancy is the production grid shared across operations.</summary>
internal static class ScatterRowVectorAdapters
{
    private static double N(JsonNode? n) => VectorCompare.Num(n);
    private static double? Opt(JsonNode? n) => VectorCompare.NumOrNull(n);
    private static JsonNode? J<T>(T value) => System.Text.Json.JsonSerializer.SerializeToNode(value);
    private static Func<double>? Stream(JsonNode? node)
    {
        if (node is null) return null;
        var values = node.AsArray().Select(N).ToArray(); int i = 0;
        return () => i < values.Length ? values[i++] : throw new InvalidOperationException("row RNG stream exhausted");
    }
    private static IScatterOccupancy? Grid(JsonNode? node)
    {
        if (node is null) return null;
        var g = new OccupancyGrid();
        foreach (var p in node.AsArray()) g.Add(N(p!["x"]), N(p["z"]), N(p["r"]), StrOrNull(p["tag"]));
        return g;
    }
    private static Func<double, double, double>? Axis(JsonNode? node)
        => node is null ? null : ScatterRows.AreaAxis(RingOrNull(node["line"]), RingOrNull(node["ring"]) ?? new(), StrOrNull(node["sides"]));
    private static ScatterRows.Options Options(JsonNode? node)
    {
        var o = node!.AsObject();
        string[] keys = { "spacingM", "offsetM", "startM", "jitterM", "seed", "sides", "edges", "side", "line", "yawMode", "yawDeg", "variantCount", "variant", "maxPoints", "footprints", "clearM", "occluders", "occupied", "occupyR", "occupyTag", "rng", "jitterRng", "axisFrom" };
        if (o.Any(p => !keys.Contains(p.Key))) throw new ArgumentException("unknown row option");
        return new()
        {
            SpacingM = NumOrNaN(o["spacingM"]), OffsetM = Opt(o["offsetM"]), StartM = Opt(o["startM"]), JitterM = Opt(o["jitterM"]),
            Seed = StrOrNull(o["seed"]) ?? "", Sides = StrOrNull(o["sides"]), Side = StrOrNull(o["side"]),
            Line = RingOrNull(o["line"]) ?? new(), Edges = o["edges"]?.AsArray().Select(Int).ToList(),
            YawMode = StrOrNull(o["yawMode"]), YawDeg = Opt(o["yawDeg"]), VariantCount = Opt(o["variantCount"]), Variant = Opt(o["variant"]),
            MaxPoints = IntOrNull(o["maxPoints"]), Footprints = FootprintsOrNull(o["footprints"]), ClearM = Opt(o["clearM"]),
            Occluders = RingsOrNull(o["occluders"]), Occupied = Grid(o["occupied"]), OccupyR = Opt(o["occupyR"]), OccupyTag = StrOrNull(o["occupyTag"]),
            Rng = Stream(o["rng"]), JitterRng = Stream(o["jitterRng"]), AxisAt = Axis(o["axisFrom"]),
        };
    }
    private static JsonArray Sample(string fn, JsonNode node, IScatterOccupancy? grid = null)
    {
        var o = (JsonObject)node.DeepClone(); var axis = Axis(o["axisFrom"]); var occupied = grid ?? Grid(o["occupied"]);
        var radius = Opt(o["occupyR"]); var tag = StrOrNull(o["occupyTag"]);
        foreach (var key in new[] { "axisFrom", "occupied", "occupyR", "occupyTag" }) o.Remove(key);
        if (fn == "scatterInstances")
        {
            var opts = SampleOptions(o); opts.AxisAt = axis; opts.Occupied = occupied; opts.OccupyR = radius; opts.OccupyTag = tag;
            return InstancesJson(ScatterMath.Instances(opts));
        }
        var cell = CellOptions(o); cell.AxisAt = axis; cell.Occupied = occupied; cell.OccupyR = radius; cell.OccupyTag = tag;
        return InstancesJson(ScatterMath.CellInstances(cell));
    }
    private static JsonArray Occupancy(JsonArray a)
    {
        IScatterOccupancy grid = Arg(a, 1)?.GetValue<bool>() == true ? new CellOccupancy(new()) : new OccupancyGrid();
        var answers = new JsonArray();
        foreach (var op in a[0]!.AsArray())
        {
            var p = op!; string kind = Str(p["op"]);
            if (kind == "add") grid.Add(N(p["x"]), N(p["z"]), N(p["r"]), StrOrNull(p["tag"]));
            else if (kind == "blocks") answers.Add(grid.Blocks(N(p["x"]), N(p["z"]), N(p["r"]), StrOrNull(p["tag"])));
            else if (kind == "sample")
            {
                string fn = Str(p["fn"]);
                if (fn == "scatterEdgeInstances") { var opts = Options(p["options"]); opts.Occupied = grid; answers.Add(InstancesJson(ScatterRows.EdgeInstances(Ring(p["ring"]), opts))); }
                else if (fn is "scatterInstances" or "scatterCellInstances") answers.Add(Sample(fn, p["options"]!, grid));
                else throw new ArgumentException("unknown occupancy sampler");
            }
            else throw new ArgumentException("unknown occupancy op");
        }
        return answers;
    }
    public static Dictionary<string, Func<JsonArray, JsonNode?>> Dispatch() => new()
    {
        ["ringEdgeAxis"] = a => J(ScatterRows.RingEdgeAxis(Ring(Arity(a, 3, 4)[0]), N(a[1]), N(a[2]), Arg(a, 3)?.AsArray().Select(Int).ToList())),
        ["lineAxis"] = a => J(ScatterRows.LineAxis(Ring(Arity(a, 3, 3)[0]), N(a[1]), N(a[2]))),
        ["areaAxis"] = a => { var o = Arity(a, 1, 1)[0]!; return J(Axis(o)!(N(o["at"]![0]), N(o["at"]![1]))); },
        ["ringSelectedEdges"] = a => J(ScatterRows.RingSelectedEdges(Ring(Arity(a, 1, 2)[0]), StrOrNull(Arg(a, 1)))),
        ["ribbonSelectedEdges"] = a => J(ScatterRows.RibbonSelectedEdges(Ring(Arity(a, 1, 2)[0]), StrOrNull(Arg(a, 1)))),
        ["polylabel"] = a => { var p = ScatterRows.Polylabel(Ring(Arity(a, 1, 2)[0]), Opt(Arg(a, 1)) ?? 0.5); return new JsonObject { ["x"] = p.X, ["z"] = p.Z, ["d"] = p.D }; },
        ["ringStations"] = a => new JsonArray(ScatterRows.RingStations(Ring(Arity(a, 2, 2)[0]), Options(a[1])).Select(s => (JsonNode?)new JsonObject { ["x"] = s.X, ["z"] = s.Z, ["axis"] = s.Axis, ["ordinal"] = s.Ordinal }).ToArray()),
        ["scatterEdgeInstances"] = a => InstancesJson(ScatterRows.EdgeInstances(Ring(Arity(a, 2, 2)[0]), Options(a[1]))),
        ["scatterCenterInstance"] = a => InstancesJson(ScatterRows.CenterInstance(Ring(Arity(a, 2, 2)[0]), Options(a[1]))),
        ["scatterInstances"] = a => Sample("scatterInstances", Arity(a, 1, 1)[0]!),
        ["scatterCellInstances"] = a => Sample("scatterCellInstances", Arity(a, 1, 1)[0]!),
        ["occupancy"] = a => Occupancy(Arity(a, 1, 2)),
        ["strokeStations"] = a => InstancesJson(StrokeMath.Stations(Options(Arity(a, 1, 1)[0]))),
        ["alongSeed"] = a => J(StrokeMath.AlongSeed(Str(Arity(a, 2, 3)[0]), Int(a[1]), Opt(Arg(a, 2)))),
        ["strokeCentreLine"] = a => { var o = Arity(a, 1, 1)[0]!; return PointsJson(StrokeMath.CentreLine(new(Ring(o["points"]), StrOrNull(o["style"]), Opt(o["spacing_m"]), Opt(o["amplitude_m"])))); },
        ["decorateStroke"] = a =>
        {
            var d = StrokeMath.Decorate(Ring(Arity(a, 4, 5)[0]), Str(a[1]), N(a[2]), N(a[3]), StrOrNull(Arg(a, 4)));
            return new JsonObject { ["points"] = PointsJson(d.Points), ["spacingM"] = d.SpacingM, ["capped"] = d.Capped,
                ["pointCount"] = d.Points.Count, ["xs"] = J(d.Points.Select(p => p.X).ToArray()) };
        },
    };
}
