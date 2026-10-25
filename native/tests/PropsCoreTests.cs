using System;
using System.Collections.Generic;
using System.Linq;
using AnimaNative.Overview;
using AnimaNative.Scatter;
using AnimaNative.Scene;
using AnimaNative.World;
using Xunit;

namespace AnimaNative.Tests;

/// <summary>
/// Hand-derived checks of the native-only parts of Task 18 that no browser vector covers: the reflection view that
/// replaces three's oblique near plane (<see cref="MirrorMath.ReflectionView"/>) and the light pool's per-frame state
/// (<see cref="LightPoolState"/>, which strings together the vector-checked <see cref="PropLights"/> functions).
/// </summary>
public class PropsCoreTests
{
    private const double Eps = 1e-12;

    /// <summary>A 1 × 1 m pane in the plane z = 0 facing +z, centred (0, 1.5, 0).</summary>
    private static readonly Vec3[] Pane = { new(-0.5, 1, 0), new(0.5, 1, 0), new(0.5, 2, 0), new(-0.5, 2, 0) };
    private static readonly Vec3 PanePoint = new(0, 1.5, 0), PaneNormal = new(0, 0, 1);

    private static void Near(double want, double got, double eps = Eps) => Assert.True(Math.Abs(want - got) <= eps, $"expected {want}, got {got}");

    private static void NearV(Vec3 want, Vec3 got) { Near(want.X, got.X); Near(want.Y, got.Y); Near(want.Z, got.Z); }

    [Fact]
    public void ViewerInFrontOfTheMiddle()
    {
        // Eye (0, 1.5, 2): d = 2, mirror image (0, 1.5, −2); the camera looks along +z (back −z), up +y, right = up × back
        // = (−1, 0, 0). Pane corners: r = (x, y − 1.5, 2) → x_c = −x ∈ [−.5, .5], y_c ∈ [−.5, .5] at depth 2 = near.
        var v = MirrorMath.ReflectionView(PanePoint, PaneNormal, Pane, new Vec3(0, 1.5, 2))!.Value;
        NearV(new Vec3(0, 1.5, -2), v.Eye);
        NearV(new Vec3(0, 0, -1), v.Back);
        NearV(new Vec3(0, 1, 0), v.Up);
        NearV(new Vec3(-1, 0, 0), v.Right);
        Near(2, v.Near); Near(2, v.Distance); Near(1, v.Size); Near(0, v.OffsetX); Near(0, v.OffsetY);
        // The centre samples the middle of the image; the corner (−0.5, 2, 0) — the viewer's top RIGHT — the top right.
        var c = MirrorMath.TexCoord(v, PanePoint);
        Near(0.5, c.U); Near(0.5, c.V);
        var tr = MirrorMath.TexCoord(v, new Vec3(-0.5, 2, 0));
        Near(1, tr.U); Near(0, tr.V);
        var bl = MirrorMath.TexCoord(v, new Vec3(0.5, 1, 0));
        Near(0, bl.U); Near(1, bl.V);
    }

    [Fact]
    public void ThePaneSamplesWhereTheCameraSeesTheMirroredPoint()
    {
        // Q = (0.2, 1.7, 1) in front of the mirror, its image Q' = (0.2, 1.7, −1). The viewer at (0, 1.5, 2) sees Q' through
        // P = eye + t·(Q' − eye) with 2 − 3t = 0 → t = 2/3 → P = (2/15, 1.5 + 0.2·2/3, 0). The reflection camera projects
        // Q to u = (2·(−0.2) + 0.5·3)/3 = 1.1/3, v = (0.5·3 − 2·0.2)/3 = 1.1/3; the pane fragment at P must sample there.
        var v = MirrorMath.ReflectionView(PanePoint, PaneNormal, Pane, new Vec3(0, 1.5, 2))!.Value;
        var q = MirrorMath.TexCoord(v, new Vec3(0.2, 1.7, 1));
        var p = MirrorMath.TexCoord(v, new Vec3(2.0 / 15, 1.5 + 0.2 * 2 / 3, 0));
        Near(1.1 / 3, q.U); Near(1.1 / 3, q.V);
        Near(q.U, p.U); Near(q.V, p.V);
    }

    [Fact]
    public void OffAxisViewerShiftsTheWindow()
    {
        // Eye (1, 1.5, 2): image (1, 1.5, −2); x_c = 1 − x ∈ [0.5, 1.5] → window centre +1, size 1.
        var v = MirrorMath.ReflectionView(PanePoint, PaneNormal, Pane, new Vec3(1, 1.5, 2))!.Value;
        NearV(new Vec3(1, 1.5, -2), v.Eye);
        Near(1, v.Size); Near(1, v.OffsetX); Near(0, v.OffsetY); Near(2, v.Near);
    }

    [Fact]
    public void ViewerBehindThePaneTurnsTheNormal()
    {
        // Eye (0, 1.5, −3): the normal turns to (0, 0, −1), d = 3, image (0, 1.5, 3), back +z, right (1, 0, 0).
        var v = MirrorMath.ReflectionView(PanePoint, PaneNormal, Pane, new Vec3(0, 1.5, -3))!.Value;
        NearV(new Vec3(0, 1.5, 3), v.Eye);
        NearV(new Vec3(0, 0, 1), v.Back);
        NearV(new Vec3(1, 0, 0), v.Right);
        Near(3, v.Near);
    }

    [Fact]
    public void AViewerCloserThanTheMinimumNearKeepsTheWindowAngles()
    {
        // d = 0.005 < 0.01: near 0.01 = 2·d, so the 1 m window at d becomes 2 m at the near plane.
        var v = MirrorMath.ReflectionView(PanePoint, PaneNormal, Pane, new Vec3(0, 1.5, 0.005))!.Value;
        Near(MirrorMath.MinNear, v.Near); Near(2, v.Size, 1e-9); Near(0.005, v.Distance);
    }

    [Fact]
    public void NoViewOnThePlaneOrWithoutExtent()
    {
        Assert.Null(MirrorMath.ReflectionView(PanePoint, PaneNormal, Pane, new Vec3(3, 1.5, 0)));
        Assert.Null(MirrorMath.ReflectionView(PanePoint, PaneNormal, new[] { PanePoint }, new Vec3(0, 1.5, 2)));
    }

    [Fact]
    public void AFloorPaneTakesTheNorthAxisAsUp()
    {
        // A pane in y = 0 facing up, eye straight above: world up is parallel to the view axis, so up falls back to
        // (0, 0, −1); back = −n = (0, −1, 0) and right = up × back — still an orthonormal basis.
        var floor = new[] { new Vec3(-1, 0, -1), new Vec3(1, 0, -1), new Vec3(1, 0, 1), new Vec3(-1, 0, 1) };
        var v = MirrorMath.ReflectionView(new Vec3(0, 0, 0), new Vec3(0, 1, 0), floor, new Vec3(0, 5, 0))!.Value;
        NearV(new Vec3(0, -5, 0), v.Eye);
        NearV(new Vec3(0, 0, -1), v.Up);
        NearV(new Vec3(0, -1, 0), v.Back);
        // (0,0,−1) × (0,−1,0) = (0·0 − (−1)(−1), (−1)·0 − 0·0, 0·(−1) − 0·0) = (−1, 0, 0).
        NearV(new Vec3(-1, 0, 0), v.Right);
        Near(2, v.Size); Near(5, v.Near);
    }

    private static ScenePropLight Lamp(double intensity = 2, string when = "always", string flicker = "none", double glow = 0.1)
        => new("#ffb35c", intensity, 4, flicker, when, glow, new P2(0, 0), 2);

    [Fact]
    public void ASlotFadesInOverPointFourSeconds()
    {
        // Register → the next update selects (elapsed starts at .2). The empty slot takes the lamp at gain 0, then
        // +0.2/0.4 per 0.2 s step: 0 → 0.5 → 1. No flicker, always: intensity = 2·gain.
        var pool = new LightPoolState();
        pool.Register(Lamp(), new Vec3(1, 0, 0), "", 0);
        var rooms = new HashSet<string>();
        var focus = new Vec3(0, 0, 0);
        Near(0, pool.Update(0.2, focus, 0, rooms).Slots[0].Intensity);
        Near(1, pool.Update(0.2, focus, 0, rooms).Slots[0].Intensity);
        Near(2, pool.Update(0.2, focus, 0, rooms).Slots[0].Intensity);
        Assert.Equal(new[] { "1" }, pool.Selected);
    }

    [Fact]
    public void EightLampsSixSlotsNearestWin()
    {
        // Lamps 1..8 at x = 1..8 (range 4 → cutoff 34): the nearest six win; after removing lamp 3 the next selection
        // keeps 1, 2, 4, 5, 6 in their slots and lamp 7 takes the freed slot 2.
        var pool = new LightPoolState();
        var ids = Enumerable.Range(1, 8).Select(i => pool.Register(Lamp(), new Vec3(i, 0, 0), "", 0)).ToList();
        var rooms = new HashSet<string>();
        pool.Update(0.2, new Vec3(0, 0, 0), 0, rooms);
        Assert.Equal(new[] { "1", "2", "3", "4", "5", "6" }, pool.Selected);
        Assert.True(pool.Remove(ids[2]));
        Assert.False(pool.Remove(ids[2]));
        pool.Update(0.01, new Vec3(0, 0, 0), 0, rooms);
        Assert.Equal(new[] { "1", "2", "7", "4", "5", "6" }, pool.Selected);
    }

    [Fact]
    public void NightLampsAndHalosFollowTheNightAndTheRoom()
    {
        // A night lamp in room r: at night 0.45 its gain is 0.5 (smoothstep), the halo shows only while r is shown.
        var pool = new LightPoolState();
        pool.Register(Lamp(when: "night"), new Vec3(1, 0, 0), "loc:r", 0);
        var shown = new HashSet<string> { "loc:r" };
        var (_, halos) = pool.Update(0.2, new Vec3(0, 0, 0), 0.45, shown);
        Assert.True(halos.Single().Visible);
        Near(0.5, halos.Single().Opacity);
        Assert.False(pool.Update(0.01, new Vec3(0, 0, 0), 0.45, new HashSet<string>()).Halos.Single().Visible);
        Assert.False(pool.Update(0.01, new Vec3(0, 0, 0), 0.3, shown).Halos.Single().Visible);
    }

    [Fact]
    public void StageScaleIsTheBrowserSunAtItsDefaultAngle()
    {
        // 1 / (0.25 + 2·sin(0.35π)); sin(0.35π) = 0.8910065241883679 → 1 / 2.0320130483767358.
        Near(1 / 2.0320130483767358, Ambience.StageScale);
    }
}
