using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;
using AnimaNative.Api;
using AnimaNative.Ground;
using AnimaNative.Scene;
using Godot;

namespace AnimaNative.World;

/// <summary>Everything the build produced, for the log line and the check.</summary>
public sealed class WorldStats
{
    public AnchorInfo Anchor = AnchorInfo.Origin;
    public int OverviewVertices, OverviewTriangles;
    public int Tiles, TileVertices, TileTriangles;
    public int Locations, Scenes, Buildings, BuildingsCompressed, BuildingVertices, BuildingIndices;
    /// <summary>Placed locations the browser does not mount at all from this view (ring <c>gone</c>).</summary>
    public int LocationsGone;
    /// <summary>The location opened at the boot (the avatar's; its interior fades in) — "" when none.</summary>
    public string OpenLocation = "";
    public int Failures;
    /// <summary>The scene-recipe primitives, drawn and skipped by reason.</summary>
    public RecipeStats Recipe = new();
    /// <summary>The model specs (recipe <c>models[]</c> incl. buildings + world props), per kind.</summary>
    public ModelStats Models = new();
    public int WorldPropRows;
    /// <summary>The per-fragment cuts of the mount (<see cref="CutMaterials"/>): placements cut, surfaces wearing a cut material, surfaces left uncut.</summary>
    public int CutPlacements, CutSurfaces, CutFallbacks;
    /// <summary>
    /// The water (Wasser v2 K-A has no water mesh — a water body is the terrain lifted onto its mirror): painted
    /// water areas with a carved bed, wet tiles drawn with the water variant, water kinds (look rows), wet lattice
    /// points; <see cref="WaterMode"/> "drawn", "none…" or "off: --no-water".
    /// </summary>
    public int WaterTiles, WaterKinds, WaterTexels, WaterAreas;
    public string WaterMode = "none";
    /// <summary>The ground surfaces (Task S3b); Mode "plain" = the S1a vertex colour.</summary>
    public GroundStats Ground = new();
    public List<string> Problems { get; } = new();
    /// <summary>§ B5a over every mounted location: locations reported, numbers checked, deviation rows.</summary>
    public int VerifyLocations, VerifyChecked, VerifyRows;

    public int TerrainVertices => OverviewVertices + TileVertices;
    public int Primitives => Recipe.Primitives;
    public int Skipped => Recipe.Skipped;

    public string WaterSummary() => WaterMode == "drawn"
        ? $"water[areas={WaterAreas} tiles={WaterTiles} kinds={WaterKinds} wet_texels={WaterTexels}]"
        : $"water[{WaterMode}]";

    public string Summary() =>
        $"terrain_vertices={TerrainVertices} overview_vertices={OverviewVertices} overview_triangles={OverviewTriangles} "
        + $"tiles={Tiles} tile_vertices={TileVertices} locations={Locations} gone={LocationsGone} scenes={Scenes} "
        + $"open={(OpenLocation.Length > 0 ? OpenLocation : "-")} buildings={Buildings} "
        + $"buildings_meshopt={BuildingsCompressed} building_vertices={BuildingVertices} building_indices={BuildingIndices} "
        + $"primitives={Primitives} skipped={Skipped} ({Recipe.SkipSummary()}) shell_copies={Recipe.ShellCopies} "
        + $"culled_walls={Recipe.CulledWalls} interior_mounted={Recipe.InteriorMounted} {Models.Summary()} world_props={WorldPropRows} {CutSummary()} "
        + $"failures={Failures} anchor=({Anchor.Position().X:0.###},{Anchor.Position().Y:0.###},{Anchor.Position().Z:0.###}) "
        + $"{WaterSummary()} {Ground.Summary()} {VerifySummary()}";

    public string CutSummary() => $"cuts[placements={CutPlacements} surfaces={CutSurfaces} fallbacks={CutFallbacks}]";

    public string VerifySummary() => $"verify[locations={VerifyLocations} checked={VerifyChecked} rows={VerifyRows}]";
}

/// <summary>
/// One built location (the browser's resident TILE): its group in the world (the pick target — every mesh
/// under it answers <see cref="Loc"/>'s id, as <c>tile.group.userData.locationId</c> does), the facts the
/// overview needs about it (centre, footprint width, reading height, whether it can be opened) and whether
/// it is shown open right now. The location is mounted ONCE (shell, outdoor pieces and its interior held at fade 0);
/// opening and closing only move <see cref="Fade"/> (<see cref="WorldBuilder.TickView"/>).
/// </summary>
public sealed class LocationSlot
{
    public required LocationInfo Loc { get; init; }
    public required Ring Ring { get; init; }
    /// <summary>The location group, (pos_x, ground datum, pos_z), turned by yaw (<c>tile.group</c>, <c>tile.center</c>).</summary>
    public required Node3D Group { get; set; }
    /// <summary><c>footprintWidth</c> (<c>tile.width</c>).</summary>
    public double Width { get; init; }
    /// <summary>
    /// <c>tile.height</c>: the vertical extent of the building model(s) or of the far-view shell, else the reading
    /// height of <c>buildPlace</c>. A rebuild that places nothing measurable keeps the last measured value.
    /// </summary>
    public double Height { get; set; }
    /// <summary><see cref="Height"/> came from a model or shell, not from the default.</summary>
    public bool HeightMeasured { get; set; }
    /// <summary><c>openable(tile)</c>: an interior exists and the place is a building, a shell area or a ground model.</summary>
    public bool Openable { get; set; }
    /// <summary>The fade TARGET: the open location (the singleton) fades its interior in, every other one out.</summary>
    public bool Open { get; set; }
    /// <summary>The crossfade and occlusion state of the mounted group.</summary>
    public LocationFade Fade { get; init; } = new();
    /// <summary>
    /// <c>tile.levelFilter</c>: the storey the open view shows — view state, 0 at the mount (buildTile), moved by the
    /// level switch (<see cref="WorldBuilder.SetLevel"/>); every storey is mounted, so a switch rebuilds nothing. The
    /// slot lives as long as the world knows the place, so it is also the per-session memory (main.ts
    /// <c>storeyByPlace</c> only bridges a streamed-out tile, which this client does not have yet).
    /// </summary>
    public int LevelFilter { get; set; }
    /// <summary>The storey passes of the mounted location (room groups, slabs, walls, marks, labels, the switch data).</summary>
    public LocationStoreys Storeys { get; init; } = new();
    /// <summary>The § B5a report of the mount (<c>window.__sceneVerify[loc]</c>).</summary>
    public VerifyReport? Verify { get; set; }
    /// <summary>Bumped when the location is dropped; work for it that finishes later is thrown away.</summary>
    internal int Generation;
    /// <summary>The scene's <c>signature</c> at the mount (the 60 s sweep remounts on a change).</summary>
    public string? Signature { get; init; }
    /// <summary>The payload's <c>area_detail</c> (the interior tier of a closed area scene stays low).</summary>
    public bool AreaDetail { get; init; }
    /// <summary>
    /// Every model spec of the mount with what fills it now (the browser's <c>tile.placedModels</c>): the tier swap
    /// replaces the node in place, the re-lift moves it, the cuts belong to the record.
    /// </summary>
    public List<PlacedModel> Placements { get; init; } = new();
    /// <summary>The tier the building model(s) / the dioramas and props show (<c>buildingTierByLoc</c> / <c>interiorTierByLoc</c>).</summary>
    public string BuildingTier { get; set; } = "low";
    public string InteriorTier { get; set; } = "low";
    /// <summary>The far-view shell copies of a place whose building model did not stand at the mount (dropped when one arrives).</summary>
    public List<MeshInstance3D> FarShell { get; init; } = new();
    /// <summary>Counts every change of the meshes under <see cref="Group"/> (tier swap, re-datum): the pick cache follows it.</summary>
    public int MeshVersion { get; set; }
}

/// <summary>
/// One model spec of a mounted scene and what fills it (sceneRecipe.ts <c>PlacedSceneModel</c>): the mesh, the grey
/// placeholder or nothing (a missing mesh keeps its record, so a later tier swap can still bring one), the URL it was
/// loaded from, the § A16.9 lift it stands on and its cut materials.
/// </summary>
public sealed class PlacedModel
{
    public required SceneModelSpec Spec { get; init; }
    /// <summary>The node it hangs in (room group, interior, the location group).</summary>
    public required Node3D Parent { get; init; }
    public Node3D? Node { get; set; }
    public string Url { get; set; } = "";
    /// <summary>The URL a swap is loading right now (<c>rec.wantUrl</c>): a newer wish discards an older answer.</summary>
    public string? WantUrl { get; set; }
    public double Lift { get; set; }
    public bool Placeholder { get; set; }
    public CutHandle? Cut { get; set; }
    public bool IsBuilding => Spec.Role == "building";
}

/// <summary>
/// Builds the world from an <see cref="IWorldSource"/> — the server online, the fixtures in <c>--check</c>, a
/// payload dump in <c>--offline</c>; all paths run THIS code.
///
///   1. <c>/play/heightfield</c> overview, <c>/play/worldmap</c> (placement) and <c>/world/locations?view=3d</c>
///   2. the anchor (<see cref="Anchor.FromWorld"/> — the browser bench rule)
///   3. the indexed 2 m tiles within <see cref="TileRadiusM"/> of the anchor (<c>HEIGHT_TILE_RADIUS_M</c>)
///   4. terrain meshes (overview with the tiled cells left out, one mesh per tile; a wet tile lifted onto its
///      water mirror), dressed in the browser's ground material + its water variant (<see cref="GroundSurfaces"/>)
///   5. per placed location in reach (<see cref="LocationView"/>): a group at (pos_x, ground, pos_z) turned by
///      +yaw_deg (§ A1.1); its scene recipe mounted ONCE as the browser mounts it — building model(s), outdoor
///      model specs, the outdoor rooms' primitives, the far-view shell of a place without a model, and its
///      interior (primitives of every storey, in the near ring the indoor model specs, in room groups) held at
///      fade 0 until it is opened (<see cref="SetOpen"/>, crossfaded by <see cref="TickView"/>, which also applies
///      the shown storey, <see cref="SetLevel"/>); then its § B5a verify
///   6. the world props of <c>/play/worldmap</c> (§ A9a)
/// </summary>
public sealed partial class WorldBuilder
{
    /// <summary><c>HEIGHT_TILE_RADIUS_M</c> = <c>FOG_FAR_M</c> + 40 (client3d/src/scene/heightTiles.ts).</summary>
    public const double TileRadiusM = LayerCut.TileRadiusM;
    private const int SceneConcurrency = 4;
    /// <summary>Keyframe 0 of the bench path, relative to the anchor: where the static tiers are measured from.</summary>
    public static readonly Vector3 StartCameraOffset = new(0, 24, 40);
    /// <summary><c>WORLD_PROP_LOD_SCALE</c> (worldProps.ts): landmarks keep their tiers 3× as far as scatter.</summary>
    public const double WorldPropLodScale = 3;

    private readonly IWorldSource _source;
    private readonly Action<string> _log;
    private readonly bool _strict;
    private ModelCache _models = null!;
    private RecipeMaterials _materials = null!;
    private SurfaceLibrary? _library;

    public WorldHeight? Height { get; private set; }
    /// <summary>The GLB cache of the build (free its templates when the world goes).</summary>
    public ModelCache? Models => _models;
    /// <summary>The <c>/world/locations?view=3d</c> rows of the build (names for the anchor's goto match).</summary>
    public IReadOnlyList<LocationInfo> Details { get; private set; } = Array.Empty<LocationInfo>();
    /// <summary>The <c>/play/worldmap</c> payload the build used (the anchor's fallback snapshot).</summary>
    public JsonElement? FirstMap { get; private set; }
    /// <summary>The ground surfaces of the build (null = plain material).</summary>
    public GroundSurfaces? Ground { get; private set; }
    /// <summary><c>--plain-ground</c>: keep the S1a vertex-colour terrain (no layer requests at all).</summary>
    public bool PlainGround { get; init; }
    /// <summary><c>--no-water</c>: no lift, no water variant (the browser bench's <c>&amp;water=0</c>).</summary>
    public bool NoWater { get; init; }
    /// <summary>
    /// The § B5a log: true = the full table per mounted location (the browser's <c>?verify=1</c>; always in
    /// <c>--check</c>, <c>--verify</c> in play), false = only a location with deviations is logged.
    /// </summary>
    public bool VerifyFull { get; init; }

    private readonly Dictionary<string, LocationSlot> _slots = new();
    /// <summary>Every placed location id the world has taken in (built or out of reach) — main.ts <c>places</c>.</summary>
    private readonly HashSet<string> _known = new();
    /// <summary>The stream points of the build (avatar, anchor): the rings of revealed locations are measured from them.</summary>
    private List<(double X, double Z)> _points = new();
    private Node3D? _places;
    private Vector3 _tierCamera;
    /// <summary>The avatar's lock verdicts the marks wear (<see cref="SetLocks"/>).</summary>
    private LockState _locks = LockState.None;

    /// <summary>The built locations by id (the browser's resident tiles). Filled by <see cref="BuildAsync"/>.</summary>
    public IReadOnlyDictionary<string, LocationSlot> Slots => _slots;

    /// <summary>A location group left the world (<see cref="DropVanished"/>; the pick cache drops its entry).</summary>
    public event Action<LocationSlot>? Dropped;

    /// <param name="strict">true in <c>--check</c>: any failure aborts; online a broken location is logged and skipped.</param>
    public WorldBuilder(IWorldSource source, Action<string> log, bool strict)
    {
        _source = source;
        _log = log;
        _strict = strict;
        VerifyFull = strict;
    }

    /// <summary>
    /// The world data the start fetches before anything is built (main.ts: <c>Promise.all(getLocations3d,
    /// getWorldMap, getSurfaceTextures)</c> — here the heightfield, the worldmap and the location details; the
    /// surface library follows with the ground). One unit, so a retry repeats all three.
    /// </summary>
    public sealed record BootData(HeightfieldOverview Overview, JsonElement Map, JsonElement Locations);

    /// <summary>
    /// The boot's view of the build: <see cref="Stage"/> hears <c>world</c> (the boot data is in), <c>scenes</c>
    /// (every scene recipe of the start ring is fetched) and <c>tiles</c> (the start ring and the world props
    /// stand); <see cref="Bootstrap"/> wraps the boot data fetch (the client's retry with its title notes);
    /// <see cref="Locations3d"/> replaces the plain details request (the client's conditional cache).
    /// </summary>
    public sealed class BuildHooks
    {
        public Action<string>? Stage { get; init; }
        public Func<Func<Task<BootData>>, Task<BootData>>? Bootstrap { get; init; }
        public Func<Task<JsonElement>>? Locations3d { get; init; }
        /// <summary>The boot's world map (main.ts <c>api.getWorldMap(showAll)</c>: the stored start view); default the source's.</summary>
        public Func<Task<JsonDocument>>? WorldMap { get; init; }
    }

    /// <summary>The boot data, the three requests at once (one failure fails the unit).</summary>
    public async Task<BootData> FetchBootDataAsync(Func<Task<JsonElement>>? locations3d = null,
                                                   Func<Task<JsonDocument>>? worldMap = null)
    {
        var hf = Fetch(_source.GetHeightfieldAsync(), root => HeightfieldOverview.Parse(root));
        var map = Fetch(worldMap is not null ? worldMap() : _source.GetWorldMapAsync(), root => root.Clone());
        var loc = locations3d is not null ? locations3d() : Fetch(_source.GetLocations3dAsync(), root => root.Clone());
        await Task.WhenAll(hf, map, loc);
        return new BootData(hf.Result, map.Result, loc.Result);

        static async Task<T> Fetch<T>(Task<JsonDocument> request, Func<JsonElement, T> take)
        {
            using var doc = await request;
            return take(doc.RootElement);
        }
    }

    public async Task<WorldStats> BuildAsync(Node3D root, string? gotoQuery, BuildHooks? hooks = null)
    {
        var stats = new WorldStats();
        var boot = hooks?.Bootstrap is { } wrap
            ? await wrap(() => FetchBootDataAsync(hooks.Locations3d, hooks.WorldMap))
            : await FetchBootDataAsync(hooks?.Locations3d, hooks?.WorldMap);
        var overview = boot.Overview;
        var mapRoot = boot.Map;
        var locations = LocationInfo.ParseList(mapRoot);
        var details = LocationInfo.ParseList(boot.Locations);
        Details = details;
        FirstMap = mapRoot;
        hooks?.Stage?.Invoke("world");
        _log($"heightfield {overview.Grid.Cols}x{overview.Grid.Rows} step {overview.Grid.Step} m, "
             + $"{overview.TileIndex.Count} indexed tiles; worldmap {locations.Count} locations, "
             + $"view=3d {details.Count}");

        stats.Anchor = Anchor.FromWorld(mapRoot, details, overview.Grid, gotoQuery);
        _log($"anchor {stats.Anchor.Position()} ({stats.Anchor.Source}{(stats.Anchor.LocationId is { } id ? ", " + id : "")})");

        var height = Height = new WorldHeight(overview);
        var keys = height.IndexedTilesNear(stats.Anchor.Position().X, stats.Anchor.Position().Z, TileRadiusM);
        for (int i = 0; i < keys.Count; i += AnimaApi.HeightTileBatchMax)
        {
            var batch = keys.Skip(i).Take(AnimaApi.HeightTileBatchMax).ToList();
            using var tileDoc = await _source.GetHeightTilesAsync(batch);
            height.AddTiles(HeightTile.ParseBatch(tileDoc.RootElement));
        }

        var terrain = new Node3D { Name = "Terrain" };
        root.AddChild(terrain);
        var (ov, ovStats) = TerrainBuilder.BuildOverview(overview.Grid, overview.TileM, height.HasTile);
        terrain.AddChild(ov);
        stats.OverviewVertices = ovStats.Vertices;
        stats.OverviewTriangles = ovStats.Triangles;
        bool liftWater = !NoWater && !PlainGround;
        var tileNodes = new Dictionary<MeshInstance3D, HeightTile>();
        foreach (var tile in height.Tiles.OrderBy(t => t.Key.Tx).ThenBy(t => t.Key.Tz))
        {
            var (node, ts) = TerrainBuilder.BuildTile(tile, liftWater);
            terrain.AddChild(node);
            tileNodes[node] = tile;
            stats.Tiles++;
            stats.TileVertices += ts.Vertices;
            stats.TileTriangles += ts.Triangles;
        }
        _log($"terrain: overview {stats.OverviewVertices} v / {stats.OverviewTriangles} t, "
             + $"{stats.Tiles} tiles {stats.TileVertices} v / {stats.TileTriangles} t");
        stats.Ground = await DressGround(terrain, height, stats.Anchor);
        ApplyWaterOutcome(stats, tileNodes);

        _library = await SurfaceLibrary.LoadAsync(_source, _log);
        _models = new ModelCache(_source, _log);
        _materials = new RecipeMaterials(_library);

        // The view: the avatar opens its location, the stream points are its position and the camera focus.
        var avatar = AvatarOf(mapRoot, locations);
        var anchorXZ = (X: (double)stats.Anchor.X, Z: (double)stats.Anchor.Z);
        var points = new List<(double X, double Z)>();
        if (avatar.Pos is { } ap) points.Add(ap);
        points.Add(anchorXZ);
        _points = points;
        var camera = _tierCamera = _viewCamera = stats.Anchor.Position() + StartCameraOffset;
        _heightRevision = height.Revision;

        var places = _places = new Node3D { Name = "Locations" };
        root.AddChild(places);
        var placed = locations.Where(l => l.IsPlaced).ToList();
        stats.Locations = placed.Count;
        var jobs = new List<(LocationInfo Loc, Ring Ring, bool Pinned)>();
        foreach (var loc in placed)
        {
            _known.Add(loc.Id);
            bool pinned = loc.Id == avatar.LocationId;
            var ring = LocationView.RingFor(LocationView.PlaceDistance(loc, points), pinned);
            if (ring == Ring.Gone) { stats.LocationsGone++; continue; }
            jobs.Add((loc, ring, pinned));
        }
        // main.ts: `scenes.prime(residentIds)` → 'scenes', then the tiles → 'tiles'. The recipes of the start ring
        // first, all of them; then each location is built from its recipe.
        var scenes = await PrimeScenes(jobs.Select(j => j.Loc), stats);
        hooks?.Stage?.Invoke("scenes");
        using var gate = new SemaphoreSlim(SceneConcurrency);
        var tasks = jobs.Select(async job =>
        {
            var (loc, ring, pinned) = job;
            if (!scenes.TryGetValue(loc.Id, out var doc)) return;   // its fetch failed (counted there)
            await gate.WaitAsync();
            try
            {
                if (doc is null) return;   // 404: nothing to compose
                // The avatar's location starts open (main.ts arrivalLocId / bootPin); every other one closed.
                var built = await BuildFromScene(loc, doc.RootElement, height, stats, ring, pinned, camera);
                places.AddChild(built.Group);
                if (built.Storeys.BoundaryMarks is { } bm) places.AddChild(bm);
                lock (_slots) _slots[loc.Id] = built;
            }
            catch (Exception e) when (!_strict)
            {
                stats.Failures++;
                stats.Problems.Add($"{loc.Id}: {e.Message}");
                _log($"location {loc.Id} ({loc.Name}) failed: {e.Message}");
            }
            finally
            {
                doc?.Dispose();
                gate.Release();
            }
        }).ToList();
        await Task.WhenAll(tasks);

        await BuildWorldProps(root, mapRoot, height, stats, camera);
        hooks?.Stage?.Invoke("tiles");
        _log($"recipe: {stats.Recipe.Primitives} primitives drawn ({stats.Recipe.Plates} plates, {stats.Recipe.Walls} walls, "
             + $"{stats.Recipe.Extras} extras; {stats.Recipe.ShellCopies} far-shell copies), {stats.Recipe.Skipped} skipped "
             + $"({stats.Recipe.SkipSummary()}); surfaces {_library.Loaded} loaded / {_library.Failed} failed; "
             + $"{_materials.Count} materials");
        _log($"models: {stats.Models.Summary()}; {_models.Loaded} GLBs loaded ({_models.Bytes / 1048576.0:0.0} MiB), "
             + $"{_models.Failed} failed, {_models.Neutralized} materials' metalness neutralised; {stats.CutSummary()}");
        _log($"water: {stats.WaterSummary()}");
        return stats;
    }

    /// <summary>The avatar's row: location (opened), room (its storey) and position (a stream point).</summary>
    private static (string? LocationId, string? RoomId, (double X, double Z)? Pos) AvatarOf(
        JsonElement map, List<LocationInfo> locations)
    {
        var name = Json.Str(map, "avatar");
        if (name.Length == 0) return (null, null, null);
        foreach (var c in Json.Arr(map, "characters"))
        {
            if (Json.Str(c, "name") != name) continue;
            var loc = Json.Str(c, "location_id");
            (double, double)? pos = null;
            if (c.TryGetProperty("pos", out var p) && p.ValueKind == JsonValueKind.Object
                && Json.NumOrNull(p, "x") is double x && Json.NumOrNull(p, "z") is double z)
                pos = (x, z);
            else if (locations.FirstOrDefault(l => l.Id == loc) is { IsPlaced: true } row)
                pos = (row.PosX!.Value, row.PosZ!.Value);
            return (loc.Length > 0 ? loc : null, Json.Str(c, "room_id"), pos);
        }
        return (null, null, null);
    }

    /// <summary>
    /// The ground surfaces on every terrain mesh. Never fatal: any failure keeps the plain material and is
    /// logged (and reported in <see cref="GroundStats.Reason"/>), online and in <c>--check</c> alike.
    /// </summary>
    private async Task<GroundStats> DressGround(Node3D terrain, WorldHeight height, AnchorInfo anchor)
    {
        var (stats, ground) = await DressGroundAsync(_source, terrain, height, anchor, _log, PlainGround, !NoWater);
        Ground = ground;
        return stats;
    }

    /// <summary>The one ground step (also driven directly by the check's fallback cases).</summary>
    public static async Task<(GroundStats Stats, GroundSurfaces? Ground)> DressGroundAsync(
        IWorldSource source, Node3D terrain, WorldHeight height, AnchorInfo anchor, Action<string> log, bool plain,
        bool water = true)
    {
        if (plain) return (new GroundStats { Reason = "--plain-ground" }, null);
        try
        {
            var ground = await GroundSurfaces.LoadAsync(source, height, anchor.X, anchor.Z, log, water);
            ground.ApplyTo(terrain.GetChildren().OfType<GeometryInstance3D>());
            return (ground.Stats, ground);
        }
        catch (Exception e)
        {
            log($"ground surfaces failed, keeping the plain material: {e.Message}");
            return (new GroundStats { Reason = e.Message }, null);
        }
    }

    /// <summary>A wet tile that ends up without the water variant goes back to its bed (no lifted plain ground).</summary>
    private void ApplyWaterOutcome(WorldStats stats, Dictionary<MeshInstance3D, HeightTile> tiles)
    {
        var wet = tiles.Keys.Where(n => n.HasMeta("wet")).ToList();
        if (NoWater) { stats.WaterMode = "off: --no-water"; return; }
        if (wet.Count == 0)
        {
            stats.WaterMode = tiles.Values.Any(t => t.Water is { } w && w.Wet > 0) ? "none: plain ground" : "none";
            return;
        }
        if (Ground?.WaterMaterial is null)
        {
            foreach (var n in wet)
            {
                var (dry, _) = TerrainBuilder.BuildTile(tiles[n], false);
                n.Mesh = dry.Mesh;
                n.RemoveMeta("wet");
                dry.Free();
            }
            stats.WaterMode = "none: water variant unavailable";
            return;
        }
        stats.WaterMode = "drawn";
        stats.WaterTiles = wet.Count;
        stats.WaterKinds = Ground.Stats.WaterKinds;
        stats.WaterTexels = Ground.Stats.WaterTexels;
        stats.WaterAreas = Ground.Stats.WaterAreas;
    }

    /// <summary>
    /// The scene recipes of these locations, at most <see cref="SceneConcurrency"/> requests at a time: id → the
    /// payload (null for a 404). A failed request is counted and logged here (online) and has no entry.
    /// </summary>
    private async Task<Dictionary<string, JsonDocument?>> PrimeScenes(IEnumerable<LocationInfo> locs, WorldStats stats)
    {
        var scenes = new Dictionary<string, JsonDocument?>();
        using var gate = new SemaphoreSlim(SceneConcurrency);
        await Task.WhenAll(locs.Select(async loc =>
        {
            await gate.WaitAsync();
            try
            {
                var doc = await _source.GetLocationSceneAsync(loc.Id);
                lock (scenes) scenes[loc.Id] = doc;
            }
            catch (Exception e) when (!_strict)
            {
                stats.Failures++;
                stats.Problems.Add($"{loc.Id}: {e.Message}");
                _log($"location {loc.Id} ({loc.Name}) failed: {e.Message}");
            }
            finally { gate.Release(); }
        }));
        return scenes;
    }

    /// <summary>
    /// One location from its scene recipe, MOUNTED ONCE and built DETACHED (the caller hangs
    /// <see cref="LocationSlot.Group"/> into the world) — sceneRecipe.ts <c>mountShell</c> + <c>mountDetail</c>:
    ///
    ///   • the shell layer: every building model (a fading one — display shell / shell_area / roof_only — is a roof
    ///     part of the crossfade; its cutouts go on per fragment (CutMaterials)), the outdoor
    ///     specs, the outdoor rooms' primitives and, for a place without a building model, the far-view shell;
    ///   • the interior group <c>g</c> (hidden at fade 0): the interior primitives of every storey and — in the near
    ///     ring only, like <c>mountDetail</c> — the indoor specs, each in its room's group.
    /// <paramref name="wantOpen"/> sets the fade TARGET (the avatar's location at the boot) if it can be opened
    /// (<c>openable(tile)</c>). EVERY storey is mounted (Task 16): room groups per declared room, the storey rules filed
    /// in <see cref="LocationStoreys"/>, the door marks (near ring, buildings), the boundary marks (world frame) and the
    /// room labels; the storey shown starts at 0 (buildTile). Every mount ends with its § B5a verify
    /// (<see cref="SceneVerifier"/>) over all of it.
    /// </summary>
    private async Task<LocationSlot> BuildFromScene(LocationInfo loc, JsonElement sceneRoot, WorldHeight height,
                                                    WorldStats stats, Ring ring, bool wantOpen, Vector3 camera)
    {
        var scene = ScenePayload.Parse(sceneRoot);
        stats.Scenes++;
        if (Math.Abs(scene.K - 1) > 1e-9)
            _log($"location {loc.Id}: scene k={scene.K} (contract says 1) — drawn unscaled");

        double x = loc.PosX!.Value, z = loc.PosZ!.Value;
        double datum = height.GroundAt(x, z);
        var group = new Node3D
        {
            Name = $"Loc_{loc.Id}",
            Position = new Vector3((float)x, (float)datum, (float)z),
            Rotation = new Vector3(0, (float)(loc.YawDeg * Math.PI / 180.0), 0),
        };
        group.SetMeta("location_id", loc.Id);

        var (isBuilding, natureSite) = LocationView.Kind(loc);
        var buildings = scene.Models.Where(m => m.Role == "building").ToList();
        bool shellArea = scene.AreaDetail || buildings.Any(m => m.Display == "shell_area");
        bool groundModel = buildings.Any(m => m.Display == "ground");
        bool hasInterior = SceneView.HasInterior(scene.Plates.Count, scene.FloorPlanCount, scene.Walls.Count, scene.Extras.Count,
                                                 scene.MarkerCount, scene.Models.Select(m => m.Role));
        // openable(tile) + the singleton: only the location the caller opens fades in.
        bool openable = SceneView.Openable(hasInterior, isBuilding, shellArea, groundModel);
        bool open = wantOpen && openable;
        if (open) stats.OpenLocation = loc.Id;
        var roomLevel = scene.Rooms.GroupBy(r => r.RoomId).ToDictionary(g => g.Key, g => g.First().Level);
        // buildTile: levelFilter 0 — the overview opens every location on the ground floor (the avatar's storey is
        // followed only in the embodied mode, followAvatarStorey).
        const int levelFilter = 0;
        var outdoor = LocationView.OutdoorRoomIds(scene);
        bool RoomShown(string roomId) => outdoor.Contains(roomId)
            || !roomLevel.TryGetValue(roomId, out var lv) || SceneView.RoomVisible(false, lv, levelFilter);

        double width = LocationView.FootprintWidth(loc);
        string buildingTier = LocationView.BuildingTier(ring, camera.DistanceTo(group.Position), width);
        string interiorTier = LocationView.InteriorTier(ring, scene.AreaDetail, open);
        var models = new ModelStats();
        var fade = new LocationFade { ShellArea = shellArea };
        var interior = hasInterior ? new Node3D { Name = "Interior" } : null;
        if (interior is not null) group.AddChild(interior);
        fade.Interior = interior;
        // The room groups (mountShell step 5): an outdoor / always-visible room off the tile, every other one in the
        // interior group; the first entry of an id wins (as roomLevel does).
        var storeys = new LocationStoreys
        {
            Buttons = StoreyView.HasLevelSwitch(scene.Levels) ? StoreyView.SwitchButtons(scene.Levels) : new List<LevelButton>(),
            Elevator = StoreyView.ElevatorAnchor(scene.Extras),
            StoreyM = scene.StoreyM,
            FloorY = scene.FloorYOrNull,
            HasBasement = StoreyView.HasBasement(scene.Levels),
        };
        foreach (var r in scene.Rooms)
        {
            if (storeys.Rooms.ContainsKey(r.RoomId)) continue;
            bool od = outdoor.Contains(r.RoomId);
            var parentNode = od ? group : interior;
            if (parentNode is null) continue;   // no interior: nothing would ever hang in it
            var node = new Node3D { Name = "Room_" + NodeName(r.RoomId) };
            parentNode.AddChild(node);
            storeys.Rooms[r.RoomId] = new LocationStoreys.RoomGroup(r.RoomId, node, r.Level, od);
        }
        // parentFor(room) of mountModels: the room's group, else the tile for an outdoor spec, else the interior.
        Node3D? ParentFor(string roomId, bool isOut)
            => roomId.Length > 0 && storeys.Rooms.TryGetValue(roomId, out var rg) ? rg.Node : isOut ? group : interior;
        var verify = new SceneVerifier();

        // ── Building model(s): all mounted; a fading one is a roof part, its cutouts (a kept plan hull / ground model,
        //    or any building spec that carries them) open with the fade. ──
        var placements = new List<PlacedModel>();
        bool solidBuildingPlaced = false;
        Aabb? buildingBox = null;
        foreach (var spec in buildings)
        {
            var node = await SceneModels.PlaceAsync(_models, spec, buildingTier, "building", group, 0, models, _materials);
            var rec = new PlacedModel
            {
                Spec = spec, Parent = group, Node = node, Url = ModelVariants.PickModelVariant(spec, buildingTier),
                Placeholder = node is not null && SceneModels.IsPlaceholder(node),
            };
            placements.Add(rec);
            if (node is null) continue;
            if (!spec.RoofOnly) solidBuildingPlaced = true;
            var nb = ModelPlacement.Measure(node, Transform3D.Identity);
            buildingBox = buildingBox is { } bb ? bb.Merge(nb) : nb;
            ApplyBuildingModel(group, fade, rec);
            if (spec.Display != "ground" && !spec.PlanHull && open) models.Faded++;
            if (rec.Url.Length > 0 && (await _models.GetAsync(rec.Url)) is { } t)
            {
                stats.Buildings++;
                if (t.Compressed) stats.BuildingsCompressed++;
                stats.BuildingVertices += t.Counts.Vertices;
                stats.BuildingIndices += t.Counts.Indices;
            }
        }

        // ── The other specs: outdoor ones off the tile; indoor ones into their room groups (near ring, every storey). ──
        var jobs = new List<Task>();
        foreach (var spec in scene.Models.Where(m => m.Role != "building"))
        {
            bool isOut = LocationView.IsOutdoor(scene, spec.RoomId);
            if (!isOut)
            {
                // mountDetail runs for the near ring only; its parentFor(room) is the room group or the interior.
                if (ring != Ring.Near || interior is null) { models.Interior++; continue; }
                // Mounted all the same: its room group hides it until the switch shows its storey.
                if (!RoomShown(spec.RoomId)) models.Storey++;
            }
            var parent = ParentFor(spec.RoomId, isOut)!;
            double lift = GroundLift(group, spec, height, datum);
            var rec = new PlacedModel { Spec = spec, Parent = parent, Url = ModelVariants.PickModelVariant(spec, interiorTier), Lift = lift };
            placements.Add(rec);
            jobs.Add(PlaceAndRecord(rec));
        }
        await Task.WhenAll(jobs);

        async Task PlaceAndRecord(PlacedModel rec)
        {
            var node = await SceneModels.PlaceAsync(_models, rec.Spec, interiorTier, SceneModels.KindOf(rec.Spec), rec.Parent,
                                                    rec.Lift, models, _materials);
            rec.Node = node;
            rec.Placeholder = node is not null && SceneModels.IsPlaceholder(node);
            // The depth cut (also on a stand-in box) and the room clip (meshes only), after the node hangs in place.
            if (node is not null) rec.Cut = CutPlacement(group, rec);
        }
        foreach (var rec in placements)
            if (rec.Cut is { } h)
            {
                stats.CutPlacements++;
                stats.CutSurfaces += h.Entries.Count;
                stats.CutFallbacks += h.Fallbacks;
            }

        // ── Recipe primitives by layer: outdoor rooms, the interior, the far-view shell of a modelless place. ──
        bool farShell = !solidBuildingPlaced
                        && SceneView.FarShellSource(isBuilding, natureSite, scene.AreaDetail, false,
                                                    scene.Plates.Count, scene.Walls.Count) == "recipe";
        var kinds = scene.Plates.Select(p => p.TextureKind).Concat(scene.Walls.Select(w => w.TextureKind))
                         .Concat(scene.Extras.Select(e => e.TextureKind)).Where(k => k.Length > 0).Append("floor");
        await _library!.PreloadAsync(kinds);
        var (layers, rs) = RecipeMeshes.Build(scene, new RecipeView(open, levelFilter, farShell), _materials, "Recipe");
        foreach (var piece in layers.Pieces)
        {
            // Every non-outdoor piece implies an interior (hasInterior counts plates, walls and extras).
            var parent = ParentFor(piece.Unit.Room, piece.Unit.Outdoor) ?? group;
            parent.AddChild(piece.Mesh);
            if (piece.Unit.Outdoor) fade.OutdoorCull.Add(piece.Mesh);
            storeys.Add(piece);
        }
        foreach (var m in layers.Shell)
        {
            group.AddChild(m);
            fade.RoofParts.Add(m);
        }
        // The overlays: door marks (a building's thresholds, near ring — buildDoorMarks), boundary marks (every
        // resident, world frame — buildBoundaryMarks), the room names (not on an area location).
        var frame0 = new TileFrame(new Overview.Vec3(x, datum, z), group.Rotation.Y);
        if (isBuilding && ring == Ring.Near) storeys.BuildDoorMarks(group, scene);
        storeys.BuildBoundaryMarks(loc.Id, frame0, scene, height.GroundAt);
        if (!StoreyView.AreaLocation(natureSite, isBuilding, scene.AreaDetail, scene.Models))
            AddRoomLabels(storeys, scene, DetailRooms(loc.Id));
        // tile.height: the building model(s) measured (a roof-only part together with the rest, as
        // `box.expandByObject(tile.shell)` reads it), else the far shell, else buildPlace's reading height.
        double? measured = buildingBox is { } box && box.Size.Y > 0 ? box.Size.Y : null;
        if (measured is null && farShell)
        {
            Aabb? shellBox = null;
            foreach (var m in layers.Shell)
                if (m.Mesh is { } mesh)
                {
                    var b = m.Transform * mesh.GetAabb();
                    shellBox = shellBox is { } sb ? sb.Merge(b) : b;
                }
            if (shellBox is { } sh && sh.Size.Y > 0) measured = sh.Size.Y;
        }

        // ── § B5a: every mounted primitive and placement against its spec, in the tile frame. ──
        var frame = group.Transform;
        var origin = new Overview.Vec3(group.Position.X, group.Position.Y, group.Position.Z);
        double yaw = group.Rotation.Y;
        foreach (var mp in layers.Measured)
            verify.Primitive(mp.Name, WorldBox(mp.Local, frame), origin, yaw, mp.Targets);
        verify.Total = placements.Count;
        foreach (var rec in placements) VerifyPlacement(verify, rec.Spec, rec.Node, rec.Lift, group, origin, yaw);
        var report = verify.Report(loc.Id);
        LogVerify(report);

        fade.Collect(group);
        storeys.Apply(levelFilter, 0, openable, fade);
        storeys.ApplyLocks(_locks, loc.Id);
        lock (stats)
        {
            stats.Recipe.Add(rs);
            Merge(stats.Models, models);
            stats.VerifyLocations++;
            stats.VerifyChecked += report.Checked;
            stats.VerifyRows += report.Rows.Count;
        }
        if (rs.Primitives > 0 || open)
            _log($"location {loc.Id} ({loc.Name}): ring={ring.ToString().ToLowerInvariant()}{(open ? $" OPEN storey {levelFilter}" : "")}"
                 + $"{(farShell ? " far-shell" : "")} — {rs.Primitives} primitives, skipped {rs.SkipSummary()}, "
                 + $"interior mounted {rs.InteriorMounted}; {models.Summary()}");
        return new LocationSlot
        {
            Loc = loc, Ring = ring, Group = group, Width = width, Openable = openable, Open = open,
            Height = measured ?? Overview.EventPinRule.DefaultPlaceHeight(isBuilding, natureSite, LocationView.DetectStyle(loc)),
            HeightMeasured = measured is not null,
            Fade = fade, LevelFilter = levelFilter, Verify = report, Storeys = storeys,
            Signature = scene.Signature, AreaDetail = scene.AreaDetail, Placements = placements,
            BuildingTier = buildingTier, InteriorTier = interiorTier, FarShell = layers.Shell.ToList(),
        };
    }

    /// <summary>The room names of a location: its <c>/world/locations?view=3d</c> row's <c>rooms</c> (empty when unknown).</summary>
    private IReadOnlyDictionary<string, string> DetailRooms(string id)
    {
        foreach (var d in Details) if (d.Id == id) return d.Rooms;
        return new Dictionary<string, string>();
    }

    /// <summary>
    /// mountShell step 16: one label per room group whose room has a non-empty name, at the room rectangle's centre
    /// (<see cref="StoreyView.RoomHulls"/> / <see cref="StoreyView.RectCentre"/>, else the tile origin), its storey's
    /// floor + min(1.5, 0.8·storey_m) up, in the room's group.
    /// </summary>
    private static void AddRoomLabels(LocationStoreys storeys, ScenePayload scene, IReadOnlyDictionary<string, string> names)
    {
        var hulls = StoreyView.RoomHulls(scene);
        foreach (var rg in storeys.Rooms.Values)
        {
            if (!names.TryGetValue(rg.Id, out var name) || name.Length == 0) continue;
            var centre = hulls.TryGetValue(rg.Id, out var hull) ? StoreyView.RectCentre(hull) : null;
            var p = StoreyView.RoomLabelPosition(centre, scene.FloorYOrNull(rg.Level), scene.StoreyM);
            storeys.Labels.Add(new RoomLabel(rg.Id, name, rg.Node, new Vector3((float)p.X, (float)p.Y, (float)p.Z)));
        }
    }

    /// <summary>A room id as a node name (Godot refuses <c>. : @ / " %</c> in names).</summary>
    private static string NodeName(string id)
    {
        var chars = id.ToCharArray();
        for (int i = 0; i < chars.Length; i++)
            if (chars[i] is '.' or ':' or '@' or '/' or '"' or '%') chars[i] = '_';
        return new string(chars);
    }

    /// <summary>A box of the location frame in the world (three's <c>Box3.applyMatrix4</c>: the AABB of the 8 corners).</summary>
    public static VBox WorldBox(VBox local, Transform3D frame)
    {
        var a = frame * new Aabb(new Vector3((float)local.Min.X, (float)local.Min.Y, (float)local.Min.Z),
                                 new Vector3((float)(local.Max.X - local.Min.X), (float)(local.Max.Y - local.Min.Y),
                                             (float)(local.Max.Z - local.Min.Z)));
        return ToVBox(a);
    }

    private static VBox ToVBox(Aabb a) => new(new Overview.Vec3(a.Position.X, a.Position.Y, a.Position.Z),
                                              new Overview.Vec3(a.End.X, a.End.Y, a.End.Z));

    /// <summary>
    /// <c>verify.placement</c> / <c>verify.skip</c> of one spec (mountModels): nothing placed → the <c>geladen</c> row;
    /// a mesh or placeholder → its world box and the outer node's world position against the spec (with its
    /// storey-0 lift); a real mesh with a baked <c>surface</c> (not <c>fit</c>) also gets <c>surface_scale</c> (the
    /// outer scale against <c>surfaceScale</c>) and <c>surface_box</c> (the fix group's box against the bake's).
    /// </summary>
    public static void VerifyPlacement(SceneVerifier v, SceneModelSpec spec, Node3D? node, double lift, Node3D group,
                                       Overview.Vec3 origin, double yaw)
    {
        if (node is null) { v.Skip(spec); return; }
        v.Placed++;
        var frame = group.Transform * ChainTo(node.GetParent(), group);
        if (!SceneModels.IsPlaceholder(node) && spec.Surface is { } surface && spec.Measure != "fit")
        {
            var obj = $"{spec.Role}:{spec.Id}";
            v.Check(obj, "surface_scale", node.Transform.Basis.Scale.X,
                    SurfaceHeight.Scale(surface, new SurfacePlacement(new Scatter.P2(spec.AnchorX, spec.AnchorZ), spec.YawDeg,
                                                                      spec.BottomY, spec.MaxM, spec.Measure)));
            if (FixGroupBox(node) is { } fb) v.Check(obj, "surface_box", SceneVerifier.SurfaceBoxDeviation(fb, surface), 0);
        }
        var box = ModelPlacement.Measure(node, frame);
        var p = frame * node.Position;
        v.Placement(ToVBox(box), new Overview.Vec3(p.X, p.Y, p.Z), spec, origin, yaw, lift);
    }

    /// <summary>
    /// <c>fixGroupBox</c>: the box of the fix group's meshes in the FIT frame (yaw and outer scale stripped, the
    /// fix kept), its re-seat on the centre taken back out — the box the bake describes. Null without meshes.
    /// </summary>
    public static VBox? FixGroupBox(Node3D placed)
    {
        if (placed.GetChildCount() == 0 || placed.GetChild(0).GetChildCount() == 0) return null;
        if (placed.GetChild(0).GetChild(0) is not Node3D fit || fit.GetChildCount() == 0 || fit.GetChild(0) is not Node3D fix) return null;
        var box = ModelPlacement.Measure(fix, Transform3D.Identity);
        if (box.Size == Vector3.Zero) return null;
        var b = ToVBox(box);
        var o = fix.Position;
        return new VBox(new Overview.Vec3(b.Min.X - o.X, b.Min.Y - o.Y, b.Min.Z - o.Z), new Overview.Vec3(b.Max.X - o.X, b.Max.Y - o.Y, b.Max.Z - o.Z));
    }

    /// <summary>The transform from <paramref name="node"/>'s frame up to (not including) <paramref name="ancestor"/>.</summary>
    private static Transform3D ChainTo(Node? node, Node3D ancestor)
    {
        var xf = Transform3D.Identity;
        for (var n = node; n is not null && n != ancestor; n = n.GetParent())
            if (n is Node3D n3) xf = n3.Transform * xf;
        return xf;
    }

    /// <summary>The verify log: the full table with <see cref="VerifyFull"/>, otherwise only a location that deviates.</summary>
    private void LogVerify(VerifyReport report)
    {
        if (!VerifyFull && report.Clean) return;
        _log(report.Headline());
        foreach (var line in report.Table()) _log(line);
    }

    /// <summary>
    /// <c>openLocation</c> / <c>closeOpenLocation</c> as the fade TARGET of one built location — nothing is rebuilt;
    /// <see cref="TickView"/> crossfades it (the caller keeps the singleton, <c>OpenView</c>). Returns whether the
    /// location exists and can take that state.
    /// </summary>
    public bool SetOpen(string id, bool open)
    {
        if (!_slots.TryGetValue(id, out var slot)) return false;
        if (open && !slot.Openable) return false;
        if (slot.Open == open) return true;
        slot.Open = open;
        _log($"location {id} ({slot.Loc.Name}) {(open ? "opens" : "closes")} (crossfade)");
        return true;
    }

    /// <summary>
    /// The per-frame view pass of main.ts' frame hook: every openable location steps its crossfade towards its
    /// target (<c>applyTileFade</c>); every location applies its shown storey (<see cref="LocationStoreys.Apply"/>:
    /// <c>applyLevelDisplay</c>, the storey half of <c>applyWallCulling</c>, <c>applyRoomVisibility</c>, the door
    /// marks); the ground opens over a basement while one is shown (<see cref="BasementHoleOf"/>); the open location,
    /// once past fade 0.4, makes every taller neighbour between the camera and its centre fade out
    /// (<see cref="SceneView.NeighbourOccludes"/>, <c>applyTileOcclusion</c>).
    /// </summary>
    public void TickView(double dt, Vector3 camera)
    {
        LocationSlot? open = null;
        LocationSlot? basement = null;
        foreach (var slot in _slots.Values)
        {
            if (!GodotObject.IsInstanceValid(slot.Group)) continue;
            if (slot.Openable)
            {
                slot.Fade.Step(dt, slot.Open);
                if (slot.Open && slot.Fade.Fade > 0.4) open = slot;
                // The ground opens over a basement only while a storey below ground is the displayed one.
                if (StoreyView.BasementOpen(slot.Storeys.HasBasement, slot.Fade.Fade, slot.LevelFilter)) basement = slot;
            }
            // applyLevelDisplay / applyWallCulling (openable, fade > 0.03), applyRoomVisibility and the door marks (all).
            slot.Storeys.Apply(slot.LevelFilter, slot.Openable ? slot.Fade.Fade : 0, slot.Openable, slot.Fade);
        }
        Ground?.SetHole(basement is null ? null : BasementHoleOf(basement, camera));
        var cam = new Scatter.P2(camera.X, camera.Z);
        foreach (var slot in _slots.Values)
        {
            if (!GodotObject.IsInstanceValid(slot.Group)) continue;
            bool hide = open is not null && SceneView.NeighbourOccludes(cam,
                new Scatter.P2(open.Group.Position.X, open.Group.Position.Z),
                new Neighbour(slot.Group.Position.X, slot.Group.Position.Z, slot.Width, slot.Height), slot == open);
            slot.Fade.StepOcclusion(slot.Group, hide, dt);
        }
        StepModelClock(dt, camera);
    }

    /// <summary>
    /// <c>terrainGround.setHole(basementHole(tileWorldBounds(tile), tile.center, camera, tile.width))</c>: the open
    /// location's footprint as a world rectangle, grown towards the camera by up to one width; null without a boundary.
    /// </summary>
    public static double[]? BasementHoleOf(LocationSlot slot, Vector3 camera)
    {
        var g = slot.Group.Position;
        var frame = new TileFrame(new Overview.Vec3(g.X, g.Y, g.Z), slot.Group.Rotation.Y);
        var boundary = slot.Loc.Boundary?.Select(p => new Scatter.P2(p.X, p.Z)).ToArray();
        if (SceneView.TileWorldBounds(frame, boundary) is not { } bounds) return null;
        return SceneView.BasementHole(bounds, new Scatter.P2(g.X, g.Z), new Scatter.P2(camera.X, camera.Z), slot.Width);
    }

    /// <summary>
    /// The level switch's click (<c>tile.levelFilter = lv</c>): the storey the location shows from the next frame on —
    /// nothing is rebuilt or fetched. Returns false for an unknown location or a storey its payload does not declare.
    /// </summary>
    public bool SetLevel(string id, int level)
    {
        if (!_slots.TryGetValue(id, out var slot)) return false;
        if (slot.Storeys.Buttons.Count > 0 && slot.Storeys.Buttons.All(b => b.Level != level)) return false;
        if (slot.LevelFilter == level) return true;
        slot.LevelFilter = level;
        _log($"location {id} ({slot.Loc.Name}) shows storey {level}");
        return true;
    }

    /// <summary>
    /// The avatar's lock verdicts changed (the HUD's <c>lockedRooms</c> / <c>lockedLoc</c> / <c>lockedLocations</c>, or
    /// the room it stands in): every location repaints its door marks and shows or hides its boundary marks
    /// (main.ts: repainted only on a real change; the caller compares).
    /// </summary>
    public void SetLocks(LockState locks)
    {
        _locks = locks;
        foreach (var slot in _slots.Values)
            if (GodotObject.IsInstanceValid(slot.Group)) slot.Storeys.ApplyLocks(locks, slot.Loc.Id);
    }

    /// <summary>
    /// The room labels to draw this frame (a source of the label overlay): every label of a location whose labels are
    /// on (<see cref="StoreyView.LabelsOn"/>) and whose room group is shown in the tree (interior up, the storey
    /// filter, the neighbour occlusion all take it along).
    /// </summary>
    public IEnumerable<Ui.IOverlayLabel> VisibleRoomLabels()
    {
        foreach (var slot in _slots.Values)
        {
            if (slot.Storeys.Labels.Count == 0 || !GodotObject.IsInstanceValid(slot.Group)) continue;
            if (!StoreyView.LabelsOn(slot.Openable, slot.Fade.Fade)) continue;
            foreach (var label in slot.Storeys.Labels)
                if (label.Parent.IsVisibleInTree()) yield return label;
        }
    }

    // ---- locations that come and go while one plays (main.ts revealLocations / dropVanished) ----------

    /// <summary>
    /// The placed locations of a worldmap snapshot the world has not taken in yet (main.ts: <c>placeableOf(map)</c>
    /// minus <c>places</c>) — a place the avatar has just discovered, or what the admin's unfiltered view adds.
    /// </summary>
    /// <summary>Every place the world has taken in, built or not (main.ts <c>places</c>): the location labels' set.</summary>
    public IReadOnlyCollection<string> Known => _known;

    public List<LocationInfo> FreshOf(JsonElement map)
        => LocationInfo.ParseList(map).Where(l => l.IsPlaced && !_known.Contains(l.Id)).ToList();

    /// <summary>
    /// <c>revealLocations(map)</c>: build the fresh locations of this snapshot the same way the boot built its own —
    /// ring from the build's stream points (a place out of reach is only taken in), recipes first, then the
    /// groups; <paramref name="stillValid"/> is asked before anything goes into the world (the client's view
    /// revision: a reveal of the view one has just left must not mount). Returns how many groups went in.
    /// </summary>
    public async Task<int> RevealAsync(JsonElement map, Func<bool> stillValid)
    {
        if (_places is null || Height is null || _library is null) return 0;
        var fresh = FreshOf(map);
        if (fresh.Count == 0) return 0;
        var avatar = AvatarOf(map, LocationInfo.ParseList(map));
        var stats = new WorldStats();
        var jobs = new List<(LocationInfo Loc, Ring Ring, bool Pinned)>();
        foreach (var loc in fresh)
        {
            bool pinned = loc.Id == avatar.LocationId;
            var ring = LocationView.RingFor(LocationView.PlaceDistance(loc, _points), pinned);
            if (ring != Ring.Gone) jobs.Add((loc, ring, pinned));
        }
        var scenes = await PrimeScenes(jobs.Select(j => j.Loc), stats);
        if (!stillValid())
        {
            foreach (var d in scenes.Values) d?.Dispose();
            return 0;
        }
        int added = 0;
        foreach (var (loc, ring, pinned) in jobs)
        {
            if (!scenes.TryGetValue(loc.Id, out var doc)) continue;
            using (doc)
            {
                if (doc is null) { _known.Add(loc.Id); continue; }
                LocationSlot built;
                try
                {
                    built = await BuildFromScene(loc, doc.RootElement, Height, stats, ring, false, _tierCamera);
                }
                catch (Exception e) when (!_strict)
                {
                    _log($"location {loc.Id} ({loc.Name}) failed: {e.Message}");
                    continue;
                }
                if (!stillValid() || !GodotObject.IsInstanceValid(_places))
                {
                    built.Group.Free();
                    built.Storeys.BoundaryMarks?.Free();
                    return added;
                }
                _places.AddChild(built.Group);
                if (built.Storeys.BoundaryMarks is { } bm) _places.AddChild(bm);
                _slots[loc.Id] = built;
                _known.Add(loc.Id);
                added++;
            }
        }
        // Out of reach: taken in without a group, like the boot's 'gone' ring.
        foreach (var loc in fresh)
            if (!jobs.Any(j => j.Loc.Id == loc.Id)) _known.Add(loc.Id);
        if (added > 0) _log($"revealed {added} location(s): {string.Join(", ", fresh.Where(l => _slots.ContainsKey(l.Id)).Select(l => l.Id))}");
        return added;
    }

    /// <summary>
    /// <c>dropVanished(map)</c>: give back every location this snapshot no longer carries — except the avatar's own
    /// (the ground it stands on). Returns the ids that went.
    /// </summary>
    public List<string> DropVanished(JsonElement map)
    {
        var keep = LocationInfo.ParseList(map).Where(l => l.IsPlaced).Select(l => l.Id).ToHashSet();
        if (AvatarOf(map, new List<LocationInfo>()).LocationId is { } here) keep.Add(here);
        var gone = _known.Concat(_slots.Keys).Where(id => !keep.Contains(id)).Distinct().ToList();
        foreach (var id in gone)
        {
            _known.Remove(id);
            if (!_slots.Remove(id, out var slot)) continue;
            slot.Generation++;   // a rebuild in flight must not put it back
            if (GodotObject.IsInstanceValid(slot.Group)) slot.Group.QueueFree();
            if (slot.Storeys.BoundaryMarks is { } bm && GodotObject.IsInstanceValid(bm)) bm.QueueFree();
            Dropped?.Invoke(slot);
        }
        if (gone.Count > 0) _log($"dropped {gone.Count} location(s) the view no longer carries: {string.Join(", ", gone)}");
        return gone;
    }

    /// <summary>
    /// A re-synced <c>/world/locations?view=3d</c> (main.ts <c>applyLocations</c>): the detail rows (names, rooms)
    /// are replaced. Rebuilding a built location whose details changed is not ported (no live tile rebuild yet).
    /// </summary>
    public void TakeDetails(JsonElement locations) => Details = LocationInfo.ParseList(locations);

    /// <summary>
    /// § A16.9 <see cref="StoreyGround.Lift"/>: a level-0 spec moves onto the ground under its own anchor (turned into
    /// the world by the tile frame, <see cref="SceneView.TileToWorld"/>).
    /// </summary>
    private static double GroundLift(Node3D group, SceneModelSpec spec, WorldHeight height, double datum)
    {
        var frame = new TileFrame(new Overview.Vec3(group.Position.X, group.Position.Y, group.Position.Z), group.Rotation.Y);
        var w = SceneView.TileToWorld(frame, spec.AnchorX, spec.AnchorZ);
        return StoreyGround.Lift(spec.Level, w.X, w.Z, datum, height.GroundAt);
    }

    private static void Merge(ModelStats into, ModelStats m)
    {
        foreach (var k in ModelStats.Kinds) into.Placed[k] += m.Placed[k];
        into.Placeholders += m.Placeholders; into.Missing += m.Missing; into.Interior += m.Interior;
        into.Storey += m.Storey; into.Faded += m.Faded; into.Culled += m.Culled;
        into.Vertices += m.Vertices; into.Indices += m.Indices; into.Compressed += m.Compressed;
        into.Full += m.Full; into.Low += m.Low;
    }

    /// <summary>
    /// The world props (§ A9a, worldProps.ts): one placement per row through § B2 with <c>measure: "xyz"</c>;
    /// bottom = ground + <c>offset_y</c> + <c>ground_offset_m</c> (<c>worldPropBottom</c>); tier by
    /// <c>instanceTier(distance to the camera, 'low', scatter LOD × 3)</c>, hidden beyond 360 m; the variant by
    /// <c>pickModelVariant</c> (the row's <c>variant</c> first, then the tier).
    /// </summary>
    private async Task BuildWorldProps(Node3D root, JsonElement map, WorldHeight height, WorldStats stats, Vector3 camera)
    {
        var group = new Node3D { Name = "WorldProps" };
        root.AddChild(group);
        var cfg = new Scatter.ScatterLodCfg(Scatter.ScatterLod.TierNear * WorldPropLodScale,
                                            Scatter.ScatterLod.TierFar * WorldPropLodScale,
                                            Scatter.ScatterLod.CullFar * WorldPropLodScale);
        var models = new ModelStats();
        var jobs = new List<Task>();
        foreach (var wp in Json.Arr(map, "world_props"))
        {
            if (wp.ValueKind != JsonValueKind.Object || Json.Str(wp, "id").Length == 0) continue;
            if (Json.NumOrNull(wp, "x") is not double x || Json.NumOrNull(wp, "z") is not double z) continue;
            stats.WorldPropRows++;
            double bottom = height.GroundAt(x, z) + Json.Num(wp, "offset_y") + Json.Num(wp, "ground_offset_m");
            var spec = WorldPropSpec(wp, x, z, bottom);
            double d = Math.Sqrt((x - camera.X) * (x - camera.X) + (z - camera.Z) * (z - camera.Z));
            byte tier = Scatter.ScatterLod.InstanceTier(d, 1, cfg);
            if (tier == 2) { models.Culled++; continue; }
            jobs.Add(SceneModels.PlaceAsync(_models, spec, tier == 0 ? "full" : "low", "world", group, 0, models, null));
        }
        await Task.WhenAll(jobs);
        lock (stats) Merge(stats.Models, models);
    }

    /// <summary><c>worldPropSceneSpec</c>: role prop, measure fixed to xyz, max_m || 1, anchor (x, z) in world metres.</summary>
    public static SceneModelSpec WorldPropSpec(JsonElement wp, double x, double z, double bottom)
    {
        var parsed = ScenePayload.ParseModel(wp);
        return parsed with
        {
            Role = "prop", Id = Json.Str(wp, "prop_id"), Measure = "xyz",
            MaxM = Js.Or(Json.Num(wp, "max_m"), 1),
            AnchorX = x, AnchorZ = z, BottomY = bottom, SizeM = null,
        };
    }
}
