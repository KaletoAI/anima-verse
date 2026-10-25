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
    public int Primitives, Skipped, DoorPropLeaves, Failures;
    /// <summary>The ground surfaces (Task S3b); Mode "plain" = the S1a vertex colour.</summary>
    public GroundStats Ground = new();
    public List<string> Problems { get; } = new();

    public int TerrainVertices => OverviewVertices + TileVertices;

    public string Summary() =>
        $"terrain_vertices={TerrainVertices} overview_vertices={OverviewVertices} overview_triangles={OverviewTriangles} "
        + $"tiles={Tiles} tile_vertices={TileVertices} locations={Locations} scenes={Scenes} buildings={Buildings} "
        + $"buildings_meshopt={BuildingsCompressed} building_vertices={BuildingVertices} building_indices={BuildingIndices} "
        + $"primitives={Primitives} skipped={Skipped} door_prop_leaves={DoorPropLeaves} failures={Failures} "
        + $"anchor=({Anchor.Position.X:0.###},{Anchor.Position.Y:0.###},{Anchor.Position.Z:0.###}) {Ground.Summary()}";
}

/// <summary>
/// Builds the S1a world from an <see cref="IWorldSource"/> — the server online,
/// the fixtures in <c>--check</c>; both paths run THIS code.
///
///   1. <c>/play/heightfield</c> overview, <c>/play/worldmap</c> (placement)
///      and <c>/world/locations?view=3d</c> (ids/names for the goto match)
///   2. the anchor (<see cref="Anchor.FromWorld"/> — the browser bench rule)
///   3. the indexed 2 m tiles within <see cref="TileRadiusM"/> of the anchor
///   4. terrain meshes (overview with the tiled cells left out, one mesh per tile), dressed in the browser's
///      ground material (<see cref="GroundSurfaces"/>, Task S3b) — or, when that fails or with
///      <see cref="PlainGround"/>, left in the plain vertex colour
///   5. per placed location: a group at (pos_x, ground, pos_z) turned by
///      +yaw_deg (§ A1.1, <c>buildTile</c>); its scene recipe's building model
///      placed by § B2 — or, when it has none (or only a roof), its recipe
///      primitives as untextured meshes.
/// </summary>
public sealed class WorldBuilder
{
    public const double TileRadiusM = 384;
    private const int SceneConcurrency = 4;

    private readonly IWorldSource _source;
    private readonly Action<string> _log;
    private readonly bool _strict;

    public WorldHeight? Height { get; private set; }
    /// <summary>The <c>/world/locations?view=3d</c> rows of the build (names for the anchor's goto match).</summary>
    public IReadOnlyList<LocationInfo> Details { get; private set; } = Array.Empty<LocationInfo>();
    /// <summary>The <c>/play/worldmap</c> payload the build used (the anchor's fallback snapshot).</summary>
    public JsonElement? FirstMap { get; private set; }
    /// <summary>The ground surfaces of the build (null = plain material).</summary>
    public GroundSurfaces? Ground { get; private set; }
    /// <summary><c>--plain-ground</c>: keep the S1a vertex-colour terrain (no layer requests at all).</summary>
    public bool PlainGround { get; init; }

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
        _log($"anchor {stats.Anchor.Position} ({stats.Anchor.Source}{(stats.Anchor.LocationId is { } id ? ", " + id : "")})");

        var height = Height = new WorldHeight(overview);
        var keys = height.IndexedTilesNear(stats.Anchor.Position.X, stats.Anchor.Position.Z, TileRadiusM);
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
        foreach (var tile in height.Tiles.OrderBy(t => t.Key.Tx).ThenBy(t => t.Key.Tz))
        {
            var (node, ts) = TerrainBuilder.BuildTile(tile);
            terrain.AddChild(node);
            stats.Tiles++;
            stats.TileVertices += ts.Vertices;
            stats.TileTriangles += ts.Triangles;
        }
        _log($"terrain: overview {stats.OverviewVertices} v / {stats.OverviewTriangles} t, "
             + $"{stats.Tiles} tiles {stats.TileVertices} v / {stats.TileTriangles} t");
        stats.Ground = await DressGround(terrain, height, stats.Anchor);

        var places = new Node3D { Name = "Locations" };
        root.AddChild(places);
        var placed = locations.Where(l => l.IsPlaced).ToList();
        stats.Locations = placed.Count;
        using var gate = new SemaphoreSlim(SceneConcurrency);
        var tasks = placed.Select(async loc =>
        {
            await gate.WaitAsync();
            try { await BuildLocation(loc, places, height, stats); }
            catch (Exception e) when (!_strict)
            {
                stats.Failures++;
                stats.Problems.Add($"{loc.Id}: {e.Message}");
                _log($"location {loc.Id} ({loc.Name}) failed: {e.Message}");
            }
            finally { gate.Release(); }
        }).ToList();
        await Task.WhenAll(tasks);
        return stats;
    }

    /// <summary>
    /// The ground surfaces on every terrain mesh. Never fatal: any failure keeps the plain material and is
    /// logged (and reported in <see cref="GroundStats.Reason"/>), online and in <c>--check</c> alike.
    /// </summary>
    private async Task<GroundStats> DressGround(Node3D terrain, WorldHeight height, AnchorInfo anchor)
    {
        var (stats, ground) = await DressGroundAsync(_source, terrain, height, anchor, _log, PlainGround);
        Ground = ground;
        return stats;
    }

    /// <summary>The one ground step (also driven directly by the check's fallback cases).</summary>
    public static async Task<(GroundStats Stats, GroundSurfaces? Ground)> DressGroundAsync(
        IWorldSource source, Node3D terrain, WorldHeight height, AnchorInfo anchor, Action<string> log, bool plain)
    {
        if (plain) return (new GroundStats { Reason = "--plain-ground" }, null);
        try
        {
            var ground = await GroundSurfaces.LoadAsync(source, height, anchor.X, anchor.Z, log);
            ground.ApplyTo(terrain.GetChildren().OfType<GeometryInstance3D>());
            return (ground.Stats, ground);
        }
        catch (Exception e)
        {
            log($"ground surfaces failed, keeping the plain material: {e.Message}");
            return (new GroundStats { Reason = e.Message }, null);
        }
    }

    private async Task BuildLocation(LocationInfo loc, Node3D parent, WorldHeight height, WorldStats stats)
    {
        using var doc = await _source.GetLocationSceneAsync(loc.Id);
        if (doc is null) return;  // 404: nothing to compose (no plan, no rooms, no model)
        var scene = ScenePayload.Parse(doc.RootElement);
        stats.Scenes++;
        if (Math.Abs(scene.K - 1) > 1e-9)
            _log($"location {loc.Id}: scene k={scene.K} (contract says 1) — drawn unscaled");

        double x = loc.PosX!.Value, z = loc.PosZ!.Value;
        var group = new Node3D
        {
            Name = $"Loc_{loc.Id}",
            Position = new Vector3((float)x, (float)height.GroundAt(x, z), (float)z),
            Rotation = new Vector3(0, (float)(loc.YawDeg * Math.PI / 180.0), 0),
        };
        group.SetMeta("location_id", loc.Id);
        parent.AddChild(group);

        bool hasBuilding = false;
        foreach (var spec in scene.Models)
        {
            if (spec.Role != "building")
            {
                // Rooms/props are S1b/S3 territory: counted, not drawn.
                stats.Skipped++;
                continue;
            }
            var result = await BuildingLoader.LoadAsync(_source, spec);
            if (result is null) { stats.Skipped++; continue; }  // no mesh (placeholder)
            group.AddChild(result.Placed);
            stats.Buildings++;
            if (result.WasCompressed) stats.BuildingsCompressed++;
            stats.BuildingVertices += result.Counts.Vertices;
            stats.BuildingIndices += result.Counts.Indices;
            if (!spec.RoofOnly) hasBuilding = true;
        }

        // The far view of the browser: a building model replaces the recipe
        // shell (a roof-only model sits on top of it). Interiors stay hidden.
        if (hasBuilding) return;
        var (mesh, rs) = RecipeMeshes.Build(scene, "Recipe");
        if (mesh is not null) group.AddChild(mesh);
        stats.Primitives += rs.Primitives;
        stats.Skipped += rs.Skipped;
        stats.DoorPropLeaves += rs.DoorPropLeaves;
        if (rs.Skipped > 0) _log($"location {loc.Id}: {rs.Skipped} recipe primitives skipped");
    }
}
