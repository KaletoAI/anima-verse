using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
using System.Threading.Tasks;
using AnimaNative.Api;
using AnimaNative.Gltf;
using AnimaNative.Overview;
using AnimaNative.World;
using Godot;
using Json = AnimaNative.World.Json;

namespace AnimaNative.Figures;

/// <summary>Counts for the log line and the check.</summary>
public sealed class FigureStats
{
    public int Figures, GlbFigures, Placeholders, ClipsLoaded, ClipsFailed, BoundTracks, UnboundClips;
    public int ModelLoads, ModelFailures, Offmap, Polls, KindsBound, LowTier;

    public string Summary() =>
        $"figures={Figures} glb_figures={GlbFigures} placeholders={Placeholders} clips_loaded={ClipsLoaded} "
        + $"kinds_bound={KindsBound} bound_tracks={BoundTracks} unbound_clips={UnboundClips} model_loads={ModelLoads} "
        + $"model_failures={ModelFailures} offmap={Offmap} clip_failures={ClipsFailed} low_tier={LowTier}";
}

/// <summary>
/// The figures of <c>GET /play/worldmap</c> on the open map — client3d's <c>FigureLibrary</c> + the model side of
/// <c>NpcManager</c>:
///
///   • which and where: <see cref="FigurePlacement.Resolve"/> (the browser's far view; rooms are Task 29);
///     y = <see cref="WorldHeight.GroundAt"/> at the shown point, every frame;
///   • fed by the client's world-map poll (<see cref="ApplyPolled"/>); a moved target lerps in over the poll
///     interval (<see cref="PollSeconds"/>; NPC walking is Task 30); <c>activity_animation</c> is what a standing
///     figure plays, <c>animation_sets</c> its set chain;
///   • model: <c>GET /characters/{name}/model3d</c> → <c>model.url</c> / <c>model.low_url</c> used unchanged (§ A7),
///     every load (model3d + GLB + fit) one job of a <see cref="FocusQueue"/> of width 3 — the avatar first, then
///     the figure nearest the camera target; a GLB is Meshopt-decoded and imported once per (URL, set chain) and
///     duplicated per figure; FBX (generic rig) and "no model" (404 or <c>model</c> null) are capsule placeholders
///     (Task 34 / Task 29); a transient failure retries after <see cref="RetryDelayS"/>; reloaded when the row's
///     <c>model_sig</c> or <c>model_rev</c> changes (§ A11a, <c>refreshIfChanged</c>);
///   • looks: metalness forced to 0 on every material (characters are dielectrics, AV3D-14), roughness untouched;
///     scale <c>normalized</c> → 1, else height / raw bounding-box height (height = <c>height_cm</c>/100 when
///     30 &lt; cm &lt; 400, default 1.70 m; a Z-up export is stood up first);
///   • clips: the WHOLE library along the character's set chain (<see cref="ClipLibrary.ClipsFor"/>), retargeted
///     once per template, one action per kind + the synonym aliases; only a <c>mixamo</c> rig gets them;
///   • tiers: every <see cref="FigureTiers.TickS"/> the camera distance picks full (&lt; 25 m) / low (&gt; 35 m),
///     the band between keeps; a cached tier swaps at once, a missing one loads through the queue.
/// </summary>
public partial class FigureManager : Node3D
{
    public const double DefaultHeightM = 1.70;
    /// <summary>The browser's model queue width (<c>createFocusQueue({max: 3})</c>).</summary>
    public const int ModelQueueWidth = 3;
    /// <summary>A transient model failure retries after this many seconds (figures.ts: 30 000 ms).</summary>
    public double RetryDelayS { get; set; } = 30;
    /// <summary>The current poll interval (s): a moved figure lerps to its new spot over it.</summary>
    public double PollSeconds { get; set; } = 3.0;
    /// <summary>false in <c>--check</c>: time only moves through <see cref="Tick"/>, tiers only through <see cref="TickTiers"/>.</summary>
    public bool AutoTick { get; set; } = true;

    /// <summary>Where the camera is (tiers measure from it, npcs.ts <c>tickFigureTiers(camera.position)</c>); null = no tiers.</summary>
    public Func<Vector3?>? CameraPosition { get; set; }
    /// <summary>The orbit target (the model queue's distance, main.ts <c>setModelFocus</c>: distance² to <c>engine.target</c>).</summary>
    public Func<Vector3?>? FocusTarget { get; set; }

    private readonly IWorldSource _source;
    private readonly WorldHeight _height;
    private readonly Action<string> _log;
    private readonly bool _strict;
    private readonly Dictionary<string, Figure> _figures = new();
    private readonly Dictionary<string, Task<ModelTemplate>> _templates = new();
    private readonly Dictionary<string, ModelInfo> _infos = new();
    private readonly FocusQueue _models = new(ModelQueueWidth);
    private double _tierClock;

    /// <summary>
    /// The mirror over a point for the underwater ghost (npcs.ts: <c>groundWaterLevel(typeAt(x, z).water_level, scope)</c>,
    /// <see cref="World.WorldBuilder.FigureWaterLevel"/>); null = no ghosts at all.
    /// </summary>
    public Func<double, double, double?>? WaterLevelAt { get; set; }

    public ClipLibrary Clips { get; }
    public FigureStats Stats { get; } = new();
    public IReadOnlyDictionary<string, Figure> Figures => _figures;
    /// <summary>The world map's <c>avatar</c> (the model queue serves it first).</summary>
    public string AvatarName { get; private set; } = "";
    /// <summary>The order the model jobs STARTED in (character names, a tier load included) — the queue's observable.</summary>
    public List<string> ModelLoadOrder { get; } = new();

    private sealed class ModelTemplate
    {
        public required Node3D Root { get; init; }
        public required double RawHeight { get; init; }
        public required string Url { get; init; }
        public AnimationLibrary? Library { get; init; }
        /// <summary>The action kinds in <see cref="Library"/>, in action order (the figure's fallback is the first).</summary>
        public IReadOnlyList<string> Kinds { get; init; } = Array.Empty<string>();
        /// <summary>Library kind → the set its file came from (the set chain's decision).</summary>
        public IReadOnlyDictionary<string, string> ClipSets { get; init; } = new Dictionary<string, string>();
        public int BoundTracks { get; init; }
        public int Unbound { get; init; }
        /// <summary>Bones with a rest correction; −1 = no rig (verbatim copy).</summary>
        public int Corrected { get; init; }
        public long Keys { get; init; }
        /// <summary>Godot static memory grown by the retarget of this template (bytes).</summary>
        public long ClipBytes { get; init; }
        public double FitMs { get; init; }
    }

    private sealed record ModelInfo(string Url, string? LowUrl, string Format, string Rig, bool Normalized, string? ModelRev);

    public FigureManager(IWorldSource source, WorldHeight height, Action<string> log, bool strict)
    {
        Name = "Figures";
        _source = source;
        _height = height;
        _log = log;
        _strict = strict;
        Clips = new ClipLibrary(source, log) { NextFrame = NextFrame };
    }

    /// <summary>One frame later (inside the tree), else at once.</summary>
    private async Task NextFrame()
    {
        if (IsInstanceValid(this) && IsInsideTree()) await ToSignal(GetTree(), SceneTree.SignalName.ProcessFrame);
    }

    /// <summary>
    /// Start the library (listing, rig, every clip) and wait for the LISTING only: the pose table is known, the
    /// clips keep coming in the background — a model fit waits for them (<c>await this.settled</c>). A missing list
    /// leaves every figure in bind pose (online); <c>strict</c> rethrows.
    /// </summary>
    public async Task InitAsync()
    {
        var load = Clips.LoadClipsAsync();
        await Task.WhenAny(load, Clips.ListingParsed);
        if (load.IsFaulted)
        {
            if (_strict) await load;
            _log($"clips: list failed: {load.Exception?.InnerException?.Message} — figures stay in bind pose");
        }
    }

    private readonly TaskCompletionSource _firstPoll = new(TaskCreationOptions.RunContinuationsAsynchronously);

    /// <summary>
    /// Completes when the FIRST poll's figures and the model loads it started are done (failed loads included —
    /// they are counted, not awaited again). The bench (S2) starts after it.
    /// </summary>
    public Task FirstPollDone => _firstPoll.Task;

    /// <summary>The latest polled <c>/play/worldmap</c> payload (null before the first poll) — the bench anchor's snapshot.</summary>
    public JsonElement? LatestMap { get; private set; }

    /// <summary>The last poll failed (the HUD's <c>connection: 'lost'</c>); false after the next good one.</summary>
    public bool LastPollFailed { get; private set; }

    /// <summary>Counts finished polls (good or failed) — lets a reader see that <see cref="LatestMap"/> was renewed.</summary>
    public int PollSerial { get; private set; }

    /// <summary>A poll landed: <see cref="LatestMap"/> is the new payload (the event pins rebuild on it, like <c>applyWorldMap</c>).</summary>
    public event Action? Polled;

    /// <summary>
    /// A world-map poll landed (the client's <see cref="Sync.PollScheduler"/> fetched it): it becomes
    /// <see cref="LatestMap"/>, the figures follow it, <see cref="Polled"/> fires. The first one completes
    /// <see cref="FirstPollDone"/> once the model loads it started are through.
    /// </summary>
    public void ApplyPolled(JsonElement map)
    {
        bool first = LatestMap is null;
        LatestMap = map;
        LastPollFailed = false;
        PollSerial++;
        var loads = Apply(map);
        Polled?.Invoke();
        if (first) _ = loads.ContinueWith(_ => _firstPoll.TrySetResult(), TaskScheduler.Default);
    }

    /// <summary>A world-map poll failed: the figures keep the last good map; nothing to wait for any more.</summary>
    public void MarkPollFailed()
    {
        LastPollFailed = true;
        PollSerial++;
        _firstPoll.TrySetResult();   // the bench runs on what is there
    }

    /// <summary>
    /// One world-map payload: resolve the spots, add/move/remove figures, hand each its activity and set chain,
    /// start model (re)loads. Reads the JSON synchronously; the returned task completes when the loads it started
    /// are done (the check awaits it, the poll loop does not).
    /// </summary>
    public Task Apply(JsonElement root)
    {
        Stats.Polls++;
        AvatarName = Json.Str(root, "avatar");
        var rows = CharacterRow.ParseList(root);
        var spots = FigurePlacement.Resolve(rows, MapPlace.ParsePlaced(root));
        Stats.Offmap = rows.Count(r => !spots.ContainsKey(r.Name));
        var loads = new List<Task>();
        foreach (var row in rows)
        {
            if (!spots.TryGetValue(row.Name, out var spot)) continue;
            var at = new Vector2((float)spot.X, (float)spot.Z);
            bool fresh = !_figures.TryGetValue(row.Name, out var fig);
            if (fresh)
            {
                fig = new Figure(row.Name);
                _figures[row.Name] = fig;
                AddChild(fig);
            }
            if (row.HeightCm is > 30 and < 400) fig!.HeightM = row.HeightCm.Value / 100.0;
            if (row.AnimationSets.Count > 0) fig!.Sets = row.AnimationSets;   // setCharacterSets: only a non-empty chain
            fig!.Rule = spot.Rule;
            fig.Activity = row.ActivityAnimation;
            fig.SetTarget(at, PollSeconds, snap: fresh);
            fig.Advance(0, _height.GroundAt);
            Gate(fig);
            fig.WantedSig = row.ModelSig;
            fig.WantedRev = row.ModelRev;
            if (fresh)
            {
                fig.SetBody(Figure.Capsule(fig.HeightM), false, null, null);
                loads.Add(LoadModelAsync(fig));
            }
            else if (!fig.Loading && !fig.RetryPending && Changed(fig)) loads.Add(LoadModelAsync(fig));
        }
        foreach (var gone in _figures.Keys.Where(n => !spots.ContainsKey(n)).ToList())
        {
            _figures[gone].QueueFree();
            _figures.Remove(gone);
        }
        UpdateStats();
        return Task.WhenAll(loads);
    }

    /// <summary>
    /// <c>refreshIfChanged(name, model_sig, model_rev)</c>: the signature differs, or the row carries a revision
    /// other than the one the model was loaded with (an absent revision never reloads).
    /// </summary>
    private static bool Changed(Figure fig)
        => fig.WantedSig != fig.LoadedSig || (fig.WantedRev is not null && fig.WantedRev != fig.LoadedRev);

    public void Tick(double dt)
    {
        foreach (var fig in _figures.Values)
        {
            fig.Advance(dt, _height.GroundAt);
            Gate(fig);
        }
    }

    /// <summary>
    /// npcs.ts <c>tickFigureTiers(camera, 25, 35)</c>: per figure with a server model, the distance from the camera
    /// picks its tier (<see cref="FigureTiers.Next"/>); a change swaps from the template cache at once or loads the
    /// missing tier. Returns the loads it started.
    /// </summary>
    public Task TickTiers(Vector3 camera)
    {
        var loads = new List<Task>();
        foreach (var fig in _figures.Values)
        {
            if (!_infos.ContainsKey(fig.CharacterName)) continue;   // no server model: the tier means nothing
            var next = FigureTiers.Next(fig.WantedTier, camera.DistanceTo(fig.Position));
            if (next == fig.WantedTier) continue;
            fig.WantedTier = next;
            loads.Add(SyncTier(fig));
        }
        UpdateStats();
        return Task.WhenAll(loads);
    }

    /// <summary>
    /// <c>syncTier</c>: bring the body to the wanted tier — a template already built swaps at once, otherwise ONE load
    /// through the model queue, then check again (the wish may have changed meanwhile). A failure gives up until the
    /// next tier change.
    /// </summary>
    private Task SyncTier(Figure fig)
    {
        if (fig.Loading || fig.WantedTier == fig.LoadedTier || !_infos.TryGetValue(fig.CharacterName, out var info)) return Task.CompletedTask;
        var want = fig.WantedTier;
        var url = UrlFor(info, want);
        if (url == fig.LoadedUrl)
        {
            // No low edition (low_url absent → url): the same mesh, nothing to swap.
            fig.LoadedTier = want;
            return Task.CompletedTask;
        }
        if (_templates.TryGetValue(TemplateKey(url, fig.Sets), out var cached) && cached.IsCompletedSuccessfully)
        {
            Instantiate(fig, cached.Result, info, want);
            return Task.CompletedTask;
        }
        fig.Loading = true;
        return _models.Push(Job(fig, async () =>
        {
            try
            {
                var template = await GetTemplate(url, info, fig.Sets);
                if (Alive(fig) && fig.LoadedSig == fig.WantedSig) Instantiate(fig, template, info, want);
            }
            catch (Exception e) when (!_strict)
            {
                _log($"figure {fig.CharacterName}: {want} tier could not be loaded: {e.Message}");
            }
            finally { fig.Loading = false; }
            if (Alive(fig) && fig.WantedTier != fig.LoadedTier && fig.LoadedUrl != UrlFor(info, fig.WantedTier)) await SyncTier(fig);
        }));
    }

    /// <summary>The URL of a tier: <c>low</c> → <c>low_url ?? url</c> (buildModel).</summary>
    private static string UrlFor(ModelInfo info, FigureTier tier) => tier == FigureTier.Low ? info.LowUrl ?? info.Url : info.Url;

    /// <summary>One model-queue job of a figure: the avatar first, then by distance² to the camera target.</summary>
    private FocusJob Job(Figure fig, Func<Task> run)
        => new(() => FocusDistance(fig), async () =>
        {
            ModelLoadOrder.Add(fig.CharacterName);
            await run();
        }, fig.CharacterName, fig.CharacterName == AvatarName);

    private double FocusDistance(Figure fig)
    {
        if (!IsInstanceValid(fig) || FocusTarget?.Invoke() is not { } t) return double.PositiveInfinity;
        return fig.Position.DistanceSquaredTo(t);
    }

    /// <summary>
    /// THE UNDERWATER GHOST of a figure, every frame (npcs.ts): <c>ghostCutY(bedY, groundWaterLevel(…))</c> on the UNGATED
    /// water level — a wader is exactly the figure the opaque water surface cuts in half. The figure stands on the bed
    /// (<see cref="WorldHeight.GroundAt"/>) until E5 brings swimming.
    /// </summary>
    private void Gate(Figure fig)
    {
        if (WaterLevelAt is not { } at) return;
        var p = fig.Position;
        fig.SetSubmerged(Water.WaterGates.GhostCutY(p.Y, at(p.X, p.Z)));
    }

    public override void _Process(double delta)
    {
        if (!AutoTick) return;
        Tick(delta);
        _tierClock += delta;
        if (_tierClock < FigureTiers.TickS) return;
        _tierClock = 0;
        if (CameraPosition?.Invoke() is { } cam) _ = TickTiers(cam);
    }

    /// <summary>Templates live outside the tree (their meshes/skeletons are only duplicated): free them here.</summary>
    public override void _ExitTree()
    {
        foreach (var task in _templates.Values)
        {
            if (!task.IsCompletedSuccessfully) continue;
            var t = task.Result;
            if (IsInstanceValid(t.Root)) t.Root.Free();
            t.Library?.Dispose();
        }
        _templates.Clear();
        Clips.Release();
    }

    /// <summary>Figures in name order (the F key cycles through them).</summary>
    public List<Figure> Ordered()
        => _figures.Values.OrderBy(f => f.CharacterName, StringComparer.Ordinal).ToList();

    /// <summary>
    /// <c>fetchCharacterModel</c>: one queue job — model3d, then the template of the wanted tier, then the body.
    /// 404 / no <c>model.url</c> → placeholder; a transient error → placeholder now, another try in
    /// <see cref="RetryDelayS"/> s. Reloads again when the row moved on meanwhile.
    /// </summary>
    private async Task LoadModelAsync(Figure fig)
    {
        fig.Loading = true;
        var sig = fig.WantedSig;
        var rev = fig.WantedRev;
        bool retry = false;
        await _models.Push(Job(fig, async () =>
        {
            try
            {
                var info = await FetchInfo(fig.CharacterName);
                if (!Alive(fig)) return;   // vanished while loading
                if (info is null)
                {
                    _infos.Remove(fig.CharacterName);
                    fig.SetBody(Figure.Capsule(fig.HeightM), false, null, null);
                    fig.BoundTracks = fig.UnboundClips = 0;
                    fig.LoadedRev = "";
                    _log($"figure {fig.CharacterName}: no model → placeholder");
                }
                else if (info.Format != "glb")
                {
                    // Generic rig: FBX + separate texture (§ A7) — Task 34. Placeholder until then.
                    _infos.Remove(fig.CharacterName);
                    fig.SetBody(Figure.Capsule(fig.HeightM), false, null, null);
                    fig.BoundTracks = fig.UnboundClips = 0;
                    fig.LoadedRev = info.ModelRev;
                    _log($"figure {fig.CharacterName}: {info.Format}/{info.Rig} model → placeholder");
                }
                else
                {
                    var tier = fig.WantedTier;
                    var template = await GetTemplate(UrlFor(info, tier), info, fig.Sets);
                    if (!Alive(fig)) return;
                    _infos[fig.CharacterName] = info;
                    fig.LoadedRev = info.ModelRev;
                    Instantiate(fig, template, info, tier);
                }
                Stats.ModelLoads++;
            }
            catch (Exception e) when (!_strict)
            {
                Stats.ModelFailures++;
                retry = true;
                _log($"figure {fig.CharacterName}: model failed: {e.Message} → placeholder, retrying in {RetryDelayS:0} s");
            }
            finally
            {
                fig.LoadedSig = sig;
                fig.Loading = false;
                if (IsInstanceValid(this)) UpdateStats();
            }
        }));
        if (!Alive(fig)) return;
        if (retry)
        {
            ScheduleRetry(fig);
            return;
        }
        // The row moved on while this load ran (a revision the model3d answer does not carry is NOT a reason by
        // itself: the browser asks again only on the next poll).
        if (fig.WantedSig != sig || fig.WantedRev != rev) await LoadModelAsync(fig);
        else if (fig.WantedTier != fig.LoadedTier) await SyncTier(fig);
    }

    /// <summary>The browser's <c>setTimeout(fetchCharacterModel, 30 000)</c> after a transient failure.</summary>
    private void ScheduleRetry(Figure fig)
    {
        if (!IsInsideTree()) return;
        fig.RetryPending = true;
        GetTree().CreateTimer(RetryDelayS).Timeout += () =>
        {
            fig.RetryPending = false;
            if (Alive(fig) && !fig.Loading) _ = LoadModelAsync(fig);
        };
    }

    /// <summary>Still the figure shown for its character (not removed, not replaced by a new one of that name).</summary>
    private bool Alive(Figure fig)
        => IsInstanceValid(fig) && _figures.TryGetValue(fig.CharacterName, out var cur) && ReferenceEquals(cur, fig);

    /// <summary><c>getCharacterModel</c> (api.ts): null for 404 or a payload without <c>model.url</c>.</summary>
    private async Task<ModelInfo?> FetchInfo(string name)
    {
        using var doc = await _source.GetCharacterModelAsync(name);
        if (doc is null) return null;
        var root = doc.RootElement;
        if (root.ValueKind != JsonValueKind.Object || !root.TryGetProperty("model", out var m)
            || m.ValueKind != JsonValueKind.Object) return null;
        var url = Json.Str(m, "url");
        if (url.Length == 0) return null;
        var rig = Json.Str(m, "rig");
        if (rig.Length == 0) rig = Json.Str(root, "rig", "mixamo");
        var low = Json.Str(m, "low_url");
        var rev = Json.Str(m, "model_rev");
        return new ModelInfo(url, low.Length > 0 ? low : null, Json.Str(m, "format", "glb").ToLowerInvariant(), rig,
                             Json.Bool(m, "normalized"), rev.Length > 0 ? rev : null);
    }

    /// <summary>A template is one model URL fitted along one set chain (the browser fits per character, the URL is per character).</summary>
    private static string TemplateKey(string url, IReadOnlyList<string> sets) => url + "|" + string.Join(",", sets);

    private Task<ModelTemplate> GetTemplate(string url, ModelInfo info, IReadOnlyList<string> sets)
    {
        var key = TemplateKey(url, sets);
        if (!_templates.TryGetValue(key, out var task) || task.IsFaulted)
            _templates[key] = task = BuildTemplate(url, info, sets);
        return task;
    }

    /// <summary>
    /// <c>buildModel</c>: download, Meshopt decode off-thread, import, metalness 0, Z-up fix, raw height; on a mixamo
    /// rig the library along <paramref name="sets"/> fitted (<c>fitLibraryAsync</c>), in slices of at most
    /// <see cref="FitSliceMs"/> ms between frames.
    /// </summary>
    private async Task<ModelTemplate> BuildTemplate(string url, ModelInfo info, IReadOnlyList<string> sets)
    {
        var bytes = await _source.GetBytesAsync(url);
        var plain = await Task.Run(() => GlbLoader.Prepare(bytes));
        var (root, _) = GlbLoader.Import(plain, url);
        root.Name = "Model";
        int metals = Dielectric(root);
        var size = ModelPlacement.Measure(root, Transform3D.Identity).Size;
        if (size.Z > size.Y * 1.5f)   // stand a Z-up export upright (buildModel)
        {
            root.Rotation = new Vector3(-Mathf.Pi / 2f, 0, 0);
            size = ModelPlacement.Measure(root, Transform3D.Identity).Size;
        }
        double raw = Math.Max(size.Y, 0.01);
        var skel = ClipLibrary.Find<Skeleton3D>(root);
        if (info.Rig != "mixamo" || skel is null || skel.GetBoneCount() == 0)
            return new ModelTemplate { Root = root, RawHeight = raw, Url = url, Corrected = -1 };

        await Clips.WaitClipsAsync();
        var sw = System.Diagnostics.Stopwatch.StartNew();
        var candidates = Clips.ClipsFor(sets);
        // The browser's rest-pose correction against the reference rig (restCorrections, once per model).
        var fixes = Clips.DonorRest is { } donor ? RestAdapter.Build(donor, root, skel) : null;
        double restMs = sw.Elapsed.TotalMilliseconds;
        var (standRef, standSource) = Clips.StandingReference(candidates);
        bool rigKnown = standSource == "rig";
        var lib = new AnimationLibrary();
        var bound = new List<BoundClip>();
        var setOf = new Dictionary<string, string>();
        int tracks = 0;
        long keys = 0;
        var slice = System.Diagnostics.Stopwatch.StartNew();
        foreach (var clip in candidates)
        {
            if (slice.Elapsed.TotalMilliseconds > FitSliceMs)
            {
                await NextFrame();
                slice.Restart();
            }
            var b = ClipLibrary.Retarget(clip, root, skel, fixes, standRef ?? 0, rigKnown);
            if (b.Anim is null) continue;
            bound.Add(b);
            setOf[clip.Kind] = clip.Set;
            tracks += b.Tracks;
            keys += b.Keys;
        }
        // One action per clip name lower-cased + the synonym aliases (Figure constructor); AddAnimation refuses
        // '/', ':', ',' and '[' (Godot's animation-name rule) — such a kind stays unbound.
        var byName = bound.GroupBy(b => b.Kind.ToLowerInvariant()).ToDictionary(g => g.Key, g => g.Last().Anim!);
        var kinds = new List<string>();
        foreach (var (kind, clipName) in ClipLibraryRules.BindActions(bound.Select(b => b.Kind).ToList()))
        {
            if (lib.AddAnimation(kind, byName[clipName.ToLowerInvariant()]) == Error.Ok) kinds.Add(kind);
            else _log($"model {url}: action '{kind}' refused by Godot's animation-name rule");
        }
        var missing = FigureClips.MissingClipKinds(candidates.Select(c => c.Kind), kinds);
        // Clip memory of this template: Godot keeps a 3D track key as TKey<T> {real_t transition; double time; T value}
        // = 32 bytes for a quaternion (4 + 4 pad + 8 + 16) and, aligned, for a Vector3 — the static-memory monitor
        // cannot attribute it (three templates fit at once and the GC frees mesh arrays meanwhile).
        long clipBytes = keys * KeyBytes;
        double fitMs = sw.Elapsed.TotalMilliseconds;
        if (missing.Count > 0)
            _log($"model {url}: {missing.Count} of {candidates.Count} library clip kinds NOT bound — {string.Join(", ", missing)}");
        _log($"model {url}: {skel.GetBoneCount()} bones, raw height {raw:0.###} m, {metals} materials metallic→0, "
             + $"{bound.Count} clips → {kinds.Count} actions (sets [{string.Join(",", sets)}]), {tracks} tracks, {keys} keys, "
             + $"clip memory ≈{clipBytes / 1048576.0:0.0} MiB, fit {fitMs:0} ms (rest + soles {restMs:0} ms), "
             + (fixes is not null ? $"{fixes.Count} bones rest-corrected" : "no rig: verbatim copy") + $", stand ref {standSource}");
        return new ModelTemplate
        {
            Root = root, RawHeight = raw, Url = url, Library = lib, Kinds = kinds, ClipSets = setOf, BoundTracks = tracks,
            Unbound = missing.Count, Corrected = fixes?.Count ?? -1, Keys = keys, ClipBytes = clipBytes, FitMs = fitMs,
        };
    }

    /// <summary>Built templates and the keys of their retargeted clips (both tiers of every character).</summary>
    public int TemplateCount => _templates.Values.Count(t => t.IsCompletedSuccessfully);
    public long TemplateKeys => _templates.Values.Where(t => t.IsCompletedSuccessfully).Sum(t => t.Result.Keys);

    /// <summary>Bytes per retargeted key (Godot's <c>TKey&lt;Quaternion&gt;</c>), for the clip-memory estimate.</summary>
    public const long KeyBytes = 32;

    /// <summary>The browser's fit slice budget (<c>FIT_SLICE_MS</c>): a frame is yielded once a slice ran this long.</summary>
    public const double FitSliceMs = 12;

    /// <summary>
    /// Characters are DIELECTRICS (figures.ts <c>buildModel</c>, AV3D-14): metalness 0 on every material of the model —
    /// Godot multiplies the metallic texture by <c>metallic</c>, so 0 zeroes an embedded MR map like three's
    /// <c>metalness = 0</c>; roughness is not touched. Returns how many materials had a non-zero metallic.
    /// </summary>
    private static int Dielectric(Node root)
    {
        int changed = 0;
        var seen = new HashSet<ulong>();
        void Fix(Material? m)
        {
            if (m is not BaseMaterial3D bm || !seen.Add(bm.GetInstanceId())) return;
            if (bm.Metallic != 0) changed++;
            bm.Metallic = 0;
        }
        foreach (var mi in Walk(root).OfType<MeshInstance3D>())
        {
            Fix(mi.MaterialOverride);
            for (int s = 0; s < mi.GetSurfaceOverrideMaterialCount(); s++) Fix(mi.GetSurfaceOverrideMaterial(s));
            if (mi.Mesh is { } mesh)
                for (int s = 0; s < mesh.GetSurfaceCount(); s++) Fix(mesh.SurfaceGetMaterial(s));
        }
        return changed;
    }

    /// <summary>Every BaseMaterial3D under a body with a non-zero metallic (the check's probe).</summary>
    public static int MetallicMaterials(Node root)
        => Walk(root).OfType<MeshInstance3D>()
                     .SelectMany(mi => Enumerable.Range(0, mi.Mesh?.GetSurfaceCount() ?? 0).Select(s => mi.GetActiveMaterial(s)))
                     .OfType<BaseMaterial3D>().Count(m => m.Metallic != 0);

    private void Instantiate(Figure fig, ModelTemplate t, ModelInfo info, FigureTier tier)
    {
        var inst = (Node3D)t.Root.Duplicate();
        double scale = info.Normalized ? 1.0 : fig.HeightM / t.RawHeight;
        var body = new Node3D { Name = "Body", Scale = Vector3.One * (float)scale };
        body.AddChild(inst);
        AnimationPlayer? player = null;
        if (t.Library is not null)
        {
            player = new AnimationPlayer { Name = "Anim" };
            inst.AddChild(player);   // root_node ".." = the model root the track paths start from
            player.AddAnimationLibrary("", t.Library);
        }
        fig.BoundTracks = t.BoundTracks;
        fig.UnboundClips = t.Unbound;
        fig.ClipSets = t.ClipSets;
        fig.ClipKeys = t.Keys;
        fig.ClipBytes = t.ClipBytes;
        fig.Poses = Clips.Poses;
        fig.LoadedUrl = t.Url;
        fig.LoadedTier = tier;
        fig.SetBody(body, true, ClipLibrary.Find<Skeleton3D>(inst), player, t.Library is null ? null : t.Kinds);
    }

    // ---- the figure pick (Task 9) ----------------------------------------------------------------

    /// <summary>
    /// The prefilter sphere around a figure: centred half-way up its height, radius 1.5 × height (at least
    /// 1.5 m). A body of height h, however posed — standing, arms raised, sitting with the legs forward, lying
    /// with the feet at the root — stays within 1.12 h of that centre (lying: √(h² + (h/2)²)); a model that
    /// came normalised (scale 1) is drawn at its own height, which the floor of 1 m covers up to 1.5 m.
    /// </summary>
    public const double PickSphereFactor = 1.5;

    /// <summary>Counters of the last figure pick (for the check and the report).</summary>
    public int LastPickCandidates { get; private set; }
    public int LastPickSkinnedVertices { get; private set; }
    public double LastPickMs { get; private set; }

    private sealed class SkinSurface
    {
        public required float[] Rest;
        public required int[] Bones;
        public required float[] Weights;
        public required int[] Indices;
        public required int Slots;
        public float[]? Posed;
    }

    /// <summary>The bind-pose arrays of a skinned mesh resource, read once (the figures of one GLB share the mesh).</summary>
    private readonly Dictionary<ulong, SkinSurface[]> _skinData = new();

    /// <summary>
    /// npcs.ts <c>characterAt(ray)</c>: the character whose figure the ray hits first, among the VISIBLE
    /// figures, and the distance (m). Every mesh of the figure counts (the whole hierarchy, as three's
    /// recursive intersect does): a skinned GLB part in its CURRENT pose — the vertices skinned on the CPU
    /// exactly as the shader skins them (<see cref="Skinning"/>), like three.js <c>SkinnedMesh.raycast</c> —
    /// and an unskinned part or the capsule placeholder as stored. A sphere around each figure
    /// (<see cref="PickSphereFactor"/>) keeps the skinning to the figures the ray can reach at all.
    /// </summary>
    public (string Name, double Distance)? CharacterAt(Vec3 origin, Vec3 dir)
    {
        var sw = System.Diagnostics.Stopwatch.StartNew();
        LastPickCandidates = 0;
        LastPickSkinnedVertices = 0;
        double len = Math.Sqrt(dir.X * dir.X + dir.Y * dir.Y + dir.Z * dir.Z);
        if (len == 0) return null;
        var o = new Vector3((float)origin.X, (float)origin.Y, (float)origin.Z);
        var d = new Vector3((float)(dir.X / len), (float)(dir.Y / len), (float)(dir.Z / len));
        string? bestName = null;
        double best = double.PositiveInfinity;
        foreach (var fig in _figures.Values)
        {
            if (!IsInstanceValid(fig) || !fig.IsVisibleInTree() || fig.Body is not { } body) continue;
            double h = Math.Max(fig.HeightM, 1.0);
            var c = fig.GlobalPosition + new Vector3(0, (float)(fig.HeightM / 2), 0);
            if (!RayMath.RaySphere(origin, new Vec3(d.X, d.Y, d.Z), new Vec3(c.X, c.Y, c.Z), PickSphereFactor * h)) continue;
            LastPickCandidates++;
            foreach (var mi in Walk(body).OfType<MeshInstance3D>())
            {
                if (!mi.IsVisibleInTree() || mi.HasMeta(World.SubmergedGhost.Meta)) continue;
                double? t = mi.Skin is not null && mi.GetNodeOrNull<Skeleton3D>(mi.Skeleton) is { } skel
                    ? SkinnedHit(mi, skel, o, d) : MeshRay.Static(mi, o, d);
                if (t is double tt && tt < best)
                {
                    best = tt;
                    bestName = fig.CharacterName;
                }
            }
        }
        LastPickMs = sw.Elapsed.TotalMilliseconds;
        return bestName is null ? null : (bestName, best);
    }

    /// <summary>The ray against a skinned mesh in its current pose: world distance of the nearest hit, or null.</summary>
    private double? SkinnedHit(MeshInstance3D mi, Skeleton3D skel, Vector3 o, Vector3 d)
    {
        if (mi.Mesh is not { } mesh || mi.Skin is not { } skin) return null;
        var surfaces = SkinData(mesh);
        if (surfaces.Length == 0) return MeshRay.Static(mi, o, d);
        // Skeleton3D's own upload (skeleton_3d.cpp): bind i → bone by its NAME when the bind has one, else by
        // its index; transform = bone global pose · bind pose.
        int binds = skin.GetBindCount();
        var mats = new Affine[binds];
        for (int i = 0; i < binds; i++)
        {
            string name = skin.GetBindName(i);
            int bone = name.Length > 0 ? skel.FindBone(name) : skin.GetBindBone(i);
            if (bone < 0 || bone >= skel.GetBoneCount()) bone = 0;
            mats[i] = ToAffine(skel.GetBoneGlobalPose(bone) * skin.GetBindPose(i));
        }
        var world = mi.GlobalTransform;
        var inv = world.AffineInverse();
        var lo = inv * o;
        var ld = inv.Basis * d;
        var lov = new Vec3(lo.X, lo.Y, lo.Z);
        var ldv = new Vec3(ld.X, ld.Y, ld.Z);
        double? best = null;
        foreach (var s in surfaces)
        {
            s.Posed ??= new float[s.Rest.Length];
            Skinning.Apply(s.Rest, s.Bones, s.Weights, s.Slots, mats, s.Posed);
            LastPickSkinnedVertices += s.Rest.Length / 3;
            if (RayMath.NearestTriangle(lov, ldv, s.Posed, s.Indices) is not double t) continue;
            var hit = world * (lo + ld * (float)t);
            double dist = (hit - o).Length();
            if (best is null || dist < best) best = dist;
        }
        return best;
    }

    private SkinSurface[] SkinData(Mesh mesh)
    {
        ulong key = mesh.GetInstanceId();
        if (_skinData.TryGetValue(key, out var cached)) return cached;
        var list = new List<SkinSurface>();
        for (int s = 0; s < mesh.GetSurfaceCount(); s++)
        {
            var arrays = mesh.SurfaceGetArrays(s);
            var verts = arrays[(int)Mesh.ArrayType.Vertex].AsVector3Array();
            var bones = arrays[(int)Mesh.ArrayType.Bones].AsInt32Array();
            var weights = arrays[(int)Mesh.ArrayType.Weights].AsFloat32Array();
            var idx = arrays[(int)Mesh.ArrayType.Index].AsInt32Array();
            if (verts.Length == 0 || bones.Length == 0 || bones.Length != weights.Length || bones.Length % verts.Length != 0)
                continue;
            if (idx.Length == 0) idx = Enumerable.Range(0, verts.Length).ToArray();
            var rest = new float[verts.Length * 3];
            for (int v = 0; v < verts.Length; v++)
            {
                rest[v * 3] = verts[v].X;
                rest[v * 3 + 1] = verts[v].Y;
                rest[v * 3 + 2] = verts[v].Z;
            }
            list.Add(new SkinSurface { Rest = rest, Bones = bones, Weights = weights, Indices = idx, Slots = bones.Length / verts.Length });
        }
        return _skinData[key] = list.ToArray();
    }

    private static Affine ToAffine(Transform3D t)
        => new(t.Basis.Column0.X, t.Basis.Column0.Y, t.Basis.Column0.Z,
               t.Basis.Column1.X, t.Basis.Column1.Y, t.Basis.Column1.Z,
               t.Basis.Column2.X, t.Basis.Column2.Y, t.Basis.Column2.Z,
               t.Origin.X, t.Origin.Y, t.Origin.Z);

    private static IEnumerable<Node> Walk(Node n)
    {
        yield return n;
        foreach (var c in n.GetChildren())
        foreach (var d in Walk(c))
            yield return d;
    }

    /// <summary>Recount (the check reads <see cref="Stats"/> after the library came in).</summary>
    public void UpdateStats()
    {
        Stats.Figures = _figures.Count;
        Stats.GlbFigures = _figures.Values.Count(f => f.IsGlb);
        Stats.Placeholders = Stats.Figures - Stats.GlbFigures;
        Stats.BoundTracks = _figures.Values.Sum(f => f.BoundTracks);
        Stats.UnboundClips = _figures.Values.Sum(f => f.UnboundClips);
        Stats.KindsBound = _figures.Values.Sum(f => f.ClipKinds.Count);
        Stats.LowTier = _figures.Values.Count(f => f.IsGlb && f.LoadedTier == FigureTier.Low);
        Stats.ClipsLoaded = Clips.ClipsLoaded;
        Stats.ClipsFailed = Clips.ClipsFailed;
    }
}
