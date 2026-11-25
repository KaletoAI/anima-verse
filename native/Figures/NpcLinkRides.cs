using System;
using System.Collections.Generic;
using AnimaNative.Nav;
using AnimaNative.Orders;
using AnimaNative.Overview;
using AnimaNative.Scatter;
using AnimaNative.Scene;

namespace AnimaNative.Figures;

/// <summary>
/// Plan E3 Task 5 (decision 13, review W5): an NPC's ride over a stair link of its order walk. No server request — an
/// NPC answers <see cref="LinkRideState.Riding"/> from <see cref="Begin"/> on. The figure walks the flight's run towards
/// the link end at the order's speed; the height is the flight's ramp (<see cref="Stairs.RideStep"/> on a one-leg
/// <see cref="StairRide"/>, armed at the start — as <c>AvatarRoomsController.RideLinkAsync</c> builds it). One instance
/// per figure.
/// </summary>
public sealed class NpcStairsRide : ILinkRide
{
    private readonly Func<IReadOnlyList<StairLink>> _flights;
    private NavLink? _link;
    private StairRide? _ride;

    public NpcStairsRide(Func<IReadOnlyList<StairLink>> flights) => _flights = flights;

    public string Kind => "stairs";

    public LinkRideState Begin(string actor, NavLink link)
    {
        _link = link;
        _ride = null;
        var flights = _flights();
        if (NavLinkOwner.TryStairs(link.Owner, out int flight) && flight >= 0 && flight < flights.Count)
        {
            var s = flights[flight];
            // The landing the link ends at (the nearer of foot and head).
            var dest = Dist(s.Head.Pos, link.End) <= Dist(s.Foot.Pos, link.End) ? s.Head : s.Foot;
            if (Stairs.LegTo(new[] { s }, dest) is { } leg)
                _ride = new StairRide { Legs = new[] { leg }, Leg = 0, Armed = true };
        }
        return LinkRideState.Riding;
    }

    public LinkRideState Poll(ref Vec3 pos, double dt, double speedMS)
    {
        if (_link is not { } link) return LinkRideState.Done;
        double dx = link.End.X - pos.X, dz = link.End.Z - pos.Z, d = Math.Sqrt(dx * dx + dz * dz);
        double step = Math.Max(0, speedMS * dt);
        var from = new P2(pos.X, pos.Z);
        if (d <= step + 1e-9)
        {
            pos = link.End;
            Abort();
            return LinkRideState.Done;
        }
        double x = pos.X + dx / d * step, z = pos.Z + dz / d * step;
        double y = pos.Y + (link.End.Y - pos.Y) * step / d;
        if (_ride is { } ride)
        {
            var r = Stairs.RideStep(ride, x, pos.Y, z, from);
            ride.Leg = r.Leg;
            ride.Armed = r.Armed;
            if (r.Y is { } ramp) y = ramp;
        }
        pos = new Vec3(x, y, z);
        return LinkRideState.Riding;
    }

    public void Abort()
    {
        _link = null;
        _ride = null;
    }

    private static double Dist(Vec3 a, Vec3 b)
        => Math.Sqrt((a.X - b.X) * (a.X - b.X) + (a.Y - b.Y) * (a.Y - b.Y) + (a.Z - b.Z) * (a.Z - b.Z));
}

/// <summary>
/// Plan E3 Task 5: an NPC's lift hop. Like the avatar's ride (<c>AvatarRoomsController.RideLinkAsync</c> puts the figure
/// on the other stop), the figure stands at the stop it arrived at for the hop and is then on the link end; an NPC
/// needs no room request. One instance per figure.
/// </summary>
public sealed class NpcLiftRide : ILinkRide
{
    /// <summary>Vertical metres per second of the hop (the cabin is not drawn; the figure waits at its stop).</summary>
    public const double HopSpeedMS = 1.5;

    private NavLink? _link;
    private double _left;

    public string Kind => "lift";

    public LinkRideState Begin(string actor, NavLink link)
    {
        _link = link;
        _left = Math.Abs(link.End.Y - link.Start.Y) / HopSpeedMS;
        return LinkRideState.Riding;
    }

    public LinkRideState Poll(ref Vec3 pos, double dt, double speedMS)
    {
        if (_link is not { } link) return LinkRideState.Done;
        _left -= Math.Max(0, dt);
        if (_left > 1e-9) return LinkRideState.Riding;
        pos = link.End;
        _link = null;
        return LinkRideState.Done;
    }

    public void Abort() => _link = null;
}
