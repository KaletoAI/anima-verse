using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Threading.Tasks;
using AnimaNative.Overview;
using AnimaNative.Scatter;
using AnimaNative.Scene;
using AnimaNative.World;
using Godot;

namespace AnimaNative.Check;

/// <summary>
/// <c>--check fidelity</c> (part of every <c>--check</c>, Task 17): model fidelity on the hand-written world
/// <c>fixtures/fidelity/</c> (README "Fidelity world"), against numbers derived there by hand:
///
///   F1 metalness neutralisation of every GLB (glbMaterials.ts): the hull's unset metallicFactor (glTF 1.0) → 0, the
///      textured metal box keeps 1;
///   F2 the cut shaders compile headless with the hand-counted uniforms, and which placements carry which cuts;
///   F3 which world points the cut uniforms AS WRITTEN discard — the CPU twin of the injected GLSL
///      (<see cref="CutShader.Discards"/>) on the hull's cutout with the GLB's 0.25 m padding, the room clip, two depth
///      cuts on a location turned by 90° (one on a placeholder box) — and that the cutouts agree with ClipMath;
///   F4 the cutout switch follows the fade (on past 0.03), a shell area's stays shut;
///   F5 the tier swap: camera distances 70 → 44 → 50 → 61 m give low, full, full, low (45/60 hysteresis), the hull mesh
///      is replaced in place, the old one leaves the tree, the cuts come along with the switch state;
///   F6 a height revision re-datums the two locations on the changed tile and re-lifts the one placement that moved;
///   F7 the 60 s sweep remounts exactly the location whose scene signature moved, carrying its open target.
/// </summary>
public static class FidelityCheck
{
    private const float HullDatum = 3.875f;              // tile (0,0) ground at (64, 120) = 2·64/64 + 120/64
    private const float PropDatum = 4.693359375f;        // overview at (−40, 100) (README "S3c world")
    private const double HalfDiagonal = 12 * 0.7071067811865476;   // plan_width 12 · √½

    public static async Task<string> RunAsync(Node3D host, string fixtures)
    {
        var dir = Path.Combine(fixtures, "fidelity");
        var source = new FixtureSource(dir, fixtures);
        var world = new Node3D { Name = "FidelityWorld" };
        host.AddChild(world);
        var builder = new WorldBuilder(source, line => GD.Print("[check-fidelity] " + line), strict: true);
        try
        {
            var stats = await builder.BuildAsync(world, "Hull");
            var hull = builder.Slots["loc-hull"];
            var prop = builder.Slots["loc-prop"];
            var area = builder.Slots["loc-area"];
            Near("datum loc-hull", hull.Group.Position.Y, HullDatum);
            Near("datum loc-prop", prop.Group.Position.Y, PropDatum);
            Near("datum loc-area", area.Group.Position.Y, 2.8125);   // 2·20/64 + 140/64

            // ---- F1 neutralisation ----
            // Task 44 / controller ruling: gone→far mounts hull_low, then far→near swaps to hull_full.
            // Two loaded GLBs, each with one untextured material (no metallicFactor → 1.0 → 0),
            // each neutralised once: 1 + 1 = 2. box.glb has a metallicRoughnessTexture and keeps 1.0.
            Eq("F1 neutralised at the boot", builder.Models!.Neutralized, 2);
            var hullRec = hull.Placements.Single(r => r.IsBuilding);
            var roomRec = hull.Placements.Single(r => r.Spec.Id == "r-hall");
            var tableRec = prop.Placements.Single(r => r.Spec.Id == "table");
            var crateRec = prop.Placements.Single(r => r.Spec.Id == "crate");
            var areaRec = area.Placements.Single(r => r.IsBuilding);
            var stoneRec = area.Placements.Single(r => r.Spec.Id == "stone");
            Expect("F1 hull metallic 0", (float)hullRec.Cut!.Entries[0].Material.GetShaderParameter("metallic") == 0f, "");
            Expect("F1 textured metal keeps 1", (float)roomRec.Cut!.Entries[0].Material.GetShaderParameter("metallic") == 1f
                   && (float)tableRec.Cut!.Entries[0].Material.GetShaderParameter("metallic") == 1f, "");

            // ---- F2 shaders and cut placements ----
            // Generator uniforms of a glTF material without emission/normal/AO/alpha: albedo, texture_albedo,
            // albedo_texture_size, point_size, roughness, texture_metallic, metallic_texture_channel, texture_roughness,
            // specular, metallic, uv1_scale, uv1_offset, uv2_scale, uv2_offset = 14; cutouts +4 (cut_pts, cut_off, cut_len,
            // cut_on), clip +1 (clip_pts), plane +1 (cut_plane). Task 53 adds occ_gate +1 to the hull; its four
            // globals are shared, not material uniforms. The placeholder's source is the recipe placeholder shader.
            var placeholderSrc = RecipeMaterials.ShaderFor(true, false).GetShaderUniformList().Count;
            foreach (var (name, count) in new[] { ("cut[std+corridor+cutouts+pad]", 19), ("cut[std+clip]", 15), ("cut[std+plane]", 15),
                                                  ($"cut[shader{placeholderSrc}+plane]", placeholderSrc + 1) })
                Expect($"F2 shader {name}", ShaderSafety.Lines.Contains($"shader {name}: compiled ({count} uniforms)"),
                       string.Join(" | ", ShaderSafety.Lines.Where(l => l.Contains("cut["))));
            // Cut placements: hull (cutouts), room (clip), table (plane), crate (placeholder, plane), area (cutouts) = 5;
            // one surface each; the stone carries nothing.
            Expect("F2 cut stats", stats.CutPlacements == 5 && stats.CutSurfaces == 5 && stats.CutFallbacks == 0, stats.CutSummary());
            Expect("F2 stone uncut", stoneRec.Cut is null, "");
            Expect("F2 cut kinds", hullRec.Cut.Entries[0].Uniforms is { HasCutouts: true, HasClip: false, HasPlane: false }
                   && roomRec.Cut.Entries[0].Uniforms is { HasClip: true, HasCutouts: false, HasPlane: false }
                   && tableRec.Cut!.Entries[0].Uniforms is { HasPlane: true, HasClip: false }
                   && crateRec.Placeholder && crateRec.Cut!.Entries[0].Uniforms is { HasPlane: true, HasClip: false }, "");
            Expect("F2 two-sided", hullRec.Cut.Entries[0].Material.Shader.Code.Contains("cull_disabled")
                   && !hullRec.Cut.Entries[0].Material.Shader.Code.Contains("cull_back"), "");
            Expect("F2 the template stays uncut", FirstMesh(hullRec.Node!)!.Mesh.SurfaceGetMaterial(0) is StandardMaterial3D, "");

            // ---- F3 discards ----
            // Hull (64, 120) yaw 0, scale max_m 10 / 10 m = 1: cutout world x 61..67, z 117..123; padding 0.25 · 1.
            var hu = hullRec.Cut.Entries[0].Uniforms;
            Near("F3 hull padding", hu.Padding, 0.25);
            Expect("F3 hull padding define", hullRec.Cut.Entries[0].Material.Shader.Code.Contains("#define CUT_PADDING_SQ 0.0625"), "");
            var hullPoly = new[] { new P2(61, 117), new P2(67, 117), new P2(67, 123), new P2(61, 123) };
            Expect("F3 hull uniforms", hullRec.Cut.Entries[0].Material.GetShaderParameter("cut_pts").AsVector2Array()
                       .SequenceEqual(hullPoly.Select(p => new Vector2((float)p.X, (float)p.Z))), "");
            foreach (var (x, z, want, why) in new[]
                     {
                         (64.0, 120.0, true, "inside"), (67.2, 120.0, true, "0.2 m outside, within the padding"),
                         (67.3, 120.0, false, "0.3 m outside"), (60.8, 120.0, true, "0.2 m outside the west edge"),
                         (64.0, 123.3, false, "0.3 m beyond the north edge"),
                     })
            {
                bool got = CutShader.Discards(hu, new Vec3(x, 4, z), true);
                Expect($"F3 hull ({x},{z}) {why}", got == want
                       && got == ClipMath.CutoutDiscardsPoint(new P2(x, z), new[] { hullPoly }, 0.25), $"{got}");
                Expect($"F3 hull ({x},{z}) switched off", !CutShader.Discards(hu, new Vec3(x, 4, z), false), "");
            }
            // Room clip (−5,−5)…(5,0) around (64, 120) → world x 59..69, z 115..120: keep inside, discard outside.
            var ru = roomRec.Cut.Entries[0].Uniforms;
            Expect("F3 clip uniforms", roomRec.Cut.Entries[0].Material.GetShaderParameter("clip_pts").AsVector2Array()
                       .SequenceEqual(new[] { new Vector2(59, 115), new Vector2(69, 115), new Vector2(69, 120), new Vector2(59, 120) }), "");
            Expect("F3 clip keeps (64, 118)", !CutShader.Discards(ru, new Vec3(64, 4, 118), false)
                   && ClipMath.ClipKeepsPoint(new P2(64, 118), ru.Clip), "");
            Expect("F3 clip drops (64, 121)", CutShader.Discards(ru, new Vec3(64, 4, 121), false)
                   && !ClipMath.ClipKeepsPoint(new P2(64, 121), ru.Clip), "");
            // Table: local plane n (1,0,0), c −0.5 (keep x_local ≥ 0.5) at yaw 90° — local x runs to world −z, the plane
            // point (0.5, 0, 0) is world z = 100 − 0.5 → world n (0,0,−1), c = 99.5. Crate: n (0,0,1), c 0 → local z runs to
            // world +x → n (1,0,0), c = −(1 · −40) = 40.
            NearPlane("F3 table plane", tableRec.Cut!.Entries[0].Uniforms.Plane, 0, 0, -1, 99.5);
            NearPlane("F3 crate plane", crateRec.Cut!.Entries[0].Uniforms.Plane, 1, 0, 0, 40);
            var tu = tableRec.Cut.Entries[0].Uniforms;
            var cu = crateRec.Cut.Entries[0].Uniforms;
            Expect("F3 table keeps z 99, drops z 100", !CutShader.Discards(tu, new Vec3(-40, 5, 99), false)
                   && CutShader.Discards(tu, new Vec3(-40, 5, 100), false), "");
            Expect("F3 crate keeps x −39, drops x −41", !CutShader.Discards(cu, new Vec3(-39, 5, 100), false)
                   && CutShader.Discards(cu, new Vec3(-41, 5, 100), false), "");

            // ---- F4 the switch follows the fade ----
            Expect("F4 closed: shut", !hullRec.Cut.CutoutsOn && !areaRec.Cut!.CutoutsOn, "");
            var cam0 = new Vector3(64, 30, 200);
            Expect("F4 open both", builder.SetOpen("loc-hull", true) && builder.SetOpen("loc-area", true), "");
            builder.TickView(1.0 / 60, cam0);   // f = 1 − e^(−1/15) = 0.0645 > 0.03
            Expect("F4 hull cutouts open", hullRec.Cut.CutoutsOn
                   && (float)hullRec.Cut.Entries[0].Material.GetShaderParameter("cut_on") == 1f, $"fade {hull.Fade.Fade}");
            Expect("F4 shell area stays shut, fades as a roof part", !areaRec.Cut!.CutoutsOn && area.Fade.RoofParts.Contains(areaRec.Node!)
                   && !hull.Fade.RoofParts.Contains(hullRec.Node!), "");
            builder.SetOpen("loc-area", false);

            // ---- F5 tier swap 70 → 44 → 50 → 61 m ----
            // Boot: anchor y = overview(64,120) 7.34375, camera = anchor + (0, 24, 40) → |(0, 27.46875, 40)| = 48.5235 m,
            // minus 12·√½ = 40.04 < 45 → full.
            Expect("F5 boot tier full", hull.BuildingTier == "full" && hullRec.Url == "/f/hull_full.glb", hull.BuildingTier);
            var expected = new[] { (70.0, "low", 1), (44.0, "full", 1), (50.0, "full", 0), (61.0, "low", 1) };
            var tiers = new List<string>();
            foreach (var (d, want, swaps) in expected)
            {
                var before = hullRec.Node!;
                int version = hull.MeshVersion;
                var cam = hull.Group.Position + new Vector3(0, 0, (float)(d + HalfDiagonal));
                var tick = builder.TickModels(cam);
                int swapped = (await Task.WhenAll(tick.Swaps)).Sum();
                tiers.Add(hull.BuildingTier);
                Expect($"F5 {d} m → {want}", hull.BuildingTier == want && hullRec.Url == $"/f/hull_{want}.glb", $"{hull.BuildingTier} {hullRec.Url}");
                Eq($"F5 {d} m swaps", swapped, swaps);
                if (swaps == 0) { Expect($"F5 {d} m kept", ReferenceEquals(before, hullRec.Node), ""); continue; }
                Expect($"F5 {d} m replaced in place", !ReferenceEquals(before, hullRec.Node) && !before.IsInsideTree()
                       && hullRec.Node!.GetParent() == hull.Group && hull.MeshVersion == version + 1, "");
                Expect($"F5 {d} m cuts came along", hull.Fade.Cutouts.Count == 1 && hull.Fade.Cutouts[0] == hullRec.Cut
                       && hullRec.Cut!.CutoutsOn && FirstMesh(hullRec.Node!)!.GetSurfaceOverrideMaterial(0) == hullRec.Cut.Entries[0].Material
                       && (float)hullRec.Cut.Entries[0].Material.GetShaderParameter("cut_on") == 1f, "");
            }
            Expect("F5 sequence", string.Join(",", tiers) == "low,full,full,low", string.Join(",", tiers));
            Eq("F5 hull_low neutralised too", builder.Models.Neutralized, 2);
            Expect("F5 low material metallic 0", (float)hullRec.Cut!.Entries[0].Material.GetShaderParameter("metallic") == 0f, "");

            // ---- F6 height revision ----
            // A flat tile (0,0) at 10 m: loc-hull 3.875 → 10 (+6.125), loc-area 2.8125 → 10 (+7.1875); loc-prop stands on
            // the overview and stays. The stone's lift was ground(23, 140) − 2.8125 = 2.90625 − 2.8125 = 0.09375 and is 0 on
            // the flat tile (re-lifted); the hall diorama's anchor is the pin (lift 0 before and after).
            int rev = builder.Height!.Revision;
            var stoneY = stoneRec.Node!.Position.Y;
            builder.Height.AddTiles(new[] { new HeightTile((0, 0), new HeightGrid(0, 0, 64, 5, 5, Enumerable.Repeat(10f, 25).ToArray())) });
            Eq("F6 revision", builder.Height.Revision, rev + 1);
            var redatum = builder.TickModels(hull.Group.Position + new Vector3(0, 0, (float)(61 + HalfDiagonal)));
            Eq("F6 datums moved", redatum.Redatumed, 2);
            Eq("F6 placements re-lifted", redatum.Relifted, 1);
            Near("F6 loc-hull datum", hull.Group.Position.Y, 10);
            Near("F6 loc-area datum", area.Group.Position.Y, 10);
            Near("F6 loc-prop datum", prop.Group.Position.Y, PropDatum);
            Near("F6 stone lift", stoneRec.Lift, 0);
            Near("F6 stone moved by −0.09375", stoneRec.Node.Position.Y - stoneY, -0.09375);
            Near("F6 hall lift", roomRec.Lift, 0);
            Eq("F6 a second tick changes nothing", builder.TickModels(hull.Group.Position + new Vector3(0, 0, 80)).Redatumed, 0);

            // ---- F7 the scene sweep ----
            int requests = source.SceneRequests.Count;
            var nothing = await builder.SweepAsync();
            Expect("F7 unchanged signatures: no remount", nothing.Count == 0 && ReferenceEquals(builder.Slots["loc-hull"], hull)
                   && source.SceneRequests.Count == requests + 3, $"{string.Join(",", nothing)}");
            int remountEvents = 0;
            builder.Remounted += (_, _) => remountEvents++;
            source.SceneFiles["loc-hull"] = "scene_loc-hull.v2.json";
            var remounted = await builder.SweepAsync();
            var hull2 = builder.Slots["loc-hull"];
            Expect("F7 only loc-hull remounted", remounted.SequenceEqual(new[] { "loc-hull" }) && remountEvents == 1
                   && !ReferenceEquals(hull2, hull) && ReferenceEquals(builder.Slots["loc-prop"], prop)
                   && ReferenceEquals(builder.Slots["loc-area"], area), string.Join(",", remounted));
            Expect("F7 new signature, open carried, new group on today's ground", hull2.Signature == "hull-2" && hull2.Open
                   && hull2.Group.IsInsideTree() && Math.Abs(hull2.Group.Position.Y - 10) < 1e-4, $"{hull2.Signature} {hull2.Group.Position}");
            // QueueFree lands at a frame end; under a loaded full --check that can be a frame or two later.
            for (int f = 0; f < 5 && GodotObject.IsInstanceValid(hull.Group); f++)
                await host.ToSignal(host.GetTree(), SceneTree.SignalName.ProcessFrame);
            Expect("F7 old group gone", !GodotObject.IsInstanceValid(hull.Group), "");
            var room2 = hull2.Placements.Single(r => r.Spec.Id == "r-hall");
            Near("F7 the moved diorama (anchor z −1)", ModelPlacement.Measure(room2.Node!, Transform3D.Identity).GetCenter().Z, -1);
            Expect("F7 fresh cuts, switch off at fade 0", hull2.Fade.Fade == 0 && hull2.Placements.Single(r => r.IsBuilding).Cut is { CutoutsOn: false }, "");

            return $"fidelity F1..F7 ok (neutralised {builder.Models.Neutralized}, {stats.CutSummary()}, tiers {string.Join(",", tiers)}, "
                   + $"re-datum {redatum.Redatumed}/{redatum.Relifted}, remounted {string.Join(",", remounted)})";
        }
        finally
        {
            builder.Models?.FreeAll();
            world.QueueFree();
        }
    }

    private static MeshInstance3D? FirstMesh(Node n)
    {
        if (n is MeshInstance3D mi) return mi;
        foreach (var c in n.GetChildren())
            if (FirstMesh(c) is { } m) return m;
        return null;
    }

    private static void NearPlane(string what, CutPlaneData? p, double nx, double ny, double nz, double c)
        => Expect(what, p is { } q && Math.Abs(q.Normal.X - nx) < 1e-5 && Math.Abs(q.Normal.Y - ny) < 1e-5
                         && Math.Abs(q.Normal.Z - nz) < 1e-5 && Math.Abs(q.Constant - c) < 1e-4,
                  p is { } r ? $"({r.Normal.X},{r.Normal.Y},{r.Normal.Z}) {r.Constant}" : "null");

    private static void Near(string what, double got, double want)
        => Expect(what, Math.Abs(got - want) < 1e-4, $"got {got}, expected {want}");

    private static void Eq(string what, int got, int want) => Expect(what, got == want, $"got {got}, expected {want}");

    private static void Expect(string what, bool ok, string detail)
    {
        if (!ok) throw new InvalidOperationException($"fidelity {what}: {detail}");
    }
}
