using System;
using System.Collections.Generic;
using System.Text.Json.Nodes;
using System.Threading.Tasks;
using AnimaNative.Bench;
using AnimaNative.World;
using Godot;

namespace AnimaNative;

/// <summary>
/// Main, the bench matrix (<c>--bench-matrix</c>, Task 26b): the drive of <c>--bench</c> once per variant of
/// <see cref="BenchMatrix"/>, in this process, on this world, with the same anchor, warm-up and duration — each pass with
/// exactly one feature switched off by <see cref="BenchSwitches"/> and put back after it, a baseline pass between every
/// two variants (<see cref="BenchMatrix.Schedule"/>, Task 26c: drift). Every pass prints the usual
/// <c>[bench] result {json}</c> line (plus <c>variant</c>, <c>switch</c>, <c>applied</c>, <c>matrixId</c>,
/// <c>matrixPass</c>, <c>matrixPasses</c>), appends it to ONE file <c>user://bench-matrix-&lt;stamp&gt;.jsonl</c> and posts it
/// to <c>/play/bench-result</c> (online); the end prints the summary table (each variant against the mean of its two
/// neighbouring baselines), shows it on screen and appends one <c>matrixSummary</c> line to the local file.
/// </summary>
public partial class Main : Node3D
{
    private async Task RunBenchMatrixAsync(WorldBuilder builder)
    {
        // Task 26c: a baseline between every two variants (drift on a laptop iGPU); deltas against the neighbours.
        var variants = BenchMatrix.Schedule(BenchMatrix.Select(_options!.BenchMatrix));
        var settings = BenchRunner.SettingsFor(_figures!.LatestMap ?? builder.FirstMap!.Value, builder,
                                               _options.Goto, _options.Vsync, scatter: _scatter is not null,
                                               water: _waterDrawn);
        string stamp = DateTime.Now.ToString("yyyyMMdd-HHmmss");
        string userPath = $"user://bench-matrix-{stamp}.jsonl";
        string file = ProjectSettings.GlobalizePath(userPath);
        var ctx = new BenchSwitchContext
        {
            Stage = _stage,
            Fog = _stage?.Fog,
            Backdrop = () => _backdrop,
            Builder = builder,
            Figures = _figures,
            Gate = _shadowGate,
        };
        double minutes = variants.Count * (settings.Warmup + settings.Duration) / 60;
        Log($"bench matrix {stamp}: {variants.Count} passes × ({settings.Warmup} s warm-up + {settings.Duration} s drive) ≈ "
            + $"{minutes:0.#} min; results → {file}");
        var rows = new List<BenchMatrixRow>();
        for (int i = 0; i < variants.Count; i++)
        {
            if (_stop.IsCancellationRequested || Leaving) return;
            var v = variants[i];
            var sw = BenchSwitches.Apply(v.Name, ctx);
            Log($"bench matrix {i + 1}/{variants.Count} {v.Name}: {sw.Detail}{(sw.Applied ? "" : " (nothing to switch)")}");
            JsonObject result;
            try
            {
                // Two frames for the switch to land (a hidden node leaves the scenario, a uniform reaches the GPU); the
                // drive's own warm-up then absorbs pipeline compiles and the terrain re-selection.
                await ToSignal(GetTree(), SceneTree.SignalName.ProcessFrame);
                await ToSignal(GetTree(), SceneTree.SignalName.ProcessFrame);
                builder.Terrain?.ResetPeak();
                _streamer?.Probe.Reset();
                var done = new TaskCompletionSource<JsonObject>(TaskCreationOptions.RunContinuationsAsynchronously);
                AddChild(new BenchRunner(_camera!, settings, r => done.TrySetResult(r)));
                result = await done.Task;
                // The extras (the shadow census among them) while the switch is still in force.
                AddBenchExtras(result, builder);
            }
            finally
            {
                sw.Restore();
            }
            result["variant"] = v.Name;
            result["switch"] = sw.Detail;
            result["applied"] = sw.Applied;
            result["matrixId"] = stamp;
            result["matrixPass"] = i + 1;
            result["matrixPasses"] = variants.Count;
            string line = BenchOutput.Line(result);
            GD.Print("[bench] result " + line);
            try
            {
                System.IO.File.AppendAllText(file, line + "\n");
            }
            catch (Exception e)
            {
                Log($"bench matrix: cannot write {file}: {e.Message}");
            }
            rows.Add(new BenchMatrixRow(v.Name, (double)result["fps"]!, (double)result["frameMsMedian"]!,
                                        (double)result["frameMsP95"]!, result["gpuMs"] is { } g ? (double)g : (double?)null,
                                        (double)result["draws"]!, (double)result["triangles"]!, sw.Applied));
            if (_api is not null)
            {
                try
                {
                    await _api.PostBenchResultAsync(line);
                    Log($"bench matrix {v.Name}: sent to the server (logs/bench.jsonl)");
                }
                catch (Exception e)
                {
                    Log($"bench matrix {v.Name}: NOT sent to the server: {e.Message}");
                }
            }
        }
        string table = BenchMatrix.Table(rows);
        // One closing line in the local file: every pass with its reference (neighbouring baselines) and delta.
        var deltas = BenchMatrix.NeighbourDeltas(rows);
        var summary = new JsonArray();
        for (int i = 0; i < rows.Count; i++)
            summary.Add(new JsonObject
            {
                ["matrixPass"] = i + 1, ["variant"] = rows[i].Variant, ["applied"] = rows[i].Applied, ["gpuMs"] = rows[i].GpuMs,
                ["gpuRefMs"] = deltas[i].Reference, ["gpuDeltaMs"] = deltas[i].Delta,
            });
        try
        {
            System.IO.File.AppendAllText(file, BenchOutput.Line(new JsonObject { ["matrixId"] = stamp, ["matrixSummary"] = summary }) + "\n");
        }
        catch (Exception e)
        {
            Log($"bench matrix: cannot write the summary to {file}: {e.Message}");
        }
        foreach (var l in table.TrimEnd('\n').Split('\n')) GD.Print("[bench-matrix] " + l);
        Log($"bench matrix done: {rows.Count} passes written to {file}");
        BenchOutput.ShowText(this, $"Bench matrix {stamp} — {file}", table);
        if (_options.QuitAfterBench || _options.Offline is not null) GetTree().Quit(0);
    }
}
