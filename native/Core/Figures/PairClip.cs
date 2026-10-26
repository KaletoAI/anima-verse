using System;
using System.Collections.Generic;
using System.Text.RegularExpressions;

namespace AnimaNative.Figures;

/// <summary><c>PairClipInput</c> of client3d/src/game/pairClip.ts: the server's game-clock numbers and the local clip clock.</summary>
/// <param name="ElapsedGameS">GAME seconds since the interaction began, as of the last poll; null BETWEEN polls</param>
/// <param name="Rate">game seconds per real second (0 = frozen world)</param>
/// <param name="Loop">does the clip repeat, or hold its last frame</param>
/// <param name="ClipDurationS">the clip's own length (0 / unknown = no wrap, no clamp)</param>
/// <param name="LocalClipT">the clip clock this figure carries, REAL seconds; null = adopt a fresh interaction</param>
/// <param name="SnapS">drift threshold of the snap; null = <see cref="PairClip.SnapS"/></param>
public readonly record struct PairClipInput(double? ElapsedGameS, double Rate, bool Loop, double ClipDurationS,
                                            double? LocalClipT = null, double? SnapS = null);

/// <summary>One horizontal track of a raw pair clip half (three's <c>KeyframeTrack</c>: name, times, flat values).</summary>
public sealed record PairTrack(string Name, float[] Times, float[] Values);

/// <summary>
/// PAIR CLIPS (§ A8a) — the clip timing of client3d/src/game/pairClip.ts (<c>pairClipPhase</c>, <c>PAIR_SNAP_S</c>), the
/// root path of a half (figures.ts <c>extractRootPath</c>, <c>isPairClipName</c>; the interpolation is
/// <see cref="BridgeTravel.RootPathAt"/>), the anchor transform and the height rule of npcs.ts <c>tickInteraction</c>.
/// Vectors shared/test-vectors/pair_clip_phase.json (hand derivations: client3d/scripts/smoke_pair_realtime.mjs),
/// pair_clip_geometry.json (smoke_clip_pair.mjs) and pair_height.json (smoke_pair_storey.mjs).
/// </summary>
public static class PairClip
{
    /// <summary><c>PAIR_SNAP_S</c>: drift (real seconds) between the local clip clock and a fresh poll beyond which it snaps.</summary>
    public const double SnapS = 0.3;
    /// <summary>figures.ts <c>PAIR_RESYNC_S</c>: the figure re-seeks its action only when its own time drifted more than this.</summary>
    public const double ResyncS = 0.2;
    /// <summary>The browser's clip files are Mixamo centimetres (three's FBXLoader keeps the file unit): /100 = metres.</summary>
    public const double BrowserUnitsPerMetre = 100;

    /// <summary>
    /// <c>pairClipPhase(input)</c>: the server's clip clock is <c>elapsed / rate</c> (real seconds, only with a finite
    /// elapsed and rate &gt; 0); a missing local clock adopts it (else 0), a local clock more than the snap threshold off
    /// snaps to it (strict), otherwise the local clock stays; clamped at 0. The phase wraps a cycle and clamps a one-shot
    /// against a positive length.
    /// </summary>
    public static (double ClipT, double Phase) Phase(PairClipInput input)
    {
        double snapS = input.SnapS ?? SnapS;
        double? serverT = input.ElapsedGameS is { } e && double.IsFinite(e) && input.Rate > 0 ? Math.Max(0, e / input.Rate) : null;
        double clipT;
        if (input.LocalClipT is not { } local || !double.IsFinite(local)) clipT = serverT ?? 0;
        else if (serverT is { } s && Math.Abs(local - s) > snapS) clipT = s;
        else clipT = local;
        clipT = Math.Max(0, clipT);
        return (clipT, PhaseAt(clipT, input.Loop, input.ClipDurationS));
    }

    /// <summary><c>clipPhaseAt</c>: a cycle replays (<c>t mod length</c>), a one-shot holds its end; no length = the clock.</summary>
    private static double PhaseAt(double clipT, bool loop, double clipDurationS)
    {
        if (!(clipDurationS > 0)) return clipT;
        return loop ? clipT % clipDurationS : Math.Min(clipT, clipDurationS);
    }

    /// <summary><c>isPairClipName</c>: a <c>&lt;kind&gt;__a</c> / <c>__b</c> half.</summary>
    public static bool IsPairClipName(string name) => ClipLibraryRules.IsPairName(name);

    private static readonly Regex MixamoPrefix = new("^mixamorig:?", RegexOptions.IgnoreCase | RegexOptions.CultureInvariant);
    private static readonly Regex HipsDot = new("hips\\.", RegexOptions.IgnoreCase | RegexOptions.CultureInvariant);

    /// <summary>
    /// <c>extractRootPath(clip)</c>: the FIRST <c>.position</c> track whose name (a leading <c>mixamorig:</c> stripped)
    /// matches <c>/hips\./i</c>; per key its x and z divided by <paramref name="unitsPerMetre"/> (Float32, like the
    /// browser's arrays) — metres in the clip's own frame, Y ignored. No such track = the zero path at t 0.
    /// The browser divides by 100 (FBXLoader keeps Mixamo centimetres); Godot's FBX import already yields metres.
    /// </summary>
    public static RootPath ExtractRootPath(IEnumerable<PairTrack> tracks, double unitsPerMetre = BrowserUnitsPerMetre)
    {
        foreach (var t in tracks)
        {
            if (!t.Name.EndsWith(".position", StringComparison.Ordinal) || !HipsDot.IsMatch(MixamoPrefix.Replace(t.Name, ""))) continue;
            int n = t.Times.Length;
            var xz = new float[n * 2];
            for (int i = 0; i < n; i++)
            {
                xz[i * 2] = (float)(t.Values[i * 3] / unitsPerMetre);
                xz[i * 2 + 1] = (float)(t.Values[i * 3 + 2] / unitsPerMetre);
            }
            return new RootPath((float[])t.Times.Clone(), xz);
        }
        return new RootPath(new float[] { 0 }, new float[] { 0, 0 });
    }

    /// <summary>
    /// The anchor transform of § A8a (npcs.ts <c>tickInteraction</c> ↔ <c>interaction_engine._rotate</c>):
    /// <c>x = ax + rx·cos(yaw) + rz·sin(yaw)</c>, <c>z = az − rx·sin(yaw) + rz·cos(yaw)</c>.
    /// </summary>
    public static (double X, double Z) AnchorPoint(double ax, double az, double yaw, double rx, double rz)
    {
        double c = Math.Cos(yaw), s = Math.Sin(yaw);
        return (ax + rx * c + rz * s, az - rx * s + rz * c);
    }

    /// <summary>
    /// The height of a pair figure (npcs.ts <c>tickInteraction</c>): a pair seated on a PLACE stands at the place's first
    /// slot (<paramref name="seatY"/> non-null — even at 0); else the room's standing height
    /// (<paramref name="roomStand"/>, null = none); else the ground. The later rungs are asked only when needed.
    /// </summary>
    public static double StandY(double? seatY, Func<double?> roomStand, Func<double> ground)
        => seatY ?? roomStand() ?? ground();
}

/// <summary>The interaction block of a worldmap row (§ A8a <c>MapInteraction</c>), as parsed (<see cref="CharacterRow"/>).</summary>
/// <param name="ElapsedS">GAME seconds into the interaction (NaN when the row lacks it)</param>
/// <param name="ClipDurationS">the clip's own length (<c>clip_duration_s ?? 0</c>)</param>
/// <param name="Rate">game seconds per real second (<c>rate ?? 0</c>)</param>
public sealed record PairInteraction(string Id, string Kind, string Role, string Partner, PairAnchor Anchor, double ElapsedS,
                                     double ClipDurationS, bool Loop, double Rate)
{
    /// <summary>The clip half this figure plays: <c>&lt;kind&gt;__&lt;role&gt;</c>.</summary>
    public string Clip => $"{Kind}__{Role}";
}

/// <summary>The pair's anchor: world x/z, the yaw of the clip frame (three's Y rotation) and the place it sits on (null = ground).</summary>
public readonly record struct PairAnchor(double X, double Z, double Yaw, string? PlaceId);

/// <summary>
/// A pair interaction as the renderer runs it (npcs.ts <c>PairPlay</c>): the anchor, the game-clock elapsed of the last
/// poll and ONE local number — the clip clock in REAL seconds — advanced by the frame time and reconciled against each
/// NEW poll (<see cref="PairClip.Phase"/>).
/// </summary>
public sealed class PairPlay
{
    public required string Id { get; init; }
    /// <summary><c>&lt;kind&gt;__&lt;role&gt;</c>.</summary>
    public required string Clip { get; init; }
    public PairAnchor Anchor { get; set; }
    /// <summary>Interaction time in GAME seconds as of the last poll, advanced by dt·rate between polls.</summary>
    public double Elapsed { get; set; }
    /// <summary>REAL seconds since the interaction started: the clip's own clock.</summary>
    public double ClipT { get; set; }
    public double ClipDuration { get; init; }
    public bool Loop { get; init; }
    public double Rate { get; set; }
    public long Stamp { get; set; }

    /// <summary>
    /// npcs.ts <c>adoptInteraction</c>: no block = none; a new id (or a different half) is adopted whole — the clip clock
    /// from the server's numbers, <paramref name="fresh"/> = the caller drops route, stations and climb; the same id takes
    /// the rate and the anchor at once and reconciles the clip clock only for a NEW poll (<paramref name="stamp"/>): the
    /// elapsed snaps when it is more than the snap threshold off, the clock through <see cref="PairClip.Phase"/>.
    /// </summary>
    public static PairPlay? Adopt(PairPlay? cur, PairInteraction? it, long stamp, out bool fresh)
    {
        fresh = false;
        if (it is null) return null;
        var clip = it.Clip;
        if (cur is null || cur.Id != it.Id || cur.Clip != clip)
        {
            fresh = true;
            return new PairPlay
            {
                Id = it.Id, Clip = clip, Anchor = it.Anchor, Elapsed = it.ElapsedS, Rate = it.Rate, Stamp = stamp,
                ClipT = PairClip.Phase(new PairClipInput(it.ElapsedS, it.Rate, it.Loop, it.ClipDurationS)).ClipT,
                ClipDuration = it.ClipDurationS, Loop = it.Loop,
            };
        }
        cur.Rate = it.Rate;
        cur.Anchor = it.Anchor;
        if (cur.Stamp != stamp)
        {
            if (Math.Abs(cur.Elapsed - it.ElapsedS) > PairClip.SnapS) cur.Elapsed = it.ElapsedS;
            cur.ClipT = PairClip.Phase(new PairClipInput(it.ElapsedS, cur.Rate, cur.Loop, cur.ClipDuration, cur.ClipT)).ClipT;
            cur.Stamp = stamp;
        }
        return cur;
    }

    /// <summary>
    /// The clock part of <c>tickInteraction</c>: the game clock runs by dt·rate, the CLIP clock by the frame's real dt
    /// only while rate &gt; 0 (a frozen world stands still); returns the phase the half is seeked to.
    /// </summary>
    public double Advance(double dt)
    {
        Elapsed += dt * Rate;
        if (Rate > 0) ClipT += dt;
        return PairClip.Phase(new PairClipInput(null, Rate, Loop, ClipDuration, ClipT)).Phase;
    }

    /// <summary>
    /// The placement part of <c>tickInteraction</c>: the root at <c>anchor + R_y(yaw) · clipRoot</c>; the height of the
    /// place's first slot when the anchor names a place the lookup knows (<paramref name="seatY"/>: id, anchor x, z →
    /// slot 0's y or null), else the room's stand at the point, else the ground there.
    /// </summary>
    public V3 Place((double X, double Z) root, Func<string, double, double, double?> seatY,
                    Func<double, double, double?> roomStand, Func<double, double, double> ground)
    {
        var a = Anchor;
        var (x, z) = PairClip.AnchorPoint(a.X, a.Z, a.Yaw, root.X, root.Z);
        double? seat = !string.IsNullOrEmpty(a.PlaceId) ? seatY(a.PlaceId!, a.X, a.Z) : null;
        return new V3(x, PairClip.StandY(seat, () => roomStand(x, z), () => ground(x, z)), z);
    }
}

/// <summary>
/// The figure's BIND anchoring — packages/scene-render/src/figure.ts <c>anchorFigureBind</c> and the same centring in
/// client3d's <c>Figure</c> constructor: the body measured in its bind pose, centred on its bounding box in XZ, its lowest
/// point on y = 0. Vectors shared/test-vectors/figure_normalisation.json (hand derivations:
/// client3d/scripts/smoke_figure_normalisation.mjs).
/// </summary>
public static class FigureBind
{
    /// <summary>The offset that centres a box (scaled by <paramref name="scale"/>) in XZ and puts its bottom on 0.</summary>
    public static V3 Offset(V3 min, V3 max, double scale)
    {
        double cx = (min.X + max.X) * 0.5, cz = (min.Z + max.Z) * 0.5;
        return new V3(-cx * scale, -min.Y * scale, -cz * scale);
    }

    /// <summary>
    /// <c>anchorFigureBind(THREE, pivot, figureHeight)</c>: the pivot's scale and position are reset (owned), the bind box
    /// measured, <c>k = height / (size.y || 1)</c>, position <see cref="Offset"/>(min, max, k). Returns k and the position.
    /// </summary>
    public static (double Scale, V3 Position) Anchor(V3 min, V3 max, double figureHeight)
    {
        double sy = max.Y - min.Y;
        double k = figureHeight / (sy == 0 || double.IsNaN(sy) ? 1 : sy);
        return (k, Offset(min, max, k));
    }
}
