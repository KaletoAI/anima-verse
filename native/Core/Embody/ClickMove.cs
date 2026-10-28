using System;
using AnimaNative.Scatter;

namespace AnimaNative.Embody;

/// <summary>Task 47 (E7-T2): clickmove.ts, one straight goal with arrival and stalled-frame gates; walk_control.json.</summary>
public static class ClickMove
{
    public const double GoalArriveM = 0.2, StallStepM = 0.01;
    public const int StallFrames = 20;
    public readonly record struct Direction(double X, double Z, double Dist);

    /// <summary>A blocked or already reached click falls through to the info panel.</summary>
    public static P2? PlanClickWalk(P2 from, P2 to, Func<double, double, bool> blocked)
        => blocked(to.X, to.Z) || ReachedGoal(from, to) ? null : to;
    public static bool ReachedGoal(P2 pos, P2 goal) => double.Hypot(goal.X - pos.X, goal.Z - pos.Z) < GoalArriveM;
    public static Direction? GoalDir(P2 pos, P2 goal)
    {
        double dx = goal.X - pos.X, dz = goal.Z - pos.Z, dist = double.Hypot(dx, dz);
        return dist < 1e-6 ? null : new Direction(dx / dist, dz / dist, dist);
    }
    public static bool WalkStalled(P2 before, P2 after) => double.Hypot(after.X - before.X, after.Z - before.Z) < StallStepM;
}
