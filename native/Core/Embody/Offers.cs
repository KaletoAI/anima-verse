using System;

namespace AnimaNative.Embody;

/// <summary>Task 47 (E7-T2), offers.ts: nearest finite non-negative offer; exact ties go talk, elevator, stairs, enter, item.</summary>
public static class Offers
{
    public static string? NearestOffer(double? talkTarget, double? elevator, double? stairs, double? enterOffer, double? item = null)
    {
        string? best = null;
        double bestDist = double.PositiveInfinity;
        Consider("talk", talkTarget); Consider("elevator", elevator); Consider("stairs", stairs); Consider("enter", enterOffer); Consider("item", item);
        return best;
        void Consider(string kind, double? value)
        {
            if (value is double dist && double.IsFinite(dist) && dist >= 0 && dist < bestDist)
            { best = kind; bestDist = dist; }
        }
    }
}
