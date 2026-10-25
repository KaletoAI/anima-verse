using System;
using System.Collections.Generic;
using System.Text.Json;
using System.Text.Json.Nodes;
using AnimaNative.Ui;
using AnimaNative.World;
using Godot;

namespace AnimaNative.Bench;

/// <summary>What one run drives and reports.</summary>
/// <param name="Warmup">Seconds at keyframe 0 before the measured window (the path's value; the offline smoke shortens it).</param>
/// <param name="Duration">Seconds of the measured drive; the path is traversed in this time (path time = elapsed · path.duration / Duration, = elapsed in a real run).</param>
public sealed record BenchSettings(CameraPath Path, double Warmup, double Duration, AnchorInfo Anchor, string? Goto,
                                   bool Vsync, bool Scatter = false, bool Water = false);

/// <summary>
/// The bench drive in Godot — the counterpart of <c>client3d/src/bench/bench.ts</c>
/// (same path file, same anchor rule, same phase logic, same summary):
///
///   • warm-up: <see cref="BenchSettings.Warmup"/> s of wall time with the
///     camera at keyframe 0; then the drive along the path relative to the anchor;
///   • the free camera is switched off for the run and its pose restored after;
///     V-sync is disabled for the run unless <c>--vsync=on</c>;
///   • per frame the raw wall delta (<see cref="Time.GetTicksUsec"/>, never
///     clamped; the very first frame has none = 0, like the browser's first
///     <c>benchDt</c>) advances the phase; the frame that turns warm-up into the
///     drive establishes t = 0 and is NOT sampled, every later frame up to and
///     including the one that reaches the duration is;
///   • a sample: dt, <c>cpuMs</c> = <c>Performance.TimeProcess</c>·1000 (the
///     plan's choice), <c>renderCpuMs</c> = the viewport's measured render CPU
///     time, <c>gpuMs</c> = its measured GPU time (null on the headless dummy
///     renderer), draw calls and primitives of the frame.
///
/// One difference the browser does not have: Godot's monitors and measured
/// render times are read in <c>_Process</c>, i.e. they describe the PREVIOUS
/// rendered frame (the browser reads <c>renderer.info</c> right after its own
/// render call). Over a 20 s drive that one-frame shift does not move a median.
/// </summary>
public partial class BenchRunner : Node
{
    private enum Phase { Warm, Run, Done }

    private readonly FlyCamera _camera;
    private readonly BenchSettings _s;
    private readonly Action<JsonObject> _finished;
    private readonly List<BenchSample> _samples = new(4096);

    private Phase _phase = Phase.Warm;
    private double _warm, _elapsed;
    private ulong _lastUsec;
    private Rid _viewport;
    private bool _headless;
    private DisplayServer.VSyncMode _oldVsync;
    private (Vector3 Target, float Distance, float Yaw, float Pitch, Node3D? Follow) _saved;

    /// <summary>The last camera pose the drive set (world metres) — for the offline smoke.</summary>
    public Vector3 LastPosition { get; private set; }
    public Vector3 LastTarget { get; private set; }
    /// <summary>The measured frames (for the offline smoke).</summary>
    public IReadOnlyList<BenchSample> Samples => _samples;

    /// <summary>
    /// The settings of a run, shared by the online start and the offline smoke:
    /// the anchor from <paramref name="worldmap"/> (the CURRENT snapshot —
    /// browser: <c>lastMap ?? firstMap</c>) with the build's view=3d names and
    /// overview grid, frozen here; the embedded path; warm-up/duration from the
    /// path unless overridden (offline smoke only).
    /// </summary>
    public static BenchSettings SettingsFor(JsonElement worldmap, WorldBuilder builder, string? gotoQuery, bool vsync,
                                            double? warmup = null, double? duration = null, bool scatter = false)
    {
        var anchor = World.Anchor.FromWorld(worldmap, builder.Details, builder.Height!.Overview.Grid, gotoQuery,
                                            World.Anchor.BenchSource);
        var path = CameraPath.LoadEmbedded();
        return new BenchSettings(path, warmup ?? path.Warmup, duration ?? path.Duration, anchor, gotoQuery, vsync, scatter);
    }

    public BenchRunner(FlyCamera camera, BenchSettings settings, Action<JsonObject> finished)
    {
        Name = "Bench";
        _camera = camera;
        _s = settings;
        _finished = finished;
        ProcessPriority = 1000;  // after everything else that moves this frame
    }

    public override void _Ready()
    {
        _headless = DisplayServer.GetName() == "headless";
        _viewport = GetViewport().GetViewportRid();
        RenderingServer.ViewportSetMeasureRenderTime(_viewport, true);
        _oldVsync = DisplayServer.WindowGetVsyncMode();
        if (!_s.Vsync) DisplayServer.WindowSetVsyncMode(DisplayServer.VSyncMode.Disabled);

        _saved = (_camera.Target, _camera.Distance, _camera.Yaw, _camera.Pitch, _camera.Follow);
        _camera.Follow = null;
        _camera.SetProcess(false);
        _camera.SetProcessUnhandledInput(false);
        PlaceCamera(0);
        GD.Print($"[bench] warm-up {_s.Warmup}s; drive {_s.Duration}s; anchor ({_s.Anchor.X}, {_s.Anchor.Y}, {_s.Anchor.Z})"
                 + (_s.Anchor.LocationId is { } id ? $" {id}" : "") + $"; vsync {(_s.Vsync ? "on" : "off")}");
    }

    public override void _Process(double delta)
    {
        if (_phase == Phase.Done) return;
        ulong now = Time.GetTicksUsec();
        double dt = _lastUsec == 0 ? 0 : (now - _lastUsec) / 1e6;
        _lastUsec = now;

        // benchFrame
        if (_phase == Phase.Warm)
        {
            _warm += dt;
            if (_warm >= _s.Warmup) { _phase = Phase.Run; _elapsed = 0; }
        }
        else _elapsed += dt;
        double sampleTime = _phase == Phase.Run ? Math.Min(_elapsed, _s.Duration) : 0;

        // benchCamera
        PlaceCamera(sampleTime);

        // benchRendered: the transition frame establishes t = 0; only later intervals count.
        if (_phase != Phase.Run || _elapsed == 0) return;
        _samples.Add(Measure(dt));
        if (_elapsed < _s.Duration) return;
        Finish();
    }

    private void PlaceCamera(double sampleTime)
    {
        var (pos, target) = _s.Path.Sample(sampleTime * _s.Path.Duration / _s.Duration);
        var a = _s.Anchor;
        LastPosition = new Vector3((float)(pos[0] + a.X), (float)(pos[1] + a.Y), (float)(pos[2] + a.Z));
        LastTarget = new Vector3((float)(target[0] + a.X), (float)(target[1] + a.Y), (float)(target[2] + a.Z));
        // engine.target of the browser: the scatter window/undergrowth anchor follows it (restored after).
        _camera.Target = LastTarget;
        _camera.LookAtFromPosition(LastPosition, LastTarget, Vector3.Up);
    }

    private BenchSample Measure(double dt)
    {
        double cpuMs = Performance.GetMonitor(Performance.Monitor.TimeProcess) * 1000.0;
        double calls = Performance.GetMonitor(Performance.Monitor.RenderTotalDrawCallsInFrame);
        double tris = Performance.GetMonitor(Performance.Monitor.RenderTotalPrimitivesInFrame);
        double? gpu = _headless ? null : RenderingServer.ViewportGetMeasuredRenderTimeGpu(_viewport);
        double? renderCpu = _headless ? null : RenderingServer.ViewportGetMeasuredRenderTimeCpu(_viewport);
        return new BenchSample(dt, cpuMs, gpu, calls, tris, renderCpu);
    }

    private void Finish()
    {
        _phase = Phase.Done;
        var summary = BenchStats.Summarize(_samples);
        double? renderCpu = BenchStats.MedianOrNull(_samples.ConvertAll(x => x.RenderCpuMs));
        var vp = GetViewport().GetVisibleRect().Size;
        var info = Engine.GetVersionInfo();
        string vendor = RenderingServer.GetVideoAdapterVendor();
        string adapter = RenderingServer.GetVideoAdapterName();
        var result = BuildResult(_s, summary, renderCpu, $"{(int)vp.X}x{(int)vp.Y}",
                                 info.ContainsKey("string") ? info["string"].AsString() : "",
                                 vendor.Length > 0 ? $"{adapter} ({vendor})" : adapter,
                                 OS.GetProcessorName());

        // Restore normal play.
        RenderingServer.ViewportSetMeasureRenderTime(_viewport, false);
        if (!_s.Vsync) DisplayServer.WindowSetVsyncMode(_oldVsync);
        (_camera.Target, _camera.Distance, _camera.Yaw, _camera.Pitch, _camera.Follow) = _saved;
        _camera.SetProcess(true);
        _camera.SetProcessUnhandledInput(true);

        _finished(result);
        QueueFree();
    }

    /// <summary>
    /// The result object — the browser's keys in the browser's order
    /// (<c>bench.ts</c>: backend … size, the summary, fps/gpuMs/draws/triangles),
    /// then the native extras <c>renderCpuMsMedian</c>, <c>godot</c>, <c>gpu</c>, <c>cpu</c>.
    /// </summary>
    public static JsonObject BuildResult(BenchSettings s, BenchSummary sum, double? renderCpuMsMedian, string size,
                                         string godot, string gpu, string cpu)
    {
        var a = s.Anchor;
        return new JsonObject
        {
            ["backend"] = "godot-forward+",
            ["path"] = CameraPath.RepoPath,
            ["pathVersion"] = s.Path.Version,
            ["duration"] = s.Duration,
            ["warmup"] = s.Warmup,
            ["flags"] = new JsonObject
            {
                ["goto"] = s.Goto,
                ["scatter"] = s.Scatter,
                ["water"] = s.Water,
                ["vsync"] = s.Vsync,
            },
            ["anchor"] = new JsonObject
            {
                ["pos"] = new JsonArray(a.X, a.Y, a.Z),
                ["locationId"] = a.LocationId,
                ["heightSource"] = a.Source,
            },
            ["size"] = size,
            ["frames"] = sum.Frames,
            ["seconds"] = sum.Seconds,
            ["fpsMean"] = sum.FpsMean,
            ["frameMsMedian"] = sum.FrameMsMedian,
            ["frameMsP95"] = sum.FrameMsP95,
            ["cpuMsMedian"] = sum.CpuMsMedian,
            ["cpuMsP95"] = sum.CpuMsP95,
            ["gpuMsMedian"] = sum.GpuMsMedian,
            ["callsMedian"] = sum.CallsMedian,
            ["trisMedian"] = sum.TrisMedian,
            ["fps"] = sum.FpsMean,
            ["gpuMs"] = sum.GpuMsMedian,
            ["draws"] = sum.CallsMedian,
            ["triangles"] = sum.TrisMedian,
            ["renderCpuMsMedian"] = renderCpuMsMedian,
            ["godot"] = godot,
            ["gpu"] = gpu,
            ["cpu"] = cpu,
        };
    }
}
