using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
using System.Threading.Tasks;
using AnimaNative.Api;
using AnimaNative.Gltf;
using AnimaNative.Overview;
using AnimaNative.Scatter;
using AnimaNative.World;
using Godot;
using Json = AnimaNative.World.Json;

namespace AnimaNative.Figures;

/// <summary>Counts for the log line and the check.</summary>
public sealed class FigureStats
{
    public int Figures, GlbFigures, Placeholders, ClipsLoaded, ClipsFailed, BoundTracks, UnboundClips;
    public int ModelLoads, ModelFailures, Offmap, Polls, KindsBound, LowTier;
    /// <summary>Task 29: figures the placement hides, figures on a seat or a sit/lie surface, pool models, portraits.</summary>
    public int Hidden, Seated, PoolFigures, Portraits;

    public string Summary() =>
        $"figures={Figures} glb_figures={GlbFigures} placeholders={Placeholders} clips_loaded={ClipsLoaded} "
        + $"kinds_bound={KindsBound} bound_tracks={BoundTracks} unbound_clips={UnboundClips} model_loads={ModelLoads} "
        + $"model_failures={ModelFailures} offmap={Offmap} clip_failures={ClipsFailed} low_tier={LowTier} "
        + $"hidden={Hidden} seated={Seated} pool={PoolFigures} portraits={Portraits}";
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
        /// <summary><c>fit.fits</c>: at least one library clip adapted to this rig (the random pool takes only those).</summary>
        public bool LibraryFits { get; init; }
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
        _rows = CharacterRow.ParseList(root);
        _mapPlaces = MapPlace.ParsePlaced(root);
        var plans = Place();
        var loads = new List<Task>();
        foreach (var row in _rows)
        {
            if (!plans.TryGetValue(row.Name, out var plan)) continue;
            bool fresh = !_figures.TryGetValue(row.Name, out var fig);
            if (fresh)
            {
                fig = new Figure(row.Name);
                _figures[row.Name] = fig;
                AddChild(fig);
            }
            if (row.HeightCm is > 30 and < 400) fig!.HeightM = row.HeightCm.Value / 100.0;
            if (row.AnimationSets.Count > 0) fig!.Sets = row.AnimationSets;   // setCharacterSets: only a non-empty chain
            fig!.Activity = row.ActivityAnimation;
            fig.AvatarUrl = row.AvatarUrl;
            fig.IsAvatar = row.Name == AvatarName;
            ApplyPlan(fig, plan, fresh);
            fig.WantedSig = row.ModelSig;
            fig.WantedRev = row.ModelRev;
            if (fresh)
            {
                ShowStandIn(fig);
                loads.Add(LoadModelAsync(fig));
            }
            else if (!fig.Loading && !fig.RetryPending && Changed(fig)) loads.Add(LoadModelAsync(fig));
        }
        foreach (var gone in _figures.Keys.Where(n => !plans.ContainsKey(n)).ToList())
        {
            _figures[gone].QueueFree();
            _figures.Remove(gone);
            _shown.Remove(gone);
        }
        UpdateStats();
        return Task.WhenAll(loads);
    }

    // ---- placement (Task 29: main.ts computeNpcPlacements, 1 Hz from the cached map) -------------------------------

    /// <summary>The mounted locations (id → slot) the room placement reads; null = none (every row free or offmap).</summary>
    public Func<IReadOnlyDictionary<string, LocationSlot>>? Slots { get; set; }
    /// <summary>The last parsed rows and placed locations of <see cref="Apply"/> (the 1 Hz pass re-places from them).</summary>
    private List<CharacterRow> _rows = new();
    private Dictionary<string, MapPlace> _mapPlaces = new();
    /// <summary>main.ts <c>shownPlacement</c>: where each figure was drawn last (room, interior revealed).</summary>
    private readonly Dictionary<string, ShownPlacement> _shown = new();
    private double _placeClock;
    /// <summary>The placement pass interval (main.ts' <c>setInterval(…, 1000)</c> over <c>computeNpcStates(lastMap)</c>).</summary>
    public const double PlaceTickS = 1.0;
    /// <summary>The plans of the last placement pass, by name (the check reads them).</summary>
    public IReadOnlyDictionary<string, FigurePlan> LastPlans => _lastPlans;
    private Dictionary<string, FigurePlan> _lastPlans = new();

    /// <summary>
    /// One placement pass over the cached rows (<see cref="FigurePlacement.Plan"/>): the room ladder of every mounted
    /// location with its view state NOW — fade, shown storey, near ring — so opening a building, switching a storey or
    /// a re-lift reaches the figures within a second, as in the browser.
    /// </summary>
    private Dictionary<string, FigurePlan> Place()
    {
        var slots = Slots?.Invoke();
        LocationPlacement? TileOf(string locId)
        {
            if (slots is null || locId.Length == 0 || !slots.TryGetValue(locId, out var slot)) return null;
            if (!IsInstanceValid(slot.Group)) return null;
            var stands = slot.Stands;
            return new LocationPlacement(slot.PlacementView(), slot.Ring == Ring.Near, stands.TileGroundY, stands.RoomStandY);
        }
        var plans = FigurePlacement.Plan(_rows, TileOf, _height.GroundAt, _shown,
            id => _mapPlaces.TryGetValue(id, out var p) ? new Vec3(p.X, 0, p.Z) : null);
        _lastPlans = plans.ToDictionary(p => p.Name);
        Stats.Offmap = _rows.Count(r => !_lastPlans.ContainsKey(r.Name));
        Stats.Hidden = plans.Count(p => p.Hidden);
        Stats.Seated = plans.Count(p => p.Rule is "seat" or "pool");
        return _lastPlans;
    }

    /// <summary>npcs.update for one figure: target (snap or walk), facing, lean, visibility.</summary>
    private void ApplyPlan(Figure fig, FigurePlan plan, bool fresh)
    {
        fig.Rule = plan.Rule;
        fig.OnTerrain = plan.OnTerrain;
        fig.Face = plan.Face is { } f ? new Vector3((float)f.X, 0, (float)f.Z) : null;
        fig.Lean = plan.Lean;
        fig.SetHidden(plan.Hidden);
        fig.SetTarget(new Vector3((float)plan.Pos.X, (float)plan.Pos.Y, (float)plan.Pos.Z), PollSeconds, snap: fresh || plan.Snap);
        fig.Advance(0, _height.GroundAt);
        Gate(fig);
    }

    /// <summary>
    /// The placement census of one location (the <c>--offline</c> report): its rows' plans counted by rule, how many are
    /// hidden, and how many stand in front of the building although the server has them in a room.
    /// </summary>
    public string Census(string locId)
    {
        var rows = _rows.Where(r => r.LocationId == locId && _lastPlans.ContainsKey(r.Name)).ToList();
        var plans = rows.Select(r => _lastPlans[r.Name]).ToList();
        var rules = string.Join(" ", plans.GroupBy(p => p.Rule).OrderBy(g => g.Key, StringComparer.Ordinal).Select(g => $"{g.Key}={g.Count()}"));
        int doorstep = rows.Count(r => r.RoomId.Length > 0 && _lastPlans[r.Name] is { Rule: "tile", Hidden: false });
        return $"figures={plans.Count} {rules} hidden={plans.Count(p => p.Hidden)} visible_room_figures_on_doorstep={doorstep}";
    }

    /// <summary>The 1 Hz pass: re-place every figure from the cached rows (no model work — that is the poll's).</summary>
    public void TickPlacement()
    {
        if (_rows.Count == 0) return;
        foreach (var (name, plan) in Place())
            if (_figures.TryGetValue(name, out var fig)) ApplyPlan(fig, plan, false);
    }

    /// <summary>
    /// <c>refreshIfChanged(name, model_sig, model_rev)</c>: the signature differs, or the row carries a revision
    /// other than the one the model was loaded with (an absent revision never reloads).
    /// </summary>
    private static bool Changed(Figure fig)
        => fig.WantedSig != fig.LoadedSig || (fig.WantedRev is not null && fig.WantedRev != fig.LoadedRev);

    public void Tick(double dt)
    {
        double camDist = CamDist?.Invoke() ?? DefaultCamDist;
        foreach (var fig in _figures.Values)
        {
            fig.Advance(dt, _height.GroundAt);
            Gate(fig);
            fig.Portrait?.Tick(dt, camDist, fig.Moving);
        }
    }

    /// <summary>The camera's orbit distance (the portrait sprites size with it, npcs.ts <c>camDist·0.055</c>).</summary>
    public Func<double>? CamDist { get; set; }
    /// <summary>Without a camera: the distance at which a portrait has its initial 2.6 m.</summary>
    public const double DefaultCamDist = 2.6 / 0.055;

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
        _placeClock += delta;
        if (_placeClock >= PlaceTickS)
        {
            _placeClock = 0;
            TickPlacement();
        }
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
                    // apiModels.set(name, null): the fallback pool, else the portrait (instantiate).
                    _infos.Remove(fig.CharacterName);
                    fig.Api = Figure.ModelAnswer.None;
                    fig.LoadedRev = "";
                    ShowStandIn(fig);
                    _log($"figure {fig.CharacterName}: no model → {(fig.PoolModel is { } pm ? $"pool model {pm}" : "portrait")}");
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
                    fig.Api = Figure.ModelAnswer.Ready;
                    fig.LoadedRev = info.ModelRev;
                    Instantiate(fig, template, info, tier);
                }
                Stats.ModelLoads++;
            }
            catch (Exception e) when (!_strict)
            {
                Stats.ModelFailures++;
                retry = true;
                // firstAttemptFailed: the pool (or the portrait) stands in until the retry brings the model.
                if (Alive(fig) && fig.Api != Figure.ModelAnswer.Ready)
                {
                    fig.Api = Figure.ModelAnswer.Failed;
                    ShowStandIn(fig);
                }
                _log($"figure {fig.CharacterName}: model failed: {e.Message} → stand-in, retrying in {RetryDelayS:0} s");
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
    private async Task<ModelTemplate> BuildTemplate(string url, ModelInfo info, IReadOnlyList<string> sets, bool ownClips = false)
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
        // The file's own takes (the pool's Soldier / Xbot / Robot): taken out of the import's player, kept per kind.
        var own = ownClips ? TakeOwnClips(root) : new List<(string Kind, Animation Anim)>();
        if (info.Rig != "mixamo" || skel is null || skel.GetBoneCount() == 0)
        {
            if (own.Count == 0) return new ModelTemplate { Root = root, RawHeight = raw, Url = url, Corrected = -1 };
            var ownLib = new AnimationLibrary();
            foreach (var (kind, anim) in own) ownLib.AddAnimation(kind, anim);
            return new ModelTemplate { Root = root, RawHeight = raw, Url = url, Corrected = -1, Library = ownLib, Kinds = own.Select(o => o.Kind).ToList() };
        }

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
        // A file's own take wins its kind (embedded first in the action order: [...model.clips, ...fit.extra]).
        foreach (var (kind, anim) in own)
            if (lib.AddAnimation(kind, anim) == Error.Ok) kinds.Add(kind);
        var ownKinds = own.Select(o => o.Kind).ToHashSet();
        foreach (var (kind, clipName) in ClipLibraryRules.BindActions(bound.Where(b => !ownKinds.Contains(b.Kind.ToLowerInvariant()))
                                                                           .Select(b => b.Kind).ToList()))
        {
            if (lib.HasAnimation(kind)) continue;
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
            LibraryFits = bound.Count > 0,
        };
    }

    /// <summary>
    /// A model file's own non-empty takes, lower-cased, looping (a take nobody flagged loops), taken out of the import's
    /// AnimationPlayer (which is freed: the figure's one player carries them).
    /// </summary>
    private static List<(string Kind, Animation Anim)> TakeOwnClips(Node root)
    {
        var list = new List<(string, Animation)>();
        foreach (var player in Walk(root).OfType<AnimationPlayer>().ToList())
        {
            foreach (var libName in player.GetAnimationLibraryList())
            {
                var lib = player.GetAnimationLibrary(libName);
                foreach (var name in lib.GetAnimationList())
                {
                    var anim = lib.GetAnimation(name);
                    if (anim.GetTrackCount() == 0) continue;
                    var kind = name.ToString().ToLowerInvariant();
                    if (list.Any(e => e.Item1 == kind)) continue;
                    var copy = (Animation)anim.Duplicate();
                    copy.LoopMode = Animation.LoopModeEnum.Linear;
                    list.Add((kind, copy));
                }
            }
            player.GetParent()?.RemoveChild(player);
            player.Free();
        }
        return list;
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

    private void Instantiate(Figure fig, ModelTemplate t, ModelInfo info, FigureTier tier, double? poolHeight = null)
    {
        var inst = (Node3D)t.Root.Duplicate();
        double scale = poolHeight is { } ph ? ph / t.RawHeight : info.Normalized ? 1.0 : fig.HeightM / t.RawHeight;
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

    // ---- the fallback pool and the portrait (Task 29, ruling P3-R10) -------------------------------------------------

    /// <summary>Where the browser's fallback pool lives (served anonymously with the 3D client, § /static/client3d).</summary>
    public const string PoolBase = "/static/client3d/models/";

    private sealed record PoolModel(string Name, ModelTemplate Template, ModelInfo Info, double Height, bool AssignOnly);

    private readonly List<PoolModel> _pool = new();
    private Dictionary<string, string> _assignments = new();
    private readonly HashSet<string> _waitingForPool = new();
    private Task? _poolLoad;
    /// <summary>figures.ts <c>poolState</c>: idle → loading → ready | failed (a failure retries after 30 s while someone waits).</summary>
    public string PoolState { get; private set; } = "idle";
    /// <summary>The pool's models in manifest order and whether the library fits each (for the check / report).</summary>
    public IReadOnlyList<(string Name, bool LibraryFits)> PoolModels => _pool.Select(p => (p.Name, p.Template.LibraryFits)).ToList();
    private readonly Dictionary<string, Task<Image?>> _portraits = new();

    /// <summary>
    /// figures.ts <c>instantiate(name)</c> for a figure without a server model on screen: when the server said "none" or
    /// failed (or the manifest assigns this character a model) the pool is wanted — not ready yet → the portrait now and a
    /// pool load (the figure waits for it); ready → the assigned model, else a seeded pick over the rigs the library
    /// fits (<c>animatablePool</c>, <c>seededRandom('model:' + name)</c>); an empty pool → the portrait.
    /// </summary>
    private void ShowStandIn(Figure fig)
    {
        if (fig.Api == Figure.ModelAnswer.Ready) return;
        bool wantsPool = fig.Api is Figure.ModelAnswer.None or Figure.ModelAnswer.Failed
                         || (fig.Api == Figure.ModelAnswer.Unknown && _assignments.ContainsKey(fig.CharacterName));
        if (wantsPool && PoolState != "ready")
        {
            _waitingForPool.Add(fig.CharacterName);
            if (PoolState == "idle") _ = EnsurePool();
            ShowPortrait(fig);
            return;
        }
        var model = PickPoolModel(fig.CharacterName);
        if (model is null)
        {
            ShowPortrait(fig);
            return;
        }
        if (fig.PoolModel == model.Name && fig.Body is not null) return;
        Instantiate(fig, model.Template, model.Info, FigureTier.Full, model.Height);
        fig.MarkPool(model.Name, model.Height);
        UpdateStats();
    }

    /// <summary>The pool model for a character (<c>instantiate</c>'s choice), null when the pool holds none.</summary>
    private PoolModel? PickPoolModel(string name)
    {
        if (_pool.Count == 0) return null;
        var assigned = _assignments.TryGetValue(name, out var a) ? a : name;
        var model = _pool.FirstOrDefault(m => m.Name == assigned);
        if (model is not null) return model;
        var pool = FigureClips.AnimatablePool(_pool.Where(m => !m.AssignOnly).ToList(), m => m.Template.LibraryFits);
        if (pool.Count == 0) return null;
        var rnd = ScatterMath.SeededRandom("model:" + name);
        return pool[(int)Math.Floor(rnd() * pool.Count)];
    }

    /// <summary>The portrait sprite (once per figure body; the picture is fetched once per URL).</summary>
    private void ShowPortrait(Figure fig)
    {
        if (fig.Portrait is not null) return;
        var portrait = new Portrait(fig.CharacterName, fig.IsAvatar);
        fig.SetPortrait(portrait);
        fig.BoundTracks = fig.UnboundClips = 0;
        UpdateStats();
        if (fig.AvatarUrl.Length == 0) return;
        var url = Portrait.TransparentPortraitUrl(fig.AvatarUrl);
        if (!_portraits.TryGetValue(url, out var load))
            _portraits[url] = load = FetchPortrait(url);
        _ = PictureWhenLoaded(fig, portrait, load);
    }

    /// <summary><c>img.onload = () =&gt; draw(img)</c>: on the main thread, only while that portrait is still the body.</summary>
    private async Task PictureWhenLoaded(Figure fig, Portrait portrait, Task<Image?> load)
    {
        var img = await load;
        if (img is not null && IsInstanceValid(fig) && ReferenceEquals(fig.Portrait, portrait)) portrait.SetPicture(img);
    }

    private async Task<Image?> FetchPortrait(string url)
    {
        try
        {
            var bytes = await _source.GetBytesAsync(url);
            return Portrait.Decode(bytes);
        }
        catch (Exception e)
        {
            _log($"portrait {url}: {e.Message} — the initials stay");
            return null;
        }
    }

    /// <summary>figures.ts <c>ensureFallbackPool</c>: one load at a time; the waiting figures are served when it settles.</summary>
    public Task EnsurePool() => _poolLoad ??= LoadPoolAsync();

    /// <summary>
    /// <c>loadManifestModels</c>: the manifest (<c>defaultHeight</c>, <c>models[]</c>, <c>assignments</c>), every model
    /// that is not assign-only (or is assigned) built like a server model on a mixamo rig — its own takes first, the
    /// library over the neutral set — scaled to its own height (<c>height ?? defaultHeight</c>). Nothing loaded = failed;
    /// a failed pool is asked again after 30 s while figures wait for it.
    /// </summary>
    private async Task LoadPoolAsync()
    {
        PoolState = "loading";
        try
        {
            using var doc = JsonDocument.Parse(await _source.GetBytesAsync(PoolBase + "manifest.json"));
            var root = doc.RootElement;
            double defaultHeight = Json.Num(root, "defaultHeight", DefaultHeightM);
            var assignments = new Dictionary<string, string>();
            if (root.TryGetProperty("assignments", out var asg) && asg.ValueKind == JsonValueKind.Object)
                foreach (var p in asg.EnumerateObject())
                    if (p.Value.ValueKind == JsonValueKind.String) assignments[p.Name] = p.Value.GetString()!;
            _assignments = assignments;
            var assigned = assignments.Values.ToHashSet();
            foreach (var m in Json.Arr(root, "models"))
            {
                var name = Json.Str(m, "name");
                var file = Json.Str(m, "url");
                bool assignOnly = Json.Bool(m, "assignOnly");
                if (name.Length == 0 || file.Length == 0 || (assignOnly && !assigned.Contains(name))) continue;
                var url = PoolBase + file;
                var info = new ModelInfo(url, null, "glb", "mixamo", false, null);
                try
                {
                    var template = await BuildTemplate(url, info, Array.Empty<string>(), ownClips: true);
                    _pool.Add(new PoolModel(name, template, info, Json.Num(m, "height", defaultHeight), assignOnly));
                    _log($"pool model {name}: {template.Kinds.Count} actions, library {(template.LibraryFits ? "fits" : "does not fit")}");
                }
                catch (Exception e)
                {
                    _log($"pool model {name} failed: {e.Message}");
                }
            }
            if (_pool.Count == 0) throw new InvalidOperationException("no fallback model loaded");
            PoolState = "ready";
        }
        catch (Exception e)
        {
            PoolState = "failed";
            _log($"fallback pool failed — portraits stand in, retrying in {RetryDelayS:0} s: {e.Message}");
        }
        if (!IsInstanceValid(this)) return;
        var waiting = _waitingForPool.ToList();
        if (PoolState == "ready") _waitingForPool.Clear();
        foreach (var name in waiting)
            if (_figures.TryGetValue(name, out var fig) && Alive(fig)) ShowStandIn(fig);
        if (PoolState == "failed")
        {
            _poolLoad = null;
            if (IsInsideTree() && _waitingForPool.Count > 0)
                GetTree().CreateTimer(RetryDelayS).Timeout += () =>
                {
                    if (_waitingForPool.Count > 0 && PoolState == "failed") { PoolState = "idle"; _ = EnsurePool(); }
                };
        }
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
            if (fig.Portrait is { } portrait)
            {
                // three's Sprite.raycast hits the camera-facing quad; here the quad faces the ray (a vertical billboard
                // through the sprite's axis), Scale × Scale with its anchor 2 % above its bottom edge.
                if (PortraitHit(portrait, fig.GlobalPosition, o, d) is { } pt && pt < best)
                {
                    best = pt;
                    bestName = fig.CharacterName;
                }
                continue;
            }
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

    /// <summary>
    /// The ray against a portrait sprite: the vertical plane through the figure's axis facing the ray (normal = −d
    /// horizontal), hit when the point lies within half the sprite's size sideways and between its bottom and top edge
    /// (root + lift − 0.02·size … + 0.98·size). A ray without a horizontal part, or one running away, misses.
    /// </summary>
    public static double? PortraitHit(Portrait portrait, Vector3 root, Vector3 o, Vector3 d)
    {
        var h = new Vector3(d.X, 0, d.Z);
        if (h.LengthSquared() < 1e-12f) return null;
        h = h.Normalized();
        double denom = d.Dot(h);
        double t = (root - o).Dot(h) / denom;
        if (!(t > 0)) return null;
        var p = o + d * (float)t;
        double side = new Vector3(p.X - root.X, 0, p.Z - root.Z).Length();
        double size = portrait.Scale;
        double bottom = root.Y + portrait.Lift - Portrait.Anchor * size;
        if (side > size / 2 || p.Y < bottom || p.Y > bottom + size) return null;
        return t;
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
        Stats.PoolFigures = _figures.Values.Count(f => f.PoolModel is not null);
        Stats.Portraits = _figures.Values.Count(f => f.Portrait is not null);
        Stats.ClipsLoaded = Clips.ClipsLoaded;
        Stats.ClipsFailed = Clips.ClipsFailed;
    }
}
