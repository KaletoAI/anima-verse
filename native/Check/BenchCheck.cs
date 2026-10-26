using System;
using System.IO;
using System.Linq;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Threading.Tasks;
using AnimaNative.Bench;
using AnimaNative.Figures;
using AnimaNative.Gltf;
using AnimaNative.Scatter;
using AnimaNative.Ui;
using AnimaNative.World;
using Godot;

namespace AnimaNative.Check;

/// <summary>
/// <c>-- --check-bench</c>: the offline bench smoke. Builds the fixture world
/// (terrain, tiles, buildings, the first poll's figures — the same code as
/// online), then runs THE bench driver for a 0.5 s warm-up and a 2 s drive (the
/// whole 20 s path compressed into it) and checks what can be checked without a
/// GPU:
///
///   • anchor = the fixture's <c>harbour</c> → loc-house (64, 7.5, 128), label =
///     the browser's bench <c>heightSource</c>;
///   • measured window: frames &gt; 0, seconds ≥ 2 and less than 2 + the largest
///     frame interval (the run ends on the first frame that reaches 2 s),
///     fpsMean = frames / seconds;
///   • the last camera pose = the path's END keyframe + anchor:
///     pos (0, 24, 40) + (64, 7.5, 128) = (64, 31.5, 168), target (64, 9, 128);
///   • the result keys in the browser's order plus the native extras, gpu/render
///     times null (headless dummy renderer), flags {goto, scatter false, water
///     false, vsync};
///   • the free camera is handed back (processing on, pose restored);
///   • the written file parses to the printed object.
///
/// With <c>--scatter</c> (Task S3) the fixture's scatter + undergrowth layers ride along exactly as online
/// (anchored on the camera target, the browser's LOD cadence): flags.scatter true, the extra
/// <c>scatterLayers</c> key, the window followed the drive to the end target, LOD passes ran.
/// </summary>
public static class BenchCheck
{
    private const double Warmup = 0.5, Duration = 2.0;
    private static readonly string[] Keys =
    {
        "backend", "path", "pathVersion", "duration", "warmup", "flags", "anchor", "size", "frames", "seconds",
        "fpsMean", "frameMsMedian", "frameMsP95", "cpuMsMedian", "cpuMsP95", "gpuMsMedian", "callsMedian",
        "trisMedian", "fps", "gpuMs", "draws", "triangles", "renderCpuMsMedian", "godot", "gpu", "cpu",
    };

    public static async Task<int> RunAsync(Node3D host, OverviewCamera camera, CliOptions options)
    {
        try
        {
            var dir = Path.Combine(ProjectSettings.GlobalizePath("res://"), "fixtures");
            MeshoptNative.EnsureLoaded(ProjectSettings.GlobalizePath("res://bin"));
            var source = new FixtureSource(dir);
            var world = new Node3D { Name = "World" };
            host.AddChild(world);
            void Log(string line) => GD.Print("[check-bench] " + line);
            var gotoQuery = options.Goto ?? "harbour";
            var builder = new WorldBuilder(source, Log, strict: true) { NoWater = options.NoWater };
            var stats = await builder.BuildAsync(world, gotoQuery);
            var figures = new FigureManager(source, builder.Height!, Log, strict: true);
            world.AddChild(figures);
            await figures.InitAsync();
            using (var map = await source.GetWorldMapAsync()) await figures.Apply(map.RootElement);
            Log($"world {stats.Summary()} | figures {figures.Stats.Summary()}");

            ScatterLayer? scatter = null;
            if (options.Scatter)
            {
                scatter = await ScatterLayer.CreateAsync(source, builder.Height!, builder.FirstMap!.Value,
                                                         () => camera.Target, Log);
                world.AddChild(scatter);
                ulong t0 = Time.GetTicksMsec();
                do await host.ToSignal(host.GetTree(), SceneTree.SignalName.ProcessFrame);
                while (scatter.Field.Busy && Time.GetTicksMsec() - t0 < 60000);
                Expect("scatter settled", !scatter.Field.Busy, "loads still running after 60 s");
                Log("scatter settled: " + scatter.Summary());
            }
            var settings = BenchRunner.SettingsFor(builder.FirstMap!.Value, builder, gotoQuery, options.Vsync,
                                                   Warmup, Duration, scatter: scatter is not null,
                                                   water: stats.WaterMode == "drawn");
            var anchor = settings.Anchor;
            if (options.Goto is null)
                Expect("anchor", anchor.Position().DistanceTo(new Vector3(64f, 7.5f, 128f)) < 1e-4f
                                 && anchor.LocationId == "loc-house", $"{anchor}");
            Expect("anchor label", anchor.Source == Anchor.BenchSource, anchor.Source);

            camera.JumpTo(anchor.Position() + new Vector3(0, 1.5f, 0), 33);
            var before = (camera.Target, camera.Distance);
            var done = new TaskCompletionSource<JsonObject>(TaskCreationOptions.RunContinuationsAsynchronously);
            builder.Terrain!.ResetPeak();
            var runner = new BenchRunner(camera, settings, r => done.TrySetResult(r));
            host.AddChild(runner);
            var finished = await Task.WhenAny(done.Task, Task.Delay(TimeSpan.FromSeconds(60)));
            Expect("bench finished", finished == done.Task, "no result within 60 s");
            var result = done.Task.Result;
            int passesAtEnd = scatter?.LodPasses ?? 0;
            if (scatter is not null) result["scatterLayers"] = scatter.Summary();
            result["ground"] = stats.Ground.Summary();
            result["water"] = stats.WaterSummary();
            result["terrain"] = builder.Terrain!.Summary();
            var file = BenchOutput.Emit(result);
            BenchOutput.ShowPanel(host, result, file);
            Expect("panel", host.GetNodeOrNull("BenchResult") is not null, "no result panel");
            Expect("printed line unescaped", BenchOutput.Line(result).Contains("\"backend\":\"godot-forward+\""),
                   BenchOutput.Line(result));

            Expect("keys", result.Select(kv => kv.Key).SequenceEqual((scatter is null ? Keys : Keys.Append("scatterLayers")).Append("ground").Append("water").Append("terrain")),
                   string.Join(",", result.Select(kv => kv.Key)));
            Expect("backend", (string?)result["backend"] == "godot-forward+", $"{result["backend"]}");
            Expect("path", (string?)result["path"] == "shared/bench/camera_path_v1.json", $"{result["path"]}");
            Expect("duration/warmup", (double)result["duration"]! == Duration && (double)result["warmup"]! == Warmup, "");
            var flags = result["flags"]!.AsObject();
            Expect("flags", flags.Select(kv => kv.Key).SequenceEqual(new[] { "goto", "scatter", "water", "vsync" })
                            && (string?)flags["goto"] == gotoQuery && (bool)flags["scatter"]! == (scatter is not null) && !(bool)flags["water"]!
                            && (bool)flags["vsync"]! == options.Vsync, flags.ToJsonString());
            var a = result["anchor"]!.AsObject();
            Expect("anchor object", (string?)a["locationId"] == anchor.LocationId && (string?)a["heightSource"] == Anchor.BenchSource
                                    && (double)a["pos"]![1]! == anchor.Y, a.ToJsonString());

            int frames = (int)result["frames"]!;
            double seconds = (double)result["seconds"]!;
            double p95 = (double)result["frameMsP95"]!;
            Expect("frames", frames > 0, $"{frames}");
            Expect("seconds ≥ duration", seconds >= Duration, $"{seconds}");
            Expect("fpsMean = frames / seconds", Math.Abs((double)result["fpsMean"]! - frames / seconds) < 1e-9, "");
            Expect("fps = fpsMean", (double)result["fps"]! == (double)result["fpsMean"]!, "");
            Expect("headless: gpu null", result["gpuMsMedian"] is null && result["gpuMs"] is null
                                         && result["renderCpuMsMedian"] is null, result.ToJsonString());
            Expect("p95 ≤ the run", p95 / 1000 <= seconds, $"{p95}");
            Expect("samples = frames", runner.Samples.Count == frames, $"{runner.Samples.Count}");
            Expect("the run ends on the first frame that reaches the duration",
                   seconds - runner.Samples[^1].Dt < Duration + 1e-9, $"{seconds} - {runner.Samples[^1].Dt}");

            var wantPos = new Vector3(0, 24f, 40f) + anchor.Position();      // end keyframe pos (-0, 24, 40)
            var wantTarget = new Vector3(0, 1.5f, 0) + anchor.Position();
            Expect("last camera position = end keyframe + anchor", runner.LastPosition.DistanceTo(wantPos) < 1e-4f,
                   $"{runner.LastPosition} vs {wantPos}");
            Expect("last camera target", runner.LastTarget.DistanceTo(wantTarget) < 1e-4f, $"{runner.LastTarget} vs {wantTarget}");
            Expect("camera handed back", camera.IsProcessing() && camera.IsProcessingUnhandledInput()
                                         && camera.Target == before.Target && camera.Distance == before.Distance,
                   $"processing={camera.IsProcessing()} target={camera.Target}");

            if (scatter is not null)
            {
                // The window follows engine.target: the end target (64, 9, 128) lies in cell (1, 2), so the
                // 5 × 5 window starts at (-1, 0); the 1 Hz tick ran at least twice in the 2.5 s.
                var cells = scatter.Field.Cells;
                Expect("scatter window follows the target", cells.Count == 25 && cells[0] == (-1, 0), string.Join(";", cells.Take(2)));
                Expect("scatter LOD passes", passesAtEnd >= 3, $"{passesAtEnd}");
                Expect("scatterLayers key", ((string?)result["scatterLayers"])?.StartsWith("scatter[") == true, $"{result["scatterLayers"]}");
            }

            // Task S3c: the fixture world has a water LAYER but no wet height tile → no water drawn, flag false.
            Expect("water key", (string?)result["water"] == (options.NoWater ? "water[off: --no-water]" : "water[none]"),
                   $"{result["water"]}");
            Expect("ground key: the fixture world draws the layer material",
                   ((string?)result["ground"])?.StartsWith("ground[layers=") == true, $"{result["ground"]}");
            var written = JsonNode.Parse(File.ReadAllText(file))!;
            Expect("file = printed result", JsonNode.DeepEquals(written, result), file);

            GD.Print($"CHECK-BENCH ok frames={frames} seconds={seconds:0.####} fpsMean={(double)result["fpsMean"]!:0.#} "
                     + $"frameMsMedian={(double)result["frameMsMedian"]!:0.###} cpuMsMedian={(double)result["cpuMsMedian"]!:0.###} "
                     + $"draws={result["draws"]} triangles={result["triangles"]} size={result["size"]} "
                     + $"gpu=null (headless dummy renderer) file={file}"
                     + (scatter is not null ? $" | {scatter.Summary()}" : "") + $" | {stats.Ground.Summary()} | {stats.WaterSummary()}");
            builder.Models?.FreeAll();   // the GLB templates never enter the tree (World/ModelCache.cs)
            return 0;
        }
        catch (Exception e)
        {
            GD.PrintErr($"CHECK-BENCH FAILED {e.GetType().Name}: {e.Message}");
            GD.Print($"CHECK-BENCH FAILED {e.GetType().Name}: {e.Message}");
            return 1;
        }
    }

    private static void Expect(string what, bool ok, string detail)
    {
        if (!ok) throw new InvalidOperationException($"{what}: {detail}");
    }
}
