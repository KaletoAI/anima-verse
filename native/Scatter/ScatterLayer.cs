using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
using System.Threading.Tasks;
using AnimaNative.Api;
using AnimaNative.Ground;
using AnimaNative.World;
using Godot;

namespace AnimaNative.Scatter;

/// <summary>
/// <c>--scatter</c>: both layers the browser bench's <c>&amp;scatter=0</c> hides — the authored scatter
/// (<see cref="ScatterField"/>) and the undergrowth (<see cref="UndergrowthField"/>) — driven at the
/// browser's cadence (client3d/src/main.ts):
///
///   · the 1 Hz LOD tick: a full LOD pass, then <c>setHeightAnchor(engine.target)</c> (scatter window +
///     undergrowth cells);
///   · the movement driver (a frame hook): another pass when ≥ 100 ms have passed AND the camera moved
///     more than 8 m or turned more than 10° (<c>SCATTER_LOD_MIN_MS / _MOVE_M / _YAW_RAD</c>).
///
/// The anchor is the camera's look-at target (<see cref="Ui.OverviewCamera.Target"/>; the bench driver keeps it
/// on the path's target like the browser's <c>engine.target</c>). The browser's movement driver compares
/// <c>engine.yaw</c>, the orbit yaw, which the bench does not update; this compares the camera's real
/// heading — at most extra passes, i.e. extra CPU for Godot.
/// </summary>
public partial class ScatterLayer : Node3D
{
    public const double LodTickS = 1.0, LodMinS = 0.1, LodMoveM = 8, LodYawRad = 10 * Math.PI / 180;

    public ScatterField Field { get; }
    public UndergrowthField Undergrowth { get; }
    private readonly Func<Vector3> _anchor;
    private TerrainPayload? _terrain;
    private string _footprintSig = "";
    private Func<GroundSurfaces?>? _ground;
    private GroundSurfaces? _boundGround;
    private LayerMaskWindow? _boundMask;
    private readonly Action<string> _log;
    private double _sinceTick = double.PositiveInfinity, _sinceLod = double.PositiveInfinity, _sinceLog;
    private Vector3 _lodPos = new(float.NaN, float.NaN, float.NaN);
    private double _lodYaw = double.NaN;
    public int LodPasses { get; private set; }

    public ScatterLayer(IWorldSource source, WorldHeight height, Func<Vector3> anchor, Action<string> log)
    {
        Name = "ScatterLayer";
        _anchor = anchor;
        _log = log;
        Field = new ScatterField(source, height, log);
        Undergrowth = new UndergrowthField(height);
        AddChild(Field);
        AddChild(Undergrowth);
    }

    /// <summary><c>GET /play/terrain</c> + the worldmap's location outlines and game clock → both layers.</summary>
    public static async Task<ScatterLayer> CreateAsync(IWorldSource source, WorldHeight height, JsonElement worldmap,
                                                       Func<Vector3> anchor, Action<string> log)
    {
        using var doc = await source.GetTerrainAsync();
        var terrain = TerrainPayload.Parse(doc.RootElement);
        var layer = new ScatterLayer(source, height, anchor, log);
        if (worldmap.TryGetProperty("game_time", out var gt) && TerrainPayload.NumOrNull(gt, "total_seconds") is double s)
            layer.Field.GameSeconds = s;
        layer._terrain = terrain;
        layer._footprintSig = TerrainPayload.FootprintSignature(worldmap);
        var locFp = TerrainPayload.LocationFootprints(worldmap);
        var a = anchor();
        layer.Field.SetAnchor(a.X, a.Z);
        // The boot's window is sampled right here (before the first picture); every later rebuild goes to a worker.
        layer.Field.SetTerrain(terrain, locFp, inline: true);
        var all = new List<IReadOnlyList<P2>>(locFp);
        all.AddRange(terrain.PropFootprints());
        layer.Undergrowth.SetAreas(UndergrowthField.AreasOf(terrain), all);
        layer.Undergrowth.SetAnchor(a.X, a.Z, inline: true);
        log($"scatter: terrain {terrain.Areas.Count} areas, {terrain.Types.Count} types, {terrain.PropBoxes.Count} prop boxes, "
            + $"{locFp.Count} location footprints; window {layer.Field.Cells.Count} cells");
        return layer;
    }

    /// <summary><c>rebuildAreas</c> after the ground moved under both layers (a streamed batch, a new relief).</summary>
    /// <param name="tiles">The tile squares whose ground changed (null = all of it, a new relief).</param>
    public void Redrape(IReadOnlyCollection<(int Tx, int Tz)>? tiles = null, double tileM = 0)
    {
        Field.Redrape(tiles, tileM);
        Undergrowth.Redrape(tiles, tileM);
    }

    /// <summary>
    /// A new <c>terrain_sig</c>: the painted terrain is fetched again and both layers are rebuilt from it with the
    /// current map's location outlines (<c>reload</c> → <c>rebuildAreas</c>).
    /// </summary>
    public async Task ReloadAsync(IWorldSource source, JsonElement worldmap)
    {
        using var doc = await source.GetTerrainAsync();
        var terrain = TerrainPayload.Parse(doc.RootElement);
        _terrain = terrain;
        _footprintSig = TerrainPayload.FootprintSignature(worldmap);
        var locFp = TerrainPayload.LocationFootprints(worldmap);
        Field.SetTerrain(terrain, locFp);
        var all = new List<IReadOnlyList<P2>>(locFp);
        all.AddRange(terrain.PropFootprints());
        Undergrowth.SetAreas(UndergrowthField.AreasOf(terrain), all);
        _log($"scatter: terrain reloaded ({terrain.Areas.Count} areas, {terrain.PropBoxes.Count} prop boxes)");
    }

    /// <summary>Task 39 D4/D5: every accepted poll supplies the game clock and location outlines.
    /// Only a changed epoch or footprint signature re-samples; both layers share the new footprints.</summary>
    public void SyncWorldMap(JsonElement worldmap)
    {
        Field.GameSeconds = worldmap.TryGetProperty("game_time", out var gt)
            ? TerrainPayload.NumOrNull(gt, "total_seconds") ?? double.NaN : double.NaN;
        string sig = TerrainPayload.FootprintSignature(worldmap);
        if (sig == _footprintSig || _terrain is null) return;
        _footprintSig = sig;
        var loc = TerrainPayload.LocationFootprints(worldmap);
        Field.SetTerrain(_terrain, loc);
        Undergrowth.SetAreas(UndergrowthField.AreasOf(_terrain), loc.Cast<IReadOnlyList<P2>>().Concat(_terrain.PropFootprints()));
    }

    /// <summary>Task 39 D6: bind the ground already loaded by the world; follow replacements and streamed
    /// windows on the main thread, without fetching a second set of masks.</summary>
    public void BindGround(Func<GroundSurfaces?> ground)
    {
        _ground = ground;
        RefreshMask();
    }

    private void RefreshMask()
    {
        if (_ground is null) return;
        var g = _ground();
        if (ReferenceEquals(g, _boundGround) && ReferenceEquals(g?.Window, _boundMask)) return;
        _boundGround = g; _boundMask = g?.Window;
        Undergrowth.SetLayerMask(g?.Window, g?.Layers ?? Enumerable.Empty<TerrainLayer>());
    }

    public override void _Process(double delta)
    {
        RefreshMask();
        var cam = GetViewport().GetCamera3D();
        if (cam is null) return;
        _sinceTick += delta;
        _sinceLod += delta;
        _sinceLog += delta;
        if (_sinceTick >= LodTickS)
        {
            _sinceTick = 0;
            // main.ts order: runScatterLod() first, then setHeightAnchor(engine.target) — a window that
            // moved is re-sampled and binned against the camera of that very pass.
            RunLod(cam);
            var a = _anchor();
            Field.SetAnchor(a.X, a.Z);
            Undergrowth.SetAnchor(a.X, a.Z);
        }
        else if (_sinceLod >= LodMinS)
        {
            var fwd = -cam.GlobalTransform.Basis.Z;
            double yaw = Math.Atan2(fwd.X, fwd.Z);
            double turn = Math.Abs(Math.IEEERemainder(yaw - _lodYaw, 2 * Math.PI));
            bool moved = !(cam.GlobalPosition.DistanceTo(_lodPos) <= LodMoveM);
            if (!double.IsFinite(_lodYaw) || turn > LodYawRad || moved) RunLod(cam);
        }
        if (_sinceLog >= 5)
        {
            _sinceLog = 0;
            _log("scatter " + Summary());
        }
    }

    public void RunLod(Camera3D cam)
    {
        var p = cam.GlobalPosition;
        var fwd = -cam.GlobalTransform.Basis.Z;
        var size = GetViewport().GetVisibleRect().Size;
        double aspect = size.Y > 0 ? size.X / size.Y : 16.0 / 9.0;
        Field.Tick(p.X, p.Y, p.Z, fwd.X, fwd.Z, cam.Fov, aspect);
        Undergrowth.Tick(p.X, p.Y, p.Z);
        _sinceLod = 0;
        _lodPos = p;
        _lodYaw = Math.Atan2(fwd.X, fwd.Z);
        LodPasses++;
    }

    /// <summary>
    /// A fingerprint of everything both layers placed: every authored prop's (row, variant, base count, instance
    /// transforms) in area order, then every undergrowth layer's (cell, area, base count, transforms + colours) in cell
    /// order. Two runs that placed the same instances print the same 16 hex digits — the before/after proof of the
    /// worker build (Task 26).
    /// </summary>
    public string Digest()
    {
        using var sha = System.Security.Cryptography.IncrementalHash.CreateHash(System.Security.Cryptography.HashAlgorithmName.SHA256);
        void Ints(params int[] v)
        {
            foreach (var i in v) sha.AppendData(BitConverter.GetBytes(i));
        }
        void Floats(float[] f, int count) => sha.AppendData(System.Runtime.InteropServices.MemoryMarshal.AsBytes(f.AsSpan(0, count)));
        int props = 0, layers = 0;
        foreach (var p in Field.Props)
        {
            Ints(p.Row, p.VariantPos, p.BaseCount);
            Floats(p.Src, p.BaseCount * 12);
            props++;
        }
        foreach (var l in Undergrowth.Layers.OrderBy(l => l.Cell.Cx).ThenBy(l => l.Cell.Cz))
        {
            Ints(l.Cell.Cx, l.Cell.Cz, l.BaseCount);
            sha.AppendData(System.Text.Encoding.UTF8.GetBytes(l.AreaId));
            Floats(l.Src, l.BaseCount * 16);
            layers++;
        }
        var ledger = ScatterField.MeasuredUrls();
        string ledgerHash = Convert.ToHexString(System.Security.Cryptography.SHA256.HashData(
            System.Text.Encoding.UTF8.GetBytes(string.Join("\n", ledger))))[..8].ToLowerInvariant();
        return $"digest={Convert.ToHexString(sha.GetHashAndReset())[..16].ToLowerInvariant()} props={props} ug_layers={layers} "
               + $"measured_urls={ledger.Count}/{ledgerHash}";
    }

    /// <summary>Loads in flight, a clearance re-sample armed, or either layer building on its worker.</summary>
    public bool Busy => Field.Busy || Undergrowth.Building;

    public string Summary()
    {
        var s = Field.Counts();
        var u = Undergrowth.Counts();
        return $"scatter[{s}] undergrowth[{u}] triangles={s.Triangles + u.Triangles} rebuilds={Field.Rebuilds} redrapes={Field.Redrapes} "
               + $"skipped_rows={Field.SkippedRows} lod_passes={LodPasses} "
               + $"worker_ms={Field.LastBuildMs:0.#}/{Field.MaxBuildMs:0.#} mount_ms={Field.LastApplyMs:0.##}/{Field.MaxApplyMs:0.##} "
               + $"ug_cells_built={Undergrowth.CellsBuilt} ug_worker_ms={Undergrowth.LastBuildMs:0.#}/{Undergrowth.MaxBuildMs:0.#} "
               + $"ug_mount_ms={Undergrowth.LastApplyMs:0.##}/{Undergrowth.MaxApplyMs:0.##} discarded={Field.Discarded + Undergrowth.Discarded}";
    }
}
