using System;
using System.Linq;
using System.Threading.Tasks;
using AnimaNative.Scatter;
using AnimaNative.World;
using Godot;

namespace AnimaNative.Check;

/// <summary>Task 38 (E4-T3): exercise the runtime binning against a supplied bake, because the dummy renderer cannot
/// render one. A premature mesh sphere return, horizontal distance, full billboarding or a cached refusal on missing
/// renderer must fail here. The regular scatter fixture below still exercises the real baker's no-renderer path.</summary>
public static class ImpostorCheck
{
    private sealed class Frames : IImpostorSource, IDisposable
    {
        public int Refs;
        public readonly ImageTexture Texture;
        public Frames()
        {
            using var image = Image.CreateEmpty(1, 1, false, Image.Format.Rgba8);
            image.Fill(Colors.White);
            Texture = ImageTexture.CreateFromImage(image);
        }
        public ImpostorBake? Acquire(string url) { Refs++; return new(Texture, ScatterLod.ImpostorFrame(4, 1)!.Value); }
        public void Release(string url) => Refs--;
        public void Dispose() => Texture.Dispose();
    }

    public static async Task RunAsync(Node3D world, FixtureSource source, WorldHeight height)
    {
        void Need(string what, bool yes) { if (!yes) throw new InvalidOperationException("impostor: " + what); }
        var wideFrame = ScatterLod.ImpostorFrame(1, 10)!.Value;
        var bakeCamera = ImpostorBaker.CameraForBake(1, 10, 0.5, wideFrame);
        world.AddChild(bakeCamera);
        Need("wide template side meshes survive CPU camera culling", bakeCamera.IsPositionInFrustum(new Vector3(10, 0.5f, 0))
            && bakeCamera.IsPositionInFrustum(new Vector3(-10, 0.5f, 0)));
        bakeCamera.Free();
        using var frames = new Frames();
        var field = new ScatterField(source, height, _ => { }, frames);
        world.AddChild(field);
        field.Tick(2000, 50, 2000, 1, 0, 60, 1);
        using var terrain = await source.GetTerrainAsync();
        field.SetTerrain(TerrainPayload.Parse(terrain.RootElement), Array.Empty<P2[]>(), inline: true);
        var tree = field.Props.Single(p => p.LoUrl.Length > 0);
        var tuft = field.Props.Single(p => p.LoUrl.Length == 0);
        tree.WantLow = tree.LoUrl; tree.WantHigh = tree.HiUrl;
        // Keep the sampled entries; use a synthetic position prefix with index 0 surviving every thinning share.
        Array.Fill(tree.Pos, float.NaN);
        tree.Pos[0] = 0; tree.Pos[1] = 0; tree.Pos[2] = 0;
        tree.SphereCenter = (0, 0, 0); tree.SphereRadius = 0;
        field.Tick(0, 0, 120, 0, -1, 60, 1);
        Need("mesh owns the exact cull line", tree.ImpostorN == 0);
        field.Tick(0, 0, 121, 0, -1, 60, 1);
        Need("one billboard just outside cull", tree.ImpostorN == 1 && tree.Impostor!.VisibleInstanceCount == 1);
        Need("tuft has no far half", tuft.Impostor is null);
        Need("one lease per entry", frames.Refs == 1);
        Need("mesh sphere hides independently", tree.Hidden && tree.LowN == 0 && tree.ImpostorNode!.Visible);
        var costs = Ui.PerfProbe.ScatterSnapshot(field);
        Need("perf split counts billboard and its two triangles", costs.Impostor == new Overview.ScatterCost(1, 1, 2));
        var ug = new UndergrowthField(height); field.AddChild(ug);
        using var triangle = new ArrayMesh();
        var arrays = new Godot.Collections.Array(); arrays.Resize((int)Mesh.ArrayType.Max);
        arrays[(int)Mesh.ArrayType.Vertex] = new[] { Vector3.Zero, Vector3.Right, Vector3.Up };
        triangle.AddSurfaceFromArrays(Mesh.PrimitiveType.Triangles, arrays);
        using var mm = new MultiMesh { Mesh = triangle, TransformFormat = MultiMesh.TransformFormatEnum.Transform3D, InstanceCount = 7 };
        var ugNode = new MultiMeshInstance3D { Multimesh = mm }; ug.AddChild(ugNode);
        Need("perf split excludes undergrowth as browser debugParts.scatter does", Ui.PerfProbe.ScatterSnapshot(field) == costs);
        ug.RemoveChild(ugNode); field.AddChild(ugNode);
        var authored = Ui.PerfProbe.ScatterSnapshot(field);
        Need("nonindexed authored mesh counts geometry times instances", authored.Mesh ==
            new Overview.ScatterCost(costs.Mesh.Calls + 1, costs.Mesh.Instances + 7, costs.Mesh.Triangles + 7));
        ugNode.Visible = false;
        Need("hidden authored mesh excluded", Ui.PerfProbe.ScatterSnapshot(field) == costs);
        ugNode.Free(); ug.Free();
        var probe = new Ui.PerfProbe();
        var readout = probe.Frame(true, 0.3, field)!;
        Need("HUD actual perf keys", (long)readout["scatter"]!["impostor"]!["calls"]! == 1
            && (long)readout["scatter"]!["impostor"]!["instances"]! == 1
            && (long)readout["scatter"]!["impostor"]!["triangles"]! == 2 && readout.ContainsKey("scatterLodMs"));
        field.ImpostorsEnabled = false;
        Need("matrix impostors off hides the drawn stage immediately", tree.ImpostorN == 0 && !tree.ImpostorNode!.Visible);
        field.Tick(0, 0, 121, 0, -1, 60, 1);
        Need("matrix gate survives ticks", tree.ImpostorN == 0);
        field.ImpostorsEnabled = true;
        Need("restore re-bins immediately", tree.ImpostorN == 1);
        var first = tree.ImpostorBuf!.Take(12).ToArray();
        field.Tick(121, 0, 0, -1, 0, 60, 1);
        Need("yaw refreshed on next LOD pass", Math.Abs(tree.ImpostorBuf![0]) < 1e-5 && Math.Abs(first[0]) > 1);
        Need("upright basis", tree.ImpostorBuf[1] == 0 && tree.ImpostorBuf[4] == 0 && tree.ImpostorBuf[6] == 0 && tree.ImpostorBuf[9] == 0);
        field.Tick(0, 0, 121, 0, 1, 60, 1);
        Need("view cone gates billboards", tree.ImpostorN == 0);
        field.Tick(0, 399, 30, 0, -1, 60, 1);
        Need("slant distance beyond 400 hides", tree.ImpostorN == 0);
        field.Tick(0, 400, 0, 0, -1, 60, 1);
        Need("400 metres inclusive, high camera", tree.ImpostorN == 1);
        field.SetLod(new ScatterLodCfg(10, 20, 500));
        Need("prefs empty far window immediately", tree.ImpostorN == 0);
        for (int i = 0; i < 1000; i++)
            Need("nested seam set", ScatterLod.InstanceVisible(i, 120, ScatterLod.Defaults)
                == ScatterLod.ImpostorVisible(i, 120 + 1e-9, ScatterLod.Defaults));
        var corners = ScatterLod.ImpostorCorners(0, 4, 0, 2, 8, 200, 0);
        Need("Y-only corners", corners[0].Y == 0 && corners[1].Y == 0 && corners[2].Y == 8 && corners[3].Y == 8);
        using var material = new StandardMaterial3D { Metallic = 1 };
        using var neutral = ScatterShaders.Neutralize(material);
        Need("D7 untextured metallic neutralized without mutating source", neutral.Metallic == 0 && material.Metallic == 1);
        material.MetallicTexture = frames.Texture;
        using var textured = ScatterShaders.Neutralize(material);
        Need("D7 metallic map survives", textured.Metallic == 1);
        material.MetallicTexture = null; material.Metallic = 0.5f;
        using var threshold = ScatterShaders.Neutralize(material);
        Need("D7 threshold is strict", threshold.Metallic == 0.5f);
        field.Free();
        Need("entry releases its bake", frames.Refs == 0);
        var baker = new ImpostorBaker(new FixtureSource(source.Dir), _ => { });
        world.AddChild(baker);
        Need("dummy renderer returns no bake", baker.Acquire("offline-no-renderer") is null);
        Need("no-renderer retry is not cached as refusal", baker.LastVerdict == "retry" && baker.CachedCount == 0);
        await baker.BakeAndStoreAsync("/assets/surface-textures/ground_grass.png");
        Need("decode/parse failure retries without caching a refusal", baker.LastVerdict == "retry" && baker.CachedCount == 0);
        baker.Free();
        var layer = new ScatterLayer(source, height, () => Vector3.Zero, _ => { }); world.AddChild(layer);
        var perfCamera = new Camera3D(); world.AddChild(perfCamera);
        layer.RunLod(perfCamera);
        var timed = new Ui.PerfProbe().Frame(true, 0.3, layer)!;
        Need("HUD carries measured complete LOD pass time", layer.LastLodMs > 0 && (double)timed["scatterLodMs"]! == layer.LastLodMs);
        layer.Free(); perfCamera.Free();
        GD.Print("[check] impostors: bins=1 seam=0.25 corners=Y-only no-renderer=retry parse-failed=retry wide-frustum=pass D7=pass perf=mesh/impostor/time");
    }
}
