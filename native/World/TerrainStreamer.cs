using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Linq;
using System.Text.Json;
using System.Threading.Tasks;
using AnimaNative.Api;
using AnimaNative.Ground;
using AnimaNative.Scatter;
using AnimaNative.Terrain;
using Godot;

namespace AnimaNative.World;

/// <summary>
/// The terrain streaming in Godot: the Godot-free <see cref="TerrainStream"/> (ground.ts' loaders and signatures) wired to
/// the drawn world —
///
///   • the ANCHOR: the camera target (<see cref="Ui.OverviewCamera.Target"/>; the avatar from E7) on main.ts' 1 Hz tick;
///   • a taken height batch → ONE field rebuild (<see cref="Coalescer"/>): the near pyramid, the water fields (level,
///     sd, look rows, flow — all on the near lattice) and their images are made on a worker thread from a
///     <see cref="WorldHeight.Snapshot"/>; only the texture upload and the uniform binding run on the main thread
///     (<see cref="TerrainLodNode.ApplyField"/>); then the scatter and the undergrowth sample the ground again
///     (<c>rebuildAreas</c>);
///   • a taken mask batch → the window repacked on a worker, uploaded on the main thread
///     (<see cref="GroundSurfaces.SetLayerWindow"/>);
///   • more statistics → the level errors of the standing field (<c>refreshStats</c>);
///   • the worldmap poll (<see cref="Sync"/>): the world frame (<c>rebuildBase</c>), <c>height_sig</c> (refetch the
///     overview, new AO, rebuild — the height revision makes every location re-datum, Task 17) and <c>terrain_sig</c>
///     (a new ground: terrain catalog, layer index, masks; the scatter refetches its terrain), the mask re-index.
///
/// The probe: every frame's wall time goes into <see cref="Probe"/> (reset by the bench and the fly drive) and
/// <see cref="Session"/>, flagged "streaming" while anything above is in flight; a log line every 10 s that saw streaming.
/// </summary>
public partial class TerrainStreamer : Node
{
    /// <summary><c>LOD_TICK_MS</c> (main.ts): the anchor follows the camera target once a second.</summary>
    public const double AnchorTickS = 1.0;
    public const double LogEveryS = 10.0;

    private readonly WorldBuilder _b;
    private readonly IWorldSource _source;
    private readonly Action<string> _log;
    private readonly Func<Vector3> _anchor;
    private readonly bool _water;
    private readonly Coalescer _field;
    private HeightfieldOverview? _farOverview;
    private double _tick = double.PositiveInfinity, _logClock;
    private ulong _lastUsec;
    private int _groundReloads;
    private bool _groundBusy, _maskBusy;
    private int _streamFramesLogged;

    public TerrainStream Stream { get; }
    /// <summary>The window the bench and the fly drive measure (reset at their start).</summary>
    public StreamProbe Probe { get; } = new();
    /// <summary>Everything since the world stood.</summary>
    public StreamProbe Session { get; } = new();
    /// <summary>The scatter layer whose areas re-sample after a batch / reload (null = scatter off).</summary>
    public ScatterLayer? Scatter { get; set; }
    /// <summary>The latest polled map (the scatter's reload reads the location outlines from it).</summary>
    private JsonElement? _lastMap;

    /// <summary>Field rebuilds, their worker time and their main-thread upload time (last / largest, ms).</summary>
    public int FieldBuilds => _field.Runs;
    public double LastBuildMs { get; private set; }
    public double MaxBuildMs { get; private set; }
    public double LastUploadMs { get; private set; }
    public double MaxUploadMs { get; private set; }
    public int MaskWindows { get; private set; }

    /// <summary>false = the 1 Hz tick does not move the anchor (a check drives <see cref="TerrainStream.SetAnchor"/> itself).</summary>
    public bool AnchorFollows { get; set; } = true;

    /// <summary>Something that cuts the ground is in flight (a loader, a build, a reload).</summary>
    public bool Active => Stream.Active || _field.Busy || _groundBusy || _maskBusy;

    /// <param name="anchorX">The point the boot ring was loaded round (the build's anchor).</param>
    /// <param name="water">The water may be drawn at all (not <c>--no-water</c>, not <c>--plain-ground</c>).</param>
    /// <param name="cacheMax">The LRU cap (default <c>HEIGHT_TILE_CACHE_MAX</c> 96; the check shrinks it to see evictions).</param>
    public TerrainStreamer(WorldBuilder builder, IWorldSource source, Func<Vector3> anchor, Action<string> log,
                           string heightSig, string terrainSig, double anchorX, double anchorZ, bool water,
                           int? cacheMax = null)
    {
        Name = "TerrainStreamer";
        _b = builder;
        _source = source;
        _anchor = anchor;
        _log = log;
        _water = water;
        _farOverview = builder.Height!.Overview;
        _field = new Coalescer(BuildFieldOnceAsync);
        Stream = new TerrainStream(source, builder.Height!, log) { CacheMax = cacheMax ?? HeightTiles.CacheMax };
        // loadedSig = payload.sig || sig: the terrain the ground was built from, else the boot map's.
        var groundSig = builder.Ground?.TerrainSig ?? "";
        Stream.Seed(heightSig, groundSig.Length > 0 ? groundSig : terrainSig, anchorX, anchorZ);
        if (builder.Ground is { } g) Stream.SeedLayers(g.Index, g.Tiles);
        Stream.FieldChanged = async () =>
        {
            var changed = Stream.LastChanged.ToList();
            await _field.RequestAsync();
            RebuildAreas(changed);
        };
        Stream.StatsChanged = TakeStats;
        Stream.LayerWindowChanged = TakeMaskWindowAsync;
        Stream.LayerIndexMoved = async index => { await ReloadGroundAsync(index); };
        Stream.HeightApplied = ov =>
        {
            _b.Ground?.SetAoField(ov.Grid);
            return _field.RequestAsync();
        };
        Stream.TerrainReload = ReloadTerrainAsync;
        Stream.AreasRebuild = () =>
        {
            RebuildAreas();
            return Task.CompletedTask;
        };
        _ = Stream.StartStatsFill();
    }

    public override void _Process(double delta)
    {
        ulong now = Time.GetTicksUsec();
        if (_lastUsec != 0)
        {
            double ms = (now - _lastUsec) / 1000.0;
            bool active = Active;
            Probe.Frame(ms, active);
            Session.Frame(ms, active);
        }
        _lastUsec = now;
        _tick += delta;
        if (_tick >= AnchorTickS && AnchorFollows)
        {
            _tick = 0;
            var a = _anchor();
            _ = Stream.SetAnchor(a.X, a.Z);
        }
        _logClock += delta;
        if (_logClock >= LogEveryS)
        {
            _logClock = 0;
            if (Session.StreamFrames != _streamFramesLogged)
            {
                _streamFramesLogged = Session.StreamFrames;
                _log("stream " + Summary());
            }
        }
    }

    /// <summary>
    /// The worldmap poll's ground half (<c>terrainGround.sync(terrain_sig, world_bounds, …, height_sig ?? '')</c>): the
    /// frame first (<c>rebuildBase</c>), then the signatures decide.
    /// </summary>
    public Task<bool> Sync(JsonElement map)
    {
        _lastMap = map.Clone();
        if (_b.Terrain is { } t) t.SetExtent(TerrainField.ExtentOf(Overview.OverviewControl.WorldBoundsOf(map)));
        return Stream.SyncAsync(Json.Str(map, "terrain_sig"), Json.Str(map, "height_sig"));
    }

    /// <summary>A frame of the waits below (the settle loops of a check or the fly drive).</summary>
    public async Task SettleAsync(double maxSeconds = 60, double quietSeconds = 0)
    {
        ulong start = Time.GetTicksMsec(), quietSince = 0;
        while (Time.GetTicksMsec() - start < maxSeconds * 1000)
        {
            await ToSignal(GetTree(), SceneTree.SignalName.ProcessFrame);
            if (Active || Stream.StatsFilling) { quietSince = 0; continue; }
            if (quietSince == 0) quietSince = Time.GetTicksMsec();
            if (Time.GetTicksMsec() - quietSince >= quietSeconds * 1000) return;
        }
    }

    // ---- the field ------------------------------------------------------------------------------------------------

    /// <summary>
    /// One field rebuild: snapshot on the main thread, build on a worker (the near pyramid through the tile-first
    /// height, the water level/sd/rows/flow/cap on the near lattice, the far pyramid only when the overview changed, all
    /// images), then upload + bind on the main thread with the frame and statistics of NOW.
    /// </summary>
    private async Task BuildFieldOnceAsync()
    {
        var term = _b.Terrain;
        var height = _b.Height;
        if (term is null || height is null) return;
        var ground = _b.Ground;
        bool water = _water && ground is not null;
        var snap = height.Snapshot();
        double ax = Stream.AnchorX, az = Stream.AnchorZ;
        var extent = (double[])term.Field.Extent.Clone();
        var far = ReferenceEquals(snap.Overview, _farOverview) ? term.Field.Far : null;
        Dictionary<string, int>? rows = null;
        if (water)
        {
            ground!.BuildWaterLooks();
            rows = new Dictionary<string, int>(ground.WaterRowOfKind);
        }
        var clock = Stopwatch.StartNew();
        var prep = await Task.Run(() =>
        {
            var raster = water ? snap.WaterRaster() : null;
            var field = TerrainField.Build(snap, ax, az, raster, extent, far, rows);
            var images = TerrainLodNode.PrepareImages(field, skipFar: far is not null);
            return (field, images);
        });
        LastBuildMs = clock.Elapsed.TotalMilliseconds;
        MaxBuildMs = Math.Max(MaxBuildMs, LastBuildMs);
        if (!IsInstanceValid(term) || term != _b.Terrain || height != _b.Height) return;
        clock.Restart();
        var g = _b.Ground;
        // The water variant comes into being with the first field that carries water (its look, sd, rows and flow all
        // ride on the field's near lattice — no window of its own any more).
        if (water && g == ground && prep.field.Water is not null) g!.EnsureWaterMaterial();
        // The frame and the statistics of NOW (a poll or the fill may have moved them during the build).
        prep.field.SetExtent(term.Field.Extent);
        var ov = height.Overview;
        prep.field.TakeStats(height.Stats, ov.MipLevelsM, ov.TileM);
        term.ApplyField(prep.field, prep.images, g?.Material, g?.WaterMaterial);
        _farOverview = snap.Overview;
        LastUploadMs = clock.Elapsed.TotalMilliseconds;
        MaxUploadMs = Math.Max(MaxUploadMs, LastUploadMs);
        _log($"stream: field rebuilt ({snap.Tiles.Count} tiles, revision {snap.Revision}) — {prep.field.Summary()}; "
             + $"worker {LastBuildMs:0.#} ms, upload {LastUploadMs:0.##} ms");
    }

    /// <summary><c>terrain.refreshStats()</c>: the level errors of the standing field from every statistic known now.</summary>
    private void TakeStats()
    {
        if (_b.Terrain is not { } term || _b.Height is not { } h) return;
        term.Field.TakeStats(h.Stats, h.Overview.MipLevelsM, h.Overview.TileM);
        term.Invalidate();
    }

    /// <summary>
    /// <c>rebuildAreas</c>: everything grown on the ground samples it again (the authored scatter, the undergrowth) —
    /// after a batch only where a changed tile touches a cell (<paramref name="tiles"/>; null = everywhere). The browser
    /// re-samples everything per batch; the result is the same, the main-thread cost is not (a full scatter rebuild is
    /// ~300 ms on the real world, a batch at the 560 m rim touches no cell of the window round the anchor).
    /// </summary>
    private void RebuildAreas(IReadOnlyCollection<(int Tx, int Tz)>? tiles = null)
    {
        if (Scatter is { } s && IsInstanceValid(s)) s.Redrape(tiles, _b.Height?.Overview.TileM ?? 0);
    }

    // ---- masks and the ground -------------------------------------------------------------------------------------

    /// <summary><c>setLayerTiles</c>: pack the held masks into one window on a worker, upload it on the main thread.</summary>
    private async Task TakeMaskWindowAsync(IReadOnlyList<KeyValuePair<string, LayerTile>> tiles, LayerFormat fmt)
    {
        var g = _b.Ground;
        if (g is null || g.Format.Sig != fmt.Sig) return;
        _maskBusy = true;
        try
        {
            var (window, images) = await Task.Run(() =>
            {
                var w = LayerCut.Pack(tiles, fmt);
                return (w, w is null ? ((Image, Image)?)null : GroundSurfaces.WindowImages(w));
            });
            if (_b.Ground != g) return;
            g.SetLayerWindow(window, images);
            g.Stats.MaskTiles = tiles.Count;
            g.Stats.WantedTiles = Stream.WantedLayers().Count;
            MaskWindows++;
        }
        finally
        {
            _maskBusy = false;
        }
    }

    /// <summary>
    /// A new ground for the current anchor (a new <c>terrain_sig</c>, or the re-index with its <paramref name="index"/>):
    /// catalog, library, layer index, the wanted masks, the slices — the old ground keeps drawing until the new one
    /// stands; then the field is rebuilt (its look rows follow the new look table). A failure keeps the old ground (false).
    /// </summary>
    private async Task<bool> ReloadGroundAsync(LayerIndex? index)
    {
        if (_b.PlainGround || _b.Height is not { } height) return true;
        _groundBusy = true;
        try
        {
            var g = await GroundSurfaces.LoadAsync(_source, height, Stream.AnchorX, Stream.AnchorZ, _log, water: false, index);
            if (!IsInstanceValid(this)) return false;
            if (_b.Ground?.Hole is { } hole) g.SetHole(hole);
            _b.ReplaceGround(g);
            Stream.SeedLayers(g.Index, g.Tiles);
            _groundReloads++;
            _log($"stream: ground reloaded ({(index is null ? "terrain_sig" : "re-index " + index.Format.Sig)}) — {g.Stats.Summary()}");
            await _field.RequestAsync();
            return true;
        }
        catch (Exception e)
        {
            _log($"stream: ground reload failed, the old ground stays: {e.Message}");
            return false;
        }
        finally
        {
            _groundBusy = false;
        }
    }

    /// <summary><c>reload</c>'s terrain half: the ground (unless plain), the scatter's terrain; the signature now held.</summary>
    private async Task<string?> ReloadTerrainAsync()
    {
        if (!await ReloadGroundAsync(null)) return null;
        if (Scatter is { } s && IsInstanceValid(s) && _lastMap is { } map)
        {
            try { await s.ReloadAsync(_source, map); }
            catch (Exception e) { _log($"stream: scatter reload failed: {e.Message}"); }
        }
        return _b.Ground?.TerrainSig ?? "";
    }

    // ---- reporting ----------------------------------------------------------------------------------------------

    /// <summary>
    /// The bench result's extra keys (Task 24), after <c>terrain</c>: <c>streamMaxFrameMs</c> — the longest frame of the
    /// drive while the terrain streamed (null = nothing streamed during the drive), <c>streamFrames</c> — how many frames
    /// that was, <c>stream</c> — the counters line. The E3 gate (Task 26) reads the first.
    /// </summary>
    public void AddBenchKeys(System.Text.Json.Nodes.JsonObject result)
    {
        result["streamMaxFrameMs"] = Probe.StreamFrames > 0 ? System.Text.Json.Nodes.JsonValue.Create(Math.Round(Probe.StreamMaxMs, 3)) : null;
        result["streamFrames"] = Probe.StreamFrames;
        result["stream"] = Summary();
    }

    public string Summary()
    {
        var h = _b.Height;
        return $"stream[held={h?.Tiles.Count ?? 0} stats={h?.Stats.Count ?? 0} {Stream.Counters} builds={FieldBuilds} "
               + $"build_ms={LastBuildMs:0.#}/{MaxBuildMs:0.#} upload_ms={LastUploadMs:0.##}/{MaxUploadMs:0.##} "
               + $"mask_windows={MaskWindows} ground_reloads={_groundReloads} anchor=({Stream.AnchorX:0},{Stream.AnchorZ:0}) "
               + $"session {Session.Summary()}]";
    }
}
