using System;
using System.Text.Json;
using System.Text.Json.Nodes;
using AnimaNative.Overview;
using AnimaNative.Scatter;
using AnimaNative.World;

namespace AnimaNative.Hud;

/// <summary>Task 55 / E7-T10: the six fields of game/minimap.ts, with finished relief JSON retained by identity
/// across steps. Areas are bottom to top; locations are only the map payload's known, placed locations. The
/// avatar is the window anchor, and yaw is the follow camera rounded to whole degrees, both as in main.ts.</summary>
public sealed record MinimapState(JsonArray Areas, string ReliefJson, JsonArray Locations, P2? Avatar,
                                  double Yaw, BoundsXZ? Bounds);

/// <summary>Task 55 / E7-T10: main.ts' 250ms minimap publisher, independent of Godot. The change signature is
/// terrain identity, height revision, location IDs/positions, anchor, whole-degree yaw and bounds. Relief
/// samples the overview (not the near tiles), with MAP_RELIEF_Z_FACTOR=3, only after a height revision.
/// Tile batches advance that revision too, exactly like terrainGround.heightRevision(). Null is emitted once
/// on leaving embodiment; re-entry clears the anchor while keeping the height cache. Tick returns true only
/// when the caller must publish State, including its null transition.</summary>
public sealed class MinimapProducer
{
    public const double IntervalS = .25;
    private const double SizePx = 160, FollowStepPx = .6, MinSpanM = 10, ViewRadiusM = 520;
    public MinimapState? State { get; private set; }
    private double _elapsed;
    private P2? _anchor;
    private TerrainPayload? _terrain;
    private JsonArray _areas = new(), _locations = new();
    private JsonElement? _map;
    private string _locationSig = "";
    private BoundsXZ? _bounds;
    private WorldHeight? _height;
    private int _heightRev = -1;
    private string _reliefJson = "null";
    private (TerrainPayload? Terrain, WorldHeight? Height, int Rev, string Locations, P2? Anchor, double Yaw, BoundsXZ? Bounds)? _published;

    public bool Tick(double dt, bool embodied, TerrainPayload? terrain, WorldHeight? height,
                     JsonElement? map, P2? position, double yaw)
    {
        _elapsed += Math.Max(0, dt);
        if (_elapsed + 1e-12 < IntervalS) return false;
        // Consume the same epsilon-admitted interval; modulo alone keeps a just-short interval
        // and would publish again on the very next frame (Task 55, repeated 60Hz regression).
        double intervals = Math.Floor((_elapsed + 1e-12) / IntervalS);
        _elapsed = Math.Max(0, _elapsed - intervals * IntervalS);
        if (!embodied)
        {
            if (_published is null) return false;
            _published = null; _anchor = null; State = null;
            return true;
        }
        if (!Nullable.Equals(_map, map)) TakeMap(map);
        double span = _bounds is { } b ? Math.Max(b.MaxX - b.MinX, b.MaxZ - b.MinZ) : 0;
        double radius = Math.Min(ViewRadiusM, Math.Max(span, MinSpanM) / 2);
        double step = FollowStepPx * 2 * radius / SizePx;
        if (position is null) _anchor = null;
        else if (_anchor is not { } previous || double.Hypot(position.Value.X - previous.X, position.Value.Z - previous.Z) > step)
            _anchor = position;
        double yawDeg = Math.Floor(yaw * 180 / Math.PI + .5);
        int rev = height?.Revision ?? -1;
        var signature = (terrain, height, rev, _locationSig, _anchor, yawDeg, _bounds);
        if (_published == signature) return false;
        _published = signature;
        if (!ReferenceEquals(_terrain, terrain))
        {
            _terrain = terrain;
            _areas = new JsonArray();
            if (terrain is not null)
                foreach (var area in terrain.Areas)
                {
                    var polygon = new JsonArray();
                    foreach (var p in area.Polygon) polygon.Add(new JsonArray(p.X, p.Z));
                    _areas.Add(new JsonObject { ["polygon"] = polygon, ["color"] = terrain.KindColor(area.Kind.Trim()) });
                }
        }
        if (!ReferenceEquals(_height, height) || _heightRev != rev)
        {
            _height = height; _heightRev = rev;
            var field = ForWire(height?.Overview.Grid);
            var image = Hillshade.Build(field, new JsonObject { ["zFactor"] = Hillshade.MapReliefZFactor });
            _reliefJson = image is null || field is null ? "null" : new JsonObject
            {
                ["image"] = image.ToJson(), ["origin_x"] = field.OriginX,
                ["origin_z"] = field.OriginZ, ["step_m"] = field.Step,
            }.ToJsonString();
        }
        State = new(_areas, _reliefJson, _locations, _anchor, yawDeg * Math.PI / 180, _bounds);
        return true;
    }

    /// <summary>The longest relief edge the bridge carries. The minimap canvas is <see cref="SizePx"/> CSS px, so a
    /// finer relief is never seen; the browser hands its full overview to the HUD in-process, but natively every changed
    /// state crosses the CEF bridge as JSON (≈1.5 MB per message for a 521×198 overview, four times a second while
    /// walking, and the HUD rebuilds the bitmap per message). Controller ruling P3-R28.</summary>
    public const int WireReliefMaxPx = 192;

    /// <summary>The overview decimated by an integer factor so neither edge exceeds <see cref="WireReliefMaxPx"/>
    /// (every k-th sample, step × k, same origin); a field already small enough passes unchanged.</summary>
    public static HeightGrid? ForWire(HeightGrid? field)
    {
        if (field is null) return null;
        int k = (int)Math.Ceiling(Math.Max(field.Cols, field.Rows) / (double)WireReliefMaxPx);
        if (k <= 1) return field;
        int cols = (field.Cols + k - 1) / k, rows = (field.Rows + k - 1) / k;
        var heights = new float[cols * rows];
        for (int j = 0; j < rows; j++)
            for (int i = 0; i < cols; i++)
                heights[j * cols + i] = field.At(i * k, j * k);
        return new HeightGrid(field.OriginX, field.OriginZ, field.Step * k, rows, cols, heights);
    }

    /// <summary>Task 55: cache the browser's locationsSignature once per taken map. Names accompany dots but
    /// do not enter the browser's signature. Bounds include undiscovered places via world_bounds, never a fit
    /// over the visible dots. The server has already filtered locations by the avatar's knowledge.</summary>
    private void TakeMap(JsonElement? map)
    {
        _map = map; _locations = new JsonArray();
        var signature = new JsonArray();
        _bounds = map is { } m ? OverviewControl.WorldBoundsOf(m) : null;
        if (map is { } payload)
            foreach (var loc in World.Json.Arr(payload, "locations"))
            {
                string id = World.Json.Str(loc, "id");
                double? x = World.Json.NumOrNull(loc, "pos_x"), z = World.Json.NumOrNull(loc, "pos_z");
                signature.Add(new JsonArray(id, x, z));
                if (x is not null && z is not null)
                {
                    string name = World.Json.Str(loc, "name");
                    _locations.Add(new JsonObject { ["id"] = id, ["name"] = name.Length > 0 ? name : id, ["x"] = x, ["z"] = z });
                }
            }
        _locationSig = signature.ToJsonString();
    }
}
