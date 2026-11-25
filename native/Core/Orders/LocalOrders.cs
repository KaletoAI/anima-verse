using System;
using System.Collections.Generic;
using AnimaNative.Overview;
using AnimaNative.Scatter;

namespace AnimaNative.Orders;

/// <summary>
/// What the client knows of a furniture action at the click (plan E3 Task 6, spec 5e): the avatar, where it stands,
/// the access it walks to (the marker's access of its role, else <see cref="AccessAuto.Compute"/>), the anchor (the
/// marker slot = body root), the entry mode and pose of the offer, and — when it sits — the exit of its current pose.
/// </summary>
public sealed record LocalPropAction(string Name, double? HeightCm, OrderPoint Start, string StartRoom, int StartLevel,
                                     OrderPoint Access, OrderPoint Anchor, double RootOffset, string EntryMode, OrderStep? Exit,
                                     string PoseKind, string PoseKey, string LocationId, string RoomId, int Level);

/// <summary>
/// The client-made orders of the avatar (plan E3 Task 6): an order with id <c>local:&lt;n&gt;</c> the server does not
/// know, played by the same <see cref="OrderPlayer"/> from the click on — so the avatar walks before the reservation is
/// answered. The answer's order adopts it in place (same kind, location and anchor; review W3.1).
/// </summary>
public static class LocalOrders
{
    /// <summary>A local furniture order waits at the access for the server's answer.</summary>
    public const string AwaitsAnswer = "answer";

    /// <summary>
    /// A server order of a figure that reports its own arrival, held at the access until the server's revision
    /// <c>entering</c> (<see cref="HoldForArrival"/>).
    /// </summary>
    public const string AwaitsArrival = "arrival";

    /// <summary>The walking speed until the answer names one (app/core/travel_engine.py <c>DEFAULT_SPEED_M_S</c>).</summary>
    public const double DefaultSpeedMS = 1.4;

    /// <summary>How long a local order may wait for its answer (motion seconds after the click).</summary>
    public const double DeadlineS = 60;

    /// <summary>
    /// <c>local:&lt;n&gt;</c>, kind <c>prop_action</c>, issued at <paramref name="motionNow"/>: the actor's sequence is
    /// <c>exit</c> (when it sits) → <c>walk</c> → <c>entry</c> → <c>loop</c> with nominal 0 — the order awaits the answer
    /// at the access (<see cref="AwaitsAnswer"/>, no flip), so its entry never starts without the server's order.
    /// </summary>
    public static Order PropAction(int n, double motionNow, double speedMS, LocalPropAction a)
    {
        var sequence = new List<OrderStep>();
        if (a.Exit is { } exit) sequence.Add(exit);
        sequence.Add(new OrderStep("walk", "", "", 0));
        sequence.Add(new OrderStep("entry", a.PoseKind, a.PoseKey, 0));
        sequence.Add(new OrderStep("loop", a.PoseKind, a.PoseKey, 0));
        var actor = new OrderActor(a.Name, "actor", "", a.HeightCm, a.Start, a.StartRoom, a.StartLevel, a.Access, a.Anchor,
                                   a.RootOffset, a.EntryMode, sequence, true, null);
        return new Order("local:" + n, 1, 0, "prop_action", motionNow, motionNow, null, motionNow + DeadlineS, "approaching",
                         AwaitsAnswer, "walk", speedMS, new[] { actor }, a.LocationId, a.RoomId, a.Level, null,
                         Array.Empty<P2>(), false);
    }

    /// <summary>
    /// <c>local:&lt;n&gt;</c>, kind <c>walk</c>: the figure walks to <paramref name="goal"/> (links ridden on the way) and stands
    /// there (the chain's loop on the goal). No answer is awaited.
    /// </summary>
    public static Order Walk(int n, double motionNow, double speedMS, string name, OrderPoint start, string startRoom, int startLevel,
                             OrderPoint goal, string locationId, string roomId, int level)
    {
        var actor = new OrderActor(name, "actor", "", null, start, startRoom, startLevel, null, null, 0, "", new[] { new OrderStep("walk", "", "", 0) },
                                   true, null);
        return new Order("local:" + n, 1, 0, "walk", motionNow, motionNow, null, motionNow + DeadlineS, "approaching", "", "walk",
                         speedMS, new[] { actor }, locationId, roomId, level, goal, Array.Empty<P2>(), false);
    }

    /// <summary>
    /// Under the server that still drives the avatar's approach as a journey (until plan E3 Task 7), a server order of a
    /// figure that reports its arrival and is still <c>approaching</c> without <c>awaits</c> waits at the access until
    /// the revision <c>entering</c>: <c>awaits</c> <see cref="AwaitsArrival"/>, no flip (as the server drops it for a set
    /// <c>awaits</c>). Every other order comes back unchanged (the same instance).
    /// </summary>
    public static Order HoldForArrival(Order order, string name)
    {
        if (order.IsLocal || order.Status != "approaching" || order.Awaits.Length > 0) return order;
        if (order.ActorNamed(name) is not { ReportsArrival: true }) return order;
        return order with { Awaits = AwaitsArrival, FlipS = null };
    }

    /// <summary>
    /// The facing away from a piece of furniture after a refusal (compass degrees, <c>atan2(x, z)</c>): from
    /// <paramref name="furniture"/> towards <paramref name="from"/> on the floor; null when both share x and z.
    /// </summary>
    public static double? TurnAwayYawDeg(Vec3 from, Vec3 furniture)
    {
        double dx = from.X - furniture.X, dz = from.Z - furniture.Z;
        if (dx * dx + dz * dz < 1e-12) return null;
        return Math.Atan2(dx, dz) * 180 / Math.PI;
    }
}
