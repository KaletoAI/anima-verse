using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Security.Cryptography;
using System.Text.Json;
using System.Threading.Tasks;
using AnimaNative.Scatter;
using AnimaNative.World;
using Godot;

namespace AnimaNative.Check;

/// <summary>
/// The scatter part of <c>--check</c> (Task S3):
///
///   1. the C# sampler against the TS sampler's own output (<c>fixtures/scatter_reference.json</c>, written
///      by <c>scatter_reference.mjs</c>): every instance x/z/yaw within 1e-6, variants equal, the maxPoints
///      case a prefix of the full run; seeds, hashes, shades and the blade texture bytes;
///   2. the fixture world (<c>terrain.json</c>) through the RUNTIME layers: the window cells, footprints,
///      every row's instances before the prop mesh landed (estimated clearance) and after (measured), the
///      per-entry MultiMesh counts after the LOD at the fixture camera, the undergrowth cells, instances and
///      bins — against the reference; then the HAND-DERIVED numbers of <c>fixtures/README.md</c> (window 25
///      cells, 20 undergrowth cells, wanted per cell 41 / 61 / 66, 5909 / 1477 triangles per tree, 12 per
///      tuft, 10 per cone, nothing drawn from a camera 2 km away).
/// </summary>
public static class ScatterCheck
{
    private const double Tol = 1e-6;
    private const int ExpWindowCells = 25;          // k = ceil(120/64) = 2 → 5 × 5
    private const int ExpUndergrowthCells = 20;     // README: 25 candidates minus 5 corners beyond 128 m
    private const int ExpTreesPerCell = 41;         // round(40.96 · 1.0)
    private const int ExpTuftsPerCell = 61;         // round(40.96 · 1.5)
    private const int ExpUndergrowthPerCell = 66;   // round(40.96 · 0.8·100·0.02) = round(65.536)
    private const int ExpFullTris = 5909, ExpLowTris = 1477, ExpConeTris = 10, ExpTuftTris = 12;
    private const string FullUrl = "/assets/props/broadleaf/model.glb?tier=full";
    private const string LowUrl = "/assets/props/broadleaf/model.glb?tier=low";

    public static async Task<string> RunAsync(Node3D world, FixtureSource source, WorldHeight height, string dir)
    {
        using var refDoc = JsonDocument.Parse(File.ReadAllBytes(Path.Combine(dir, "scatter_reference.json")));
        var root = refDoc.RootElement;
        int cases = CheckCases(root);
        CheckPure(root);
        string fixture = await CheckFixture(root.GetProperty("fixture"), world, source, height);
        return $"cases={cases} {fixture}";
    }

    // ---- 1. reference vectors -------------------------------------------------------------------

    private static List<P2> Ring(JsonElement e) => e.EnumerateArray().Select(p => new P2(p[0].GetDouble(), p[1].GetDouble())).ToList();

    private static double? Opt(JsonElement o, string name)
        => o.TryGetProperty(name, out var v) && v.ValueKind == JsonValueKind.Number ? v.GetDouble() : null;

    private static string? OptStr(JsonElement o, string name)
        => o.TryGetProperty(name, out var v) && v.ValueKind == JsonValueKind.String ? v.GetString() : null;

    private static void ComparePoints(string what, IReadOnlyList<ScatterInstance> got, JsonElement want)
    {
        int n = want.GetArrayLength();
        Expect($"{what} count", got.Count == n, $"got {got.Count}, expected {n}");
        int i = 0;
        foreach (var w in want.EnumerateArray())
        {
            var g = got[i];
            double wx = w[0].GetDouble(), wz = w[1].GetDouble(), wy = w[2].GetDouble();
            int? wv = w[3].ValueKind == JsonValueKind.Null ? null : w[3].GetInt32();
            if (Math.Abs(g.X - wx) > Tol || Math.Abs(g.Z - wz) > Tol || Math.Abs(g.Yaw - wy) > Tol || g.Variant != wv)
                throw new InvalidOperationException(
                    $"{what} instance {i}: got ({g.X}, {g.Z}, {g.Yaw}, {g.Variant?.ToString() ?? "-"}), "
                    + $"expected ({wx}, {wz}, {wy}, {wv?.ToString() ?? "-"})");
            i++;
        }
    }

    private static int CheckCases(JsonElement root)
    {
        var byName = new Dictionary<string, List<ScatterInstance>>();
        int n = 0;
        foreach (var c in root.GetProperty("cases").EnumerateArray())
        {
            string name = c.GetProperty("name").GetString()!;
            List<ScatterInstance> got;
            if (c.GetProperty("kind").GetString() == "instances")
            {
                var ring = Ring(c.GetProperty("ring"));
                double area = ScatterMath.PolygonArea(ring);
                Expect($"{name} areaM2", Math.Abs(area - c.GetProperty("areaM2").GetDouble()) < 1e-9, $"{area}");
                var fps = new List<IReadOnlyList<P2>>();
                if (c.TryGetProperty("footprints", out var f))
                    foreach (var fp in f.EnumerateArray()) fps.Add(Ring(fp));
                if (c.TryGetProperty("prop_boxes", out var pb))
                    foreach (var b in pb.EnumerateArray())
                        fps.Add(ScatterMath.PropBoxFootprint(b.GetProperty("x").GetDouble(), b.GetProperty("z").GetDouble(),
                                                             b.GetProperty("yaw_deg").GetDouble(), b.GetProperty("half_w").GetDouble(),
                                                             b.GetProperty("half_d").GetDouble())!);
                var occ = new List<IReadOnlyList<P2>>();
                if (c.TryGetProperty("occluders", out var o))
                    foreach (var r in o.EnumerateArray()) occ.Add(Ring(r));
                int? maxPoints = Opt(c, "maxPoints") is double mp ? (int)mp : null;
                double density = c.GetProperty("density").GetDouble();
                Expect($"{name} wanted", ScatterMath.WantedCount(area, density, maxPoints) == c.GetProperty("wanted").GetInt32(),
                       $"{ScatterMath.WantedCount(area, density, maxPoints)}");
                got = ScatterMath.Instances(new ScatterMath.SampleOptions
                {
                    Ring = ring, AreaM2 = area, DensityPer100m2 = density, Seed = c.GetProperty("seed").GetString()!,
                    Footprints = fps, ClearM = Opt(c, "clearM"), Occluders = occ, MinSpacingM = Opt(c, "minSpacingM"),
                    MaxPoints = maxPoints,
                });
            }
            else
            {
                double? epoch = ScatterMath.ReshuffleEpoch(c.GetProperty("epoch_total_s").GetDouble(), Opt(c, "reshuffle_min"));
                string seed = ScatterMath.CellSeed(c.GetProperty("area_id").GetString()!, c.GetProperty("index").GetInt32(),
                                                   c.GetProperty("cx").GetInt32(), c.GetProperty("cz").GetInt32(), epoch);
                Expect($"{name} seed", seed == c.GetProperty("seed").GetString(), seed);
                var grids = new Dictionary<(int, int), OccupancyGrid>();
                var occ = new CellOccupancy(grids);
                foreach (var pf in c.GetProperty("prefill").EnumerateArray())
                    occ.GridOf(1, 0).Add(pf[0].GetDouble(), pf[1].GetDouble(), pf[2].GetDouble(), pf[3].GetString());
                got = ScatterMath.CellInstances(new ScatterMath.CellOptions
                {
                    Ring = Ring(c.GetProperty("ring")), Cx = c.GetProperty("cx").GetInt32(), Cz = c.GetProperty("cz").GetInt32(),
                    DensityPer100m2 = c.GetProperty("density").GetDouble(), Seed = seed,
                    MinSpacingM = Opt(c, "minSpacingM"), VariantCount = Opt(c, "variantCount"), Variant = Opt(c, "variant"),
                    YawMode = OptStr(c, "yawMode"), YawDeg = Opt(c, "yawDeg"),
                    Occupied = occ.GridOf(1, 0), OccupyR = Opt(c, "occupyR"), OccupyTag = OptStr(c, "occupyTag"),
                });
            }
            ComparePoints($"case {name}", got, c.GetProperty("points"));
            if (OptStr(c, "prefix_of") is { } full)
            {
                var whole = byName[full];
                Expect($"{name} is a prefix of {full}", got.Count <= whole.Count && got.Select((p, i) => p == whole[i]).All(b => b),
                       "differs from the fuller run");
            }
            byName[name] = got;
            n++;
        }
        Expect("cases ≥ 6", n >= 6, $"{n}");
        return n;
    }

    private static void CheckPure(JsonElement root)
    {
        foreach (var h in root.GetProperty("hashes").EnumerateArray())
        {
            double got = ScatterLod.InstanceHash(h[0].GetInt32());
            Expect($"instanceHash({h[0].GetInt32()})", got == h[1].GetDouble(), $"got {got}, expected {h[1].GetDouble()}");
        }
        foreach (var s in root.GetProperty("shades").EnumerateArray())
        {
            double got = UndergrowthMath.Shade(s[0].GetDouble(), s[1].GetDouble());
            Expect($"undergrowthShade({s[0]}, {s[1]})", got == s[2].GetDouble(), $"got {got}, expected {s[2].GetDouble()}");
        }
        foreach (var s in root.GetProperty("seeds").EnumerateArray())
        {
            uint got = ScatterMath.SeedHash(s[0].GetString()!);
            Expect($"seedHash({s[0]})", got == s[1].GetUInt32(), $"got {got}, expected {s[1].GetUInt32()}");
        }
        var tex = root.GetProperty("texture");
        var px = UndergrowthMath.TexturePixels(tex.GetProperty("size").GetInt32());
        foreach (var smp in tex.GetProperty("samples").EnumerateArray())
        {
            int r = smp[0].GetInt32(), c = smp[1].GetInt32(), o = (r * UndergrowthMath.TexSize + c) * 4;
            var want = smp[2].EnumerateArray().Select(v => v.GetInt32()).ToArray();
            Expect($"texture pixel ({r}, {c})", want.SequenceEqual(px.Skip(o).Take(4).Select(b => (int)b)),
                   $"got {string.Join(",", px.Skip(o).Take(4))}, expected {string.Join(",", want)}");
        }
        string sha = Convert.ToHexString(SHA256.HashData(px)).ToLowerInvariant();
        Expect("texture bytes (sha256)", px.Length == tex.GetProperty("bytes").GetInt32() && sha == tex.GetProperty("sha256").GetString(),
               $"got {sha}, expected {tex.GetProperty("sha256").GetString()}");
    }

    // ---- 2. the fixture world through the runtime layers ----------------------------------------

    private static async Task<string> CheckFixture(JsonElement fx, Node3D world, FixtureSource source, WorldHeight height)
    {
        var anchor = fx.GetProperty("anchor");
        double ax = anchor.GetProperty("x").GetDouble(), az = anchor.GetProperty("z").GetDouble();
        var cam = fx.GetProperty("camera");
        var cp = cam.GetProperty("pos");
        var cf = cam.GetProperty("fwd");
        double vfov = cam.GetProperty("vfov_deg").GetDouble(), aspect = cam.GetProperty("aspect").GetDouble();

        using var mapDoc = await source.GetWorldMapAsync();
        var anchorPos = new Vector3((float)ax, (float)height.GroundAt(ax, az), (float)az);
        var layer = await ScatterLayer.CreateAsync(source, height, mapDoc.RootElement.Clone(), () => anchorPos,
                                                   line => GD.Print("[check] " + line));
        world.AddChild(layer);
        var field = layer.Field;
        var ug = layer.Undergrowth;

        // Window cells and footprints.
        var wantCells = fx.GetProperty("cells").EnumerateArray().Select(c => (c[0].GetInt32(), c[1].GetInt32())).ToList();
        Expect("window cells", field.Cells.SequenceEqual(wantCells), string.Join(";", field.Cells));
        Eq("window cells (hand)", field.Cells.Count, ExpWindowCells);
        using var terrainDoc = await source.GetTerrainAsync();
        var terrain = TerrainPayload.Parse(terrainDoc.RootElement);
        var fps = TerrainPayload.LocationFootprints(mapDoc.RootElement).Concat(terrain.PropFootprints()).ToList();
        var wantFps = fx.GetProperty("footprints").EnumerateArray().Select(Ring).ToList();
        Expect("footprints", fps.Count == wantFps.Count
                             && fps.Zip(wantFps).All(p => p.First.Length == p.Second.Count
                                 && p.First.Zip(p.Second).All(q => Math.Abs(q.First.X - q.Second.X) < 1e-9
                                                                   && Math.Abs(q.First.Z - q.Second.Z) < 1e-9)),
               $"{fps.Count} vs {wantFps.Count}");
        Eq("wanted trees per cell", ScatterMath.WantedCount(4096, 1.0, ScatterMath.MaxPerCell), ExpTreesPerCell);
        Eq("wanted tufts per cell", ScatterMath.WantedCount(4096, 1.5, ScatterMath.MaxPerCell), ExpTuftsPerCell);
        Eq("wanted undergrowth per cell", ScatterLod.UgCellCount(0.02), ExpUndergrowthPerCell);
        Expect("no along/edge/center rows in the fixture", field.SkippedRows == 0, $"{field.SkippedRows}");

        // Before any mesh: the estimated clearance (h · 0.5), tufts on the cheap buffer.
        CompareRows("estimate", field, fx.GetProperty("estimate"));
        Expect("estimate: nothing measured yet", ScatterField.MeasuredSpread(FullUrl) is null, "spread already known");
        Expect("estimate: cone stand-ins", field.Props.All(p => p.LowTris == ExpConeTris && p.High is null), "a mesh is mounted");

        // The LOD pass at the fixture camera starts the downloads; wait for both tiers + the re-sample.
        field.Tick(cp[0].GetDouble(), cp[1].GetDouble(), cp[2].GetDouble(), cf[0].GetDouble(), cf[2].GetDouble(), vfov, aspect);
        int rebuildsBefore = field.Rebuilds;
        ulong start = Time.GetTicksMsec();
        do await world.ToSignal(world.GetTree(), SceneTree.SignalName.ProcessFrame);
        while (field.Busy && Time.GetTicksMsec() - start < 60000);
        Expect("scatter loads settle", !field.Busy, "still busy after 60 s");
        Eq("prop load failures", field.LoadFailures, 0);
        // One re-sample per measured URL that lands after the previous one fired — at least one.
        Expect("clearance re-sample ran", field.Rebuilds >= rebuildsBefore + 1, $"rebuilds {field.Rebuilds} (before {rebuildsBefore})");
        var spreads = fx.GetProperty("measured_spread");
        foreach (var url in new[] { FullUrl, LowUrl })
        {
            double got = ScatterField.MeasuredSpread(url) ?? double.NaN;
            double want = spreads.GetProperty(url).GetDouble();
            Expect($"spread {url}", Math.Abs(got - want) < 1e-5, $"got {got}, expected {want}");
        }
        CompareRows("measured", field, fx.GetProperty("measured"));
        int lowN = 0, highN = 0;
        CompareBins(field, fx.GetProperty("measured"), ref lowN, ref highN);
        var tree = field.Props.Single(p => p.Row == 0);
        var tuft = field.Props.Single(p => p.Row == 1);
        Eq("tree full-tier triangles", tree.HighTris, ExpFullTris);
        Eq("tree low-tier triangles", tree.LowTris, ExpLowTris);
        Eq("built-in tuft triangles (cone)", tuft.LowTris, ExpConeTris);
        Expect("tree tiers mounted", tree.ShownLow == LowUrl && tree.ShownHigh == FullUrl, $"{tree.ShownLow} / {tree.ShownHigh}");
        Expect("tree multimesh counts", tree.Low.VisibleInstanceCount == tree.LowN && tree.High!.VisibleInstanceCount == tree.HighN,
               $"{tree.Low.VisibleInstanceCount}/{tree.High?.VisibleInstanceCount}");
        var sc = field.Counts();
        long expTris = (long)tree.LowN * ExpLowTris + (long)tree.HighN * ExpFullTris + (long)tuft.LowN * ExpConeTris;
        Expect("scatter counts", sc.Instances == lowN + highN && sc.Triangles == expTris, $"{sc} vs {lowN + highN} / {expTris}");

        // Undergrowth: cells, instances per (cell, area), bins at the camera.
        var wantUg = fx.GetProperty("undergrowth");
        var cellsGot = UndergrowthMath.WantedCells(ax, az);
        var cellsWant = wantUg.EnumerateArray().Select(c => c.GetProperty("key").GetString()!).ToList();
        Expect("undergrowth cells", cellsGot.Select(c => UndergrowthMath.CellKey(c.Cx, c.Cz)).SequenceEqual(cellsWant),
               string.Join(";", cellsGot));
        Eq("undergrowth cells (hand)", cellsGot.Count, ExpUndergrowthCells);
        Eq("undergrowth cells built", ug.CellKeys.Count, ExpUndergrowthCells);
        ug.Tick(cp[0].GetDouble(), cp[1].GetDouble(), cp[2].GetDouble());
        int ugLayers = 0, ugInst = 0, ugVisible = 0;
        foreach (var c in wantUg.EnumerateArray())
        {
            var key = c.GetProperty("key").GetString()!;
            var parts = key.Split(',');
            var cell = (int.Parse(parts[0]), int.Parse(parts[1]));
            var got = ug.Layers.Where(l => l.Cell == cell).ToList();
            var want = c.GetProperty("layers");
            Eq($"undergrowth layers in {key}", got.Count, want.GetArrayLength());
            int i = 0;
            foreach (var w in want.EnumerateArray())
            {
                var l = got[i++];
                Expect($"undergrowth {key} area", l.AreaId == w.GetProperty("area").GetString(), l.AreaId);
                ComparePoints($"undergrowth {key}", l.Points, w.GetProperty("points"));
                Eq($"undergrowth {key} visible at the camera", l.N, w.GetProperty("visible").GetInt32());
                Eq($"undergrowth {key} multimesh count", l.Mm.VisibleInstanceCount, l.N);
                Expect($"undergrowth {key} shade", UndergrowthMath.Shade(l.Points[0].X, l.Points[0].Z) == w.GetProperty("shade0").GetDouble(), "differs");
                Expect($"undergrowth {key} height", Math.Abs(ScatterLod.UgHeight(l.Points[0].Yaw) - w.GetProperty("height0").GetDouble()) < 1e-12, "differs");
                Expect($"undergrowth {key} per-cell ceiling", l.BaseCount <= ExpUndergrowthPerCell, $"{l.BaseCount}");
                ugLayers++;
                ugInst += l.BaseCount;
                ugVisible += l.N;
            }
        }
        var uc = ug.Counts();
        Expect("undergrowth counts", uc.Instances == ugVisible && uc.Triangles == (long)ugVisible * ExpTuftTris && uc.BaseInstances == ugInst,
               $"{uc}");

        // A camera 2 km away: every entry fails its sphere test, nothing is drawn (hand).
        field.Tick(2000, 50, 2000, 1, 0, vfov, aspect);
        ug.Tick(2000, 50, 2000);
        var far = field.Counts();
        var farU = ug.Counts();
        Expect("far camera: nothing drawn", far.Instances == 0 && farU.Instances == 0 && field.Props.All(p => p.Hidden)
                                           && !field.Props.Any(p => p.LowNode.Visible || (p.HighNode?.Visible ?? false)),
               $"{far} / {farU}");

        layer.QueueFree();
        return $"scatter_rows={field.Props.Count()} scatter_base={sc.BaseInstances} scatter_drawn={sc.Instances} "
               + $"(low {lowN}, full {highN}) scatter_tris={sc.Triangles} | undergrowth_cells={ug.CellKeys.Count} "
               + $"layers={ugLayers} base={ugInst} drawn={ugVisible} tris={uc.Triangles}";
    }

    private static void CompareRows(string phase, ScatterField field, JsonElement areas)
    {
        foreach (var a in areas.EnumerateArray())
            foreach (var r in a.GetProperty("rows").EnumerateArray())
            {
                int index = r.GetProperty("index").GetInt32();
                var props = field.Props.Where(p => p.Row == index).OrderBy(p => p.VariantPos).ToList();
                // One variant per row in the fixture: the prop's instance list IS the row's.
                var got = props.SelectMany(p => p.Points).ToList();
                ComparePoints($"{phase} row {index}", got, r.GetProperty("points"));
            }
    }

    private static void CompareBins(ScatterField field, JsonElement areas, ref int lowN, ref int highN)
    {
        foreach (var a in areas.EnumerateArray())
            foreach (var r in a.GetProperty("rows").EnumerateArray())
            {
                int index = r.GetProperty("index").GetInt32();
                foreach (var pr in r.GetProperty("props").EnumerateArray())
                {
                    var p = field.Props.Single(x => x.Row == index && x.VariantPos == pr.GetProperty("variant").GetInt32());
                    var bins = pr.GetProperty("bins");
                    Eq($"row {index} low buffer at the camera", p.LowN, bins.GetProperty("low").GetInt32());
                    Eq($"row {index} full buffer at the camera", p.HighN, bins.GetProperty("high").GetInt32());
                    lowN += p.LowN;
                    highN += p.HighN;
                }
            }
    }

    private static void Expect(string what, bool ok, string detail)
    {
        if (!ok) throw new InvalidOperationException($"{what}: {detail}");
    }

    private static void Eq(string what, long got, long want) => Expect(what, got == want, $"got {got}, expected {want}");
}
