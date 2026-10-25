using System;
using AnimaNative.Scatter;

namespace AnimaNative.Scene;

/// <summary>The lift now applied, and the move from the lift the object was carrying.</summary>
public readonly record struct GroundStep(double Lift, double Delta);

/// <summary>The datum under the pin now, and the move of the whole scene frame to it.</summary>
public readonly record struct DatumStep(double Datum, double Delta);

/// <summary>
/// WHERE A STOREY-0 PLACEMENT STANDS (§ A16.9), a port of packages/scene-render/src/storeyGround.ts plus
/// <c>markerLiftPoint</c> (client3d/src/game/placement.ts), checked against shared/test-vectors/scene_models.json
/// [G]/[K]. A sampler answers the world height at a world (x, z); a non-finite answer means "nothing to say".
/// </summary>
public static class StoreyGround
{
    /// <summary><c>storeyGroundLift</c>: <c>ground(x, z) − datum</c> for storey 0 (or none), else 0; no sampler / NaN = 0.</summary>
    public static double Lift(double? level, double worldX, double worldZ, double datumY, Func<double, double, double>? sampler)
    {
        if ((level ?? 0) != 0) return 0;
        if (sampler is null) return 0;
        if (!double.IsFinite(datumY)) return 0;
        double y = sampler(worldX, worldZ);
        if (!double.IsFinite(y)) return 0;
        return y - datumY;
    }

    /// <summary><c>storeyGroundRelift</c>: mount (applied 0) and re-drape are one move; "nothing to say" keeps the lift.</summary>
    public static GroundStep Relift(double applied, double? level, double worldX, double worldZ, double datumY,
                                    Func<double, double, double>? sampler)
        => ReliftAgainst(applied, level, worldX, worldZ, datumY, sampler);

    /// <summary><c>tileDatumStep</c>: the datum is a height sample too — the same rule against the world's zero.</summary>
    public static DatumStep TileDatumStep(double applied, double worldX, double worldZ, Func<double, double, double>? sampler)
    {
        var s = ReliftAgainst(applied, 0, worldX, worldZ, 0, sampler);
        return new DatumStep(s.Lift, s.Delta);
    }

    private static GroundStep ReliftAgainst(double applied, double? level, double worldX, double worldZ, double datumY,
                                            Func<double, double, double>? sampler)
    {
        double have = double.IsFinite(applied) ? applied : 0;
        if ((level ?? 0) != 0) return new GroundStep(0, -have);
        if (sampler is null || !double.IsFinite(datumY)) return new GroundStep(have, 0);
        double y = sampler(worldX, worldZ);
        if (!double.IsFinite(y)) return new GroundStep(have, 0);
        double lift = y - datumY;
        return new GroundStep(lift, lift - have);
    }

    /// <summary><c>markerLiftPoint</c>: a prop marker samples at its placement's anchor (when finite), a room marker at its own point.</summary>
    public static P2 MarkerLiftPoint(P2 at, P2? anchor)
        => anchor is { } a && double.IsFinite(a.X) && double.IsFinite(a.Z) ? new P2(a.X, a.Z) : new P2(at.X, at.Z);
}
