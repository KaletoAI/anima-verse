using System;
using System.Collections.Generic;
using System.Linq;
using AnimaNative.Nav;
using AnimaNative.Overview;
using AnimaNative.Scatter;
using Xunit;

namespace AnimaNative.Tests;

/// <summary>
/// <see cref="PropFootprint.Of"/> on prisms built here (band 0.25…1.8, cell 0.05). Hand derivations in
/// native/fixtures/README.md, section "Nav world" ("Prop footprints"):
/// <code>
///   box 1.6 × 0.9 × 0.75 turned 30° → one rectangle = the box's own corners (the grid starts at the box's own minimum and
///     ends at its maximum: no raster growth), y 0.25…0.75, area 1.44
///   L sofa, bars 2.6 × 0.9 and 0.9 × 2.0, h 0.85, one piece → covers the L (area 3.33), the free inner corner
///     x −0.4…1.3, z −0.1…1 stays free except at most one 0.05 cell along its two seat fronts
///   rug y 0…0.02, lamp y 1.9…2.2 → null; a table (top 0.72…0.75 over 1.2 × 0.8, four 5 cm legs) → one 1.2 × 0.8 rectangle
///   a cabinet of four upright sides only (0.6 × 0.4, y 0…2) → its inside filled: one 0.6 × 0.4 rectangle, y 0.25…1.8
/// </code>
/// </summary>
public class PropFootprintTests
{
    private const double Low = 0.25, High = 1.8;

    private static P2 Turn(P2 q, double deg, P2 at)
    {
        double a = deg * Math.PI / 180, c = Math.Cos(a), s = Math.Sin(a);
        return new P2(at.X + c * q.X - s * q.Z, at.Z + s * q.X + c * q.Z);
    }

    /// <summary>The ring extruded from y0 to y1 (sides as two triangles per edge, caps as fans), turned by deg about at.</summary>
    private static List<Vec3> Prism(P2[] ring, double y0, double y1, double deg = 0, P2 at = default, bool caps = true)
    {
        var w = ring.Select(q => Turn(q, deg, at)).ToArray();
        var tris = new List<Vec3>();
        for (int i = 0; i < w.Length; i++)
        {
            var a = w[i];
            var b = w[(i + 1) % w.Length];
            tris.AddRange(new[] { new Vec3(a.X, y0, a.Z), new Vec3(b.X, y0, b.Z), new Vec3(b.X, y1, b.Z) });
            tris.AddRange(new[] { new Vec3(a.X, y0, a.Z), new Vec3(b.X, y1, b.Z), new Vec3(a.X, y1, a.Z) });
        }
        if (caps)
            for (int i = 1; i + 1 < w.Length; i++)
                foreach (var y in new[] { y0, y1 })
                    tris.AddRange(new[] { new Vec3(w[0].X, y, w[0].Z), new Vec3(w[i].X, y, w[i].Z), new Vec3(w[i + 1].X, y, w[i + 1].Z) });
        return tris;
    }

    private static P2[] Rect(double x0, double z0, double x1, double z1)
        => new[] { new P2(x0, z0), new P2(x1, z0), new P2(x1, z1), new P2(x0, z1) };

    private static P2 Axis(double deg) => Turn(new P2(1, 0), deg, default);

    private static bool InConvex(P2[] ring, P2 p)
    {
        for (int i = 0; i < ring.Length; i++)
        {
            var a = ring[i];
            var b = ring[(i + 1) % ring.Length];
            if ((b.X - a.X) * (p.Z - a.Z) - (b.Z - a.Z) * (p.X - a.X) < -1e-9) return false;
        }
        return true;
    }

    private static bool Covered(PropFootprint.Result r, P2 p) => r.Outlines.Any(o => InConvex(o, p));

    [Theory]
    [InlineData(0)]
    [InlineData(30)]
    [InlineData(-30)]
    [InlineData(45)]
    public void TurnedBoxIsItsOwnRectangle(double deg)
    {
        var at = new P2(2, 3);
        var box = Rect(-0.8, -0.45, 0.8, 0.45);
        var r = PropFootprint.Of(Prism(box, 0, 0.75, deg, at), Axis(deg), Low, High);
        Assert.NotNull(r);
        var o = Assert.Single(r!.Outlines);
        foreach (var corner in box.Select(q => Turn(q, deg, at)))
            Assert.Contains(o, q => Math.Abs(q.X - corner.X) < 1e-9 && Math.Abs(q.Z - corner.Z) < 1e-9);
        Assert.Equal(1.44, r.Area, 9);
        Assert.Equal(0.25, r.BottomY, 12);
        Assert.Equal(0.75, r.TopY, 12);
    }

    [Theory]
    [InlineData(0)]
    [InlineData(45)]
    public void OnePieceLSofaKeepsItsInnerCornerFree(double deg)
    {
        var l = new[] { new P2(-1.3, -1), new P2(1.3, -1), new P2(1.3, -0.1), new P2(-0.4, -0.1), new P2(-0.4, 1), new P2(-1.3, 1) };
        var r = PropFootprint.Of(Prism(l, 0, 0.85, deg), Axis(deg), Low, High);
        Assert.NotNull(r);
        // every point of the L is covered, every point more than one cell (0.05) out of it is not
        for (double x = -1.29; x < 1.3; x += 0.1)
            for (double z = -0.99; z < 1; z += 0.1)
            {
                bool inL = (z <= -0.1 && x <= 1.3) || x <= -0.4;
                bool farOut = (x > -0.4 + 0.05 + 1e-6 && z > -0.1 + 0.05 + 1e-6);
                var p = Turn(new P2(x, z), deg, default);
                if (inL) Assert.True(Covered(r!, p), $"L point ({x:0.##}, {z:0.##}) not covered");
                if (farOut) Assert.False(Covered(r!, p), $"inner corner point ({x:0.##}, {z:0.##}) covered");
            }
        Assert.False(Covered(r!, Turn(new P2(0.45, 0.45), deg, default)));   // the centre of the free inner corner
        Assert.InRange(r!.Area, 3.33 - 1e-9, 3.33 + 0.05 * (1.7 + 1.1) + 1e-9);
    }

    [Fact]
    public void RugAndLampHaveNoFootprint()
    {
        Assert.Null(PropFootprint.Of(Prism(Rect(-1, -0.75, 1, 0.75), 0, 0.02), Axis(0), Low, High));
        Assert.Null(PropFootprint.Of(Prism(Rect(-0.25, -0.25, 0.25, 0.25), 1.9, 2.2), Axis(0), Low, High));
        Assert.Null(PropFootprint.Of(Array.Empty<Vec3>(), Axis(0), Low, High));
    }

    [Fact]
    public void TableTopCoversItsLegs()
    {
        var tris = Prism(Rect(-0.6, -0.4, 0.6, 0.4), 0.72, 0.75);
        foreach (var (x, z) in new[] { (-0.55, -0.35), (0.55, -0.35), (0.55, 0.35), (-0.55, 0.35) })
            tris.AddRange(Prism(Rect(x - 0.025, z - 0.025, x + 0.025, z + 0.025), 0, 0.72));
        var r = PropFootprint.Of(tris, Axis(0), Low, High);
        var o = Assert.Single(r!.Outlines);
        Assert.Equal(0.96, r.Area, 9);
        Assert.Equal(-0.6, o.Min(q => q.X), 9);
        Assert.Equal(0.6, o.Max(q => q.X), 9);
        Assert.Equal(0.25, r.BottomY, 12);
        Assert.Equal(0.75, r.TopY, 12);
    }

    [Fact]
    public void CabinetSidesFillTheirInside()
    {
        // four upright sides, no top or bottom in the band: only the perimeter is marked, the row-and-column rule fills it
        var r = PropFootprint.Of(Prism(Rect(0, 0, 0.6, 0.4), 0, 2.0, caps: false), Axis(0), Low, High);
        var o = Assert.Single(r!.Outlines);
        Assert.Equal(0.24, r.Area, 9);
        Assert.Equal(0.25, r.BottomY, 12);
        Assert.Equal(1.8, r.TopY, 12);
        Assert.True(InConvex(o, new P2(0.3, 0.2)));
    }
}
