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
    private const int ExpPlaceholders = 1, ExpMissing = 1, ExpModelInterior = 1, ExpModelStorey = 1, ExpCulled = 1;
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
            Expect("s3c hidden specs not loaded", !asked.Any(u => u.Contains("/lamp/") || u.Contains("/shelf/")), "");

            // Placements, measured in the location frame (§ B2 + the § A16.9 lift).
            var open = world.GetNode<Node3D>("Locations/Loc_loc-open");
            var chair = open.GetChildren().OfType<Node3D>().Single(n => n.Name.ToString() == "Placed_prop_chair");
            Near("s3c chair bottom (lift)", ModelPlacement.Measure(chair, Transform3D.Identity).Position.Y, ExpChairBottom);
            var door = open.GetChildren().OfType<Node3D>().Single(n => n.Name.ToString() == "Placed_prop_door_s3c0001");
            var doorBox = ModelPlacement.Measure(door, Transform3D.Identity);
            Near("s3c door bottom", doorBox.Position.Y, ExpDoorBottom);
            Near("s3c door height (fit)", doorBox.Size.Y, ExpDoorHeight);
            var ph = open.GetChildren().OfType<Node3D>().Single(n => n.Name.ToString().StartsWith("Placeholder"));
            Near("s3c placeholder y", ph.Position.Y, ExpPlaceholderY);
            Near("s3c placeholder yaw", ph.Rotation.Y, Mathf.DegToRad(90f));

            // The plan hull kept its outside and lost its inside (no remaining centroid in the cutout).
            var hull = open.GetChildren().OfType<Node3D>().Single(n => n.Name.ToString() == "Placed_building_loc-open");
            Expect("s3c cutout removed triangles", stats.CutoutTriangles > 0 && stats.CutoutTriangles < 3330 / 3,
                   stats.CutoutTriangles.ToString());
            CheckCutoutClean(hull);

            // The outline walls of the open location wear the culling material, the glass the translucent one.
            var recipeMats = open.GetChildren().OfType<MeshInstance3D>()
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
                   + $"culled_walls={r.CulledWalls} {m.Summary()} cutout_triangles={stats.CutoutTriangles} "
                   + $"{stats.WaterSummary()} no_water={dry}";
        }
        finally
        {
            builder.Models?.FreeAll();
            world.QueueFree();
        }
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

    /// <summary>No triangle of the kept hull has its centroid inside the cutout (location frame).</summary>
    private static void CheckCutoutClean(Node3D hull)
    {
        var poly = new (double X, double Z)[] { (-3, -3), (3, -3), (3, 3), (-3, 3) };
        int left = 0, inside = 0;
        foreach (var mi in Walk(hull).OfType<MeshInstance3D>())
        {
            var xf = hull.Transform * Rel(mi, hull);
            var mesh = (ArrayMesh)mi.Mesh;
            for (int s = 0; s < mesh.GetSurfaceCount(); s++)
            {
                var a = mesh.SurfaceGetArrays(s);
                var v = a[(int)Mesh.ArrayType.Vertex].AsVector3Array();
                var idx = a[(int)Mesh.ArrayType.Index].AsInt32Array();
                for (int i = 0; i + 2 < idx.Length; i += 3)
                {
                    var c = xf * ((v[idx[i]] + v[idx[i + 1]] + v[idx[i + 2]]) / 3f);
                    left++;
                    if (LocationView.PointInPolygon(c.X, c.Z, poly)) inside++;
                }
            }
        }
        Expect("s3c cutout clean", left > 0 && inside == 0, $"{left} triangles left, {inside} inside the cutout");
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

    private static Transform3D Rel(Node3D node, Node3D ancestor)
    {
        var xf = Transform3D.Identity;
        for (Node? n = node; n is not null && n != ancestor; n = n.GetParent())
            if (n is Node3D n3) xf = n3.Transform * xf;
        return xf;
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
}
