using System;
using System.Collections.Generic;
using System.Linq;
using AnimaNative.Figures;
using AnimaNative.Overview;
using AnimaNative.Scatter;
using AnimaNative.Scene;
using Xunit;

namespace AnimaNative.Tests;

/// <summary>
/// <see cref="FigureStands"/> — the lookups around the vector-checked rules (tiles.ts <c>tileGroundY</c>/<c>tileWalkY</c>,
/// <c>bakedFloorAt</c>, <c>roomFloorWorldY</c>/<c>roomBaseFloorY</c>, <c>roomStandY</c>, <c>deriveRoomSpots</c>,
/// <c>deriveCorridorCentres</c>), every number derived by hand here.
///
/// The frame: centre (100, 2, 50), yaw 90° → tileToWorld(lx, lz) = (100 + lz, ·, 50 − lx), worldToTile(x, z) =
/// (50 − z, x − 100). The world ground: g(x, z) = 2 + 0.1·(x − 100).
/// </summary>
public class FigureStandsTests
{
    private static readonly TileFrame Frame = new(new Vec3(100, 2, 50), Math.PI / 2);
    private static double G(double x, double z) => 2 + 0.1 * (x - 100);

    private static P2[] Sq(double x0, double z0, double x1, double z1)
        => new[] { new P2(x0, z0), new P2(x1, z0), new P2(x1, z1), new P2(x0, z1) };

    private static FigureStands Stands() => new() { Frame = Frame, WorldGround = G };

    /// <summary>A 3 × 3 lattice of 50 cm over a 2 × 2 box, placed at the tile origin with scale 1 (max_m 2 / extent 2).</summary>
    private static PlacedSurface Lattice(double level, string roomId, double lift)
        => new("s", new SurfacePlacement(new P2(0, 0), 0, 0.2, 2, "xz"),
               new SceneSurface(1, new P2(-1, -1), 3, 3, Enumerable.Repeat((double?)50, 9).ToArray(),
                                new Vec3(-1, 0, -1), new Vec3(1, 1, 1), new Vec3(2, 1, 2)), lift, level, roomId);

    [Fact]
    public void TheGroundLadderOfATile()
    {
        var s = Stands();
        // No rung answers: the datum 2 against the world — the world wins where higher (103, 50: 2.3), the datum
        // where the world is lower (97, 50: g 1.7 → 2).
        Assert.Equal(2.3, s.TileGroundY(103, 50), 9);
        Assert.Equal(2.0, s.TileGroundY(97, 50), 9);
        // A declaration (hut hull ±1 around the origin, top 0.5) at (100, 50) = local (0, 0): 2 + 0.5 + 0.01.
        s.DeclaredFloors.Add(new DeclaredFloor("hut", 0.5, Sq(-1, -1, 1, 1)));
        Assert.Equal(2.51, s.TileGroundY(100, 50), 9);
        // A storey plate top 3.0 over ±5: out of reach under the default ceiling 1.2 …
        s.WalkPlates.Add(new WalkPlate(3.0, Sq(-5, -5, 5, 5)));
        Assert.Equal(2.3, s.TileGroundY(103, 47), 9);   // local (3, 3): outside the hut, plate refused → 2 vs 2.3
        // … in reach once the building declares walk_y 2.0 (ceiling 3.2): 2 + 3 + 0.01 = 5.01 — but never inside the
        // declaration, which outranks it (still 2.51).
        s.ModelWalkY = 2.0;
        Assert.Equal(5.01, s.TileGroundY(103, 47), 9);
        Assert.Equal(2.51, s.TileGroundY(100, 50), 9);
        // A storey-0 lattice outranks both: at local (0, 0) it answers 0.2 + lift 0.1 + 1·50/100 = 0.8 → world 2.8,
        // + clearance = 2.81. A storey-1 lattice is not the ground's: back to the declaration.
        s.Surfaces.Add(Lattice(0, "hut", 0.1));
        Assert.Equal(2.81, s.TileGroundY(100, 50), 9);
        s.Surfaces[0] = Lattice(1, "hut", 0.1);
        Assert.Equal(2.51, s.TileGroundY(100, 50), 9);
        // A NaN world leaves the tile's answer (standY): at (100, 44) = local (6, 0), off plate and hut, the datum 2.
        s.WorldGround = (_, _) => double.NaN;
        Assert.Equal(2.0, s.TileGroundY(100, 44), 9);
    }

    [Fact]
    public void TheRoomFloorAndItsStandingHeight()
    {
        var s = Stands();
        s.RoomFloors.Add(new("hall", new RoomFloor { Hull = Sq(-2, -1, 2, 3) }));
        s.RoomFloors.Add(new("loft", new RoomFloor { Hull = Sq(-2, -1, 2, 3), Declared = 3.0 }));
        // hall is undeclared: the terrain at local (2, 0) = world (100, 48) → 2, standing 2.01.
        Assert.Equal(2.0, s.RoomFloorAt("hall", 2, 0)!.Value, 9);
        Assert.Equal(2.01, s.RoomStandY("hall", 2, 0)!.Value, 9);
        // loft declares 3.0 over the datum: 5.0, standing 5.01, anywhere.
        Assert.Equal(5.01, s.RoomStandY("loft", 2, 0)!.Value, 9);
        // The room's OWN lattice (any storey) outranks its declaration: 2 + 0.8 = 2.8 at the origin.
        s.Surfaces.Add(Lattice(1, "loft", 0.1));
        Assert.Equal(2.8, s.RoomFloorAt("loft", 0, 0)!.Value, 9);
        // …while the base floor of a marker never reads a lattice.
        Assert.Equal(5.0, s.RoomBaseFloorY(s.RoomFloors[1].Value, 0, 0), 9);
        // An unknown room: no floor; its stand falls back to a known centre, else nothing.
        Assert.Null(s.RoomFloorAt("cellar", 0, 0));
        Assert.Null(s.RoomStandY("cellar", 0, 0));
        s.RoomCenters["cellar"] = new Vec3(1, -1.5, 2);
        Assert.Equal(-1.5, s.RoomStandY("cellar", 0, 0)!.Value, 9);
    }

    [Fact]
    public void DeriveAllWritesCentresSurfacesMarkersAndCorridors()
    {
        var s = Stands();
        s.RoomNames["hall"] = "Hall";
        s.RoomFloors.Add(new("hall", new RoomFloor { Hull = Sq(-2, -1, 2, 3) }));
        var inv = new PlaceInventory();
        var room = new PlaceEntry { Id = "m", RoomId = "hall", Group = "seat", Slots = new[] { new Vec3(100.5, 9, 49), new Vec3(101.5, 9, 49) }, Drop = 0.4, OffsetY = 0.45 };
        var prop = new PlaceEntry { Id = "p", RoomId = "hall", Group = "seat", Slots = new[] { new Vec3(99, 7, 52) }, Fixed = true };
        var byId = new Dictionary<string, PlaceEntry> { ["m"] = room, ["p"] = prop };
        inv.Markers["hall"] = byId;
        inv.Markers["Hall"] = byId;
        inv.Corridors.Add(new CorridorStand { RoomId = "__floor__0", Level = 0, Anchor = new P2(0, -3), Outline = Sq(-5, -5, 5, 5) });
        inv.Corridors.Add(new CorridorStand { RoomId = "__floor__1", Level = 1, Anchor = new P2(0, -3), Outline = Sq(-5, -5, 5, 5), PlateTop = 3.08 });
        var bed = new SpotBox(new Vec3(98, 2.1, 48), new Vec3(100, 2.65, 49.5));      // over 0.55, 2 × 1.5 → lie
        var chair = new SpotBox(new Vec3(101, 2.1, 51), new Vec3(101.5, 2.55, 51.5));  // over 0.45, 0.5 × 0.5 → sit
        var table = new SpotBox(new Vec3(99, 2.1, 50), new Vec3(100, 2.9, 51));        // over 0.8 → nothing
        s.DeriveAll(id => id == "hall" ? new[] { bed, chair, table } : Array.Empty<SpotBox>(), inv);

        // The centre: the centroid (0, 1) of the hull lies inside → world (101, ·, 50), floor = g(101) = 2.1, + 0.01.
        Assert.Equal(new RoomRect(0, 1, 4, 4), s.RoomRects["hall"]);
        AssertNear(new Vec3(101, 2.11, 50), s.RoomCenters["hall"]);
        Assert.Equal(s.RoomCenters["hall"], s.RoomCenters["Hall"]);
        // The surfaces judged against that floor: the bed lies (99, 2.66, 48.75), the chair seats (101.25, 2.56, 51.25).
        AssertNear(new Vec3(99, 2.66, 48.75), s.LieSpots["hall"].Single());
        AssertNear(new Vec3(101.25, 2.56, 51.25), s.SitSpots["Hall"].Single());
        // The room marker: mean slot (101, 49) → local (1, 1) → base floor g(101) = 2.1, − 0.4 + 0.45 = 2.15, both slots,
        // in place; the prop marker keeps its 7.
        Assert.All(room.Slots, p => Assert.Equal(2.15, p.Y, 9));
        Assert.Equal(7, prop.Slots[0].Y);
        // The corridors: storey 1 on its plate (2 + 3.08 + 0.01 = 5.09), storey 0 on the ground ladder at world
        // (97, 50): standY(2, 1.7) = 2. Both at tileToWorld(0, −3) = (97, ·, 50).
        AssertNear(new Vec3(97, 2, 50), s.RoomCenters["__floor__0"]);
        AssertNear(new Vec3(97, 5.09, 50), s.RoomCenters["__floor__1"]);

        // An empty pass keeps the old surface lists (the browser's put() never clears).
        s.DeriveAll(_ => Array.Empty<SpotBox>(), inv);
        Assert.Single(s.LieSpots["hall"]);
    }

    private static void AssertNear(Vec3 want, Vec3 got)
    {
        Assert.Equal(want.X, got.X, 9);
        Assert.Equal(want.Y, got.Y, 9);
        Assert.Equal(want.Z, got.Z, 9);
    }
}
