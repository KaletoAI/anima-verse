using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Threading.Tasks;
using AnimaNative.Ground;
using AnimaNative.Terrain;
using AnimaNative.Water;
using AnimaNative.World;
using Godot;

namespace AnimaNative.Check;

/// <summary>
/// <c>--check terrain</c> (part of every <c>--check</c>, Task 23): the CDLOD terrain as the build makes it, against
/// numbers derived BY HAND in native/fixtures/README.md "CDLOD terrain" — the selection itself is
/// <see cref="TerrainLod"/>, vector-checked in <c>dotnet test</c> against shared/test-vectors/terrain_lod.json; this
/// checks what the client does with it:
///
///   T0 the shaders: ground, ground-water and terrain-plain compile with 33 / 42 / 15 uniforms; the shader text prints
///      the constants the twin reads (PATCH_N, MORPH_START, LOD_CAP_NONE, the outline band, the dry sd);
///   T1 the main fixture's field: near pyramid 641² at 2 m (6 levels, rows 0/641/962/1123/1204/1245, 1266 high), far
///      pyramid 3² at 256 m (2 levels), near rectangle, frame = world_bounds ± 60 m, range (0, 16), zero level errors;
///   T2 a far camera: the 4 roots at level 5; T3 the bench's start camera: 41 pieces in the hand order (16 leaves, 13
///      parent quadrants, 12 whole nodes), 64 000 triangles, one draw; the instance buffer carries exactly that list;
///   T4 the GPU-free twin (<see cref="TerrainShaderTwin"/>) on the uniforms and textures READ BACK from the material
///      = <see cref="TerrainLod.LodVertex"/> for 11 vertices of every piece, and at λ = 0 = the tile-first height;
///   T5 the s3c world: the water cap {0,0: 4}, the far camera's 10 pieces (2 wet), the wet program's twin, and every
///      vertex any piece draws on the lattice points of README "Water (tile 0, 0)" inside the frame at the table's lifted
///      height and depth — whichever piece draws it (no seam); with --no-water the bed and no wet program;
///   T6 the pixel scale and the frame without bounds.
/// </summary>
public static class TerrainCheck
{
    private const double Tol = 1e-6;

    public static async Task<string> RunAsync(Node3D host, string fixtures)
    {
        var lines = new List<string> { Shaders() };
        lines.Add(await MainWorld(host, fixtures));
        lines.Add(await S3cWorld(host, fixtures, noWater: false));
        lines.Add(await S3cWorld(host, fixtures, noWater: true));
        lines.Add(Misc());
        return "terrain " + string.Join("; ", lines);
    }

    // ---- T0 ----
    private static string Shaders()
    {
        var plain = GroundShader.Plain();
        Expect("T0 terrain-plain compiles", ShaderSafety.Ok(plain, "terrain-plain"), "");
        int nDry = GroundShader.Get().GetShaderUniformList().Count, nWet = GroundShader.Get(true).GetShaderUniformList().Count;
        int nPlain = plain.GetShaderUniformList().Count;
        // + the exploration veil's 7 uniforms on every variant (Task 26).
        Expect("T0 uniforms ground 40 / ground-water 49 / terrain-plain 22", nDry == 40 && nWet == 49 && nPlain == 22,
               $"{nDry} / {nWet} / {nPlain}");
        foreach (var code in new[] { GroundShader.Code(), GroundShader.Code(true), GroundShader.PlainCode() })
        {
            Expect("T0 PATCH_N printed", code.Contains($"const float TL_PATCH_N = 32.0;") && TerrainLod.PatchN == 32, "");
            Expect("T0 MORPH_START printed", code.Contains("const float TL_MORPH_START = 0.5;") && TerrainLod.MorphStart == 0.5, "");
            Expect("T0 LOD_CAP_NONE printed", code.Contains("const float TL_CAP_NONE = 6.0;") && TerrainLod.LodCapNone == 6, "");
            Expect("T0 six levels", code.Contains("uniform float tl_range[6];") && code.Contains("for (int j = 5; j >= 1; j--)")
                                     && TerrainLod.MaxLodLevels == 6, "");
            Expect("T0 the eye and the node", code.Contains("tl_compute(INSTANCE_CUSTOM, VERTEX.xz, INV_VIEW_MATRIX[3].xyz, tl_wet)"), "");
        }
        var wet = GroundShader.Code(true);
        Expect("T0 outline band 0.5 m, dry sd −1e4", wet.Contains("clamp(sd / 0.5, 0.0, 1.0)") && WaterShade.SdBandM == 0.5
                                                   && wet.Contains("const float TL_SD_DRY = -10000.0;"), "");
        Expect("T0 the dry program lifts nothing", !GroundShader.Code().Contains("tl_lift") && !GroundShader.PlainCode().Contains("tl_lift"), "");
        return $"shaders 40/49/22";
    }

    // ---- T1–T4 ----
    private static async Task<string> MainWorld(Node3D host, string fixtures)
    {
        var source = new FixtureSource(fixtures);
        var world = new Node3D { Name = "TerrainWorld" };
        host.AddChild(world);
        var builder = new WorldBuilder(source, line => GD.Print("[check-terrain] " + line), strict: true);
        try
        {
            await builder.BuildAsync(world, "harbour");
            var t = builder.Terrain ?? throw new InvalidOperationException("T1 no terrain node");
            t.AutoUpdate = false;
            var f = t.Field;

            // T1 the field.
            var near = f.Near ?? throw new InvalidOperationException("T1 no near pyramid");
            Expect("T1 near pyramid 641² at 2 m, 6 levels", near.OriginX == -512 && near.OriginZ == -512 && near.Step == 2
                   && near.Levels.Select(l => (l.Cols, l.Row0)).SequenceEqual(new[] { (641, 0), (321, 641), (161, 962), (81, 1123), (41, 1204), (21, 1245) })
                   && near.TexW == 641 && near.TexH == 1266, string.Join(",", near.Levels));
            var far = f.Far ?? throw new InvalidOperationException("T1 no far pyramid");
            Expect("T1 far pyramid 3² at 256 m, 2 levels", far.Levels.Count == 2 && far.Levels[0].Cols == 3 && far.Levels[1].Cols == 2
                   && far.Levels[1].Step == 512 && far.TexH == 5, string.Join(",", far.Levels));
            Expect("T1 far = the overview, round-to-nearest", far.Data.Take(9).SequenceEqual(new float[] { 0, 0, 0, 0, 4, 8, 0, 8, 16 })
                   && far.Data.Skip(9).SequenceEqual(new float[] { 0, 0, 0, 0, 16, 0 }), string.Join(",", far.Data));
            Expect("T1 near rect", f.NearRect!.SequenceEqual(new double[] { -512, -512, 768, 768 }), string.Join(",", f.NearRect!));
            Expect("T1 frame = world_bounds ± 60", f.Extent.SequenceEqual(new double[] { -164, -263, 360, 194 }), string.Join(",", f.Extent));
            Expect("T1 range (0, 16)", f.GlobalRange == new NodeStatSpan(0, 16), $"{f.GlobalRange}");
            Expect("T1 level errors 0 (tile 0,0 err all 0)", f.LevelErrorM.All(e => e == 0) && builder.Height!.Stats.ContainsKey("0,0"), "");
            Expect("T1 no water", f.Water is null && f.WaterTileKeys is null && f.CapGrid is null, "");
            Expect("T1 normal lattices = level 0", f.NormalLattices().Near is { Cols: 641, Rows: 641, Step: 2 }
                   && f.NormalLattices().Far is { Cols: 3, Rows: 3, Step: 256 }, "");

            // T2 a far camera: the four roots, whole, morph 1.
            var ps = TerrainField.PixelScale(1080, 45);
            var fr = t.UpdateFor(98, 10000, -34.5, ps);
            Expect("T2 far camera: 4 roots at level 5", fr.Nodes == 4 && fr.Wet.Count == 0
                   && fr.Dry.Select(n => (n.X, n.Z, n.Size, n.Level, n.Cells)).SequenceEqual(new[]
                       { (-2048.0, -2048.0, 2048.0, 5, 32), (0.0, -2048.0, 2048.0, 5, 32), (-2048.0, 0.0, 2048.0, 5, 32), (0.0, 0.0, 2048.0, 5, 32) })
                   && fr.Dry.All(n => n.Morph == 1) && fr.Triangles == 8192 && fr.Draws == 1,
                   string.Join(" ", fr.Dry));
            Expect("T2 the frame covered", f.Coverage(fr) == 1, $"{f.Coverage(fr)}");
            Expect("T2 rings 128…4096", fr.Ranges.SequenceEqual(new double[] { 128, 256, 512, 1024, 2048, 4096 }), string.Join(",", fr.Ranges));

            // T3 the bench start camera (anchor (64, 7.5, 128) + (0, 24, 40)).
            var eye = (X: 64.0, Y: 31.5, Z: 168.0);
            var frame = t.UpdateFor(eye.X, eye.Y, eye.Z, ps);
            var want = BenchStartPieces();
            var got = frame.Dry.Select(n => (n.X, n.Z, n.Size, n.Level, n.Cells)).ToList();
            Expect("T3 41 pieces in the hand order", got.SequenceEqual(want),
                   $"{got.Count}: {string.Join(" ", got.Take(45))}");
            Expect("T3 16 leaves, 13 quadrants, 12 whole", got.Count(p => p.Level == 0) == 16 && got.Count(p => p.Cells == 16) == 13
                   && got.Count(p => p.Level > 0 && p.Cells == 32) == 12, "");
            Expect("T3 the frame covered, no hole", f.Coverage(frame) == 1, $"{f.Coverage(frame)}");
            Expect("T3 64 000 triangles, one draw", frame.Triangles == 64000 && frame.Draws == 1 && frame.Wet.Count == 0, $"{frame.Triangles}");
            var mm = t.DryInstance.Multimesh;
            Expect("T3 instances visible = pieces", mm.VisibleInstanceCount == 41 && mm.InstanceCount >= 41
                   && t.WetInstance.Multimesh.VisibleInstanceCount == 0, $"{mm.VisibleInstanceCount}/{mm.InstanceCount}");
            var buf = mm.Buffer;
            int inBuf = 0;
            if (buf.Length >= 41 * TerrainLodNode.Stride)
            {
                for (int i = 0; i < 41; i++)
                {
                    int o = i * TerrainLodNode.Stride;
                    var p = want[i];
                    Expect($"T3 instance {i} custom = (x, z, size, level)", buf[o + 12] == p.Item1 && buf[o + 13] == p.Item2
                           && buf[o + 14] == p.Item3 && buf[o + 15] == p.Item4 && buf[o] == 1 && buf[o + 5] == 1 && buf[o + 10] == 1
                           && buf[o + 3] == 0 && buf[o + 7] == 0 && buf[o + 11] == 0, $"{buf[o + 12]},{buf[o + 13]},{buf[o + 14]},{buf[o + 15]}");
                    inBuf++;
                }
            }
            Expect("T3 the terrain casts no shadow", t.DryInstance.CastShadow == GeometryInstance3D.ShadowCastingSetting.Off
                   && t.WetInstance.CastShadow == GeometryInstance3D.ShadowCastingSetting.Off, "");

            // T4 the twin on the read-back uniforms vs the CPU vertex; λ = 0 → the tile-first height.
            var (dryMat, _) = t.Materials;
            Expect("T4 the dry instance wears the ground material", t.DryInstance.MaterialOverride == builder.Ground!.Material
                   && dryMat == builder.Ground.Material, "");
            var state = ReadBack(dryMat, water: false);
            int twins = Twins(f, frame, frame.Dry, state, eye, water: false);
            int flat = 0;
            foreach (var n in frame.Dry.Where(n => n.Level == 0))
            foreach (var (i, j) in TerrainShaderTwin.SampleVertices)
            {
                var v = TerrainShaderTwin.Compute(state, Node(n), i / 32.0, j / 32.0, eye, false);
                double dx = v.X - eye.X, dy = v.Y - eye.Y, dz = v.Z - eye.Z;
                if (Math.Sqrt(dx * dx + dy * dy + dz * dz) >= 63) continue;   // λ = 0 below s0 = 64 m (the morph reads the owner)
                Near($"T4 λ=0 vertex ({v.X}, {v.Z}) = heightAt", v.Y, builder.Height!.GroundAt(v.X, v.Z), 1e-4);
                flat++;
            }
            Expect("T4 some λ = 0 vertices", flat >= 20, $"{flat}");
            return $"main[pieces 4/41, triangles 8192/64000, instances {inBuf}, twin {twins} vertices, λ0 {flat}]";
        }
        finally
        {
            builder.Models?.FreeAll();
            world.QueueFree();
        }
    }

    /// <summary>README "CDLOD terrain": the 41 pieces of the start camera, roots (−1,−1), (0,−1), (−1,0), (0,0), quadrants in q order.</summary>
    private static List<(double, double, double, int, int)> BenchStartPieces() => new()
    {
        (-256, -512, 256, 2, 32), (-256, -256, 128, 2, 16), (-128, -256, 128, 2, 16), (-256, -128, 128, 1, 32), (-128, -128, 128, 1, 32),
        (0, -512, 256, 2, 32), (256, -512, 256, 2, 32), (0, -256, 128, 2, 16), (128, -256, 128, 2, 16), (0, -128, 128, 1, 32),
        (128, -128, 128, 1, 32), (256, -256, 128, 2, 16), (256, -128, 128, 1, 32),
        (-256, 0, 128, 1, 32), (-128, 0, 64, 1, 16), (-64, 0, 64, 0, 32), (-128, 64, 64, 1, 16), (-64, 64, 64, 0, 32),
        (-256, 128, 128, 1, 32), (-128, 128, 64, 1, 16), (-64, 128, 64, 0, 32), (-128, 192, 64, 1, 16), (-64, 192, 64, 0, 32),
        (0, 0, 64, 0, 32), (64, 0, 64, 0, 32), (0, 64, 64, 0, 32), (64, 64, 64, 0, 32),
        (128, 0, 64, 0, 32), (192, 0, 64, 1, 16), (128, 64, 64, 0, 32), (192, 64, 64, 1, 16),
        (0, 128, 64, 0, 32), (64, 128, 64, 0, 32), (0, 192, 64, 0, 32), (64, 192, 64, 0, 32),
        (128, 128, 64, 0, 32), (192, 128, 64, 1, 16), (128, 192, 64, 0, 32), (192, 192, 64, 1, 16),
        (256, 0, 128, 1, 32), (256, 128, 128, 1, 32),
    };

    // ---- T5 ----
    /// <summary>The lattice points of README "Water (tile 0, 0)" inside the s3c frame (z ≥ 36: the z = 0 row is clamped away).</summary>
    private static readonly (double X, double Z, double Y, double Wet)[] TablePoints =
    {
        (0, 64, 6, 5), (64, 64, 3, 0), (0, 128, 2.625, 0.625),
    };

    private static async Task<string> S3cWorld(Node3D host, string fixtures, bool noWater)
    {
        var dir = Path.Combine(fixtures, "s3c");
        var source = new FixtureSource(dir, fixtures);
        var world = new Node3D { Name = noWater ? "TerrainS3cDry" : "TerrainS3c" };
        host.AddChild(world);
        var builder = new WorldBuilder(source, _ => { }, strict: true) { NoWater = noWater };
        try
        {
            await builder.BuildAsync(world, "Glass");
            var t = builder.Terrain ?? throw new InvalidOperationException("T5 no terrain node");
            t.AutoUpdate = false;
            var f = t.Field;
            var ps = TerrainField.PixelScale(1080, 45);
            Expect("T5 s3c frame = world_bounds ± 60", f.Extent.SequenceEqual(new double[] { -104, 36, 2064, 2064 }), string.Join(",", f.Extent));
            var farEye = (X: 1000.0, Y: 10000.0, Z: 1000.0);
            var close = (X: 32.0, Y: 10.0, Z: 32.0);
            if (noWater)
            {
                Expect("T5 --no-water: no water, no cap, no wet program", f.Water is null && f.CapGrid is null && f.WaterTileKeys is null
                       && t.WetInstance.MaterialOverride == t.DryInstance.MaterialOverride, "");
                var fr0 = t.UpdateFor(farEye.X, farEye.Y, farEye.Z, ps);
                Expect("T5 --no-water far camera: the 6 roots, all dry", fr0.Nodes == 6 && fr0.Wet.Count == 0 && fr0.Dry.All(n => n.Level == 5), $"{fr0.Nodes}");
                var frame0 = t.UpdateFor(close.X, close.Y, close.Z, ps);
                var st0 = ReadBack(t.Materials.Dry, water: false);
                var hits0 = TableHits(st0, frame0.Dry, close, false).Where(h => h.X == 0 && h.Z == 64).ToList();
                Expect("T5 --no-water: (0, 64) drawn on its bed, 1", hits0.Count > 0 && hits0.All(h => Math.Abs(h.Y - 1) < Tol), $"{hits0.Count}");
                return $"s3c-dry[roots 6, bed (0,64) 1 by {hits0.Count} pieces]";
            }
            Expect("T5 water: one wet tile, cap {0,0: 4}", f.WaterTileKeys!.SetEquals(new[] { "0,0" }) && f.CapGrid is { } cg
                   && cg.X0 == -256 && cg.Z0 == -256 && cg.Step == 256 && cg.Cols == 4 && cg.Rows == 4 && cg.Min == 4
                   && cg.Caps.SequenceEqual(new float[] { 6, 6, 6, 6, 6, 4, 4, 6, 6, 4, 4, 6, 6, 6, 6, 6 }),
                   f.CapGrid is null ? "none" : string.Join(",", f.CapGrid.Caps));
            Expect("T5 the wet instance wears the water variant", t.WetInstance.MaterialOverride == builder.Ground!.WaterMaterial
                   && t.WetInstance.HasMeta("wet"), "");

            var fr = t.UpdateFor(farEye.X, farEye.Y, farEye.Z, ps);
            var wantWet = new[] { (-1024.0, 0.0, 1024.0, 4, 32), (0.0, 0.0, 1024.0, 4, 32) };
            var wantDry = new[]
            {
                (1024.0, 0.0, 1024.0, 5, 16), (0.0, 1024.0, 1024.0, 5, 16), (1024.0, 1024.0, 1024.0, 5, 16), (2048.0, 0.0, 2048.0, 5, 32),
                (-1024.0, 1024.0, 1024.0, 5, 16), (-2048.0, 2048.0, 2048.0, 5, 32), (0.0, 2048.0, 2048.0, 5, 32), (2048.0, 2048.0, 2048.0, 5, 32),
            };
            Expect("T5 far camera: the cap splits the water's roots — 2 wet level-4 nodes", fr.Wet.Select(Key).SequenceEqual(wantWet)
                   && fr.Wet.All(n => n.Morph == 0), string.Join(" ", fr.Wet));
            Expect("T5 far camera: 8 dry pieces", fr.Dry.Select(Key).OrderBy(k => k).SequenceEqual(wantDry.OrderBy(k => k))
                   && fr.Dry.All(n => n.Morph == 1), string.Join(" ", fr.Dry));
            Expect("T5 far camera: the frame covered", f.Coverage(fr) == 1, $"{f.Coverage(fr)}");
            Expect("T5 far camera: 14 336 triangles, two draws", fr.Triangles == 14336 && fr.Draws == 2
                   && t.WetInstance.Multimesh.VisibleInstanceCount == 2 && t.DryInstance.Multimesh.VisibleInstanceCount == 8, $"{fr.Triangles}");
            var wetState = ReadBack(t.Materials.Wet, water: true);
            var dryState = ReadBack(t.Materials.Dry, water: false);
            int twins = Twins(f, fr, fr.Wet, wetState, farEye, water: true) + Twins(f, fr, fr.Dry, dryState, farEye, water: false);

            // Close over the water: every piece that draws a table point draws it at the table's height and depth.
            var frame = t.UpdateFor(close.X, close.Y, close.Z, ps);
            wetState = ReadBack(t.Materials.Wet, water: true);
            dryState = ReadBack(t.Materials.Dry, water: false);
            twins += Twins(f, frame, frame.Wet, wetState, close, water: true) + Twins(f, frame, frame.Dry, dryState, close, water: false);
            var hits = TableHits(wetState, frame.Wet, close, true);
            int dryHits = TableHits(dryState, frame.Dry, close, false).Count;
            Expect("T5 no dry piece draws a table point (closed rectangle)", dryHits == 0, $"{dryHits}");
            foreach (var (x, z, y, wet) in TablePoints)
            {
                var at = hits.Where(h => h.X == x && h.Z == z).ToList();
                Expect($"T5 table point ({x}, {z}) drawn", at.Count > 0, "no piece draws it");
                foreach (var h in at)
                {
                    Near($"T5 ({x}, {z}) lifted", h.Y, y, 1e-4);
                    Near($"T5 ({x}, {z}) depth", h.Wet, wet, 1e-4);
                }
            }
            return $"s3c[cap 4, far 10 pieces (2 wet) 14336 triangles, close {frame.Nodes} ({frame.Wet.Count} wet), twin {twins}, table hits {hits.Count}]";
        }
        finally
        {
            builder.Models?.FreeAll();
            world.QueueFree();
        }
    }

    private static (double, double, double, int, int) Key(LodNode n) => (n.X, n.Z, n.Size, n.Level, n.Cells);

    /// <summary>Every patch vertex of these pieces whose drawn point is one of the table's lattice points.</summary>
    private static List<(double X, double Z, double Y, double Wet)> TableHits(TerrainShaderState s, List<LodNode> pieces,
                                                                             (double X, double Y, double Z) eye, bool water)
    {
        var hits = new List<(double, double, double, double)>();
        foreach (var n in pieces)
            for (int j = 0; j <= TerrainLod.PatchN; j++)
            for (int i = 0; i <= TerrainLod.PatchN; i++)
            {
                var v = TerrainShaderTwin.Compute(s, Node(n), i / 32.0, j / 32.0, eye, water);
                if (TablePoints.Any(p => p.X == v.X && p.Z == v.Z)) hits.Add((v.X, v.Z, v.Y, v.Wet));
            }
        return hits;
    }

    // ---- T6 ----
    private static string Misc()
    {
        // 1080 / (2·tan 22.5°) = 1080 / 0.828427125 = 1303.6753.
        Near("T6 pixel scale at 1080 px, 45°", TerrainField.PixelScale(1080, 45), 1303.6753236814712, 1e-9);
        Expect("T6 no viewport, no scale", TerrainField.PixelScale(0, 45) == 0 && TerrainField.PixelScale(1080, 0) == 0, "");
        Expect("T6 frame without bounds = the 200 m square", TerrainField.ExtentOf(null).SequenceEqual(new double[] { -100, -100, 100, 100 }), "");
        Expect("T6 a degenerate frame keeps 1 m", TerrainField.ExtentOf(new Overview.BoundsXZ(5, 5, 7, 7)).SequenceEqual(new double[] { -55, -53, 65, 67 }), "");
        return "misc[pixel scale 1303.7]";
    }

    /// <summary>The twin on <paramref name="state"/> = <see cref="TerrainLod.LodVertex"/> for the sample vertices of every piece.</summary>
    private static int Twins(TerrainField f, TerrainFrame frame, List<LodNode> pieces, TerrainShaderState state,
                             (double X, double Y, double Z) eye, bool water)
    {
        int n = 0;
        foreach (var node in pieces)
        foreach (var (i, j) in TerrainShaderTwin.SampleVertices)
        {
            var twin = TerrainShaderTwin.Compute(state, Node(node), i / 32.0, j / 32.0, eye, water);
            var cpu = TerrainLod.LodVertex(node, i, j, f.Near, f.NearRect, f.Far, f.Extent, new LodCamera(eye.X, eye.Y, eye.Z),
                                           frame.Ranges, water ? f.Water : null, (x, z) => f.CapAt(x, z, frame.CapRelax),
                                           water ? f.Sd : null);
            Expect($"T4 twin = lodVertex at {node} ({i}, {j})", Math.Abs(twin.X - cpu.X) < 1e-9 && Math.Abs(twin.Z - cpu.Z) < 1e-9
                   && Math.Abs(twin.Y - cpu.Y) < Tol, $"twin ({twin.X}, {twin.Y}, {twin.Z}) vs cpu ({cpu.X}, {cpu.Y}, {cpu.Z})");
            n++;
        }
        return n;
    }

    private static double[] Node(LodNode n) => new[] { n.X, n.Z, n.Size, n.Level };

    /// <summary>The program's uniforms as the material holds them — textures through their images.</summary>
    private static TerrainShaderState ReadBack(ShaderMaterial m, bool water)
    {
        double[] V(string name)
        {
            var v = m.GetShaderParameter(name).AsVector4();
            return new double[] { v.X, v.Y, v.Z, v.W };
        }
        double[][] Rows(string name)
        {
            var rows = m.GetShaderParameter(name).AsVector4Array();
            Expect($"{name} has 6 rows", rows.Length == TerrainLod.MaxLodLevels, $"{rows.Length}");
            return rows.Select(r => new double[] { r.X, r.Y, r.Z, r.W }).ToArray();
        }
        TwinTexture? Tex(string name)
        {
            var t = m.GetShaderParameter(name).As<Texture2D>();
            if (t is null) return null;
            var img = t.GetImage() ?? throw new InvalidOperationException($"{name}: no image to read back");
            Expect($"{name} is R32F", img.GetFormat() == Image.Format.Rf, $"{img.GetFormat()}");
            var bytes = img.GetData();
            var data = new float[bytes.Length / 4];
            Buffer.BlockCopy(bytes, 0, data, 0, bytes.Length);
            return new TwinTexture(data, img.GetWidth(), img.GetHeight());
        }
        var range = m.GetShaderParameter("tl_range").AsFloat32Array().Select(x => (double)x).ToArray();
        Expect("tl_range has 6 rings", range.Length == TerrainLod.MaxLodLevels, $"{range.Length}");
        var fit = m.GetShaderParameter("tl_cap_fit");
        var capFit = fit.VariantType == Variant.Type.Nil ? new double[4] : V("tl_cap_fit");
        return new TerrainShaderState(
            Tex("tl_near"), V("tl_near_geom"), Rows("tl_near_levels"), V("tl_near_rect"),
            Tex("tl_far"), V("tl_far_geom"), Rows("tl_far_levels"),
            V("tl_extent"), range, (float)m.GetShaderParameter("tl_base_step"), (float)m.GetShaderParameter("tl_normal_span"),
            Tex("tl_cap"), V("tl_cap_geom"), capFit,
            water ? Tex("tl_water") : null, water ? Tex("tl_water_sd") : null,
            water ? V("tl_water_geom") : new double[] { 0, 0, 1, 0 },
            water ? Rows("tl_water_levels") : Enumerable.Range(0, 6).Select(_ => new double[4]).ToArray());
    }

    private static void Near(string what, double got, double want, double eps)
        => Expect(what, Math.Abs(got - want) <= eps, $"got {got:R}, expected {want:R}");

    private static void Expect(string what, bool ok, string detail)
    {
        if (!ok) throw new InvalidOperationException($"terrain {what}: {detail}");
    }
}
