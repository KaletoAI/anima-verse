using System;
using System.Collections.Generic;
using AnimaNative.Nav;
using AnimaNative.Overview;

namespace AnimaNative.Orders;

/// <summary>What one <see cref="OrderWalk.Step"/> did: the new position and facing and what the caller must do next.</summary>
/// <param name="Arrived">The figure stands on the access (or the goal of a <c>walk</c> order).</param>
/// <param name="Stuck">The second failure to make progress: the walk gives up (heal rule 2 takes over).</param>
/// <param name="NeedsReplan">Plan the path again from <paramref name="Pos"/> and hand it to <see cref="OrderWalk.Replan"/>.</param>
/// <param name="FinalPiece">On the straight final piece from the map's closest point to the access.</param>
/// <param name="AtLink">At a link: the ride is requested or running.</param>
/// <param name="LinkRefused">The ride answered Refused.</param>
public sealed record WalkStep(Vec3 Pos, double YawDeg, bool Arrived, bool Stuck, bool NeedsReplan, bool FinalPiece, bool AtLink,
                              bool LinkRefused);

/// <summary>
/// Follows a <see cref="NavPlan"/> frame by frame for an order (spec 5c/5d) — the order-side successor of
/// <see cref="NavRoute"/> (which stays for the click walk until plan E3 Task 10). The figure moves exactly
/// <c>speed · dt</c> per frame along the corners and lands on a corner without overshoot. Each step on a walk section
/// is clamped onto the map (<see cref="IPathProvider.ClosestOnVertical"/>) when the clamp is a small correction
/// (≤ <see cref="NavRoutePlanner.OnMeshM"/>); the clamp pushing the step back is a blockade. After the plan's goal
/// (the map's closest point to the access) comes a straight, unclamped final piece to the access itself.
/// Watches: stuck (horizontal speed below <see cref="OrderPlayer.StuckSpeedMS"/> for <see cref="OrderPlayer.StuckS"/>
/// → <see cref="WalkStep.NeedsReplan"/>, the second time <see cref="WalkStep.Stuck"/>; the count and clock survive
/// <see cref="Replan"/>), deviation from the current segment above <see cref="OrderPlayer.ReplanDeviationM"/> and a
/// blockade longer than <see cref="OrderPlayer.ReplanBlockedS"/> (→ <see cref="WalkStep.NeedsReplan"/>, no failure).
/// A figure held within <see cref="OrderPlayer.ArriveTolM"/> of the access counts as arrived. Links are ridden through
/// the <see cref="ILinkRide"/> of their kind; while a ride runs neither stuck time nor deviation counts.
/// A step with <c>dt ≤ 0</c> is neutral.
/// </summary>
public sealed class OrderWalk
{
    /// <summary>Half height of the vertical clamp query.</summary>
    public const double ClampHalfHeightM = 1.0;

    private const double Eps = 1e-6;

    private readonly IReadOnlyDictionary<string, ILinkRide> _rides;
    private readonly double _speed;
    private readonly string _actor;
    private NavPlan _plan;
    private int _step, _corner = 1;
    private bool _final, _arrived, _stuck, _refused;
    private ILinkRide? _ride;
    private Vec3? _last;
    private double _stuckTime, _blockedTime, _yaw;
    private int _stuckCount;

    public OrderWalk(NavPlan plan, Vec3 access, double speedMS, IReadOnlyDictionary<string, ILinkRide> rides, string actor = "")
    {
        if (!(speedMS > 0))
            throw new ArgumentOutOfRangeException(nameof(speedMS), "an order walk needs a positive speed");
        _speed = speedMS;
        _rides = rides;
        _actor = actor;
        _plan = plan;
        Access = access;
        Reset();
        _yaw = InitialYaw();
    }

    /// <summary>Where the final piece ends.</summary>
    public Vec3 Access { get; private set; }

    /// <summary>How often the walk failed to make progress so far.</summary>
    public int StuckCount => _stuckCount;

    /// <summary>The unused part of the last step's dt when it arrived (the arrival lies that far before the frame).</summary>
    public double LeftoverS { get; private set; }

    /// <summary>A link ride is requested or running.</summary>
    public bool Riding => _ride is not null;

    /// <summary>A new plan from where the figure stands (stuck count and clock are kept); not during a ride.</summary>
    public void Replan(NavPlan plan, Vec3? access = null)
    {
        if (_ride is not null)
            return;
        _plan = plan;
        if (access is { } a)
            Access = a;
        Reset();
        _blockedTime = 0;
    }

    /// <summary>Stops a running ride (the order changed mid-ride).</summary>
    public void Abort()
    {
        _ride?.Abort();
        _ride = null;
    }

    /// <summary>
    /// Moves the figure <paramref name="meters"/> along the plan at once (the late-entry seek of spec 5c, done once):
    /// no clamp, no stuck clock; stops at a link foot. <paramref name="arrived"/> when it reaches the access,
    /// <paramref name="restM"/> = the metres left over.
    /// </summary>
    public Vec3 Seek(Vec3 pos, double meters, out bool arrived, out double restM)
    {
        double budget = Math.Max(0, meters);
        var p = pos;
        Advance(ref p, ref budget, clamp: null, out _, out bool atLink);
        arrived = _arrived;
        restM = budget;
        _last = p;
        return p;
    }

    public WalkStep Step(Vec3 pos, double dt, IPathProvider nav)
    {
        LeftoverS = 0;
        if (_refused)
            return Make(pos, linkRefused: true);
        if (_arrived)
            return Make(pos, arrived: true);
        if (_stuck)
            return Make(pos, stuck: true);
        if (!(dt > 0))
            return Make(pos, atLink: _ride is not null);

        if (_ride is not null)
        {
            var p = pos;
            var state = _ride.Poll(ref p, dt, _speed);
            switch (state)
            {
                case LinkRideState.Refused:
                    _ride = null;
                    _refused = true;
                    return Make(p, linkRefused: true);
                case LinkRideState.Done:
                    _ride = null;
                    _step++;
                    _corner = 1;
                    if (_step >= _plan.Steps.Count)
                        _final = true;
                    _last = p;
                    _stuckTime = _blockedTime = 0;
                    return Make(p);
                default:
                    _last = p;
                    return Make(p, atLink: true);
            }
        }

        if (!_final && Current is NavWalk w && SegmentDistance(pos, w.Points[_corner - 1], w.Points[_corner]) > OrderPlayer.ReplanDeviationM)
        {
            _stuckTime = _blockedTime = 0;
            _last = pos;
            return Make(pos, needsReplan: true);
        }

        double budget = _speed * dt;
        var q = pos;
        Advance(ref q, ref budget, nav, out bool blocked, out bool atLinkNow);
        if (_refused)
            return Make(q, linkRefused: true);
        if (_arrived)
        {
            LeftoverS = budget / _speed;
            _last = q;
            return Make(q, arrived: true);
        }
        if (atLinkNow)
        {
            _last = q;
            _stuckTime = 0;
            return Make(q, atLink: true);
        }

        bool slow = _last is { } before && NavRoutePlanner.Horizontal(q, before) / dt < OrderPlayer.StuckSpeedMS;
        _last = q;
        if ((blocked || slow) && NavRoutePlanner.Horizontal(q, Access) <= OrderPlayer.ArriveTolM)
        {
            _arrived = true;
            return Make(q, arrived: true);
        }
        if (slow)
        {
            _stuckTime += dt;
            if (_stuckTime >= OrderPlayer.StuckS - 1e-9)
            {
                _stuckTime = _blockedTime = 0;
                _stuckCount++;
                if (_stuckCount >= 2)
                {
                    _stuck = true;
                    return Make(q, stuck: true);
                }
                return Make(q, needsReplan: true);
            }
        }
        else
        {
            _stuckTime = 0;
        }
        if (blocked)
        {
            _blockedTime += dt;
            if (_blockedTime > OrderPlayer.ReplanBlockedS)
            {
                _blockedTime = 0;
                return Make(q, needsReplan: true);
            }
        }
        else
        {
            _blockedTime = 0;
        }
        return Make(q);
    }

    private NavStep? Current => _step < _plan.Steps.Count ? _plan.Steps[_step] : null;

    private void Reset()
    {
        _step = 0;
        _corner = 1;
        _final = _plan.Steps.Count == 0;
    }

    /// <summary>
    /// Spends <paramref name="budget"/> metres along the plan. A link foot reached begins the ride (with a clamp
    /// provider, i.e. not while seeking) and stops; the access reached sets the arrival. The rest of the budget stays.
    /// </summary>
    private void Advance(ref Vec3 p, ref double budget, IPathProvider? clamp, out bool blocked, out bool atLink)
    {
        blocked = atLink = false;
        var start = p;
        for (int guard = 0; guard < 4096; guard++)
        {
            if (_final)
            {
                double d = NavRoutePlanner.Horizontal(p, Access);
                if (d <= budget + Eps)
                {
                    budget = Math.Max(0, budget - d);
                    p = Access;
                    _arrived = true;
                    break;
                }
                p = Toward(p, Access, budget / d);
                budget = 0;
                break;
            }
            if (Current is NavLink link)
            {
                if (Distance3(p, link.Start) <= NavRoute.LinkArriveM)
                {
                    if (clamp is null)
                    {
                        atLink = true; // a seek stops at the link foot
                        break;
                    }
                    BeginRide(link);
                    atLink = !_refused;
                    break;
                }
                double dl = NavRoutePlanner.Horizontal(p, link.Start);
                if (dl <= budget + Eps)
                {
                    budget = Math.Max(0, budget - dl);
                    p = link.Start;
                    continue;
                }
                p = Toward(p, link.Start, budget / dl);
                budget = 0;
                break;
            }
            var walk = (NavWalk)Current!;
            var corner = walk.Points[_corner];
            double dc = NavRoutePlanner.Horizontal(p, corner);
            if (dc <= budget + Eps)
            {
                budget = Math.Max(0, budget - dc);
                p = corner;
                if (_corner < walk.Points.Count - 1)
                    _corner++;
                else
                {
                    _step++;
                    _corner = 1;
                    if (_step >= _plan.Steps.Count)
                        _final = true;
                }
                continue;
            }
            var next = Toward(p, corner, budget / dc);
            budget = 0;
            if (clamp is not null)
            {
                var on = clamp.ClosestOnVertical(next, ClampHalfHeightM);
                double push = NavRoutePlanner.Horizontal(on, next);
                if (push > Eps && push <= NavRoutePlanner.OnMeshM)
                {
                    blocked = true;
                    next = on;
                }
            }
            p = next;
            break;
        }
        double mx = p.X - start.X, mz = p.Z - start.Z;
        if (mx * mx + mz * mz > 1e-12)
            _yaw = Math.Atan2(mx, mz) * 180 / Math.PI;
    }

    private void BeginRide(NavLink link)
    {
        string kind = KindOf(link.Owner);
        if (!_rides.TryGetValue(kind, out var ride))
        {
            _refused = true;
            return;
        }
        switch (ride.Begin(_actor, link))
        {
            case LinkRideState.Refused:
                _refused = true;
                return;
            case LinkRideState.Done:
                _step++;
                _corner = 1;
                if (_step >= _plan.Steps.Count)
                    _final = true;
                return;
            default:
                _ride = ride;
                _stuckTime = 0;
                return;
        }
    }

    /// <summary>The ride kind of a link owner (decision 13 of E2): <c>stairs</c>, <c>lift</c>, else <c>link</c>.</summary>
    public static string KindOf(ulong owner)
        => NavLinkOwner.TryStairs(owner, out _) ? "stairs" : NavLinkOwner.TryElevator(owner, out _) ? "lift" : "link";

    private double InitialYaw()
    {
        if (Current is NavWalk w)
        {
            var a = w.Points[0];
            var b = w.Points[Math.Min(1, w.Points.Count - 1)];
            double dx = b.X - a.X, dz = b.Z - a.Z;
            if (dx * dx + dz * dz > 1e-12)
                return Math.Atan2(dx, dz) * 180 / Math.PI;
        }
        return 0;
    }

    private WalkStep Make(Vec3 pos, bool arrived = false, bool stuck = false, bool needsReplan = false, bool atLink = false,
                          bool linkRefused = false)
        => new(pos, _yaw, arrived, stuck, needsReplan, _final, atLink, linkRefused);

    private static Vec3 Toward(Vec3 a, Vec3 b, double f)
        => new(a.X + (b.X - a.X) * f, a.Y + (b.Y - a.Y) * f, a.Z + (b.Z - a.Z) * f);

    private static double Distance3(Vec3 a, Vec3 b)
        => Math.Sqrt((a.X - b.X) * (a.X - b.X) + (a.Y - b.Y) * (a.Y - b.Y) + (a.Z - b.Z) * (a.Z - b.Z));

    /// <summary>Horizontal distance from <paramref name="p"/> to the segment a → b.</summary>
    private static double SegmentDistance(Vec3 p, Vec3 a, Vec3 b)
    {
        double ex = b.X - a.X, ez = b.Z - a.Z, len2 = ex * ex + ez * ez;
        double t = len2 < 1e-12 ? 0 : Math.Clamp(((p.X - a.X) * ex + (p.Z - a.Z) * ez) / len2, 0, 1);
        double dx = a.X + t * ex - p.X, dz = a.Z + t * ez - p.Z;
        return Math.Sqrt(dx * dx + dz * dz);
    }
}

/// <summary>A map without obstacles: the straight line, every point is on it (an order walked with no navmesh).</summary>
internal sealed class StraightPath : IPathProvider
{
    public static readonly StraightPath Instance = new();

    public bool Ready => true;

    public NavPath Query(Vec3 from, Vec3 to)
    {
        double dx = to.X - from.X, dy = to.Y - from.Y, dz = to.Z - from.Z;
        return new NavPath(new[] { from, to }, new ulong[] { 0, 0 }, Math.Sqrt(dx * dx + dy * dy + dz * dz));
    }

    public Vec3 Closest(Vec3 p) => p;

    public Vec3 ClosestOnVertical(Vec3 p, double halfHeight) => p;
}
