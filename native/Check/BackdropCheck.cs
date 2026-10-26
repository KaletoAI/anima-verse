using System;
using System.Linq;
using System.Text.Json;
using AnimaNative.Sky;
using AnimaNative.World;
using Godot;

namespace AnimaNative.Check;

/// <summary>
/// <c>--check backdrop</c> (part of every <c>--check</c>, Task 22): the far backdrop of § A17 on the REAL node
/// (<see cref="WorldBackdrop"/>, the one Main hangs under the world) against numbers derived by hand in
/// native/fixtures/README.md "Backdrop":
///
///   B0 the payload: no block = no rings; a block builds two; the same key again builds nothing; a changed seed rebuilds;
///      <c>null</c> removes them;
///   B1 the strips: vertex and index counts of an open arc and of the full ring, read back from the Godot meshes;
///   B2 heights: the hand ring (every draw ½) and the shared vector's seeded ridge (backdrop.json "ridge seeded north");
///   B3 placement and material: follows the target in x/z only (y 0, no rotation), unlit, back-face culled, no shadow,
///      the day/night tint (front noon / back night) as Godot channels.
/// </summary>
public static class BackdropCheck
{
    private static JsonElement Map(string backdrop)
        => JsonDocument.Parse("{\"backdrop\": " + backdrop + "}").RootElement.Clone();

    public static string Run(Node3D host)
    {
        var bd = new WorldBackdrop { Name = "BackdropCheck" };
        host.AddChild(bd);
        try
        {
            // ---- B0 payload ----
            bd.Sync(BackdropSpec.Of(JsonDocument.Parse("{}").RootElement));
            Expect("B0 no block, no rings", bd.Rings.Count == 0 && bd.Builds == 0 && bd.BuiltKey == "", "");
            var arc = Map("{\"height_m\": 120, \"seed\": 7, \"arcs\": [[90, 135]]}");
            bd.Sync(BackdropSpec.Of(arc));
            Expect("B0 a block builds two rings", bd.Rings.Count == 2 && bd.Builds == 1, $"{bd.Rings.Count}/{bd.Builds}");
            bd.Sync(BackdropSpec.Of(arc));
            Expect("B0 the same key builds nothing", bd.Builds == 1, $"{bd.Builds}");

            // ---- B1 strips: [90, 135] at 96 segments → nodes 25..35 + two ends = 13 points, 12 quads → 48 / 72 per ring ----
            Counts("B1 open arc", bd, 48, 72);
            bd.Sync(BackdropSpec.Of(Map("{\"height_m\": 120, \"seed\": 8, \"arcs\": [[0, 360]]}")));
            Expect("B0 a changed seed rebuilds", bd.Builds == 2, $"{bd.Builds}");
            // [0, 360]: 96 nodes + the closing one = 97 points, 96 quads → 384 / 576 per ring.
            Counts("B1 full ring", bd, 384, 576);

            // ---- B2 heights ----
            var half = Backdrop.RidgeProfile(1, new[] { (90.0, 135.0) }, 120, Backdrop.Segments, () => 0.5);
            var front = BackdropMesh.Ring(half, 0)!.Value;
            var back = BackdropMesh.Ring(half, 1)!.Value;
            // Node 30 (112.5°) = vertex 25: 120·(0.45 + 0.55·½) = 87 at (380 sin 112.5°, ·, 380 cos 112.5°); back 150·0.725.
            Near("B2 front peak 112.5° height", front.Positions[25 * 3 + 1], 87);
            Near("B2 front peak 112.5° x", front.Positions[25 * 3], 351.0742224);
            Near("B2 front peak 112.5° z", front.Positions[25 * 3 + 2], -145.4197043);
            Near("B2 back peak 112.5° height", back.Positions[25 * 3 + 1], 108.75);
            // Node 25 (93.75°), 3.75° into the arc: taper t = 0.3125 → 0.2319336 · 87.
            Near("B2 tapered node 93.75°", front.Positions[5 * 3 + 1], 20.17822266);
            Near("B2 arc start on the ground at 90° (east)", front.Positions[0] + front.Positions[1], 380);
            // backdrop.json "[20] ridge seeded north": seed 7, [157.5, 202.5], 100 m, 8 segments → the front node at 180° is
            // 66.38405470992438 (pinned by the smoke against seededRandom); it is quad 0's second peak (vertex 3) at (0, ·, −380).
            var seeded = BackdropMesh.Ring(Backdrop.RidgeProfile(7, new[] { (157.5, 202.5) }, 100, 8), 0)!.Value;
            Near("B2 seeded north peak (vector)", seeded.Positions[3 * 3 + 1], 66.38405470992438);
            Near("B2 seeded north peak z", seeded.Positions[3 * 3 + 2], -380);

            // ---- B3 placement + material ----
            bd.Follow(new Vector3(12.5f, 33f, -7f));
            Expect("B3 follows the target in x/z", bd.Position == new Vector3(12.5f, 0, -7f) && bd.Basis == Basis.Identity, $"{bd.Position}");
            var m0 = bd.MaterialOf(0)!;
            var m1 = bd.MaterialOf(1)!;
            Expect("B3 unlit, front faces, no shadow", new[] { m0, m1 }.All(m => m.ShadingMode == BaseMaterial3D.ShadingModeEnum.Unshaded
                   && m.CullMode == BaseMaterial3D.CullModeEnum.Back)
                   && bd.Rings.All(r => r.CastShadow == GeometryInstance3D.ShadowCastingSetting.Off), "");
            // Boot: night 0, sky 9fc7e8 → front lerp(5f6d84, 9fc7e8, 0.30) = linear (0.184116, 0.278386, 0.403604) → Godot
            // (0.466243, 0.564235, 0.667881).
            Col("B3 front by day", m0.AlbedoColor, 0.466243409, 0.564234836, 0.667881492);
            Col("B3 back by day (mix 0.48)", m1.AlbedoColor, 0.547455093, 0.662255663, 0.773703662);
            bd.SetDayNight(1, LinearRgb.FromSrgbHex(0x1a2340));
            Col("B3 front at night (mix 0.85)", m0.AlbedoColor, 0.175380684, 0.212773660, 0.309809025);
            Col("B3 back at night (mix capped 0.92)", m1.AlbedoColor, 0.168005033, 0.203566300, 0.301058243);

            bd.Sync(null);
            Expect("B0 null removes the rings", bd.MaterialOf(0) is null && bd.BuiltKey == "", "");

            return "backdrop B0..B3 ok (rebuild on key only; open arc 48/72, full ring 384/576 vertices/indices per ring; "
                   + "peaks 87 / 108.75 / tapered 20.178, seeded vector 66.384; follows x/z; tint day/night)";
        }
        finally
        {
            bd.QueueFree();
        }
    }

    private static void Counts(string what, WorldBackdrop bd, int verts, int indices)
    {
        foreach (var r in bd.Rings)
        {
            var mesh = (ArrayMesh)r.Mesh;
            Expect($"{what} {r.Name}", mesh.GetSurfaceCount() == 1 && mesh.SurfaceGetArrayLen(0) == verts
                   && mesh.SurfaceGetArrayIndexLen(0) == indices, $"{mesh.SurfaceGetArrayLen(0)}/{mesh.SurfaceGetArrayIndexLen(0)}");
        }
    }

    private static void Near(string what, double got, double want)
        => Expect(what, Math.Abs(got - want) < 1e-6, $"got {got}, expected {want}");

    private static void Col(string what, Color got, double r, double g, double b)
        => Expect(what, Math.Abs(got.R - r) < 1e-5 && Math.Abs(got.G - g) < 1e-5 && Math.Abs(got.B - b) < 1e-5, $"got {got}, expected ({r}, {g}, {b})");

    private static void Expect(string what, bool ok, string detail)
    {
        if (!ok) throw new InvalidOperationException($"backdrop {what}: {detail}");
    }
}
