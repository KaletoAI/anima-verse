using System;
using System.Collections.Generic;
using System.Text.RegularExpressions;

namespace AnimaNative.Figures;

/// <summary><c>PairClipInput</c> of client3d/src/game/pairClip.ts: the server's clip clock and the local one.</summary>
/// <param name="ClipS">the server's clip clock <c>clip_s</c> (CLIP seconds since the clip began) as of the last poll;
/// null BETWEEN polls</param>
/// <param name="Tempo">clip seconds per real second (<c>tempo</c>; <see cref="PairClip.ClipTempo"/> clamps it)</param>
/// <param name="Frozen">a frozen world (rate 0): the local clock stands</param>
/// <param name="Loop">does the clip repeat, or hold its last frame</param>
/// <param name="ClipDurationS">the clip's own length (0 / unknown = no wrap, no clamp)</param>
/// <param name="LocalClipT">the clip clock this figure carries, CLIP seconds; null = adopt a fresh interaction</param>
/// <param name="SnapS">drift threshold of the snap; null = <see cref="PairClip.SnapS"/></param>
/// <param name="Dt">REAL seconds this frame adds to the local clock (times the tempo)</param>
public readonly record struct PairClipInput(double? ClipS, double Tempo, bool Frozen, bool Loop, double ClipDurationS,
                                            double? LocalClipT = null, double? SnapS = null, double Dt = 0);

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
    /// <summary><c>PAIR_SNAP_S</c>: drift (clip seconds) between the local clip clock and a fresh poll beyond which it snaps.</summary>
    public const double SnapS = 0.3;
    /// <summary>figures.ts <c>PAIR_RESYNC_S</c>: the figure re-seeks its action only when its own time drifted more than this.</summary>
    public const double ResyncS = 0.2;
    /// <summary>The browser's clip files are Mixamo centimetres (three's FBXLoader keeps the file unit): /100 = metres.</summary>
    public const double BrowserUnitsPerMetre = 100;

    /// <summary><c>clipTempo</c>: a finite tempo clamped to [0.2, 1]; 1 for anything else (a row without one).</summary>
    public static double ClipTempo(double? tempo)
        => tempo is { } t && double.IsFinite(t) ? Math.Min(1, Math.Max(0.2, t)) : 1;

    /// <summary>
    /// <c>pairClipPhase(input)</c>: the local clock advances by <c>dt · tempo</c> (nothing while frozen); the server's
    /// <c>clip_s</c> (finite, clamped at 0) is adopted when there is no local clock (else 0) and snapped to when the
    /// advanced local clock is more than the snap threshold off (strict), otherwise the local clock stays; clamped at 0.
    /// The phase wraps a cycle and clamps a one-shot against a positive length.
    /// </summary>
    public static (double ClipT, double Phase) Phase(PairClipInput input)
    {
        double snapS = input.SnapS ?? SnapS;
        double step = !input.Frozen && input.Dt > 0 ? input.Dt * ClipTempo(input.Tempo) : 0;
        double? serverT = input.ClipS is { } c && double.IsFinite(c) ? Math.Max(0, c) : null;
        double clipT;
        if (input.LocalClipT is not { } local || !double.IsFinite(local)) clipT = serverT ?? 0;
        else
        {
            double advanced = local + step;
            clipT = serverT is { } s && Math.Abs(advanced - s) > snapS ? s : advanced;
        }
        clipT = Math.Max(0, clipT);
        return (clipT, PhaseAt(clipT, input.Loop, input.ClipDurationS));
    }

    /// <summary><c>clipPhaseAt</c>: a cycle replays (<c>t mod length</c>), a one-shot holds its end; no length = the clock.</summary>
    private static double PhaseAt(double clipT, bool loop, double clipDurationS)
    {
        if (!(clipDurationS > 0)) return clipT;
        return loop ? clipT % clipDurationS : Math.Min(clipT, clipDurationS);
    }

    /// <summary><c>isPairClipName</c>: a <c>&lt;kind&gt;__a</c> … <c>__e</c> role half (pair or group).</summary>
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
/// <param name="Members">role ("a".."e", clip order) → name of every participant, this figure included (G2b)</param>
public sealed record PairInteraction(string Id, string Kind, string Role, IReadOnlyDictionary<string, string> Members, PairAnchor Anchor, double ElapsedS,
                                     double ClipDurationS, bool Loop, double Rate)
{
    public string Alt { get; init; } = "";
    /// <summary><c>clip_s</c>: the scene's clip clock, CLIP seconds since this clip began (null when the row lacks it).</summary>
    public double? ClipS { get; init; }
    /// <summary><c>tempo</c>: clip seconds per real second, clamped to [0.2, 1] (1 when the row lacks it).</summary>
    public double Tempo { get; init; } = 1;
    /// <summary>The role's own half, used when this rig lacks the alternative.</summary>
    public string Base => ClipLibraryRules.IndexName(Kind, Role);
    /// <summary>The requested half, including the optional alternative suffix.</summary>
    public string Clip => ClipLibraryRules.IndexName(Kind, Role, Alt);
}

/// <summary>
/// The worldmap <c>place</c> block's scene clock (§ A8a): a place a SOLO furniture run seated the figure on carries
/// that scene's <c>scene_id</c>, <c>clip_s</c> and <c>tempo</c> (clamped, 1 when the row lacks it).
/// </summary>
public sealed record SoloSceneClock(string SceneId, double ClipS, double Tempo);

/// <summary>
/// The held clip's local clock of a SOLO furniture scene (client3d/src/game/pairClip.ts <c>HeldClock</c>,
/// <c>adoptHeldClock</c> / <c>stepHeldClock</c>): CLIP seconds since the clip began, the tempo, the scene and the poll
/// stamp it was last reconciled with — the pair rule (<see cref="PairClip.Phase"/>) without a wrap; the figure wraps
/// against the clip it plays.
/// </summary>
public sealed record HeldClock(string SceneId, double ClipT, double Tempo, long Stamp)
{
    /// <summary>
    /// No clock in the row = none; a new scene adopts <c>clip_s</c> as it is; the same scene takes the tempo at once and
    /// reconciles the clock only for a NEW poll (<paramref name="stamp"/>), snapping beyond <see cref="PairClip.SnapS"/>.
    /// </summary>
    public static HeldClock? Adopt(HeldClock? prev, SoloSceneClock? block, long stamp)
    {
        if (block is null || block.SceneId.Length == 0 || !double.IsFinite(block.ClipS)) return null;
        double tempo = PairClip.ClipTempo(block.Tempo);
        if (prev is null || prev.SceneId != block.SceneId) return new HeldClock(block.SceneId, Math.Max(0, block.ClipS), tempo, stamp);
        if (prev.Stamp == stamp) return prev with { Tempo = tempo };
        double clipT = PairClip.Phase(new PairClipInput(block.ClipS, tempo, false, true, 0, prev.ClipT)).ClipT;
        return new HeldClock(prev.SceneId, clipT, tempo, stamp);
    }

    /// <summary>One frame: <c>dt · tempo</c> CLIP seconds, nothing in a frozen world.</summary>
    public HeldClock Step(double dt, bool frozen)
        => this with { ClipT = PairClip.Phase(new PairClipInput(null, Tempo, frozen, true, 0, ClipT, Dt: dt)).ClipT };
}

/// <summary>The pair's anchor: world x/z, the yaw of the clip frame (three's Y rotation) and the place it sits on (null = ground).</summary>
public readonly record struct PairAnchor(double X, double Z, double Yaw, string? PlaceId);

/// <summary>
/// A pair interaction as the renderer runs it (npcs.ts <c>PairPlay</c>): the anchor, the game-clock elapsed of the last
/// poll and ONE local number — the clip clock in CLIP seconds — advanced by the frame time × the scene's tempo and
/// reconciled against each NEW poll's <c>clip_s</c> (<see cref="PairClip.Phase"/>).
/// </summary>
public sealed class PairPlay
{
    public (PairPose From, double At)? Blend { get; set; }
    public required string Id { get; init; }
    /// <summary><c>&lt;kind&gt;__&lt;role&gt;</c>, optionally followed by <c>~&lt;alt&gt;</c>.</summary>
    public required string Clip { get; init; }
    public string Base { get; init; } = "";
    /// <summary>role → member name (the interaction's <c>members</c>, this figure included) — the pair height's cast.</summary>
    public IReadOnlyDictionary<string, string> Roles { get; set; } = new Dictionary<string, string>();

    public string? ResolveClip(Func<string, bool> usable)
        => ClipLibraryRules.SelectClip(Clip, Base.Length > 0 ? Base : Clip, usable);
    public PairAnchor Anchor { get; set; }
    /// <summary>Interaction time in GAME seconds as of the last poll, advanced by dt·rate between polls.</summary>
    public double Elapsed { get; set; }
    /// <summary>CLIP seconds since the clip began: the clip's own clock, advanced by dt·tempo.</summary>
    public double ClipT { get; set; }
    /// <summary>Clip seconds per real second (the scene's <c>tempo</c>, 0.2..1).</summary>
    public double Tempo { get; set; } = 1;
    public double ClipDuration { get; init; }
    public bool Loop { get; init; }
    public double Rate { get; set; }
    public long Stamp { get; set; }

    /// <summary>
    /// npcs.ts <c>adoptInteraction</c>: no block = none; a new id (or a different half — a pose switch) is adopted whole —
    /// the clip clock from the server's <c>clip_s</c>, <paramref name="fresh"/> = the caller drops route, stations and
    /// climb; the same id takes the rate, the tempo and the anchor at once and reconciles the clip clock only for a NEW
    /// poll (<paramref name="stamp"/>): the elapsed snaps when it is more than the snap threshold off, the clock through
    /// <see cref="PairClip.Phase"/>.
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
                Blend = cur?.Id == it.Id ? cur.Blend : null,
                Id = it.Id, Clip = clip, Base = it.Base, Anchor = it.Anchor, Elapsed = it.ElapsedS, Rate = it.Rate, Stamp = stamp,
                Tempo = PairClip.ClipTempo(it.Tempo),
                ClipT = PairClip.Phase(new PairClipInput(it.ClipS, it.Tempo, it.Rate <= 0, it.Loop, it.ClipDurationS)).ClipT,
                ClipDuration = it.ClipDurationS, Loop = it.Loop, Roles = it.Members,
            };
        }
        cur.Roles = it.Members;
        cur.Rate = it.Rate;
        cur.Tempo = PairClip.ClipTempo(it.Tempo);
        cur.Anchor = it.Anchor;
        if (cur.Stamp != stamp)
        {
            if (Math.Abs(cur.Elapsed - it.ElapsedS) > PairClip.SnapS) cur.Elapsed = it.ElapsedS;
            cur.ClipT = PairClip.Phase(new PairClipInput(it.ClipS, cur.Tempo, cur.Rate <= 0, cur.Loop, cur.ClipDuration, cur.ClipT)).ClipT;
            cur.Stamp = stamp;
        }
        return cur;
    }

    /// <summary>
    /// The clock part of <c>tickInteraction</c>: the game clock runs by dt·rate, the CLIP clock by the frame's real dt
    /// times the tempo only while rate &gt; 0 (a frozen world stands still); returns the phase the half is seeked to.
    /// </summary>
    public double Advance(double dt)
    {
        Elapsed += dt * Rate;
        var (clipT, phase) = PairClip.Phase(new PairClipInput(null, Tempo, Rate <= 0, Loop, ClipDuration, ClipT, Dt: dt));
        ClipT = clipT;
        return phase;
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
