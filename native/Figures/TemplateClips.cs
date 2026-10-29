using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Linq;
using System.Threading.Tasks;
using AnimaNative.Overview;
using Godot;

namespace AnimaNative.Figures;

/// <summary>How a template's library clips are fitted (Task 35b, ruling P3-R15).</summary>
public enum ClipFitMode
{
    /// <summary>
    /// The live client: at build only the movement poses (plus what the figure that asked for the template needs); every
    /// other clip when a figure on the template first needs it (play / crossfade / bridge / pair). The key math, the
    /// bridge relock and the clip's ground measurement run on worker threads; the engine work (writing the Animation,
    /// sampling it, adding it to the library) runs on the main thread in turns of at most
    /// <see cref="FigureManager.ClipBudgetMs"/> per frame. Until the clip is in, the figure keeps what it plays.
    /// </summary>
    Lazy,
    /// <summary>
    /// The checks: the same plan and the same build, but a clip a figure needs is fitted AT ONCE on the main thread inside
    /// the call that asks for it — the frame it starts in, and so every number a check measures, is the eager fit's.
    /// </summary>
    OnDemandSync,
    /// <summary>Every library clip at build, on the main thread — the reference the lazy fit is compared with.</summary>
    Eager,
}

/// <summary>One clip fit as it happened (the offline log and the report): wall time, main-thread time and its longest turn, worker time.</summary>
public sealed record ClipFitTime(string Url, string Kind, bool OnDemand, double WallMs, double MainMs, double MainMaxMs, double WorkerMs);

/// <summary>
/// The library clips of ONE model template, fitted lazily (Task 35b, ruling P3-R15). The template's PLAN is made at
/// build without writing a single key (<see cref="PlanAsync"/>, on a worker): per candidate clip of the set chain,
/// whether it binds on this rig (<see cref="ClipLibrary.Compute"/> with <c>countOnly</c> — the very loop of the fit, so
/// track and key counts are the eager fit's), and from that the action table (one action per clip name lower-cased + the synonym aliases, own takes
/// first). What the figures read about the library — its kinds, the bound tracks and keys, the missing kinds — is the
/// plan's and therefore unchanged; what is HELD is only what has been fitted.
///
/// A clip is fitted exactly as the eager fit did it, one clip at a time (the relock and the ground measurement were
/// already per clip): retarget, share an identical clip of an earlier template (<see cref="FigureManager"/>'s digest
/// table), re-lock / pin / lift / turn a root-motion clip and write the rewritten tracks back, measure its ground offset
/// on this rig's skinning, then add the Animation to the template's library under each of its action names — the
/// figures of the template see it from their next play on. The lazy path computes on worker threads what the eager path
/// computes inline, with the same code on the same inputs: the keys, the extras and the offsets are the same bit for bit
/// (<c>--check clips</c>). The ground measurement's rest-pose minimum (<see cref="ClipGround.BindMinY"/>) is measured once
/// per rig on a fresh rest pose instead of once per call, and later clips are measured on just the vertices the
/// measurement samples (<see cref="ClipGround.SampledSkins"/>) — the same numbers.
/// </summary>
public sealed class TemplateClips
{
    private readonly FigureManager _mgr;
    private readonly Action<string> _log;
    private readonly RetargetRig _rig;
    private readonly IReadOnlyDictionary<string, RestFix>? _fixes;
    private readonly double _standRef;
    private readonly bool _rigKnown;
    /// <summary>The bridges' relock scale (<c>normalized ? 1 : height / raw</c>); not &gt; 0 = neither relock nor ground offsets (the eager fit's rule).</summary>
    private readonly double _scale;
    private readonly string _skelPath;
    private readonly ProbeRig _probe;
    /// <summary>
    /// The rig's skinned surfaces: whole until the plan, then — in the lazy mode — only the vertices the ground measurement
    /// samples (<see cref="ClipGround.SampledSkins"/>, ~1 000) and the rest pose's lowest point over all of them: a
    /// template does not hold a copy of its mesh for the clips it may fit later. The synchronous modes keep the whole
    /// surfaces and measure exactly as the eager fit did (the reference <c>--check clips</c> compares with).
    /// </summary>
    private List<ProbeSkin>? _skins;
    private List<ProbeSkin> _sampled = new();
    private double _bindMinY;
    private readonly bool _hasSkins;
    private bool _dead;

    public string Url { get; }
    public AnimationLibrary Library { get; }
    /// <summary>Per fitted Animation its bridge travel / turn / lift and ground offset (the figures read this dictionary).</summary>
    public Dictionary<Animation, ClipExtras> Extras { get; } = new();
    /// <summary>Every fitted library clip of this template and its key count (shared ones included).</summary>
    public Dictionary<Animation, long> AnimKeys { get; } = new();
    /// <summary>Keys of the fitted clips this template created itself (not taken over from an earlier template).</summary>
    public long OwnKeys { get; private set; }
    /// <summary>Fitted clips taken over from an earlier template because their content is identical.</summary>
    public int SharedClips { get; private set; }

    /// <summary>The plan: action → the source clip that plays it, the actions in order, and per source clip its actions.</summary>
    private readonly Dictionary<string, ClipSource> _clipOf = new(StringComparer.Ordinal);
    private readonly Dictionary<ClipSource, List<string>> _actionsOf = new(ReferenceEqualityComparer.Instance);
    public IReadOnlyList<string> Actions { get; private set; } = Array.Empty<string>();
    /// <summary>Planned: candidate clips that bind on this rig, their tracks and keys (the eager fit's bound totals), set per kind.</summary>
    public int PlannedClips { get; private set; }
    public int PlannedTracks { get; private set; }
    public long PlannedKeys { get; private set; }
    public IReadOnlyDictionary<string, string> ClipSets { get; private set; } = new Dictionary<string, string>();
    /// <summary>Planned library clips a figure can play (the ones behind an action) — what an eager fit would have measured.</summary>
    public int FittableClips => _actionsOf.Count;

    private readonly Dictionary<ClipSource, Task<Animation?>> _fits = new(ReferenceEqualityComparer.Instance);
    /// <summary>Clips fitted so far (on this template) and the ones whose fit failed.</summary>
    public int FittedClips { get; private set; }
    public int FailedClips { get; private set; }
    /// <summary>A fit is still running (the manager never retires a template while one is).</summary>
    public bool Busy => _fits.Values.Any(t => !t.IsCompleted);
    /// <summary>The build's own fit ended: what is fitted from now on is "on demand" in the log.</summary>
    public bool Built { get; set; }

    /// <summary>The template's rig read from the engine (main thread); <see cref="PlanAsync"/> makes the plan.</summary>
    /// <param name="library">the template's library, holding the own takes already.</param>
    public TemplateClips(FigureManager mgr, Action<string> log, string url, Node3D root, Skeleton3D skel,
                         IReadOnlyDictionary<string, RestFix>? fixes, double standRef, bool rigKnown, double scale,
                         AnimationLibrary library)
    {
        _mgr = mgr;
        _log = log;
        Url = url;
        _fixes = fixes;
        _standRef = standRef;
        _rigKnown = rigKnown;
        _scale = scale;
        Library = library;
        _rig = RetargetRig.Of(root, skel);
        _skelPath = root.GetPathTo(skel).ToString();
        _probe = BridgeFit.RigOf(root, skel);
        _skins = BridgeFit.SkinsOf(root, skel);
        _hasSkins = _skins.Count > 0;
    }

    /// <param name="candidates">the set chain's clips (<see cref="ClipLibrary.ClipsFor"/>), in order.</param>
    /// <param name="ownKinds">the file's own takes (lower-cased): they win their kind, the library fills the rest.</param>
    public async Task PlanAsync(IReadOnlyList<ClipSource> candidates, IReadOnlyCollection<string> ownKinds)
    {
        // Which candidates bind (the fit's own loop, counting only — on a worker), in candidate order.
        var (rig, fixes, standRef, rigKnown, probe, skins) = (_rig, _fixes, _standRef, _rigKnown, _probe, _skins!);
        var (counts, bindMinY, sampled) = await Task.Run(() =>
        {
            using var fitting = _mgr.Measurements?.Time("character GLB", "fitting");
            return (candidates.Select(c => ClipLibrary.Compute(c, rig, fixes, standRef, rigKnown, countOnly: true)).ToList(),
             ClipGround.BindMinY(probe, skins), ClipGround.SampledSkins(skins));
        });
        _bindMinY = bindMinY;
        _sampled = sampled;
        if (_mgr.ClipFit == ClipFitMode.Lazy) _skins = null;
        var bound = new List<ClipSource>();
        var sets = new Dictionary<string, string>();
        int tracks = 0;
        long keys = 0;
        for (int i = 0; i < candidates.Count; i++)
        {
            if (!counts[i].Binds) continue;
            bound.Add(candidates[i]);
            sets[candidates[i].Kind] = candidates[i].Set;
            tracks += counts[i].TrackCount;
            keys += counts[i].Keys;
        }
        PlannedClips = bound.Count;
        PlannedTracks = tracks;
        PlannedKeys = keys;
        ClipSets = sets;
        // One action per clip name lower-cased (the LAST bound clip of that name plays it) + the synonym aliases
        // (Figure constructor); an own take wins its kind; a name Godot's library refuses stays unbound.
        var byLower = new Dictionary<string, ClipSource>(StringComparer.Ordinal);
        foreach (var c in bound) byLower[c.Kind.ToLowerInvariant()] = c;
        var actions = new List<string>();
        var taken = new HashSet<string>(ownKinds, StringComparer.Ordinal);
        foreach (var (action, clipName) in ClipLibraryRules.BindActions(bound.Where(b => !ownKinds.Contains(b.Kind.ToLowerInvariant()))
                                                                             .Select(b => b.Kind).ToList()))
        {
            if (taken.Contains(action)) continue;
            if (!ValidActionName(action))
            {
                _log($"model {Url}: action '{action}' refused by Godot's animation-name rule");
                continue;
            }
            taken.Add(action);
            var src = byLower[clipName.ToLowerInvariant()];
            _clipOf[action] = src;
            if (!_actionsOf.TryGetValue(src, out var list)) _actionsOf[src] = list = new List<string>();
            list.Add(action);
            actions.Add(action);
        }
        Actions = actions;
    }

    /// <summary>Godot's <c>AnimationLibrary::is_valid_animation_name</c>: not empty, none of <c>/ : , [</c>.</summary>
    public static bool ValidActionName(string name)
        => name.Length > 0 && name.IndexOfAny(new[] { '/', ':', ',', '[' }) < 0;

    /// <summary>The source clip behind a library action (null for an own take or an unknown name).</summary>
    public ClipSource? ClipOf(string action) => _clipOf.TryGetValue(action, out var c) ? c : null;

    /// <summary>
    /// A figure asks for <paramref name="action"/> (<see cref="Figure.FitClip"/>): true when it is in the library now.
    /// Lazy: the fit is started (once) and false returned — the figure asks again next frame. Otherwise the clip is fitted
    /// here and now.
    /// </summary>
    public bool Request(string action)
    {
        if (Library.HasAnimation(action)) return true;
        if (_dead || !_clipOf.TryGetValue(action, out var src)) return false;
        var fit = Fit(src);
        return fit.IsCompletedSuccessfully && fit.Result is not null && Library.HasAnimation(action);
    }

    /// <summary>Fit the clips behind <paramref name="actions"/> (unknown names and own takes are skipped); completes when they are in.</summary>
    public Task EnsureAsync(IEnumerable<string> actions)
        => Task.WhenAll(actions.Where(a => !Library.HasAnimation(a) && _clipOf.ContainsKey(a)).Select(a => _clipOf[a])
                               .Distinct(ReferenceEqualityComparer.Instance).Cast<ClipSource>().Select(Fit).ToList());

    /// <summary>Every clip of the plan (the eager fit, and the checks that compare against it).</summary>
    public Task EnsureAllAsync() => EnsureAsync(Actions);

    /// <summary>The template is freed: running fits stop at their next main-thread turn, nothing is added any more.</summary>
    public void Kill() => _dead = true;

    private Task<Animation?> Fit(ClipSource src)
    {
        if (_fits.TryGetValue(src, out var running)) return running;
        // The manager's mode NOW (the offline walk probe drives its frames synchronously and switches to OnDemandSync).
        var task = _mgr.ClipFit == ClipFitMode.Lazy ? FitAsync(src) : Task.FromResult(FitInline(src));
        _fits[src] = task;
        return task;
    }

    // ---- the inline fit: the eager fit's arithmetic on the calling (main) thread ----------------------------------

    private Animation? FitInline(ClipSource src)
    {
        var sw = Stopwatch.StartNew();
        var keys = ClipLibrary.Compute(src, _rig, _fixes, _standRef, _rigKnown);
        var anim = Bind(keys);
        if (anim is null) return null;
        string extraLog = "";
        if (keys.RootPath is { } path && _scale > 0)
        {
            var clip = BridgeFit.RelockClipOf(src.Kind, anim, path);
            var lines = new List<string>();
            var reports = FootLockMeasure.Relock(new[] { clip }, _probe, 1 / (100 * _scale), line => lines.Add(line));
            extraLog += Relocked(src.Kind, anim, clip, reports, lines);
        }
        if (_hasSkins && _scale > 0)
        {
            var g = BridgeFit.GroundClipOf(src.Kind, anim);
            // The whole surfaces with bindMinY measured in the call, as the eager fit did; once they were let go (a lazy
            // template whose manager switched to fitting at once), the sampled ones — the same number.
            if (_skins is { } full) ClipGround.Measure(new[] { g }, _probe, full);
            else ClipGround.MeasureSampled(new[] { g }, _probe, _sampled, _bindMinY);
            extraLog += Grounded(src.Kind, anim, g.GroundOffset);
        }
        AddActions(src, anim);
        double ms = sw.Elapsed.TotalMilliseconds;
        Done(src, new ClipFitTime(Url, src.Kind, Built, ms, ms, ms, 0), extraLog);
        return anim;
    }

    // ---- the lazy fit: key math and measurements on workers, engine work in main-thread turns ---------------------

    private async Task<Animation?> FitAsync(ClipSource src)
    {
        var wall = Stopwatch.StartNew();
        double main = 0, mainMax = 0, worker = 0;
        void Charge(Stopwatch s, string what)
        {
            double ms = s.Elapsed.TotalMilliseconds;
            main += ms;
            mainMax = Math.Max(mainMax, ms);
            _mgr.ChargeMain(ms, what);
        }
        try
        {
            var rig = _rig;
            var (keys, wk) = await Worker(() => ClipLibrary.Compute(src, rig, _fixes, _standRef, _rigKnown));
            worker += wk;
            if (!await _mgr.MainTurn() || _dead) return null;
            var step = Stopwatch.StartNew();
            var anim = Bind(keys);
            Charge(step, "write");
            if (anim is null) return null;
            string extraLog = "";
            if (keys.RootPath is { } path && _scale > 0)
            {
                if (!await _mgr.MainTurn() || _dead) return null;
                step.Restart();
                var clip = BridgeFit.RelockClipOf(src.Kind, anim, path);
                Charge(step, "relock sampling");
                var lines = new List<string>();
                var probe = _probe;
                double unitsPerCm = 1 / (100 * _scale);
                var (reports, rk) = await Worker(() => FootLockMeasure.Relock(new[] { clip }, probe, unitsPerCm, line => lines.Add(line)));
                worker += rk;
                if (!await _mgr.MainTurn() || _dead) return null;
                step.Restart();
                extraLog += Relocked(src.Kind, anim, clip, reports, lines);
                Charge(step, "relock write-back");
            }
            if (_hasSkins && _scale > 0)
            {
                if (!await _mgr.MainTurn() || _dead) return null;
                step.Restart();
                var g = BridgeFit.GroundClipOf(src.Kind, anim);
                Charge(step, "ground sampling");
                var (probe, sampled, bindMinY) = (_probe, _sampled, _bindMinY);
                var (_, gk) = await Worker(() =>
                {
                    ClipGround.MeasureSampled(new[] { g }, probe, sampled, bindMinY);
                    return 0;
                });
                worker += gk;
                extraLog += Grounded(src.Kind, anim, g.GroundOffset);
            }
            if (!await _mgr.MainTurn() || _dead) return null;
            step.Restart();
            AddActions(src, anim);
            Charge(step, "add to library");
            Done(src, new ClipFitTime(Url, src.Kind, Built, wall.Elapsed.TotalMilliseconds, main, mainMax, worker), extraLog);
            return anim;
        }
        catch (Exception e) when (!_mgr.Strict)
        {
            FailedClips++;
            _log($"model {Url}: clip {src.Kind} could not be fitted: {e.Message}");
            return null;
        }
    }

    /// <summary>Run <paramref name="work"/> on a worker thread; the result and its own time (ms).</summary>
    private static async Task<(T, double)> Worker<T>(Func<T> work)
        => await Task.Run(() =>
        {
            var sw = Stopwatch.StartNew();
            var r = work();
            return (r, sw.Elapsed.TotalMilliseconds);
        });

    // ---- the steps both paths share (main thread) -------------------------------------------------------------------

    /// <summary>Write the Animation and share an identical one of an earlier template (<see cref="FigureManager.ShareIdentical"/>).</summary>
    private Animation? Bind(RetargetKeys keys)
    {
        var b = ClipLibrary.Write(keys, _rig);
        if (b.Anim is null) return null;
        bool shared = false;
        b = _mgr.ShareIdentical(b, ref shared);
        if (shared) SharedClips++;
        else OwnKeys += b.Keys;
        AnimKeys[b.Anim!] = b.Keys;
        return b.Anim;
    }

    /// <summary>The relock's result baked into the Animation and its extras; the log fragment (the browser's line).</summary>
    private string Relocked(string kind, Animation anim, ProbeClip clip, List<RelockReport> reports, List<string> lines)
    {
        BridgeFit.WriteBack(clip, anim, _skelPath);
        Extras[anim] = new ClipExtras
        {
            Path = clip.Path, Turn = clip.Turn, Lift = clip.Lift,
            PivotFrame = clip.Turn is { } turn ? RigMath.Apply(_probe.Root, turn.Pivot) : null,
        };
        bool missingFeet = reports.Any(r => r.Reason == "no foot bones");
        var parts = lines.Select(l => l.StartsWith("foot lock per rig — ", StringComparison.Ordinal) ? l["foot lock per rig — ".Length..] : l);
        return lines.Count > 0 ? $"; {(missingFeet ? "WARN " : "")}foot lock per rig — {string.Join(", ", parts)}" : "";
    }

    private string Grounded(string kind, Animation anim, double offset)
    {
        if (!Extras.TryGetValue(anim, out var x)) Extras[anim] = x = new ClipExtras();
        x.GroundOffset = offset;
        return offset * _scale > 0.05 ? $"; authored off the floor +{offset * _scale:0.00} m (dropped while walking that ground)" : "";
    }

    /// <summary>The clip under each of its action names: the figures of this template can play it from now on.</summary>
    private void AddActions(ClipSource src, Animation anim)
    {
        foreach (var action in _actionsOf.TryGetValue(src, out var list) ? list : new List<string>())
            if (!Library.HasAnimation(action)) Library.AddAnimation(action, anim);
    }

    private void Done(ClipSource src, ClipFitTime time, string extraLog)
    {
        FittedClips++;
        _mgr.RecordFit(time);
        if (time.OnDemand || extraLog.Length > 0)
            _log($"model {Url}: clip {src.Kind} fitted{(time.OnDemand ? " on first use" : "")} in {time.WallMs:0.0} ms "
                 + $"(main {time.MainMs:0.0} ms, longest turn {time.MainMaxMs:0.0} ms; worker {time.WorkerMs:0.0} ms){extraLog}");
    }
}
