using System.Text.Json;
using System.Text.Json.Nodes;
using AnimaNative.Orders;
using Xunit;

namespace AnimaNative.Tests;

/// <summary>
/// <see cref="OrderParse.From"/> on the wire form of plan E3 decision 2 (built by
/// <c>app/core/motion_orders.py::new_order</c>, Task 1): fields per actor, <c>flip_motion_s</c> missing while
/// <c>awaits</c> is set, <c>stand</c> per actor on a <c>cancel</c>. A missing id, an unknown <c>kind</c> or a
/// non-finite number yields <c>null</c>.
/// </summary>
public class OrderParseTests
{
    internal const string BedWire = """
        {"order_id":"run-1","revision":1,"seq":1,"kind":"prop_action","issued_motion_s":100,"eta_motion_s":103.2,
         "flip_motion_s":105.6,"deadline_motion_s":113.2,"status":"approaching","awaits":"","gait":"walk","speed_m_s":1.4,
         "target":{"location_id":"loc-o","room_id":"r-a","level":0,"floor_y":0,"placement_id":"bed-1","slot":0},
         "hint_route":[],"snap":false,
         "actors":[{"name":"Ona","role":"sleeper","clip_role":"a","height_cm":168,
                    "start":{"x":0,"y":0,"z":0,"yaw":90,"room_id":"r-a","level":0},
                    "access":{"x":2.8,"y":0,"z":0,"yaw":90},
                    "anchor":{"x":3.3,"y":0.45,"z":0,"yaw":90,"root_offset":0.1},
                    "entry_mode":"bridge",
                    "sequence":[{"step":"exit","pose_kind":"seat","pose_key":"sit_idle","nominal_s":1.2},
                                {"step":"walk","pose_kind":"","pose_key":"","nominal_s":0},
                                {"step":"entry","pose_kind":"lie","pose_key":"lie_down","nominal_s":2.4},
                                {"step":"loop","pose_kind":"lie","pose_key":"lie_idle","nominal_s":0}],
                    "reports_arrival":false}]}
        """;

    internal static JsonObject Wire() => JsonNode.Parse(BedWire)!.AsObject();

    internal static Order? Parse(JsonNode node)
    {
        using var doc = JsonDocument.Parse(node.ToJsonString());
        return OrderParse.From(doc.RootElement);
    }

    [Fact]
    public void ParsesTheWireForm()
    {
        var o = Parse(Wire())!;
        Assert.NotNull(o);
        Assert.Equal("run-1", o.Id);
        Assert.Equal(1, o.Revision);
        Assert.Equal(1L, o.Seq);
        Assert.Equal("prop_action", o.Kind);
        Assert.Equal(100, o.IssuedS);
        Assert.Equal(103.2, o.EtaS);
        Assert.Equal(105.6, o.FlipS);
        Assert.Equal(113.2, o.DeadlineS);
        Assert.Equal("approaching", o.Status);
        Assert.Equal("", o.Awaits);
        Assert.Equal("walk", o.Gait);
        Assert.Equal(1.4, o.SpeedMS);
        Assert.Equal("loc-o", o.LocationId);
        Assert.Equal("r-a", o.RoomId);
        Assert.Equal(0, o.Level);
        Assert.Null(o.Goal);
        Assert.Empty(o.HintRoute);
        Assert.False(o.Snap);
        Assert.False(o.IsLocal);
        var a = Assert.Single(o.Actors);
        Assert.Equal("Ona", a.Name);
        Assert.Equal("sleeper", a.Role);
        Assert.Equal("a", a.ClipRole);
        Assert.Equal(168, a.HeightCm);
        Assert.Equal(new OrderPoint(0, 0, 0, 90), a.Start);
        Assert.Equal("r-a", a.StartRoom);
        Assert.Equal(0, a.StartLevel);
        Assert.Equal(new OrderPoint(2.8, 0, 0, 90), a.Access);
        Assert.Equal(new OrderPoint(3.3, 0.45, 0, 90), a.Anchor);
        Assert.Equal(0.1, a.RootOffset);
        Assert.Equal("bridge", a.EntryMode);
        Assert.Equal(4, a.Sequence.Count);
        Assert.Equal(new OrderStep("exit", "seat", "sit_idle", 1.2), a.Sequence[0]);
        Assert.Equal(new OrderStep("loop", "lie", "lie_idle", 0), a.Sequence[3]);
        Assert.False(a.ReportsArrival);
        Assert.Null(a.Stand);
    }

    [Fact]
    public void AwaitsWithoutFlip()
    {
        var w = Wire();
        w["awaits"] = "reaction";
        w["status"] = "waiting";
        w.Remove("flip_motion_s");
        var o = Parse(w)!;
        Assert.NotNull(o);
        Assert.Equal("reaction", o.Awaits);
        Assert.Null(o.FlipS);
    }

    [Fact]
    public void CancelCarriesStandPerActor()
    {
        var w = Wire();
        w["kind"] = "cancel";
        w["order_id"] = "ord-c";
        w["snap"] = true;
        w["actors"]![0]!["stand"] = new JsonObject { ["x"] = 1, ["y"] = 0, ["z"] = 2, ["yaw"] = 180 };
        var o = Parse(w)!;
        Assert.Equal("cancel", o.Kind);
        Assert.True(o.Snap);
        Assert.Equal(new OrderPoint(1, 0, 2, 180), o.Actors[0].Stand);
    }

    [Fact]
    public void WalkTargetPointIsTheGoal()
    {
        var w = Wire();
        w["kind"] = "walk";
        w["target"] = new JsonObject { ["location_id"] = "loc-o", ["room_id"] = "r-b", ["level"] = 1, ["x"] = 5, ["y"] = 3, ["z"] = -2 };
        w["actors"]![0]!["access"] = null;
        w["actors"]![0]!["anchor"] = null;
        w["hint_route"] = new JsonArray(new JsonArray(1, 2), new JsonArray(3, 0, 4), new JsonObject { ["x"] = 5, ["z"] = 6 });
        var o = Parse(w)!;
        Assert.Equal(new OrderPoint(5, 3, -2, 0), o.Goal);
        Assert.Equal("r-b", o.RoomId);
        Assert.Equal(1, o.Level);
        Assert.Null(o.Actors[0].Access);
        Assert.Null(o.Actors[0].Anchor);
        Assert.Equal(new[] { new AnimaNative.Scatter.P2(1, 2), new AnimaNative.Scatter.P2(3, 4), new AnimaNative.Scatter.P2(5, 6) }, o.HintRoute);
    }

    [Fact]
    public void LocalIdIsLocal()
    {
        var w = Wire();
        w["order_id"] = "local:1";
        Assert.True(Parse(w)!.IsLocal);
    }

    [Fact]
    public void MissingIdIsNull()
    {
        var w = Wire();
        w.Remove("order_id");
        Assert.Null(Parse(w));
        w["order_id"] = "";
        Assert.Null(Parse(w));
    }

    [Fact]
    public void UnknownKindIsNull()
    {
        var w = Wire();
        w["kind"] = "teleport";
        Assert.Null(Parse(w));
        w.Remove("kind");
        Assert.Null(Parse(w));
    }

    [Fact]
    public void NonFiniteNumberIsNull()
    {
        // JSON has no NaN literal; 1e400 is valid JSON that overflows to infinity.
        string text = BedWire.Replace("\"eta_motion_s\":103.2", "\"eta_motion_s\":1e400");
        using (var doc = JsonDocument.Parse(text))
            Assert.Null(OrderParse.From(doc.RootElement));
        string actorText = BedWire.Replace("\"x\":2.8", "\"x\":-1e999");
        using (var doc = JsonDocument.Parse(actorText))
            Assert.Null(OrderParse.From(doc.RootElement));
    }

    [Fact]
    public void WrongTypesAreNull()
    {
        var w = Wire();
        w["speed_m_s"] = "1.4";
        Assert.Null(Parse(w));
        w = Wire();
        w["actors"]![0]!["start"]!["x"] = "0";
        Assert.Null(Parse(w));
        using var doc = JsonDocument.Parse("[1, 2]");
        Assert.Null(OrderParse.From(doc.RootElement));
    }

    [Fact]
    public void SpeedFollowsTheServerRule()
    {
        // motion_orders.new_order: a moving order needs speed > 0, a cancel may carry 0, never a negative speed.
        var w = Wire();
        w["speed_m_s"] = 0;
        Assert.Null(Parse(w));
        w["kind"] = "walk";
        Assert.Null(Parse(w));
        w["kind"] = "cancel";
        Assert.NotNull(Parse(w));
        w["speed_m_s"] = -1;
        Assert.Null(Parse(w));
    }
}
