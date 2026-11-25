using System;
using System.Collections.Generic;
using AnimaNative.Overview;
using AnimaNative.Scatter;

namespace AnimaNative.Orders;

// The client side of a motion order (spec 2026-11-25-client-ausfuehrung-design § 5b, plan E3 decision 2): the wire
// form app/core/motion_orders.py::new_order builds, parsed by OrderParse.From and played by OrderPlayer.

/// <summary>A point in world metres with a facing in degrees (atan2(x, z) convention of the client).</summary>
public sealed record OrderPoint(double X, double Y, double Z, double YawDeg)
{
    public Vec3 Pos => new(X, Y, Z);
}

/// <summary>
/// One semantic phase of an actor's chain: <c>exit</c> · <c>walk</c> · <c>entry</c> · <c>loop</c> · <c>phase</c> ·
/// <c>finale</c>. The order names the phase and its pose kind, never a clip; <see cref="NominalS"/> is the catalogue
/// duration the server estimated with.
/// </summary>
public sealed record OrderStep(string Step, string PoseKind, string PoseKey, double NominalS);

/// <summary>
/// One participant (decision 2: access, anchor, entry mode and sequence live per actor). <see cref="Stand"/> only on a
/// <c>cancel</c>, per participant (decision 19).
/// </summary>
public sealed record OrderActor(string Name, string Role, string ClipRole, double? HeightCm, OrderPoint Start, string StartRoom,
                                int StartLevel, OrderPoint? Access, OrderPoint? Anchor, double RootOffset, string EntryMode,
                                IReadOnlyList<OrderStep> Sequence, bool ReportsArrival, OrderPoint? Stand);

/// <summary>
/// One order. Times are motion seconds (<c>timeutils.motion_time()</c>); <see cref="FlipS"/> is missing while
/// <see cref="Awaits"/> is set. <see cref="Goal"/> is the target point of a <c>walk</c> (the target's x, y, z), null
/// for a furniture order. An id starting with <c>local:</c> is a client-made order the server does not know.
/// </summary>
public sealed record Order(string Id, int Revision, long Seq, string Kind, double IssuedS, double EtaS, double? FlipS,
                           double DeadlineS, string Status, string Awaits, string Gait, double SpeedMS,
                           IReadOnlyList<OrderActor> Actors, string LocationId, string RoomId, int Level, OrderPoint? Goal,
                           IReadOnlyList<P2> HintRoute, bool Snap)
{
    public bool IsLocal => Id.StartsWith("local:", StringComparison.Ordinal);

    /// <summary>The run a furniture order plays (`target.execution_id`); "" for any other order and a local one.</summary>
    public string ExecutionId { get; init; } = "";

    /// <summary>The participant with this name, or null when the order does not move that figure.</summary>
    public OrderActor? ActorNamed(string name)
    {
        foreach (var a in Actors)
            if (a.Name == name)
                return a;
        return null;
    }
}
