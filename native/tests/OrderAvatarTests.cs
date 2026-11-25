using System;
using System.Linq;
using AnimaNative.Orders;
using AnimaNative.Overview;
using Xunit;

namespace AnimaNative.Tests;

/// <summary>
/// Plan E3 Task 6: the avatar's local furniture order on the order player (the controller around it is
/// <c>--check orders</c>, R2–R2d). Free floor (path = straight line), speed 1 m/s, frames of 1/60 s. Local order: start
/// (0, 0, 0), access (2, 0, 0) yaw 90, anchor (2.6, 0.5, 0) yaw 90, no exit — it walks 2 m in 2.0 s and then waits at
/// the access for the server's answer (awaits "answer").
/// </summary>
public class OrderAvatarTests
{
    private const double Frame = 1.0 / 60 + 1e-6;
    private const double TolM = 1.0 / 60 + 1e-6;   // one frame at 1 m/s

    private static OrderPoint P(double x, double y, double z, double yaw = 0) => new(x, y, z, yaw);

    internal static Order Local(int n = 1, OrderPoint? access = null, OrderPoint? anchor = null, double motionNow = 100)
        => LocalOrders.PropAction(n, motionNow, 1.0, new LocalPropAction(
            "Ona", 170, P(0, 0, 0), "r-b", 0, access ?? P(2, 0, 0, 90), anchor ?? P(2.6, 0.5, 0, 90), 0.4, "bridge", null,
            "seat", "sitting", "loc-1", "r-b", 0));

    /// <summary>The server's order for the same run: same kind, location and anchor, its own access, an entry of 1.0 s.</summary>
    private static Order Server(Order local, OrderPoint access, string id = "ord-a1", int revision = 1, string status = "approaching")
    {
        var actor = local.Actors[0] with
        {
            Access = access,
            Sequence = new[] { new OrderStep("walk", "", "", 0), new OrderStep("entry", "seat", "sitting", 1.0), new OrderStep("loop", "seat", "sitting", 0) },
        };
        return local with
        {
            Id = id, Revision = revision, Seq = 1, Status = status, Awaits = "", FlipS = local.IssuedS + 10,
            Actors = new[] { actor },
        };
    }

    [Fact]
    public void LocalOrderAdvancesWithoutAnswer()
    {
        var h = new OrderHarness(OrderHarness.Floor());
        var local = Local();
        Assert.True(local.IsLocal);
        Assert.Equal(LocalOrders.AwaitsAnswer, local.Awaits);
        Assert.Null(local.FlipS);
        h.Accept(local);
        var f = h.RunThrough(1.0);
        Assert.Equal(OrderState.Walk, f.State);
        Assert.True(Math.Abs(f.Position.X - 1.0) <= TolM, $"x {f.Position.X}");
        f = h.RunThrough(3.0);
        Assert.Equal(OrderState.WaitAccess, f.State);
        Assert.True(Math.Abs(f.Position.X - 2.0) <= TolM && Math.Abs(f.Position.Z) <= TolM, $"{f.Position}");
        // Walk from the first frame, the wait at 2 m / 1 m/s = 2.0 s; no entry without an answer.
        Assert.Equal(new[] { OrderState.Walk, OrderState.WaitAccess }, h.States.Select(s => s.State));
        Assert.True(Math.Abs(h.States[1].T - 2.0) <= 2 * Frame, $"wait at {h.States[1].T}");
        Assert.DoesNotContain(h.Events, e => e.Event == "entry_started");
    }

    [Fact]
    public void AnswerReplacesGoalNotClock()
    {
        var h = new OrderHarness(OrderHarness.Floor());
        var local = Local();
        h.Accept(local);
        h.RunBefore(0.6);
        double issued = h.Player.IssuedLocal;
        var before = h.Last!.Position;
        // The answer: the access 0.3 m to the side (> AccessDiffM 0.15) — only the walk goal changes.
        Assert.True(h.Accept(Server(local, P(2, 0, 0.3, 90))));
        Assert.Equal("ord-a1", h.Player.Current!.Id);
        Assert.Equal(issued, h.Player.IssuedLocal);
        Assert.Equal(new Vec3(2, 0, 0.3), h.Player.WalkGoal);
        var f = h.Tick();
        Assert.Equal(OrderState.Walk, f.State);
        Assert.True(double.Hypot(f.Position.X - before.X, f.Position.Z - before.Z) <= TolM + 1e-9, $"{before} -> {f.Position}");
        // Arrival at 2 m − the shown 0.6 m … the clock never restarted: the access is reached at 2.0 + the 0.3 m detour's
        // share; the entry (1.0 s) then the loop.
        h.RunThrough(4.0);
        Assert.Equal(new[] { OrderState.Walk, OrderState.Entry, OrderState.Loop }, h.States.Select(s => s.State));
        Assert.True(Math.Abs(h.Frames.First(x => x.State == OrderState.Entry).Position.Z - 0.3) <= 1e-9);
    }

    [Fact]
    public void AnswerWithin015KeepsGoal()
    {
        var h = new OrderHarness(OrderHarness.Floor());
        var local = Local();
        h.Accept(local);
        h.RunBefore(0.6);
        double issued = h.Player.IssuedLocal;
        Assert.True(h.Accept(Server(local, P(2, 0, 0.1, 90))));
        Assert.Equal("ord-a1", h.Player.Current!.Id);
        Assert.Equal(issued, h.Player.IssuedLocal);
        Assert.Equal(new Vec3(2, 0, 0), h.Player.WalkGoal);
    }

    [Fact]
    public void RefusalAbortsAndTurnsAway()
    {
        var h = new OrderHarness(OrderHarness.Floor());
        h.Accept(Local());
        h.RunBefore(0.8);
        h.Player.Refuse("no_free_slot");
        var f = h.Tick();
        Assert.Equal(OrderState.Abort, f.State);
        Assert.Contains("aborted", f.Events);
        Assert.Equal("no_free_slot", h.Player.RefusalReason);
        Assert.True(Math.Abs(f.Position.X - 0.8) <= TolM, $"x {f.Position.X}");
        h.RunThrough(4.0);
        Assert.Equal(new[] { OrderState.Walk, OrderState.Abort, OrderState.Idle }, h.States.Select(s => s.State));
        Assert.True(Math.Abs(h.States[1].T - 0.8) <= Frame);
        // Away from the furniture: from (0.8, 0) the anchor (2.6, 0) lies on +x, so away = −x = atan2(−1, 0) = −90°.
        Assert.Equal(-90.0, LocalOrders.TurnAwayYawDeg(new Vec3(0.8, 0, 0), new Vec3(2.6, 0.5, 0))!.Value, 9);
        Assert.Null(LocalOrders.TurnAwayYawDeg(new Vec3(1, 0, 1), new Vec3(1, 3, 1)));
    }

    [Fact]
    public void SecondClickReplacesLocalOrder()
    {
        var h = new OrderHarness(OrderHarness.Floor());
        h.Accept(Local(1));
        h.RunBefore(0.5);
        var before = h.Last!.Position;
        // The second click: local:2 to the access B (0, 0, 2) — a new id, case 1 of the accept (no answer involved).
        var b = Local(2, access: P(0, 0, 2, 0), anchor: P(0, 0.5, 2.6, 0), motionNow: 100.5);
        Assert.Equal("local:2", b.Id);
        Assert.True(h.Accept(b));
        Assert.Equal("local:2", h.Player.Current!.Id);
        Assert.True(Math.Abs(h.Player.IssuedLocal - 0.5) <= 1e-9);
        var f = h.Tick();
        Assert.True(double.Hypot(f.Position.X - before.X, f.Position.Z - before.Z) <= TolM + 1e-9, $"{before} -> {f.Position}");
        // (0.5, 0) → (0, 2): √(0.25 + 4) = 2.061553 m → waiting from 0.5 + 2.061553 = 2.561553 s.
        f = h.RunThrough(4.0);
        Assert.Equal(OrderState.WaitAccess, f.State);
        Assert.True(Math.Abs(f.Position.X) <= TolM && Math.Abs(f.Position.Z - 2) <= TolM, $"{f.Position}");
        Assert.Equal(new[] { OrderState.Walk, OrderState.WaitAccess }, h.States.Select(s => s.State));
        Assert.True(Math.Abs(h.States[1].T - 2.561553) <= 2 * Frame, $"wait at {h.States[1].T}");
    }

    [Fact]
    public void ArrivalHoldWaitsForEntering()
    {
        // A server order for a figure that reports its arrival, still approaching: under the journey server (until
        // plan E3 Task 7) the avatar waits at the access until the revision "entering" comes.
        var server = Server(Local(), P(2, 0, 0, 90));
        var held = LocalOrders.HoldForArrival(server, "Ona");
        Assert.Equal(LocalOrders.AwaitsArrival, held.Awaits);
        Assert.Null(held.FlipS);
        Assert.Same(server, LocalOrders.HoldForArrival(server, "Uli"));
        var active = server with { Status = "active" };
        Assert.Same(active, LocalOrders.HoldForArrival(active, "Ona"));
        var npc = server with { Actors = new[] { server.Actors[0] with { ReportsArrival = false } } };
        Assert.Same(npc, LocalOrders.HoldForArrival(npc, "Ona"));

        var h = new OrderHarness(OrderHarness.Floor());
        h.Accept(held);
        var f = h.RunThrough(3.0);
        Assert.Equal(OrderState.WaitAccess, f.State);
        var entering = Server(Local(), P(2, 0, 0, 90), revision: 2, status: "entering");
        Assert.Same(entering, LocalOrders.HoldForArrival(entering, "Ona"));
        Assert.True(h.Accept(entering));
        h.RunThrough(3.5);
        Assert.Equal(new[] { OrderState.Walk, OrderState.WaitAccess, OrderState.Entry },
                     h.States.Select(s => s.State));
        Assert.True(Math.Abs(h.States[2].T - 3.0) <= 2 * Frame, $"entry at {h.States[2].T}");
    }

    [Fact]
    public void LocalWalkStandsAtItsGoal()
    {
        // (0, 0) → (3, 4): 5 m at 1 m/s → the loop on the goal from 5.0 s on, no answer awaited.
        var walk = LocalOrders.Walk(3, 100, 1.0, "Ona", P(0, 0, 0), "r-b", 0, P(3, 0, 4), "loc-1", "r-b", 0);
        Assert.Equal("local:3", walk.Id);
        Assert.Equal("walk", walk.Kind);
        Assert.Equal("", walk.Awaits);
        var h = new OrderHarness(OrderHarness.Floor());
        h.Accept(walk);
        var f = h.RunThrough(6.0);
        Assert.True(Math.Abs(f.Position.X - 3) <= TolM && Math.Abs(f.Position.Z - 4) <= TolM, $"{f.Position}");
        Assert.Equal(new[] { OrderState.Walk, OrderState.Loop }, h.States.Select(s => s.State));
        Assert.True(Math.Abs(h.States[1].T - 5.0) <= 2 * Frame, $"loop at {h.States[1].T}");
    }

    [Fact]
    public void ServerOrderCarriesItsExecutionId()
    {
        var w = OrderParseTests.Wire();
        w["target"]!["execution_id"] = "exec-7";
        Assert.Equal("exec-7", OrderParseTests.Parse(w)!.ExecutionId);
        Assert.Equal("", Local().ExecutionId);
    }
}
