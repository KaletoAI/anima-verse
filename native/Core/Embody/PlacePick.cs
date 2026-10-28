using System.Collections.Generic;
using AnimaNative.Scatter;

namespace AnimaNative.Embody;

public sealed record PickPlace(string Id, IReadOnlyList<P2> Free);

/// <summary>Task 47 (E7-T2): placement.ts pickablePlaceFor; closest free slot, payload order within squared-distance epsilon.</summary>
public static class PlacePick
{
    public const double PlacePickRadiusM = 0.6;
    public static string? PickablePlaceFor(P2 hit, IEnumerable<PickPlace> places, double? maxDistM = null)
    {
        string? best = null;
        double bestD = double.PositiveInfinity;
        foreach (var place in places)
        foreach (var p in place.Free)
        {
            double d = (p.X - hit.X) * (p.X - hit.X) + (p.Z - hit.Z) * (p.Z - hit.Z);
            if (d < bestD - 1e-9) { bestD = d; best = place.Id; }
        }
        return maxDistM is double max && bestD > max * max ? null : best;
    }
}
