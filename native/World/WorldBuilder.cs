using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;
using AnimaNative.Api;
using AnimaNative.Ground;
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
    /// <summary>The open location (the avatar's, interior shown) — "" when none.</summary>
    public string OpenLocation = "";
    public int Failures;
    /// <summary>The scene-recipe primitives, drawn and skipped by reason.</summary>
    public RecipeStats Recipe = new();
    /// <summary>The model specs (recipe <c>models[]</c> incl. buildings + world props), per kind.</summary>
    public ModelStats Models = new();
    public int WorldPropRows;
    /// <summary>Triangles the open plan-hull model lost to its cutouts.</summary>
    public int CutoutTriangles;
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
        + $"culled_walls={Recipe.CulledWalls} {Models.Summary()} world_props={WorldPropRows} cutout_triangles={CutoutTriangles} "
        + $"failures={Failures} anchor=({Anchor.Position().X:0.###},{Anchor.Position().Y:0.###},{Anchor.Position().Z:0.###}) "
        + $"{WaterSummary()} {Ground.Summary()}";
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
///      +yaw_deg (§ A1.1); its scene recipe as the browser shows it — building model(s), outdoor model specs,
///      the outdoor rooms' primitives, the far-view shell of a place without a model, and for the OPEN location
///      (the avatar's) its interior: primitives on the shown storey and the indoor model specs
///   6. the world props of <c>/play/worldmap</c> (§ A9a)
/// </summary>
public sealed class WorldBuilder
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

    /// <param name="strict">true in <c>--check</c>: any failure aborts; online a broken location is logged and skipped.</param>
    public WorldBuilder(IWorldSource source, Action<string> log, bool strict)
    {
        _source = source;
        _log = log;
        _strict = strict;
    }

    public async Task<WorldStats> BuildAsync(Node3D root, string? gotoQuery)
    {
        var stats = new WorldStats();
        using var hfDoc = await _source.GetHeightfieldAsync();
        var overview = HeightfieldOverview.Parse(hfDoc.RootElement);
        using var mapDoc = await _source.GetWorldMapAsync();
        var locations = LocationInfo.ParseList(mapDoc.RootElement);
        using var locDoc = await _source.GetLocations3dAsync();
        var details = LocationInfo.ParseList(locDoc.RootElement);
        Details = details;
        FirstMap = mapDoc.RootElement.Clone();
        _log($"heightfield {overview.Grid.Cols}x{overview.Grid.Rows} step {overview.Grid.Step} m, "
             + $"{overview.TileIndex.Count} indexed tiles; worldmap {locations.Count} locations, "
             + $"view=3d {details.Count}");

        stats.Anchor = Anchor.FromWorld(mapDoc.RootElement, details, overview.Grid, gotoQuery);
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
        var avatar = AvatarOf(mapDoc.RootElement, locations);
        var anchorXZ = (X: (double)stats.Anchor.X, Z: (double)stats.Anchor.Z);
        var points = new List<(double X, double Z)>();
        if (avatar.Pos is { } ap) points.Add(ap);
        points.Add(anchorXZ);
        var camera = stats.Anchor.Position() + StartCameraOffset;

        var places = new Node3D { Name = "Locations" };
        root.AddChild(places);
        var placed = locations.Where(l => l.IsPlaced).ToList();
        stats.Locations = placed.Count;
        using var gate = new SemaphoreSlim(SceneConcurrency);
        var tasks = placed.Select(async loc =>
        {
            await gate.WaitAsync();
            try
            {
                bool pinned = loc.Id == avatar.LocationId;
                var ring = LocationView.RingFor(LocationView.PlaceDistance(loc, points), pinned);
                if (ring == Ring.Gone) { stats.LocationsGone++; return; }
                await BuildLocation(loc, places, height, stats, ring, loc.Id == avatar.LocationId ? avatar.RoomId : null,
                                    camera);
            }
            catch (Exception e) when (!_strict)
            {
                stats.Failures++;
                stats.Problems.Add($"{loc.Id}: {e.Message}");
                _log($"location {loc.Id} ({loc.Name}) failed: {e.Message}");
            }
            finally { gate.Release(); }
        }).ToList();
        await Task.WhenAll(tasks);

        await BuildWorldProps(root, mapDoc.RootElement, height, stats, camera);
        _log($"recipe: {stats.Recipe.Primitives} primitives drawn ({stats.Recipe.Plates} plates, {stats.Recipe.Walls} walls, "
             + $"{stats.Recipe.Extras} extras; {stats.Recipe.ShellCopies} far-shell copies), {stats.Recipe.Skipped} skipped "
             + $"({stats.Recipe.SkipSummary()}); surfaces {_library.Loaded} loaded / {_library.Failed} failed; "
             + $"{_materials.Count} materials");
        _log($"models: {stats.Models.Summary()}; {_models.Loaded} GLBs loaded ({_models.Bytes / 1048576.0:0.0} MiB), "
             + $"{_models.Failed} failed");
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

    private async Task BuildLocation(LocationInfo loc, Node3D parent, WorldHeight height, WorldStats stats,
                                     Ring ring, string? avatarRoom, Vector3 camera)
    {
        using var doc = await _source.GetLocationSceneAsync(loc.Id);
        if (doc is null) return;  // 404: nothing to compose (no plan, no rooms, no model)
        var scene = ScenePayload.Parse(doc.RootElement);
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
        parent.AddChild(group);

        var (isBuilding, natureSite) = LocationView.Kind(loc);
        var buildings = scene.Models.Where(m => m.Role == "building").ToList();
        bool shellArea = scene.AreaDetail || buildings.Any(m => m.Display == "shell_area");
        bool groundModel = buildings.Any(m => m.Display == "ground");
        bool hasInterior = scene.Plates.Count > 0 || scene.Walls.Count > 0 || scene.Extras.Count > 0
                           || scene.HasFloorPlanOrMarkers || scene.Models.Any(m => m.Role != "building");
        // openable(tile) + the singleton: only the avatar's location is open (fade 1).
        bool open = avatarRoom is not null && hasInterior && (isBuilding || shellArea || groundModel);
        if (open) stats.OpenLocation = loc.Id;
        var roomLevel = scene.Rooms.GroupBy(r => r.RoomId).ToDictionary(g => g.Key, g => g.First().Level);
        int levelFilter = avatarRoom is { Length: > 0 } ar && roomLevel.TryGetValue(ar, out var lvl) ? lvl : 0;
        var outdoor = LocationView.OutdoorRoomIds(scene);
        bool RoomShown(string roomId) => outdoor.Contains(roomId)
            || (!roomLevel.TryGetValue(roomId, out var lv) || lv == levelFilter);

        double width = LocationView.FootprintWidth(loc);
        string buildingTier = LocationView.BuildingTier(ring, camera.DistanceTo(group.Position), width);
        string interiorTier = LocationView.InteriorTier(ring, scene.AreaDetail, open);
        var models = new ModelStats();

        // ── Building model(s): the far view, or — open — a kept plan hull / ground model with its cutouts. ──
        bool solidBuildingPlaced = false;
        foreach (var spec in buildings)
        {
            bool keep = spec.Display == "ground" || spec.PlanHull;
            if (open && !keep && !spec.RoofOnly) { models.Faded++; continue; }
            if (open && spec.RoofOnly) { models.Faded++; continue; }
            var node = await SceneModels.PlaceAsync(_models, spec, buildingTier, "building", group, 0, models, _materials);
            if (node is null) continue;
            if (!spec.RoofOnly) solidBuildingPlaced = true;
            if (open && keep && spec.Cutouts.Length > 0) stats.CutoutTriangles += SceneModels.ApplyCutouts(node, spec.Cutouts);
            if ((await _models.GetAsync(spec.PickUrl(buildingTier))) is { } t)
            {
                stats.Buildings++;
                if (t.Compressed) stats.BuildingsCompressed++;
                stats.BuildingVertices += t.Counts.Vertices;
                stats.BuildingIndices += t.Counts.Indices;
            }
        }

        // ── The other specs: outdoor ones always, indoor ones only in the open location on its storey. ──
        var placements = new List<Task>();
        foreach (var spec in scene.Models.Where(m => m.Role != "building"))
        {
            bool isOut = LocationView.IsOutdoor(scene, spec.RoomId);
            if (!isOut)
            {
                if (!open) { models.Interior++; continue; }
                if (!RoomShown(spec.RoomId)) { models.Storey++; continue; }
            }
            double lift = spec.Level == 0 ? GroundLift(group, spec, height, datum) : 0;
            placements.Add(SceneModels.PlaceAsync(_models, spec, interiorTier, SceneModels.KindOf(spec), group, lift,
                                                  models, _materials));
        }
        await Task.WhenAll(placements);

        // ── Recipe primitives: outdoor rooms, the open interior, or the far-view shell of a modelless place. ──
        bool farShell = !open && !solidBuildingPlaced
                        && LocationView.FarShellSource(isBuilding, natureSite, scene.AreaDetail, false,
                                                       scene.Plates.Count, scene.Walls.Count) == "recipe";
        var kinds = scene.Plates.Select(p => p.TextureKind).Concat(scene.Walls.Select(w => w.TextureKind))
                         .Concat(scene.Extras.Select(e => e.TextureKind)).Where(k => k.Length > 0).Append("floor");
        await _library!.PreloadAsync(kinds);
        var (meshes, rs) = RecipeMeshes.Build(scene, new RecipeView(open, levelFilter, farShell), _materials, "Recipe");
        foreach (var m in meshes) group.AddChild(m);
        lock (stats)
        {
            stats.Recipe.Add(rs);
            Merge(stats.Models, models);
        }
        if (rs.Primitives > 0 || open)
            _log($"location {loc.Id} ({loc.Name}): ring={ring.ToString().ToLowerInvariant()}{(open ? $" OPEN storey {levelFilter}" : "")}"
                 + $"{(farShell ? " far-shell" : "")} — {rs.Primitives} primitives, skipped {rs.SkipSummary()}; {models.Summary()}");
    }

    /// <summary>§ A16.9 <c>storeyGroundLift</c>: a level-0 spec moves onto the ground under its own anchor.</summary>
    private static double GroundLift(Node3D group, SceneModelSpec spec, WorldHeight height, double datum)
    {
        var w = group.Transform * new Vector3((float)spec.AnchorX, 0, (float)spec.AnchorZ);
        double y = height.GroundAt(w.X, w.Z);
        return double.IsFinite(y) ? y - datum : 0;
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
            MaxM = Json.Num(wp, "max_m") is var m && m > 0 ? m : 1,
            AnchorX = x, AnchorZ = z, BottomY = bottom, SizeM = null,
        };
    }
}
