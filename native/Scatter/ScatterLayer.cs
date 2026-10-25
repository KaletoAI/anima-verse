using System;
using System.Collections.Generic;
using System.Text.Json;
using System.Threading.Tasks;
using AnimaNative.Api;
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
/// The anchor is the camera's look-at target (<see cref="Ui.FlyCamera.Target"/>; the bench driver keeps it
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
        Field = new ScatterField(source, height.GroundAt, log);
        Undergrowth = new UndergrowthField(height.GroundAt);
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
        var locFp = TerrainPayload.LocationFootprints(worldmap);
        var a = anchor();
        layer.Field.SetAnchor(a.X, a.Z);
        layer.Field.SetTerrain(terrain, locFp);
        var all = new List<IReadOnlyList<P2>>(locFp);
        all.AddRange(terrain.PropFootprints());
        layer.Undergrowth.SetAreas(UndergrowthField.AreasOf(terrain), all);
        layer.Undergrowth.SetAnchor(a.X, a.Z);
        log($"scatter: terrain {terrain.Areas.Count} areas, {terrain.Types.Count} types, {terrain.PropBoxes.Count} prop boxes, "
            + $"{locFp.Count} location footprints; window {layer.Field.Cells.Count} cells");
        return layer;
    }

    public override void _Process(double delta)
    {
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

    public string Summary()
    {
        var s = Field.Counts();
        var u = Undergrowth.Counts();
        return $"scatter[{s}] undergrowth[{u}] triangles={s.Triangles + u.Triangles} rebuilds={Field.Rebuilds} "
               + $"skipped_rows={Field.SkippedRows} lod_passes={LodPasses}";
    }
}
