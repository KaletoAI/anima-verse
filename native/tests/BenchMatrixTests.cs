using System;
using System.Linq;
using AnimaNative.Bench;
using AnimaNative.Scene;
using AnimaNative.Sky;
using Xunit;

namespace AnimaNative.Tests;

/// <summary>
/// Task 26b: the bench matrix's variant list and summary table (<see cref="BenchMatrix"/>), and the distance fog's compute
/// twin (<see cref="FogCompute"/>) against the screen pass it may replace (<see cref="FogPost"/>). Expectations derived by
/// hand next to each case.
/// </summary>
public class BenchMatrixTests
{
    // ---- the matrix ----------------------------------------------------------------------------------------------------

    /// <summary>The task's eleven switches + the baseline at both ends + the fog-compute candidate = 14, in this order.</summary>
    [Fact]
    public void VariantsAreTheTasksListInOrder()
    {
        var names = BenchMatrix.Variants.Select(v => v.Name).ToArray();
        Assert.Equal(new[]
        {
            "baseline", "no-shadow", "no-hemi-extra-lights", "no-fog-pass", "no-veil", "no-backdrop", "no-water-extras",
            "no-mirrors", "no-prop-lights", "no-cut-shader", "terrain-lod-coarse", "shadow-atlas-2048", "fog-compute",
            "baseline-end",
        }, names);
        Assert.All(BenchMatrix.Variants, v => Assert.False(string.IsNullOrWhiteSpace(v.Switches)));
    }

    /// <summary>A subset keeps the matrix order and gets the baseline in front; "" and null are the whole matrix.</summary>
    [Fact]
    public void SelectKeepsOrderAndBaseline()
    {
        Assert.Equal(new[] { "baseline", "no-fog-pass", "fog-compute" },
                     BenchMatrix.Select(" fog-compute ,no-fog-pass").Select(v => v.Name));
        Assert.Same(BenchMatrix.Variants, BenchMatrix.Select(""));
        Assert.Same(BenchMatrix.Variants, BenchMatrix.Select(null));
        var e = Assert.Throws<ArgumentException>(() => BenchMatrix.Select("no-shadow,no-sky"));
        Assert.Contains("no-sky", e.Message);
    }

    /// <summary>
    /// Baseline gpu 21.60, no-fog 19.35 → Δ −2.25; a headless row (gpu null) has no delta; the n/a mark; tris in millions
    /// (6093179 → 6.09).
    /// </summary>
    [Fact]
    public void TableShowsDeltasAgainstTheFirstBaseline()
    {
        var rows = new[]
        {
            new BenchMatrixRow("baseline", 40.86, 22.35, 25.80, 21.60, 352, 6093179, true),
            new BenchMatrixRow("no-fog-pass", 45.10, 20.10, 23.00, 19.35, 351, 6093100, true),
            new BenchMatrixRow("fog-compute", 40.80, 22.40, 25.90, null, 352, 6093179, false),
        };
        Assert.Equal(-2.25, BenchMatrix.GpuDelta(rows[1], rows[0])!.Value, 9);
        Assert.Null(BenchMatrix.GpuDelta(rows[2], rows[0]));
        var lines = BenchMatrix.Table(rows).TrimEnd('\n').Split('\n');
        Assert.Equal(4, lines.Length);
        Assert.StartsWith("variant", lines[0]);
        Assert.Contains("+0.00", lines[1]);
        Assert.Contains("-2.25", lines[2]);
        Assert.Contains("6.09", lines[1]);
        Assert.StartsWith("fog-compute (n/a)", lines[3]);
    }

    // ---- the compute fog ------------------------------------------------------------------------------------------------

    /// <summary>The kernel prints the browser's band and reads/writes in place (no screen copy).</summary>
    [Fact]
    public void KernelCarriesTheBandAndWritesInPlace()
    {
        var code = FogCompute.ShaderCode;
        Assert.StartsWith("#version 450", code);
        Assert.Contains("smoothstep(220.0, 520.0, z)", code);
        Assert.Contains("layout(rgba16f, set = 0, binding = 0) uniform restrict image2D color_image;", code);
        Assert.Contains("imageStore(color_image, px,", code);
        Assert.Contains("if (d <= 0.0) return;", code);
        Assert.DoesNotContain("hint_screen_texture", code);
    }

    /// <summary>
    /// For an OPAQUE pixel the kernel's single mix lands where the screen pass's blend (X·f + S·(1 − f), then the encode)
    /// lands: both are toSrgb(toLinear(mix(toSrgb(S), F, f))) — algebraically, so to 1e-12 at every depth of the band.
    /// </summary>
    [Fact]
    public void ComputeEqualsTheScreenPassOnOpaquePixels()
    {
        var fog = (0.623529, 0.780392, 0.909804);
        var colours = new[] { (0.0, 0.0, 0.0), (0.05, 0.2, 0.5), (0.9, 0.7, 0.01), (1.0, 1.0, 1.0), (0.002, 0.0031, 0.04) };
        foreach (double z in new[] { 0.5, 100, 219.9, 220, 221, 300, 370, 445, 519, 520, 600, 799 })
            foreach (var c in colours)
            {
                double d = FogPost.DepthAt(z);
                var a = FogCompute.Shown(c, d, fog);
                var b = FogPost.Shown(c, d, fog);
                Assert.True(Math.Abs(a.R - b.R) < 1e-12 && Math.Abs(a.G - b.G) < 1e-12 && Math.Abs(a.B - b.B) < 1e-12,
                            $"z {z} colour {c}: {a} vs {b}");
            }
        // Background (depth 0) untouched: the colour's own encode.
        Assert.Equal(FogPost.Shown((0.3, 0.3, 0.3), 0, fog), FogCompute.Shown((0.3, 0.3, 0.3), 0, fog));
    }

    /// <summary>370 m, f = 0.5: the F3 wall bytes (60, 62, 58) under the noon sky (159, 199, 232) → their mean.</summary>
    [Fact]
    public void ComputeGivesTheF3WallBytes()
    {
        static double L(int b) => GodotSrgb.ToLinear(b / 255.0);
        var shown = FogCompute.Shown((L(60), L(62), L(58)), FogPost.DepthAt(370), (159 / 255.0, 199 / 255.0, 232 / 255.0));
        Assert.Equal(109.5, shown.R * 255, 6);
        Assert.Equal(130.5, shown.G * 255, 6);
        Assert.Equal(145.0, shown.B * 255, 6);
    }

    /// <summary>The push block: size, near, far, fog rgb, pad — 8 little-endian floats; 3816 × 1030 → 477 × 129 groups.</summary>
    [Fact]
    public void PushAndGroups()
    {
        var bytes = FogCompute.Push(3816, 1030, 0.2, 800, (0.5, 0.25, 0.125));
        Assert.Equal(FogCompute.PushBytes, bytes.Length);
        var f = Enumerable.Range(0, 8).Select(i => BitConverter.ToSingle(bytes, i * 4)).ToArray();
        Assert.Equal(new[] { 3816f, 1030f, 0.2f, 800f, 0.5f, 0.25f, 0.125f, 0f }, f);
        Assert.Equal((477, 129), FogCompute.Groups(3816, 1030));
        Assert.Equal((1, 1), FogCompute.Groups(1, 1));
        Assert.Equal((0, 0), FogCompute.Groups(0, 0));
    }
}
