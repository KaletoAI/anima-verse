using System;
using System.Collections.Generic;
using AnimaNative.Scatter;
using AnimaNative.Scene;

namespace AnimaNative.Embody;

public readonly record struct EntryFootprint(double X, double Z, double Yaw);
public sealed record EntryOpening(int Edge, P2 AtWorld, P2 Inward);
public sealed record EntryTile(string LocId, EntryFootprint Footprint, IReadOnlyList<EntryOpening> Openings,
                               IReadOnlyList<P2>? Boundary = null, bool Locked = false);
public sealed record EntryOffer(string LocId, P2 Point, int? Edge, double Dist, P2 Inward);

/// <summary>Task 47 (E7-T2): enterLocation.ts offers at authored world openings or the single polygon rim helper; enter.json.</summary>
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
            if (t.Openings.Count > 0)
            {
                foreach (var o in t.Openings)
                {
                    double dist = double.Hypot(o.AtWorld.X - pos.X, o.AtWorld.Z - pos.Z);
                    if (dist > radius) continue;
                    if (near is null || dist < near.Dist) near = new(t.LocId, o.AtWorld, o.Edge, dist, o.Inward);
                }
            }
            else if (t.Boundary is not null)
            {
                var fp = t.Footprint;
                double c = Math.Cos(fp.Yaw), s = Math.Sin(fp.Yaw);
                var local = new P2((pos.X - fp.X) * c - (pos.Z - fp.Z) * s, (pos.X - fp.X) * s + (pos.Z - fp.Z) * c);
                var rim = SceneView.NearestRimPoint(local.X, local.Z, t.Boundary);
                if (rim is RimPoint r && r.Dist <= radius)
                    near = new(t.LocId, LocalToWorld(r.Point.X, r.Point.Z, fp.X, fp.Z, fp.Yaw), null, r.Dist,
                        new(r.Inward.X * c + r.Inward.Z * s, -r.Inward.X * s + r.Inward.Z * c));
            }
            if (near is null) continue;
            if (best is null || (bestLocked && !t.Locked) || (bestLocked == t.Locked && near.Dist < best.Dist))
            { best = near; bestLocked = t.Locked; }
        }
        return best;
    }
}
