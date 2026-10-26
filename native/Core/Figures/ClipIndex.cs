using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.RegularExpressions;

namespace AnimaNative.Figures;

/// <summary>
/// One listing entry as the browser's figure library sees it (<c>ClipSource</c> of client3d/src/game/clipCommit.ts):
/// the kind (a pair half as <c>&lt;kind&gt;__&lt;role&gt;</c>), its set (<c>""</c> = neutral), the opaque URL, the
/// loop flag (null = not given = loop) and whether it carries root motion (<c>root_motion.mode</c> other than
/// <c>strip</c>).
/// </summary>
public sealed record ClipSourceEntry(string Kind, string Set, string Url, bool? Loop = null, bool RootMotion = false)
{
    /// <summary><c>clipLoops</c>: a missing flag loops (§ A8).</summary>
    public bool Loops => Loop ?? true;
}

/// <summary>The committed library: kind → (set → clip) in listing order of the kinds, plus the pair-half roots.</summary>
public sealed class ClipIndex<C>
{
    /// <summary>Kinds in the order their first clip was committed (the JS Map's insertion order).</summary>
    public List<string> Kinds { get; } = new();
    public Dictionary<string, Dictionary<string, C>> BySet { get; } = new(StringComparer.Ordinal);
    public Dictionary<string, object?> PairRoots { get; } = new(StringComparer.Ordinal);
    public bool HasKind(string kind) => BySet.ContainsKey(kind);
}

/// <summary>The per-clip operations of <c>commitInListOrder</c> (<c>CommitOps</c>).</summary>
public interface IClipCommitOps<C>
{
    void SetFlags(C clip, ClipSourceEntry source);
    bool IsPair(string kind);
    object? PairRoot(C clip);
    C Rename(C clip, string kind);
}

/// <summary>
/// The library bookkeeping of client3d's figure library as pure functions: <c>commitInListOrder</c>
/// (client3d/src/game/clipCommit.ts; vectors shared/test-vectors/clip_commit.json, derivations
/// client3d/scripts/smoke_clip_order.mjs), the per-character set chain (<c>clipsFor</c>, figures.ts) and
/// the pair-half name test (<c>isPairClipName</c>).
/// </summary>
public static class ClipLibraryRules
{
    private static readonly Regex PairName = new("__[ab]$", RegexOptions.CultureInvariant);

    /// <summary><c>isPairClipName</c>: a <c>&lt;kind&gt;__a</c>/<c>__b</c> half.</summary>
    public static bool IsPairName(string kind) => PairName.IsMatch(kind);

    /// <summary>
    /// <c>commitInListOrder(sources, results, ops)</c>: downloads may finish in any order, the LISTING owns
    /// precedence — the first clip per (kind, set) wins; a missing result (null or past the end) leaves a gap;
    /// a pair half records its root (a later half of the same name replaces it).
    /// </summary>
    public static ClipIndex<C> CommitInListOrder<C>(IReadOnlyList<ClipSourceEntry> sources, IReadOnlyList<C?> results,
                                                    IClipCommitOps<C> ops) where C : class
    {
        var index = new ClipIndex<C>();
        for (int i = 0; i < sources.Count; i++)
        {
            var s = sources[i];
            if (i >= results.Count || results[i] is not { } r) continue;
            var clip = ops.Rename(r, s.Kind);
            ops.SetFlags(clip, s);
            if (ops.IsPair(s.Kind)) index.PairRoots[s.Kind] = ops.PairRoot(clip);
            if (!index.BySet.TryGetValue(s.Kind, out var bySet))
            {
                index.BySet[s.Kind] = bySet = new Dictionary<string, C>(StringComparer.Ordinal);
                index.Kinds.Add(s.Kind);
            }
            bySet.TryAdd(s.Set, clip);
        }
        return index;
    }

    /// <summary>
    /// <c>clipsFor(name)</c>: per kind of the index (its order), the first clip along the character's set chain
    /// <c>[...sets, '']</c>; kinds without one in the chain are skipped. Returns (kind, set, clip).
    /// </summary>
    public static List<(string Kind, string Set, C Clip)> ClipsFor<C>(ClipIndex<C> index, IReadOnlyList<string>? sets)
    {
        var chain = (sets ?? Array.Empty<string>()).Append("").ToList();
        var output = new List<(string, string, C)>();
        foreach (var kind in index.Kinds)
        {
            var bySet = index.BySet[kind];
            foreach (var set in chain)
                if (bySet.TryGetValue(set, out var clip)) { output.Add((kind, set, clip)); break; }
        }
        return output;
    }

    /// <summary><c>CLIP_SYNONYMS</c> (figures.ts): the alias layer a canonical kind no clip carries literally is bound through.</summary>
    public static readonly IReadOnlyList<(string Kind, string[] Needles)> ClipSynonyms = new[]
    {
        ("idle", new[] { "idle", "stand", "breath" }),
        ("walk", new[] { "walk" }),
        ("run", new[] { "run" }),
        ("sit", new[] { "sit" }),
        ("lie", new[] { "lie", "lay", "sleep" }),
        ("dance", new[] { "dance", "samba" }),
        ("wave", new[] { "wave", "greet" }),
    };

    /// <summary>
    /// The action table of a figure (<c>Figure</c> constructor): one action per clip name lower-cased (a later
    /// clip of the same lower-cased name replaces the earlier one's clip but keeps its position, like a JS Map
    /// <c>set</c>), then every <see cref="ClipSynonyms"/> kind not bound literally, through
    /// <see cref="FigureClips.ResolveClipName"/>. Returns (action kind, clip name it plays) in action order.
    /// </summary>
    public static List<(string Kind, string Clip)> BindActions(IReadOnlyList<string> clipNames)
    {
        var order = new List<string>();
        var byName = new Dictionary<string, string>(StringComparer.Ordinal);
        foreach (var name in clipNames)
        {
            var key = name.ToLowerInvariant();
            if (key.Length == 0) continue;
            if (!byName.ContainsKey(key)) order.Add(key);
            byName[key] = name;
        }
        var actions = order.Select(k => (k, byName[k])).ToList();
        var have = new HashSet<string>(order, StringComparer.Ordinal);
        foreach (var (kind, needles) in ClipSynonyms)
        {
            if (have.Contains(kind)) continue;
            var hit = FigureClips.ResolveClipName(order, needles);
            if (hit.Length > 0 && byName.TryGetValue(hit, out var clip)) { actions.Add((kind, clip)); have.Add(kind); }
        }
        return actions;
    }

    /// <summary>
    /// The stand-in pace of <c>Figure.play</c>: no clip of the idle family for a wanted idle → 0.1 (reads as
    /// breathing); no clip of the run family for a wanted run → 1.5 (the walk take, sped up); else 1.
    /// Judged by family of the wanted kind and of the kind actually chosen (<c>""</c> = none).
    /// </summary>
    public static double StandInPace(string wantKind, string chosenKind)
    {
        bool gotFamily = chosenKind.Length > 0 && FigureClips.AnimFamily(chosenKind) == FigureClips.AnimFamily(wantKind);
        var family = FigureClips.AnimFamily(wantKind);
        return family == "idle" && !gotFamily ? 0.1 : family == "run" && !gotFamily ? 1.5 : 1;
    }

    /// <summary>Crossfade of a clip switch (<c>fadeIn(0.25)</c>/<c>fadeOut(0.25)</c> in <c>Figure.play</c>).</summary>
    public const double CrossfadeS = 0.25;
}

/// <summary>A figure's resolution tier: the full mesh or the distance edition (<c>low_url</c>).</summary>
public enum FigureTier { Full, Low }

/// <summary>
/// The distance tiers of figures (view state, client3d main.ts <c>FIGURE_TIER_NEAR/FAR</c> + npcs.ts
/// <c>tickFigureTiers</c>): evaluated every <see cref="TickS"/>; nearer than <see cref="NearM"/> → full, farther
/// than <see cref="FarM"/> → low, in between the last wish stays (hysteresis); the player-driven figure is
/// always full.
/// </summary>
public static class FigureTiers
{
    public const double NearM = 25, FarM = 35, TickS = 1.0;

    public static FigureTier Next(FigureTier current, double distanceM, bool playerDriven = false)
        => playerDriven ? FigureTier.Full
           : distanceM < NearM ? FigureTier.Full
           : distanceM > FarM ? FigureTier.Low : current;
}
