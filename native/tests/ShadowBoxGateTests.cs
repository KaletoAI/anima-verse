using System;
using AnimaNative.Sky;
using Xunit;

namespace AnimaNative.Tests;

/// <summary>
/// Task 26c: the browser's shadow-caster prism (<see cref="ShadowBoxGate"/>). Hand derivation at the noon offset
/// (0, 80, 25) around the origin:
///   z = (0, 80, 25)/√7025 = (0, 0.954480, 0.298275); x = normalize((0,1,0) × z) = (1, 0, 0); y = z × x = (0, 0.298275, −0.954480);
///   |offset| = √7025 = 83.815273; with the 8 m margin: half 78, z from 83.815273 − 300 − 8 = −224.184727 to
///   83.815273 − 0.5 + 8 = 91.315273.
/// </summary>
public class ShadowBoxGateTests
{
    private static readonly (double, double, double) Zero = (0, 0, 0);
    private static readonly ShadowBoxGate.Box Noon = ShadowBoxGate.Of(Zero, (0, 80, 25));

    private static bool Point((double, double, double) c) => ShadowBoxGate.Overlaps(Noon, c, Zero, Zero, Zero);

    [Fact]
    public void PrismOfTheNoonSun()
    {
        Assert.Equal(78, Noon.Half, 12);
        Assert.Equal(-224.184727, Noon.ZLo, 6);
        Assert.Equal(91.315273, Noon.ZHi, 6);
        Assert.Equal(1, Noon.Basis.X.X, 12);
        Assert.Equal(-0.954480, Noon.Basis.Y.Z, 6);
    }

    /// <summary>Along x: a point at 77.9 m is in, 78.1 m is out; a box at 80 m with a 3 m half-axis reaches 77 m: in.</summary>
    [Fact]
    public void LightPlaneXEdge()
    {
        Assert.True(Point((77.9, 0, 0)));
        Assert.False(Point((78.1, 0, 0)));
        Assert.False(Point((-78.1, 0, 0)));
        Assert.True(ShadowBoxGate.Overlaps(Noon, (80, 0, 0), (3, 0, 0), Zero, Zero));
    }

    /// <summary>On the ground towards +z: y = −0.954480·z, so 80 m → −76.358 (in) and 100 m → −95.448 (out).</summary>
    [Fact]
    public void GroundAlongTheSunsDirectionIsStretched()
    {
        Assert.True(Point((0, 0, 80)));
        Assert.False(Point((0, 0, 100)));
    }

    /// <summary>
    /// Towards the sun: a point at 95 m along z is above the near plane (95 &gt; 91.315), but a box with a 5 m half-axis
    /// up (radius on z: 0.954480·5 = 4.772) reaches 90.228: in. 230 m the other way is beyond the far plane.
    /// </summary>
    [Fact]
    public void NearAndFarAlongTheLight()
    {
        var z = Noon.Basis.Z;
        Assert.False(Point((z.X * 95, z.Y * 95, z.Z * 95)));
        Assert.True(ShadowBoxGate.Overlaps(Noon, (z.X * 95, z.Y * 95, z.Z * 95), Zero, (0, 5, 0), Zero));
        Assert.False(Point((-z.X * 230, -z.Y * 230, -z.Z * 230)));
        Assert.True(Point((-z.X * 220, -z.Y * 220, -z.Z * 220)));
    }

    /// <summary>
    /// The re-evaluation threshold: 3 m along x stays, 4.5 m moves; 4.5 m along world z is 4.295 m along y: moves;
    /// 4.5 m straight up is 1.342 m along y: stays.
    /// </summary>
    [Fact]
    public void MovedOnlyBeyondFourMetresInTheLightPlane()
    {
        Assert.False(ShadowBoxGate.Moved(Noon, (3, 0, 0)));
        Assert.True(ShadowBoxGate.Moved(Noon, (4.5, 0, 0)));
        Assert.True(ShadowBoxGate.Moved(Noon, (0, 0, 4.5)));
        Assert.False(ShadowBoxGate.Moved(Noon, (0, 4.5, 0)));
    }

    /// <summary>The margin keeps the browser's own ±70 m box inside the gate while the centre moves up to 4 m: 70 + 4 ≤ 78.</summary>
    [Fact]
    public void MarginCoversTheMoveThreshold()
        => Assert.True(ShadowSnap.HalfM + ShadowBoxGate.MoveM <= ShadowSnap.HalfM + ShadowBoxGate.MarginM);
}
