using System;
using System.Collections.Generic;
using AnimaNative.Overview;
using AnimaNative.Water;

namespace AnimaNative.Figures;

/// <summary>
/// <c>npcGoal</c>'s plan: the point walked to now (the first station not yet retired, else the target), how many leading
/// stations were retired, the horizontal delta and distance to that point, the run distance (+10 m while a station is
/// left) and whether the figure moves at all (horizontal distance &gt; <see cref="NpcWalk.MoveEpsM"/>).
/// </summary>
public readonly record struct NpcGoalPlan(Vec3 Goal, int Retired, Vec3 Delta, double DistToGoal, double Dist, bool Moving);

/// <summary>
/// The pure NPC walking and facing arithmetic of client3d/src/game/npcWalk.ts — the step rule, the facing rules and
/// the two eases of every walking figure (npcs.ts <c>tick</c>, figures.ts <c>update</c>) — checked against
/// shared/test-vectors/npc_walk.json (hand derivations: client3d/scripts/smoke_npc_walk.mjs). Points are world
/// metres, time seconds, yaw radians (three's Y rotation: yaw 0 looks along +z).
/// </summary>
public static class NpcWalk
{
    /// <summary><c>WALK_SPEED</c>: metres per real second, every figure.</summary>
    public const double WalkSpeed = 3.4;
    /// <summary><c>RUN_DISTANCE</c>: farther than this from the goal (+10 m while a station is left) a figure runs.</summary>
    public const double RunDistance = 6;
    /// <summary>The run boost on the walking step.</summary>
    public const double RunFactor = 1.8;
    /// <summary><c>WAYPOINT_ARRIVE_M</c>: a door or route station counts as reached within this 3D distance.</summary>
    public const double WaypointArriveM = 1.5;
    /// <summary><c>walk.MOVE_EPS_M</c>: a horizontal distance up to this is standing.</summary>
    public const double MoveEpsM = 0.05;
    /// <summary>The standing facing looks at the neighbours inside this 3D sphere (strict).</summary>
    public const double NeighbourRadiusM = 4.5;
    /// <summary>The yaw ease (<c>min(1, dt·10)</c> of the shortest turn) and the root-height ease (<c>min(1, dt·4)</c>).</summary>
    public const double YawEaseRate = 10, HeightEaseRate = 4;

    /// <summary>
    /// <c>npcGoal(pos, target, waypoints, retireM)</c>: retire every leading station within <paramref name="retireM"/>
    /// in 3D (strict), then measure the chosen goal horizontally. The inputs are not changed.
    /// </summary>
    public static NpcGoalPlan Goal(Vec3 pos, Vec3 target, IReadOnlyList<Vec3> waypoints, double retireM = WaypointArriveM)
    {
        int retired = 0;
        while (retired < waypoints.Count)
        {
            var p = waypoints[retired];
            double dx = pos.X - p.X, dy = pos.Y - p.Y, dz = pos.Z - p.Z;
            if (!(Math.Sqrt(dx * dx + dy * dy + dz * dz) < retireM)) break;
            retired++;
        }
        var goal = retired < waypoints.Count ? waypoints[retired] : target;
        var delta = new Vec3(goal.X - pos.X, 0, goal.Z - pos.Z);
        double distToGoal = Math.Sqrt(delta.X * delta.X + delta.Z * delta.Z);
        return new NpcGoalPlan(goal, retired, delta, distToGoal,
                               retired < waypoints.Count ? distToGoal + 10 : distToGoal, distToGoal > MoveEpsM);
    }

    /// <summary>
    /// <c>npcStep(goal, movement, reckoning, dt, pace, paceLimit, reckonedStep)</c>: run only beyond
    /// <see cref="RunDistance"/> on a ground that lets one run and never by reckoning; the step is the capped nominal
    /// one (or the measured one) times the pace limit — the cap comes BEFORE the limit.
    /// </summary>
    public static (bool Running, double Step) Step(NpcGoalPlan goal, string movement, bool reckoning, double dt, double pace,
                                                   double paceLimit, double? reckonedStep = null)
    {
        bool running = !reckoning && goal.Dist > RunDistance && FigureClips.CanRun(movement);
        double step = !goal.Moving || paceLimit <= 0 ? 0
            : (reckonedStep ?? Math.Min(goal.DistToGoal, WalkSpeed * dt * pace * (running ? RunFactor : 1))) * paceLimit;
        return (running, step);
    }

    /// <summary><c>neighbourFacing(pos, others)</c>: the centroid of the others inside the strict 4.5 m sphere, else null.</summary>
    public static Vec3? NeighbourFacing(Vec3 pos, IEnumerable<Vec3> others)
    {
        double cx = 0, cy = 0, cz = 0;
        int count = 0;
        foreach (var p in others)
        {
            double dx = p.X - pos.X, dy = p.Y - pos.Y, dz = p.Z - pos.Z;
            if (Math.Sqrt(dx * dx + dy * dy + dz * dz) < NeighbourRadiusM)
            {
                cx += p.X; cy += p.Y; cz += p.Z;
                count++;
            }
        }
        if (count == 0) return null;
        double inverse = 1.0 / count;
        return new Vec3(cx * inverse, cy * inverse, cz * inverse);
    }

    /// <summary>
    /// <c>standingFacing(pos, marker, neighbour, viewYaw)</c>: a view yaw wins, then the marker's direction (copied
    /// whole), then the horizontal direction towards the neighbour centroid; null = keep the current facing.
    /// </summary>
    public static Vec3? StandingFacing(Vec3 pos, Vec3? marker, Vec3? neighbour, double? viewYaw)
    {
        if (viewYaw is { } yaw) return new Vec3(Math.Sin(yaw), 0, Math.Cos(yaw));
        if (marker is { } m) return m;
        return neighbour is { } n ? new Vec3(n.X - pos.X, 0, n.Z - pos.Z) : null;
    }

    /// <summary><c>facingYaw(dir)</c>: <c>atan2(x, z)</c>, or null for a direction shorter than 1e-3 (length² &lt; 1e-6, Y included).</summary>
    public static double? FacingYaw(Vec3 dir)
    {
        if (dir.X * dir.X + dir.Y * dir.Y + dir.Z * dir.Z < 1e-6) return null;
        return Math.Atan2(dir.X, dir.Z);
    }

    /// <summary><c>easeNpcYaw(current, target, dt)</c>: the shortest turn into [−π, π] (both ends kept), eased ×10/s.</summary>
    public static double EaseYaw(double current, double target, double dt)
    {
        double d = target - current;
        while (d > Math.PI) d -= Math.PI * 2;
        while (d < -Math.PI) d += Math.PI * 2;
        return current + d * Math.Min(1, dt * YawEaseRate);
    }

    /// <summary><c>easeNpcY(current, target, dt)</c>: the root height eased ×4/s.</summary>
    public static double EaseY(double current, double target, double dt)
        => current + (target - current) * Math.Min(1, dt * HeightEaseRate);

    /// <summary>
    /// <c>liftStops(stops, from, to)</c>: the lift stop of the start storey, then of the destination, each falling back
    /// to storey 0; a stop that is absent even there is skipped (no deduplication).
    /// </summary>
    public static List<T> LiftStops<T>(IReadOnlyDictionary<int, T> stops, int from, int to)
    {
        var output = new List<T>(2);
        if (stops.TryGetValue(from, out var a) || stops.TryGetValue(0, out a)) output.Add(a);
        if (stops.TryGetValue(to, out var b) || stops.TryGetValue(0, out b)) output.Add(b);
        return output;
    }
}

/// <summary>
/// What the GROUND says at one world point before the reach rules (npcs.ts <c>GroundMove</c>, main.ts
/// <c>setTerrainMove</c>): the catalog's movement word, its two sinks, the painted mirror (null = none), the swim
/// threshold, the raw speed factor, the scope there and a prop water region over the point (null = none).
/// </summary>
public sealed record GroundMove(string Movement, GroundSink Sink, double? Water, double SwimFromM, double Speed,
                                GroundScope Scope, WaterHit? PropWater)
{
    /// <summary>The world without painted ground (npcs.ts' default <c>groundMoveAt</c>).</summary>
    public static GroundMove Plain { get; } = new(FigureClips.WalkRun, new GroundSink(0, 0), null, WaterGates.SwimFromDefaultM,
                                                  1, GroundScope.Wilderness, null);
}

/// <summary>The ground word at a figure (npcs.ts <c>groundWordAt</c>): the raw read, the bed under it and the gated word.</summary>
public readonly record struct GroundWord(GroundMove Raw, double BedY, GroundWater Word);

/// <summary>
/// The ground rules of client3d/src/game/walk.ts the walking figure needs beyond <see cref="WaterGates"/>:
/// <c>terrainPace</c>, <c>groundSink</c>, <c>sinkForState</c>, <c>floatRootY</c> — checked against
/// shared/test-vectors/npc_ground.json (hand derivations: client3d/scripts/smoke_walk_math.mjs [30]) — and the
/// npcs.ts composition <c>groundWordAt</c>.
/// </summary>
public static class WalkGround
{
    /// <summary><c>MIN_PACE</c>: the slowest pace a ground may impose outside a built place.</summary>
    public const double MinPace = 0.25;

    /// <summary>
    /// <c>terrainPace(speedFactor, scope)</c>: junk walks at 1, a built place at 1, an open place's factor ≤ 0 at 1;
    /// otherwise the factor, clamped up to <see cref="MinPace"/>.
    /// </summary>
    public static double TerrainPace(double speedFactor, GroundScope scope)
    {
        if (!double.IsFinite(speedFactor)) return 1;
        if (scope == GroundScope.Built) return 1;
        if (scope == GroundScope.Open && speedFactor <= 0) return 1;
        return Math.Max(speedFactor, MinPace);
    }

    /// <summary><c>groundSink(sink, scope)</c>: junk and ≤ 0 sink nobody, a built place neither.</summary>
    public static double GroundSink(double sink, GroundScope scope)
    {
        if (!double.IsFinite(sink) || sink <= 0) return 0;
        return scope == GroundScope.Built ? 0 : sink;
    }

    /// <summary><c>sinkForState(moving, groundIdle, sink)</c>: the move depth while moving; waiting, the idle depth only where the ground names an idle clip.</summary>
    public static double SinkForState(bool moving, string groundIdle, GroundSink sink)
    {
        if (moving) return sink.Move;
        return groundIdle.Length > 0 ? sink.Idle : 0;
    }

    /// <summary><c>floatRootY(groundY, waterLevel, sink)</c>: over water the root rides max(bed + sink, mirror); else the bed.</summary>
    public static double FloatRootY(double groundY, double? waterLevel, double sink)
    {
        double s = double.IsFinite(sink) && sink > 0 ? sink : 0;
        if (waterLevel is not { } w || !double.IsFinite(w)) return groundY;
        return Math.Max(groundY + s, w);
    }

    /// <summary>
    /// npcs.ts <c>groundWordAt</c>: the scope-filtered movement (its sinks only for <c>swim</c>), the scope-filtered
    /// mirror, through <see cref="WaterGates.PropWaterWord"/> against the bed.
    /// </summary>
    public static GroundWord WordOf(GroundMove raw, double bedY)
    {
        var movement = FigureClips.MovementOf(raw.Movement, raw.Scope);
        var word = new GroundWater(movement, movement == FigureClips.Swim ? raw.Sink : new GroundSink(0, 0),
                                   WaterGates.GroundWaterLevel(raw.Water, raw.Scope));
        return new GroundWord(raw, bedY, WaterGates.PropWaterWord(word, bedY, raw.SwimFromM, raw.PropWater));
    }

    /// <summary>The scope the sink is cut by: a prop water region is open water whatever the place (npcs.ts).</summary>
    public static GroundScope SinkScope(GroundMove raw) => raw.PropWater is not null ? GroundScope.Open : raw.Scope;
}
