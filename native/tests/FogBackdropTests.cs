using System;
using System.Linq;
using System.Text.Json;
using AnimaNative.Sky;
using Xunit;

namespace AnimaNative.Tests;

/// <summary>
/// Task 22: the distance-fog screen pass (<see cref="FogPost"/>) and the backdrop ring around the vector-checked ridge
/// profile (<see cref="BackdropSpec"/>, <see cref="BackdropMesh"/>, <see cref="BackdropLook"/>). Every expectation is
/// derived by hand in the comment next to it (also native/fixtures/README.md "Fog" / "Backdrop").
/// </summary>
public class FogBackdropTests
{
    private static double Lin(int b) => GodotSrgb.ToLinear(b / 255.0);

    // ---- fog ------------------------------------------------------------------------------------------------------

    /// <summary>The band of fogConstants.ts, printed from the constants, and the view-depth rebuild.</summary>
    [Fact]
    public void ShaderCarriesTheBrowserBandOnTheViewDepth()
    {
        var code = FogPost.ShaderCode;
        Assert.Contains("smoothstep(220.0, 520.0, -v.z / v.w)", code);
        Assert.Contains("INV_PROJECTION_MATRIX * vec4(SCREEN_UV * 2.0 - 1.0, d, 1.0)", code);
        Assert.Contains("hint_screen_texture", code);
        Assert.Contains("hint_depth_texture", code);
        Assert.Contains("blend_mix", code);
        Assert.Contains("fog_disabled", code);
        Assert.DoesNotContain("FOG =", code);
    }

    /// <summary>
    /// d = n(f − z)/((f − n)z) with n = 0.2, f = 800: z = n → 1, z = f → 0, z = 370 → 0.2·430/(799.8·370) = 2.906132e-4;
    /// <see cref="FogPost.ViewDepth"/> is its inverse.
    /// </summary>
    [Fact]
    public void DepthBufferRoundTrip()
    {
        Assert.Equal(1, FogPost.DepthAt(0.2), 12);
        Assert.Equal(0, FogPost.DepthAt(800), 12);
        Assert.Equal(2.906131938e-4, FogPost.DepthAt(370), 12);
        foreach (var z in new[] { 0.2, 1, 50, 220, 295, 370, 445, 520, 799 })
            Assert.Equal(z, FogPost.ViewDepth(FogPost.DepthAt(z)), 6);
    }

    /// <summary>
    /// fogFactor through the pass (depth buffer → view depth → smoothstep): t = (z − 220)/300; 295 → t ¼ → 1/16·(3 − ½) =
    /// 0.15625; 370 → ½ → 0.5; 445 → ¾ → 9/16·1.5 = 0.84375; ≤ 220 → none (the pass discards), ≥ 520 → 1.
    /// </summary>
    [Theory]
    [InlineData(100, null)]
    [InlineData(220, null)]
    [InlineData(295, 0.15625)]
    [InlineData(370, 0.5)]
    [InlineData(445, 0.84375)]
    [InlineData(520, 1.0)]
    [InlineData(799, 1.0)]
    public void FactorAlongTheBand(double z, double? want)
    {
        var x = FogPost.Fragment((0.5, 0.5, 0.5), FogPost.DepthAt(z), (0.6, 0.7, 0.8));
        if (want is null) Assert.Null(x);
        else
        {
            Assert.NotNull(x);
            Assert.Equal(want.Value, x!.Value.Alpha, 9);
            Assert.Equal(want.Value, Fog.Factor(z), 9);
        }
    }

    /// <summary>Background (depth 0 under reverse Z) is never fogged: the background is the sky already.</summary>
    [Fact]
    public void BackgroundIsLeftAlone() => Assert.Null(FogPost.Fragment((0.1, 0.2, 0.3), 0, (0.6, 0.7, 0.8)));

    /// <summary>
    /// The display-space mix of three: a wall pixel of bytes (60, 62, 58) at 370 m (f = ½) under the noon sky
    /// 9fc7e8 → ((60 + 159)/2, (62 + 199)/2, (58 + 232)/2) = (109.5, 130.5, 145.0) — where a linear mix would show
    /// (122.4, 151.0, 174.3). three's fog colour is LinearToSRGB(SRGBToLinear(byte/255)), within 1e-5 of the byte.
    /// </summary>
    [Fact]
    public void DisplaySpaceMixLikeThree()
    {
        var fog = FogPost.FogSrgb(LinearRgb.FromSrgbHex(0x9fc7e8));
        Assert.Equal(159 / 255.0, fog.R, 4);
        Assert.Equal(199 / 255.0, fog.G, 4);
        Assert.Equal(232 / 255.0, fog.B, 4);
        var shown = FogPost.Shown((Lin(60), Lin(62), Lin(58)), FogPost.DepthAt(370), fog);
        Assert.Equal(109.5, shown.R * 255, 2);
        Assert.Equal(130.5, shown.G * 255, 2);
        Assert.Equal(145.0, shown.B * 255, 2);
    }

    /// <summary>On every opaque pixel the pass reproduces mix(sRGB(colour), fogSrgb, f) — including colours above 1
    /// (three encodes before clamping) and a night fog darker than the pixel (X below 0 is fine on the float buffer).</summary>
    [Fact]
    public void ShownEqualsTheBrowserFormulaEverywhere()
    {
        var night = FogPost.FogSrgb(LinearRgb.FromSrgbHex(0x1a2340));
        var noon = FogPost.FogSrgb(LinearRgb.FromSrgbHex(0x9fc7e8));
        foreach (var fog in new[] { noon, night })
        foreach (var s in new[] { (0.0, 0.0, 0.0), (0.02, 0.5, 1.0), (1.4, 0.9, 0.001), (0.25, 0.25, 0.25) })
        foreach (var z in new[] { 230.0, 300, 370, 480, 519 })
        {
            double f = Fog.Factor(z);
            double Enc(double c) => GodotSrgb.FromLinear(c);
            var shown = FogPost.Shown(s, FogPost.DepthAt(z), fog);
            Assert.Equal(Enc(s.Item1) + (fog.R - Enc(s.Item1)) * f, shown.R, 9);
            Assert.Equal(Enc(s.Item2) + (fog.G - Enc(s.Item2)) * f, shown.G, 9);
            Assert.Equal(Enc(s.Item3) + (fog.B - Enc(s.Item3)) * f, shown.B, 9);
        }
    }

    // ---- backdrop spec ----------------------------------------------------------------------------------------------

    private static JsonElement Map(string json) => JsonDocument.Parse(json).RootElement.Clone();

    [Fact]
    public void SpecReadsTheBlock()
    {
        var spec = BackdropSpec.Of(Map("{\"backdrop\": {\"height_m\": 150, \"seed\": 7, \"arcs\": [[0, 90], [\"x\", 5], 3]}}"))!;
        Assert.Equal(150, spec.HeightM);
        Assert.Equal(7, spec.Seed);
        Assert.Equal(3, spec.Arcs.Count);
        Assert.Equal((0.0, 90.0), spec.Arcs[0]);
        Assert.True(double.IsNaN(spec.Arcs[1].Start) && spec.Arcs[1].End == 5);
        Assert.True(double.IsNaN(spec.Arcs[2].Start) && double.IsNaN(spec.Arcs[2].End));
        Assert.Equal("[150,7,[[0, 90], [\"x\", 5], 3]]", spec.Key);
    }

    /// <summary>A missing block, <c>null</c> or a non-object is the ring being off; junk fields become "unusable".</summary>
    [Fact]
    public void SpecOffAndJunk()
    {
        Assert.Null(BackdropSpec.Of(Map("{}")));
        Assert.Null(BackdropSpec.Of(Map("{\"backdrop\": null}")));
        Assert.Null(BackdropSpec.Of(Map("{\"backdrop\": 5}")));
        var junk = BackdropSpec.Of(Map("{\"backdrop\": {\"height_m\": \"tall\", \"arcs\": 4}}"))!;
        Assert.Null(junk.HeightM);
        Assert.True(double.IsNaN(junk.Seed));
        Assert.Empty(junk.Arcs);
        Assert.Equal("[\"tall\",undefined,4]", junk.Key);
    }

    [Fact]
    public void KeyChangesWithEveryField()
    {
        string K(string b) => BackdropSpec.Of(Map("{\"backdrop\": " + b + "}"))!.Key;
        var a = K("{\"height_m\": 120, \"seed\": 1, \"arcs\": [[0, 360]]}");
        Assert.Equal(a, K("{\"height_m\": 120, \"seed\": 1, \"arcs\": [[0, 360]]}"));
        Assert.NotEqual(a, K("{\"height_m\": 121, \"seed\": 1, \"arcs\": [[0, 360]]}"));
        Assert.NotEqual(a, K("{\"height_m\": 120, \"seed\": 2, \"arcs\": [[0, 360]]}"));
        Assert.NotEqual(a, K("{\"height_m\": 120, \"seed\": 1, \"arcs\": [[0, 180]]}"));
    }

    // ---- backdrop mesh -----------------------------------------------------------------------------------------------

    private static Func<double> Half => () => 0.5;

    /// <summary>
    /// Arc [90, 135], height 120, every draw 0.5, 96 segments (step 3.75°): the start (90°, 0), the nodes strictly inside
    /// i = ceil(90/3.75 + ε) = 25 … floor(135/3.75 − ε) = 35 (11 nodes), the end (135°, 0) → 13 points per ring, 12
    /// quads (no pair has both peaks at 0) → 48 vertices and 72 indices per ring. Node heights: front 120·(0.45 + 0.55·½)
    /// = 87, back 150·0.725 = 108.75; node 25 (93.75°) is 3.75° from the start → taper t = 0.3125, t²(3 − 2t) =
    /// 0.231933594 → 87·0.2319336 = 20.17822266. Node 30 (112.5°) is pts[6] → the peak vertex of quad 6 = vertex 25, at
    /// (380 sin 112.5°, 87, 380 cos 112.5°) = (351.0742224, 87, −145.4197043).
    /// </summary>
    [Fact]
    public void OpenArcStrip()
    {
        var profile = Backdrop.RidgeProfile(1, new[] { (90.0, 135.0) }, 120, Backdrop.Segments, Half);
        var front = BackdropMesh.Ring(profile, 0)!.Value;
        var back = BackdropMesh.Ring(profile, 1)!.Value;
        Assert.Equal(48 * 3, front.Positions.Length);
        Assert.Equal(72, front.Indices.Length);
        Assert.Equal(48 * 3, back.Positions.Length);
        Assert.Equal(72, back.Indices.Length);
        Assert.Equal(351.0742224, front.Positions[25 * 3], 6);
        Assert.Equal(87, front.Positions[25 * 3 + 1], 9);
        Assert.Equal(-145.4197043, front.Positions[25 * 3 + 2], 6);
        Assert.Equal(108.75, back.Positions[25 * 3 + 1], 9);
        // Quad 1 (node 25 → node 26): its first peak is vertex 5.
        Assert.Equal(20.17822266, front.Positions[5 * 3 + 1], 7);
        // Quad 0 starts on the ground at 90° (east): (380, 0, 0).
        Assert.Equal(380, front.Positions[0], 9);
        Assert.Equal(0, front.Positions[1], 9);
        Assert.Equal(0, front.Positions[2], 9);
        // Back ring at 440 m: the start vertex (440, 0, 0).
        Assert.Equal(440, back.Positions[0], 9);
    }

    /// <summary>The full ring [0, 360]: 96 nodes plus the closing first node at +360 → 97 points, 96 quads → 384
    /// vertices and 576 indices per ring.</summary>
    [Fact]
    public void FullRing()
    {
        var profile = Backdrop.RidgeProfile(1, new[] { (0.0, 360.0) }, 120, Backdrop.Segments, Half);
        var ring = BackdropMesh.Ring(profile, 0)!.Value;
        Assert.Equal(384 * 3, ring.Positions.Length);
        Assert.Equal(576, ring.Indices.Length);
    }

    /// <summary>Two arcs meeting at 45°: 13 + 13 points, the join pair (45°, 0) → (45°, 0) skipped → 24 quads = 96 vertices.</summary>
    [Fact]
    public void ArcJoinIsSkipped()
    {
        var profile = Backdrop.RidgeProfile(1, new[] { (0.0, 45.0), (45.0, 90.0) }, 120, Backdrop.Segments, Half);
        Assert.Equal(26, profile.Count(p => p.Layer == 0));
        var ring = BackdropMesh.Ring(profile, 0)!.Value;
        Assert.Equal(96 * 3, ring.Positions.Length);
        Assert.Equal(144, ring.Indices.Length);
    }

    /// <summary>
    /// Every triangle faces the centre for Godot (clockwise front faces: the front normal is −(v1 − v0) × (v2 − v0)).
    /// First triangle of the full ring at 0° (south): v0 = (0, 0, 380), v1 = peak at 3.75°, v2 = peak at 0° → front normal
    /// ∝ (−0.81h, 0, −24.85h), pointing to −z = the centre.
    /// </summary>
    [Fact]
    public void FacesPointInwardForGodot()
    {
        var profile = Backdrop.RidgeProfile(1, new[] { (0.0, 360.0) }, 120, Backdrop.Segments, Half);
        var (p, idx) = BackdropMesh.Ring(profile, 0)!.Value;
        for (int t = 0; t < idx.Length; t += 3)
        {
            double[] V(int i) => new[] { p[idx[i] * 3], p[idx[i] * 3 + 1], p[idx[i] * 3 + 2] };
            var a = V(t);
            var b = V(t + 1);
            var c = V(t + 2);
            double ux = b[0] - a[0], uy = b[1] - a[1], uz = b[2] - a[2];
            double vx = c[0] - a[0], vy = c[1] - a[1], vz = c[2] - a[2];
            double nx = -(uy * vz - uz * vy), nz = -(ux * vy - uy * vx);
            double cx = (a[0] + b[0] + c[0]) / 3, cz = (a[2] + b[2] + c[2]) / 3;
            Assert.True(nx * -cx + nz * -cz > 0, $"triangle {t / 3} faces outward");
        }
    }

    [Fact]
    public void NothingToDrawIsNull()
    {
        Assert.Null(BackdropMesh.Ring(Array.Empty<RidgePoint>(), 0));
        Assert.Null(BackdropMesh.Ring(new[] { new RidgePoint(0, 0, 0), new RidgePoint(10, 0, 0) }, 0));
    }

    // ---- backdrop tint ------------------------------------------------------------------------------------------------

    /// <summary>
    /// mix = min(0.92, 0.30 + 0.55·night + 0.18·layer): front day 0.30, back day 0.48, front night 0.85, back night 1.03 →
    /// 0.92. Front at noon: lerp(linear 5f6d84, linear 9fc7e8, 0.3) = (0.184115979, 0.278385755, 0.403603711).
    /// </summary>
    [Fact]
    public void TintMixesTowardsTheSky()
    {
        Assert.Equal(0.30, BackdropLook.SkyMix(0, 0), 12);
        Assert.Equal(0.48, BackdropLook.SkyMix(1, 0), 12);
        Assert.Equal(0.85, BackdropLook.SkyMix(0, 1), 12);
        Assert.Equal(0.92, BackdropLook.SkyMix(1, 1), 12);
        Assert.Equal(0.30, BackdropLook.SkyMix(0, double.NaN), 12);
        Assert.Equal(0.85, BackdropLook.SkyMix(0, 7), 12);
        var c = BackdropLook.Colour(0, 0, LinearRgb.FromSrgbHex(0x9fc7e8));
        Assert.Equal(0.184115979, c.R, 8);
        Assert.Equal(0.278385755, c.G, 8);
        Assert.Equal(0.403603711, c.B, 8);
        var night = BackdropLook.Colour(1, 1, LinearRgb.FromSrgbHex(0x1a2340));
        Assert.Equal(0.023996577, night.R, 8);
        Assert.Equal(0.034226832, night.G, 8);
        Assert.Equal(0.073764025, night.B, 8);
    }
}
