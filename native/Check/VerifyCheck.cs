using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using System.Threading.Tasks;
using AnimaNative.Scene;
using AnimaNative.World;
using Godot;

namespace AnimaNative.Check;

/// <summary>
/// <c>--check verify</c> (part of every <c>--check</c>): the § B5a verify after each mount, over both fixture worlds,
/// against counts derived BY HAND in native/fixtures/README.md ("Verify (§ B5a)"). Per location: how many numbers
/// are checked, which rows deviate (only the <c>geladen</c> row of a spec whose mesh is missing — every mounted
/// primitive and placement must sit on its spec to 0.01 m), and placed/total models. Then two cross-checks that the
/// verify measures what is DRAWN and does find a deviation:
///   V1 the house's one drawn wall, measured off its own merged recipe mesh (not the builder's measured list),
///      against its spec → 4 numbers, 0 rows; against a spec 5 cm higher (base_y 0.05) → base_y and top_y rows,
///      delta −0.05 each;
///   V2 loc-open's chair, measured as placed, against its spec with bottom_y + 0.1 → one bottom_y row, delta −0.1.
/// </summary>
public static class VerifyCheck
{
    /// <summary>(location, checked, rows, placed, total) — README "Verify (§ B5a)".</summary>
    private static readonly (string Loc, int Checked, int Rows, int Placed, int Total)[] ExpMain =
    {
        ("loc-house", 11, 1, 1, 2),
        ("loc-yard", 30, 0, 0, 0),
    };

    private static readonly (string Loc, int Checked, int Rows, int Placed, int Total)[] ExpS3c =
    {
        ("loc-open", 52, 2, 5, 7),
        ("loc-closed", 15, 1, 2, 3),
        ("loc-far", 16, 0, 1, 1),
    };

    public static async Task<string> RunAsync(Node3D host, string fixtures)
    {
        var lines = new StringBuilder();
        var main = await Run(host, new FixtureSource(fixtures), "harbour", ExpMain, "verify-main", async (world, builder) =>
        {
            var house = builder.Slots["loc-house"];
            var interior = house.Group.GetNode<Node3D>("Interior");
            var wallMesh = interior.GetChildren().OfType<MeshInstance3D>().Single(m => m.Name.ToString().Contains("_wall0_"));
            var box = WorldBuilder.WorldBox(ToV(wallMesh.Transform * wallMesh.Mesh.GetAabb()), house.Group.Transform);
            var origin = new Overview.Vec3(house.Group.Position.X, house.Group.Position.Y, house.Group.Position.Z);
            var wall = new SceneWall(0, (-4, -3), (4, -3), 0, 3, 0.2, false, false, false);
            var good = new SceneVerifier();
            good.Primitive("wall:contour@0", box, origin, house.Group.Rotation.Y, SceneVerify.WallTargets(wall));
            Expect("V1 drawn wall", good.Checked == 4 && good.Rows.Count == 0, Rows(good));
            var bad = new SceneVerifier();
            bad.Primitive("wall:contour@0", box, origin, house.Group.Rotation.Y, SceneVerify.WallTargets(wall with { BaseY = 0.05 }));
            Expect("V1 lifted spec", bad.Rows.Select(r => (r.Field, r.Delta)).SequenceEqual(new[] { ("base_y", -0.05), ("top_y", -0.05) }), Rows(bad));
            var report = bad.Report("loc-house (V1 doctored)");
            GD.Print("[check-verify] " + report.Headline());
            foreach (var l in report.Table()) GD.Print("[check-verify] " + l);
            await Task.CompletedTask;
        });
        lines.Append(main);
        var s3c = await Run(host, new FixtureSource(Path.Combine(fixtures, "s3c"), fixtures), "Glass", ExpS3c, "verify-s3c", async (world, builder) =>
        {
            var open = builder.Slots["loc-open"];
            var chair = open.Group.GetNode<Node3D>("Interior/Room_r-ground/Placed_prop_chair");
            using var doc = System.Text.Json.JsonDocument.Parse(File.ReadAllBytes(Path.Combine(fixtures, "s3c", "scene_loc-open.json")));
            var spec = ScenePayload.Parse(doc.RootElement).Models.Single(m => m.Id == "chair");
            var origin = new Overview.Vec3(open.Group.Position.X, open.Group.Position.Y, open.Group.Position.Z);
            const double lift = 0.046875;   // README "Models": ground(66, 119) 3.921875 − datum 3.875
            var good = new SceneVerifier();
            WorldBuilder.VerifyPlacement(good, spec, chair, lift, open.Group, origin, open.Group.Rotation.Y);
            Expect("V2 chair", good.Checked == 4 && good.Rows.Count == 0, Rows(good));
            var bad = new SceneVerifier();
            WorldBuilder.VerifyPlacement(bad, spec with { BottomY = 0.1 }, chair, lift, open.Group, origin, open.Group.Rotation.Y);
            Expect("V2 raised spec", bad.Rows.Select(r => (r.Object, r.Field, r.Delta)).SequenceEqual(new[] { ("prop:chair", "bottom_y", -0.1) }), Rows(bad));
            await Task.CompletedTask;
        });
        lines.Append(' ').Append(s3c);
        return "verify " + lines + " V1 V2 ok";
    }

    private static async Task<string> Run(Node3D host, FixtureSource source, string gotoQuery,
                                          (string Loc, int Checked, int Rows, int Placed, int Total)[] expected, string tag,
                                          Func<Node3D, WorldBuilder, Task> extra)
    {
        var world = new Node3D { Name = "VerifyWorld_" + tag };
        host.AddChild(world);
        var builder = new WorldBuilder(source, line => GD.Print($"[check-{tag}] " + line), strict: true);
        try
        {
            var stats = await builder.BuildAsync(world, gotoQuery);
            var parts = new List<string>();
            foreach (var (loc, chk, rows, placed, total) in expected)
            {
                var r = builder.Slots[loc].Verify ?? throw new InvalidOperationException($"verify {loc}: no report");
                Expect($"{loc} checked", r.Checked == chk, $"got {r.Checked}, expected {chk}");
                Expect($"{loc} models", r.Placed == placed && r.Total == total, $"got {r.Placed}/{r.Total}, expected {placed}/{total}");
                Expect($"{loc} rows", r.Rows.Count == rows && r.Rows.All(x => x.Field == "geladen"),
                       $"got {r.Rows.Count} ({string.Join("; ", r.Table())}), expected {rows} geladen");
                parts.Add($"{loc} {r.Checked}/{r.Rows.Count}");
            }
            Expect($"{tag} totals", stats.VerifyLocations == expected.Length
                   && stats.VerifyChecked == expected.Sum(e => e.Checked) && stats.VerifyRows == expected.Sum(e => e.Rows),
                   stats.VerifySummary());
            await extra(world, builder);
            return string.Join(", ", parts);
        }
        finally
        {
            builder.Models?.FreeAll();
            world.QueueFree();
        }
    }

    private static VBox ToV(Aabb a) => new(new Overview.Vec3(a.Position.X, a.Position.Y, a.Position.Z),
                                           new Overview.Vec3(a.End.X, a.End.Y, a.End.Z));

    private static string Rows(SceneVerifier v) => $"{v.Checked} checked: " + string.Join("; ", v.Rows.Select(r => $"{r.Object} {r.Field} {r.Delta}"));

    private static void Expect(string what, bool ok, string detail)
    {
        if (!ok) throw new InvalidOperationException($"verify {what}: {detail}");
    }
}
