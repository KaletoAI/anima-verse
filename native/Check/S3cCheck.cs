using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Threading.Tasks;
using AnimaNative.Ground;
using AnimaNative.World;
using Godot;

namespace AnimaNative.Check;

/// <summary>
/// Task S3c: the scene shapes of a real world, reproduced in the SMALL synthetic world <c>fixtures/s3c/</c>
/// (hand-written, the ground files borrowed from <c>fixtures/</c>) and checked against the numbers derived by
/// hand in <c>fixtures/README.md</c> ("S3c world"):
///
///   • the browser's VIEW of each location: the avatar's location is OPEN (interior on the shown storey, panes of
///     door/window models hidden, outline walls culled per frame, a plan-hull model kept with its cutouts), a
///     closed one shows only its outdoor rooms + outdoor specs, a modelless one its far-view shell, a location
///     beyond the haze is not mounted (no scene request);
///   • model specs: props, a <c>measure: "fit"</c> door model, a placeholder box, a missing diorama, the § A16.9
///     terrain lift, the static tiers (ring + camera distance), world props with their variant, bottom and cull;
///   • water: the wet tile lifted onto its mirror by the shore gate, the water variant compiled and worn.
/// </summary>
public static class S3cCheck
{
    // ---- Expected values, derived in native/fixtures/README.md ("S3c world") ----
    private const int ExpLocations = 4, ExpGone = 1, ExpScenes = 3;
    private const int ExpDrawn = 9, ExpPlates = 2, ExpWalls = 5, ExpExtras = 2, ExpShellCopies = 2, ExpCulledWalls = 2;
    private const int ExpDegenerate = 1, ExpInterior = 4, ExpStorey = 3, ExpPanes = 2;
    private const int ExpBuildings = 2, ExpProps = 4, ExpDoors = 1, ExpWorld = 2;
    // Task 15 mounts the near ring's indoor specs once (hidden at fade 0): loc-closed's shelf is asked for and, having
    // no fixture, is MISSING (+1) instead of "interior"; Task 16 mounts every storey, so loc-open's level-1 lamp is
    // asked for too and is MISSING (+1) — still counted "storey" (hidden by its room group at the build's storey 0).
    private const int ExpPlaceholders = 1, ExpMissing = 3, ExpModelInterior = 0, ExpModelStorey = 1, ExpCulled = 1;
    private const int ExpInteriorMounted = 14;               // loc-open 8 + loc-closed 2 + loc-far 4 (README "Primitives")
    private const int ExpFull = 6, ExpLow = 3;
    private const int ExpBuildingVertices = 2 * 2220, ExpBuildingIndices = 2 * 3330;
    private const float ExpChairBottom = 0.046875f;          // bottom_y 0 + ground(66, 119) 3.921875 − datum 3.875
    private const float ExpDoorBottom = -0.1796875f, ExpDoorHeight = 2.1f;
    private const float ExpPlaceholderY = 0.6890625f;        // 0.9 + ground(59, 116.5) 3.6640625 − 3.875
    private const float ExpStoneBottom = 5.09375f;           // ground(80, 150) 4.84375 + 0.5 − 0.25
    private static readonly (int I, int J, float Y, float Wet)[] ExpLift =
    {
        (0, 0, 6f, 6f), (1, 0, 4f, 2f), (0, 1, 6f, 5f), (1, 1, 3f, 0f), (0, 2, 2.625f, 0.625f), (2, 0, 4f, 0f),
    };

    public static async Task<string> RunAsync(Node3D host, string fixtures)
    {
        CheckEuler();
        var dir = Path.Combine(fixtures, "s3c");
        var source = new FixtureSource(dir, fixtures);
        var world = new Node3D { Name = "S3cWorld" };
        host.AddChild(world);
        var builder = new WorldBuilder(source, line => GD.Print("[check-s3c] " + line), strict: true);
        var stats = await builder.BuildAsync(world, "Glass");
        try
        {
            Eq("s3c locations", stats.Locations, ExpLocations);
            Eq("s3c gone", stats.LocationsGone, ExpGone);
            Eq("s3c scenes", stats.Scenes, ExpScenes);
            Expect("s3c scene requests", source.SceneRequests.OrderBy(s => s).SequenceEqual(new[] { "loc-closed", "loc-far", "loc-open" }),
                   string.Join(";", source.SceneRequests));
            Expect("s3c open", stats.OpenLocation == "loc-open", stats.OpenLocation);

            var r = stats.Recipe;
            Eq("s3c primitives", r.Primitives, ExpDrawn);
            Eq("s3c plates", r.Plates, ExpPlates);
            Eq("s3c walls", r.Walls, ExpWalls);
            Eq("s3c extras", r.Extras, ExpExtras);
            Eq("s3c shell copies", r.ShellCopies, ExpShellCopies);
            Eq("s3c culled walls", r.CulledWalls, ExpCulledWalls);
            Eq("s3c degenerate", r.Degenerate, ExpDegenerate);
            Eq("s3c interior", r.Interior, ExpInterior);
            Eq("s3c storey", r.Storey, ExpStorey);
            Eq("s3c panes", r.Panes, ExpPanes);
            Eq("s3c interior mounted", r.InteriorMounted, ExpInteriorMounted);

            var m = stats.Models;
            Eq("s3c buildings placed", m.Placed["building"], ExpBuildings);
            Eq("s3c props placed", m.Placed["prop"], ExpProps);
            Eq("s3c doors placed", m.Placed["door"], ExpDoors);
            Eq("s3c windows placed", m.Placed["window"], 0);
            Eq("s3c rooms placed", m.Placed["room"], 0);
            Eq("s3c world props placed", m.Placed["world"], ExpWorld);
            Eq("s3c placeholders", m.Placeholders, ExpPlaceholders);
            Eq("s3c missing", m.Missing, ExpMissing);
            Eq("s3c model interior", m.Interior, ExpModelInterior);
            Eq("s3c model storey", m.Storey, ExpModelStorey);
            Eq("s3c faded", m.Faded, 0);
            Eq("s3c world props culled", m.Culled, ExpCulled);
            Eq("s3c tier full", m.Full, ExpFull);
            Eq("s3c tier low", m.Low, ExpLow);
            Eq("s3c building vertices", stats.BuildingVertices, ExpBuildingVertices);
            Eq("s3c building indices", stats.BuildingIndices, ExpBuildingIndices);

            // Which URLs the tiers and variants asked for — and which hidden specs asked for nothing.
            var asked = source.ByteRequests.ToHashSet();
            Expect("s3c far prop low tier", asked.Contains("/assets/props/post/model.glb?tier=low")
                   && !asked.Contains("/assets/props/post/model.glb?tier=full"), string.Join(";", asked));
            Expect("s3c world prop variant 1 full", asked.Contains("/assets/props/stone/model?variant=1&tier=full"), "");
            Expect("s3c world prop low", asked.Contains("/assets/props/sign/model?tier=low"), "");
            Expect("s3c level-1 lamp asked at the mount (every storey)", asked.Contains("/assets/props/lamp/model?tier=full"), "");
            Expect("s3c near-ring shelf asked at the mount", asked.Contains("/assets/props/shelf/model?tier=full"), "");

            // Placements, measured in the location frame (§ B2 + the § A16.9 lift).
            var open = world.GetNode<Node3D>("Locations/Loc_loc-open");
            // Indoor specs hang in the interior group (mounted once, shown by the crossfade).
            var openInterior = open.GetNode<Node3D>("Interior");
            var chair = Descendants(openInterior).OfType<Node3D>().Single(n => n.Name.ToString() == "Placed_prop_chair");
            Expect("s3c chair in its room group", chair.GetParent().Name.ToString() == "Room_r-ground", chair.GetParent().Name);
            Near("s3c chair bottom (lift)", ModelPlacement.Measure(chair, Transform3D.Identity).Position.Y, ExpChairBottom);
            var door = Descendants(openInterior).OfType<Node3D>().Single(n => n.Name.ToString() == "Placed_prop_door_s3c0001");
            var doorBox = ModelPlacement.Measure(door, Transform3D.Identity);
            Near("s3c door bottom", doorBox.Position.Y, ExpDoorBottom);
            Near("s3c door height (fit)", doorBox.Size.Y, ExpDoorHeight);
            var ph = Descendants(openInterior).OfType<Node3D>().Single(n => n.Name.ToString().StartsWith("Placeholder"));
            Near("s3c placeholder y", ph.Position.Y, ExpPlaceholderY);
            Near("s3c placeholder yaw", ph.Rotation.Y, Mathf.DegToRad(90f));

            // The plan hull is ONE model whose 8 surfaces wear cut materials (Task 17: per fragment, like cutouts.ts):
            // the cutout [-3,-3]..[3,3] around loc-open's pin (64, 120), yaw 0 → world x 61..67, z 117..123, no GLB
            // padding (building_original.glb's node has no extras), the switch OFF at the build (fade 0).
            Expect("s3c whole hull, no cut copy", open.GetChildren().OfType<Node3D>().Count(n => n.Name.ToString() == "Placed_building_loc-open") == 1
                   && open.GetNodeOrNull("Cutout_building_loc-open") is null, "");
            var openSlot = builder.Slots["loc-open"];
            Expect("s3c one cutout handle", openSlot.Fade.Cutouts.Count == 1, $"{openSlot.Fade.Cutouts.Count}");
            var handle = openSlot.Fade.Cutouts[0];
            Expect("s3c cut surfaces (8 primitives, none left uncut)", handle.Entries.Count == 8 && handle.Fallbacks == 0,
                   $"{handle.Entries.Count} entries, {handle.Fallbacks} fallbacks");
            Expect("s3c cut stats", stats.CutPlacements == 1 && stats.CutSurfaces == 8 && stats.CutFallbacks == 0, stats.CutSummary());
            Expect("s3c cutouts start off", !handle.CutoutsOn
                   && handle.Entries.All(e => (float)e.Material.GetShaderParameter("cut_on") == 0f), "");
            var e0 = handle.Entries[0].Material;
            var pts = e0.GetShaderParameter("cut_pts").AsVector2Array();
            Expect("s3c cutout uniforms in world xz", pts.SequenceEqual(new[] { new Vector2(61, 117), new Vector2(67, 117), new Vector2(67, 123), new Vector2(61, 123) })
                   && e0.GetShaderParameter("cut_off").AsInt32Array().SequenceEqual(new[] { 0 })
                   && e0.GetShaderParameter("cut_len").AsInt32Array().SequenceEqual(new[] { 4 }), string.Join(";", pts));
            // The CPU twin of the injected test on the uniforms as written: the pin (64, 120) and (66.9, 122.9) are inside,
            // (67.1, 120) is outside; switched off nothing goes — the same answers ClipMath gives (vector-checked).
            var u0 = handle.Entries[0].Uniforms;
            var worldPoly = new[] { new Scatter.P2(61, 117), new Scatter.P2(67, 117), new Scatter.P2(67, 123), new Scatter.P2(61, 123) };
            foreach (var (px, pz, want) in new[] { (64.0, 120.0, true), (66.9, 122.9, true), (67.1, 120.0, false) })
            {
                bool got = Scene.CutShader.Discards(u0, new Overview.Vec3(px, 5, pz), true);
                Expect($"s3c cutout discards ({px},{pz})", got == want
                       && got == Scene.ClipMath.CutoutDiscardsPoint(new Scatter.P2(px, pz), new[] { worldPoly }),
                       got.ToString());
                Expect($"s3c cutout off keeps ({px},{pz})", !Scene.CutShader.Discards(u0, new Overview.Vec3(px, 5, pz), false), "");
            }
            Expect("s3c shader cut[std+cutouts]", ShaderSafety.Lines.Contains("shader cut[std+cutouts]: compiled (18 uniforms)"),
                   string.Join(" | ", ShaderSafety.Lines));
            // The crossfade opens them at f > 0.03: loc-open is the open location; 1 frame at 1/60 s gives f = 1 − e^(−1/15)
            // = 0.0645 > 0.03.
            builder.TickView(1.0 / 60, new Vector3(64, 30, 160));
            Expect("s3c cutouts open with the fade", handle.CutoutsOn
                   && handle.Entries.All(e => (float)e.Material.GetShaderParameter("cut_on") == 1f), $"fade {openSlot.Fade.Fade}");

            // The outline walls of the open location wear the culling material, the glass the translucent one.
            var recipeMats = Descendants(open).OfType<MeshInstance3D>()
                .Select(mi => mi.Mesh.SurfaceGetMaterial(0)).OfType<ShaderMaterial>().ToList();
            Expect("s3c wall-cull material", recipeMats.Any(x => (float)x.GetShaderParameter("wall_cull") > 0.5f), "");
            Expect("s3c translucent glass", recipeMats.Any(x => Math.Abs((float)x.GetShaderParameter("opacity") - 0.3f) < 1e-6), "");
            Expect("s3c textured wall", recipeMats.Any(x => (float)x.GetShaderParameter("has_tex") > 0.5f), "");

            // World prop: bottom on ground + offset_y + ground_offset_m.
            var stone = world.GetNode<Node3D>("WorldProps").GetChildren().OfType<Node3D>()
                             .Single(n => n.Name.ToString() == "Placed_prop_stone");
            Near("s3c world prop bottom", ModelPlacement.Measure(stone, Transform3D.Identity).Position.Y, ExpStoneBottom);

            // Water: lifted lattice, the variant on the wet tile.
            var tile = builder.Height!.Tiles.Single(t => t.Key == (0, 0));
            var w = tile.Water ?? throw new InvalidOperationException("s3c: tile 0,0 has no water field");
            Eq("s3c wet texels", w.Wet, 5);
            foreach (var (i, j, y, wet) in ExpLift)
            {
                int k = j * w.Cols + i;
                float h = tile.Grid.At(i, j);
                float lifted = (float)Water.Lifted(h, w.Level[k], w.Sd[k]);
                Near($"s3c lift ({i},{j})", lifted, y);
                Near($"s3c wet ({i},{j})", lifted - h, wet);
            }
            var tileNode = world.GetNode<MeshInstance3D>("Terrain/TerrainTile_0_0");
            Expect("s3c tile tagged wet", tileNode.HasMeta("wet"), "");
            CheckTileVertices(tileNode);
            Expect("s3c water material", builder.Ground?.WaterMaterial is not null && tileNode.MaterialOverride == builder.Ground.WaterMaterial,
                   "the wet tile does not wear the water variant");
            Expect("s3c water mode", stats.WaterMode == "drawn" && stats.WaterTiles == 1 && stats.WaterKinds == 1 && stats.WaterTexels == 5
                   && stats.WaterAreas == 0,
                   stats.WaterSummary());
            var win = builder.Ground!.WaterWindow!;
            Expect("s3c water window", win.Cols == 5 && win.Rows == 5 && win.OriginX == 0 && win.OriginZ == 0 && win.Step == 64,
                   $"{win.Cols}x{win.Rows} @ ({win.OriginX}, {win.OriginZ}) step {win.Step}");
            Near("s3c window sd (1,0)", win.Sd[1], 0.25f);
            Near("s3c window sd dry", win.Sd[2 * 5 + 2], (float)Water.SdDry);
            Expect("s3c water look default", builder.Ground.WaterLooks.Count == 1
                   && Math.Abs(builder.Ground.WaterLooks[0].OpaqueDepthM - 1.5) < 1e-9, "");

            // Every spatial shader compiled in the headless front end (one log line each).
            foreach (var name in new[] { "ground", "ground-water", "recipe[opaque]", "recipe[translucent]", "recipe[opaque,both-sides]" })
                Expect($"s3c shader {name}", ShaderSafety.Lines.Contains($"shader {name}: compiled ({UniformCount(name)} uniforms)"),
                       string.Join(" | ", ShaderSafety.Lines));

            // --no-water: no lift, no variant, the flag in the stats.
            var dry = await NoWaterRun(host, dir, fixtures);

            return $"s3c drawn={r.Primitives} skipped={r.Skipped} ({r.SkipSummary()}) shell={r.ShellCopies} "
                   + $"culled_walls={r.CulledWalls} {m.Summary()} {stats.CutSummary()} "
                   + $"{stats.WaterSummary()} no_water={dry}";
        }
        finally
        {
            builder.Models?.FreeAll();
            world.QueueFree();
        }
    }

    /// <summary>
    /// The rotations reach Godot as the Core's matrices (<see cref="ModelPlacement.ToBasis"/>), never as a Godot
    /// Euler. Here the Godot side of that hand-over is pinned: the extra of scene_primitives.json [6] (XYZ 90/90/90,
    /// centre (10, 20, 30)) must put the local point (1, 2, 3) on (13, 18, 31) through the Godot basis, and
    /// Godot's own <c>Basis.FromEuler</c> must agree with the Core for the orders the spike used (XYZ for extras,
    /// YXZ for the model fix) and for the yaw about +y — so a later caller that reaches for FromEuler is not wrong.
    /// </summary>
    private static void CheckEuler()
    {
        var extra = new SceneExtra("stair_stringer", new double[] { 10, 20, 30 }, new double[] { 2, 4, 6 }, new double[] { 90, 90, 90 });
        var basis = ModelPlacement.ToBasis(AnimaNative.Scene.PrimitiveMath.ExtraMatrix(extra));
        var p = basis * new Vector3(1, 2, 3) + new Vector3(10, 20, 30);
        Expect("euler xyz extra [6]", p.DistanceTo(new Vector3(13, 18, 31)) < 1e-5f, p.ToString());
        foreach (var (x, y, z) in new[] { (90.0, 90.0, 90.0), (5.0, 110.0, 355.0), (-38.2997, 0.0, 0.0), (0.0, 0.0, 38.2997) })
        {
            const double d = Math.PI / 180;
            var v = new Vector3((float)(x * d), (float)(y * d), (float)(z * d));
            SameBasis($"euler xyz {x}/{y}/{z}", Basis.FromEuler(v, EulerOrder.Xyz),
                      ModelPlacement.ToBasis(AnimaNative.Scene.Mat3.EulerXyz(x * d, y * d, z * d)));
            SameBasis($"euler yxz {x}/{y}/{z}", Basis.FromEuler(v, EulerOrder.Yxz),
                      ModelPlacement.ToBasis(AnimaNative.Scene.Mat3.EulerYxz(x * d, y * d, z * d)));
        }
        SameBasis("yaw 217", new Basis(Vector3.Up, Mathf.DegToRad(217f)),
                  ModelPlacement.ToBasis(AnimaNative.Scene.Mat3.RotY(217 * Math.PI / 180)));
    }

    private static void SameBasis(string what, Basis godot, Basis core)
    {
        float worst = 0;
        for (int c = 0; c < 3; c++) worst = Math.Max(worst, (godot[c] - core[c]).Length());
        Expect(what, worst < 1e-5f, $"Godot {godot} vs Core {core}");
    }

    private static int UniformCount(string name) => name switch
    {
        "ground" => GroundShader.Get().GetShaderUniformList().Count,
        "ground-water" => GroundShader.Get(true).GetShaderUniformList().Count,
        "recipe[opaque]" => RecipeMaterials.ShaderFor(false, false).GetShaderUniformList().Count,
        "recipe[translucent]" => RecipeMaterials.ShaderFor(true, false).GetShaderUniformList().Count,
        _ => RecipeMaterials.ShaderFor(false, true).GetShaderUniformList().Count,
    };

    /// <summary>The tile mesh itself: vertex y = the lifted height, UV2.x = the lift (when the renderer keeps arrays).</summary>
    private static void CheckTileVertices(MeshInstance3D node)
    {
        if (node.Mesh is not ArrayMesh mesh || mesh.GetSurfaceCount() == 0) throw new InvalidOperationException("s3c: tile has no mesh");
        var arrays = mesh.SurfaceGetArrays(0);
        var verts = arrays[(int)Mesh.ArrayType.Vertex].AsVector3Array();
        var uv2 = arrays[(int)Mesh.ArrayType.TexUV2].AsVector2Array();
        Expect("s3c tile arrays", verts.Length == 25 && uv2.Length == 25, $"{verts.Length} vertices, {uv2.Length} uv2");
        foreach (var (i, j, y, wet) in ExpLift)
        {
            Near($"s3c tile vertex ({i},{j}) y", verts[j * 5 + i].Y, y);
            Near($"s3c tile vertex ({i},{j}) uv2", uv2[j * 5 + i].X, wet);
        }
    }

    private static async Task<string> NoWaterRun(Node3D host, string dir, string fixtures)
    {
        var source = new FixtureSource(dir, fixtures);
        var world = new Node3D { Name = "S3cDry" };
        host.AddChild(world);
        var builder = new WorldBuilder(source, _ => { }, strict: true) { NoWater = true };
        try
        {
            var stats = await builder.BuildAsync(world, "Glass");
            var tileNode = world.GetNode<MeshInstance3D>("Terrain/TerrainTile_0_0");
            Expect("s3c --no-water mode", stats.WaterMode == "off: --no-water", stats.WaterMode);
            Expect("s3c --no-water untagged", !tileNode.HasMeta("wet") && builder.Ground?.WaterMaterial is null, "");
            var verts = ((ArrayMesh)tileNode.Mesh).SurfaceGetArrays(0)[(int)Mesh.ArrayType.Vertex].AsVector3Array();
            Near("s3c --no-water bed (0,0)", verts[0].Y, 0f);
            return stats.WaterSummary();
        }
        finally
        {
            builder.Models?.FreeAll();
            world.QueueFree();
        }
    }

    private static IEnumerable<Node> Walk(Node n)
    {
        yield return n;
        foreach (var c in n.GetChildren())
        foreach (var d in Walk(c))
            yield return d;
    }

    private static void Expect(string what, bool ok, string detail)
    {
        if (!ok) throw new InvalidOperationException($"{what}: {detail}");
    }

    private static void Eq(string what, int got, int want) => Expect(what, got == want, $"got {got}, expected {want}");

    private static void Near(string what, float got, float want, float eps = 1e-3f)
        => Expect(what, Math.Abs(got - want) <= eps, $"got {got}, expected {want}");

    /// <summary>Every node below <paramref name="n"/> (room groups nest the interior's pieces since Task 16).</summary>
    private static IEnumerable<Node> Descendants(Node n)
    {
        foreach (var c in n.GetChildren())
        {
            yield return c;
            foreach (var d in Descendants(c)) yield return d;
        }
    }
}
