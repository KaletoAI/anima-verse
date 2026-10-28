using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
using System.Threading.Tasks;
using AnimaNative.Scatter;
using AnimaNative.Scene;
using AnimaNative.Water;
using Godot;

namespace AnimaNative.World;

/// <summary>Task 40 (E4-T5), worldProps.ts: one record per authored id, including culled landmarks.
/// The builder owns the 1 Hz beat; sync owns shape/translation, and each asynchronous mount checks the latest wish.
/// Templates remain in ModelCache (worker Parse, main-thread Generate); nodes, sheets and ghosts belong to this layer.</summary>
public partial class WorldPropsLayer : Node3D
{
    public sealed class Record
    {
        public string Id = "";
        public JsonElement Row;
        public SceneModelSpec Spec = null!;
        public byte Tier = 1;
        public double Distance;
        public Node3D? Node;
        public string ShownUrl = "", WantedUrl = "", LightKey = "", WaterKey = "";
        public string? LightId;
        public List<MeshInstance3D> Sheets = new();
        public SubmergedGhost? Ghost;
        public double PlacedX, PlacedZ, PlacedBottom;
        public bool Disposed;
    }
    private readonly Dictionary<string, Record> _records = new();
    public IReadOnlyDictionary<string, Record> Records => _records;
    private readonly ModelCache _cache;
    private readonly WorldHeight _height;
    private readonly PropLightPool? _lights;
    private readonly Action<string> _log;
    private readonly HashSet<Task> _pending = new();
    private string _signature = "";
    private bool _disposed;
    private Vector3? _camera;
    public ScatterLodCfg Lod { get; private set; } = WorldPropMath.LodCfg(ScatterLod.Defaults);
    public ModelStats Stats { get; } = new();
    public event Action? WaterChanged;
    private bool _waterSuppressed;
    /// <summary>Task 40 review: benchmark water suppression survives ticks, redrape and newly synced sheets.
    /// Restoring it derives visibility from the current tier, rather than a stale snapshot of each sheet.</summary>
    public bool WaterSuppressed
    {
        get => _waterSuppressed;
        set { _waterSuppressed = value; foreach (var r in _records.Values) SetSheetVisibility(r); }
    }
    private void SetSheetVisibility(Record r)
    {
        foreach (var sheet in r.Sheets) sheet.Visible = r.Tier != 2 && !_waterSuppressed;
    }

    public WorldPropsLayer(ModelCache cache, WorldHeight height, PropLightPool? lights, Action<string> log)
    {
        Name = "WorldProps"; _cache = cache; _height = height; _lights = lights; _log = log;
    }
    private static string Key(JsonElement row, string key) => row.TryGetProperty(key, out var v) ? v.GetRawText() : "";
    private static string Shape(JsonElement row) => string.Join("|", new[] {
        "prop_id", "max_m", "yaw_deg", "fix_euler", "variant", "variants", "model_variants"
    }.Select(k => Key(row, k)));

    /// <summary>Task 40: every accepted map, with the browser's signature-and-count fast path; only shape changes replace a node.</summary>
    public void SyncWorldMap(JsonElement map)
    {
        if (_disposed) return;
        var rows = Json.Arr(map, "world_props").ToList();
        string sig = Json.Str(map, "world_props_sig");
        if (sig.Length > 0 && sig == _signature && rows.Count == _records.Count) return;
        _signature = sig;
        var seen = new HashSet<string>();
        foreach (var row in rows)
        {
            string id = Json.Str(row, "id");
            if (id.Length == 0 || Json.NumOrNull(row, "x") is not double || Json.NumOrNull(row, "z") is not double) continue;
            seen.Add(id);
            if (!_records.TryGetValue(id, out var r)) _records[id] = r = new Record { Id = id, Row = row.Clone() };
            else if (Shape(r.Row) != Shape(row)) { DropNode(r); r.WantedUrl = ""; }
            r.Row = row.Clone();
            RedrapeOne(r);
        }
        foreach (var id in _records.Keys.Where(id => !seen.Contains(id)).ToList())
        {
            Drop(_records[id]); _records.Remove(id);
        }
        WaterChanged?.Invoke();
    }

    /// <summary>Task 40: horizontal distance (camera altitude never enters), hysteresis and ×3 preferences.
    /// Tier 2 hides sheets and mesh, while the light remains registered. Awaitable for boot and offline proof.</summary>
    public Task TickAsync(Vector3 camera)
    {
        if (_disposed) return Task.CompletedTask;
        _camera = camera;
        foreach (var r in _records.Values)
        {
            double dx = r.Spec.AnchorX - camera.X, dz = r.Spec.AnchorZ - camera.Z;
            r.Distance = Math.Sqrt(dx * dx + dz * dz);
            r.Tier = ScatterLod.InstanceTier(r.Distance, r.Tier, Lod);
            if (r.Node is not null) r.Node.Visible = r.Tier != 2;
            SetSheetVisibility(r);
            if (r.Tier != 2) RequestMount(r, ModelVariants.PickModelVariant(r.Spec, r.Tier == 0 ? "full" : "low"));
        }
        return WhenIdleAsync();
    }
    public Task WhenIdleAsync() => Task.WhenAll(_pending.ToArray());
    private void RequestMount(Record r, string url)
    {
        if (url.Length == 0) return;
        // Returning to the shown URL must cancel an older in-flight wish as well.
        if (url == r.ShownUrl) { r.WantedUrl = url; return; }
        if (url == r.WantedUrl) return;
        r.WantedUrl = url;
        var task = MountAsync(r, url);
        _pending.Add(task);
        _ = ForgetAsync(task);
    }
    private async Task ForgetAsync(Task task) { try { await task; } finally { _pending.Remove(task); } }
    private async Task MountAsync(Record r, string url)
    {
        try
        {
            var template = await _cache.GetAsync(url);
            if (_disposed || r.Disposed || r.WantedUrl != url) return;
            if (template is null) { r.WantedUrl = r.ShownUrl; return; }
            RedrapeOne(r);
            var placed = ModelPlacement.Place(ModelCache.Instance(template), r.Spec);
            SceneModels.CastNone(placed);
            DropNode(r);
            r.Node = placed; r.ShownUrl = url;
            r.PlacedX = r.Spec.AnchorX; r.PlacedZ = r.Spec.AnchorZ; r.PlacedBottom = r.Spec.BottomY;
            placed.Visible = r.Tier != 2;
            AddChild(placed);
            Stats.Placed["world"]++;
            if (r.Tier == 0) Stats.Full++; else Stats.Low++;
            Stats.Vertices += template.Counts.Vertices; Stats.Indices += template.Counts.Indices;
            if (template.Compressed) Stats.Compressed++;
            RefreshGhost(r);
            WaterChanged?.Invoke();
        }
        catch (Exception e) { r.WantedUrl = r.ShownUrl; _log($"world prop {r.Id}: {e.Message}"); }
    }

    /// <summary>Task 40: a height revision translates existing nodes by the bottom difference, relifts sheets and re-gates ghosts.</summary>
    public void Redrape()
    {
        foreach (var r in _records.Values) RedrapeOne(r);
        WaterChanged?.Invoke();
    }
    private void RedrapeOne(Record r)
    {
        double x = Json.Num(r.Row, "x"), z = Json.Num(r.Row, "z"), ground = _height.GroundAt(x, z);
        r.Spec = WorldPropMath.SceneSpec(r.Row, WorldPropMath.Bottom(r.Row, ground));
        string lightKey = Key(r.Row, "light");
        if (r.LightKey != lightKey)
        {
            if (r.LightId is { } id) _lights?.Remove(id);
            r.LightId = null; r.LightKey = lightKey;
        }
        if (r.Spec.Light is { } light && _lights is not null)
        {
            var pos = new Vector3((float)(x + light.Offset.X), (float)(r.Spec.BottomY + light.HeightM), (float)(z + light.Offset.Z));
            if (r.LightId is { } id) _lights.Move(id, pos); else r.LightId = _lights.Register(light, pos, "");
        }
        string waterKey = Key(r.Row, "water");
        if (r.WaterKey != waterKey)
        {
            DropSheets(r); r.WaterKey = waterKey;
            r.Sheets = PropWaterSheets.Build(r.Spec.Water, this, ground);
        }
        PropWaterSheets.Relift(r.Sheets, r.Spec.Water, ground);
        SetSheetVisibility(r);
        if (r.Node is not { } node) return;
        node.Position += new Vector3((float)(x - r.PlacedX), (float)(r.Spec.BottomY - r.PlacedBottom), (float)(z - r.PlacedZ));
        r.PlacedX = x; r.PlacedZ = z; r.PlacedBottom = r.Spec.BottomY;
        RefreshGhost(r);
    }
    private void RefreshGhost(Record r)
    {
        if (r.Node is null) return;
        var level = WaterGates.PlacementGhostCut(_height.WaterRaster(), r.Spec.AnchorX, r.Spec.AnchorZ, r.Spec.BottomY);
        if (r.Ghost is null && level is not null) r.Ghost = new SubmergedGhost(r.Node);
        r.Ghost?.Set(level);
    }
    public void SetLod(ScatterLodCfg cfg) { Lod = WorldPropMath.LodCfg(cfg); if (_camera is { } cam) _ = TickAsync(cam); }
    private static void DropNode(Record r)
    {
        r.Ghost?.Dispose(); r.Ghost = null;
        if (r.Node is { } node) { node.GetParent()?.RemoveChild(node); node.QueueFree(); }
        r.Node = null; r.ShownUrl = "";
    }
    private static void DropSheets(Record r)
    {
        foreach (var sheet in r.Sheets) { sheet.GetParent()?.RemoveChild(sheet); sheet.QueueFree(); }
        r.Sheets.Clear();
    }
    private void Drop(Record r)
    {
        r.Disposed = true; DropNode(r); DropSheets(r);
        if (r.LightId is { } id) _lights?.Remove(id);
    }
    public override void _ExitTree() { _disposed = true; foreach (var r in _records.Values) Drop(r); _records.Clear(); }
}
