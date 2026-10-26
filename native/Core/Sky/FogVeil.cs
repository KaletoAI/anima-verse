using System;
using System.Collections.Generic;
using System.Text.RegularExpressions;

namespace AnimaNative.Sky;

/// <summary>The veil's cell texture window (<c>FogGrid</c>): first cell and size in cells.</summary>
public readonly record struct FogGrid(double Cx0, double Cz0, double Cols, double Rows);

/// <summary>
/// The exploration haze's pure math (<c>client3d/src/scene/fogVeilMath.ts</c>, contract § A12): explored cells of
/// 64 m anchored at the world origin, their bounding box plus one ring as a texture whose texel centres sit on cell
/// centres, and the veil's strength from the camera height above its target.
/// </summary>
public static partial class FogVeil
{
    /// <summary><c>FOG_CELL_M</c> (the server's <c>EXPLORED_CELL_M</c>), <c>FOG_PAD_CELLS</c>, <c>FOG_BLEND_M</c>.</summary>
    public const double CellM = 64, PadCells = 1, BlendM = CellM / 2;
    /// <summary><c>FOG_CLEAR_H_M</c>, <c>FOG_FULL_H_M</c>, <c>FOG_ALPHA_MAX</c>, <c>FOG_FADE_S</c>, <c>FOG_TEX_MAX</c>.</summary>
    public const double ClearHM = 20, FullHM = 45, AlphaMax = 0.72, FadeS = 0.6, TexMax = 2048;

    /// <summary><c>fogCellOf</c>: <c>floor(v / 64)</c> — −1 m is cell −1, not 0.</summary>
    public static double CellOf(double v) => Math.Floor(v / CellM);

    [GeneratedRegex("^(-?[0-9]+),(-?[0-9]+)$", RegexOptions.CultureInvariant)]
    private static partial Regex CellKey();

    /// <summary><c>fogParseCell</c>: exactly two integers (ASCII digits, optional '-') — nothing else is a cell.</summary>
    public static (double Cx, double Cz)? ParseCell(string? key)
    {
        if (key is null) return null;
        // JS /^…$/ without the m flag: '$' matches only at the very end (.NET's '$' would also accept a final '\n').
        var m = CellKey().Match(key);
        if (!m.Success || m.Index + m.Length != key.Length) return null;
        return (double.Parse(m.Groups[1].Value, System.Globalization.CultureInfo.InvariantCulture),
                double.Parse(m.Groups[2].Value, System.Globalization.CultureInfo.InvariantCulture));
    }

    /// <summary><c>fogGrid</c>: the box of every readable cell plus one ring, each side capped at 2048; none = null.</summary>
    public static FogGrid? Grid(IEnumerable<string> cells)
    {
        double minX = double.PositiveInfinity, minZ = double.PositiveInfinity;
        double maxX = double.NegativeInfinity, maxZ = double.NegativeInfinity;
        int seen = 0;
        foreach (var key in cells)
        {
            if (ParseCell(key) is not { } c) continue;
            seen++;
            if (c.Cx < minX) minX = c.Cx;
            if (c.Cx > maxX) maxX = c.Cx;
            if (c.Cz < minZ) minZ = c.Cz;
            if (c.Cz > maxZ) maxZ = c.Cz;
        }
        if (seen == 0) return null;
        return new FogGrid(minX - PadCells, minZ - PadCells,
                           Math.Min(maxX - minX + 1 + 2 * PadCells, TexMax), Math.Min(maxZ - minZ + 1 + 2 * PadCells, TexMax));
    }

    /// <summary><c>fogTexUv</c>: a world point in the cell texture's 0…1 space (cell centres on texel centres).</summary>
    public static (double U, double V) TexUv(double x, double z, FogGrid g)
        => ((x / CellM - g.Cx0) / g.Cols, (z / CellM - g.Cz0) / g.Rows);

    /// <summary><c>fogTexIndex</c>: a cell's texel index, −1 outside the window.</summary>
    public static double TexIndex(double cx, double cz, FogGrid g)
    {
        double i = cx - g.Cx0, j = cz - g.Cz0;
        if (i < 0 || j < 0 || i >= g.Cols || j >= g.Rows) return -1;
        return j * g.Cols + i;
    }

    private static double Clamp01(double v) => !double.IsFinite(v) ? 0 : v < 0 ? 0 : v > 1 ? 1 : v;

    /// <summary><c>fogHeightAlpha</c>: smoothstep of the camera height above the target from 20 m to 45 m.</summary>
    public static double HeightAlpha(double heightM)
    {
        double t = Clamp01((heightM - ClearHM) / (FullHM - ClearHM));
        return t * t * (3 - 2 * t);
    }

    /// <summary><c>fogVeilAlpha</c>: 0.72 · (1 − explored, clamped) · the height ramp.</summary>
    public static double VeilAlpha(double heightM, double explored) => AlphaMax * (1 - Clamp01(explored)) * HeightAlpha(heightM);
}
