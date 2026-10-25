using System;
using System.Collections.Generic;
using System.Linq;
using AnimaNative.Overview;
using AnimaNative.Scene;
using AnimaNative.World;
using Xunit;

namespace AnimaNative.Tests;

/// <summary>
/// The accumulating verifier (§ B5a, the browser's <c>Verifier</c> report around the vector-checked cores) and the
/// view-state steps of the crossfade. Every expected number is derived by hand in the comments; the per-function
/// cores themselves are pinned by shared/test-vectors/scene_verify.json and scene_view.json.
/// </summary>
public class SceneVerifierTests
{
    private static SceneWall Wall(double fx, double fz, double tx, double tz, double baseY = 0, double h = 3, double t = 0.2)
        => new(0, (fx, fz), (tx, tz), baseY, h, t, false, false, false);

    /// <summary>The world AABB of a box given by its tile-local corners, turned by +yaw about the tile centre (tileToWorld).</summary>
    private static VBox WorldBox(Vec3 min, Vec3 max, Vec3 origin, double yaw, double dy = 0)
    {
        double c = Math.Cos(yaw), s = Math.Sin(yaw);
        var pts = new List<Vec3>();
        foreach (var x in new[] { min.X, max.X })
        foreach (var y in new[] { min.Y, max.Y })
        foreach (var z in new[] { min.Z, max.Z })
            pts.Add(new Vec3(origin.X + x * c + z * s, origin.Y + y + dy, origin.Z - x * s + z * c));
        return new VBox(new Vec3(pts.Min(p => p.X), pts.Min(p => p.Y), pts.Min(p => p.Z)),
                        new Vec3(pts.Max(p => p.X), pts.Max(p => p.Y), pts.Max(p => p.Z)));
    }

    [Fact]
    public void WallInAnUnturnedTileHasNoDeviation()
    {
        // Wall (0,0)→(4,0), base 0, height 3, thickness 0.2: local box x 0…4, y 0…3, z −0.1…0.1. The tile centre
        // (10, 2, −5) shifts it to x 10…14, y 2…5, z −5.1…−4.9; in the frame again: base 0, top 3, centre (2, 0).
        var v = new SceneVerifier();
        var w = Wall(0, 0, 4, 0);
        var origin = new Vec3(10, 2, -5);
        v.Primitive(SceneVerifier.WallName(w), WorldBox(new Vec3(0, 0, -0.1), new Vec3(4, 3, 0.1), origin, 0), origin, 0,
                    SceneVerify.WallTargets(w));
        Assert.Equal(4, v.Checked);
        Assert.Empty(v.Rows);
    }

    [Fact]
    public void TurnedTileRecoversTheCentre()
    {
        // The same wall in a tile turned by +30°: the world AABB grows (a turned box), but its CENTRE turns back
        // exactly and the y range is untouched — the four targets stay clean.
        var v = new SceneVerifier();
        var w = Wall(0, 0, 4, 0);
        var origin = new Vec3(-100, 2.91357421875, 50);
        double yaw = 30 * Math.PI / 180;
        v.Primitive("wall:contour@0", WorldBox(new Vec3(0, 0, -0.1), new Vec3(4, 3, 0.1), origin, yaw), origin, yaw,
                    SceneVerify.WallTargets(w));
        Assert.Equal(4, v.Checked);
        Assert.Empty(v.Rows);
    }

    [Fact]
    public void LiftedWallGivesTwoRows()
    {
        // The measured box 5 cm too high: base_y 0.05 against 0 and top_y 3.05 against 3 — both beyond 0.01 m,
        // delta 0.05 each; the centre stays clean. Rounded to the millimetre like the browser's r3.
        var v = new SceneVerifier();
        var w = Wall(0, 0, 4, 0);
        var origin = new Vec3(0, 0, 0);
        v.Primitive(SceneVerifier.WallName(w), WorldBox(new Vec3(0, 0, -0.1), new Vec3(4, 3, 0.1), origin, 0, dy: 0.05), origin, 0,
                    SceneVerify.WallTargets(w));
        Assert.Equal(4, v.Checked);
        Assert.Equal(new[] { ("wall:contour@0", "base_y", 0.05, 0.0, 0.05), ("wall:contour@0", "top_y", 3.05, 3.0, 0.05) },
                     v.Rows.Select(r => (r.Object, r.Field, r.Actual, r.Target, r.Delta)));
        var report = v.Report("loc-x");
        Assert.Equal("[verify] loc-x: 2 deviation(s) in 4 checked numbers (models 0/0, 0 skipped), tolerance 0.01 m", report.Headline());
        Assert.Equal(new[]
        {
            "  object          field   actual  target  delta",
            "  wall:contour@0  base_y    0.05       0   0.05",
            "  wall:contour@0  top_y     3.05       3   0.05",
        }, report.Table());
    }

    [Fact]
    public void PlateTargetsBodyAndBareSurface()
    {
        // A body (thickness 0.2, top 3): top_y 3 and bottom_y 2.8 → 2 numbers; a bare surface (thickness 0): top only.
        var body = new ScenePlate(1, new[] { (-4.0, -3.0), (4.0, -3.0), (4.0, 3.0) }, Array.Empty<(double, double)[]>(), 3, 0.2);
        var bare = new ScenePlate(0, new[] { (-4.0, -3.0), (4.0, -3.0), (4.0, 3.0) }, Array.Empty<(double, double)[]>(), 0.02, 0) { RoomId = "r" };
        var v = new SceneVerifier();
        var o = new Vec3(0, 0, 0);
        v.Primitive(SceneVerifier.PlateName(body), new VBox(new Vec3(-4, 2.8, -3), new Vec3(4, 3, 3)), o, 0, SceneVerify.PlateTargets(body));
        v.Primitive(SceneVerifier.PlateName(bare), new VBox(new Vec3(-4, 0.02, -3), new Vec3(4, 0.02, 3)), o, 0, SceneVerify.PlateTargets(bare));
        Assert.Equal(3, v.Checked);
        Assert.Empty(v.Rows);
        Assert.Equal("plate:level@1", SceneVerifier.PlateName(body));
        Assert.Equal("plate:r@0", SceneVerifier.PlateName(bare));
    }

    [Fact]
    public void SkippedSpecIsADeviation()
    {
        // verify.skip: one number (`geladen` 0 against 1, delta −1), counted as skipped.
        var spec = new SceneModelSpec("prop", "crate", "shell", false, new(), null, double.NaN, 0, 0, 0, 45, 1, "xyz", null, 2, 2, 0);
        var v = new SceneVerifier { Total = 2, Placed = 1 };
        v.Skip(spec);
        Assert.Equal(1, v.Checked);
        Assert.Equal(1, v.Skipped);
        var row = Assert.Single(v.Rows);
        Assert.Equal(("prop:crate", "geladen", 0.0, 1.0, -1.0), (row.Object, row.Field, row.Actual, row.Target, row.Delta));
        Assert.Equal("[verify] loc-house: 1 deviation(s) in 1 checked numbers (models 1/2, 1 skipped), tolerance 0.01 m",
                     v.Report("loc-house").Headline());
    }

    [Fact]
    public void CleanReportHeadline()
    {
        var v = new SceneVerifier { Total = 3, Placed = 3 };
        v.Check("prop:a", "bottom_y", 0.004, 0);   // within 0.01 m
        var r = v.Report("loc-yard");
        Assert.True(r.Clean);
        Assert.Empty(r.Table());
        Assert.Equal("[verify] loc-yard: 1 numbers checked, no deviation > 0.01 m (models 3/3)", r.Headline());
    }

    [Fact]
    public void SurfaceBoxDeviationIsTheWorstOfFour()
    {
        // Bake box (−0.5, 0, −0.5)…(0.5, 1, 0.5); measured (−0.5, 0.02, −0.5)…(0.5, 1.02, 0.53): sizes 1, 1, 1.03 against
        // 1, 1, 1 → 0, 0, 0.03; bottom 0.02 against 0 → 0.02. Worst: 0.03.
        var s = new SceneSurface(0.5, new Scatter.P2(-0.5, -0.5), 3, 2, new double?[6], new Vec3(-0.5, 0, -0.5), new Vec3(0.5, 1, 0.5), new Vec3(1, 1, 1));
        double dev = SceneVerifier.SurfaceBoxDeviation(new VBox(new Vec3(-0.5, 0.02, -0.5), new Vec3(0.5, 1.02, 0.53)), s);
        Assert.Equal(0.03, dev, 12);
    }

    [Fact]
    public void OcclusionStepFollowsTheEightPerSecondLerp()
    {
        // t = 1 − e^(−8/60) = 0.12482668095705252.
        Assert.Equal(0, SceneView.OcclusionStep(0, false, 1 / 60.0));
        Assert.Equal(0.12482668095705252, SceneView.OcclusionStep(0, true, 1 / 60.0), 12);
        // Fading back: 0.5 · (1 − t) = 0.43758665952147374; a value that lands under 0.02 snaps to 0.
        Assert.Equal(0.43758665952147374, SceneView.OcclusionStep(0.5, false, 1 / 60.0), 12);
        Assert.Equal(0, SceneView.OcclusionStep(0.0225, false, 1 / 60.0));   // 0.0225 · 0.875 = 0.0197 < 0.02
        // One second hidden: 1 − e^(−8) = 0.9996645373720975 → past 0.95, the group is hidden.
        double o = 0;
        for (int i = 0; i < 60; i++) o = SceneView.OcclusionStep(o, true, 1 / 60.0);
        Assert.Equal(0.9996645373720975, o, 9);
        Assert.True(o >= SceneView.OccludedHideAt);
    }

    [Fact]
    public void CrossfadeTiming()
    {
        // fadeStep at 60 fps: f_n = 1 − e^(−4·n/60). After 6 frames (0.1 s) 0.32967995396436056 — the roof at
        // 1 − 1.4·f = 0.5384480644498952, the shell still casts; after 45 frames (0.75 s) 1 − e^(−3) = 0.950213 —
        // past 0.95, the roof is hidden: the browser's "95 % in about 0.75 s".
        double f = 0;
        for (int i = 0; i < 6; i++) f = SceneView.FadeStep(f, 1, 1 / 60.0);
        Assert.Equal(0.32967995396436056, f, 12);
        var look = SceneView.FadeOpacities(f);
        Assert.Equal(0.5384480644498952, look.Roof, 12);
        Assert.True(look.ShellShadow && look.InteriorVisible && look.RoofVisible && !look.LabelsVisible);
        for (int i = 6; i < 45; i++) f = SceneView.FadeStep(f, 1, 1 / 60.0);
        Assert.Equal(0.950212931632136, f, 12);
        look = SceneView.FadeOpacities(f);
        Assert.False(look.RoofVisible);
        Assert.Equal(0, look.Roof);
    }

    [Fact]
    public void InstanceTransparencyCombinesFadeAndOcclusion()
    {
        Assert.Equal(0, SceneView.InstanceTransparency(1, 0));          // opaque: the opaque pass
        Assert.Equal(0, SceneView.InstanceTransparency(0.9995, 0));     // fade alpha ≥ 0.999 → Godot draws it opaque anyway
        Assert.Equal(0.5, SceneView.InstanceTransparency(0.5, 0), 12);
        Assert.Equal(0.25, SceneView.InstanceTransparency(1, 0.25), 12);
        // Roof 0.5384480644498952 under occlusion 0.5: 1 − 0.26922403222494760 = 0.7307759677750524.
        Assert.Equal(0.7307759677750524, SceneView.InstanceTransparency(0.5384480644498952, 0.5), 12);
        Assert.Equal(1, SceneView.InstanceTransparency(0, 0));
    }
}
