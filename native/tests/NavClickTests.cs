using AnimaNative.Nav;
using AnimaNative.Overview;
using AnimaNative.Scatter;
using Xunit;

namespace AnimaNative.Tests;

/// <summary>
/// The ground click of plan E2 Task 6 (<see cref="NavClick"/>), every value derived by hand:
///
///   ray o = (98, 10, 5), d = (0, −10, −6) (not normalised; the hit does not depend on the length of d);
///   FloorHit(planeY 0): t = (0 − 10) / −10 = 1   → (98 + 0, 5 − 6·1)   = (98, −1);
///   FloorHit(planeY 3): t = (3 − 10) / −10 = 0.7 → (98, 5 − 6·0.7)     = (98, 0.8);
///   d = (0, 0, −1): dir.Y = 0 ≥ −1e-6 → null; o = (98, −1, 5) below the plane y 0 with d down: t = (0 + 1) / −10 &lt; 0 → null;
///   GroundHit on the slope groundAt(x, z) = −0.5·z, firstY 0: h1 = (98, −1) → ground 0.5 → t = (0.5 − 10) / −10 = 0.95
///   → (98, 5 − 6·0.95) = (98, −0.7); on flat ground (groundAt ≡ 0) GroundHit = FloorHit(0) = (98, −1).
/// </summary>
public class NavClickTests
{
    private static readonly Vec3 O = new(98, 10, 5), D = new(0, -10, -6);

    private static void AssertHit(P2? got, double x, double z)
    {
        Assert.NotNull(got);
        Assert.Equal(x, got!.Value.X, 9);
        Assert.Equal(z, got.Value.Z, 9);
    }

    [Fact]
    public void FloorHitAtGroundLevel() => AssertHit(NavClick.FloorHit(O, D, 0), 98, -1);

    [Fact]
    public void FloorHitAtTheLoft() => AssertHit(NavClick.FloorHit(O, D, 3), 98, 0.8);

    [Fact]
    public void FloorHitScaleFree() => AssertHit(NavClick.FloorHit(O, new Vec3(0, -5, -3), 3), 98, 0.8);

    [Fact]
    public void HorizontalRayMisses() => Assert.Null(NavClick.FloorHit(O, new Vec3(0, 0, -1), 0));

    [Fact]
    public void PlaneBehindTheRayMisses() => Assert.Null(NavClick.FloorHit(new Vec3(98, -1, 5), D, 0));

    [Fact]
    public void GroundHitOnASlope() => AssertHit(NavClick.GroundHit(O, D, 0, (_, z) => -0.5 * z), 98, -0.7);

    [Fact]
    public void GroundHitOnFlatGroundIsTheFloorHit() => AssertHit(NavClick.GroundHit(O, D, 0, (_, _) => 0), 98, -1);

    [Fact]
    public void GroundHitMissesWhenTheFirstCutMisses() => Assert.Null(NavClick.GroundHit(O, new Vec3(0, 0, -1), 0, (_, _) => 0));
}
