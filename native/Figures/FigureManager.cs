using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
using System.Threading.Tasks;
using AnimaNative.Api;
using AnimaNative.Gltf;
using AnimaNative.Overview;
using AnimaNative.Scatter;
using AnimaNative.Scene;
using AnimaNative.Water;
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
    /// <summary>Task 30: snaps that moved a figure more than 0.5 m (npcs.ts <c>syncCounters.place</c>).</summary>
    public int PlaceSnaps;

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
///   • which and where: <see cref="FigurePlacement.Plan"/> once a second from the cached map (journeys, free points,
///     the room ladder of every mounted location — Task 29), a real room change routed through doors, stairs or the
///     lift (<see cref="NpcRoute"/>);
///   • how it gets there: every frame the browser's NPC walk (<see cref="Tick"/>, Task 30) — 3.4 m/s, running beyond
///     6 m, stations retired at 1.5 m, the yaw eased ×10/s, the root height ×4/s, the ground word deciding swim / crawl
///     / treading and the float over water, the underwater ghost, the stair ride;
///   • fed by the client's world-map poll (<see cref="ApplyPolled"/>); <c>activity_animation</c> is what a standing
///     figure plays, <c>animation_sets</c> its set chain;
///   • model: <c>GET /characters/{name}/model3d</c> → <c>model.url</c> / <c>model.low_url</c> used unchanged (§ A7),
///     every load (model3d + GLB + fit) one job of a <see cref="FocusQueue"/> of width 3 — the avatar first, then
///     the figure nearest the camera target; a GLB is Meshopt-decoded and imported once per (URL, set chain) and
///     duplicated per figure; an FBX (animals, rig <c>generic</c>) is imported through Godot's FBXDocument and dressed
///     in its separate <c>texture_url</c> (Task 34); "no model" (404 or <c>model</c> null) shows the fallback pool or
///     the portrait (Task 29); a transient failure retries after <see cref="RetryDelayS"/>; reloaded when the row's
///     <c>model_sig</c> or <c>model_rev</c> changes (§ A11a, <c>refreshIfChanged</c>);
///   • looks: metalness forced to 0 on every material (characters are dielectrics, AV3D-14), roughness untouched;
///     scale <c>normalized</c> → 1, else height / raw bounding-box height (height = <c>height_cm</c>/100 when
///     30 &lt; cm &lt; 400, default 1.70 m; a Z-up export is stood up first);
///   • clips: the file's own takes (every rig but <c>none</c>, loop flags from <c>model.clips</c>); on a <c>mixamo</c>
///     rig also the WHOLE library along the character's set chain (<see cref="ClipLibrary.ClipsFor"/>), planned once per
///     template and each clip fitted when a figure first needs it (<see cref="TemplateClips"/>, Task 35b); one action
///     per kind + the synonym aliases; a rig without any action walks procedurally (<see cref="ProceduralGait"/>, Task 34);
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
    /// <summary>false in <c>--check</c>: time only moves through <see cref="Tick"/>, tiers only through <see cref="TickTiers"/>.</summary>
    public bool AutoTick { get; set; } = true;
    /// <summary>
    /// How the library clips are fitted (Task 35b, ruling P3-R15): <see cref="ClipFitMode.Lazy"/> in the client, the checks
    /// <see cref="ClipFitMode.OnDemandSync"/> (the same lazy plan, a needed clip fitted inside the call that asks for it).
    /// Set before the first template is built.
    /// </summary>
    public ClipFitMode ClipFit { get; set; } = ClipFitMode.Lazy;
    /// <summary>Strict (the checks): a failure is thrown, not logged.</summary>
    public bool Strict => _strict;

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
    private readonly Dictionary<string, PublicMotionState> _publicRoutes = new();
    private readonly Dictionary<string, (PublicPropEntry Entry, double Received)> _publicEntries = new();
    private readonly Dictionary<string, PublicPropEntry> _finishedEntries = new();
    private readonly HashSet<(string Name, string Kind)> _entryWarnings = new();
    private readonly Dictionary<string, PublicPropEntry> _cancelledEntries = new();
    private readonly Dictionary<string, PublicPropEntry> _failedEntries = new();
    public event Action<string>? MotionUnavailable;
    public bool HasSemanticMotion { get; private set; }
    public string? ControlledName { get; set; }
    public void CancelOwnedMotion()
    {
        if (_publicRoutes.TryGetValue(AvatarName, out var route)) route.CancelOwned();
        if (_publicEntries.TryGetValue(AvatarName, out var entry)) _cancelledEntries[AvatarName] = entry.Entry;
        _publicEntries.Remove(AvatarName);
        _finishedEntries.Remove(AvatarName);
        _failedEntries.Remove(AvatarName);
        if (_figures.TryGetValue(AvatarName, out var fig)) { fig.EndPublicEntry(); fig.Pair = null; }
    }

    /// <summary>
    /// What the GROUND says at a world point (npcs.ts <c>groundMoveAt</c>, main.ts <c>setTerrainMove</c>:
    /// <see cref="World.WorldBuilder.FigureGroundMove"/>) — movement word, sinks, mirror, swim threshold, speed, scope,
    /// prop water; null = the world without painted ground (walk, run, no water, no ghosts).
    /// </summary>
    public Func<double, double, GroundMove>? GroundMoveAt { get; set; }
    /// <summary>
    /// The ground height under a figure (npcs.ts <c>groundY</c>, main.ts <c>groundY</c>: the tile ladder inside a
    /// footprint, the world outside — <see cref="World.WorldBuilder.FigureGroundY"/>); null = the world height.
    /// </summary>
    public Func<double, double, double>? GroundYAt { get; set; }
    /// <summary>
    /// main.ts <c>npcs.setPlaceAt</c>: the slot height of a place a pair is seated on — (the character's room, the place
    /// id, anchor x, z) → slot 0's y, null = unknown (<see cref="World.WorldBuilder.PairSeatY"/>); null = no lookup.
    /// </summary>
    public Func<string, string, double, double, double?>? SeatYAt { get; set; }
    /// <summary>
    /// main.ts <c>npcs.setRoomStandAt</c>: the standing height of the character's room at a point (null = none,
    /// <see cref="World.WorldBuilder.PairRoomStandY"/>); null = no lookup (every pair on the ground).
    /// </summary>
    public Func<string, double, double, double?>? RoomStandAt { get; set; }

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
        /// <summary>The bind box (three's <c>Box3.setFromObject</c>, skinned rest pose, the Z-up fix included); null = no mesh.</summary>
        public (V3 Min, V3 Max)? BindBox { get; init; }
        public AnimationLibrary? Library { get; init; }
        /// <summary>The action kinds of the library (planned: own takes, then the library actions), in action order (the figure's fallback is the first).</summary>
        public IReadOnlyList<string> Kinds { get; init; } = Array.Empty<string>();
        /// <summary>Library kind → the set its file came from (the set chain's decision).</summary>
        public IReadOnlyDictionary<string, string> ClipSets { get; init; } = new Dictionary<string, string>();
        /// <summary>Tracks and keys of every library clip that binds on this rig (the plan — what an eager fit holds).</summary>
        public int BoundTracks { get; init; }
        public int Unbound { get; init; }
        /// <summary>Bones with a rest correction; −1 = no rig (verbatim copy).</summary>
        public int Corrected { get; init; }
        public long Keys { get; init; }
        /// <summary>The library clips, fitted lazily (Task 35b); null for a template without the library (own takes only).</summary>
        public TemplateClips? Lazy { get; init; }
        /// <summary>Keys of the FITTED clips this template created itself (the ones it shares are another template's).</summary>
        public long OwnKeys => Lazy?.OwnKeys ?? 0;
        /// <summary>Fitted clips taken over from an earlier template because their content is identical (<see cref="ShareIdentical"/>).</summary>
        public int SharedClips => Lazy?.SharedClips ?? 0;
        /// <summary>The estimated memory of this template's OWN fitted clip keys (<see cref="OwnKeys"/> × <see cref="KeyBytes"/>).</summary>
        public long ClipBytes => OwnKeys * KeyBytes;
        /// <summary>Every FITTED library clip of this template and its key count (shared ones included).</summary>
        public IReadOnlyDictionary<Animation, long> AnimKeys => Lazy?.AnimKeys ?? (IReadOnlyDictionary<Animation, long>)EmptyKeys;
        /// <summary>The set chain the library was fitted along (for <see cref="ProbeClipMemory"/>).</summary>
        public IReadOnlyList<string> Sets { get; init; } = Array.Empty<string>();
        /// <summary>Wall time of the build's own fit (plan + the clips fitted at build).</summary>
        public double FitMs { get; init; }
        /// <summary><c>fit.fits</c>: at least one library clip adapted to this rig (the random pool takes only those).</summary>
        public bool LibraryFits { get; init; }
        /// <summary>Per fitted Animation: its bridge travel / turn / lift and ground offset (empty without a fit).</summary>
        public IReadOnlyDictionary<Animation, ClipExtras> Extras => Lazy?.Extras ?? (IReadOnlyDictionary<Animation, ClipExtras>)EmptyExtras;

        private static readonly Dictionary<Animation, long> EmptyKeys = new();
        private static readonly Dictionary<Animation, ClipExtras> EmptyExtras = new();
    }

    private sealed record ModelInfo(string Url, string? LowUrl, string Format, string Rig, bool Normalized, string? ModelRev)
    {
        /// <summary><c>model.texture_url</c>: the separate base-colour texture of an FBX model (null = none).</summary>
        public string? TextureUrl { get; init; }
        /// <summary><c>model.clips</c>: the loop flag per EXACT embedded take name (missing = loop).</summary>
        public IReadOnlyDictionary<string, bool> ClipLoops { get; init; } = new Dictionary<string, bool>();
        /// <summary>The answer's top-level <c>motion</c> (<c>extension_rig.motion_payload</c>); null = none.</summary>
        public MotionPayload? Motion { get; init; }
    }

    /// <summary>
    /// figures.ts <c>motionState</c>: the motion payload per character — the worldmap row's <c>motion</c> whenever it
    /// carries one, else the model3d answer's (only while none is known). The figure reads it every frame.
    /// </summary>
    private readonly Dictionary<string, MotionPayload?> _motionState = new();

    /// <summary>The world map's <c>game_rate === 0</c>: the world is frozen (the secondary motion stops its dynamics).</summary>
    public bool WorldFrozen { get; private set; }

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
        var avatar = Json.Str(root, "avatar");
        if (avatar != AvatarName)
        {
            _publicRoutes.Clear();
            _publicEntries.Clear();
            _finishedEntries.Clear();
            _failedEntries.Clear();
            _cancelledEntries.Clear();
            ControlledName = null;
        }
        AvatarName = avatar;
        WorldFrozen = root.TryGetProperty("game_rate", out var rate) && rate.ValueKind == JsonValueKind.Number && rate.GetDouble() == 0;
        _rows = CharacterRow.ParseList(root);
        _rowByName = _rows.GroupBy(r => r.Name).ToDictionary(g => g.Key, g => g.Last());
        HasSemanticMotion = _rows.Any(row => row.PropEntry is not null || row.LocalApproach is not null);
        var avatarRoom = _rowByName.GetValueOrDefault(AvatarName)?.RoomId ?? "";
        foreach (var row in _rows)
        {
            if (!_publicRoutes.TryGetValue(row.Name, out var motion)) _publicRoutes[row.Name] = motion = new PublicMotionState();
            motion.Adopt(row.RouteFor(AvatarName, avatarRoom), _clock);
            if (row.PropEntry is { } entry && (!_cancelledEntries.TryGetValue(row.Name, out var cancelled) || !cancelled.SameClip(entry)))
                _publicEntries[row.Name] = (entry, _clock);
            else _publicEntries.Remove(row.Name);
        }
        foreach (var gone in _publicRoutes.Keys.Where(name => !_rowByName.ContainsKey(name)).ToArray())
        {
            _publicRoutes.Remove(gone);
            _publicEntries.Remove(gone);
            _finishedEntries.Remove(gone);
            _failedEntries.Remove(gone);
        }
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
            // refreshIfChanged(name, sig, rev, motion): a row's motion replaces the known payload, an absent one keeps it.
            if (row.HasMotion || !_motionState.ContainsKey(row.Name)) _motionState[row.Name] = row.Motion;
            fig.Motion = _motionState[row.Name];
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
    private Dictionary<string, CharacterRow> _rowByName = new();
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
            return new LocationPlacement(slot.PlacementView(), slot.Ring == Ring.Near, stands.TileGroundY, stands.RoomStandY)
            {
                Route = slot.RouteView(),
            };
        }
        var plans = FigurePlacement.Plan(_rows, TileOf, _height.GroundAt, _shown,
            id => _mapPlaces.TryGetValue(id, out var p) ? new Vec3(p.X, 0, p.Z) : null);
        _lastPlans = plans.ToDictionary(p => p.Name);
        Stats.Offmap = _rows.Count(r => !_lastPlans.ContainsKey(r.Name));
        Stats.Hidden = plans.Count(p => p.Hidden);
        Stats.Seated = plans.Count(p => p.Rule is "seat" or "pool");
        return _lastPlans;
    }

    /// <summary>
    /// npcs.ts <c>update</c> for one figure (and main.ts' ride bookkeeping of a routed room change): a NEW goal adopts the
    /// route's stations (<c>st.via</c>); a snap — the first placement, a view change — puts the figure on it at once,
    /// stations and climb dropped; then goal, pace 1, facing, lean, visibility and the travelling flag.
    /// </summary>
    private void ApplyPlan(Figure fig, FigurePlan plan, bool fresh)
    {
        fig.Rule = plan.Rule;
        AdoptInteraction(fig);
        if (fig.CharacterName == ControlledName) return;
        if (!_publicEntries.ContainsKey(fig.CharacterName) && _failedEntries.TryGetValue(fig.CharacterName, out var failed))
        {
            var row = _rowByName.GetValueOrDefault(fig.CharacterName);
            if (row?.Place is not null || row?.Interaction is not null)
            {
                // Core completed but this renderer never had a valid measured entry: hide, never invent a teleport.
                fig.SnapTo(new Vector3((float)failed.Access.X, (float)failed.Access.Y, (float)failed.Access.Z));
                fig.SetHidden(true);
                return;
            }
            _failedEntries.Remove(fig.CharacterName); // actual cancellation/stop, not a successful furniture arrival
        }
        _publicRoutes.TryGetValue(fig.CharacterName, out var motion);
        if (_publicEntries.ContainsKey(fig.CharacterName) || motion is not null && motion.TryAt(_clock, out _))
        {
            fig.SetHidden(plan.Hidden);
            if (plan.Hidden)
            {
                _publicEntries.Remove(fig.CharacterName);
                motion?.Adopt(null, _clock);
                fig.EndPublicEntry();
            }
            return;
        }
        if (_finishedEntries.Remove(fig.CharacterName, out var finished))
        {
            var row = _rowByName.GetValueOrDefault(fig.CharacterName);
            bool committed = row?.Place is not null || row?.Interaction is not null;
            if (committed && !fig.PlayPublicEntry(finished, 1))
            {
                _failedEntries[fig.CharacterName] = finished;
                fig.SetHidden(true);
                MotionUnavailable?.Invoke($"prop entry {fig.CharacterName}: final measured clip/support data unavailable");
                return;
            }
            fig.EndPublicEntry();
            var at = committed ? new Vec3(finished.Anchor.X, finished.Anchor.Y, finished.Anchor.Z) : plan.Pos;
            fig.SnapTo(new Vector3((float)at.X, (float)at.Y, (float)at.Z));
            fig.SetYaw(committed ? finished.Anchor.Yaw * Math.PI / 180 : fig.Yaw);
            fig.PlayDirect(fig.Activity);
        }
        // THE GOAL: the server's point — or, after a stand-up, the spot the bridge left the figure on, for as long as the
        // server sends the SAME point (settleOffset against the kept server point); a different one voids the spot.
        if (fig.Settle is { } kept)
        {
            var offset = StandSettle.SettleOffset(new P2(kept.Server.X + kept.Offset.X, kept.Server.Z + kept.Offset.Z),
                                                  new P2(plan.Pos.X, plan.Pos.Z), kept.Server);
            fig.Settle = offset is { } o ? (kept.Server, o) : null;
        }
        var settle = fig.Settle?.Offset ?? new P2(0, 0);
        var goal = new Vector3((float)(plan.Pos.X + settle.X), (float)plan.Pos.Y, (float)(plan.Pos.Z + settle.Z));
        if (fresh)
        {
            // createNpc: the first sync puts the figure on its point — no walk across the whole map.
            fig.SnapTo(goal);
        }
        else
        {
            // main.ts: a routed room change ends whatever climb the figure was on (the avatar's own climb excepted), and
            // a climb over stairs becomes the ride — unarmed, the figure is still a room away.
            if (plan.Routed && fig.CharacterName != AvatarName) fig.Ride = null;
            if (plan.Legs.Count > 0) fig.Ride = new Scene.StairRide { Legs = plan.Legs };
            if (fig.Target != goal)
            {
                fig.Waypoints.Clear();
                if (plan.Via is { } via) fig.Waypoints.AddRange(via.Select(v => new Vector3((float)v.X, (float)v.Y, (float)v.Z)));
            }
            if (plan.Snap)
            {
                if (fig.Position.DistanceTo(goal) > 0.5f) Stats.PlaceSnaps++;
                fig.SnapTo(goal);
            }
        }
        fig.Target = goal;
        fig.Pace = 1;
        fig.Face = plan.Face is { } f ? new Vector3((float)f.X, (float)f.Y, (float)f.Z) : null;
        fig.Lean = plan.Lean;
        fig.ApplyRotation();
        fig.SetHidden(plan.Hidden);
        fig.Travelling = _rowByName.TryGetValue(fig.CharacterName, out var row) && row.Travelling;
    }

    /// <summary>
    /// npcs.ts <c>adoptInteraction</c> from the row's <c>interaction</c> (§ A8a), stamped with the poll it came from (the
    /// 1 Hz pass re-reads the SAME payload and reconciles nothing): a NEW interaction drops the stations and the climb —
    /// the anchor places the figure, not a walk.
    /// </summary>
    private void AdoptInteraction(Figure fig)
    {
        var it = _rowByName.TryGetValue(fig.CharacterName, out var row) ? row.Interaction : null;
        fig.Pair = PairPlay.Adopt(fig.Pair, it, Stats.Polls, out bool fresh);
        if (!fresh) return;
        fig.Waypoints.Clear();
        fig.Ride = null;
        // The half is asked for now (Task 35b): its fit runs while the poll's other work goes on.
        if (fig.Pair is { } pair) fig.EnsureClip(pair.Clip);
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

    /// <summary>
    /// The per-frame walk of every figure — npcs.ts <c>tick</c> without a server route (journeys follow their polled
    /// point by reckoning until E6) and the player-driven figure (E7); the bridges hold the step (paceLimitFor) and hand the
    /// travel and the height over (takeTravel + settle, beginBridgeLift / shiftBridgeLift):
    ///
    ///   1. the plan (<see cref="NpcWalk.Goal"/>): stations retire at 1.5 m (a stair ride at 0.4 m), the goal is the first
    ///      left, else the target; standing at ≤ 0.05 m;
    ///   2. the step (<see cref="NpcWalk.Step"/>): 3.4 m/s, running ×1.8 beyond 6 m (+10 m while a station is left) on a
    ///      ground that lets one run, never for a traveller; the figure turns into the step;
    ///   3. the ground word where it now stands (<see cref="WalkGround.WordOf"/>): the underwater ghost cut at the UNGATED
    ///      mirror over the bed; the sink of the state (move / idle) cut by the scope;
    ///   4. the height: a guided climb answers it outright (<see cref="Stairs.RideStep"/>, swept from the frame start), else the root eases ×4/s to
    ///      <c>floatRootY(station or target y, mirror, sink)</c>;
    ///   5. standing: the marker's facing, else the neighbours' centroid within 4.5 m, else keep;
    ///   6. the clip: <c>moveClip(movement, run)</c> moving, else <c>standingClipFor(activity, idleClip(movement))</c>,
    ///      the ground's clips dropped by the sink; the yaw eases ×10/s.
    /// </summary>
    public void Tick(double dt)
    {
        _clock += dt;
        double camDist = CamDist?.Invoke() ?? DefaultCamDist;
        // npcs.ts facingTargets(): every figure's neighbours, measured before anybody steps this frame.
        var all = _figures.Values.ToList();
        var positions = all.Select(f => V(f.Position)).ToList();
        var faceTo = new Dictionary<Figure, Vec3>();
        for (int i = 0; i < all.Count; i++)
            if (NpcWalk.NeighbourFacing(positions[i], positions.Where((_, j) => j != i)) is { } c) faceTo[all[i]] = c;
        foreach (var fig in all) StepFigure(fig, dt, faceTo.TryGetValue(fig, out var n) ? n : null, camDist);
    }

    private static Vec3 V(Vector3 v) => new(v.X, v.Y, v.Z);

    /// <summary>The manager's frame clock (s): the sum of every <see cref="Tick"/> delta — the bridges' clock.</summary>
    private double _clock;
    public double Clock => _clock;

    /// <summary>npcs.ts <c>groundWordAt(x, z)</c>: the raw ground word, the bed under the point and the gated word.</summary>
    public GroundWord WordAt(double x, double z)
        => WalkGround.WordOf(GroundMoveAt?.Invoke(x, z) ?? GroundMove.Plain, GroundYAt?.Invoke(x, z) ?? _height.GroundAt(x, z));

    private void StepFigure(Figure fig, double dt, Vec3? neighbour, double camDist)
    {
        if (fig.CharacterName == ControlledName) return;
        if (_failedEntries.ContainsKey(fig.CharacterName) && !_publicEntries.ContainsKey(fig.CharacterName)) return;
        if (TickPublicMotion(fig, dt)) return;
        // A running pair interaction places the figure and plays its half (npcs.ts: `tickInteraction` before anything).
        if (fig.Pair is not null && TickPair(fig, dt)) return;
        // BRIDGE TRAVEL WITHOUT A ROUTE (rule 4, figures.ts travelBase): the bridge has ended and its body stands where
        // the clip carried it — the root moves there now, the body on screen does not move. The GOAL does not move with
        // it: it is the server's stand point (seat + travel); near it the NPC keeps the spot it stands on.
        if (fig.Player is not null && !fig.Bridging && fig.HoldsTravel && ApplyBridgeTravel(fig)) SettleAfterBridge(fig);
        var pos = V(fig.Position);
        // Where this frame starts, for the ride's swept test below: the walk retires a landing from HERE.
        var frameFrom = new P2(pos.X, pos.Z);
        var plan = NpcWalk.Goal(pos, V(fig.Target), fig.Waypoints.Select(V).ToList(),
                                fig.Ride is not null ? Stairs.RideArriveM : NpcWalk.WaypointArriveM);
        fig.Waypoints.RemoveRange(0, plan.Retired);
        double rootYBefore = pos.Y;
        bool reckoning = fig.Travelling;
        var stepGround = WordAt(pos.X, pos.Z);
        var (running, _) = NpcWalk.Step(plan, stepGround.Word.Movement, reckoning, dt, fig.Pace, 1);
        // A BRIDGE CLIP HOLDS THE FIGURE at the step: asked for the clip this frame WILL ask for (paceLimitFor), because
        // the clip is played after the step — on the frame a bridge starts, paceLimit would still say "nothing holds you".
        double paceLimit = fig.Player is null ? 1
            : plan.Moving && !fig.Bridging ? fig.PaceLimitFor(FigureClips.MoveClip(stepGround.Word.Movement, running, fig.Poses))
            : fig.PaceLimit;
        if (plan.Moving && paceLimit > 0)
        {
            var (_, step) = NpcWalk.Step(plan, stepGround.Word.Movement, reckoning, dt, fig.Pace, paceLimit);
            double len = plan.DistToGoal;
            double dx = plan.Delta.X / len, dz = plan.Delta.Z / len;
            pos = new Vec3(pos.X + dx * step, pos.Y, pos.Z + dz * step);
            fig.FaceTowards(new Vector3((float)dx, 0, (float)dz));
        }
        var stand = WordAt(pos.X, pos.Z);
        var raw = stand.Raw;
        if (fig.Portrait is null)
            fig.SetSubmerged(WaterGates.GhostCutY(stand.BedY, WaterGates.GroundWaterLevel(raw.Water, raw.Scope)));
        var standIdle = FigureClips.IdleClip(stand.Word.Movement, fig.Poses);
        double standSink = WalkGround.GroundSink(WalkGround.SinkForState(plan.Moving, standIdle, stand.Word.Sink),
                                                 WalkGround.SinkScope(raw));
        // THE HEIGHT: the ride's ramp outright, else the root eases to the station's (or the goal's) height, floated —
        // unless a bridge owns the height (easeRootY: a different floor is handed over to the lift instead).
        double? rideY = null;
        if (fig.Ride is { } ride)
        {
            var r = Stairs.RideStep(ride, pos.X, pos.Y, pos.Z, frameFrom);
            if (r.Done) fig.Ride = null;
            else
            {
                ride.Leg = r.Leg;
                ride.Armed = r.Armed;
                rideY = r.Y;
            }
        }
        double y, goalY;
        if (rideY is { } ry) y = goalY = ry;
        else
        {
            goalY = WalkGround.FloatRootY(fig.Waypoints.Count > 0 ? fig.Waypoints[0].Y : fig.Target.Y, stand.Word.Water, standSink);
            y = EaseRootY(fig, pos.Y, goalY, dt);
        }
        fig.Position = new Vector3((float)pos.X, (float)y, (float)pos.Z);
        var standingClip = FigureClips.StandingClipFor(fig.Activity, standIdle, fig.Poses);
        if (!plan.Moving && fig.Portrait is null)
        {
            var marker = fig.Face is { } f ? new Vec3(f.X, f.Y, f.Z) : (Vec3?)null;
            // Not while a bridge holds the facing: the body getting up is the clip's.
            if (NpcWalk.StandingFacing(new Vec3(pos.X, y, pos.Z), marker, neighbour, null) is { } dir && !fig.HoldsFacing)
                fig.FaceTowards(new Vector3((float)dir.X, (float)dir.Y, (float)dir.Z));
        }
        bool run = !reckoning && plan.Dist > NpcWalk.RunDistance;
        fig.SetMotion(plan.Moving, plan.Moving && run && FigureClips.CanRun(stand.Word.Movement), stand.Word.Movement);
        PlayLifting(fig, plan.Moving ? FigureClips.MoveClip(stand.Word.Movement, run, fig.Poses) : standingClip,
                    plan.Moving || standIdle.Length > 0, standSink, rootYBefore, goalY);
        fig.SecondaryFrozen = WorldFrozen;
        fig.UpdateFigure(dt);
        fig.Portrait?.Tick(dt, camDist, plan.Moving);
    }

    private bool TickPublicMotion(Figure fig, double dt)
    {
        var name = fig.CharacterName;
        if (_publicEntries.TryGetValue(name, out var pending))
        {
            var e = pending.Entry;
            double phase = e.PhaseAt(_clock - pending.Received);
            if (!fig.PlayPublicEntry(e, phase))
            {
                _failedEntries[name] = e;
                fig.Position = new Vector3((float)e.Access.X, (float)e.Access.Y, (float)e.Access.Z);
                if (_entryWarnings.Add((name, e.Kind)))
                {
                    string message = $"prop entry {name}: measured clip/support data for '{e.Kind}' unavailable; holding authoritative access";
                    _log(message);
                    MotionUnavailable?.Invoke(message);
                }
                fig.SecondaryFrozen = true;
                fig.UpdateFigure(0);
            }
            else
            {
                _failedEntries.Remove(name);
                _finishedEntries[name] = e;
            }
            return true;
        }
        if (_publicRoutes.TryGetValue(name, out var route) && route.TryAt(_clock, out var point))
        {
            var before = fig.Position;
            var room = _rowByName.GetValueOrDefault(name)?.RoomId ?? "";
            double y = RoomStandAt?.Invoke(room, point.X, point.Z)
                ?? GroundYAt?.Invoke(point.X, point.Z) ?? _height.GroundAt(point.X, point.Z);
            fig.Position = new Vector3((float)point.X, (float)y, (float)point.Z);
            var delta = fig.Position - before;
            bool moving = !WorldFrozen && delta.LengthSquared() > 1e-10;
            if (moving) fig.FaceTowards(delta);
            fig.SetMotion(moving, false, "walk");
            fig.Play(moving ? FigureClips.MoveClip("walk", false, fig.Poses) : FigureClips.IdleClip("walk", fig.Poses));
            fig.SecondaryFrozen = WorldFrozen;
            fig.UpdateFigure(dt);
            return true;
        }
        return false;
    }

    /// <summary>
    /// npcs.ts <c>tickInteraction</c>: one frame of a pair interaction — the clock advances (<see cref="PairPlay.Advance"/>),
    /// the half plays at the phase (<see cref="Figure.PlayPair"/>, which also ends a running bridge; a travel nobody took
    /// is dropped: the ANCHOR places the figure), the root stands at <c>anchor + R_y(yaw)·pairRootAt(phase)</c> at the
    /// place's slot height, else the room's stand, else the ground (<see cref="PairPlay.Place"/>), turned to the anchor's
    /// yaw. False when the figure has no rig or the half is not loaded / bound: the ordinary placement and a solo clip.
    /// </summary>
    private bool TickPair(Figure fig, double dt)
    {
        var it = fig.Pair!;
        if (fig.Player is null || fig.Portrait is not null) return false;
        double phase = it.Advance(dt);
        if (Clips.PairRootAt(it.Clip, phase) is not { } root) return false;
        if (fig.ClipPending(it.Clip))
        {
            // Lazy (Task 35b): the half is being fitted — the figure holds where it stands, playing what it played.
            fig.SecondaryFrozen = WorldFrozen;
            fig.UpdateFigure(dt);
            return true;
        }
        if (!fig.PlayPair(it.Clip, phase, it.Rate <= 0, it.Loop)) return false;
        if (fig.HoldsTravel) fig.TakeTravel();
        var room = _rowByName.TryGetValue(fig.CharacterName, out var row) ? row.RoomId : "";
        var at = it.Place(root, (id, x, z) => SeatYAt?.Invoke(room, id, x, z),
                          (x, z) => RoomStandAt?.Invoke(room, x, z),
                          (x, z) => GroundYAt?.Invoke(x, z) ?? _height.GroundAt(x, z));
        fig.Position = new Vector3((float)at.X, (float)at.Y, (float)at.Z);
        fig.SetYaw(it.Anchor.Yaw);
        fig.SecondaryFrozen = WorldFrozen || it.Rate <= 0;   // npcs.ts: figure.update(dt, {frozen: frozen || it.rate <= 0})
        fig.UpdateFigure(dt);
        return true;
    }

    /// <summary>
    /// npcs.ts <c>easeRootY</c>: the 4·dt ease towards <paramref name="goalY"/> — unless a bridge owns the height: then a
    /// goal off the floor the bridge started over is handed to the lift (<see cref="Figure.ShiftBridgeLift"/>) and the
    /// root goes onto it at once.
    /// </summary>
    private static double EaseRootY(Figure fig, double rootY, double goalY, double dt)
    {
        if (fig.HoldsHeight)
        {
            double drop = rootY - goalY;
            if (Math.Abs(drop) > 1e-6 && fig.ShiftBridgeLift(drop)) return goalY;
            return rootY;
        }
        return NpcWalk.EaseY(rootY, goalY, dt);
    }

    /// <summary>
    /// npcs.ts <c>playLifting</c>: ask the figure for its clip — and when that opens a bridge the figure LIFTS, put the
    /// root onto its goal height at once and hand the difference over (<see cref="Figure.BeginBridgeLift"/>).
    /// </summary>
    private static void PlayLifting(Figure fig, string kind, bool terrainClip, double sink, double rootYBefore, double goalY)
    {
        bool wasBridging = fig.Bridging;
        fig.Play(kind, terrainClip, sink);
        if (!wasBridging && fig.Bridging && fig.BeginBridgeLift(rootYBefore - goalY))
            fig.Position = new Vector3(fig.Position.X, (float)goalY, fig.Position.Z);
        // Lazy (Task 35b): the HOLDING bridge this frame asked for waits for its clip — the root keeps the height it had,
        // so the bridge takes the whole difference over once it opens (the eager fit opened it this frame, from there).
        else if (fig.PendingBridgeAccel is <= 0)
            fig.Position = new Vector3(fig.Position.X, (float)rootYBefore, fig.Position.Z);
    }

    /// <summary>npcs.ts <c>applyBridgeTravel</c>: the root takes the figure's held travel over; false when none was held.</summary>
    private static bool ApplyBridgeTravel(Figure fig)
    {
        if (fig.TakeTravel() is not { } t) return false;
        fig.Position = new Vector3((float)(fig.Position.X + t.X), fig.Position.Y, (float)(fig.Position.Z + t.Z));
        return true;
    }

    /// <summary>
    /// npcs.ts <c>settleAfterBridge</c>: the goal is the server's stand point (seat + the clip's travel); within
    /// <see cref="StandSettle.StandAdoptM"/> of it the NPC keeps the spot its root now stands on.
    /// </summary>
    private static void SettleAfterBridge(Figure fig)
    {
        var server = fig.Settle is { } kept ? kept.Server : new P2(fig.Target.X, fig.Target.Z);
        var offset = StandSettle.SettleOffset(new P2(fig.Position.X, fig.Position.Z), server, server);
        fig.Settle = offset is { } o ? (server, o) : null;
        fig.Target = new Vector3((float)(server.X + (offset?.X ?? 0)), fig.Target.Y, (float)(server.Z + (offset?.Z ?? 0)));
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
        if (_templates.TryGetValue(TemplateKey(url, fig.Sets, fig.HeightM), out var cached) && cached.IsCompletedSuccessfully)
        {
            // A cached tier swaps at once — once the clips the figure plays are fitted on it (Task 35b); until then the
            // body on screen stays.
            var prepared = PrepareAsync(fig, cached.Result);
            if (prepared.IsCompletedSuccessfully)
            {
                Instantiate(fig, cached.Result, info, want);
                return Task.CompletedTask;
            }
            fig.Loading = true;
            return SwapWhenFitted(fig, cached.Result, info, want, prepared);
        }
        fig.Loading = true;
        return _models.Push(Job(fig, async () =>
        {
            try
            {
                var template = await GetTemplate(url, info, fig.Sets, fig.HeightM);
                if (Alive(fig)) await PrepareAsync(fig, template);
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

    /// <summary>The cached tier's swap once its clips are fitted (<see cref="SyncTier"/>); the wish may have moved on meanwhile.</summary>
    private async Task SwapWhenFitted(Figure fig, ModelTemplate t, ModelInfo info, FigureTier want, Task prepared)
    {
        try { await prepared; }
        catch (Exception e) when (!_strict) { _log($"figure {fig.CharacterName}: {want} tier clips could not be fitted: {e.Message}"); }
        finally { fig.Loading = false; }
        if (!Alive(fig)) return;
        if (fig.WantedTier == want && fig.LoadedSig == fig.WantedSig) Instantiate(fig, t, info, want);
        if (fig.WantedTier != fig.LoadedTier) await SyncTier(fig);
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
        RetireStaleTemplates();
        if (CameraPosition?.Invoke() is { } cam) _ = TickTiers(cam);
    }

    /// <summary>
    /// figures.ts <c>retireModels</c> / <c>freeRetired</c>: a character whose model changed (a new <c>model_sig</c> /
    /// <c>model_rev</c> = a new URL) leaves both tier templates of its OLD model behind. Once no figure shows such a
    /// template and no load is running, it is freed — its mesh copy, its skeleton and every clip no live template
    /// shares. A template stays while any character's current model names its URL (both tiers stay cached, like the
    /// browser's <c>tierCache</c>). Runs on the 1 Hz tier tick; returns how many templates were freed.
    /// </summary>
    public int RetireStaleTemplates()
    {
        // Never while a template is being built: it may already bind a clip of a template this pass would free.
        if (_figures.Values.Any(f => f.Loading) || _templates.Values.Any(t => !t.IsCompleted) || PoolState == "loading") return 0;
        // Nor while a clip is being fitted (Task 35b): it may be about to share a clip of a template this pass would free.
        if (_templates.Values.Any(t => t.IsCompletedSuccessfully && t.Result.Lazy is { Busy: true })
            || _pool.Any(p => p.Template.Lazy is { Busy: true })) return 0;
        var live = new HashSet<string>(StringComparer.Ordinal);
        foreach (var info in _infos.Values)
        {
            live.Add(info.Url);
            if (info.LowUrl is { } low) live.Add(low);
        }
        foreach (var fig in _figures.Values)
            if (fig.LoadedUrl is { } u) live.Add(u);
        var stale = _templates.Where(kv => kv.Value.IsCompleted && !(kv.Value.IsCompletedSuccessfully && live.Contains(kv.Value.Result.Url)))
                              .Select(kv => kv.Key).ToList();
        if (stale.Count == 0) return 0;
        var freed = new List<ModelTemplate>();
        foreach (var key in stale)
        {
            var task = _templates[key];
            _templates.Remove(key);
            if (task.IsCompletedSuccessfully) freed.Add(task.Result);
        }
        // The clips another template still binds stay (they are shared, ShareIdentical); the rest go with the template.
        var kept = new HashSet<Animation>(_templates.Values.Where(t => t.IsCompletedSuccessfully).Select(t => t.Result)
                                                   .Concat(_pool.Select(p => p.Template))
                                                   .Where(t => t.Library is not null).SelectMany(t => LibraryAnims(t.Library!)));
        foreach (var t in freed)
        {
            var anims = t.Library is { } lib ? LibraryAnims(lib).Where(a => !kept.Contains(a)).Distinct().ToList() : new List<Animation>();
            foreach (var digest in _sharedClips.Where(kv => anims.Contains(kv.Value)).Select(kv => kv.Key).ToList())
                _sharedClips.Remove(digest);
            t.Lazy?.Kill();
            if (IsInstanceValid(t.Root)) t.Root.Free();
            t.Library?.Dispose();
            foreach (var a in anims) a.Dispose();
        }
        _log($"figures: {freed.Count} template(s) of replaced models freed ({string.Join(", ", freed.Select(t => t.Url))})");
        return freed.Count;
    }

    private static IEnumerable<Animation> LibraryAnims(AnimationLibrary lib)
        => lib.GetAnimationList().Select(n => lib.GetAnimation(n));

    /// <summary>Templates live outside the tree (their meshes/skeletons are only duplicated): free them here.</summary>
    public override void _ExitTree()
    {
        foreach (var task in _templates.Values)
        {
            if (!task.IsCompletedSuccessfully) continue;
            var t = task.Result;
            t.Lazy?.Kill();
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
                else
                {
                    var tier = fig.WantedTier;
                    var template = await GetTemplate(UrlFor(info, tier), info, fig.Sets, fig.HeightM);
                    if (!Alive(fig)) return;
                    // Its first frame plays what it should: the clips it needs are fitted before the body is shown.
                    await PrepareAsync(fig, template);
                    if (!Alive(fig)) return;
                    // fetchCharacterModel: the model3d motion stands in while the worldmap has sent none.
                    if (!_motionState.TryGetValue(fig.CharacterName, out var known) || known is null)
                        _motionState[fig.CharacterName] = info.Motion;
                    fig.Motion = _motionState[fig.CharacterName];
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
        var texture = Json.Str(m, "texture_url");
        // applyEmbeddedClipLoops: the server's loop declaration per EXACT embedded take name (missing = loop).
        var loops = new Dictionary<string, bool>(StringComparer.Ordinal);
        if (m.TryGetProperty("clips", out var cl) && cl.ValueKind == JsonValueKind.Object)
            foreach (var c in cl.EnumerateObject())
                if (c.Value.ValueKind == JsonValueKind.Object && c.Value.TryGetProperty("loop", out var lp)
                    && lp.ValueKind is JsonValueKind.True or JsonValueKind.False)
                    loops[c.Name] = lp.ValueKind == JsonValueKind.True;
        return new ModelInfo(url, low.Length > 0 ? low : null, Json.Str(m, "format", "glb").ToLowerInvariant(), rig,
                             Json.Bool(m, "normalized"), rev.Length > 0 ? rev : null)
        {
            ClipLoops = loops, Motion = MotionPayload.Of(root), TextureUrl = texture.Length > 0 ? texture : null,
        };
    }

    /// <summary>
    /// A template is one model URL fitted along one set chain at one height (the browser fits per character, the URL is
    /// per character; the height is the scale the bridges are re-locked at).
    /// </summary>
    private static string TemplateKey(string url, IReadOnlyList<string> sets, double heightM)
        => url + "|" + string.Join(",", sets) + "|" + heightM.ToString("R", System.Globalization.CultureInfo.InvariantCulture);

    private Task<ModelTemplate> GetTemplate(string url, ModelInfo info, IReadOnlyList<string> sets, double heightM)
    {
        var key = TemplateKey(url, sets, heightM);
        if (!_templates.TryGetValue(key, out var task) || task.IsFaulted)
            _templates[key] = task = BuildTemplate(url, info, sets, heightM);
        return task;
    }

    /// <summary>
    /// <c>loadFile(url, forceFbx)</c>: the FBX loader when the answer says <c>format: fbx</c> or the URL names a
    /// <c>.fbx</c> file, glTF otherwise.
    /// </summary>
    public static bool IsFbx(string format, string url)
        => format == "fbx" || System.Text.RegularExpressions.Regex.IsMatch(url, @"\.fbx(\?|$)", System.Text.RegularExpressions.RegexOptions.IgnoreCase);

    /// <summary>
    /// <c>buildModel</c>: download, import (FBX through Godot's FBXDocument; a GLB Meshopt-decoded off-thread), an FBX's
    /// separate texture (<see cref="DressInTexture"/>), metalness 0, Z-up fix, raw height; the file's own
    /// takes (every rig but <c>none</c>) with the server's loop flags; on a mixamo rig the library along
    /// <paramref name="sets"/> fitted (<c>fitLibraryAsync</c>) — an embedded take wins its kind, the library fills the
    /// rest. Since Task 35b only PLANNED here (<see cref="TemplateClips"/>: which clips bind, under which actions) and
    /// the movement poses fitted; every other clip is fitted — retargeted, its bridge re-locked, pinned, lifted and turned
    /// (<see cref="FootLockMeasure"/>, baked into the bound Animation), its ground offset measured (<see cref="ClipGround"/>)
    /// — when a figure on the template first needs it. <paramref name="heightM"/> is the figure's height: the scale the
    /// bridges are re-locked at is <c>normalized ? 1 : height / raw</c> (the figure's <c>baseScale</c>).
    /// </summary>
    private async Task<ModelTemplate> BuildTemplate(string url, ModelInfo info, IReadOnlyList<string> sets, double heightM)
    {
        var bytes = await _source.GetBytesAsync(url);
        // The main-thread parts of the build, timed for the log (Task 35b): the import, the bind box, the rest correction, the plan.
        var importWatch = System.Diagnostics.Stopwatch.StartNew();
        Node3D root;
        if (IsFbx(info.Format, url))
        {
            root = ClipLibrary.ImportFbxScene(bytes) as Node3D ?? throw new InvalidOperationException($"FBX {url}: the scene root is not a Node3D");
            if (info.TextureUrl is { } textureUrl) DressInTexture(root, await LoadTexture(textureUrl));
            else BrowserLook(root);
        }
        else
        {
            // Decoded and PARSED off the main thread (Task 35b: the parse — buffers, meshes, images — was most of a model's
            // 35–40 ms main-thread import); only the scene (nodes) is generated here.
            var (doc, state, _) = await Task.Run(() => GlbLoader.Parse(GlbLoader.Prepare(bytes), url));
            importWatch.Restart();
            root = GlbLoader.Generate(doc, state, url);
        }
        double importMs = importWatch.Elapsed.TotalMilliseconds;
        await NextFrame();   // the build's main-thread parts each in a frame of their own (Task 35b)
        importWatch.Restart();
        root.Name = "Model";
        int metals = Dielectric(root);
        // three's Box3.setFromObject: a skinned mesh counts in its SKINNED rest pose (BridgeFit.BindBox), not by its
        // mesh-space AABB — a rig whose bind poses carry the armature's scale or turn (Xbot, Test3_mia) is 100× off
        // and lying down by the plain AABB. The engine data is read here, the skinning runs on a worker.
        var gathered = BridgeFit.GatherBindBox(root);
        double boxMs = importWatch.Elapsed.TotalMilliseconds;
        var box = await Task.Run(() => BridgeFit.ComputeBindBox(gathered));
        if (box.Size.Z > box.Size.Y * 1.5f)   // stand a Z-up export upright (buildModel)
        {
            importWatch.Restart();
            root.Rotation = new Vector3(-Mathf.Pi / 2f, 0, 0);
            gathered = BridgeFit.GatherBindBox(root);
            boxMs += importWatch.Elapsed.TotalMilliseconds;
            box = await Task.Run(() => BridgeFit.ComputeBindBox(gathered));
        }
        importWatch.Restart();
        var size = box.Size;
        double raw = Math.Max(size.Y, 0.01);
        // The Figure constructor's anchoring box (`!box.isEmpty()`: a model without a mesh is not anchored).
        (V3 Min, V3 Max)? bind = Walk(root).OfType<MeshInstance3D>().Any(m => m.Mesh is not null)
            ? (new V3(box.Position.X, box.Position.Y, box.Position.Z), new V3(box.End.X, box.End.Y, box.End.Z)) : null;
        var skel = ClipLibrary.Find<Skeleton3D>(root);
        // The file's own takes (`clips: rig === 'none' ? [] : gltf.animations`): taken out of the import's player, kept
        // per kind with the server's loop flag of the exact take name — for server models and the pool alike.
        var own = TakeOwnClips(root, info.ClipLoops, IsFbx(info.Format, url));
        if (info.Rig == "none") own.Clear();
        boxMs += importWatch.Elapsed.TotalMilliseconds;
        if (info.Rig != "mixamo" || skel is null || skel.GetBoneCount() == 0)
        {
            // Generic rigs keep their own takes (animals: idle, walk, run, sit …); a rig left without any action walks
            // procedurally (the Figure's leg chains).
            if (own.Count == 0)
            {
                _log($"model {url}: {info.Format}/{info.Rig}, no takes, raw height {raw:0.###} m — procedural gait");
                return new ModelTemplate { Root = root, RawHeight = raw, Url = url, Corrected = -1, BindBox = bind };
            }
            var ownLib = new AnimationLibrary();
            var actionKinds = new List<string>();
            var byKind = own.ToDictionary(o => o.Kind, o => o.Anim);
            // The Figure constructor's action table: every take by its lower-cased name, then the synonym aliases.
            foreach (var (kind, clip) in ClipLibraryRules.BindActions(own.Select(o => o.Kind).ToList()))
                if (ownLib.AddAnimation(kind, byKind[clip]) == Error.Ok) actionKinds.Add(kind);
            _log($"model {url}: {info.Format}/{info.Rig}, raw height {raw:0.###} m, {own.Count} takes → {actionKinds.Count} actions "
                 + $"[{string.Join(", ", actionKinds.Select(k => ownLib.GetAnimation(k).LoopMode == Animation.LoopModeEnum.None ? k + " (once)" : k))}]");
            return new ModelTemplate { Root = root, RawHeight = raw, Url = url, Corrected = -1, Library = ownLib, Kinds = actionKinds, BindBox = bind };
        }

        await Clips.WaitClipsAsync();
        await NextFrame();
        var sw = System.Diagnostics.Stopwatch.StartNew();
        var candidates = Clips.ClipsFor(sets);
        // The browser's rest-pose correction against the reference rig (restCorrections, once per model).
        var fixes = Clips.DonorRest is { } donor ? RestAdapter.Build(donor, root, skel) : null;
        double restMs = sw.Elapsed.TotalMilliseconds;
        var (standRef, standSource) = Clips.StandingReference(candidates);
        bool rigKnown = standSource == "rig";
        var lib = new AnimationLibrary();
        var kinds = new List<string>();
        // A file's own take wins its kind (embedded first in the action order: [...model.clips, ...fit.extra]).
        foreach (var (kind, anim) in own)
            if (lib.AddAnimation(kind, anim) == Error.Ok) kinds.Add(kind);
        var ownKinds = own.Select(o => o.Kind).ToHashSet();
        double scale = info.Normalized ? 1 : heightM / raw;
        await NextFrame();
        var planWatch = System.Diagnostics.Stopwatch.StartNew();
        // The PLAN (Task 35b): which library clips bind on this rig and under which actions — no key is written yet.
        var lazy = new TemplateClips(this, _log, url, root, skel, fixes, standRef ?? 0, rigKnown, scale, lib);
        double planMs = planWatch.Elapsed.TotalMilliseconds;
        await lazy.PlanAsync(candidates, ownKinds);
        kinds.AddRange(lazy.Actions);
        var missing = FigureClips.MissingClipKinds(candidates.Select(c => c.Kind), kinds);
        // The fit at build: the movement poses (the figure that asked adds its own clips before it is shown, PrepareAsync);
        // everything in the eager reference mode.
        var movement = MovementActions(kinds);
        if (ClipFit == ClipFitMode.Eager) await lazy.EnsureAllAsync();
        else await lazy.EnsureAsync(movement);
        lazy.Built = true;
        double fitMs = sw.Elapsed.TotalMilliseconds;
        if (missing.Count > 0)
            _log($"model {url}: {missing.Count} of {candidates.Count} library clip kinds NOT bound — {string.Join(", ", missing)}");
        _log($"model {url}: {skel.GetBoneCount()} bones, raw height {raw:0.###} m, {metals} materials metallic→0, "
             + $"{lazy.PlannedClips} clips → {kinds.Count} actions (sets [{string.Join(",", sets)}]), {lazy.PlannedTracks} tracks, {lazy.PlannedKeys} keys planned; "
             + $"fitted at build {lazy.FittedClips} of {lazy.FittableClips} clips ({ClipFit}; movement [{string.Join(",", movement)}]), {lazy.SharedClips} shared with an earlier template, "
             + $"own clip memory ≈{lazy.OwnKeys * KeyBytes / 1048576.0:0.00} MiB, fit {fitMs:0} ms (main thread: import {importMs:0} ms, "
             + $"bind box + takes {boxMs:0} ms, rest + soles {restMs:0} ms, rig + skins {planMs:0} ms), "
             + (fixes is not null ? $"{fixes.Count} bones rest-corrected" : "no rig: verbatim copy") + $", stand ref {standSource}");
        return new ModelTemplate
        {
            Root = root, RawHeight = raw, Url = url, BindBox = bind, Library = lib, Kinds = kinds, ClipSets = lazy.ClipSets,
            BoundTracks = lazy.PlannedTracks, Unbound = missing.Count, Corrected = fixes?.Count ?? -1, Keys = lazy.PlannedKeys,
            FitMs = fitMs, Sets = sets.ToArray(), LibraryFits = lazy.PlannedClips > 0, Lazy = lazy,
        };
    }

    /// <summary>
    /// <c>Figure.play</c>'s resolution of a raw kind on a template's actions: lower-cased (empty = the standing pose),
    /// <see cref="FigureClips.ResolveClipKind"/>, else the first action ("" = none).
    /// </summary>
    private string ResolveAction(string raw, IReadOnlyList<string> kinds)
    {
        var kind = (raw.Length > 0 ? raw : FigureClips.PoseKind(FigureClips.Standing, Clips.Poses)).ToLowerInvariant();
        var chosen = FigureClips.ResolveClipKind(kind, kinds, Clips.Poses);
        return chosen.Length > 0 ? chosen : kinds.FirstOrDefault() ?? "";
    }

    /// <summary>
    /// The movement poses on a template — what every figure plays standing, walking, running, swimming, treading water,
    /// crawling and resting from a crawl — fitted at build so that no figure waits for them (ruling P3-R15).
    /// </summary>
    private List<string> MovementActions(IReadOnlyList<string> kinds)
    {
        var poses = Clips.Poses;
        var actions = new List<string> { ResolveAction("", kinds) };   // "" = the standing pose
        foreach (var m in new[] { FigureClips.WalkRun, FigureClips.Walk, FigureClips.Swim, FigureClips.Crawl })
            foreach (var raw in new[] { FigureClips.MoveClip(m, false, poses), FigureClips.MoveClip(m, true, poses), FigureClips.IdleClip(m, poses) })
                if (raw.Length > 0) actions.Add(ResolveAction(raw, kinds));
        return actions.Where(a => a.Length > 0).Distinct().ToList();
    }

    /// <summary>
    /// The actions <paramref name="fig"/> needs on its first frame on a template: the standing pose, its activity, what
    /// it asked for last and what plays on its current body (a tier swap), its pair half.
    /// </summary>
    private List<string> NeededActions(Figure fig, IReadOnlyList<string> kinds)
    {
        var list = new List<string> { ResolveAction("", kinds) };
        foreach (var raw in new[] { fig.Activity, fig.WantedClip.Kind, fig.CurrentKind })
            if (raw.Length > 0) list.Add(ResolveAction(raw, kinds));
        if (fig.CurrentClip.Length > 0 && kinds.Contains(fig.CurrentClip)) list.Add(fig.CurrentClip);
        if (fig.Pair is { } pair && kinds.Contains(pair.Clip)) list.Add(pair.Clip);
        return list.Where(a => a.Length > 0).Distinct().ToList();
    }

    /// <summary>
    /// Fit what <paramref name="fig"/> needs on <paramref name="t"/> BEFORE the body is shown (<see cref="NeededActions"/>),
    /// so its first frame plays what it should; completed at once when all of it is in (or in the synchronous modes).
    /// </summary>
    private Task PrepareAsync(Figure fig, ModelTemplate t)
        => t.Lazy is { } lazy ? lazy.EnsureAsync(NeededActions(fig, t.Kinds)) : Task.CompletedTask;

    // ---- the main-thread budget of the lazy clip fit (Task 35b) ------------------------------------------------------

    /// <summary>Main-thread milliseconds the lazy clip fits may take per frame together; a turn that would start beyond it waits a frame.</summary>
    public const double ClipBudgetMs = 4;
    private ulong _budgetFrame = ulong.MaxValue;
    private double _budgetUsedMs;

    /// <summary>
    /// Wait for a main-thread turn of the lazy clip fit: at once while this frame's budget (<see cref="ClipBudgetMs"/>) is
    /// not used up, else from the next frame on. False when the manager is gone (the fit stops).
    /// </summary>
    internal async Task<bool> MainTurn()
    {
        while (true)
        {
            if (!IsInstanceValid(this)) return false;
            if (!IsInsideTree()) return true;   // no frames to wait for (a manager outside the tree fits at once)
            ulong frame = Engine.GetProcessFrames();
            if (frame != _budgetFrame)
            {
                _budgetFrame = frame;
                _budgetUsedMs = 0;
            }
            if (_budgetUsedMs < ClipBudgetMs) return true;
            await NextFrame();
        }
    }

    /// <summary>A main-thread turn of the lazy clip fit took <paramref name="ms"/>.</summary>
    internal void ChargeMain(double ms, string what)
    {
        _budgetUsedMs += ms;
        if (ms <= LongestClipTurnMs) return;
        LongestClipTurnMs = ms;
        LongestClipTurn = what;
    }

    /// <summary>The longest body swap (template duplicated, player and body set up) so far, ms — main thread.</summary>
    public double LongestInstantiateMs { get; private set; }

    /// <summary>Which step the longest main-thread turn was (write, relock sampling / write-back, ground sampling, add to library).</summary>
    public string LongestClipTurn { get; private set; } = "";

    /// <summary>Every clip fit so far (build and on demand), and the longest main-thread turn of a lazy fit (ms).</summary>
    public List<ClipFitTime> ClipFits { get; } = new();
    public double LongestClipTurnMs { get; private set; }

    internal void RecordFit(ClipFitTime t) => ClipFits.Add(t);

    /// <summary>
    /// A model file's own non-empty takes, lower-cased, taken out of the import's AnimationPlayer (which is freed: the
    /// figure's one player carries them). The loop flag is the server's for the EXACT take name
    /// (<c>applyEmbeddedClipLoops</c>); a take nobody flagged loops.
    ///
    /// <b>FBX takes are completed</b> (<paramref name="fbx"/>): Godot's FBX import drops every curve that equals the
    /// node's imported default (measured on fixtures/animals: walk keeps 4 of the 30 baked bone curves, a take whose
    /// curves are all constant arrives EMPTY) and keeps that default as the bone's pose. three's FBXLoader keeps every
    /// baked curve, so a take there poses EVERY bone — and switching from walk to sit puts the front hips back, where
    /// Godot's mixer would leave the last walk value standing (16° measured). So each FBX take gets a one-key constant
    /// track of the imported default for every bone position / rotation / scale it lacks (as <see cref="ClipLibrary"/>
    /// does for the library clips), and an FBX take is kept even when the import left it without a track.
    /// </summary>
    private static List<(string Kind, Animation Anim)> TakeOwnClips(Node root, IReadOnlyDictionary<string, bool>? loops = null,
                                                                   bool fbx = false)
    {
        var list = new List<(string, Animation)>();
        foreach (var player in Walk(root).OfType<AnimationPlayer>().ToList())
        {
            var origin = player.GetNodeOrNull(player.RootNode);
            var skel = ClipLibrary.Find<Skeleton3D>(root);
            string? skelPath = fbx && origin is not null && skel is not null ? origin.GetPathTo(skel).ToString() : null;
            foreach (var libName in player.GetAnimationLibraryList())
            {
                var lib = player.GetAnimationLibrary(libName);
                foreach (var name in lib.GetAnimationList())
                {
                    var anim = lib.GetAnimation(name);
                    if (anim.GetTrackCount() == 0 && skelPath is null) continue;
                    var kind = name.ToString().ToLowerInvariant();
                    if (list.Any(e => e.Item1 == kind)) continue;
                    var copy = (Animation)anim.Duplicate();
                    if (skelPath is not null) CompleteFbxTake(copy, skel!, skelPath);
                    bool loop = loops is null || !loops.TryGetValue(name.ToString(), out var l) || l;
                    copy.LoopMode = loop ? Animation.LoopModeEnum.Linear : Animation.LoopModeEnum.None;
                    list.Add((kind, copy));
                }
            }
            player.GetParent()?.RemoveChild(player);
            player.Free();
        }
        return list;
    }

    /// <summary>
    /// The constant tracks Godot dropped from an FBX take: for every bone of <paramref name="skel"/> and each of
    /// position / rotation / scale the take does not key, one key at 0 s holding the bone's imported pose. Returns how
    /// many tracks were added.
    /// </summary>
    public static int CompleteFbxTake(Animation anim, Skeleton3D skel, string skelPath)
    {
        var have = new HashSet<(string, Animation.TrackType)>();
        for (int t = 0; t < anim.GetTrackCount(); t++) have.Add((anim.TrackGetPath(t).ToString(), anim.TrackGetType(t)));
        int added = 0;
        for (int b = 0; b < skel.GetBoneCount(); b++)
        {
            var path = $"{skelPath}:{skel.GetBoneName(b)}";
            if (!have.Contains((path, Animation.TrackType.Position3D)))
            {
                int t = anim.AddTrack(Animation.TrackType.Position3D);
                anim.TrackSetPath(t, path);
                anim.PositionTrackInsertKey(t, 0, skel.GetBonePosePosition(b));
                added++;
            }
            if (!have.Contains((path, Animation.TrackType.Rotation3D)))
            {
                int t = anim.AddTrack(Animation.TrackType.Rotation3D);
                anim.TrackSetPath(t, path);
                anim.RotationTrackInsertKey(t, 0, skel.GetBonePoseRotation(b));
                added++;
            }
            if (!have.Contains((path, Animation.TrackType.Scale3D)))
            {
                int t = anim.AddTrack(Animation.TrackType.Scale3D);
                anim.TrackSetPath(t, path);
                anim.ScaleTrackInsertKey(t, 0, skel.GetBonePoseScale(b));
                added++;
            }
        }
        return added;
    }

    /// <summary>Built templates and the keys of their retargeted clips (both tiers of every character).</summary>
    public int TemplateCount => _templates.Values.Count(t => t.IsCompletedSuccessfully);
    public long TemplateKeys => _templates.Values.Where(t => t.IsCompletedSuccessfully).Sum(t => t.Result.Keys);
    /// <summary>Keys actually held by the templates and the fallback pool: every distinct bound Animation once (a clip shared by
    /// <see cref="ShareIdentical"/> counts once).</summary>
    public long UniqueClipKeys => _templates.Values.Where(t => t.IsCompletedSuccessfully).Select(t => t.Result)
                                            .Concat(_pool.Select(p => p.Template))
                                            .SelectMany(t => t.AnimKeys).DistinctBy(kv => kv.Key).Sum(kv => kv.Value);
    /// <summary>Planned library clips (behind an action) of all templates, the ones fitted so far and their keys (Task 35b).</summary>
    public int PlannedClipCount => LiveLazies().Sum(l => l.FittableClips);
    public int FittedClipCount => LiveLazies().Sum(l => l.FittedClips);
    public long FittedClipKeys => LiveLazies().Sum(l => l.AnimKeys.Values.Sum());
    private IEnumerable<TemplateClips> LiveLazies()
        => _templates.Values.Where(t => t.IsCompletedSuccessfully && t.Result.Lazy is not null).Select(t => t.Result.Lazy!);
    /// <summary>Bound clips that templates took over from earlier ones instead of keeping a copy.</summary>
    public int SharedClipCount => _templates.Values.Where(t => t.IsCompletedSuccessfully).Sum(t => t.Result.SharedClips);
    /// <summary>The estimated clip memory of all templates in MiB (<see cref="UniqueClipKeys"/> × <see cref="KeyBytes"/>).</summary>
    public double ClipMemMiB => UniqueClipKeys * KeyBytes / 1048576.0;
    /// <summary>Fit times (ms) of the templates that fitted the library, in build order.</summary>
    public List<double> FitTimes => _templates.Values.Where(t => t.IsCompletedSuccessfully && t.Result.Keys > 0)
                                              .Select(t => t.Result.FitMs).ToList();
    /// <summary>
    /// The bench result's figure keys (Task 35), after the stream keys: <c>figures</c> (on the map), <c>figuresAnimated</c>
    /// (moving every frame, <see cref="FiguresAnimated"/>) and <c>clipMemMiB</c> (<see cref="ClipMemMiB"/>, one decimal).
    /// </summary>
    public void AddBenchKeys(System.Text.Json.Nodes.JsonObject result)
    {
        result["figures"] = _figures.Count;
        result["figuresAnimated"] = FiguresAnimated;
        result["clipMemMiB"] = Math.Round(ClipMemMiB, 1);
    }

    /// <summary>Figures whose body moves every frame: a clip player, or a clip-less rig walking procedurally.</summary>
    public int FiguresAnimated => _figures.Values.Count(f => IsInstanceValid(f) && f.Animates);

    /// <summary>
    /// Bytes one retargeted key costs in Godot's static memory, MEASURED (Task 35, <see cref="ProbeClipMemory"/> on the
    /// world copy: one male template, 109 clips, 320 063 keys, 10.90 MiB freed = 35.7 B/key; 41.4 B/key before the
    /// one-call key writer, <see cref="KeyWriter"/>): the 32 B of a <c>TKey&lt;Quaternion&gt;</c> plus each track's own
    /// header. The release export has no static-memory monitor, so the bench's <c>clipMemMiB</c> is keys × this.
    /// </summary>
    public const long KeyBytes = 36;

    /// <summary>
    /// Bound clips by <see cref="BoundClip.Digest"/>: the first template that produced a clip keeps it here, and every later
    /// template whose retarget comes out bit-identical (same rig rests, corrections, hips frame and standing reference — the
    /// same model at another height or set chain, the fallback pool's models) plays that same <see cref="Animation"/>
    /// instead of a copy. The two tiers of ONE model do not match: the server's low bake moves the rests by ~1e-6 and the
    /// fitted clips then differ by up to 2.5° on a bone (measured on the world copy) — a near-match would change what
    /// plays. Root-motion clips never enter: the bridge fit rewrites them per template (<see cref="BridgeFit.WriteBack"/>).
    /// </summary>
    private readonly Dictionary<string, Animation> _sharedClips = new(StringComparer.Ordinal);

    /// <summary>
    /// The clip-memory reduction of ruling P3-R11 (Task 35): a freshly retargeted clip whose digest an earlier template
    /// already holds is dropped and that template's <see cref="Animation"/> is bound instead — the same keys bit for bit,
    /// so nothing that plays changes. Returns the clip to bind; <paramref name="shared"/> says whether it was taken over.
    /// </summary>
    internal BoundClip ShareIdentical(BoundClip b, ref bool shared)
    {
        shared = false;
        if (b.RootPath is not null || b.Digest is not { } digest || b.Anim is null) return b;
        if (_sharedClips.TryGetValue(digest, out var held) && IsInstanceValid(held))
        {
            b.Anim.Dispose();
            shared = true;
            return b with { Anim = held };
        }
        _sharedClips[digest] = b.Anim;
        return b;
    }

    /// <summary>Check helper (Task 35b, <c>--check clips</c>): the lazy clip fitter of the template <paramref name="name"/>'s body shows.</summary>
    public TemplateClips? ClipsOf(string name)
        => _figures.TryGetValue(name, out var f) && f.LoadedUrl is { } url
           && _templates.TryGetValue(TemplateKey(url, f.Sets, f.HeightM), out var t) && t.IsCompletedSuccessfully ? t.Result.Lazy : null;

    /// <summary>
    /// Check helper (Task 35, <c>--check pairs</c> Q9): <paramref name="name"/>'s model fitted once more at
    /// <paramref name="heightM"/> (a template of its own: the height is part of the key). Returns the action count, how
    /// many actions play the very same Animation object as the figure's own template, how many of those that differ are
    /// root-motion clips (re-locked at the new scale, never shared), and the new template's shared-clip count.
    /// </summary>
    public async Task<(int Actions, int SameObject, int RootMotionOwn, int OtherOwn, int SharedClips)> RefitAtHeightForCheck(string name, double heightM)
    {
        var fig = _figures[name];
        var info = _infos[name];
        var a = await GetTemplate(info.Url, info, fig.Sets, fig.HeightM);
        var b = await GetTemplate(info.Url, info, fig.Sets, heightM);
        // Both libraries whole (Task 35b: a template holds only what was played): the first before the second, as the
        // eager fit built them.
        await (a.Lazy?.EnsureAllAsync() ?? Task.CompletedTask);
        await (b.Lazy?.EnsureAllAsync() ?? Task.CompletedTask);
        int same = 0, rootOwn = 0, otherOwn = 0;
        foreach (var kind in b.Kinds)
        {
            var anim = b.Library!.GetAnimation(kind);
            if (a.Library!.HasAnimation(kind) && a.Library.GetAnimation(kind).GetInstanceId() == anim.GetInstanceId()) same++;
            else if (b.Extras.TryGetValue(anim, out var x) && x.Path is not null) rootOwn++;
            else otherOwn++;
        }
        return (b.Kinds.Count, same, rootOwn, otherOwn, b.SharedClips);
    }

    /// <summary>
    /// Check helper (Task 35, <c>--check pairs</c> Q9): every library clip of <paramref name="name"/>'s template retargeted
    /// twice — through <see cref="KeyWriter"/>'s one-call path and key by key (<see cref="KeyWriter.ForceInsert"/>) — and
    /// compared bit for bit (track type, path, interpolation, key count, time, transition, value), with Godot's static
    /// memory each set of Animations gives back when freed (0 without the debug monitor).
    /// </summary>
    public (int Clips, int Tracks, long Keys, int Mismatches, string FirstMismatch, long BulkBytes, long InsertBytes) CompareKeyWritersForCheck(string name)
    {
        var fig = _figures[name];
        var info = _infos[name];
        var t = _templates[TemplateKey(fig.LoadedUrl ?? info.Url, fig.Sets, fig.HeightM)].Result;
        var skel = ClipLibrary.Find<Skeleton3D>(t.Root)!;
        var candidates = Clips.ClipsFor(t.Sets);
        var fixes = Clips.DonorRest is { } donor ? RestAdapter.Build(donor, t.Root, skel) : null;
        var (standRef, standSource) = Clips.StandingReference(candidates);
        List<Animation> Fit(bool insert)
        {
            KeyWriter.ForceInsert = insert;
            try
            {
                return candidates.Select(c => ClipLibrary.Retarget(c, t.Root, skel, fixes, standRef ?? 0, standSource == "rig").Anim)
                                 .OfType<Animation>().ToList();
            }
            finally { KeyWriter.ForceInsert = false; }
        }
        long Free(List<Animation> anims)
        {
            ulong before = OS.GetStaticMemoryUsage();
            foreach (var x in anims) x.Dispose();
            return (long)before - (long)OS.GetStaticMemoryUsage();
        }
        var bulk = Fit(false);
        var insert = Fit(true);
        int tracks = 0, bad = 0;
        long keys = 0;
        string first = "";
        void Bad(string what)
        {
            bad++;
            if (first.Length == 0) first = what;
        }
        for (int c = 0; c < Math.Min(bulk.Count, insert.Count); c++)
        {
            Animation x = bulk[c], y = insert[c];
            if (x.GetTrackCount() != y.GetTrackCount() || x.Length != y.Length || x.LoopMode != y.LoopMode) { Bad($"clip {c} header"); continue; }
            for (int tr = 0; tr < x.GetTrackCount(); tr++)
            {
                tracks++;
                int n = x.TrackGetKeyCount(tr);
                if (x.TrackGetType(tr) != y.TrackGetType(tr) || x.TrackGetPath(tr) != y.TrackGetPath(tr)
                    || x.TrackGetInterpolationType(tr) != y.TrackGetInterpolationType(tr) || n != y.TrackGetKeyCount(tr))
                {
                    Bad($"clip {c} track {tr} header");
                    continue;
                }
                for (int k = 0; k < n; k++)
                {
                    keys++;
                    if (BitConverter.DoubleToInt64Bits(x.TrackGetKeyTime(tr, k)) != BitConverter.DoubleToInt64Bits(y.TrackGetKeyTime(tr, k))
                        || x.TrackGetKeyTransition(tr, k) != y.TrackGetKeyTransition(tr, k)
                        || !SameBits(x.TrackGetKeyValue(tr, k), y.TrackGetKeyValue(tr, k)))
                        Bad($"clip {c} track {x.TrackGetPath(tr)} key {k}");
                }
            }
        }
        if (bulk.Count != insert.Count) Bad($"{bulk.Count} vs {insert.Count} clips");
        int clips = bulk.Count;
        long bulkBytes = Free(bulk), insertBytes = Free(insert);
        return (clips, tracks, keys, bad, first, bulkBytes, insertBytes);
    }

    private static bool SameBits(Variant a, Variant b) => a.VariantType == b.VariantType && a.VariantType switch
    {
        Variant.Type.Quaternion => Bits(a.AsQuaternion()) == Bits(b.AsQuaternion()),
        Variant.Type.Vector3 => Bits(a.AsVector3()) == Bits(b.AsVector3()),
        _ => a.Equals(b),
    };

    private static (int, int, int, int) Bits(Quaternion q)
        => (BitConverter.SingleToInt32Bits(q.X), BitConverter.SingleToInt32Bits(q.Y), BitConverter.SingleToInt32Bits(q.Z), BitConverter.SingleToInt32Bits(q.W));

    private static (int, int, int, int) Bits(Vector3 v)
        => (BitConverter.SingleToInt32Bits(v.X), BitConverter.SingleToInt32Bits(v.Y), BitConverter.SingleToInt32Bits(v.Z), 0);

    /// <summary>
    /// Task 35's memory probe (offline only, needs the debug engine's static-memory monitor): re-runs the retarget of the
    /// first fitted template synchronously and reads Godot's static memory around it — what the new Animations hold
    /// (allocated) and what disposing them gives back (freed). Null when no fitted template exists.
    /// </summary>
    public (long Allocated, long Freed, long Keys, int Clips)? ProbeClipMemory()
    {
        var t = _templates.Values.Where(x => x.IsCompletedSuccessfully && x.Result.Keys > 0).Select(x => x.Result).FirstOrDefault();
        if (t is null || ClipLibrary.Find<Skeleton3D>(t.Root) is not { } skel) return null;
        var candidates = Clips.ClipsFor(t.Sets);
        var fixes = Clips.DonorRest is { } donor ? RestAdapter.Build(donor, t.Root, skel) : null;
        var (standRef, standSource) = Clips.StandingReference(candidates);
        GC.Collect();
        GC.WaitForPendingFinalizers();
        ulong before = OS.GetStaticMemoryUsage();
        var made = new List<Animation>();
        long keys = 0;
        foreach (var clip in candidates)
        {
            var b = ClipLibrary.Retarget(clip, t.Root, skel, fixes, standRef ?? 0, standSource == "rig");
            if (b.Anim is null) continue;
            made.Add(b.Anim);
            keys += b.Keys;
        }
        ulong after = OS.GetStaticMemoryUsage();
        foreach (var a in made) a.Dispose();
        ulong freed = OS.GetStaticMemoryUsage();
        return ((long)after - (long)before, (long)after - (long)freed, keys, made.Count);
    }


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

    /// <summary>
    /// A model's separate texture (<c>textureLoader.loadAsync(info.textureUrl)</c>): decoded, its rows flipped once
    /// (see <see cref="DressInTexture"/>), mipmapped like three's. A download or decode failure throws — the model load
    /// fails and retries like any transient error.
    /// </summary>
    private async Task<ImageTexture> LoadTexture(string url)
    {
        var bytes = await _source.GetBytesAsync(url);
        var img = Portrait.Decode(bytes) ?? throw new InvalidOperationException($"texture {url}: not a PNG/JPEG/WebP");
        return FbxTexture(img);
    }

    /// <summary>
    /// The texture image as an FBX body samples it. Godot's FBX import turns the file's UV v into 1 − v (measured on
    /// fixtures/animals: (0.375, 0.1875) arrives as (0.375, 0.8125)); three's FBXLoader keeps v, and the browser draws the
    /// texture with <c>flipY = false</c>, so v = 0 is the image's TOP row. Flipping the rows once makes Godot's
    /// v' = 1 − v land on the texel three samples: y' = (1 − v)·H in the flipped image is y = v·H in the original.
    /// </summary>
    public static ImageTexture FbxTexture(Image img)
    {
        if (img.IsCompressed()) img.Decompress();
        img.FlipY();
        img.GenerateMipmaps();
        return ImageTexture.CreateFromImage(img);
    }

    /// <summary>
    /// figures.ts <c>buildModel</c> with a <c>texture_url</c>: every mesh gets <c>MeshStandardMaterial({map, roughness:
    /// 0.85, metalness: 0})</c> — here a StandardMaterial3D per mesh with the shared texture as albedo (sRGB, like three's
    /// <c>SRGBColorSpace</c>), clamped at the edges (three's default wrap), plus the browser look every figure mesh has
    /// (Lambert diffuse, no received shadows; <see cref="GlbLoader.BrowserLook"/>). Returns the meshes dressed.
    /// </summary>
    public static int DressInTexture(Node root, Texture2D texture)
    {
        int n = 0;
        foreach (var mi in Walk(root).OfType<MeshInstance3D>())
        {
            if (mi.Mesh is null) continue;
            var mat = new StandardMaterial3D
            {
                AlbedoTexture = texture, Roughness = 0.85f, Metallic = 0, TextureRepeat = false,
                DiffuseMode = BaseMaterial3D.DiffuseModeEnum.Lambert, DisableReceiveShadows = true,
            };
            mi.MaterialOverride = null;
            for (int s = 0; s < mi.Mesh.GetSurfaceCount(); s++) mi.SetSurfaceOverrideMaterial(s, mat);
            n++;
        }
        return n;
    }

    /// <summary>An FBX without a texture keeps its own materials in the browser look (Lambert, no received shadows).</summary>
    private static void BrowserLook(Node root)
    {
        foreach (var mi in Walk(root).OfType<MeshInstance3D>())
            for (int s = 0; s < (mi.Mesh?.GetSurfaceCount() ?? 0); s++)
                if (mi.GetActiveMaterial(s) is BaseMaterial3D b)
                {
                    b.DiffuseMode = BaseMaterial3D.DiffuseModeEnum.Lambert;
                    b.DisableReceiveShadows = true;
                }
    }

    /// <summary>Every BaseMaterial3D under a body with a non-zero metallic (the check's probe).</summary>
    public static int MetallicMaterials(Node root)
        => Walk(root).OfType<MeshInstance3D>()
                     .SelectMany(mi => Enumerable.Range(0, mi.Mesh?.GetSurfaceCount() ?? 0).Select(s => mi.GetActiveMaterial(s)))
                     .OfType<BaseMaterial3D>().Count(m => m.Metallic != 0);

    private void Instantiate(Figure fig, ModelTemplate t, ModelInfo info, FigureTier tier, double? poolHeight = null)
    {
        if (!IsInstanceValid(t.Root)) return;   // retired meanwhile (RetireStaleTemplates): the next poll loads the new model
        var dupWatch = System.Diagnostics.Stopwatch.StartNew();
        var inst = (Node3D)t.Root.Duplicate();
        double scale = poolHeight is { } ph ? ph / t.RawHeight : info.Normalized ? 1.0 : fig.HeightM / t.RawHeight;
        var body = new Node3D { Name = "Body", Scale = Vector3.One * (float)scale };
        body.AddChild(inst);
        AnimationPlayer? player = null;
        if (t.Library is not null)
        {
            // MANUAL: the figure advances its own player in UpdateFigure (three's mixer.update in Figure.update), so the
            // pose and a bridge's root motion are computed in the same frame.
            player = new AnimationPlayer { Name = "Anim", CallbackModeProcess = AnimationMixer.AnimationCallbackModeProcess.Manual };
            inst.AddChild(player);   // root_node ".." = the model root the track paths start from
            player.AddAnimationLibrary("", t.Library);
        }
        fig.BoundTracks = t.BoundTracks;
        fig.UnboundClips = t.Unbound;
        fig.ClipSets = t.ClipSets;
        fig.ClipKeys = t.Keys;
        fig.ClipBytesOf = () => t.ClipBytes;
        // A clip of the plan that is not fitted yet is asked for here (Task 35b) — set before SetBody plays the first one.
        fig.FitClip = t.Lazy is { } lazy ? lazy.Request : null;
        fig.Poses = Clips.Poses;
        fig.Transitions = Clips.Transitions;
        fig.Extras = t.Extras;
        fig.BaseScale = scale;
        fig.Clock = () => _clock;
        fig.LoadedUrl = t.Url;
        fig.LoadedTier = tier;
        // figures.ts Figure constructor: the body centred on its bind box in XZ, its lowest point on the root (P3-R14);
        // the box itself (scaled, before that shift — `findLegChains(inst, box)`) and `model.height` feed the gait.
        V3? bind = t.BindBox is { } bb ? FigureBind.Offset(bb.Min, bb.Max, scale) : null;
        GaitBox? box = t.BindBox is { } b2 ? new GaitBox(b2.Min * scale, b2.Max * scale) : null;
        fig.SetBody(body, true, ClipLibrary.Find<Skeleton3D>(inst), player, t.Library is null ? null : t.Kinds, bind,
                    box, t.RawHeight * scale);
        LongestInstantiateMs = Math.Max(LongestInstantiateMs, dupWatch.Elapsed.TotalMilliseconds);
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
        _ = PrepareAsync(fig, model.Template);   // the pool body is shown now; its activity follows once fitted (Task 35b)
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
                    double poolHeight = Json.Num(m, "height", defaultHeight);
                    var template = await BuildTemplate(url, info, Array.Empty<string>(), poolHeight);
                    _pool.Add(new PoolModel(name, template, info, poolHeight, assignOnly));
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
    /// and an unskinned part (the portrait's quad) as stored. A sphere around each figure
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

    internal static IEnumerable<Node> Walk(Node n)
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
