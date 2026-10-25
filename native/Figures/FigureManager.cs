using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;
using AnimaNative.Api;
using AnimaNative.Gltf;
using AnimaNative.World;
using Godot;
using Json = AnimaNative.World.Json;

namespace AnimaNative.Figures;

/// <summary>Counts for the log line and the check.</summary>
public sealed class FigureStats
{
    public int Figures, GlbFigures, Placeholders, ClipsLoaded, ClipsFailed, BoundTracks, UnboundClips;
    public int ModelLoads, ModelFailures, Offmap, Polls;

    public string Summary() =>
        $"figures={Figures} glb_figures={GlbFigures} placeholders={Placeholders} clips_loaded={ClipsLoaded} "
        + $"bound_tracks={BoundTracks} unbound_clips={UnboundClips} model_loads={ModelLoads} "
        + $"model_failures={ModelFailures} offmap={Offmap} clip_failures={ClipsFailed}";
}

/// <summary>
/// The figures of <c>GET /play/worldmap</c> on the open map (Task S1b).
///
///   • which and where: <see cref="FigurePlacement.Resolve"/> (the browser's far view);
///     y = <see cref="WorldHeight.GroundAt"/> at the shown point, every frame;
///   • polled every <see cref="PollSeconds"/> s (online); new/vanished
///     characters are added/removed; a moved target lerps in over the interval;
///   • model: <c>GET /characters/{name}/model3d</c> → <c>model.url</c> used
///     unchanged (§ A7); a GLB is Meshopt-decoded and imported once per URL and
///     duplicated per figure; FBX (generic rig) and "no model" (404, or
///     <c>model</c> null) are capsule placeholders; reloaded when the row's
///     <c>model_sig</c> changes (§ A11a);
///   • scale: <c>normalized</c> → 1, else height / raw bounding-box height,
///     height = <c>height_cm</c>/100 when 30 &lt; cm &lt; 400, else the last
///     known one, default 1.70 m (figures.ts <c>setCharacterHeight</c>,
///     <c>BASE_FIGURE_HEIGHT_M</c>, <c>buildModel</c>; a Z-up export is stood up
///     first like there);
///   • clips: idle + walk from <see cref="ClipLibrary"/>, retargeted once per
///     model URL and shared by its figures; only a <c>mixamo</c> rig gets them.
/// </summary>
public partial class FigureManager : Node3D
{
    public const double DefaultHeightM = 1.70;
    public double PollSeconds { get; set; } = 5.0;
    /// <summary>false in <c>--check</c>: time only moves through <see cref="Tick"/>.</summary>
    public bool AutoTick { get; set; } = true;

    private readonly IWorldSource _source;
    private readonly WorldHeight _height;
    private readonly Action<string> _log;
    private readonly bool _strict;
    private readonly Dictionary<string, Figure> _figures = new();
    private readonly Dictionary<string, Task<ModelTemplate>> _templates = new();
    /// <summary>At most 4 model requests at a time (the browser's clip queue uses the same width).</summary>
    private readonly SemaphoreSlim _net = new(4);

    public ClipLibrary Clips { get; }
    public FigureStats Stats { get; } = new();
    public IReadOnlyDictionary<string, Figure> Figures => _figures;

    private sealed class ModelTemplate
    {
        public required Node3D Root { get; init; }
        public required double RawHeight { get; init; }
        public AnimationLibrary? Library { get; init; }
        public int BoundTracks { get; init; }
        public int Unbound { get; init; }
        /// <summary>Bones with a rest correction; −1 = no rig (verbatim copy).</summary>
        public int Corrected { get; init; }
    }

    private sealed record ModelInfo(string Url, string Format, string Rig, bool Normalized);

    public FigureManager(IWorldSource source, WorldHeight height, Action<string> log, bool strict)
    {
        Name = "Figures";
        _source = source;
        _height = height;
        _log = log;
        _strict = strict;
        Clips = new ClipLibrary(source, log);
    }

    /// <summary>Clip list + idle/walk import. A missing list leaves every figure in bind pose (online).</summary>
    public async Task InitAsync()
    {
        try { await Clips.LoadRolesAsync(); }
        catch (Exception e) when (!_strict) { _log($"clips: list failed: {e.Message} — figures stay in bind pose"); }
        Stats.ClipsLoaded = Clips.ClipsLoaded;
        Stats.ClipsFailed = Clips.ClipsFailed;
    }

    private readonly TaskCompletionSource _firstPoll = new(TaskCreationOptions.RunContinuationsAsynchronously);

    /// <summary>
    /// Completes when the FIRST poll's figures and the model loads it started
    /// are done (failed loads included — they are counted, not awaited again).
    /// The bench (S2) starts after it.
    /// </summary>
    public Task FirstPollDone => _firstPoll.Task;

    /// <summary>The latest polled <c>/play/worldmap</c> payload (null before the first poll) — the bench anchor's snapshot.</summary>
    public JsonElement? LatestMap { get; private set; }

    /// <summary>The last poll failed (the HUD's <c>connection: 'lost'</c>); false after the next good one.</summary>
    public bool LastPollFailed { get; private set; }

    /// <summary>Counts finished polls (good or failed) — lets a reader see that <see cref="LatestMap"/> was renewed.</summary>
    public int PollSerial { get; private set; }

    /// <summary>Online: poll the world map forever (until <paramref name="ct"/>).</summary>
    public async Task PollLoopAsync(CancellationToken ct)
    {
        while (!ct.IsCancellationRequested)
        {
            try
            {
                using var doc = await _source.GetWorldMapAsync();
                // Back to the title while the request ran: this node may be freed already.
                if (ct.IsCancellationRequested) break;
                bool first = LatestMap is null;
                LatestMap = doc.RootElement.Clone();
                LastPollFailed = false;
                PollSerial++;
                var loads = Apply(doc.RootElement);
                if (first)
                    _ = loads.ContinueWith(_ => _firstPoll.TrySetResult(), TaskScheduler.Default);
            }
            catch (Exception e)
            {
                if (ct.IsCancellationRequested) break;   // the session ended on purpose (back to the title)
                _log($"worldmap poll failed: {e.Message}");
                LastPollFailed = true;
                PollSerial++;
                _firstPoll.TrySetResult();  // nothing to wait for; the bench runs on what is there
            }
            try { await Task.Delay(TimeSpan.FromSeconds(PollSeconds), ct); }
            catch (TaskCanceledException) { break; }
        }
    }

    /// <summary>
    /// One world-map payload: resolve the spots, add/move/remove figures and
    /// start model (re)loads. Reads the JSON synchronously; the returned task
    /// completes when the loads it started are done (the check awaits it, the
    /// poll loop does not).
    /// </summary>
    public Task Apply(JsonElement root)
    {
        Stats.Polls++;
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
            fig!.Rule = spot.Rule;
            fig.SetTarget(at, PollSeconds, snap: fresh);
            fig.Advance(0, _height.GroundAt);
            if (fresh)
            {
                fig.SetBody(Figure.Capsule(fig.HeightM), false, null, null);
                fig.WantedSig = row.ModelSig;
                loads.Add(LoadModelAsync(fig));
            }
            else if (row.ModelSig != fig.WantedSig)
            {
                fig.WantedSig = row.ModelSig;
                if (!fig.Loading) loads.Add(LoadModelAsync(fig));
            }
        }
        foreach (var gone in _figures.Keys.Where(n => !spots.ContainsKey(n)).ToList())
        {
            _figures[gone].QueueFree();
            _figures.Remove(gone);
        }
        UpdateStats();
        return Task.WhenAll(loads);
    }

    public void Tick(double dt)
    {
        foreach (var fig in _figures.Values) fig.Advance(dt, _height.GroundAt);
    }

    public override void _Process(double delta)
    {
        if (AutoTick) Tick(delta);
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

    private async Task LoadModelAsync(Figure fig)
    {
        fig.Loading = true;
        var sig = fig.WantedSig;
        try
        {
            var info = await FetchInfo(fig.CharacterName);
            if (!Alive(fig)) return;   // vanished while loading
            if (info is null)
            {
                fig.SetBody(Figure.Capsule(fig.HeightM), false, null, null);
                fig.BoundTracks = 0;
                fig.UnboundClips = 0;
                _log($"figure {fig.CharacterName}: no model → placeholder");
            }
            else if (info.Format != "glb")
            {
                // Generic rig: FBX + separate texture (§ A7). Spike: placeholder.
                fig.SetBody(Figure.Capsule(fig.HeightM), false, null, null);
                fig.BoundTracks = 0;
                fig.UnboundClips = 0;
                _log($"figure {fig.CharacterName}: {info.Format}/{info.Rig} model → placeholder");
            }
            else
            {
                var template = await GetTemplate(info);
                if (!Alive(fig)) return;
                Instantiate(fig, template, info);
            }
            Stats.ModelLoads++;
        }
        catch (Exception e) when (!_strict)
        {
            Stats.ModelFailures++;
            _log($"figure {fig.CharacterName}: model failed: {e.Message} → placeholder");
        }
        finally
        {
            fig.LoadedSig = sig;
            fig.Loading = false;
            if (IsInstanceValid(this)) UpdateStats();
        }
        if (Alive(fig) && fig.WantedSig != sig) await LoadModelAsync(fig);
    }

    /// <summary>Still the figure shown for its character (not removed, not replaced by a new one of that name).</summary>
    private bool Alive(Figure fig)
        => IsInstanceValid(fig) && _figures.TryGetValue(fig.CharacterName, out var cur) && ReferenceEquals(cur, fig);

    /// <summary><c>getCharacterModel</c> (api.ts): null for 404 or a payload without <c>model.url</c>.</summary>
    private async Task<ModelInfo?> FetchInfo(string name)
    {
        JsonDocument? fetched;
        await _net.WaitAsync();
        try { fetched = await _source.GetCharacterModelAsync(name); }
        finally { _net.Release(); }
        using var doc = fetched;
        if (doc is null) return null;
        var root = doc.RootElement;
        if (root.ValueKind != JsonValueKind.Object || !root.TryGetProperty("model", out var m)
            || m.ValueKind != JsonValueKind.Object) return null;
        var url = Json.Str(m, "url");
        if (url.Length == 0) return null;
        var rig = Json.Str(m, "rig");
        if (rig.Length == 0) rig = Json.Str(root, "rig", "mixamo");
        return new ModelInfo(url, Json.Str(m, "format", "glb").ToLowerInvariant(), rig, Json.Bool(m, "normalized"));
    }

    private Task<ModelTemplate> GetTemplate(ModelInfo info)
    {
        if (!_templates.TryGetValue(info.Url, out var task) || task.IsFaulted)
            _templates[info.Url] = task = BuildTemplate(info);
        return task;
    }

    private async Task<ModelTemplate> BuildTemplate(ModelInfo info)
    {
        byte[] bytes;
        await _net.WaitAsync();
        try { bytes = await _source.GetBytesAsync(info.Url); }
        finally { _net.Release(); }
        var plain = await Task.Run(() => GlbLoader.Prepare(bytes));
        var (root, _) = GlbLoader.Import(plain, info.Url);
        root.Name = "Model";
        var size = ModelPlacement.Measure(root, Transform3D.Identity).Size;
        if (size.Z > size.Y * 1.5f)   // stand a Z-up export upright (buildModel)
        {
            root.Rotation = new Vector3(-Mathf.Pi / 2f, 0, 0);
            size = ModelPlacement.Measure(root, Transform3D.Identity).Size;
        }
        double raw = Math.Max(size.Y, 0.01);
        var skel = ClipLibrary.Find<Skeleton3D>(root);
        AnimationLibrary? lib = null;
        int bound = 0, unbound = 0, corrected = -1;
        if (info.Rig == "mixamo" && skel is not null && skel.GetBoneCount() > 0)
        {
            await Clips.WaitRolesAsync();
            // The browser's rest-pose correction against the reference rig
            // (restCorrections, built once per model like fitLibraryAsync does).
            var fixes = Clips.DonorRest is { } donor ? RestCorrections.Build(donor, root, skel) : null;
            corrected = fixes?.Count ?? -1;
            lib = new AnimationLibrary();
            foreach (var role in ClipLibrary.Roles)
            {
                var clip = Clips.ByRole.GetValueOrDefault(role);
                var b = clip is null ? new BoundClip(role, null, 0) : Clips.Retarget(clip, root, skel, fixes);
                if (b.Anim is null)
                {
                    unbound++;
                    _log($"model {info.Url}: clip '{role}' not bound ({b.Tracks} tracks) — bind pose for that role");
                    continue;
                }
                lib.AddAnimation(role, b.Anim);
                bound += b.Tracks;
            }
            _log($"model {info.Url}: {skel.GetBoneCount()} bones, raw height {raw:0.###} m, {bound} clip tracks bound, "
                 + (corrected >= 0 ? $"{corrected} bones rest-corrected" : "no rig: verbatim copy"));
        }
        return new ModelTemplate { Root = root, RawHeight = raw, Library = lib, BoundTracks = bound, Unbound = unbound,
                                   Corrected = corrected };
    }

    private void Instantiate(Figure fig, ModelTemplate t, ModelInfo info)
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
        fig.UnboundClips = t.Library is null && info.Rig == "mixamo" ? ClipLibrary.Roles.Length : t.Unbound;
        fig.SetBody(body, true, ClipLibrary.Find<Skeleton3D>(inst), player);
    }

    private void UpdateStats()
    {
        Stats.Figures = _figures.Count;
        Stats.GlbFigures = _figures.Values.Count(f => f.IsGlb);
        Stats.Placeholders = Stats.Figures - Stats.GlbFigures;
        Stats.BoundTracks = _figures.Values.Sum(f => f.BoundTracks);
        Stats.UnboundClips = _figures.Values.Sum(f => f.UnboundClips);
        Stats.ClipsLoaded = Clips.ClipsLoaded;
        Stats.ClipsFailed = Clips.ClipsFailed;
    }
}
