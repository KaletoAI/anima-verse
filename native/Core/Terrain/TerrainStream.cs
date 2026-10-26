using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
using System.Threading.Tasks;
using AnimaNative.Api;
using AnimaNative.Ground;
using AnimaNative.World;

namespace AnimaNative.Terrain;

/// <summary>What the stream did so far (the log line, the bench result, the checks).</summary>
public sealed class StreamCounters
{
    /// <summary>Height tiles taken / evicted / dropped for an origin that does not match their key.</summary>
    public int TilesTaken, TilesEvicted, TilesDropped;
    /// <summary>Height batches taken, dropped for a moved signature, failed.</summary>
    public int HeightBatches, HeightBatchesDropped, FailedBatches;
    /// <summary>Statistics batches taken and statistics taken (<c>fillMissingStats</c>).</summary>
    public int StatsBatches, StatsTaken;
    /// <summary>Mask batches taken, mask tiles taken, mask tiles dropped because they left the want set.</summary>
    public int LayerBatches, LayerTilesTaken, LayerTilesDropped;
    /// <summary>Re-indexes after a mask batch answered under another cut; height and terrain reloads after a poll.</summary>
    public int Reindexes, HeightReloads, TerrainReloads;

    public override string ToString()
        => $"tiles taken={TilesTaken} evicted={TilesEvicted} dropped={TilesDropped} batches={HeightBatches} "
           + $"stale={HeightBatchesDropped} failed={FailedBatches} stats={StatsTaken}/{StatsBatches} "
           + $"masks={LayerTilesTaken}/{LayerBatches} masks_dropped={LayerTilesDropped} reindex={Reindexes} "
           + $"height_reloads={HeightReloads} terrain_reloads={TerrainReloads}";
}

/// <summary>
/// The browser's terrain STREAMING (client3d/src/scene/ground.ts — <c>setHeightAnchor</c>, <c>refreshTiles</c>,
/// <c>takeTiles</c>, <c>evictTiles</c>, <c>fillMissingStats</c>, <c>groundBusy</c>, <c>refreshLayerTiles</c>,
/// <c>reindexLayers</c>, <c>applyHeight</c>, <c>sync</c>/<c>reload</c>) as a Godot-free state machine:
///
///   • ONE anchor (the camera target; the avatar from E7). A crossed tile border is the immediate occasion, the idle
///     poll (<see cref="SyncAsync"/> with unchanged signatures) the second one.
///   • Height tiles: the want set is <see cref="HeightTiles.WantedTiles"/> at 560 m (nearest first); wanting a held
///     tile touches it in the LRU; the missing ones are fetched 64 per request by ONE loader; a batch answering under
///     another <c>height_sig</c> is dropped whole; an origin that does not match its key drops that tile; after every
///     taken batch the cache is trimmed to <see cref="CacheMax"/> from the oldest end, never a wanted tile, and the
///     host re-drapes ONCE (<see cref="FieldChanged"/>, awaited before the next batch).
///   • Statistics: what the overview's cap kept back is fetched in the background, 64 per request, stepping aside
///     while the ground is busy (<see cref="StatsFillIdleMs"/> polls), cancelled by signature.
///   • Layer masks: the SAME want set over the mask index, 16 per request; after every taken batch every tile the want
///     set no longer holds leaves before the window is repacked (<see cref="LayerWindowChanged"/>); a batch under
///     another cut re-takes the index once (<see cref="LayerIndexMoved"/>).
///   • Signatures from the worldmap poll: a new <c>height_sig</c> refetches the overview and starts over
///     (<see cref="HeightApplied"/>); a new <c>terrain_sig</c> hands the terrain/layer refetch to the host
///     (<see cref="TerrainReload"/>); either is followed by the areas' rebuild (<see cref="AreasRebuild"/>).
///
/// THREADING. Every method is called and continues on the caller's context (the Godot main thread through its
/// synchronisation context), so the state needs no locks — exactly the browser's single thread. Only the conversion
/// of a parsed batch into tiles leaves it (<see cref="Inline"/> = false: <see cref="Task.Run(Action)"/>); the hosts'
/// hooks do their own heavy work off the thread and upload on it.
/// </summary>
public sealed class TerrainStream
{
    /// <summary><c>LAYER_BATCH_MAX</c> (ground.ts), the server's <c>terrain_layers.BATCH_MAX</c>.</summary>
    public const int LayerBatchMax = LayerCut.BatchMax;
    /// <summary><c>STATS_FILL_IDLE_MS</c>: how long the background fill waits before asking "busy?" again.</summary>
    public const int StatsFillIdleMs = 250;

    private readonly IWorldSource _source;
    private readonly Action<string> _log;
    private readonly HashSet<string> _warned = new();

    public WorldHeight Height { get; }
    public StreamCounters Counters { get; } = new();

    /// <summary>Convert batches on the calling thread (tests); false = on the thread pool.</summary>
    public bool Inline { get; init; }
    /// <summary>The fill's idle wait (tests replace it).</summary>
    public Func<int, Task> Delay { get; init; } = ms => Task.Delay(ms);
    /// <summary><c>HEIGHT_TILE_CACHE_MAX</c>; a check may shrink it to see the eviction on a small world.</summary>
    public int CacheMax { get; init; } = HeightTiles.CacheMax;

    // ---- the host's side --------------------------------------------------------------------------------------

    /// <summary><c>terrain.setField(...)</c> + <c>rebuildAreas</c> + <c>rebuildBase</c> after a taken height batch (awaited).</summary>
    public Func<Task>? FieldChanged { get; set; }
    /// <summary><c>terrain.refreshStats()</c>: more statistics arrived — only the level errors move.</summary>
    public Action? StatsChanged { get; set; }
    /// <summary><c>setLayerTiles(layerTiles, layerFmt)</c>: the held masks (want-set filtered), repacked into one window.</summary>
    public Func<IReadOnlyList<KeyValuePair<string, LayerTile>>, LayerFormat, Task>? LayerWindowChanged { get; set; }
    /// <summary>
    /// <c>applyLayers(index)</c> after a re-index: the host re-takes the layer table for this index and seeds the masks
    /// again (<see cref="SeedLayers"/>).
    /// </summary>
    public Func<LayerIndex, Task>? LayerIndexMoved { get; set; }
    /// <summary><c>applyHeight</c>'s ground half (the AO field, <c>setField</c>) for a new relief, after the tiles were cleared.</summary>
    public Func<HeightfieldOverview, Task>? HeightApplied { get; set; }
    /// <summary>
    /// <c>reload</c>'s terrain half for a new <c>terrain_sig</c> (the painted terrain, the layer index, the masks):
    /// answers the signature now held, or null when it failed (nothing advances, the next poll asks again).
    /// </summary>
    public Func<Task<string?>>? TerrainReload { get; set; }
    /// <summary><c>rebuildAreas</c> after a reload (the scatter and undergrowth sample the ground again).</summary>
    public Func<Task>? AreasRebuild { get; set; }
    /// <summary>Every request, in order: <c>tiles k;k</c>, <c>stats k;k</c>, <c>masks k;k</c>, <c>height-index</c>, <c>mask-index</c>.</summary>
    public event Action<string>? Requested;

    // ---- state ------------------------------------------------------------------------------------------------

    public double AnchorX { get; private set; }
    public double AnchorZ { get; private set; }
    public bool HasAnchor { get; private set; }
    private string? _anchorTile;
    private HashSet<string> _tileIndex = new(StringComparer.Ordinal);
    private List<string> _tileOrder = new();
    public string? LoadedHeightSig { get; private set; }
    public string? LoadedTerrainSig { get; private set; }
    public bool TilesBusy { get; private set; }
    public bool LayersBusy { get; private set; }
    public bool Reloading { get; private set; }
    public bool Reindexing { get; private set; }
    public bool StatsFilling => _statsFillSig is not null;
    private string? _statsFillSig;
    private Task<bool> _inFlight = Task.FromResult(false);

    public LayerFormat? LayerFormat { get; private set; }
    public string LayerSig { get; private set; } = "";
    private HashSet<string> _layerKeys = new(StringComparer.Ordinal);
    /// <summary>The held masks in arrival order (the browser's <c>layerTiles</c> Map).</summary>
    private readonly List<KeyValuePair<string, LayerTile>> _layerTiles = new();

    public IReadOnlyList<KeyValuePair<string, LayerTile>> LayerTiles => _layerTiles;

    /// <summary>The height tiles the last taken batch added or evicted — the squares whose ground just changed.</summary>
    public List<(int Tx, int Tz)> LastChanged { get; } = new();

    /// <summary>Something that cuts the ground is in flight — the streaming probe counts its frames.</summary>
    public bool Active => TilesBusy || LayersBusy || Reloading || Reindexing;

    public TerrainStream(IWorldSource source, WorldHeight height, Action<string> log)
    {
        _source = source;
        Height = height;
        _log = log;
        TakeIndex();
    }

    /// <summary>
    /// The boot's state: the relief the build fetched (<c>loadedHeightSig = payload.sig || heightSig</c>) and the terrain
    /// signature the ground was built for; a capped overview starts the statistics fill (as <c>applyHeight</c> does).
    /// </summary>
    public void Seed(string heightSig, string terrainSig, double anchorX, double anchorZ)
    {
        TakeIndex();
        LoadedHeightSig = Height.Overview.Sig.Length > 0 ? Height.Overview.Sig : heightSig;
        LoadedTerrainSig = terrainSig;
        AnchorX = anchorX;
        AnchorZ = anchorZ;
        HasAnchor = true;
        _anchorTile = HeightTiles.TileKeyAt(Height.Overview.TileM, anchorX, anchorZ);
    }

    /// <summary>The fill of a capped overview (<c>applyHeight</c>'s last step), not awaited by anyone but a check.</summary>
    public Task StartStatsFill() => Height.Overview.StatsIncomplete ? FillMissingStatsAsync(LoadedHeightSig) : Task.CompletedTask;

    /// <summary>
    /// <c>applyLayers</c> as far as the stream is concerned: the format, the index's tile keys and whatever masks the
    /// host fetched with it (<c>layerSig = index.sig || sig</c>). A null index = no masks at all (plain ground).
    /// </summary>
    public void SeedLayers(LayerIndex? index, IEnumerable<KeyValuePair<string, LayerTile>> tiles, string sig = "")
    {
        _layerTiles.Clear();
        if (index is null)
        {
            LayerFormat = null;
            LayerSig = "";
            _layerKeys = new(StringComparer.Ordinal);
            return;
        }
        LayerFormat = index.Format;
        LayerSig = index.Format.Sig.Length > 0 ? index.Format.Sig : sig;
        _layerKeys = index.TileKeys.ToHashSet(StringComparer.Ordinal);
        foreach (var t in tiles) PutLayerTile(t.Key, t.Value);
    }

    private void TakeIndex()
    {
        _tileOrder = Height.Overview.TileKeys.ToList();
        _tileIndex = _tileOrder.ToHashSet(StringComparer.Ordinal);
    }

    /// <summary>The height want set round the anchor now (<c>wantedTiles(tileIndex, tileM, anchor, 560)</c>).</summary>
    public List<string> WantedHeight()
        => HasAnchor ? HeightTiles.WantedTiles(_tileIndex, Height.Overview.TileM, AnchorX, AnchorZ, HeightTiles.RadiusM) : new();

    /// <summary>The mask want set round the anchor now (the mask index, the mask tile size, the same radius).</summary>
    public List<string> WantedLayers()
        => HasAnchor && LayerFormat is { } f
            ? HeightTiles.WantedTiles(_layerKeys, f.TileM, AnchorX, AnchorZ, HeightTiles.RadiusM)
            : new();

    private static (int Tx, int Tz) KeyOf(string key)
        => HeightfieldOverview.TryTileKey(key, out var k) ? k : (int.MinValue, int.MinValue);

    private Task<T> Off<T>(Func<T> work) => Inline ? Task.FromResult(work()) : Task.Run(work);

    private void WarnOnce(string tag, string line)
    {
        if (_warned.Add(tag)) _log(line);
    }

    // ---- the anchor ---------------------------------------------------------------------------------------------

    /// <summary>
    /// <c>setHeightAnchor(x, z)</c>: remember the point; when it crossed into another tile, start both loaders (the
    /// returned task completes when both have, for a check — the client does not wait).
    /// </summary>
    public Task SetAnchor(double x, double z)
    {
        if (!double.IsFinite(x) || !double.IsFinite(z)) return Task.CompletedTask;
        AnchorX = x;
        AnchorZ = z;
        HasAnchor = true;
        var key = HeightTiles.TileKeyAt(Height.Overview.TileM, x, z);
        if (key == _anchorTile) return Task.CompletedTask;
        _anchorTile = key;
        return Task.WhenAll(RefreshTilesAsync(), RefreshLayerTilesAsync());
    }

    // ---- height tiles -------------------------------------------------------------------------------------------

    /// <summary><c>refreshTiles</c>: fetch what the anchor wants and does not hold, in batches, one loader at a time.</summary>
    public async Task RefreshTilesAsync()
    {
        if (TilesBusy || Reloading) return;
        double tileM = Height.Overview.TileM;
        if (!(tileM > 0) || _tileIndex.Count == 0) return;
        var want = WantedHeight();
        foreach (var key in want) Height.Touch(KeyOf(key));
        var missing = want.Where(k => !Height.HasTile(KeyOf(k))).ToList();
        if (missing.Count == 0)
        {
            Evict(want);
            return;
        }
        TilesBusy = true;
        var sig = LoadedHeightSig;
        try
        {
            foreach (var batch in HeightTiles.TileBatches(missing))
            {
                List<HeightTile> tiles;
                string paySig;
                try
                {
                    var keys = batch.Select(KeyOf).ToList();
                    Requested?.Invoke("tiles " + string.Join(";", batch));
                    using var doc = await _source.GetHeightTilesAsync(keys);
                    var root = doc.RootElement;
                    (tiles, paySig) = await Off(() => (HeightTile.ParseBatch(root), Json.Str(root, "sig")));
                }
                catch (Exception e)
                {
                    // Keep what stands; the missing keys stay wanted (the next border or poll asks again).
                    Counters.FailedBatches++;
                    _log($"stream: height batch failed ({e.Message}) — the missing tiles stay wanted");
                    return;
                }
                if (LoadedHeightSig != sig || (paySig.Length > 0 && paySig != sig))
                {
                    Counters.HeightBatchesDropped++;
                    return;
                }
                LastChanged.Clear();
                if (Take(tiles) == 0) continue;
                Evict(want);
                Counters.HeightBatches++;
                await Hook(FieldChanged, "field rebuild");
            }
        }
        finally
        {
            TilesBusy = false;
        }
    }

    /// <summary><c>takeTiles</c>: a tile whose origin is not its key's square is dropped (once-warned); answers how many were taken.</summary>
    private int Take(List<HeightTile> tiles)
    {
        double tileM = Height.Overview.TileM;
        var ok = new List<HeightTile>(tiles.Count);
        foreach (var t in tiles)
        {
            if (t.Grid.OriginX != t.Key.Tx * tileM || t.Grid.OriginZ != t.Key.Tz * tileM)
            {
                Counters.TilesDropped++;
                WarnOnce("tile-origin", $"stream: height tile \"{t.Key.Tx},{t.Key.Tz}\" claims origin ({t.Grid.OriginX}, {t.Grid.OriginZ}) — dropped");
                continue;
            }
            ok.Add(t);
        }
        if (ok.Count > 0) Height.AddTiles(ok);
        LastChanged.AddRange(ok.Select(t => t.Key));
        Counters.TilesTaken += ok.Count;
        return ok.Count;
    }

    /// <summary><c>evictTiles</c>: over the cap, drop from the oldest end — never a tile of the current want set.</summary>
    private void Evict(IReadOnlyList<string> want)
    {
        if (Height.Tiles.Count <= CacheMax) return;
        var keep = want.Select(KeyOf).ToHashSet();
        foreach (var key in Height.LruOrder.ToList())
        {
            if (Height.Tiles.Count <= CacheMax) break;
            if (keep.Contains(key)) continue;
            if (!Height.RemoveTile(key)) continue;
            Counters.TilesEvicted++;
            LastChanged.Add(key);
        }
    }

    // ---- statistics ---------------------------------------------------------------------------------------------

    /// <summary><c>groundBusy</c>: a loader or a reload runs, or the anchor wants tiles it does not hold yet.</summary>
    public bool GroundBusy()
    {
        if (TilesBusy || LayersBusy || Reloading) return true;
        if (!(Height.Overview.TileM > 0) || _tileIndex.Count == 0) return false;
        return WantedHeight().Any(k => !Height.HasTile(KeyOf(k)));
    }

    /// <summary>
    /// <c>fillMissingStats(sig)</c>: the statistics of every indexed tile not known yet, 64 per request, behind the
    /// picture; the want list is taken once; a failed batch gives up until the next relief; a batch of another relief is
    /// dropped. One fill per signature.
    /// </summary>
    public async Task FillMissingStatsAsync(string? sig)
    {
        if (sig is null || _statsFillSig == sig) return;
        _statsFillSig = sig;
        try
        {
            var missing = _tileOrder.Where(k => !Height.Stats.ContainsKey(k)).ToList();
            foreach (var batch in HeightTiles.TileBatches(missing))
            {
                if (LoadedHeightSig != sig) return;
                while (GroundBusy())
                {
                    await Delay(StatsFillIdleMs);
                    if (LoadedHeightSig != sig) return;
                }
                var want = batch.Where(k => !Height.Stats.ContainsKey(k)).ToList();
                if (want.Count == 0) continue;
                Dictionary<string, TileStat> got;
                string paySig;
                try
                {
                    Requested?.Invoke("stats " + string.Join(";", want));
                    using var doc = await _source.GetHeightTileStatsAsync(want.Select(KeyOf).ToList());
                    got = TileStat.ParseMap(doc.RootElement, "tile_stats");
                    paySig = Json.Str(doc.RootElement, "sig");
                }
                catch (Exception e)
                {
                    _log($"stream: statistics batch failed ({e.Message}) — the level stays coarse until the next relief");
                    return;
                }
                if (LoadedHeightSig != sig || (paySig.Length > 0 && paySig != sig)) return;
                int taken = Height.AddStats(got);
                Counters.StatsBatches++;
                Counters.StatsTaken += taken;
                if (taken > 0) StatsChanged?.Invoke();
            }
        }
        finally
        {
            if (_statsFillSig == sig) _statsFillSig = null;
        }
    }

    // ---- layer masks --------------------------------------------------------------------------------------------

    private bool LayerHeld(string key) => _layerTiles.Any(t => t.Key == key);

    private void PutLayerTile(string key, LayerTile tile)
    {
        int i = _layerTiles.FindIndex(t => t.Key == key);
        if (i >= 0) _layerTiles[i] = new(key, tile);
        else _layerTiles.Add(new(key, tile));
    }

    /// <summary>
    /// <c>refreshLayerTiles</c>: the masks the anchor wants, 16 per request; after each taken batch the tiles that left
    /// the want set go and the window is handed over once. A batch under another cut re-takes the index.
    /// </summary>
    public async Task RefreshLayerTilesAsync()
    {
        if (LayersBusy || LayerFormat is null || _layerKeys.Count == 0) return;
        var fmt = LayerFormat;
        if (!(fmt.TileM > 0)) return;
        var want = WantedLayers();
        var missing = want.Where(k => !LayerHeld(k)).ToList();
        if (missing.Count == 0) return;
        LayersBusy = true;
        var sig = LayerSig;
        try
        {
            for (int i = 0; i < missing.Count; i += LayerBatchMax)
            {
                var keys = missing.Skip(i).Take(LayerBatchMax).ToList();
                LayerBatch batch;
                try
                {
                    Requested?.Invoke("masks " + string.Join(";", keys));
                    using var doc = await _source.GetTerrainLayersAsync(keys);
                    var root = doc.RootElement;
                    batch = await Off(() => LayerCut.ParseBatch(root));
                }
                catch (Exception e)
                {
                    _log($"stream: mask batch failed ({e.Message}) — the missing tiles stay wanted");
                    return;
                }
                if (LayerSig != sig) return;
                if (batch.Format.Sig.Length > 0 && batch.Format.Sig != sig)
                {
                    // The cut moved while terrain_sig stood still (room floors are in the masks, not in terrain_sig).
                    _ = ReindexLayersAsync(sig);
                    return;
                }
                int taken = 0;
                foreach (var (key, tile) in batch.Tiles)
                {
                    PutLayerTile(key, tile);
                    taken++;
                }
                if (taken == 0) continue;
                Counters.LayerTilesTaken += taken;
                var keep = want.ToHashSet(StringComparer.Ordinal);
                Counters.LayerTilesDropped += _layerTiles.RemoveAll(t => !keep.Contains(t.Key));
                Counters.LayerBatches++;
                if (LayerWindowChanged is { } hook) await Hook(() => hook(_layerTiles.ToList(), fmt), "mask window");
            }
        }
        finally
        {
            LayersBusy = false;
        }
    }

    /// <summary>The running re-index (a check awaits it).</summary>
    public Task Reindex { get; private set; } = Task.CompletedTask;

    /// <summary>
    /// <c>reindexLayers(sig)</c>: one index refetch at a time; it is taken only when the held cut is still the one the
    /// batch was asked under and the index really names another.
    /// </summary>
    public Task ReindexLayersAsync(string sig)
    {
        if (Reindexing) return Reindex;
        Reindexing = true;
        return Reindex = Run();

        async Task Run()
        {
            try
            {
                LayerIndex index;
                try
                {
                    Requested?.Invoke("mask-index");
                    using var doc = await _source.GetTerrainLayersAsync(Array.Empty<string>());
                    var root = doc.RootElement;
                    index = await Off(() => LayerCut.ParseIndex(root));
                }
                catch (Exception e)
                {
                    _log($"stream: mask index refetch failed ({e.Message})");
                    return;
                }
                if (LayerSig == sig && index.Format.Sig != sig)
                {
                    Counters.Reindexes++;
                    if (LayerIndexMoved is { } hook) await Hook(() => hook(index), "layer re-index");
                    else SeedLayers(index, Array.Empty<KeyValuePair<string, LayerTile>>());
                }
            }
            finally
            {
                Reindexing = false;
            }
        }
    }

    // ---- the poll -----------------------------------------------------------------------------------------------

    /// <summary>
    /// <c>sync(terrain_sig, …, height_sig)</c> on every worldmap poll: a reload in flight is shared; while the tile
    /// loader works nothing starts (no signature moved, the next poll asks again). Unchanged signatures = the idle
    /// occasion: both loaders and the statistics fill. A moved one = <c>reload</c>: the relief first, then the terrain,
    /// then the areas. Answers whether a reload ran and succeeded.
    /// </summary>
    public Task<bool> SyncAsync(string terrainSig, string heightSig)
    {
        if (Reloading) return _inFlight;
        if (TilesBusy) return Task.FromResult(false);
        bool wantHeight = LoadedHeightSig != heightSig;
        bool wantTerrain = LoadedTerrainSig is null || LoadedTerrainSig != terrainSig;
        if (!wantHeight && !wantTerrain)
        {
            _ = RefreshTilesAsync();
            _ = RefreshLayerTilesAsync();
            _ = FillMissingStatsAsync(LoadedHeightSig);
            return Task.FromResult(false);
        }
        Reloading = true;
        return _inFlight = Guarded();

        async Task<bool> Guarded()
        {
            try { return await ReloadAsync(terrainSig, heightSig, wantTerrain, wantHeight); }
            finally { Reloading = false; }
        }
    }

    private async Task<bool> ReloadAsync(string terrainSig, string heightSig, bool wantTerrain, bool wantHeight)
    {
        if (wantHeight)
        {
            HeightfieldOverview? ov = null;
            try
            {
                Requested?.Invoke("height-index");
                using var doc = await _source.GetHeightfieldAsync();
                var root = doc.RootElement;
                ov = await Off(() => HeightfieldOverview.Parse(root));
            }
            catch (Exception e)
            {
                // Keep the field that stands; LoadedHeightSig does not move, so the next poll asks again.
                _log($"stream: heightfield refetch failed ({e.Message})");
            }
            if (ov is not null) await ApplyHeightAsync(ov, heightSig);
        }
        bool ok = true;
        if (wantTerrain)
        {
            string? got;
            try { got = TerrainReload is { } reload ? await reload() : terrainSig; }
            catch (Exception e)
            {
                _log($"stream: terrain reload failed ({e.Message})");
                got = null;
            }
            if (got is null) ok = false;
            else
            {
                LoadedTerrainSig = got.Length > 0 ? got : terrainSig;
                Counters.TerrainReloads++;
            }
        }
        if (ok || wantHeight) await Hook(AreasRebuild, "areas rebuild");
        return ok;
    }

    /// <summary>
    /// <c>applyHeight</c>: the new overview, its index and statistics; the tiles are thrown away with the old relief; the
    /// anchor forgets its tile (so the next tick refetches); the host re-drapes; a capped overview starts the fill.
    /// </summary>
    private async Task ApplyHeightAsync(HeightfieldOverview ov, string heightSig)
    {
        Height.Reset(ov);
        TakeIndex();
        _anchorTile = null;
        LoadedHeightSig = ov.Sig.Length > 0 ? ov.Sig : heightSig;
        Counters.HeightReloads++;
        await Hook(HeightApplied is { } h ? () => h(ov) : null, "height apply");
        if (ov.StatsIncomplete) _ = FillMissingStatsAsync(LoadedHeightSig);
    }

    /// <summary>A host hook never takes the loader down with it: its failure is logged and the stream goes on.</summary>
    private async Task Hook(Func<Task>? hook, string what)
    {
        if (hook is null) return;
        try { await hook(); }
        catch (Exception e) { _log($"stream: {what} failed: {e.Message}"); }
    }
}

/// <summary>
/// One rebuild at a time, the rest folded into ONE follow-up: a request while a build runs is answered by the build
/// that starts after it (so a caller never sees a build older than its request), and any number of requests during
/// one build cost one more build, not one each.
/// </summary>
public sealed class Coalescer
{
    private readonly Func<Task> _work;
    private bool _busy;
    private TaskCompletionSource? _pending;

    public Coalescer(Func<Task> work) => _work = work;

    /// <summary>How many builds ran (the checks count them).</summary>
    public int Runs { get; private set; }
    public bool Busy => _busy;

    /// <summary>A build that starts no earlier than this call; completes (or faults) with that build.</summary>
    public Task RequestAsync()
    {
        if (_busy) return (_pending ??= new TaskCompletionSource()).Task;
        _busy = true;
        var first = new TaskCompletionSource();
        _ = DriveAsync(first);
        return first.Task;
    }

    private async Task DriveAsync(TaskCompletionSource current)
    {
        while (true)
        {
            Exception? error = null;
            try
            {
                Runs++;
                await _work();
            }
            catch (Exception e)
            {
                error = e;
            }
            // The state moves BEFORE the callers hear of it: a caller whose continuation runs inline and asks again
            // must find either an idle coalescer or a follow-up slot that this loop will still pick up.
            var done = current;
            bool last = _pending is null;
            if (last) _busy = false;
            else
            {
                current = _pending!;
                _pending = null;
            }
            if (error is null) done.TrySetResult();
            else done.TrySetException(error);
            if (last) return;
        }
    }
}

/// <summary>
/// The streaming frame-time probe: the longest frame while something streamed (a frame counts when the stream was
/// active at its start or its end — an upload that ends the stream lands in the frame measured AFTER it), next to the
/// longest frame of any kind, over a window the bench and the fly drive reset.
/// </summary>
public sealed class StreamProbe
{
    public int Frames { get; private set; }
    public int StreamFrames { get; private set; }
    public double MaxMs { get; private set; }
    public double StreamMaxMs { get; private set; }
    private bool _prevActive;

    public void Reset()
    {
        Frames = StreamFrames = 0;
        MaxMs = StreamMaxMs = 0;
        _prevActive = false;
    }

    /// <summary>One frame of <paramref name="ms"/> milliseconds; <paramref name="active"/> = streaming now.</summary>
    public void Frame(double ms, bool active)
    {
        if (!(ms >= 0) || !double.IsFinite(ms)) return;
        Frames++;
        if (ms > MaxMs) MaxMs = ms;
        if (active || _prevActive)
        {
            StreamFrames++;
            if (ms > StreamMaxMs) StreamMaxMs = ms;
        }
        _prevActive = active;
    }

    public string Summary() => $"probe[frames={Frames} max={MaxMs:0.##} ms streaming_frames={StreamFrames} streaming_max={StreamMaxMs:0.##} ms]";
}
