using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
using System.Text.Json.Nodes;
using AnimaNative.Nav;
using AnimaNative.Orders;
using AnimaNative.Overview;
using AnimaNative.Tests.Vectors;
using Xunit;
using static AnimaNative.Tests.Vectors.VectorCompare;

namespace AnimaNative.Tests;

/// <summary>
/// shared/test-vectors/order_chain.json (hand derivations: native/tests/Derivations/order_chain.md). One function:
/// <code>
///   orderChain(order, lag, nav, script, until[, rides])
///     order   the wire form (OrderParse.From), accepted at client time 0 with motion − issued = lag; an order may be
///             written as {wire, actors} (the wire form with its actors replaced)
///     nav     {mesh: [x0, z0, x1, z1], holes: [[x0, z0, x1, z1], …], height_step?: [x_from, y],
///             answers?: [{from, to, points, owners ("" | "stairs:n"), length}]} for a FakePathProvider (height 0, or y
///             from x_from on)
///     rides   {kind: "Requested" | "Riding" | "Refused"}: one FakeRide per kind answering Begin with that state
///     script  [{at, op}] in time order; op accept {order} | freeze | unfreeze | refuse | row {seq} | probe
///     until   the last frame time
///   → {states: [{state, t}], events: [{event, t}], accepts: [bool], probes: [{t, state, walked, phase_time,
///      issued_local, x, y, z, id, pose_kind, pose_key, goal_x, goal_z}]}
/// </code>
/// Frames run at 1/60 s through <see cref="OrderHarness"/>; an action happens before the tick of its frame, a probe
/// reads the frame at its time.
/// </summary>
public class OrderVectorTests
{
    private static readonly Lazy<VectorFile> File = new(() => VectorFile.Load("order_chain"));

    /// <summary>The wire order, or <c>{wire, actors}</c>: the wire order with its <c>actors</c> replaced.</summary>
    private static Order ParseOrder(JsonNode? node)
    {
        if (node is JsonObject o && o.ContainsKey("wire"))
        {
            var wire = o["wire"]!.DeepClone().AsObject();
            wire["actors"] = o["actors"]!.DeepClone();
            node = wire;
        }
        using var doc = JsonDocument.Parse(node!.ToJsonString());
        return OrderParse.From(doc.RootElement) ?? throw new InvalidOperationException("vector order does not parse");
    }

    private static FakePathProvider Nav(JsonNode? node)
    {
        var o = node!.AsObject();
        var m = o["mesh"]!.AsArray();
        Func<double, double, double>? height = null;
        if (o["height_step"] is JsonArray hs)
        {
            double from = Num(hs[0]), y = Num(hs[1]);
            height = (x, _) => x >= from ? y : 0;
        }
        var nav = new FakePathProvider { HeightAt = height }.Mesh(Num(m[0]), Num(m[1]), Num(m[2]), Num(m[3]));
        if (o["answers"] is JsonArray answers)
            foreach (var an in answers)
            {
                var a = an!.AsObject();
                nav.Answer(V(a["from"]), V(a["to"]), a["points"]!.AsArray().Select(V).ToArray(),
                           a["owners"]!.AsArray().Select(Owner).ToArray(), Num(a["length"]));
            }
        foreach (var h in o["holes"]!.AsArray())
        {
            var r = h!.AsArray();
            nav.Hole(Num(r[0]), Num(r[1]), Num(r[2]), Num(r[3]));
        }
        return nav;
    }

    private static Vec3 V(JsonNode? node)
    {
        var p = node!.AsArray();
        return new Vec3(Num(p[0]), Num(p[1]), Num(p[2]));
    }

    /// <summary>A path corner's owner: "" = none, "stairs:n" = stair flight n.</summary>
    private static ulong Owner(JsonNode? node)
    {
        string s = node!.GetValue<string>();
        if (s.Length == 0) return 0;
        if (s.StartsWith("stairs:", StringComparison.Ordinal)) return NavLinkOwner.Stairs(int.Parse(s[7..]));
        throw new InvalidOperationException($"unknown owner {s}");
    }

    /// <summary>{kind: "Requested" | "Riding" | "Refused"} → one FakeRide per kind answering Begin with that state.</summary>
    private static Dictionary<string, ILinkRide> Rides(JsonNode? node)
    {
        var rides = new Dictionary<string, ILinkRide>();
        if (node is JsonObject o)
            foreach (var (kind, v) in o)
                rides[kind] = new FakeRide(kind, Enum.Parse<LinkRideState>(v!.GetValue<string>()));
        return rides;
    }

    private static readonly Dictionary<string, Func<JsonArray, JsonNode?>> Dispatch = new()
    {
        ["orderChain"] = a =>
        {
            var h = new OrderHarness(Nav(a[2]), Rides(a.Count > 5 ? a[5] : null));
            var accepts = new JsonArray();
            var probes = new JsonArray();
            h.Accept(ParseOrder(a[0]), Num(a[1]));
            foreach (var step in a[3]!.AsArray())
            {
                var s = step!.AsObject();
                double at = Num(s["at"]);
                string op = s["op"]!.GetValue<string>();
                if (op == "probe")
                {
                    var f = h.RunThrough(at);
                    probes.Add(new JsonObject
                    {
                        ["t"] = at, ["state"] = f.State.ToString(), ["walked"] = h.Player.WalkedM,
                        ["phase_time"] = f.PhaseTime, ["issued_local"] = h.Player.IssuedLocal,
                        ["x"] = f.Position.X, ["y"] = f.Position.Y, ["z"] = f.Position.Z,
                        ["id"] = h.Player.Current?.Id, ["pose_kind"] = h.Player.PhasePoseKind, ["pose_key"] = f.PoseKey,
                        ["goal_x"] = h.Player.WalkGoal?.X, ["goal_z"] = h.Player.WalkGoal?.Z,
                    });
                    continue;
                }
                h.RunBefore(at);
                switch (op)
                {
                    case "accept": accepts.Add(h.Accept(ParseOrder(s["order"]))); break;
                    case "freeze": h.Player.SetFrozen(true, h.Now); break;
                    case "unfreeze": h.Player.SetFrozen(false, h.Now); break;
                    case "refuse": h.Player.Refuse("vector"); break;
                    case "row": h.Player.RowWithoutOrder((long)Num(s["seq"]), h.Now); break;
                    default: throw new InvalidOperationException($"unknown op {op}");
                }
            }
            h.RunThrough(Num(a[4]));
            return new JsonObject
            {
                ["states"] = new JsonArray(h.States.Select(x => (JsonNode)new JsonObject { ["state"] = x.State.ToString(), ["t"] = x.T }).ToArray()),
                ["events"] = new JsonArray(h.Events.Select(x => (JsonNode)new JsonObject { ["event"] = x.Event, ["t"] = x.T }).ToArray()),
                ["accepts"] = accepts,
                ["probes"] = probes,
            };
        },
    };

    public static TheoryData<string> Cases => VectorFile.Labels("order_chain");

    [Theory, MemberData(nameof(Cases))]
    public void Case(string label) => File.Value.AssertCase(label, Dispatch);
}
