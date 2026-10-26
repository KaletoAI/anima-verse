using System;

namespace AnimaNative.Water;

/// <summary>How far the terrain rule reaches at a point (<c>walk.ts</c> <c>GroundScope</c>, the server's
/// <c>terrain_query.SCOPE_*</c>): out between the places, inside an open place, inside a building or indoor room.</summary>
public enum GroundScope { Wilderness, Open, Built }

/// <summary>The two depths a ground carries (<c>meta.move_sink_m</c> / <c>meta.idle_sink_m</c>).</summary>
public readonly record struct GroundSink(double Move, double Idle);

/// <summary>
/// The scope-filtered ground word at a point (<c>walk.ts</c> <c>GroundWater</c>): the movement type
/// (<c>walk_run</c>, <c>walk</c>, <c>swim</c>, <c>crawl</c>), the sinks, and the mirror over the point (null = none applies).
/// </summary>
public readonly record struct GroundWater(string Movement, GroundSink Sink, double? Water);

/// <summary>A prop-water hit (<c>propWaterMath.ts</c> <c>WaterHit</c>): mirror and bed in the caller's frame plus the
/// swim threshold; <see cref="GroundY"/> is the unpadded lattice bed a caller may hand the wade gate instead of its own.</summary>
public readonly record struct WaterHit(double Y, double BedY, double SwimFromM)
{
    public double? GroundY { get; init; }
}

/// <summary>
/// The water gates of <c>client3d/src/game/walk.ts</c> — the pure rules the underwater ghost and (E5) the swimming
/// figures share, checked against <c>shared/test-vectors/prop_water.json</c>:
/// <c>groundScope</c>, <c>groundWaterLevel</c>, <c>wadeGate</c>, <c>swimFrom</c>, <c>propWaterWord</c>,
/// <c>propWaterCarry</c>, <c>submergedInWater</c>, <c>ghostCutY</c>, <c>ghostWaterLevel</c>.
/// </summary>
public static class WaterGates
{
    /// <summary><c>SWIM_FROM_DEFAULT_M</c>: the swim depth where the kind names no <c>meta.swim_from_m</c>.</summary>
    public const double SwimFromDefaultM = 1.0;
    /// <summary><c>WATER_GHOST_FROM_M</c>: from how much water a thing gets its underwater ghost — the rim ramp's 5 cm
    /// (<see cref="WaterShade.EdgeFadeM"/>; the same number on purpose).</summary>
    public const double GhostFromM = WaterShade.EdgeFadeM;
    /// <summary><c>WATER_GHOST_OPACITY</c> (submergedGhost.ts): the ghost's own opacity.</summary>
    public const double GhostOpacity = 0.4;
    /// <summary><c>propWaterWord</c>'s swimmer sinks inside a prop water region (move, idle).</summary>
    public static readonly GroundSink PropWaterSink = new(0.35, 1.3);

    /// <summary><c>groundScope(placeIsArea, roomIsOutdoor)</c>: a room answers first, then the footprint, else the wilderness.</summary>
    public static GroundScope ScopeOf(bool? placeIsArea, bool? roomIsOutdoor)
    {
        if (roomIsOutdoor is { } r) return r ? GroundScope.Open : GroundScope.Built;
        if (placeIsArea is { } a) return a ? GroundScope.Open : GroundScope.Built;
        return GroundScope.Wilderness;
    }

    /// <summary><c>groundWaterLevel(level, scope)</c>: a built place hides the painted water; a non-finite level is none.</summary>
    public static double? GroundWaterLevel(double? level, GroundScope scope)
    {
        if (level is not { } l || !double.IsFinite(l)) return null;
        return scope == GroundScope.Built ? null : l;
    }

    /// <summary><c>swimFrom(value)</c>: junk and a negative threshold are the default; 0 is a value.</summary>
    public static double SwimFrom(double? value)
        => value is { } v && double.IsFinite(v) && v >= 0 ? v : SwimFromDefaultM;

    /// <summary>
    /// <c>wadeGate(word, groundY, swimFromM)</c>: below the swim depth the figure WADES — <c>walk_run</c>, no sink, no
    /// mirror; no mirror or no ground = the word as it is.
    /// </summary>
    public static GroundWater WadeGate(GroundWater word, double groundY, double? swimFromM)
    {
        if (word.Water is not { } level || !double.IsFinite(level) || !double.IsFinite(groundY)) return word;
        if (level - groundY >= SwimFrom(swimFromM)) return word;
        return new GroundWater("walk_run", new GroundSink(0, 0), null);
    }

    /// <summary>
    /// <c>propWaterWord(word, groundY, swimFromM, region)</c>: inside a prop water region the word is SWIM with the
    /// river's sinks at the region's mirror, gated by the region's own threshold over its own bed (else the caller's
    /// ground); outside, the painted word through the ordinary wade gate. Prop water overrides the scope.
    /// </summary>
    public static GroundWater PropWaterWord(GroundWater word, double groundY, double? swimFromM, WaterHit? region)
        => region is { } r
            ? WadeGate(new GroundWater("swim", PropWaterSink, r.Y), r.GroundY ?? groundY, r.SwimFromM)
            : WadeGate(word, groundY, swimFromM);

    /// <summary><c>propWaterCarry(bedY, region)</c>: the step ladder carries a walker on the higher of bed and mirror.</summary>
    public static double PropWaterCarry(double bedY, WaterHit? region) => region is { } r ? Math.Max(bedY, r.Y) : bedY;

    /// <summary><c>submergedInWater(bedY, waterLevel)</c>: at least <see cref="GhostFromM"/> of water over the base.</summary>
    public static bool SubmergedInWater(double bedY, double? waterLevel)
        => waterLevel is { } w && double.IsFinite(w) && double.IsFinite(bedY) && w - bedY >= GhostFromM;

    /// <summary><c>ghostCutY(baseY, waterLevel)</c>: the level the ghost cuts itself off at, or null where dry.</summary>
    public static double? GhostCutY(double baseY, double? waterLevel)
        => SubmergedInWater(baseY, waterLevel) ? waterLevel : null;

    /// <summary><c>ghostWaterLevel(level, insideness)</c>: the raster's (dilated) level only where the drawn water is,
    /// i.e. where <c>waterInside(sd)</c> &gt; 0; NaN elsewhere (which <see cref="GhostCutY"/> reads as dry).</summary>
    public static double GhostWaterLevel(double waterLevel, double insideness) => insideness > 0 ? waterLevel : double.NaN;

    /// <summary>The placement gate in one call (<c>refreshPlacementGhost</c> / <c>ghostLevelOf</c>): the raster's
    /// level and outline at (x, z) against the base y.</summary>
    public static double? PlacementGhostCut(WaterRaster? raster, double x, double z, double baseY)
    {
        double level = WaterRaster.LevelAt(raster, x, z);
        double inside = WaterShade.Inside(WaterRaster.SdAt(raster, x, z));
        double cut = GhostWaterLevel(level, inside);
        return GhostCutY(baseY, double.IsNaN(cut) ? null : cut);
    }
}
