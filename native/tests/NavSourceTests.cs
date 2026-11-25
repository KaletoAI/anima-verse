using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json;
using System.Text.Json.Nodes;
using AnimaNative.Nav;
using AnimaNative.Overview;
using AnimaNative.Scatter;
using AnimaNative.Scene;
using AnimaNative.World;
using Xunit;

namespace AnimaNative.Tests;

/// <summary>
/// <see cref="NavSource.Build"/> on the nav world <c>native/fixtures/nav/scene_loc-nav.json</c>. Every expectation is
/// derived by hand in native/fixtures/README.md, section "Nav world", from the table there:
/// <code>
///   location loc-nav at world (100, 0), yaw 0, datum 0 → TileToWorld(lx, lz, ly) = (100 + lx, ly, lz)
///   boundary x −6…6, z −7…4 (a 3 m deep yard south of W1); storeys 0 / 1 at floor_y 0 / 3
///   walls storey 0 (t 0.2, h 3): W1a (−6,−4)→(−3.45,−4), W1b (−2.55,−4)→(6,−4), W2 (−6,4)→(6,4),
///     W3 (−6,−4)→(−6,4), W4 (6,−4)→(6,4), W5 (0,−4)→(0,1.55), W6 (0,2.45)→(0,4)
///   D0 at (0, 2) along (0, 1) width 0.9, rooms [r-a, r-b], inside; D1 at (−3, −4) along (1, 0) width 0.9, [r-a], outside
///   plate storey 1: r-up x 0…6, z −4…4, top 3.0, hole x 1.5…4.0, z −3.8…−2.8; four walls on storey 1 (base 3, h 2.8)
///   stair foot (1, 0, −3.3), head (4.5, 3, −3.3); lift pads storey 0 / 1 centre (5.2, 0 | 3, 3.2), size (1, 0.1, 1)
///   boxes: armchair x 96.6…97.4, y 0…0.9, z −2.4…−1.6; bed x 103.3…104.7, y 0…0.5, z 0.5…2.5;
///          rug x 96…98, y 0…0.02, z 1.25…2.75
/// </code>
/// With r = 0.25 (agent radius) and t = 0.2: a seal is the door gap (half length w/2 = 0.45 along the wall, half depth
/// t/2 = 0.1 across), a threshold has half length w/2 − r = 0.2 and half depth t/2 + r = 0.35; the outer point of an
/// outside door is the threshold centre + outward normal · 0.35. Storey 0's walkable area is the boundary pushed out by
/// r + 0.05 = 0.30. A wall / box whose top is ≤ floor + 0.25 or whose bottom is ≥ floor + 1.8 is no obstacle.
/// </summary>
public class NavSourceTests
{
    private const double Eps = 1e-9;

    private static readonly Lazy<string> FixtureDir = new(() =>
    {
        for (var dir = new DirectoryInfo(AppContext.BaseDirectory); dir is not null; dir = dir.Parent)
        {
            var candidate = Path.Combine(dir.FullName, "native", "fixtures");
            if (Directory.Exists(candidate)) return candidate;
        }
        throw new DirectoryNotFoundException($"no native/fixtures above {AppContext.BaseDirectory}");
    });

    private static JsonNode SceneJson() => JsonNode.Parse(File.ReadAllText(Path.Combine(FixtureDir.Value, "nav", "scene_loc-nav.json")))!;

    private static ScenePayload Parse(JsonNode node)
    {
        using var doc = JsonDocument.Parse(node.ToJsonString());
        return ScenePayload.Parse(doc.RootElement);
    }

    private static readonly TileFrame Frame0 = new(new Vec3(100, 0, 0), 0);

    private static readonly NavPropBox Armchair = new(0, new Vec3(96.6, 0, -2.4), new Vec3(97.4, 0.9, -1.6));
    private static readonly NavPropBox Bed = new(0, new Vec3(103.3, 0, 0.5), new Vec3(104.7, 0.5, 2.5));
    private static readonly NavPropBox Rug = new(0, new Vec3(96, 0, 1.25), new Vec3(98, 0.02, 2.75));
    private static readonly NavPropBox[] Props = { Armchair, Bed, Rug };

    private static NavSourceData Build(JsonNode? scene = null, TileFrame? frame = null, IReadOnlyList<NavPropBox>? props = null,
                                       NavBakeMode mode = NavBakeMode.Polygon)
    {
        var s = Parse(scene ?? SceneJson());
        var f = frame ?? Frame0;
        return NavSource.Build(s, f, PlaceInventory.Compose(s, f, null, null), props ?? Props, true, NavBakeParams.For(mode));
    }

    private static (double MinX, double MaxX, double MinZ, double MaxZ) Bounds(IEnumerable<P2> pts)
    {
        var list = pts.ToList();
        return (list.Min(p => p.X), list.Max(p => p.X), list.Min(p => p.Z), list.Max(p => p.Z));
    }

    private static void AssertBounds(IEnumerable<P2> pts, double minX, double maxX, double minZ, double maxZ, double eps = Eps)
    {
        var b = Bounds(pts);
        Assert.Equal(minX, b.MinX, eps);
        Assert.Equal(maxX, b.MaxX, eps);
        Assert.Equal(minZ, b.MinZ, eps);
        Assert.Equal(maxZ, b.MaxZ, eps);
    }

    private static void AssertEqual(double expected, double actual, double eps = Eps)
        => Assert.True(Math.Abs(expected - actual) <= eps, $"expected {expected}, got {actual}");

    private static void AssertPoint(P2 p, double x, double z, double eps = Eps)
    {
        AssertEqual(x, p.X, eps);
        AssertEqual(z, p.Z, eps);
    }

    private static void AssertVec(Vec3 v, double x, double y, double z)
    {
        AssertEqual(x, v.X);
        AssertEqual(y, v.Y);
        AssertEqual(z, v.Z);
    }

    private static double Shoelace(IReadOnlyList<P2> q)
    {
        double a = 0;
        for (int i = 0; i < q.Count; i++)
        {
            var p = q[i];
            var n = q[(i + 1) % q.Count];
            a += p.X * n.Z - n.X * p.Z;
        }
        return a / 2;
    }

    /// <summary>Corner order (x0, z0) → (x1, z0) → (x1, z1) → (x0, z1), positive shoelace area.</summary>
    private static void AssertQuadOrder(NavThreshold t)
    {
        var (x0, x1, z0, z1) = Bounds(t.Quad);
        Assert.Equal(4, t.Quad.Length);
        AssertPoint(t.Quad[0], x0, z0, 1e-9);
        AssertPoint(t.Quad[1], x1, z0, 1e-9);
        AssertPoint(t.Quad[2], x1, z1, 1e-9);
        AssertPoint(t.Quad[3], x0, z1, 1e-9);
        Assert.True(Shoelace(t.Quad) > 0);
    }

    private static NavStoreySource Storey(NavSourceData d, int level) => d.Storeys.Single(s => s.Level == level);

    private static NavThreshold Threshold(NavSourceData d, int doorway) => d.Thresholds.Single(t => t.Doorway == doorway);

    /// <summary>The obstacle whose outline bounds are exactly these (±1e-9), or null.</summary>
    private static NavObstacle? ObstacleWith(NavStoreySource s, string kind, double minX, double maxX, double minZ, double maxZ)
        => s.Obstacles.FirstOrDefault(o =>
        {
            if (o.Kind != kind) return false;
            var b = Bounds(o.Outline);
            return Math.Abs(b.MinX - minX) < 1e-9 && Math.Abs(b.MaxX - maxX) < 1e-9
                && Math.Abs(b.MinZ - minZ) < 1e-9 && Math.Abs(b.MaxZ - maxZ) < 1e-9;
        });

    private static JsonArray Walls(JsonNode scene) => scene["walls"]!.AsArray();

    /// <summary>The storey-0 wall (by index in the fixture's walls[]) W5 = 5, W6 = 6.</summary>
    private static void SetWallEnd(JsonNode scene, int wall, string end, double x, double z)
        => Walls(scene)[wall]![end] = new JsonArray(x, z);

    [Fact]
    public void StoreysFloorsAndHeights()
    {
        var d = Build();
        Assert.Equal(new[] { 0, 1 }, d.Storeys.Select(s => s.Level).ToArray());
        Assert.False(d.IsEmpty);

        var s0 = Storey(d, 0);
        Assert.Equal(3, s0.Floors.Count);
        // boundary x −6…6, z −7…4 pushed out by 0.30 → world x 93.7…106.3, z −7.3…4.3
        AssertBounds(s0.Floors[0].Outline, 93.7, 106.3, -7.3, 4.3);
        AssertBounds(s0.Floors[1].Outline, 94, 100, -4, 4);   // floor_plan r-a
        AssertBounds(s0.Floors[2].Outline, 100, 106, -4, 4);  // floor_plan r-b
        Assert.All(s0.Floors, f => Assert.Empty(f.Holes));
        AssertEqual(0, s0.FloorY);
        Assert.True(s0.FollowGround);
        Assert.Equal(2, s0.Hulls.Count);
        AssertBounds(s0.Hulls[0], 94, 100, -4, 4);
        AssertBounds(s0.Hulls[1], 100, 106, -4, 4);

        var s1 = Storey(d, 1);
        Assert.Single(s1.Floors);
        AssertBounds(s1.Floors[0].Outline, 100, 106, -4, 4);
        Assert.Single(s1.Floors[0].Holes);
        AssertBounds(s1.Floors[0].Holes[0], 101.5, 104, -3.8, -2.8);
        AssertEqual(3.0, s1.FloorY);
        Assert.False(s1.FollowGround);
        Assert.Empty(s1.Hulls);
    }

    [Fact]
    public void ObstacleCountsPerStorey()
    {
        var d = Build();
        var s0 = Storey(d, 0);
        Assert.Equal(7, s0.Obstacles.Count(o => o.Kind == "wall"));
        Assert.Equal(2, s0.Obstacles.Count(o => o.Kind == "seal"));
        Assert.Equal(2, s0.Obstacles.Count(o => o.Kind == "prop"));
        Assert.Equal(11, s0.Obstacles.Count);
        var s1 = Storey(d, 1);
        Assert.Equal(4, s1.Obstacles.Count);
        Assert.All(s1.Obstacles, o => Assert.Equal("wall", o.Kind));
    }

    [Fact]
    public void PartyWallRectangle()
    {
        // W5 (0,−4)→(0,1.55), half thickness 0.1, no end caps → x 99.9…100.1, z −4…1.55, y 0…3
        var w5 = ObstacleWith(Storey(Build(), 0), "wall", 99.9, 100.1, -4, 1.55);
        Assert.NotNull(w5);
        AssertEqual(0, w5!.BottomY);
        AssertEqual(3, w5.TopY);
    }

    [Fact]
    public void DoorSealAndThreshold()
    {
        var d = Build();
        // seal D0: at (100, 2), ±0.45 along z, ±0.1 across x
        Assert.NotNull(ObstacleWith(Storey(d, 0), "seal", 99.9, 100.1, 1.55, 2.45));
        var t0 = Threshold(d, 0);
        Assert.Equal(0, t0.Level);
        AssertBounds(t0.Quad, 99.65, 100.35, 1.8, 2.2);   // ±0.35 across, ±0.2 along
        AssertEqual(0, t0.Y);
        Assert.Equal(new[] { "r-a", "r-b" }, t0.Rooms);
        Assert.False(t0.Outside);
        Assert.Null(t0.OuterPoint);
    }

    [Fact]
    public void OutsideDoorThreshold()
    {
        var d = Build();
        Assert.NotNull(ObstacleWith(Storey(d, 0), "seal", 96.55, 97.45, -4.1, -3.9));
        var t1 = Threshold(d, 1);
        AssertBounds(t1.Quad, 96.8, 97.2, -4.35, -3.65);
        Assert.Equal(new[] { "r-a" }, t1.Rooms);
        Assert.True(t1.Outside);
        Assert.NotNull(t1.OuterPoint);
        AssertPoint(t1.OuterPoint!.Value, 97, -4.35);   // (97, −4) + (0, −1)·0.35
    }

    [Fact]
    public void OutsideDoorWithoutNormalUsesAlong()
    {
        var scene = SceneJson();
        scene["doorways"]![1]!.AsObject().Remove("outward_normal");
        var d = Build(scene);
        var t1 = Threshold(d, 1);
        Assert.True(t1.Outside);
        // along (1, 0) → (along.z, −along.x) = (0, −1)
        AssertPoint(t1.OuterPoint!.Value, 97, -4.35);
        Assert.Null(Threshold(d, 0).OuterPoint);
    }

    [Fact]
    public void BoundaryOffsetLShape()
    {
        var l = new[] { new P2(0, 0), new P2(6, 0), new P2(6, 3), new P2(3, 3), new P2(3, 6), new P2(0, 6) };
        var expected = new[] { new P2(-0.3, -0.3), new P2(6.3, -0.3), new P2(6.3, 3.3), new P2(3.3, 3.3), new P2(3.3, 6.3), new P2(-0.3, 6.3) };

        var (ring, ok) = NavSource.OffsetRing(l, 0.3);
        Assert.True(ok);
        Assert.Equal(expected.Length, ring.Length);
        for (int i = 0; i < expected.Length; i++) AssertPoint(ring[i], expected[i].X, expected[i].Z);

        var (back, okBack) = NavSource.OffsetRing(l.Reverse().ToArray(), 0.3);
        Assert.True(okBack);
        Assert.Equal(expected.Length, back.Length);
        for (int i = 0; i < expected.Length; i++) AssertPoint(back[i], expected[i].X, expected[i].Z);

        // A notch 0.4 wide (x 2.8…3.2, down to z 2) is narrower than 2·0.3: the pushed-out notch walls cross.
        var notch = new[]
        {
            new P2(0, 0), new P2(6, 0), new P2(6, 6), new P2(3.2, 6), new P2(3.2, 2), new P2(2.8, 2), new P2(2.8, 6), new P2(0, 6),
        };
        var (kept, okNotch) = NavSource.OffsetRing(notch, 0.3);
        Assert.False(okNotch);
        Assert.Equal(notch.Length, kept.Length);
        for (int i = 0; i < notch.Length; i++) AssertPoint(kept[i], notch[i].X, notch[i].Z);

        // In the build the unshifted ring stands and the problem is reported.
        var scene = SceneJson();
        scene["boundary"] = new JsonArray(notch.Select(p => (JsonNode)new JsonArray(p.X - 3, p.Z - 7)).ToArray());
        var d = Build(scene);
        AssertBounds(Storey(d, 0).Floors[0].Outline, 97, 103, -7, -1);   // tile x −3…3, z −7…−1
        Assert.Contains(new NavProblem("boundary_offset", -1), d.Problems);
    }

    [Fact]
    public void ThresholdQuadOrder()
    {
        var d = Build();
        AssertQuadOrder(Threshold(d, 0));
        AssertQuadOrder(Threshold(d, 1));
    }

    [Fact]
    public void NarrowDoorHasSealNoThreshold()
    {
        var scene = SceneJson();
        scene["doorways"]![0]!["width_m"] = 0.45;
        SetWallEnd(scene, 5, "to", 0, 1.775);
        SetWallEnd(scene, 6, "from", 0, 2.225);
        var d = Build(scene);
        var s0 = Storey(d, 0);
        Assert.Equal(2, s0.Obstacles.Count(o => o.Kind == "seal"));
        Assert.NotNull(ObstacleWith(s0, "seal", 99.9, 100.1, 1.775, 2.225));
        Assert.Single(d.Thresholds);
        Assert.Equal(1, d.Thresholds[0].Doorway);
        Assert.Equal(new[] { new NavProblem("door_too_narrow", 0) }, d.Problems.ToArray());
    }

    [Fact]
    public void DoorWithoutWallIsOpenFloor()
    {
        var scene = SceneJson();
        Walls(scene).RemoveAt(6);
        Walls(scene).RemoveAt(5);
        var d = Build(scene);
        var s0 = Storey(d, 0);
        var seal = Assert.Single(s0.Obstacles, o => o.Kind == "seal");
        AssertBounds(seal.Outline, 96.55, 97.45, -4.1, -3.9);
        var t = Assert.Single(d.Thresholds);
        Assert.Equal(1, t.Doorway);
        Assert.Empty(d.Problems);
    }

    [Fact]
    public void OverlappingPlatesKeepCoveredHoleOpen()
    {
        var scene = SceneJson();
        var second = scene["plates"]![0]!.DeepClone();
        second["holes"] = new JsonArray();
        second["top_y"] = 3.02;
        scene["plates"]!.AsArray().Add(second);
        var s1 = Storey(Build(scene), 1);
        Assert.Equal(2, s1.Floors.Count);
        Assert.All(s1.Floors, f => Assert.Empty(f.Holes));
        AssertEqual(3.02, s1.FloorY);   // the highest top of the storey
    }

    [Fact]
    public void CorridorIsFloor()
    {
        var scene = SceneJson();
        scene["corridors"] = new JsonArray(new JsonObject
        {
            ["room_id"] = "__floor__1", ["level"] = 1, ["anchor"] = new JsonArray(3, 3.5),
            ["outline"] = new JsonArray(new JsonArray(0, 3), new JsonArray(6, 3), new JsonArray(6, 4), new JsonArray(0, 4)),
        });
        var s1 = Storey(Build(scene), 1);
        Assert.Equal(2, s1.Floors.Count);
        AssertBounds(s1.Floors[1].Outline, 100, 106, 3, 4);
    }

    [Fact]
    public void StairAndElevatorLinks()
    {
        var d = Build();
        Assert.Equal(2, d.Links.Count);
        var stairs = d.Links[0];
        Assert.Equal(65536UL, stairs.Owner);
        Assert.Equal("stairs", stairs.Kind);
        AssertVec(stairs.Start, 101, 0, -3.3);
        AssertVec(stairs.End, 104.5, 3, -3.3);
        Assert.Equal(0, stairs.FromLevel);
        Assert.Equal(1, stairs.ToLevel);
        AssertEqual(0, stairs.EnterCost);

        var lift = d.Links[1];
        Assert.Equal(131200UL, lift.Owner);
        Assert.Equal("elevator", lift.Kind);
        AssertVec(lift.Start, 105.2, 0.05, 3.2);
        AssertVec(lift.End, 105.2, 3.05, 3.2);
        Assert.Equal(0, lift.FromLevel);
        Assert.Equal(1, lift.ToLevel);
        AssertEqual(20, lift.EnterCost);
    }

    [Fact]
    public void FlatAndOverheadPropsAreNoObstacles()
    {
        var lamp = new NavPropBox(0, new Vec3(102, 1.9, -1), new Vec3(102.5, 2.2, -0.5));
        var s0 = Storey(Build(props: new[] { Armchair, Bed, Rug, lamp }), 0);
        var props = s0.Obstacles.Where(o => o.Kind == "prop").ToList();
        Assert.Equal(2, props.Count);
        Assert.Null(ObstacleWith(s0, "prop", 96, 98, 1.25, 2.75));          // rug: top 0.02 ≤ 0.25
        Assert.Null(ObstacleWith(s0, "prop", 102, 102.5, -1, -0.5));        // lamp: bottom 1.9 ≥ 1.8
        var bed = ObstacleWith(s0, "prop", 103.3, 104.7, 0.5, 2.5);
        Assert.NotNull(bed);
        AssertEqual(0, bed!.BottomY);
        AssertEqual(0.5, bed.TopY);
    }

    [Fact]
    public void YawTurnsThresholdIntoWorld()
    {
        // yaw π/2: TileToWorld(lx, lz) = (100 + lz, ·, −lx); T0 local x −0.35…0.35, z 1.8…2.2
        var d = Build(frame: new TileFrame(new Vec3(100, 0, 0), Math.PI / 2));
        var t0 = Threshold(d, 0);
        AssertBounds(t0.Quad, 101.8, 102.2, -0.35, 0.35);
        AssertQuadOrder(t0);
    }

    [Fact]
    public void FingerprintStableAndSensitive()
    {
        var a = Build();
        var b = Build();
        Assert.Equal(a.Fingerprint, b.Fingerprint);
        Assert.Matches("^[0-9a-f]{64}$", a.Fingerprint);
        var moved = new NavPropBox(0, new Vec3(96.61, 0, -2.4), new Vec3(97.41, 0.9, -1.6));
        Assert.NotEqual(a.Fingerprint, Build(props: new[] { moved, Bed, Rug }).Fingerprint);
        Assert.NotEqual(a.Fingerprint, Build(mode: NavBakeMode.Voxel).Fingerprint);
    }

    [Fact]
    public void LayerAndOwnerEncoding()
    {
        Assert.Equal(1u << 8, NavLayers.ForLevel(0));
        Assert.Equal(1u << 9, NavLayers.ForLevel(1));
        Assert.Equal(1u, NavLayers.ForLevel(-30));
        Assert.Equal(1u << 30, NavLayers.ForLevel(40));
        Assert.Equal(1u << 31, NavLayers.Links);
        Assert.Equal(uint.MaxValue, NavLayers.All);
        Assert.Equal(65536UL, NavLinkOwner.Stairs(0));
        Assert.Equal(131200UL, NavLinkOwner.Elevator(0));
        Assert.True(NavLinkOwner.TryStairs(NavLinkOwner.Stairs(3), out var flight));
        Assert.Equal(3, flight);
        Assert.False(NavLinkOwner.TryStairs(NavLinkOwner.Elevator(0), out _));
        Assert.True(NavLinkOwner.TryElevator(NavLinkOwner.Elevator(-1), out var lower));
        Assert.Equal(-1, lower);
        Assert.False(NavLinkOwner.TryElevator(NavLinkOwner.Stairs(0), out _));
    }

    [Fact]
    public void CellSizeFloor()
    {
        var p = NavBakeParams.Create(NavBakeMode.Voxel, 0.01, 0.01);
        AssertEqual(0.05, p.CellSize);
        AssertEqual(0.05, p.CellHeight);
        Assert.Equal(NavBakeParams.Create(NavBakeMode.Voxel, 0.1, 0.1), NavBakeParams.For(NavBakeMode.Voxel));
        var poly = NavBakeParams.For(NavBakeMode.Polygon);
        AssertEqual(0.05, poly.CellSize);
        AssertEqual(0.1, poly.EdgeConnectionMargin);
        AssertEqual(0.25, NavBakeParams.For(NavBakeMode.Voxel).EdgeConnectionMargin);
        AssertEqual(0.25, poly.AgentRadius);
        AssertEqual(1.8, poly.AgentHeight);
        AssertEqual(0.25, poly.AgentMaxClimb);
        AssertEqual(40, poly.AgentMaxSlopeDeg);
        AssertEqual(0.6, poly.LinkConnectionRadius);
    }
}
