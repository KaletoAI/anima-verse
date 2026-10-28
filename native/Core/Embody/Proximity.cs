using System;
using System.Collections.Generic;
using AnimaNative.Scatter;

namespace AnimaNative.Embody;

public sealed record TalkSelf(string Name, P2 Pos, string LocId, string? Room);
public sealed record TalkCandidate(string Name, P2 Pos, string LocId, string? Room, double Scale);
public readonly record struct TalkOffer(string Name, double Dist);

/// <summary>Task 47 (E7-T2): proximity.ts; talk only within the same location and shown room, nearest then ordinal name.</summary>
public static class Proximity
{
    public const double TalkRange = 2.5;
    public static TalkOffer? TalkTargetNear(TalkSelf avatar, IEnumerable<TalkCandidate> others)
    {
        string? best = null;
        double bestDist = double.PositiveInfinity;
        foreach (var o in others)
        {
            if (o.Name == avatar.Name || o.LocId != avatar.LocId || o.Room != avatar.Room) continue;
            double dist = double.Hypot(o.Pos.X - avatar.Pos.X, o.Pos.Z - avatar.Pos.Z);
            if (dist > TalkRange * o.Scale) continue;
            if (dist < bestDist || (dist == bestDist && best is not null && string.CompareOrdinal(o.Name, best) < 0))
            { best = o.Name; bestDist = dist; }
        }
        return best is null ? null : new TalkOffer(best, bestDist);
    }
}
