using System;
using System.Collections.Generic;
using AnimaNative.Scatter;

namespace AnimaNative.Embody;

public sealed record EntryOpening(int Edge, P2 AtWorld, P2 Inward);
public sealed record EntryTile(string LocId, bool Fenced, IReadOnlyList<EntryOpening> Gates,
                               IReadOnlyList<EntryDoor> Doors, bool Locked = false);
public sealed record EntryOffer(string LocId, P2 Point, int? Edge, double Dist, P2 Inward);

/// <summary>Offers entry at gates of fenced places or at outside doors of unfenced places; enter.json.</summary>
public static class EnterLocation
{
    public const double EnterRadius = 3;
    public static P2 LocalToWorld(double lx, double lz, double cx, double cz, double yaw)
    {
        double c = Math.Cos(yaw), s = Math.Sin(yaw);
        return new(cx + lx * c + lz * s, cz - lx * s + lz * c);
    }

    /// <summary>Skip the occupied place; open beats locked regardless of distance, then strictly nearest wins.</summary>
    public static EntryOffer? EntryOfferNear(P2 pos, string myLocId, IEnumerable<EntryTile> tiles, double radius = EnterRadius)
    {
        EntryOffer? best = null;
        bool bestLocked = true;
        foreach (var t in tiles)
        {
            if (t.LocId == myLocId) continue;
            EntryOffer? near = null;
            if (t.Fenced)
            {
                foreach (var g in t.Gates)
                {
                    double dist = double.Hypot(g.AtWorld.X - pos.X, g.AtWorld.Z - pos.Z);
                    if (dist > radius) continue;
                    if (near is null || dist < near.Dist) near = new(t.LocId, g.AtWorld, g.Edge, dist, g.Inward);
                }
            }
            else
            {
                foreach (var d in t.Doors)
                {
                    double dist = double.Hypot(d.X - pos.X, d.Z - pos.Z);
                    if (dist > radius) continue;
                    if (near is null || dist < near.Dist)
                        near = new(t.LocId, new(d.X, d.Z), null, dist, new(d.OutX == 0 ? 0 : -d.OutX, d.OutZ == 0 ? 0 : -d.OutZ));
                }
            }
            if (near is null) continue;
            if (best is null || (bestLocked && !t.Locked) || (bestLocked == t.Locked && near.Dist < best.Dist))
            { best = near; bestLocked = t.Locked; }
        }
        return best;
    }
}
