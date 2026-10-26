using System;
using System.Collections.Generic;
using AnimaNative.Overview;
using AnimaNative.Scatter;

namespace AnimaNative.Scene;

/// <summary>One leg of a guided climb (stairs.ts <c>StairLeg</c>): the flight walked and its start and end landing.</summary>
public sealed record StairLeg(StairLink Flight, StairLanding Start, StairLanding End);

/// <summary>
/// A guided climb as the walking machine holds it (stairs.ts <c>StairRide</c>): the legs, the one walked now and
/// whether its start landing was reached (only then its ramp answers). MUTABLE like the browser's — the walker writes
/// <see cref="RideStepResult.Leg"/> / <see cref="RideStepResult.Armed"/> back.
/// </summary>
public sealed class StairRide
{
    public required IReadOnlyList<StairLeg> Legs { get; init; }
    public int Leg { get; set; }
    public bool Armed { get; set; }
}

/// <summary>What <see cref="Stairs.RideStep"/> answers: the leg, the arming, the height (null = the floor answers), done.</summary>
public readonly record struct RideStepResult(int Leg, bool Armed, double? Y, bool Done);

/// <summary>The stair offer (stairs.ts <c>StairPrompt</c>): up or down, the landing the ride ends on, the distance to the landing stood at.</summary>
public sealed record StairPrompt(string Dir, StairLanding Dest, double Dist);

/// <summary>
/// ROUTING OVER STAIRS — client3d/src/game/stairs.ts (<c>stairChain</c>, <c>stairY</c>, <c>rideStep</c>,
/// <c>stairLegs</c>, <c>stairLegTo</c>) on the native world flights (<see cref="PlaceInventory.Stairs"/>, already in world
/// metres). The NPC storey change walks the chain's landings and the ride owns the height on the run (ruling P3-R9;
/// the avatar reuses it in E7). Vectors shared/test-vectors/stairs.json (hand derivations: smoke_walk_math.mjs); the
/// earlier verbatim copies in tests/StairsTests.cs stay as the native cases.
/// </summary>
public static class Stairs
{
    /// <summary><c>RIDE_ARRIVE_M</c>: a landing counts as reached within this 3D distance (and stations retire at it during a ride).</summary>
    public const double RideArriveM = 0.4;

    /// <summary><c>STAIR_RANGE</c>: how close to a landing the avatar has to stand, FIGURE metres (× the figure scale).</summary>
    public const double StairRange = 1.5;

    /// <summary>
    /// <c>stairsAt(pos, level, stairs, scale)</c>: the nearest landing of the avatar's OWN storey within
    /// <see cref="StairRange"/>·scale (strictly closer; a tie keeps the first found) — at the foot the ride goes up, at
    /// the head down, the destination is the other end; null when none is in reach.
    /// </summary>
    public static StairPrompt? StairsAt(P2 pos, int level, IReadOnlyList<StairLink> stairs, double scale)
    {
        double reach = StairRange * scale;
        StairPrompt? best = null;
        double bestDist = double.PositiveInfinity;
        foreach (var s in stairs)
        {
            foreach (var (here, there, dir) in new[] { (s.Foot, s.Head, "up"), (s.Head, s.Foot, "down") })
            {
                if (here.Level != level) continue;
                double dx = here.Pos.X - pos.X, dz = here.Pos.Z - pos.Z;
                double dist = Math.Sqrt(dx * dx + dz * dz);
                if (dist >= reach || dist >= bestDist) continue;
                best = new StairPrompt(dir, there, dist);
                bestDist = dist;
            }
        }
        return best;
    }

    /// <summary>
    /// <c>stairChain(stairs, from, to)</c>: per storey step the near then the far landing of the FIRST flight that
    /// connects the two storeys exactly; empty for no storey change; null when any link is missing.
    /// </summary>
    public static List<StairLanding>? Chain(IReadOnlyList<StairLink> stairs, int from, int to)
    {
        var chain = new List<StairLanding>();
        if (from == to) return chain;
        int step = to > from ? 1 : -1;
        for (int cur = from; cur != to; cur += step)
        {
            int next = cur + step;
            int lower = step > 0 ? cur : next;
            StairLink? link = null;
            foreach (var s in stairs)
                if (s.Foot.Level == lower && s.Head.Level == lower + 1) { link = s; break; }
            if (link is null) return null;
            if (step > 0) { chain.Add(link.Foot); chain.Add(link.Head); }
            else { chain.Add(link.Head); chain.Add(link.Foot); }
        }
        return chain;
    }

    /// <summary>
    /// <c>stairY(flight, x, z)</c>: the ramp height at (x, z) on the flight — the projection onto the run axis clamped to
    /// [0, 1], gated to half the width across; null off the flight or for a degenerate run.
    /// </summary>
    public static double? StairY(StairLink flight, double x, double z)
    {
        double len = Math.Sqrt(flight.Dir.X * flight.Dir.X + flight.Dir.Z * flight.Dir.Z);
        if (!(len > 0) || !(flight.RunM > 0)) return null;
        double dx = flight.Dir.X / len, dz = flight.Dir.Z / len;
        double px = x - flight.At.X, pz = z - flight.At.Z;
        double across = px * -dz + pz * dx;
        if (Math.Abs(across) > flight.WidthM / 2) return null;
        double t = Math.Min(1, Math.Max(0, (px * dx + pz * dz) / flight.RunM));
        return flight.Foot.Pos.Y + t * (flight.Head.Pos.Y - flight.Foot.Pos.Y);
    }

    /// <summary>stairs.ts <c>sameLanding</c>: the storey first, then the point within 1e-6 per axis.</summary>
    public static bool SameLanding(StairLanding a, StairLanding b)
        => a.Level == b.Level && Math.Abs(a.Pos.X - b.Pos.X) < 1e-6 && Math.Abs(a.Pos.Y - b.Pos.Y) < 1e-6
           && Math.Abs(a.Pos.Z - b.Pos.Z) < 1e-6;

    /// <summary>
    /// <c>rideStep(ride, x, y, z, from?)</c>: arm the current leg at its start landing, retire it (only armed) at its end
    /// — in a loop, so a leg that ends where the next begins hands over in one call; the height is the armed leg's ramp.
    /// Pure: the caller writes leg and armed back and drops the ride on <c>done</c>.
    /// <para>
    /// A landing is reached by the frame's SWEPT xz segment from <paramref name="from"/> (where the figure stood when
    /// the frame began; null = a point test) to (x, z), measured at the segment point nearest the landing. The walk
    /// retires a landing at the START of a frame and turns away in the same step, so on a long frame the end point is
    /// already past the radius — a ride that missed its end there never ends and keeps lifting the figure wherever it
    /// later crosses that flight. The height measured with: the floor's <paramref name="y"/> while a leg waits to arm,
    /// the armed leg's own ramp (<see cref="StairY"/>, <paramref name="y"/> off the run's width) once armed —
    /// <paramref name="y"/> is the root height from before this frame's ramp answer and lags it on a long frame.
    /// </para>
    /// </summary>
    public static RideStepResult RideStep(StairRide ride, double x, double y, double z, P2? from = null)
    {
        double fx = from?.X ?? x, fz = from?.Z ?? z;
        double sx = x - fx, sz = z - fz;
        double len2 = sx * sx + sz * sz;
        // Within the arrival radius of p anywhere on this frame's segment, the height there being heightAt's.
        bool Reached(StairLanding p, Func<double, double, double> heightAt)
        {
            double t = len2 > 0 ? Math.Min(1, Math.Max(0, ((p.Pos.X - fx) * sx + (p.Pos.Z - fz) * sz) / len2)) : 0;
            double qx = fx + sx * t, qz = fz + sz * t;
            double dx = p.Pos.X - qx, dy = heightAt(qx, qz) - p.Pos.Y, dz = p.Pos.Z - qz;
            return Math.Sqrt(dx * dx + dy * dy + dz * dz) < RideArriveM;
        }
        double Floor(double qx, double qz) => y;
        int leg = ride.Leg;
        bool armed = ride.Armed;
        while (leg < ride.Legs.Count)
        {
            var cur = ride.Legs[leg];
            if (!armed && Reached(cur.Start, Floor)) armed = true;
            // Only an ARMED leg can end: the end landing of a stacked leg lies over its own start.
            if (armed && Reached(cur.End, (qx, qz) => StairY(cur.Flight, qx, qz) ?? y))
            {
                leg += 1;
                armed = false;
                continue;
            }
            break;
        }
        if (leg >= ride.Legs.Count) return new RideStepResult(leg, armed, null, true);
        return new RideStepResult(leg, armed, armed ? StairY(ride.Legs[leg].Flight, x, z) : null, false);
    }

    /// <summary><c>stairLegTo(links, dest)</c>: the one flight that has this landing, walked from its other end; null when none.</summary>
    public static StairLeg? LegTo(IReadOnlyList<StairLink> links, StairLanding dest)
    {
        foreach (var flight in links)
        {
            if (SameLanding(flight.Head, dest)) return new StairLeg(flight, flight.Foot, dest);
            if (SameLanding(flight.Foot, dest)) return new StairLeg(flight, flight.Head, dest);
        }
        return null;
    }

    /// <summary>
    /// <c>stairLegs(links, chain)</c>: one leg per landing PAIR of a chain, the flight matched on both landings in either
    /// order; a pair no flight owns is skipped.
    /// </summary>
    public static List<StairLeg> Legs(IReadOnlyList<StairLink> links, IReadOnlyList<StairLanding> chain)
    {
        var legs = new List<StairLeg>();
        for (int i = 0; i + 1 < chain.Count; i += 2)
        {
            var a = chain[i];
            var b = chain[i + 1];
            foreach (var s in links)
            {
                if ((SameLanding(s.Foot, a) && SameLanding(s.Head, b)) || (SameLanding(s.Head, a) && SameLanding(s.Foot, b)))
                {
                    legs.Add(new StairLeg(s, a, b));
                    break;
                }
            }
        }
        return legs;
    }
}
