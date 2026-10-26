using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Text.Json;
using AnimaNative.Water;

namespace AnimaNative.Figures;

/// <summary>Played (<see cref="Kind"/>) and shipped/public (<see cref="PublicKind"/>) clip kind of one fixed pose.</summary>
public sealed record PoseClip(string Kind, string PublicKind);

/// <summary>
/// The server's <c>movement_poses</c> as a full table (<c>walk.ts</c> <c>PoseClips</c>): every one of the seven fixed
/// poses has an entry. Built only by <see cref="FigureClips.ResolveMovementPoses"/>; <see cref="Default"/> is the
/// table of an empty payload.
/// </summary>
public sealed class PoseClips
{
    private readonly Dictionary<string, PoseClip> _byPose;

    internal PoseClips(Dictionary<string, PoseClip> byPose) => _byPose = byPose;

    /// <summary>
    /// A table that is already resolved (the browser's <c>PoseClips</c> shape, e.g. a vector fixture): taken as is,
    /// no cleaning. Every fixed pose must be present — the browser's <c>poses[pose].kind</c> throws otherwise.
    /// </summary>
    public static PoseClips Of(IReadOnlyDictionary<string, PoseClip> table)
    {
        var byPose = new Dictionary<string, PoseClip>(StringComparer.Ordinal);
        foreach (var pose in FigureClips.MovementPoses)
            byPose[pose] = table.TryGetValue(pose, out var e) ? e
                : throw new ArgumentException($"pose table lacks '{pose}'");
        return new PoseClips(byPose);
    }

    /// <summary><c>resolveMovementPoses(null)</c>: every pose plays its default clip.</summary>
    public static PoseClips Default { get; } = FigureClips.ResolveMovementPoses(null);

    /// <summary>The entry of a fixed pose (one of <see cref="FigureClips.MovementPoses"/>).</summary>
    public PoseClip this[string pose] => _byPose[pose];

    /// <summary>Pose → entry, in <see cref="FigureClips.MovementPoses"/> order.</summary>
    public IEnumerable<KeyValuePair<string, PoseClip>> Entries
        => FigureClips.MovementPoses.Select(p => new KeyValuePair<string, PoseClip>(p, _byPose[p]));
}

/// <summary>
/// One rule of the server's <c>transition_clips</c> (<c>walk.ts</c> <c>ClipTransition</c>): the clip <see cref="Kind"/>
/// that plays between clip <see cref="From"/> and clip <see cref="To"/> (<c>*</c> = any), and the fraction of normal
/// speed per second the figure gains while it plays (<see cref="Accel"/>, 0 = holds the figure).
/// </summary>
public sealed record ClipTransition(string From, string To, string Kind, double Accel);

/// <summary>
/// The figure clip decisions of the browser as pure functions of explicit server tables — a port of
/// <c>client3d/src/game/walk.ts</c> (poses, movement, transitions, bridge pace) and
/// <c>client3d/src/scene/clipCoverage.ts</c> (kind chain, kind resolution, procedural gait). Checked against
/// <c>shared/test-vectors/figure_clips.json</c> (hand derivations: <c>client3d/scripts/smoke_figure_clips.mjs</c>).
///
/// The browser keeps the server tables as module state and defaults every argument to it; the native client has
/// no module state — the clip library owns the tables and hands them in.
///
/// Movement types are the browser's strings (<c>walk_run</c>, <c>walk</c>, <c>swim</c>, <c>crawl</c>), like
/// <see cref="GroundWater.Movement"/>.
/// </summary>
public static class FigureClips
{
    public const string Standing = "standing", Walking = "walking", Running = "running", Swimming = "swimming",
        TreadingWater = "treading_water", Crawling = "crawling", CrawlingRest = "crawling_rest";

    /// <summary><c>MOVEMENT_POSES</c>: the seven fixed poses, in the browser's (and server's) order.</summary>
    public static readonly IReadOnlyList<string> MovementPoses =
        new[] { Standing, Walking, Running, Swimming, TreadingWater, Crawling, CrawlingRest };

    /// <summary><c>MOVEMENT_DEFAULTS</c>: the clip of a pose the server names none for.</summary>
    private static readonly IReadOnlyDictionary<string, string> MovementDefaults = new Dictionary<string, string>
    {
        [Standing] = "idle", [Walking] = "walk", [Running] = "run", [Swimming] = "breast-stroke",
        [TreadingWater] = "treading-water", [Crawling] = "crawl", [CrawlingRest] = "crawl-rest",
    };

    public const string WalkRun = "walk_run", Walk = "walk", Swim = "swim", Crawl = "crawl";

    /// <summary>Transition wildcard (<c>TRANSITION_ANY</c>).</summary>
    public const string Any = "*";

    /// <summary><c>BRIDGE_MIN_PACE</c>: the smallest pace a ramping bridge hands out (never 0, which means "holds").</summary>
    public const double BridgeMinPace = 0.02;

    /// <summary>Highest <see cref="ClipTransition.Accel"/> a rule keeps.</summary>
    public const double MaxAccel = 8;

    /// <summary>
    /// <c>CLIP_FALLBACK</c>: the stand-in kind when the wanted one is nowhere (before idle), looked up by kind first
    /// and by family second (<see cref="ClipKindChain"/>).
    /// </summary>
    public static readonly IReadOnlyDictionary<string, string> ClipFallback = new Dictionary<string, string>
    {
        ["lie"] = "sit", ["run"] = "walk", ["swim"] = "walk", ["crawl"] = "walk",
        ["crawl-rest"] = "idle", ["swim-idle"] = "swim", ["treading-water"] = "idle",
    };

    // ---- poses (walk.ts) ------------------------------------------------------------------------

    /// <summary>
    /// <c>resolveMovementPoses(raw)</c>: the server's <c>movement_poses</c> as a full table. A missing, blank or
    /// non-string <c>kind</c> / <c>public_kind</c> falls back to the pose's default clip, a given one is trimmed and
    /// lower-cased; a payload that is no object is the default table.
    /// </summary>
    public static PoseClips ResolveMovementPoses(JsonElement? raw)
    {
        var table = new Dictionary<string, PoseClip>(StringComparer.Ordinal);
        foreach (var pose in MovementPoses)
        {
            JsonElement entry = default;
            bool has = raw is { ValueKind: JsonValueKind.Object } src && src.TryGetProperty(pose, out entry)
                       && entry.ValueKind == JsonValueKind.Object;
            var fallback = MovementDefaults[pose];
            table[pose] = new PoseClip(Clean(has, entry, "kind", fallback), Clean(has, entry, "public_kind", fallback));
        }
        return new PoseClips(table);

        static string Clean(bool has, JsonElement entry, string key, string fallback)
        {
            if (!has || !entry.TryGetProperty(key, out var v) || v.ValueKind != JsonValueKind.String) return fallback;
            var s = v.GetString()!.Trim();
            return s.Length > 0 ? s.ToLowerInvariant() : fallback;
        }
    }

    /// <summary><c>poseClip(pose, poses)</c>: the clip a fixed pose plays.</summary>
    public static string PoseKind(string pose, PoseClips poses) => poses[pose].Kind;

    /// <summary><c>publicClip(pose, poses)</c>: the shipped clip of a fixed pose.</summary>
    public static string PublicKind(string pose, PoseClips poses) => poses[pose].PublicKind;

    /// <summary>
    /// <c>movementPoseOf(kind, poses)</c>: the fixed pose a clip kind plays — by played kind first, then by public
    /// kind; <c>""</c> for a kind no pose names.
    /// </summary>
    public static string MovementPoseOf(string? kind, PoseClips poses)
    {
        var want = (kind ?? "").Trim().ToLowerInvariant();
        return MovementPoses.FirstOrDefault(p => PoseKind(p, poses) == want)
               ?? MovementPoses.FirstOrDefault(p => PublicKind(p, poses) == want) ?? "";
    }

    /// <summary><c>movementOf(raw, scope)</c>: the ground's movement word, outside a built place; else <c>walk_run</c>.</summary>
    public static string MovementOf(string? raw, GroundScope scope)
        => scope != GroundScope.Built && raw is WalkRun or Walk or Swim or Crawl ? raw : WalkRun;

    /// <summary><c>canRun(movement)</c>: only <c>walk_run</c> ground lets a figure run.</summary>
    public static bool CanRun(string movement) => movement == WalkRun;

    /// <summary><c>moveClip(movement, running, poses)</c>: the clip a MOVING figure plays on that ground.</summary>
    public static string MoveClip(string movement, bool running, PoseClips poses)
        => PoseKind(movement == Swim ? Swimming : movement == Crawl ? Crawling
                    : CanRun(movement) && running ? Running : Walking, poses);

    /// <summary><c>idleClip(movement, poses)</c>: only swimming and crawling override a standing pose; else <c>""</c>.</summary>
    public static string IdleClip(string movement, PoseClips poses)
        => movement == Swim ? PoseKind(TreadingWater, poses)
           : movement == Crawl ? PoseKind(CrawlingRest, poses) : "";

    /// <summary>
    /// <c>standingClipFor(animation, groundIdle, poses)</c>: what a STANDING figure plays — the ground's word first,
    /// then the server's activity clip, else the <c>standing</c> pose. <c>null</c>/<c>""</c> name nothing.
    /// </summary>
    public static string StandingClipFor(string? animation, string? groundIdle, PoseClips poses)
        => !string.IsNullOrEmpty(groundIdle) ? groundIdle
           : !string.IsNullOrEmpty(animation) ? animation : PoseKind(Standing, poses);

    // ---- transitions (walk.ts) ------------------------------------------------------------------

    /// <summary>
    /// <c>resolveClipTransitions(raw)</c>: the server's <c>transition_clips</c> as rules. A non-list is no table; a
    /// row that is no object or lacks <c>from</c>, <c>to</c> or <c>kind</c> is dropped; names are trimmed and
    /// lower-cased; <c>accel</c> is 0 unless a positive number, capped at <see cref="MaxAccel"/>.
    /// </summary>
    public static List<ClipTransition> ResolveClipTransitions(JsonElement? raw)
    {
        var rules = new List<ClipTransition>();
        if (raw is not { ValueKind: JsonValueKind.Array } list) return rules;
        foreach (var r in list.EnumerateArray())
        {
            if (r.ValueKind != JsonValueKind.Object) continue;
            var from = Name(r, "from");
            var to = Name(r, "to");
            var kind = Name(r, "kind");
            double accel = r.TryGetProperty("accel", out var a) ? JsNumber(a) : double.NaN;
            accel = double.IsFinite(accel) && accel > 0 ? Math.Min(accel, MaxAccel) : 0;
            if (from.Length > 0 && to.Length > 0 && kind.Length > 0) rules.Add(new ClipTransition(from, to, kind, accel));
        }
        return rules;

        static string Name(JsonElement row, string key)
            => row.TryGetProperty(key, out var v) ? JsString(v).Trim().ToLowerInvariant() : "";
    }

    /// <summary>
    /// <c>clipTransition(from, to, table)</c>: the rule between two clips, <c>null</c> when none applies. Fixed
    /// precedence, not the table's order: both named, then the exit rule <c>(from, *)</c>, then the enter rule
    /// <c>(*, to)</c>. Switching onto the same clip (or from none) is never a transition.
    /// </summary>
    public static ClipTransition? Transition(string? from, string? to, IReadOnlyList<ClipTransition> table)
    {
        var src = (from ?? "").Trim().ToLowerInvariant();
        var dst = (to ?? "").Trim().ToLowerInvariant();
        if (src.Length == 0 || dst.Length == 0 || src == dst) return null;
        ClipTransition? wildTo = null, wildFrom = null;
        foreach (var r in table)
        {
            if (r.From == src && r.To == dst) return r;
            if (r.From == src && r.To == Any) wildTo ??= r;
            else if (r.From == Any && r.To == dst) wildFrom ??= r;
        }
        return wildTo ?? wildFrom;
    }

    /// <summary>
    /// <c>bridgePace(accel, elapsedS)</c>: how much of its normal speed a figure has while a bridge plays — 0 for a
    /// holding rule, else <c>min(1, max(BridgeMinPace, accel·elapsed))</c> with a negative elapsed taken as 0.
    /// </summary>
    public static double BridgePace(double accel, double elapsedS)
    {
        if (!double.IsFinite(accel) || accel <= 0) return 0;
        var e = double.IsFinite(elapsedS) && elapsedS > 0 ? elapsedS : 0;
        return Math.Min(1, Math.Max(BridgeMinPace, accel * e));
    }

    // ---- kinds (clipCoverage.ts) ----------------------------------------------------------------

    /// <summary><c>animFamily(kind)</c>: everything before the first <c>-</c>, trimmed and lower-cased; <c>""</c> is idle.</summary>
    public static string AnimFamily(string? kind)
    {
        var clean = (kind ?? "").Trim().ToLowerInvariant();
        if (clean.Length == 0) return "idle";
        int dash = clean.IndexOf('-');
        return dash > 0 ? clean[..dash] : clean;
    }

    /// <summary>
    /// <c>matchAnimKind(available, kind)</c>: the exact kind if available, else a family relative (the family base
    /// first, then list order), else <c>""</c>. The entry is returned as passed in.
    /// </summary>
    public static string MatchAnimKind(IReadOnlyList<string> available, string? kind)
    {
        var want = (kind ?? "").Trim().ToLowerInvariant();
        if (want.Length == 0) return "";
        var family = AnimFamily(want);
        var relative = "";
        foreach (var raw in available)
        {
            var name = (raw ?? "").Trim().ToLowerInvariant();
            if (name.Length == 0) continue;
            if (name == want) return raw!;
            if (AnimFamily(name) != family) continue;
            // the family base beats any other relative; otherwise the first listed one
            if (relative.Length == 0 || name == family) relative = raw!;
        }
        return relative;
    }

    /// <summary>
    /// <c>clipKindChain(kind, poses)</c>: the kinds tried in order — the wanted one, its pose's public kind, the
    /// stand-ins of both and of the family, the standing pose's played and public kind, <c>idle</c>; blanks and
    /// repeats dropped. An empty kind is <c>idle</c>.
    /// </summary>
    public static List<string> ClipKindChain(string? kind, PoseClips poses)
    {
        var want = (kind ?? "").Trim().ToLowerInvariant();
        if (want.Length == 0) want = "idle";
        var family = AnimFamily(want);
        var pose = MovementPoseOf(want, poses);
        var pub = pose.Length > 0 ? PublicKind(pose, poses) : "";
        string? Fallback(string key) => ClipFallback.TryGetValue(key, out var f) ? f : null;
        var chain = new List<string>();
        foreach (var step in new[] { want, pub, Fallback(want), Fallback(pub), Fallback(family),
                                     PoseKind(Standing, poses), PublicKind(Standing, poses), "idle" })
            if (!string.IsNullOrEmpty(step) && !chain.Contains(step)) chain.Add(step);
        return chain;
    }

    /// <summary>
    /// <c>resolveClipKind(kind, bound, poses)</c>: the first link of <see cref="ClipKindChain"/> that
    /// <see cref="MatchAnimKind"/> finds among the bound kinds (entry as passed in), <c>""</c> when none.
    /// </summary>
    public static string ResolveClipKind(string? kind, IReadOnlyList<string> bound, PoseClips poses)
    {
        foreach (var step in ClipKindChain(kind, poses))
        {
            var hit = MatchAnimKind(bound, step);
            if (hit.Length > 0) return hit;
        }
        return "";
    }

    /// <summary>
    /// <c>proceduralGait(kind, poses)</c>: the leg swing of a clip-less rig — the walking/running pose first, then
    /// the kind's family (<c>walk</c>/<c>run</c>), else <c>null</c>.
    /// </summary>
    public static string? ProceduralGait(string? kind, PoseClips poses)
    {
        var pose = MovementPoseOf(kind, poses);
        if (pose == Walking) return "walk";
        if (pose == Running) return "run";
        var family = AnimFamily(kind);
        return family == "run" ? "run" : family == "walk" ? "walk" : null;
    }

    /// <summary>
    /// <c>missingClipKinds(offered, bound)</c>: the offered kinds a rig cannot play — trimmed, lower-cased, blanks
    /// dropped, de-duplicated, sorted (JS default sort = UTF-16 code unit order = <see cref="StringComparer.Ordinal"/>).
    /// </summary>
    public static List<string> MissingClipKinds(IEnumerable<string> offered, IEnumerable<string> bound)
    {
        var have = new HashSet<string>(bound.Select(k => k.Trim().ToLowerInvariant()).Where(k => k.Length > 0), StringComparer.Ordinal);
        var missing = new SortedSet<string>(StringComparer.Ordinal);
        foreach (var raw in offered)
        {
            var kind = raw.Trim().ToLowerInvariant();
            if (kind.Length > 0 && !have.Contains(kind)) missing.Add(kind);
        }
        return missing.ToList();
    }

    /// <summary>
    /// <c>resolveClipName(names, needles)</c>: per needle in order, the clip that IS it before one that contains it
    /// (names trimmed + lower-cased, the cleaned name returned); <c>""</c> when nothing stands in.
    /// </summary>
    public static string ResolveClipName(IReadOnlyList<string> names, IReadOnlyList<string> needles)
    {
        var clean = names.Select(n => n.Trim().ToLowerInvariant()).ToList();
        foreach (var needle in needles)
        {
            var hit = clean.FirstOrDefault(n => n == needle) ?? clean.FirstOrDefault(n => n.Contains(needle, StringComparison.Ordinal));
            if (!string.IsNullOrEmpty(hit)) return hit;
        }
        return "";
    }

    /// <summary><c>animatablePool(pool)</c>: the entries the library fits, or all of them when none does.</summary>
    public static List<T> AnimatablePool<T>(IReadOnlyList<T> pool, Func<T, bool> libraryFits)
    {
        var fitting = pool.Where(libraryFits).ToList();
        return fitting.Count > 0 ? fitting : pool.ToList();
    }

    // ---- JS coercions -----------------------------------------------------------------------------

    /// <summary>JS <c>String(v ?? '')</c> for a JSON value.</summary>
    private static string JsString(JsonElement v) => v.ValueKind switch
    {
        JsonValueKind.String => v.GetString()!,
        JsonValueKind.Number => JsNumberText(v.GetDouble()),
        JsonValueKind.True => "true",
        JsonValueKind.False => "false",
        JsonValueKind.Object => "[object Object]",
        JsonValueKind.Array => string.Join(",", v.EnumerateArray().Select(e =>
            e.ValueKind is JsonValueKind.Null or JsonValueKind.Undefined ? "" : JsString(e))),
        _ => "",
    };

    private static string JsNumberText(double d)
        => d == Math.Floor(d) && Math.Abs(d) < 1e21 ? d.ToString("0", CultureInfo.InvariantCulture)
           : d.ToString("R", CultureInfo.InvariantCulture);

    /// <summary>JS <c>Number(v)</c> for the cases that can come out positive: numbers, numeric strings, <c>true</c>.</summary>
    private static double JsNumber(JsonElement v)
    {
        switch (v.ValueKind)
        {
            case JsonValueKind.Number: return v.GetDouble();
            case JsonValueKind.True: return 1;
            case JsonValueKind.False:
            case JsonValueKind.Null: return 0;
            case JsonValueKind.String:
                var s = v.GetString()!.Trim();
                if (s.Length == 0) return 0;
                return double.TryParse(s, NumberStyles.AllowLeadingSign | NumberStyles.AllowDecimalPoint
                                          | NumberStyles.AllowExponent, CultureInfo.InvariantCulture, out var d)
                    ? d : double.NaN;
            default: return double.NaN;
        }
    }
}
