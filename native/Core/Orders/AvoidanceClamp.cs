using System;
using AnimaNative.Nav;
using AnimaNative.Scatter;

namespace AnimaNative.Orders;

/// <summary>What the avoidance agent of a figure does in one frame (spec 5d).</summary>
public enum AvoidanceMode
{
    /// <summary>No agent: the figure plays no order (its agent is freed).</summary>
    None,
    /// <summary>A walking agent: it reports the walk's desired velocity and takes the safe velocity back.</summary>
    Moving,
    /// <summary>A static agent with velocity 0 (the loop, the wait at the access, a frozen walk): others avoid it.</summary>
    Static,
    /// <summary>Taken out of the avoidance (<c>AgentSetAvoidanceEnabled(false)</c>): exit and entry, so RVO never pushes a
    /// figure off the bed's edge.</summary>
    Off,
}

/// <summary>
/// The RVO avoidance of an order walk (plan E3 Task 11, spec 5d). RVO knows neither the navmesh nor the walls, so its
/// safe velocity may push a figure through a wall or into furniture: every avoided step is clamped — onto the navmesh of
/// the figure's storey (<see cref="NavClamp.Step"/>), then against the walls (inside a building
/// <c>Collide.ClampAgainstWalls</c>). The straight final piece to the access is exempt (it ends inside the furniture's
/// erosion on purpose). Radii: a human 0.25 m (the navmesh's agent radius), an animal half the larger side of its
/// footprint. Hand derivations: native/tests/AvoidanceClampTests.cs.
/// </summary>
public static class AvoidanceClamp
{
    /// <summary>The avoidance radius of a human figure: the navmesh's agent radius (<c>Collide.BodyRadiusM</c>).</summary>
    public const double HumanRadiusM = 0.25;

    /// <summary>
    /// The clamp of one avoided step from <paramref name="from"/> to <paramref name="safeTarget"/> (the walk's step plus
    /// the avoidance's change of velocity): on the final piece the target as it is; else the navmesh clamp (no map: none),
    /// then <paramref name="walls"/> (from, to) → to.
    /// </summary>
    public static P2 Step(P2 from, P2 safeTarget, double y, double storeyHeight, IPathProvider? nav, Func<P2, P2, P2> walls,
                          bool finalPiece)
    {
        if (finalPiece)
            return safeTarget;
        var onMesh = nav is null ? safeTarget : NavClamp.Step(from, safeTarget, y, storeyHeight, nav);
        return walls(from, onMesh);
    }

    /// <summary>
    /// The avoidance radius of a figure: an animal (a <c>generic</c> rig) half the larger side of its footprint
    /// <paramref name="width"/> × <paramref name="depth"/> (metres, the scaled bind box); everyone else, and an animal
    /// without a measured footprint, <see cref="HumanRadiusM"/>.
    /// </summary>
    public static double RadiusOf(string rig, double width, double depth)
    {
        double side = Math.Max(width, depth);
        return rig == "generic" && double.IsFinite(side) && side > 0 ? side / 2 : HumanRadiusM;
    }

    /// <summary>
    /// The agent's mode in a frame of the chain state <paramref name="state"/> (the player's own state, never the shown
    /// <c>Frozen</c>): a walk moves (a frozen one stands), the wait at the access and the loop stand, exit and entry are
    /// out of the avoidance, idle and abort have no agent.
    /// </summary>
    public static AvoidanceMode ModeOf(OrderState state, bool frozen) => state switch
    {
        OrderState.Walk => frozen ? AvoidanceMode.Static : AvoidanceMode.Moving,
        OrderState.WaitAccess or OrderState.Loop => AvoidanceMode.Static,
        OrderState.Exit or OrderState.Entry => AvoidanceMode.Off,
        _ => AvoidanceMode.None,
    };
}
