using System;
using System.Collections.Generic;
using System.Linq;
using AnimaNative.Nav;
using AnimaNative.Orders;
using AnimaNative.Overview;
using AnimaNative.Scatter;
using Xunit;

namespace AnimaNative.Tests;

/// <summary>
/// <see cref="OrderWalk"/>, the click walk's path (<see cref="ClickWalkPath"/>) and, moved here from the deleted
/// <c>NavRouteTests</c> (plan E3 Task 10, the E2 walk player <c>NavRoute</c> is gone), <see cref="NavClamp"/> and
/// <see cref="NavRoutePlanner"/> on <see cref="FakePathProvider"/> worlds. Expectations derived by hand:
/// <code>
///   (from NavRouteTests, verbatim)
///   clamp: tol 0.02, eps 1e-4, distances horizontal; a Closest whose |dy| ≥ storeyHeight/2 counts as infinitely far
///     mesh x 0…10, z 0…10, hole x 4…6, z 4…6:
///       (5, 3.9) → (5, 4.1): dTo = 0.1 &gt; tol, dFrom = 0, 0.1 &gt; 0 + eps, dFrom ≤ tol → Closest(5, 4.1) = (5, 4.0)
///       (5, 4.5) → (5, 4.3): dFrom = 0.5 (to z 4 or z 6 … nearest edge z 4 at 0.5), dTo = 0.3 ≤ 0.5 → to
///       (5, 4.3) → (5, 4.6): dFrom = 0.3, dTo = 0.4 &gt; 0.3 + eps, dFrom &gt; tol → from
///       (5, 4.3) → (5.1, 4.3): both 0.3 (x edges are 0.9 / 1.1 away) → to
///   planner: on mesh = horizontal distance to Closest ≤ 0.3; unreachable = path end &gt; 0.5 from the goal
///     furniture hole x 4…8, z 4…5.5, click (6, 4.6): edges z 4 at 0.6, z 5.5 at 0.9, x 4 / 8 at 2 → Goal (6, 0, 4)
///     outside doors (0, 5), (10, 5), from (2, 0, 5), target (−3, 0, 5): via (0, 5) = Query 2 + straight 3 = 5;
///       via (10, 5) = 8 + 13 = 21 → (0, 5) wins, Length 5
///   (the NavRoute cases on OrderWalk) stuck = horizontal speed &lt; 0.05 m/s for 2 s (OrderPlayer.StuckSpeedMS /
///     StuckS, the values of NavRoute); the first failure asks for a replan, the second one is Stuck — counted over the
///     whole walk, a replan keeps count and clock (final review E2, I-2). Unlike NavRoute, whose caller moved the figure
///     and whose stuck baseline was the plan's start, OrderWalk moves the figure itself (speed · dt per step, landing
///     on corners without overshoot), so "standing still" is a walk slower than 0.05 m/s (0.04 m/s here) and the
///     FIRST step only takes the baseline: every stuck sequence of NavRoute shifts by one step.
///     NavRoute's "Arrived 0.2 m before the corner" was its caller's corner tolerance (ClickMove.GoalArriveM); OrderWalk
///     walks onto the goal itself and reports the unused part of the step (LeftoverS).
///   links: AtLink / RideRequested / LinkResult(bool) / LinkFinished of NavRoute become the ILinkRide protocol (review
///     W5): at the link foot (≤ 0.4 m, Stairs.RideArriveM, 3D) Begin → Requested (the walk holds, no stuck, no
///     deviation) → Riding → Done (the figure at the link's end, the walk goes on) or Refused (LinkRefused at the foot).
/// </code>
/// The clamp rules of plan E3 Task 5 (review minor 1) and the click walk's path are derived in their tests.
/// </summary>
public class OrderWalkTests
{
    private const double Eps = 1e-9;

    private static FakePathProvider Room() => new FakePathProvider().Mesh(0, 0, 10, 10);

    private static void Same(P2 expected, P2 actual)
    {
        Assert.Equal(expected.X, actual.X, Eps);
        Assert.Equal(expected.Z, actual.Z, Eps);
    }

    private static void Same(Vec3 expected, Vec3 actual)
    {
        Assert.Equal(expected.X, actual.X, Eps);
        Assert.Equal(expected.Y, actual.Y, Eps);
        Assert.Equal(expected.Z, actual.Z, Eps);
    }

    private static bool AllInside(double x, double z) => true;

    private static bool InsideRoom(double x, double z) => x >= 0 && x <= 10 && z >= 0 && z <= 10;

    private const double Dt = 0.1;
    private static readonly IReadOnlyDictionary<string, ILinkRide> NoRides = new Dictionary<string, ILinkRide>();

    private static (double ArrivedS, List<WalkStep> Steps) WalkToEnd(OrderWalk walk, Vec3 start, IPathProvider nav, int maxSteps = 200)
    {
        var steps = new List<WalkStep>();
        var p = start;
        for (int i = 1; i <= maxSteps; i++)
        {
            var s = walk.Step(p, Dt, nav);
            steps.Add(s);
            p = s.Pos;
            if (s.Arrived) return (i * Dt - walk.LeftoverS, steps);
        }
        return (double.NaN, steps);
    }

    [Fact]
    public void AStartOffTheMeshIsWalkedOntoThePathNotPushedOnInOneFrame()
    {
        // Mesh x 0…10, z −1…1. The figure stands 0.2 m off its west edge at (−0.2, 0); the path starts on the edge.
        // Corner 0 first: the step goes to (−0.1, 0) — it lies 0.1 off the mesh, no further than the 0.2 the figure
        // stood, so it is not clamped. Length 0.2 + 5 = 5.2 m at 1 m/s → arrival at 5.2 s.
        // (Corner 1 first and the old clamp put the figure onto (0, 0) in the first frame: 5.1 s.)
        var nav = new FakePathProvider().Mesh(0, -1, 10, 1);
        var plan = new NavPlan(new NavStep[] { new NavWalk(new[] { new Vec3(0, 0, 0), new Vec3(5, 0, 0) }) }, new Vec3(5, 0, 0), 5);
        var walk = new OrderWalk(plan, new Vec3(5, 0, 0), 1.0, NoRides);
        var (arrived, steps) = WalkToEnd(walk, new Vec3(-0.2, 0, 0), nav);
        Assert.Equal(-0.1, steps[0].Pos.X, 9);
        Assert.Equal(5.2, arrived, 6);
        Assert.DoesNotContain(steps, s => s.NeedsReplan || s.Stuck);
    }

    [Fact]
    public void MeshEdgeNoiseBelowAMillimetreDoesNotBlock()
    {
        // The path runs along the mesh's north edge but its corners lie 0.5 mm outside it (z = 1.0005, float noise of
        // a boundary corner). Every step lands 0.5 mm off ≤ 0 + ClampNoiseM (1 mm): never clamped, never blocked, so no
        // replan after the 1 s blockade. Length 0.0005 (start → corner 0) + 5 = 5.0005 m → arrival at 5.0005 s.
        var nav = new FakePathProvider().Mesh(0, -1, 10, 1);
        var plan = new NavPlan(new NavStep[] { new NavWalk(new[] { new Vec3(0, 0, 1.0005), new Vec3(5, 0, 1.0005) }) },
                               new Vec3(5, 0, 1.0005), 5);
        var walk = new OrderWalk(plan, new Vec3(5, 0, 1.0005), 1.0, NoRides);
        var (arrived, steps) = WalkToEnd(walk, new Vec3(0, 0, 1.0), nav);
        Assert.Equal(5.0005, arrived, 6);
        Assert.DoesNotContain(steps, s => s.NeedsReplan || s.Stuck);
        Assert.Equal(1.0005, steps[^1].Pos.Z, 9);
    }

    [Fact]
    public void AStepThatLeavesTheMeshBeyondTheNoiseIsStillClamped()
    {
        // From (0, 0) towards (5, 1.2): the path leaves the mesh (z ≤ 1) at x = 5/1.2 = 4.1667. Each frame takes
        // 0.1 · 1.2 / √(5² + 1.2²) = 0.0233 m of z — far more than 1 mm beyond where the figure stood — so every step
        // past the edge is clamped back onto z = 1 (a blockade): z never exceeds 1, and the blockade asks for a replan.
        var nav = new FakePathProvider().Mesh(0, -1, 10, 1);
        var plan = new NavPlan(new NavStep[] { new NavWalk(new[] { new Vec3(0, 0, 0), new Vec3(5, 0, 1.2) }) }, new Vec3(5, 0, 1.2), 5.142);
        var walk = new OrderWalk(plan, new Vec3(5, 0, 1.2), 1.0, NoRides);
        var (_, steps) = WalkToEnd(walk, new Vec3(0, 0, 0), nav, maxSteps: 80);
        Assert.All(steps, s => Assert.True(s.Pos.Z <= 1 + 1e-9, $"z {s.Pos.Z}"));
        Assert.Contains(steps, s => s.NeedsReplan);
    }

    // ---- the NavRoute cases on OrderWalk (from NavRouteTests) --------------------------------------------------------

    /// <summary>One step's outcome as a word, for the sequences.</summary>
    private static string Word(WalkStep s)
        => s.LinkRefused ? "refused" : s.Arrived ? "arrived" : s.Stuck ? "stuck" : s.NeedsReplan ? "replan" : s.AtLink ? "link" : "none";

    /// <summary>The straight plan (0, 0, 0) → (10, 0, 0) of NavRouteTests.Straight, from <paramref name="from"/>.</summary>
    private static NavPlan StraightPlan(Vec3? from = null)
        => NavRoutePlanner.Plan(Room(), from ?? new Vec3(0, 0, 0), new Vec3(10, 0, 0), AllInside, Array.Empty<P2>(), 0)!;

    private static OrderWalk StraightWalk(double speed)
        => new(StraightPlan(), new Vec3(10, 0, 0), speed, NoRides);

    /// <summary>Steps the walk <paramref name="n"/> times from where the last step left the figure.</summary>
    private static List<WalkStep> Run(OrderWalk walk, ref Vec3 p, int n, double dt, IPathProvider nav)
    {
        var steps = new List<WalkStep>();
        for (int i = 0; i < n; i++)
        {
            var s = walk.Step(p, dt, nav);
            steps.Add(s);
            p = s.Pos;
        }
        return steps;
    }

    [Fact]
    public void StuckTwiceIsStuck()
    {
        // NavRoute: standing still with dt 0.5 → ticks 1–3 None, tick 4 (2.0 s) Replan, ticks 5–7 None, tick 8 Abort.
        // OrderWalk at 0.04 m/s (0.02 m per 0.5 s step, below 0.05 m/s): step 1 takes the baseline, steps 2–5 count
        // 0.5 s each → Replan at step 5 (2.0 s, StuckCount 1); the replan from where it stands keeps count and clock,
        // steps 6–9 → Stuck at step 9 (the second failure).
        var walk = StraightWalk(0.04);
        var p = new Vec3(0, 0, 0);
        var first = Run(walk, ref p, 5, 0.5, Room());
        Assert.Equal(new[] { "none", "none", "none", "none", "replan" }, first.Select(Word));
        Assert.Equal(1, walk.StuckCount);
        walk.Replan(StraightPlan(p));
        var second = Run(walk, ref p, 4, 0.5, Room());
        Assert.Equal(new[] { "none", "none", "none", "stuck" }, second.Select(Word));
        Assert.Equal(2, walk.StuckCount);
        Assert.Equal(0.04 * 0.5 * 9, p.X, 9);
    }

    [Fact]
    public void ReplannedWalkKeepsTheStuckCount()
    {
        // NavRoute: a replan after the first stuck hands StuckCount 1 to the new route: its first 2 s stuck (four 0.5 s
        // frames) aborts instead of replanning again. OrderWalk.Replan keeps the count (and the baseline), so the four
        // steps after it end in Stuck — the sequence of NavRoute verbatim.
        var walk = StraightWalk(0.04);
        var p = new Vec3(0, 0, 0);
        Run(walk, ref p, 5, 0.5, Room());
        Assert.Equal(1, walk.StuckCount);
        walk.Replan(StraightPlan(p));
        Assert.Equal(new[] { "none", "none", "none", "stuck" }, Run(walk, ref p, 4, 0.5, Room()).Select(Word));
    }

    [Fact]
    public void MovingIsNotStuck()
    {
        // 0.2 m/s (0.1 m per 0.5 s step) ≥ 0.05 m/s: eight steps, nothing to report.
        var walk = StraightWalk(0.2);
        var p = new Vec3(0, 0, 0);
        Assert.All(Run(walk, ref p, 8, 0.5, Room()), s => Assert.Equal("none", Word(s)));
        Assert.Equal(0.8, p.X, 9);
    }

    [Fact]
    public void DeviationReplans()
    {
        // The figure is put 0.9 m off the segment (0, 0)–(10, 0): ≤ 1 m (OrderPlayer.ReplanDeviationM), it walks on;
        // 1.2 m off → Replan, and the step does not move it. (The first step from the start takes the walk past
        // corner 0, which skips the deviation test.)
        var walk = StraightWalk(1);
        Assert.Equal("none", Word(walk.Step(new Vec3(0, 0, 0), 1, Room())));
        Assert.Equal("none", Word(walk.Step(new Vec3(4, 0, 0.9), 1, Room())));
        var s = walk.Step(new Vec3(5, 0, 1.2), 1, Room());
        Assert.Equal("replan", Word(s));
        Same(new Vec3(5, 0, 1.2), s.Pos);
    }

    [Fact]
    public void ArrivesAtGoal()
    {
        // 1 m/s: 9.7 s → (9.7, 0, 0); 0.15 s → (9.85, 0, 0), still walking (NavRoute's caller called that Arrived,
        // 0.2 m early); 0.2 s → on the goal (10, 0, 0) after 0.15 s of it: LeftoverS 0.05.
        var walk = StraightWalk(1);
        var a = walk.Step(new Vec3(0, 0, 0), 9.7, Room());
        Assert.Equal("none", Word(a));
        Assert.Equal(9.7, a.Pos.X, 9);
        var b = walk.Step(a.Pos, 0.15, Room());
        Assert.Equal("none", Word(b));
        Assert.Equal(9.85, b.Pos.X, 9);
        var c = walk.Step(b.Pos, 0.2, Room());
        Assert.Equal("arrived", Word(c));
        Same(new Vec3(10, 0, 0), c.Pos);
        Assert.Equal(0.05, walk.LeftoverS, 9);
    }

    [Fact]
    public void ZeroFrameIsNeutralForStuck()
    {
        // NavRoute: 3 still ticks of 0.5 s (1.5 s), a dt 0 frame, then one more 0.5 s → 2.0 s → Replan. OrderWalk: the
        // baseline step, then the same: 3 × 0.5 s, a dt 0 step (neither counts nor moves), one more → Replan.
        var walk = StraightWalk(0.04);
        var p = new Vec3(0, 0, 0);
        Assert.All(Run(walk, ref p, 4, 0.5, Room()), s => Assert.Equal("none", Word(s)));
        var zero = walk.Step(p, 0, Room());
        Assert.Equal("none", Word(zero));
        Same(p, zero.Pos);
        Assert.Equal("replan", Word(walk.Step(p, 0.5, Room())));
    }

    // ---- links over the ILinkRide protocol (NavRoute: AtLink / RideRequested / LinkResult / LinkFinished) --------------

    // A, B, L1, L2, C and LinkPlan() are the planner section's (below).

    private static NavPlan LinkFirstPlan()
    {
        var nav = Room().Answer(A, C, new[] { L1, L2, C }, new ulong[] { 65536, 0, 0 }, 16);
        return NavRoutePlanner.Plan(nav, A, C, AllInside, Array.Empty<P2>(), 0)!;
    }

    /// <summary>
    /// A ride the test answers: <see cref="Begin"/> answers <see cref="BeginAnswer"/>, every <see cref="Poll"/> answers
    /// <see cref="State"/>; while Riding it puts the figure at <see cref="RidingAt"/> (2 m off the walk, up the stairs),
    /// at Done at the link's end.
    /// </summary>
    private sealed class FakeRide : ILinkRide
    {
        public LinkRideState BeginAnswer = LinkRideState.Requested;
        public LinkRideState State = LinkRideState.Requested;
        public Vec3 RidingAt = new(5, 2, 3);
        public readonly List<NavLink> Begun = new();
        public int Aborts;
        private NavLink? _link;
        public string Kind => "stairs";

        public LinkRideState Begin(string actor, NavLink link)
        {
            Begun.Add(link);
            _link = link;
            return BeginAnswer;
        }

        public LinkRideState Poll(ref Vec3 pos, double dt, double speedMS)
        {
            if (State == LinkRideState.Riding) pos = RidingAt;
            else if (State == LinkRideState.Done && _link is { } l) pos = l.End;
            return State;
        }

        public void Abort() => Aborts++;
    }

    private static (OrderWalk Walk, FakeRide Ride) LinkWalk(NavPlan plan)
    {
        var ride = new FakeRide();
        var rides = new Dictionary<string, ILinkRide> { [OrderWalk.KindOf(65536)] = ride };
        return (new OrderWalk(plan, C, 1, rides), ride);
    }

    [Fact]
    public void PlanLinkIsTheStairs() => Assert.Equal("stairs", OrderWalk.KindOf(65536));

    [Fact]
    public void LinkWaitsForFinish()
    {
        // 1 m/s, steps of 1 s from A: (2, 0, 1), B (3, 0, 1), (4, 0, 1), L1 — the link foot: Begin → Requested (AtLink).
        // Six steps waiting for the answer and six riding (2 m off the A–L1 line, no progress): AtLink, no stuck, no
        // deviation. Done puts the figure on L2; then L2 → C = 4√2 = 5.656854 m: five steps of 1 m, the sixth arrives
        // after 0.656854 s of it → LeftoverS 0.343146.
        var (walk, ride) = LinkWalk(LinkPlan());
        var p = A;
        var walkIn = Run(walk, ref p, 4, 1, Room());
        Assert.Equal(new[] { "none", "none", "none", "link" }, walkIn.Select(Word));
        Same(B, walkIn[1].Pos);
        Same(L1, p);
        var begun = Assert.Single(ride.Begun);
        Assert.Equal(65536UL, begun.Owner);
        Same(L1, begun.Start);
        Same(L2, begun.End);
        Assert.True(walk.Riding);
        Assert.All(Run(walk, ref p, 6, 1, Room()), s => Assert.Equal("link", Word(s)));
        Same(L1, p);
        ride.State = LinkRideState.Riding;
        Assert.All(Run(walk, ref p, 6, 1, Room()), s => Assert.Equal("link", Word(s)));
        Same(new Vec3(5, 2, 3), p);
        ride.State = LinkRideState.Done;
        var done = walk.Step(p, 1, Room());
        Assert.Equal("none", Word(done));
        Same(L2, done.Pos);
        Assert.False(walk.Riding);
        p = done.Pos;
        var after = Run(walk, ref p, 6, 1, Room());
        Assert.Equal(new[] { "none", "none", "none", "none", "none", "arrived" }, after.Select(Word));
        Same(C, p);
        Assert.Equal(1 - (4 * Math.Sqrt(2) - 5), walk.LeftoverS, 9);
    }

    [Fact]
    public void LinkFirstWalkRequestsRideWhenClose()
    {
        // Path [L1, L2, C] with the link on its first point: the leading one-point walk is dropped, the plan starts
        // with Link(L1, L2). From (4.8, 0, 1), 0.2 from L1 (≤ 0.4): the first step begins the ride.
        var (walk, ride) = LinkWalk(LinkFirstPlan());
        var s = walk.Step(new Vec3(4.8, 0, 1), 1, Room());
        Assert.Equal("link", Word(s));
        Same(new Vec3(4.8, 0, 1), s.Pos);
        Assert.Single(ride.Begun);
    }

    [Fact]
    public void LinkFirstWalkGoesToTheLinkFoot()
    {
        // NavRoute counted stuck time while its caller approached a leading link (and aborted a start that never got
        // there); OrderWalk walks the approach itself: from A, 4 m from L1 at 1 m/s → (2, 0, 1), (3, 0, 1), (4, 0, 1),
        // then L1 and the ride's Begin in the fourth step.
        var (walk, ride) = LinkWalk(LinkFirstPlan());
        var p = A;
        Assert.Equal(new[] { "none", "none", "none", "link" }, Run(walk, ref p, 4, 1, Room()).Select(Word));
        Same(L1, p);
        Assert.Single(ride.Begun);
    }

    [Fact]
    public void LinkRefusedEndsAtTheLinkFoot()
    {
        // NavRoute: LinkResult(false) → Abort. The ride answers Refused after Requested: LinkRefused at the foot L1,
        // and every later step stays there (review W5).
        var (walk, ride) = LinkWalk(LinkPlan());
        var p = A;
        Run(walk, ref p, 4, 1, Room());
        ride.State = LinkRideState.Refused;
        var s = walk.Step(p, 1, Room());
        Assert.Equal("refused", Word(s));
        Same(L1, s.Pos);
        Assert.False(walk.Riding);
        Assert.Equal("refused", Word(walk.Step(s.Pos, 1, Room())));
    }

    [Fact]
    public void LinkRefusedAtBeginEndsAtTheLinkFoot()
    {
        // The ride refuses at once (Begin → Refused): the fourth step ends at L1 with LinkRefused.
        var (walk, ride) = LinkWalk(LinkPlan());
        ride.BeginAnswer = LinkRideState.Refused;
        var p = A;
        Assert.Equal(new[] { "none", "none", "none", "refused" }, Run(walk, ref p, 4, 1, Room()).Select(Word));
        Same(L1, p);
    }

    // ---- blockades (plan E3 Task 10: the click walk ends at its second failure) ---------------------------------------

    /// <summary>Mesh x 0…10, z −1…1 cut by a hole x 3…4 over its whole width: a straight path to (6, 0, 0) runs into it.</summary>
    private static FakePathProvider Cut() => new FakePathProvider().Mesh(0, -1, 10, 1).Hole(3, -1, 4, 1);

    [Fact]
    public void BlockadesAndStuckAreCountedApart()
    {
        // 0.4 m/s, steps of 0.25 s (0.1 m) from (2.95, 0, 0): step 1 aims at (3.05, 0, 0), 0.05 inside the hole →
        // clamped to (3, 0, 0) (a blockade, the baseline step); steps 2–5 aim 0.1 deep and are clamped back onto
        // (3, 0, 0): no progress (stuck clock 0.25 … 1.0 s) and blocked 0.5 … 1.25 s → the blockade (> 1 s) asks for a
        // replan at step 5: Blockades 1, StuckCount 0. The replan keeps the stuck clock (1.0 s): steps 6–9 add 1.0 s →
        // 2.0 s at step 9 → the first stuck (StuckCount 1, replan); the blockade clock started again at the replan and
        // is at 1.0 s there (not > 1).
        var nav = Cut();
        var plan = new NavPlan(new NavStep[] { new NavWalk(new[] { new Vec3(2.95, 0, 0), new Vec3(6, 0, 0) }) }, new Vec3(6, 0, 0), 3.05);
        var walk = new OrderWalk(plan, new Vec3(6, 0, 0), 0.4, NoRides);
        var p = new Vec3(2.95, 0, 0);
        var first = Run(walk, ref p, 5, 0.25, nav);
        Assert.Equal(new[] { "none", "none", "none", "none", "replan" }, first.Select(Word));
        Same(new Vec3(3, 0, 0), p);
        Assert.Equal(1, walk.Blockades);
        Assert.Equal(0, walk.StuckCount);
        walk.Replan(new NavPlan(new NavStep[] { new NavWalk(new[] { p, new Vec3(6, 0, 0) }) }, new Vec3(6, 0, 0), 3));
        var second = Run(walk, ref p, 4, 0.25, nav);
        Assert.Equal(new[] { "none", "none", "none", "replan" }, second.Select(Word));
        Assert.Equal(1, walk.Blockades);
        Assert.Equal(1, walk.StuckCount);
    }

    [Fact]
    public void OrderPlayerCountsTheWalkFailures()
    {
        // The same walk as a local walk order (speed 0.4, ticks every 0.25 s, the player replans by itself from where
        // the figure stands): WalkFailures = blockades + stuck = 1 after tick 5, 2 after tick 9.
        var nav = Cut();
        var player = new OrderPlayer("Walker", NoClips.Instance, NoRides);
        var order = LocalOrders.Walk(1, 0, 0.4, "Walker", new OrderPoint(2.95, 0, 0, 90), "", 0, new OrderPoint(6, 0, 0, 90), "loc", "", 0);
        Assert.True(player.Accept(order, 0, 0, new Vec3(2.95, 0, 0), 90));
        for (int i = 1; i <= 5; i++) player.Tick(0.25 * i, nav);
        Assert.Equal(1, player.WalkFailures);
        for (int i = 6; i <= 9; i++) player.Tick(0.25 * i, nav);
        Assert.Equal(2, player.WalkFailures);
        Assert.Equal(OrderState.Walk, player.State);
    }

    private sealed class NoClips : IClipDurations
    {
        public static readonly NoClips Instance = new();
        public double? Seconds(string step, string poseKind, string poseKey) => null;
    }

    // ---- the click walk's path (plan E3 Task 10) --------------------------------------------------------------------

    /// <summary>The click walk of NavRouteTests.OutsideTargetRoutesViaOutsideDoor as a path: from (2, 0, 5) in the room
    /// x 0…10, z 0…10 (the footprint), outside doors (0, 5) and (10, 5), the ground at y 0.</summary>
    private static (ClickWalkPath Path, FakePathProvider Nav) DoorWorld()
    {
        var from = new Vec3(2, 0, 5);
        var nav = Room().Answer(from, new Vec3(0, 0, 5), new[] { from, new Vec3(1, 0, 5), new Vec3(0, 0, 5) }, new ulong[] { 0, 0, 0 }, 2);
        return (new ClickWalkPath(() => nav, InsideRoom, new[] { new P2(0, 5), new P2(10, 5) }, (_, _) => 0), nav);
    }

    [Fact]
    public void ClickPathQueriesAnOutsideTargetThroughTheDoor()
    {
        // Planner case 2: via (0, 5) = 2 + 3 = 5 beats via (10, 5) = 21; the path is the door path plus the straight
        // piece to the target, all owners 0.
        var (path, _) = DoorWorld();
        var q = path.Query(new Vec3(2, 0, 5), new Vec3(-3, 0, 5));
        Assert.Equal(new[] { new Vec3(2, 0, 5), new Vec3(1, 0, 5), new Vec3(0, 0, 5), new Vec3(-3, 0, 5) }, q.Points);
        Assert.All(q.Owners, o => Assert.Equal(0UL, o));
        Assert.Equal(5, q.Length, Eps);
    }

    [Fact]
    public void ClickPathKeepsLinksOfAPlanAsOwners()
    {
        // A plan through a link flattens back into the path's points with the owner on the link's start: the planner
        // splits it again into the same three sections.
        var nav = Room().Answer(A, C, new[] { A, B, L1, L2, C }, new ulong[] { 0, 0, 65536, 0, 0 }, 20);
        var path = new ClickWalkPath(() => nav, AllInside, Array.Empty<P2>(), (_, _) => 0);
        var q = path.Query(A, C);
        Assert.Equal(new[] { A, B, L1, L2, C }, q.Points);
        Assert.Equal(new ulong[] { 0, 0, 65536, 0, 0 }, q.Owners);
    }

    [Fact]
    public void ClickPathIsTheMapInsideAndThePointOutside()
    {
        // Inside the footprint the map answers (hole x 4…6, z 4…6: (5, 4.1) → its edge (5, 4)); outside every point is
        // on the path (no clamp): (−3, 0, 5) stays itself for Closest and ClosestOnVertical.
        var nav = Room().Hole(4, 4, 6, 6);
        var path = new ClickWalkPath(() => nav, InsideRoom, Array.Empty<P2>(), (_, _) => 0);
        Same(new Vec3(5, 0, 4), path.Closest(new Vec3(5, 0, 4.1)));
        Same(new Vec3(5, 0, 4), path.ClosestOnVertical(new Vec3(5, 0, 4.1), 1));
        Same(new Vec3(-3, 0, 5), path.Closest(new Vec3(-3, 0, 5)));
        Same(new Vec3(-3, 0, 5), path.ClosestOnVertical(new Vec3(-3, 0, 5), 1));
        Assert.True(path.Ready);
        Assert.False(new ClickWalkPath(() => null, InsideRoom, Array.Empty<P2>(), (_, _) => 0).Ready);
    }

    [Fact]
    public void ClickPathBetweenTwoOutsidePointsIsStraight()
    {
        // From outside the footprint to outside it (a replan on the straight piece beyond the door): the straight line.
        var (path, _) = DoorWorld();
        var q = path.Query(new Vec3(-1, 0, 5), new Vec3(-3, 0, 6));
        Assert.Equal(new[] { new Vec3(-1, 0, 5), new Vec3(-3, 0, 6) }, q.Points);
        Assert.Equal(Math.Sqrt(5), q.Length, Eps);
    }

    [Fact]
    public void LocalWalkOrderOverTheClickPathLeavesThroughTheDoor()
    {
        // A local walk order (1 m/s) from (2, 0, 5) to (−3, 0, 5) on the click path: the player's own planning (the
        // target's closest point on the path = the target itself) gets the door route, Length 5; the walk arrives at
        // 5 s, walked 5 m, and stands on the target (the chain's loop).
        var (path, _) = DoorWorld();
        var player = new OrderPlayer("Walker", NoClips.Instance, NoRides);
        var order = LocalOrders.Walk(7, 0, 1, "Walker", new OrderPoint(2, 0, 5, 0), "", 0, new OrderPoint(-3, 0, 5, 0), "loc", "", 0);
        Assert.True(player.Accept(order, 0, 0, new Vec3(2, 0, 5), 0));
        for (int i = 1; i <= 4; i++) Assert.Equal(OrderState.Walk, player.Tick(i, path).State);
        Assert.Equal(5, player.WalkPlan!.Length, Eps);
        var end = player.Tick(5, path);
        Assert.Equal(OrderState.Loop, end.State);
        Same(new Vec3(-3, 0, 5), end.Position);
        Assert.Equal(5, player.WalkedM, 9);
    }

    // ---- NavClamp -------------------------------------------------------------------------------------------------

    [Fact]
    public void OnMeshStepPassesThrough()
        => Same(new P2(5.2, 5), NavClamp.Step(new P2(5, 5), new P2(5.2, 5), 0, 3, Room()));

    [Fact]
    public void StepIntoObstacleSlidesToEdge()
        => Same(new P2(5, 4.0), NavClamp.Step(new P2(5, 3.9), new P2(5, 4.1), 0, 3, Room().Hole(4, 4, 6, 6)));

    [Fact]
    public void OffMeshStartMayApproachMesh()
        => Same(new P2(5, 4.3), NavClamp.Step(new P2(5, 4.5), new P2(5, 4.3), 0, 3, Room().Hole(4, 4, 6, 6)));

    [Fact]
    public void OffMeshStartMayNotGoDeeper()
        => Same(new P2(5, 4.3), NavClamp.Step(new P2(5, 4.3), new P2(5, 4.6), 0, 3, Room().Hole(4, 4, 6, 6)));

    [Fact]
    public void ParallelInsideObstacleIsStable()
        => Same(new P2(5.1, 4.3), NavClamp.Step(new P2(5, 4.3), new P2(5.1, 4.3), 0, 3, Room().Hole(4, 4, 6, 6)));

    [Fact]
    public void DeeperWithinEpsilonPasses()
        // dFrom = 0.3, dTo = 0.30005 ≤ 0.3 + 1e-4 → to
        => Same(new P2(5.1, 4.30005), NavClamp.Step(new P2(5, 4.3), new P2(5.1, 4.30005), 0, 3, Room().Hole(4, 4, 6, 6)));

    [Fact]
    public void DeeperBeyondEpsilonStays()
        // dFrom = 0.3, dTo = 0.3002 > 0.3 + 1e-4, dFrom > tol → from
        => Same(new P2(5, 4.3), NavClamp.Step(new P2(5, 4.3), new P2(5.1, 4.3002), 0, 3, Room().Hole(4, 4, 6, 6)));

    [Fact]
    public void OtherStoreyIsNotOnMesh()
    {
        // The mesh lies directly above (Closest.Y = y + 3, storey height 3 → |dy| = 3 ≥ 1.5): neither point counts, and
        // an avatar off every mesh of its storey is never held (final review E2, I-1 (b)) — the step passes.
        var upstairs = new FakePathProvider { ClosestYOffset = 3 }.Mesh(0, 0, 10, 10);
        Same(new P2(5.2, 5), NavClamp.Step(new P2(5, 5), new P2(5.2, 5), 0, 3, upstairs));
    }

    [Fact]
    public void StepOffTheStoreyFromTheMeshIsHeld()
    {
        // From (5, 5) stands on the level mesh (height 0); beyond x 5.1 the mesh lies 3 m higher (another storey,
        // |dy| = 3 ≥ 1.5) → dTo infinite, dFrom 0 → held.
        var split = new FakePathProvider { HeightAt = (x, _) => x > 5.1 ? 3 : 0 }.Mesh(0, 0, 10, 10);
        Same(new P2(5, 5), NavClamp.Step(new P2(5, 5), new P2(5.2, 5), 0, 3, split));
    }

    [Fact]
    public void SlopedMeshIsWalkableAboveItsPlane()
    {
        // The mesh rises 0.1 per metre of x (y = 0.1·x, x 0…10); the avatar at (5, 5) stands at y 1.0, 0.5 above the
        // plane (0.5 there) — the terrain between the polygon corners is higher than the polygon. The 3D foot point of
        // (5, 1.0, 5) is shifted in x by g·f/(1 + g²) = 0.1·0.5/1.01 = 0.049505 > OnMeshTolM 0.02: the old 3D rule saw
        // the avatar 0.0495 off the mesh, and a step to (4.9, 5) (f = 0.51 → 0.050495, deeper by 0.00099 > 1e-4) was held.
        var slope = new FakePathProvider { Grade = 0.1 }.Mesh(0, 0, 10, 10);
        Assert.Equal(5.049505, slope.Closest(new Vec3(5, 1.0, 5)).X, 6);
        // Straight below every point lies the mesh (horizontal distance 0): every direction passes.
        foreach (var to in new[] { new P2(4.9, 5), new P2(5.1, 5), new P2(5, 4.9), new P2(5, 5.1) })
            Same(to, NavClamp.Step(new P2(5, 5), to, 1.0, 3, slope));
    }

    [Fact]
    public void FarAboveASlopeNeverFreezes()
    {
        // y 3.0 at (5, 5) is 2.5 above the plane (0.5): beyond the band ± 1.5 for both points → neither is on this
        // storey's mesh → the step passes instead of freezing every key (final review E2, I-1 (b)).
        var slope = new FakePathProvider { Grade = 0.1 }.Mesh(0, 0, 10, 10);
        Same(new P2(4.9, 5), NavClamp.Step(new P2(5, 5), new P2(4.9, 5), 3.0, 3, slope));
    }

    // ---- NavRoutePlanner ------------------------------------------------------------------------------------------

    private static readonly Vec3 A = new(1, 0, 1), B = new(3, 0, 1), L1 = new(5, 0, 1), L2 = new(5, 0, 5), C = new(9, 0, 9);

    private static NavPlan LinkPlan()
    {
        var nav = Room().Answer(A, C, new[] { A, B, L1, L2, C }, new ulong[] { 0, 0, 65536, 0, 0 }, 20);
        return NavRoutePlanner.Plan(nav, A, C, AllInside, Array.Empty<P2>(), 0)!;
    }

    [Fact]
    public void PlanSplitsAtLink()
    {
        var plan = LinkPlan();
        Assert.NotNull(plan);
        Assert.Equal(3, plan.Steps.Count);
        var w0 = Assert.IsType<NavWalk>(plan.Steps[0]);
        Assert.Equal(new[] { A, B, L1 }, w0.Points);
        var link = Assert.IsType<NavLink>(plan.Steps[1]);
        Assert.Equal(65536UL, link.Owner);
        Same(L1, link.Start);
        Same(L2, link.End);
        var w1 = Assert.IsType<NavWalk>(plan.Steps[2]);
        Assert.Equal(new[] { L2, C }, w1.Points);
        Same(C, plan.Goal);
        Assert.Equal(20, plan.Length, Eps);
    }

    [Fact]
    public void UnreachableReturnsNull()
    {
        var end = new Vec3(9, 0, 8.4); // 0.6 short of C
        var nav = Room().Answer(A, C, new[] { A, end }, new ulong[] { 0, 0 }, 10);
        Assert.Null(NavRoutePlanner.Plan(nav, A, C, AllInside, Array.Empty<P2>(), 0));
    }

    [Fact]
    public void ClickIntoFurnitureStopsAtEdge()
    {
        var nav = Room().Hole(4, 4, 8, 5.5);
        var plan = NavRoutePlanner.Plan(nav, A, new Vec3(6, 0, 4.6), AllInside, Array.Empty<P2>(), 0);
        Assert.NotNull(plan);
        var edge = new Vec3(6, 0, 4);
        Same(edge, plan!.Goal);
        Same(edge, nav.Queries[^1].To);
        var walk = Assert.IsType<NavWalk>(Assert.Single(plan.Steps));
        Same(edge, walk.Points[^1]);
        Assert.Equal(Math.Sqrt(5 * 5 + 3 * 3), plan.Length, Eps);
    }

    [Fact]
    public void OutsideTargetRoutesViaOutsideDoor()
    {
        var from = new Vec3(2, 0, 5);
        var door = new Vec3(0, 0, 5);
        var mid = new Vec3(1, 0, 5);
        var target = new Vec3(-3, 0, 5);
        var nav = Room().Answer(from, door, new[] { from, mid, door }, new ulong[] { 0, 0, 0 }, 2);
        var plan = NavRoutePlanner.Plan(nav, from, target, InsideRoom, new[] { new P2(0, 5), new P2(10, 5) }, 0);
        Assert.NotNull(plan);
        Same(target, plan!.Goal);
        Assert.Equal(5, plan.Length, Eps);
        var walk = Assert.IsType<NavWalk>(Assert.Single(plan.Steps));
        Assert.Equal(new[] { from, mid, door, target }, walk.Points);
    }

    [Fact]
    public void OutsideTargetWithoutDoorFallsBack()
        => Assert.Null(NavRoutePlanner.Plan(Room(), new Vec3(2, 0, 5), new Vec3(-3, 0, 5), InsideRoom, Array.Empty<P2>(), 0));

    [Fact]
    public void StartOutsideFootprintFallsBack()
        => Assert.Null(NavRoutePlanner.Plan(Room(), new Vec3(-3, 0, 5), new Vec3(2, 0, 5), InsideRoom, new[] { new P2(0, 5) }, 0));

    [Fact]
    public void SinglePointPathIsNoPlan()
    {
        // Query answers one point (start = goal): no section to follow → null, never a plan NavRoute rejects.
        var p = new Vec3(3, 0, 3);
        var nav = Room().Answer(p, p, new[] { p }, new ulong[] { 0 }, 0);
        Assert.Null(NavRoutePlanner.Plan(nav, p, p, AllInside, Array.Empty<P2>(), 0));
    }

    [Fact]
    public void StandingAtFurnitureEdgeIsNoPlan()
    {
        // Already at the edge (6, 4): Query(from, edge) answers the one point → null.
        var edge = new Vec3(6, 0, 4);
        var nav = Room().Hole(4, 4, 8, 5.5).Answer(edge, edge, new[] { edge }, new ulong[] { 0 }, 0);
        Assert.Null(NavRoutePlanner.Plan(nav, edge, new Vec3(6, 0, 4.6), AllInside, Array.Empty<P2>(), 0));
    }

    [Fact]
    public void OffMeshStartToMeshTargetQueriesFromStart()
    {
        // Start (5, 5) inside hole x 4…6, z 4…6 (1 m from the mesh), target (9, 9) on it → case 1 from the real start.
        var nav = Room().Hole(4, 4, 6, 6);
        var from = new Vec3(5, 0, 5);
        var plan = NavRoutePlanner.Plan(nav, from, C, AllInside, Array.Empty<P2>(), 0);
        Assert.NotNull(plan);
        Same(from, nav.Queries[^1].From);
        Same(C, plan!.Goal);
    }

    [Fact]
    public void BothOffMeshFallsBack()
    {
        var nav = Room().Hole(4, 4, 8, 8);
        Assert.Null(NavRoutePlanner.Plan(nav, new Vec3(5, 0, 5), new Vec3(7, 0, 7), AllInside, Array.Empty<P2>(), 0));
    }
}
