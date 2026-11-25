using System;
using System.Collections.Generic;
using System.Linq;
using AnimaNative.Nav;
using AnimaNative.Overview;
using AnimaNative.Scatter;

namespace AnimaNative.Orders;

/// <summary>The states of <see cref="OrderPlayer"/> (spec 5c).</summary>
public enum OrderState { Idle, Exit, Walk, WaitAccess, Entry, Loop, Abort, Frozen }

/// <summary>The real clip durations of the loaded model; <c>null</c> = the clip is missing → the step's nominal seconds.</summary>
public interface IClipDurations
{
    double? Seconds(string step, string poseKind, string poseKey);
}

/// <summary>
/// What the bridge shows this frame. <see cref="PhaseStep"/>/<see cref="PoseKey"/>: the running phase and its pose
/// (an exit names the pose it leaves). Events: <c>arrived_access</c>, <c>entry_started</c>, <c>loop_started</c>,
/// <c>healed</c>, <c>aborted</c>, <c>stuck</c>, <c>no_path</c>, <c>link_refused</c>, <c>ended</c> (an order ended
/// without a successor: blend into the rest placement, decision 6).
/// </summary>
public sealed record OrderFrame(OrderState State, Vec3 Position, double YawDeg, string? PhaseStep, string? PoseKey, double PhaseTime,
                                IReadOnlyList<string> Events);

/// <summary>
/// Plays the orders of ONE figure on the client's own clock (spec 5c; plan E3 Task 2; not wired yet).
/// <para><b>Clock.</b> At the accept <c>lag = motionNow − issued</c> and <see cref="IssuedLocal"/> =
/// <c>clientNow − lag</c>, set once and never adjusted; the order time is <c>t = clientNow − IssuedLocal</c> minus the
/// frozen spans, the local flip <c>IssuedLocal + (flip − issued)</c> (also after revisions). The chain itself runs on
/// <c>t − offset</c>: a fresh order (lag ≤ <see cref="LagFreshS"/>) and every replacement of a running chain start at
/// the accept (offset = lag); a late one (2 &lt; lag &lt; flip − issued) runs on t and seeks ONCE (exit time, path
/// length <c>(t − exit) · speed</c> from the actor's start, or into the entry clip); <c>lag ≥ flip − issued</c> or
/// status <c>active</c> shows the loop at once.</para>
/// <para><b>Accept.</b> Same id + revision → no-op (false). Same id, higher revision → fields in place (an access more
/// than <see cref="AccessDiffM"/> away replaces only the walk goal; a lifted <c>awaits</c> starts the entry at the
/// accept). A running local order (<see cref="Order.IsLocal"/>) is adopted in place by a server order of the same
/// kind, location and target (goal / anchor within <see cref="AccessDiffM"/>; review W3.1). Any other id is case 1:
/// the chain continues from the shown state — out of an entry or loop with an exit clip only when the new order
/// starts the figure's sequence with <c>exit</c> or is a <c>cancel</c> carrying it (decision 19 / N2); a walking
/// figure has no pose to leave. An order without this figure in <c>actors</c> is ignored.</para>
/// <para><b>Heal rule 2.</b> Still walking at the local flip + <see cref="HealGraceS"/>: blend onto the access,
/// event <c>healed</c>, entry. Phase, finale and tempo are never clocked here; a revision brings them.</para>
/// </summary>
public sealed class OrderPlayer
{
    public const double ArriveTolM = 0.15;
    public const double LagFreshS = 2.0;
    public const double HealGraceS = 5.0;
    public const double StuckSpeedMS = 0.05;
    public const double StuckS = 2.0;
    public const double ReplanDeviationM = 1.0;
    public const double ReplanBlockedS = 1.0;
    public const double AccessDiffM = 0.15;

    private const double Eps = 1e-6;
    private static readonly string[] LoopSteps = { "loop", "phase", "finale" };

    private readonly string _name;
    private readonly IClipDurations _clips;
    private readonly IReadOnlyDictionary<string, ILinkRide> _rides;
    private readonly List<string> _pending = new();

    private OrderActor? _actor;
    private OrderState _state = OrderState.Idle;
    private bool _frozen;
    private double _frozenSince, _frozenTotal, _offset;
    private double _phaseStart, _phaseDur, _walkC;
    private Vec3 _pos;
    private double _yaw;
    private OrderWalk? _walk;
    private Vec3? _walkTarget, _exitStand;
    private bool _late, _noPath, _stuckReported;
    private string? _phaseStep, _poseKey, _poseKind;

    public OrderPlayer(string actorName, IClipDurations clips, IReadOnlyDictionary<string, ILinkRide> rides)
    {
        _name = actorName;
        _clips = clips;
        _rides = rides;
    }

    public Order? Current { get; private set; }

    public OrderState State => _frozen && _state is not (OrderState.Idle or OrderState.Abort) ? OrderState.Frozen : _state;

    public double IssuedLocal { get; private set; }

    /// <summary>The horizontal metres walked in the current order (a late seek included).</summary>
    public double WalkedM { get; private set; }

    /// <summary>Where the current walk leads (null before the walk phase).</summary>
    public Vec3? WalkGoal => _walkTarget;

    /// <summary>The pose kind of the running phase; an exit names the kind it leaves.</summary>
    public string? PhasePoseKind => _poseKind;

    /// <summary>The reason of the last refusal.</summary>
    public string? RefusalReason { get; private set; }

    public bool Accept(Order order, double clientNow, double motionNow, Vec3 shownPos, double shownYawDeg)
    {
        var actor = order.ActorNamed(_name);
        if (actor is null)
            return false;
        var cur = Current;
        if (cur is not null && cur.Id == order.Id)
        {
            if (order.Revision <= cur.Revision)
                return false;
            Revise(order, actor, clientNow);
            return true;
        }
        if (cur is not null && cur.IsLocal && _state != OrderState.Idle && SameTarget(cur, _actor!, order, actor))
        {
            Revise(order, actor, clientNow);
            return true;
        }
        Start(order, actor, clientNow, motionNow, shownPos, shownYawDeg);
        return true;
    }

    /// <summary>The server refused the reservation or the avatar's arrival: abort from the shown state.</summary>
    public void Refuse(string reason)
    {
        RefusalReason = reason;
        if (Current is null || _state is OrderState.Idle or OrderState.Abort)
            return;
        Abort(_pos);
    }

    public void SetFrozen(bool frozen, double clientNow)
    {
        if (frozen == _frozen)
            return;
        if (frozen)
            _frozenSince = clientNow;
        else
            _frozenTotal += clientNow - _frozenSince;
        _frozen = frozen;
    }

    /// <summary>
    /// A world-map row of this figure carries no order (decision 6, second review N1): a server order ends without a
    /// successor when the row's <c>order_seq</c> covers it; a local order or an older row changes nothing.
    /// </summary>
    public void RowWithoutOrder(long orderSeq, double clientNow)
    {
        if (Current is null || Current.IsLocal || orderSeq < Current.Seq || _state == OrderState.Idle)
            return;
        EndWithoutSuccessor(clientNow);
    }

    private void EndWithoutSuccessor(double clientNow)
    {
        _walk?.Abort();
        _walk = null;
        _state = OrderState.Idle;
        _phaseStep = _poseKey = _poseKind = null;
        _pending.Add("ended");
    }

    public OrderFrame Tick(double clientNow, IPathProvider? nav)
    {
        double c = ChainTime(clientNow);
        if (Current is not null && _state is not (OrderState.Idle or OrderState.Abort))
            Advance(c, nav);
        double phaseTime = _state is OrderState.Idle or OrderState.Abort ? 0 : Math.Max(0, c - _phaseStart);
        var frame = new OrderFrame(State, _pos, _yaw, _phaseStep, _poseKey, phaseTime, _pending.ToArray());
        _pending.Clear();
        if (_state == OrderState.Abort)
        {
            _state = OrderState.Idle;
            _phaseStep = _poseKey = _poseKind = null;
        }
        return frame;
    }

    // ---- accepting -------------------------------------------------------------------------------

    private void Start(Order order, OrderActor actor, double clientNow, double motionNow, Vec3 shownPos, double shownYaw)
    {
        var prev = _state;
        string? prevKind = _poseKind, prevKey = _poseKey;
        var prevAccess = _walkTarget ?? (_actor is { } pa ? WalkTargetOf(Current!, pa) : null);
        _walk?.Abort();
        _walk = null;
        Current = order;
        _actor = actor;
        double lag = motionNow - order.IssuedS;
        IssuedLocal = clientNow - lag;
        _frozenTotal = 0;
        if (_frozen)
            _frozenSince = clientNow;
        _late = _noPath = _stuckReported = false;
        _walkTarget = null;
        _exitStand = null;
        WalkedM = 0;
        _pos = shownPos;
        _yaw = shownYaw;
        bool cancel = order.Kind == "cancel";

        if (prev is not (OrderState.Idle or OrderState.Abort))
        {
            // Case 1: a new id replaces a running chain; it continues from the shown state.
            _offset = lag;
            bool posed = prev is OrderState.Entry or OrderState.Loop;
            var exit = actor.Sequence.FirstOrDefault(s => s.Step == "exit");
            bool exitFirst = actor.Sequence.Count > 0 && actor.Sequence[0].Step == "exit";
            if (posed && (cancel || exitFirst))
            {
                _exitStand = prevAccess ?? actor.Start.Pos;
                BeginExit(0, prevKind ?? exit?.PoseKind ?? "", prevKey ?? exit?.PoseKey ?? "", exit?.NominalS ?? 0);
                return;
            }
            if (cancel)
            {
                Abort(posed ? actor.Stand?.Pos ?? _pos : _pos);
                return;
            }
            AfterExit(0);
            return;
        }

        if (cancel)
        {
            _offset = lag;
            if (order.Snap)
            {
                Abort(actor.Stand?.Pos ?? _pos);
                return;
            }
            BeginChain();
            return;
        }
        double? flipRel = order.FlipS - order.IssuedS;
        if (order.Status == "active" || (flipRel is { } f && lag >= f - Eps))
        {
            _offset = lag;
            BeginLoop(0);
            return;
        }
        if (lag <= LagFreshS)
        {
            _offset = lag;
        }
        else
        {
            _offset = 0;
            _late = true;
            _pos = actor.Start.Pos;
            _yaw = actor.Start.YawDeg;
        }
        BeginChain();
    }

    private void Revise(Order order, OrderActor actor, double clientNow)
    {
        Current = order;
        _actor = actor;
        double c = ChainTime(clientNow);
        if (_walkTarget is { } old && WalkTargetOf(order, actor) is { } next && NavRoutePlanner.Horizontal(old, next) > AccessDiffM)
        {
            _walkTarget = next;
            if (_state == OrderState.Walk)
            {
                _walk?.Abort();
                _walk = null; // the next tick plans from where the figure stands; clock and walked length stay
                _noPath = false;
            }
        }
        if (_state == OrderState.WaitAccess && string.IsNullOrEmpty(order.Awaits))
            AfterArrive(c);
        else if (_state == OrderState.Loop)
            SetLoopPose();
    }

    private static bool SameTarget(Order cur, OrderActor curActor, Order next, OrderActor nextActor)
        => next.Kind == cur.Kind && next.LocationId == cur.LocationId
           && Close(cur.Goal, next.Goal) && Close(curActor.Anchor, nextActor.Anchor);

    private static bool Close(OrderPoint? a, OrderPoint? b)
        => a is null ? b is null : b is not null && NavRoutePlanner.Horizontal(a.Pos, b.Pos) <= AccessDiffM;

    // ---- phases ----------------------------------------------------------------------------------

    private void BeginChain()
    {
        var exit = Step("exit");
        if (exit is not null)
        {
            _exitStand = _actor!.Start.Pos;
            BeginExit(0, exit.PoseKind, exit.PoseKey, exit.NominalS);
        }
        else
        {
            AfterExit(0);
        }
    }

    private void BeginExit(double at, string kind, string key, double nominal)
    {
        _state = OrderState.Exit;
        _phaseStart = at;
        _phaseDur = Duration("exit", kind, key, nominal);
        _phaseStep = "exit";
        _poseKind = kind;
        _poseKey = key;
    }

    private void AfterExit(double at)
    {
        if (_exitStand is { } stand)
        {
            _pos = stand;
            _exitStand = null;
        }
        if (Current!.Kind == "cancel")
        {
            Abort(_actor!.Stand?.Pos ?? _pos);
            return;
        }
        if (Step("walk") is not null && WalkTargetOf(Current, _actor!) is not null)
        {
            _state = OrderState.Walk;
            _phaseStart = _walkC = at;
            _phaseStep = "walk";
            _poseKey = _poseKind = null;
            _walkTarget = WalkTargetOf(Current, _actor!);
            _walk = null;
            return;
        }
        AfterArrive(at);
    }

    private void AfterArrive(double at)
    {
        if (!string.IsNullOrEmpty(Current!.Awaits))
        {
            _state = OrderState.WaitAccess;
            _phaseStart = at;
            _phaseStep = null;
            _poseKey = _poseKind = null;
            if (_actor!.Anchor is { } an)
            {
                double dx = an.X - _pos.X, dz = an.Z - _pos.Z;
                if (dx * dx + dz * dz > 1e-12)
                    _yaw = Math.Atan2(dx, dz) * 180 / Math.PI;
            }
            return;
        }
        var entry = Step("entry");
        if (entry is null)
        {
            BeginLoop(at);
            return;
        }
        _state = OrderState.Entry;
        _phaseStart = at;
        _phaseDur = Duration("entry", entry.PoseKind, entry.PoseKey, entry.NominalS);
        _phaseStep = "entry";
        _poseKind = entry.PoseKind;
        _poseKey = entry.PoseKey;
        if ((_walkTarget ?? WalkTargetOf(Current, _actor!)) is { } access)
            _pos = access;
        if (_actor!.Access is { } a)
            _yaw = a.YawDeg;
        _pending.Add("entry_started");
    }

    private void BeginLoop(double at)
    {
        _state = OrderState.Loop;
        _phaseStart = at;
        SetLoopPose();
        if (_actor!.Anchor is { } anchor)
        {
            _pos = anchor.Pos;
            _yaw = anchor.YawDeg;
        }
        else if ((_walkTarget ?? WalkTargetOf(Current!, _actor)) is { } target)
        {
            _pos = target;
        }
        _pending.Add("loop_started");
    }

    private void SetLoopPose()
    {
        var loop = _actor!.Sequence.LastOrDefault(s => LoopSteps.Contains(s.Step));
        _phaseStep = loop?.Step ?? "loop";
        _poseKind = loop?.PoseKind;
        _poseKey = loop?.PoseKey;
    }

    private void Abort(Vec3 pos)
    {
        _walk?.Abort();
        _walk = null;
        _pos = pos;
        _state = OrderState.Abort;
        _phaseStep = _poseKey = _poseKind = null;
        _pending.Add("aborted");
    }

    private void Heal(double at)
    {
        _walk?.Abort();
        _walk = null;
        if ((_walkTarget ?? WalkTargetOf(Current!, _actor!)) is { } access)
            _pos = access;
        _pending.Add("healed");
        AfterArrive(at); // heal rule 2 needs a flip, i.e. no awaits: the entry (or the loop) follows at once
    }

    // ---- the frame loop --------------------------------------------------------------------------

    private void Advance(double c, IPathProvider? nav)
    {
        for (int guard = 0; guard < 32; guard++)
        {
            switch (_state)
            {
                case OrderState.Exit:
                    if (c - _phaseStart < _phaseDur - Eps)
                        return;
                    AfterExit(_phaseStart + _phaseDur);
                    continue;
                case OrderState.Walk:
                    if (HealDue(c))
                    {
                        Heal(c);
                        continue;
                    }
                    if (!StepWalk(c, nav))
                        return;
                    continue;
                case OrderState.Entry:
                    if (c - _phaseStart < _phaseDur - Eps)
                        return;
                    BeginLoop(_phaseStart + _phaseDur);
                    continue;
                default:
                    return;
            }
        }
    }

    /// <summary>One walk step up to chain time <paramref name="c"/>; true when the state changed.</summary>
    private bool StepWalk(double c, IPathProvider? nav)
    {
        if (_walkTarget is not { } target)
        {
            AfterArrive(_walkC);
            return true;
        }
        var map = nav is { Ready: true } ? nav : StraightPath.Instance;
        double speed = Current!.SpeedMS;
        if (_walk is null)
        {
            if (_noPath)
                return false;
            var plan = PlanTo(map, _pos, target);
            if (plan is null)
            {
                _noPath = true;
                _pending.Add("no_path");
                return false;
            }
            _walk = new OrderWalk(plan, target, speed, _rides, _name);
            if (_late)
            {
                _late = false;
                var p = _walk.Seek(_pos, (c - _walkC) * speed, out bool arrived, out double restM);
                WalkedM += NavRoutePlanner.Horizontal(_pos, p);
                _pos = p;
                _walkC = c;
                if (arrived)
                {
                    _walk = null;
                    _pending.Add("arrived_access");
                    AfterArrive(c - restM / speed);
                    return true;
                }
            }
        }
        var s = _walk.Step(_pos, c - _walkC, map);
        _walkC = c;
        WalkedM += NavRoutePlanner.Horizontal(_pos, s.Pos);
        _pos = s.Pos;
        _yaw = s.YawDeg;
        if (s.LinkRefused)
        {
            _pending.Add("link_refused");
            Abort(_pos);
            return true;
        }
        if (s.Arrived)
        {
            double at = c - _walk.LeftoverS;
            _walk = null;
            _pending.Add("arrived_access");
            AfterArrive(at);
            return true;
        }
        if (s.Stuck)
        {
            if (!_stuckReported)
            {
                _stuckReported = true;
                _pending.Add("stuck");
            }
            return false;
        }
        if (s.NeedsReplan && PlanTo(map, _pos, target) is { } again)
            _walk.Replan(again);
        return false;
    }

    /// <summary>
    /// The navmesh path to the map's closest point of <paramref name="target"/> (the final piece to the target itself is
    /// the walk's). A start already at that point gets a one-segment plan; no path → null.
    /// </summary>
    private static NavPlan? PlanTo(IPathProvider map, Vec3 from, Vec3 target)
    {
        var goal = map.Closest(target);
        var plan = NavRoutePlanner.Plan(map, from, goal, static (_, _) => true, Array.Empty<P2>(), 0);
        if (plan is null && NavRoutePlanner.Horizontal(from, goal) <= NavRoutePlanner.OnMeshM)
            plan = new NavPlan(new NavStep[] { new NavWalk(new[] { from, goal }) }, goal, NavRoutePlanner.Horizontal(from, goal));
        return plan;
    }

    // ---- helpers ---------------------------------------------------------------------------------

    private bool HealDue(double c)
        => Current!.FlipS is { } flip && c + _offset >= flip - Current.IssuedS + HealGraceS - Eps;

    private double ChainTime(double clientNow)
        => (_frozen ? _frozenSince : clientNow) - IssuedLocal - _frozenTotal - _offset;

    private OrderStep? Step(string name) => _actor!.Sequence.FirstOrDefault(s => s.Step == name);

    private double Duration(string step, string kind, string key, double nominal)
        => Math.Max(0, _clips.Seconds(step, kind, key) ?? nominal);

    private static Vec3? WalkTargetOf(Order order, OrderActor actor) => (actor.Access ?? order.Goal)?.Pos;
}
