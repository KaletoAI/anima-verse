using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json.Nodes;
using AnimaNative.Nav;
using AnimaNative.Orders;
using AnimaNative.Overview;
using Xunit;

namespace AnimaNative.Tests;

/// <summary>No clip loaded: every phase lasts its nominal seconds.</summary>
internal sealed class NominalClips : IClipDurations
{
    public static readonly NominalClips Instance = new();

    public double? Seconds(string step, string poseKind, string poseKey) => null;
}

/// <summary>A link ride for the tests: answers Begin with a fixed state, then follows a script of poll answers.</summary>
internal sealed class FakeRide : ILinkRide
{
    private readonly LinkRideState _begin;
    private readonly int _requestedPolls;
    private NavLink? _link;
    private int _polls;

    public FakeRide(string kind, LinkRideState begin, int requestedPolls = 0)
    {
        Kind = kind;
        _begin = begin;
        _requestedPolls = requestedPolls;
    }

    public string Kind { get; }

    public int Begins { get; private set; }

    public int Aborts { get; private set; }

    public LinkRideState Begin(string actor, NavLink link)
    {
        Begins++;
        _link = link;
        _polls = 0;
        return _begin;
    }

    /// <summary>Requested for the scripted number of polls, then rides straight to the link end at the given speed.</summary>
    public LinkRideState Poll(ref Vec3 pos, double dt, double speedMS)
    {
        if (_link is null) return LinkRideState.Refused;
        if (_polls++ < _requestedPolls) return LinkRideState.Requested;
        var end = _link.End;
        double dx = end.X - pos.X, dy = end.Y - pos.Y, dz = end.Z - pos.Z, d = Math.Sqrt(dx * dx + dy * dy + dz * dz);
        double step = speedMS * dt;
        if (d <= step + 1e-9)
        {
            pos = end;
            return LinkRideState.Done;
        }
        pos = new Vec3(pos.X + dx / d * step, pos.Y + dy / d * step, pos.Z + dz / d * step);
        return LinkRideState.Riding;
    }

    public void Abort() => Aborts++;
}

/// <summary>
/// Drives one <see cref="OrderPlayer"/> frame by frame at 1/60 s (client clock = frame / 60). Actions "at t" happen
/// before the tick of the frame at t. The motion clock runs with the client clock from the first accept on.
/// Records the first frame of each state and every event with its frame time.
/// </summary>
internal sealed class OrderHarness
{
    public const double Dt = 1.0 / 60;

    public readonly OrderPlayer Player;
    public readonly List<(OrderState State, double T)> States = new();
    public readonly List<(string Event, double T)> Events = new();
    public readonly List<OrderFrame> Frames = new();
    private readonly IPathProvider? _nav;
    private int _k;
    private double? _motion0;

    public OrderHarness(IPathProvider? nav, IReadOnlyDictionary<string, ILinkRide>? rides = null,
                        IClipDurations? clips = null, string actor = "Ona")
    {
        _nav = nav;
        Player = new OrderPlayer(actor, clips ?? NominalClips.Instance, rides ?? new Dictionary<string, ILinkRide>());
    }

    /// <summary>The client time of the next frame.</summary>
    public double Now => _k / 60.0;

    public OrderFrame? Last => Frames.Count > 0 ? Frames[^1] : null;

    /// <summary>Accept at <see cref="Now"/>; the first accept sets the motion clock so that motion − issued = lag.</summary>
    public bool Accept(Order order, double lag = 0)
    {
        _motion0 ??= order.IssuedS + lag - Now;
        var actor = order.Actors.First(a => a.Name == "Ona" || order.Actors.Count == 1);
        var shown = Last?.Position ?? new Vec3(actor.Start.X, actor.Start.Y, actor.Start.Z);
        return Player.Accept(order, Now, MotionNow, shown, Last?.YawDeg ?? actor.Start.YawDeg);
    }

    public double MotionNow => (_motion0 ?? 0) + Now;

    public OrderFrame Tick()
    {
        double now = Now;
        var f = Player.Tick(now, _nav);
        if (Frames.Count == 0 || Frames[^1].State != f.State)
            States.Add((f.State, now));
        foreach (var e in f.Events)
            Events.Add((e, now));
        Frames.Add(f);
        _k++;
        return f;
    }

    /// <summary>Ticks every frame strictly before t.</summary>
    public void RunBefore(double t)
    {
        while (Now < t - 1e-9) Tick();
    }

    /// <summary>Ticks every frame up to and including t; returns the frame at t.</summary>
    public OrderFrame RunThrough(double t)
    {
        OrderFrame? f = null;
        while (Now <= t + 1e-9) f = Tick();
        return f ?? Last!;
    }

    public static FakePathProvider Floor() => new FakePathProvider().Mesh(-10, -10, 10, 10);
}

/// <summary>
/// The order player on the hand derivation native/tests/Derivations/order_chain.md (free floor, path = straight
/// line, exit 1.2 s, speed 1.4 m/s, entry 2.4 s, path 2.8 m = 2.0 s): one test per derivation case.
/// </summary>
public class OrderPlayerTests
{
    private const double Frame = 1.0 / 60 + 1e-6;

    internal static Order Bed(Action<JsonObject>? edit = null)
    {
        var w = OrderParseTests.Wire();
        edit?.Invoke(w);
        return OrderParseTests.Parse(w) ?? throw new InvalidOperationException("fixture order does not parse");
    }

    private static JsonArray Seq(params (string Step, string Kind, string Key, double Nominal)[] steps)
        => new(steps.Select(s => (JsonNode)new JsonObject
        {
            ["step"] = s.Step, ["pose_kind"] = s.Kind, ["pose_key"] = s.Key, ["nominal_s"] = s.Nominal,
        }).ToArray());

    private static void AssertStates(OrderHarness h, params (OrderState State, double T)[] expected)
    {
        Assert.True(expected.Length == h.States.Count,
                    $"states: {string.Join(", ", h.States.Select(s => $"{s.State}@{s.T:F4}"))}");
        for (int i = 0; i < expected.Length; i++)
        {
            Assert.Equal(expected[i].State, h.States[i].State);
            Assert.True(Math.Abs(expected[i].T - h.States[i].T) <= Frame,
                        $"{expected[i].State}: expected t {expected[i].T}, got {h.States[i].T}");
        }
    }

    private static double EventTime(OrderHarness h, string name)
        => h.Events.First(e => e.Event == name).T;

    [Fact]
    public void fresh()
    {
        var h = new OrderHarness(OrderHarness.Floor());
        Assert.True(h.Accept(Bed(), lag: 0.5));
        h.RunThrough(8);
        AssertStates(h, (OrderState.Exit, 0), (OrderState.Walk, 1.2), (OrderState.Entry, 3.2), (OrderState.Loop, 5.6));
        Assert.Equal(0 - 0.5, h.Player.IssuedLocal, 9);
        var loop = h.Last!;
        Assert.Equal("lie_idle", loop.PoseKey);
        Assert.Equal(3.3, loop.Position.X, 6);
        Assert.Equal(0.45, loop.Position.Y, 6);
    }

    [Fact]
    public void mid_walk()
    {
        var h = new OrderHarness(OrderHarness.Floor());
        Assert.True(h.Accept(Bed(), lag: 2.5));
        var first = h.Tick();
        Assert.Equal(OrderState.Walk, first.State);
        Assert.Equal(1.82, h.Player.WalkedM, 6);
        Assert.Equal(1.82, first.Position.X, 6);
        h.RunThrough(5);
        AssertStates(h, (OrderState.Walk, 0), (OrderState.Entry, 0.7), (OrderState.Loop, 3.1));
    }

    [Fact]
    public void mid_entry()
    {
        var h = new OrderHarness(OrderHarness.Floor());
        Assert.True(h.Accept(Bed(), lag: 4.0));
        var first = h.Tick();
        Assert.Equal(OrderState.Entry, first.State);
        Assert.Equal(0.8, first.PhaseTime, 6);
        Assert.Equal("lie_down", first.PoseKey);
        h.RunThrough(3);
        AssertStates(h, (OrderState.Entry, 0), (OrderState.Loop, 1.6));
    }

    [Fact]
    public void late_active()
    {
        var h = new OrderHarness(OrderHarness.Floor());
        Assert.True(h.Accept(Bed(), lag: 7.0));
        h.RunThrough(3);
        AssertStates(h, (OrderState.Loop, 0));
        Assert.Equal(3.3, h.Frames[0].Position.X, 6);
        Assert.Contains("loop_started", h.Frames[0].Events);

        var active = new OrderHarness(OrderHarness.Floor());
        Assert.True(active.Accept(Bed(w => w["status"] = "active"), lag: 0));
        active.RunThrough(3);
        AssertStates(active, (OrderState.Loop, 0));
        Assert.DoesNotContain(active.Events, e => e.Event == "entry_started");
    }

    [Fact]
    public void poll_noop()
    {
        var h = new OrderHarness(OrderHarness.Floor());
        Assert.True(h.Accept(Bed(), lag: 0));
        double issued = h.Player.IssuedLocal;
        foreach (double t in new[] { 1.0, 3.0, 5.0 })
        {
            h.RunBefore(t);
            var state = h.Player.State;
            var repeat = Bed(w =>
            {
                w["actors"]![0]!["start"]!["x"] = 0.4;
                w["actors"]![0]!["access"]!["x"] = 2.2;
            });
            Assert.False(h.Accept(repeat, 0));
            Assert.Equal(state, h.Player.State);
            Assert.Equal(issued, h.Player.IssuedLocal);
        }
        h.RunThrough(8);
        AssertStates(h, (OrderState.Exit, 0), (OrderState.Walk, 1.2), (OrderState.Entry, 3.2), (OrderState.Loop, 5.6));
        Assert.Equal(2.8, h.Frames.First(f => f.State == OrderState.Entry).Position.X, 6);
    }

    [Fact]
    public void revision_shift()
    {
        var h = new OrderHarness(OrderHarness.Floor());
        Assert.True(h.Accept(Bed(), lag: 0));
        h.RunThrough(2.0);
        double walked = h.Player.WalkedM;
        Assert.Equal(1.12, walked, 6);
        var rev = Bed(w =>
        {
            w["revision"] = 2;
            foreach (var key in new[] { "issued_motion_s", "eta_motion_s", "flip_motion_s", "deadline_motion_s" })
                w[key] = w[key]!.GetValue<double>() + 30;
        });
        Assert.True(h.Accept(rev, 0));
        Assert.Equal(OrderState.Walk, h.Player.State);
        Assert.Equal(walked, h.Player.WalkedM);
        Assert.Equal(0, h.Player.IssuedLocal);
        Assert.Equal(2, h.Player.Current!.Revision);
        h.RunThrough(8);
        AssertStates(h, (OrderState.Exit, 0), (OrderState.Walk, 1.2), (OrderState.Entry, 3.2), (OrderState.Loop, 5.6));
    }

    private static Order Cancel(string id, double issued, Action<JsonObject>? edit = null) => Bed(w =>
    {
        w["order_id"] = id;
        w["kind"] = "cancel";
        w["status"] = "ended";
        w["issued_motion_s"] = issued;
        w["eta_motion_s"] = issued;
        w["flip_motion_s"] = issued + 1;
        w["deadline_motion_s"] = issued + 10;
        var a = w["actors"]![0]!.AsObject();
        a["sequence"] = Seq(("exit", "seat", "sit_idle", 1.0));
        a["stand"] = new JsonObject { ["x"] = 1, ["y"] = 0, ["z"] = 1, ["yaw"] = 0 };
        edit?.Invoke(w);
    });

    [Fact]
    public void new_id_from_walk()
    {
        var h = new OrderHarness(OrderHarness.Floor());
        Assert.True(h.Accept(Bed(), lag: 0));
        h.RunBefore(2.5);
        Assert.True(h.Accept(Cancel("ord-c", 102.5)));
        h.RunThrough(6);
        AssertStates(h, (OrderState.Exit, 0), (OrderState.Walk, 1.2), (OrderState.Abort, 2.5), (OrderState.Idle, 2.5 + 1 / 60.0));
        Assert.Equal(2.5, EventTime(h, "aborted"), 6);
        Assert.Equal("ord-c", h.Player.Current!.Id);
    }

    [Fact]
    public void new_id_from_loop()
    {
        var h = new OrderHarness(OrderHarness.Floor());
        Assert.True(h.Accept(Bed(), lag: 0));
        h.RunBefore(6.0);
        Assert.Equal(OrderState.Loop, h.Player.State);
        var next = Bed(w =>
        {
            w["order_id"] = "run-2";
            w["issued_motion_s"] = 106;
            w["eta_motion_s"] = 108;
            w["flip_motion_s"] = 109.5;
            var a = w["actors"]![0]!.AsObject();
            a["start"] = new JsonObject { ["x"] = 2.8, ["y"] = 0, ["z"] = 0, ["yaw"] = 0, ["room_id"] = "r-a", ["level"] = 0 };
            a["access"] = new JsonObject { ["x"] = 2.8, ["y"] = 0, ["z"] = 1.4, ["yaw"] = 0 };
            a["anchor"] = new JsonObject { ["x"] = 2.8, ["y"] = 0.45, ["z"] = 1.9, ["yaw"] = 0, ["root_offset"] = 0 };
            a["sequence"] = Seq(("exit", "seat", "sit_idle", 1.0), ("walk", "", "", 0), ("entry", "seat", "sit_down", 1.5),
                                ("loop", "seat", "sit_idle", 0));
        });
        Assert.True(h.Accept(next));
        var exit = h.Tick();
        Assert.Equal(OrderState.Exit, exit.State);
        Assert.Equal("exit", exit.PhaseStep);
        Assert.Equal("lie", h.Player.PhasePoseKind); // the pose kind of the running loop, not of the new sequence
        Assert.Equal("lie_idle", exit.PoseKey);
        h.RunThrough(12);
        AssertStates(h, (OrderState.Exit, 0), (OrderState.Walk, 1.2), (OrderState.Entry, 3.2), (OrderState.Loop, 5.6),
                     (OrderState.Exit, 6.0), (OrderState.Walk, 7.0), (OrderState.Entry, 8.0), (OrderState.Loop, 9.5));
    }

    [Fact]
    public void new_id_from_loop_cancel()
    {
        var h = new OrderHarness(OrderHarness.Floor());
        Assert.True(h.Accept(Bed(), lag: 0));
        h.RunBefore(6.0);
        Assert.True(h.Accept(Cancel("ord-c", 106)));
        var exit = h.Tick();
        Assert.Equal(OrderState.Exit, exit.State);
        Assert.Equal("lie", h.Player.PhasePoseKind);
        h.RunThrough(9);
        AssertStates(h, (OrderState.Exit, 0), (OrderState.Walk, 1.2), (OrderState.Entry, 3.2), (OrderState.Loop, 5.6),
                     (OrderState.Exit, 6.0), (OrderState.Abort, 7.0), (OrderState.Idle, 7.0 + 1 / 60.0));
        var abort = h.Frames.First(f => f.State == OrderState.Abort);
        Assert.Equal(1, abort.Position.X, 6);
        Assert.Equal(1, abort.Position.Z, 6);
    }

    [Fact]
    public void new_id_from_loop_held()
    {
        var h = new OrderHarness(OrderHarness.Floor());
        Assert.True(h.Accept(Bed(), lag: 0));
        h.RunBefore(6.0);
        var follow = Bed(w =>
        {
            w["order_id"] = "run-3";
            w["issued_motion_s"] = 106;
            w["eta_motion_s"] = 106;
            w["flip_motion_s"] = 106;
            w["status"] = "entering";
            w["actors"]![0]!["sequence"] = Seq(("loop", "lie", "lie_side", 0));
        });
        Assert.True(h.Accept(follow));
        var f = h.Tick();
        Assert.Equal(OrderState.Loop, f.State);
        Assert.Equal("lie_side", f.PoseKey);
        h.RunThrough(9);
        AssertStates(h, (OrderState.Exit, 0), (OrderState.Walk, 1.2), (OrderState.Entry, 3.2), (OrderState.Loop, 5.6));
        Assert.DoesNotContain(h.Frames.Skip(360), x => x.State == OrderState.Exit);
    }

    [Fact]
    public void cancel_without_figure_keeps_order()
    {
        var h = new OrderHarness(OrderHarness.Floor());
        Assert.True(h.Accept(Bed(), lag: 0));
        h.RunBefore(6.0);
        var other = Cancel("ord-c", 106, w => w["actors"]![0]!["name"] = "Uli");
        Assert.False(h.Accept(other));
        h.RunThrough(9);
        Assert.Equal("run-1", h.Player.Current!.Id);
        AssertStates(h, (OrderState.Exit, 0), (OrderState.Walk, 1.2), (OrderState.Entry, 3.2), (OrderState.Loop, 5.6));
    }

    [Fact]
    public void refused()
    {
        var h = new OrderHarness(OrderHarness.Floor());
        Assert.True(h.Accept(Bed(), lag: 0));
        h.RunBefore(0.8);
        h.Player.Refuse("slot_taken");
        h.RunThrough(8);
        AssertStates(h, (OrderState.Exit, 0), (OrderState.Abort, 0.8), (OrderState.Idle, 0.8 + 1 / 60.0));
        Assert.Equal(0.8, EventTime(h, "aborted"), 6);
    }

    [Fact]
    public void awaits()
    {
        var h = new OrderHarness(OrderHarness.Floor());
        var waiting = Bed(w =>
        {
            w["awaits"] = "reaction";
            w["status"] = "waiting";
            w.Remove("flip_motion_s");
        });
        Assert.True(h.Accept(waiting, lag: 0));
        h.RunBefore(4.0);
        Assert.Equal(OrderState.WaitAccess, h.Player.State);
        Assert.Equal(2.8, h.Last!.Position.X, 6);
        var granted = Bed(w =>
        {
            w["revision"] = 2;
            w["status"] = "entering";
            w["flip_motion_s"] = 106.4;
        });
        Assert.True(h.Accept(granted));
        h.RunThrough(8);
        AssertStates(h, (OrderState.Exit, 0), (OrderState.Walk, 1.2), (OrderState.WaitAccess, 3.2), (OrderState.Entry, 4.0),
                     (OrderState.Loop, 6.4));
        Assert.Equal(4.0, h.States[3].T, 9);
    }

    [Fact]
    public void heal()
    {
        // A wall across the path: the hole x in (1.0, 1.5) over the whole floor depth.
        var nav = OrderHarness.Floor().Hole(1.0, -10, 1.5, 10);
        var h = new OrderHarness(nav);
        Assert.True(h.Accept(Bed(), lag: 0));
        h.RunThrough(14);
        AssertStates(h, (OrderState.Exit, 0), (OrderState.Walk, 1.2), (OrderState.Entry, 10.6), (OrderState.Loop, 13.0));
        Assert.Equal(355 / 60.0, EventTime(h, "stuck"), 6);
        Assert.Equal(10.6, EventTime(h, "healed"), 6);
        Assert.Equal(1.0, h.Frames[630].Position.X, 6); // held at the wall
        var entry = h.Frames.First(f => f.State == OrderState.Entry);
        Assert.Equal(2.8, entry.Position.X, 6);
        Assert.DoesNotContain(h.Events, e => e.Event == "arrived_access");
    }

    [Fact]
    public void frozen()
    {
        var h = new OrderHarness(OrderHarness.Floor());
        Assert.True(h.Accept(Bed(), lag: 0));
        h.RunBefore(2.0);
        h.Player.SetFrozen(true, h.Now);
        var f = h.Tick();
        Assert.Equal(OrderState.Frozen, f.State);
        Assert.Equal(1.12, h.Player.WalkedM, 6);
        h.RunBefore(5.0);
        h.Player.SetFrozen(false, h.Now);
        var resumed = h.Tick();
        Assert.Equal(OrderState.Walk, resumed.State);
        Assert.Equal(1.12, h.Player.WalkedM, 6);
        h.RunThrough(10);
        AssertStates(h, (OrderState.Exit, 0), (OrderState.Walk, 1.2), (OrderState.Frozen, 2.0), (OrderState.Walk, 5.0),
                     (OrderState.Entry, 6.2), (OrderState.Loop, 8.6));
        Assert.Equal(0, h.Player.IssuedLocal);
    }

    private static Order Local(string id = "local:1", double issued = 100) => Bed(w =>
    {
        w["order_id"] = id;
        w["seq"] = 0;
        w["issued_motion_s"] = issued;
        w["actors"]![0]!["sequence"] = Seq(("walk", "", "", 0), ("entry", "lie", "lie_down", 2.4), ("loop", "lie", "lie_idle", 0));
    });

    private static Order Server(string id, double accessDz, double anchorDz = 0) => Bed(w =>
    {
        w["order_id"] = id;
        w["seq"] = 3;
        w["issued_motion_s"] = 100.6;
        var a = w["actors"]![0]!.AsObject();
        a["sequence"] = Seq(("walk", "", "", 0), ("entry", "lie", "lie_down", 2.4), ("loop", "lie", "lie_idle", 0));
        a["access"]!["z"] = accessDz;
        a["anchor"]!["z"] = anchorDz;
    });

    [Fact]
    public void local_adopt()
    {
        var h = new OrderHarness(OrderHarness.Floor());
        Assert.True(h.Accept(Local(), lag: 0));
        h.RunBefore(0.6);
        var state = h.Player.State;
        double walked = h.Player.WalkedM, issued = h.Player.IssuedLocal;
        Assert.Equal(OrderState.Walk, state);
        Assert.True(h.Accept(Server("run-1", 0.3)));
        Assert.Equal("run-1", h.Player.Current!.Id);
        Assert.Equal(issued, h.Player.IssuedLocal);
        Assert.Equal(state, h.Player.State);
        Assert.Equal(walked, h.Player.WalkedM);
        Assert.Equal(new Vec3(2.8, 0, 0.3), h.Player.WalkGoal);
        var arrive = h.RunThrough(3);
        Assert.Equal(OrderState.Entry, h.Player.State);
        Assert.Equal(0.3, arrive.Position.Z, 6);
    }

    [Fact]
    public void local_adopt_within_tolerance_keeps_goal()
    {
        var h = new OrderHarness(OrderHarness.Floor());
        Assert.True(h.Accept(Local(), lag: 0));
        h.RunBefore(0.6);
        Assert.True(h.Accept(Server("run-1", 0.1)));
        Assert.Equal("run-1", h.Player.Current!.Id);
        Assert.Equal(new Vec3(2.8, 0, 0), h.Player.WalkGoal);
        Assert.Equal(0, h.Player.IssuedLocal);
    }

    [Fact]
    public void local_adopt_other_target_is_a_new_order()
    {
        var h = new OrderHarness(OrderHarness.Floor());
        Assert.True(h.Accept(Local(), lag: 0));
        h.RunBefore(0.6);
        Assert.True(h.Accept(Server("run-2", 2.0, anchorDz: 2.0)));
        Assert.Equal("run-2", h.Player.Current!.Id);
        Assert.Equal(0.6, h.Player.IssuedLocal, 9); // case 1: a new clock (lag 0 at t 0.6)
        Assert.Equal(0, h.Player.WalkedM);
        Assert.Equal(OrderState.Walk, h.Player.State);
    }

    [Fact]
    public void row_without_order()
    {
        var h = new OrderHarness(OrderHarness.Floor());
        Assert.True(h.Accept(Bed(w => w["seq"] = 7), lag: 0));
        h.RunBefore(6.0);
        Assert.Equal(OrderState.Loop, h.Player.State);
        h.Player.RowWithoutOrder(7, h.Now);
        var f = h.Tick();
        Assert.Equal(OrderState.Idle, f.State);
        Assert.Contains("ended", f.Events);
        h.RunThrough(7);
        Assert.Equal(1, h.Events.Count(e => e.Event == "ended"));
        h.Player.RowWithoutOrder(7, h.Now); // a second row without order changes nothing
        Assert.Empty(h.Tick().Events);
    }

    [Fact]
    public void row_without_order_stale()
    {
        var h = new OrderHarness(OrderHarness.Floor());
        Assert.True(h.Accept(Bed(w => w["seq"] = 7), lag: 0));
        h.RunThrough(2.0);
        double walked = h.Player.WalkedM;
        h.Player.RowWithoutOrder(6, h.Now);
        Assert.Equal(OrderState.Walk, h.Player.State);
        Assert.Equal(walked, h.Player.WalkedM);
        Assert.DoesNotContain("ended", h.Tick().Events);
        h.RunThrough(8);
        AssertStates(h, (OrderState.Exit, 0), (OrderState.Walk, 1.2), (OrderState.Entry, 3.2), (OrderState.Loop, 5.6));
    }

    [Fact]
    public void row_without_order_local()
    {
        var h = new OrderHarness(OrderHarness.Floor());
        Assert.True(h.Accept(Local(), lag: 0));
        h.RunThrough(1.0);
        h.Player.RowWithoutOrder(99, h.Now);
        Assert.Equal(OrderState.Walk, h.Player.State);
        h.RunThrough(5);
        AssertStates(h, (OrderState.Walk, 0), (OrderState.Entry, 2.0), (OrderState.Loop, 4.4));
    }

    private static (FakePathProvider Nav, Order Order) StairsCase()
    {
        // Ground floor y 0 for x < 3, upper floor y 3 from x 3; a stair link from (1, 0, 0) to (3, 3, 0).
        var nav = new FakePathProvider { HeightAt = (x, _) => x >= 3 ? 3 : 0 }.Mesh(-10, -10, 10, 10);
        var linkStart = new Vec3(1, 0, 0);
        var linkEnd = new Vec3(3, 3, 0);
        nav.Answer(new Vec3(0, 0, 0), new Vec3(4, 3, 0), new[] { new Vec3(0, 0, 0), linkStart, linkEnd, new Vec3(4, 3, 0) },
                   new ulong[] { 0, NavLinkOwner.Stairs(0), 0, 0 }, 1 + Math.Sqrt(13) + 1);
        var order = Bed(w =>
        {
            var a = w["actors"]![0]!.AsObject();
            a["access"] = new JsonObject { ["x"] = 4, ["y"] = 3, ["z"] = 0, ["yaw"] = 90 };
            a["anchor"] = new JsonObject { ["x"] = 4.5, ["y"] = 3.45, ["z"] = 0, ["yaw"] = 90, ["root_offset"] = 0 };
            a["sequence"] = Seq(("walk", "", "", 0), ("entry", "lie", "lie_down", 2.4), ("loop", "lie", "lie_idle", 0));
        });
        return (nav, order);
    }

    [Fact]
    public void link_refused()
    {
        var (nav, order) = StairsCase();
        var ride = new FakeRide("stairs", LinkRideState.Refused);
        var h = new OrderHarness(nav, new Dictionary<string, ILinkRide> { ["stairs"] = ride });
        Assert.True(h.Accept(order, lag: 0));
        h.RunThrough(3);
        AssertStates(h, (OrderState.Walk, 0), (OrderState.Abort, 43 / 60.0), (OrderState.Idle, 44 / 60.0));
        var abort = h.Frames.First(f => f.State == OrderState.Abort);
        Assert.Contains("link_refused", abort.Events);
        Assert.Equal(1, abort.Position.X, 6);
        Assert.Equal(0, abort.Position.Y, 6);
        Assert.Equal(1, ride.Begins);
    }

    [Fact]
    public void link_ride_requested_waits_at_the_foot()
    {
        var (nav, order) = StairsCase();
        var ride = new FakeRide("stairs", LinkRideState.Requested, requestedPolls: 30);
        var h = new OrderHarness(nav, new Dictionary<string, ILinkRide> { ["stairs"] = ride });
        Assert.True(h.Accept(order, lag: 0));
        h.RunThrough(1.0);
        Assert.Equal(OrderState.Walk, h.Player.State);
        Assert.Equal(1, h.Last!.Position.X, 6); // waiting at the link foot while the ride is requested
        h.RunThrough(8);
        Assert.Equal(1, ride.Begins);
        Assert.Contains(h.Events, e => e.Event == "arrived_access");
        Assert.DoesNotContain(h.Events, e => e.Event == "stuck");
        var entry = h.Frames.First(f => f.State == OrderState.Entry);
        Assert.Equal(4, entry.Position.X, 6);
        Assert.Equal(3, entry.Position.Y, 6);
    }

    [Fact]
    public void link_ride_aborts_on_a_new_order()
    {
        var (nav, order) = StairsCase();
        var ride = new FakeRide("stairs", LinkRideState.Riding);
        var h = new OrderHarness(nav, new Dictionary<string, ILinkRide> { ["stairs"] = ride });
        Assert.True(h.Accept(order, lag: 0));
        h.RunBefore(1.0);
        Assert.Equal(1, ride.Begins);
        Assert.True(h.Accept(Cancel("ord-c", 101)));
        Assert.Equal(1, ride.Aborts);
    }

    private sealed class LongExit : IClipDurations
    {
        public double? Seconds(string step, string poseKind, string poseKey) => step == "exit" ? 2.0 : null;
    }

    [Fact]
    public void clip_duration_overrides_nominal()
    {
        var h = new OrderHarness(OrderHarness.Floor(), clips: new LongExit());
        Assert.True(h.Accept(Bed(), lag: 0));
        h.RunThrough(8);
        AssertStates(h, (OrderState.Exit, 0), (OrderState.Walk, 2.0), (OrderState.Entry, 4.0), (OrderState.Loop, 6.4));
    }

    [Fact]
    public void walk_order_ends_at_the_goal()
    {
        var h = new OrderHarness(null);
        var walk = Bed(w =>
        {
            w["kind"] = "walk";
            w["target"] = new JsonObject { ["location_id"] = "loc-o", ["room_id"] = "r-a", ["level"] = 0, ["x"] = 0, ["y"] = 0, ["z"] = 2.8 };
            var a = w["actors"]![0]!.AsObject();
            a["access"] = null;
            a["anchor"] = null;
            a["sequence"] = Seq(("walk", "", "", 0), ("loop", "stand", "idle", 0));
        });
        Assert.True(h.Accept(walk, lag: 0));
        h.RunThrough(3);
        AssertStates(h, (OrderState.Walk, 0), (OrderState.Loop, 2.0));
        Assert.Equal(2.8, h.Last!.Position.Z, 6);
        Assert.Equal(0, h.Last!.YawDeg, 6); // walked along +z: atan2(0, 1) = 0
    }

    [Fact]
    public void no_path_waits_for_the_heal()
    {
        // The map's path ends 1.8 m short of the access (more than NavRoutePlanner.UnreachableM): no plan, the figure
        // stands where the exit left it until heal rule 2 blends it onto the access at flip + 5 = 10.6.
        var nav = OrderHarness.Floor().Answer(new Vec3(0, 0, 0), new Vec3(2.8, 0, 0),
                                              new[] { new Vec3(0, 0, 0), new Vec3(1, 0, 0) }, new ulong[] { 0, 0 }, 1);
        var h = new OrderHarness(nav);
        Assert.True(h.Accept(Bed(), lag: 0));
        h.RunThrough(14);
        Assert.Equal(1.2, EventTime(h, "no_path"), 6);
        Assert.Equal(1, h.Events.Count(e => e.Event == "no_path"));
        Assert.Equal(0, h.Frames[600].Position.X, 6);
        AssertStates(h, (OrderState.Exit, 0), (OrderState.Walk, 1.2), (OrderState.Entry, 10.6), (OrderState.Loop, 13.0));
    }

    [Fact]
    public void local_aborted_then_server_order_is_a_new_order()
    {
        // Review minor 1: an aborted local order is not running; the matching server order is case 1 and plays.
        var h = new OrderHarness(OrderHarness.Floor());
        Assert.True(h.Accept(Local(), lag: 0));
        h.RunBefore(0.6);
        h.Player.Refuse("slot_taken");
        Assert.Equal(OrderState.Abort, h.Player.State);
        Assert.True(h.Accept(Server("run-1", 0.3)));
        Assert.Equal("run-1", h.Player.Current!.Id);
        Assert.Equal(0.6, h.Player.IssuedLocal, 9); // a new clock: issued 100.6 = motion now, lag 0 at t 0.6
        Assert.Equal(OrderState.Walk, h.Tick().State);
        h.RunThrough(5);
        Assert.Contains(h.Events, e => e.Event == "entry_started");
    }

    [Fact]
    public void access_on_another_storey_is_no_path()
    {
        // Review minor 3: the floor mesh has only height 0; an access at y 3 has no mesh on its storey, the closest
        // map point (2.8, 0, 0) is 3 m below it (>= 1.5) -> no_path at 1.2, no walk onto the wrong storey.
        var h = new OrderHarness(OrderHarness.Floor());
        var up = Bed(w => w["actors"]![0]!["access"] = new JsonObject { ["x"] = 2.8, ["y"] = 3, ["z"] = 0, ["yaw"] = 90 });
        Assert.True(h.Accept(up, lag: 0));
        h.RunThrough(3);
        Assert.Equal(1.2, EventTime(h, "no_path"), 6);
        Assert.Equal(0, h.Last!.Position.X, 6);
    }

    [Fact]
    public void revision_changes_the_walking_speed()
    {
        // Review minor 4: revision 2 at t 2.0 doubles the speed to 2.8 m/s. Before the frame at 2.0 the figure has
        // walked (119/60 - 1.2) * 1.4 = 1.09667 m; the remaining 1.70333 m take 1.70333 / 2.8 = 0.60833 s from
        // 119/60 -> arrival 2.59167 (frame 2.6), Loop 2.59167 + 2.4 = 4.99167 (frame 5.0).
        var h = new OrderHarness(OrderHarness.Floor());
        Assert.True(h.Accept(Bed(), lag: 0));
        h.RunBefore(2.0);
        Assert.True(h.Accept(Bed(w =>
        {
            w["revision"] = 2;
            w["speed_m_s"] = 2.8;
        })));
        h.RunThrough(6);
        AssertStates(h, (OrderState.Exit, 0), (OrderState.Walk, 1.2), (OrderState.Entry, 2.6), (OrderState.Loop, 5.0));
    }
}
