using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
using System.Text.Json.Nodes;
using AnimaNative.Nav;
using AnimaNative.Orders;
using AnimaNative.Tests.Vectors;
using Xunit;
using static AnimaNative.Tests.Vectors.VectorCompare;

namespace AnimaNative.Tests;

/// <summary>
/// shared/test-vectors/order_chain.json (hand derivations: native/tests/Derivations/order_chain.md). One function:
/// <code>
///   orderChain(order, lag, nav, script, until)
///     order   the wire form (OrderParse.From), accepted at client time 0 with motion − issued = lag
///     nav     {mesh: [x0, z0, x1, z1], holes: [[x0, z0, x1, z1], …]} for a FakePathProvider at height 0
///     script  [{at, op}] in time order; op accept {order} | freeze | unfreeze | refuse | row {seq} | probe
///     until   the last frame time
///   → {states: [{state, t}], events: [{event, t}], accepts: [bool], probes: [{t, state, walked, phase_time,
///      issued_local, x, z}]}
/// </code>
/// Frames run at 1/60 s through <see cref="OrderHarness"/>; an action happens before the tick of its frame, a probe
/// reads the frame at its time.
/// </summary>
public class OrderVectorTests
{
    private static readonly Lazy<VectorFile> File = new(() => VectorFile.Load("order_chain"));

    private static Order ParseOrder(JsonNode? node)
    {
        using var doc = JsonDocument.Parse(node!.ToJsonString());
        return OrderParse.From(doc.RootElement) ?? throw new InvalidOperationException("vector order does not parse");
    }

    private static FakePathProvider Nav(JsonNode? node)
    {
        var o = node!.AsObject();
        var m = o["mesh"]!.AsArray();
        var nav = new FakePathProvider().Mesh(Num(m[0]), Num(m[1]), Num(m[2]), Num(m[3]));
        foreach (var h in o["holes"]!.AsArray())
        {
            var r = h!.AsArray();
            nav.Hole(Num(r[0]), Num(r[1]), Num(r[2]), Num(r[3]));
        }
        return nav;
    }

    private static readonly Dictionary<string, Func<JsonArray, JsonNode?>> Dispatch = new()
    {
        ["orderChain"] = a =>
        {
            var h = new OrderHarness(Nav(a[2]));
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
                        ["x"] = f.Position.X, ["z"] = f.Position.Z,
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
