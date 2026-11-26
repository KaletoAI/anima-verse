using System;
using System.Collections.Generic;
using System.Text.Json;

namespace AnimaNative.Figures;

/// <summary>A horizontal point of a pair clip's frame, metres (+X = side, +Z = forward).</summary>
public readonly record struct PairXZ(double X, double Z);

/// <summary>A pair/group half's root as the clip library keeps it: its horizontal root path and the clip's contact pivot.</summary>
public sealed record PairRoot(RootPath Path, PairXZ Pivot)
{
    /// <summary>The renderer-only turn of the half's own role (<c>orientation.role_turn_deg</c>, <see cref="RoleTurn"/>); none when absent.</summary>
    public RoleTurnDeg Turn { get; init; }
}

/// <summary>
/// PAIR SCALE — packages/scene-render/src/pairScale.ts (owner decision 2026-11-20): a pair/group clip's alignment is
/// measured on two 1.70 m figures; in the game each figure's horizontal root path p is scaled by its own ratio
/// a = height / 1.70 about the clip's contact pivot C, <c>p' = C + a·(p − C)</c>, which keeps a body-fixed contact on C
/// for any height. C is the clip row's <c>pair_pivot_cm</c> [side, forward] (cm, clip frame); absent or invalid = the
/// clip frame's origin. A pair/group half's renderer-only <c>shift_cm</c> scales with its figure (a·s); a solo shift
/// stays absolute. a == 1 returns the input untouched (no arithmetic), so a 1.70 m figure is placed bit for bit as
/// before. Vectors shared/test-vectors/pair_scale.json (hand derivations: scripts/smoke_pair_scale.mjs).
/// </summary>
public static class PairScale
{
    /// <summary>scene-render <c>FIGURE_HEIGHT_M</c>: the height every figure has in the Pose library's measurement.</summary>
    public const double FigureHeightM = 1.7;
    /// <summary><c>PAIR_PIVOT_BOUND_CM</c>: the bound of a stored pivot, cm per component (the server's).</summary>
    public const double PivotBoundCm = 300;
    /// <summary><c>PAIR_PIVOT_ORIGIN</c>: the pivot of a clip without a stored one.</summary>
    public static readonly PairXZ Origin = new(0, 0);

    /// <summary><c>pairFigureScale</c>: a = height / 1.70; 1 for a missing, non-finite or non-positive height.</summary>
    public static double FigureScale(double? heightM)
        => heightM is { } h && double.IsFinite(h) && h > 0 ? h / FigureHeightM : 1;

    /// <summary>
    /// <c>pairPivotOf</c>: the stored <c>pair_pivot_cm</c> [side, forward] → metres; anything but an array of exactly two
    /// finite JSON numbers within ±<see cref="PivotBoundCm"/> → <see cref="Origin"/>.
    /// </summary>
    public static PairXZ PivotOf(JsonElement stored)
    {
        if (stored.ValueKind != JsonValueKind.Array || stored.GetArrayLength() != 2) return Origin;
        static bool Ok(JsonElement e, out double v)
        {
            v = 0;
            return e.ValueKind == JsonValueKind.Number && e.TryGetDouble(out v) && double.IsFinite(v) && Math.Abs(v) <= PivotBoundCm;
        }
        if (!Ok(stored[0], out var side) || !Ok(stored[1], out var forward)) return Origin;
        return new PairXZ(side / 100, forward / 100);
    }

    /// <summary><c>scalePairRoot</c>: p' = C + a·(p − C) for one figure's root (clip frame, metres); a == 1 returns <paramref name="root"/>.</summary>
    public static (double X, double Z) ScaleRoot((double X, double Z) root, PairXZ pivot, double a)
    {
        if (a == 1) return root;
        return (pivot.X + a * (root.X - pivot.X), pivot.Z + a * (root.Z - pivot.Z));
    }

    /// <summary><c>scalePairShift</c>: a pair/group half's renderer-only shift for a figure of scale a (a == 1: the shift itself).</summary>
    public static (double X, double Z) ScaleShift((double X, double Z) shift, double a)
        => a == 1 ? shift : (a * shift.X, a * shift.Z);
}
