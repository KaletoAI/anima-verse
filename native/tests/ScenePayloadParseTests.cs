using System;
using System.IO;
using System.Linq;
using System.Text.Json;
using AnimaNative.Scatter;
using AnimaNative.World;
using Xunit;

namespace AnimaNative.Tests;

/// <summary>
/// The whole § B1 payload through <see cref="ScenePayload.Parse"/>, on the hand-written fixtures. The expected
/// values are read off the fixture files by hand (native/fixtures/README.md, "S3c world" → "Parser fields"):
/// every block the browser types in packages/scene-render/src/types.ts must arrive, including the ones no native
/// code draws yet (stairs, markers, doorways, corridors, problems, boundary openings, room openings / overlay /
/// ambience, and on models clip_outline, cut_plane, slots, door, leaf_bbox, light, surface, water, walk_y_world).
/// </summary>
public class ScenePayloadParseTests
{
    private static readonly Lazy<string> FixtureDir = new(() =>
    {
        for (var dir = new DirectoryInfo(AppContext.BaseDirectory); dir is not null; dir = dir.Parent)
        {
            var candidate = Path.Combine(dir.FullName, "native", "fixtures");
            if (Directory.Exists(candidate)) return candidate;
        }
        throw new DirectoryNotFoundException($"no native/fixtures above {AppContext.BaseDirectory}");
    });

    private static ScenePayload Load(string relative)
    {
        using var doc = JsonDocument.Parse(File.ReadAllText(Path.Combine(FixtureDir.Value, relative)));
        return ScenePayload.Parse(doc.RootElement);
    }

    private static void Pt(P2 p, double x, double z)
    {
        Assert.Equal(x, p.X, 12);
        Assert.Equal(z, p.Z, 12);
    }

    [Fact]
    public void TopLevelAndStoreys()
    {
        var s = Load("s3c/scene_loc-open.json");
        Assert.Equal("s3c-open", s.Signature);
        Assert.Equal(1, s.K);
        Assert.Equal(10, s.ExtentM);
        Assert.Equal(3, s.StoreyM);
        Assert.Equal(new[] { (0, 0.0), (1, 3.0) }, s.Levels.Select(l => (l.Level, l.FloorY)));
        Assert.Equal(3, s.FloorY(1));
        Assert.Equal(0, s.FloorY(7));   // an undeclared storey reads 0 (floorYof)
        Assert.Equal(4, s.Boundary!.Length);
        Pt(s.Boundary[2], 5, 5);
        Assert.Equal(1.7, s.Figures!.BaseHeightMWorld);
        Assert.Equal(0.12, s.Figures.StandClearance);
        Assert.False(s.AreaDetail);
    }

    [Fact]
    public void RoomsWithOutlineOpeningsOverlayAmbience()
    {
        var s = Load("s3c/scene_loc-open.json");
        var ground = s.Rooms.Single(r => r.RoomId == "r-ground");
        Assert.Equal(4, ground.Outline.Length);
        Pt(ground.Outline[1], 5, -5);
        var op = Assert.Single(ground.Openings);
        Assert.Equal((3, 0.65, 1.0, 2.1, 0.0, "door", "r-garden", "door:s3c0001", true),
                     (op.Edge, op.At, op.WidthM, op.HeightM, op.SillM, op.Type, op.To, op.PropId, op.Mirrored));
        Assert.Equal(0.6, ground.Ambience!.Daylight);
        Assert.Equal("#ffd9a0", ground.Ambience.Tint);
        Assert.Null(ground.Overlay);

        var garden = s.Rooms.Single(r => r.RoomId == "r-garden");
        Assert.True(garden.AlwaysVisible);
        Pt(garden.Overlay!.Centre, 0, 3);
        Assert.Equal((-5.0, 1.0, 10.0, 4.0, 0.02),
                     (garden.Overlay.RectX, garden.Overlay.RectZ, garden.Overlay.RectW, garden.Overlay.RectD, garden.Overlay.Y));
        Assert.Equal(1, garden.Ambience!.Daylight);
        Assert.Equal("", garden.Ambience.Tint);   // tint null → no tint

        var up = s.Rooms.Single(r => r.RoomId == "r-up");
        Assert.Equal(1, up.Level);
        Assert.Null(up.Ambience);
        Assert.Empty(up.Openings);
    }

    [Fact]
    public void FloorPlanStairsMarkersDoorwaysCorridors()
    {
        var s = Load("s3c/scene_loc-open.json");
        var f = Assert.Single(s.FloorPlan);
        Assert.Equal(("r-ground", "planks", true), (f.RoomId, f.FloorKind, f.Closed));
        Assert.Equal(4, f.PolygonWorld.Length);
        Assert.Equal(("area-pond", "lake"), f.MapWater);
        Assert.Equal(1, s.FloorPlanCount);

        var st = Assert.Single(s.Stairs);
        Assert.Equal((0, 0, 1, 180.0, 1.2, 3.0, 4, 0.3, 1.0),
                     (st.Id, st.FromLevel, st.ToLevel, st.DirDeg, st.RunM, st.RiseM, st.Steps, st.TreadM, st.WidthM));
        Pt(st.At, 2, -1.5);
        Assert.Equal((2.0, 0.01, -0.9), (st.Foot.X, st.Foot.Y, st.Foot.Z));
        Assert.Equal((2.0, 3.03, -3.1), (st.Head.X, st.Head.Y, st.Head.Z));
        Assert.Equal(4, st.Footprint.Length);
        Pt(st.Footprint[2], 2.5, -2.7);

        var m = Assert.Single(s.Markers);
        Assert.Equal(1, s.MarkerCount);
        Assert.Equal(("r-ground", "m-chair", "seat", "Chair", 1, 0.45, "prop"),
                     (m.RoomId, m.Id, m.Group, m.Label, m.Capacity, m.YWorld, m.Source));
        Pt(m.AtWorld, 2, -1);
        Pt(Assert.Single(m.Slots), 2, -1);
        Assert.Equal(0.42, m.RootOffset);
        Assert.Equal(90, m.Facing);
        Assert.Null(m.Tilt);
        Assert.Null(m.Roll);
        Pt(m.Anchor!.Value, 2, -1);
        Assert.False(m.Diorama);

        var d = Assert.Single(s.Doorways);
        Assert.Equal((0, "door", 1.0, 2.1, 0.0, true, true), (d.Level, d.Type, d.WidthM, d.HeightM, d.BaseY, d.Outside, d.Hull));
        Pt(d.AtWorld, -5, -1.5);
        Pt(d.Along, 0, -1);
        Pt(d.OutwardNormal!.Value, -1, 0);
        Assert.Equal(new[] { "r-ground" }, d.Rooms);

        var c = Assert.Single(s.Corridors);
        Assert.Equal(("__floor__1", 1), (c.RoomId, c.Level));
        Pt(c.Anchor, 0, -2.5);
        Assert.Equal(4, c.Outline.Length);
    }

    [Fact]
    public void ProblemsAndBoundaryOpenings()
    {
        var s = Load("s3c/scene_loc-open.json");
        Assert.Equal(2, s.Problems.Count);
        var a = s.Problems[0];
        Assert.Equal(("no_entrance", "r-up", "Room r-up has no entrance", 1, "editor"), (a.Kind, a.RoomId, a.Message, a.Level!.Value, a.Scope));
        var b = s.Problems[1];
        Assert.Equal((2, ""), (b.RoomCount!.Value, b.Scope));
        Assert.Equal(new[] { "r-up", "r-x" }, b.RoomIds);
        Assert.Equal(new[] { 1, 2 }, b.Levels);
        Assert.Null(b.Level);

        var o = Assert.Single(s.BoundaryOpenings);
        Assert.Equal((2, 2.0, "gate", ""), (o.Edge, o.WidthM, o.Type, o.RoomId));
        Pt(o.AtWorld, 0, 5);
        Pt(o.Inward, 0, -1);
    }

    [Fact]
    public void ModelFieldsBeyondPlacement()
    {
        var s = Load("s3c/scene_loc-open.json");
        var door = s.Models.Single(m => m.Id == "door:s3c0001");
        Assert.Equal((0, "left", -1), (door.Door!.Opening, door.Door.Hinge, door.Door.Swing));
        var leaf = door.Door.LeafBox!.Value;
        Assert.Equal((0.0, 0.0, -0.025, 1.0, 2.1, 0.025), (leaf.Min.X, leaf.Min.Y, leaf.Min.Z, leaf.Max.X, leaf.Max.Y, leaf.Max.Z));
        Assert.Equal("fit", door.Measure);
        Assert.Null(door.Light);

        var lamp = s.Models.Single(m => m.Id == "lamp");
        Assert.True(lamp.Walkable);
        Assert.True(lamp.WidthEstimated);
        Assert.Equal((0.0, 0.0, 1.0, 2.0), (lamp.CutPlane!.Normal.X, lamp.CutPlane.Normal.Y, lamp.CutPlane.Normal.Z, lamp.CutPlane.Constant));
        Assert.Equal("glass", lamp.Slots["shade"].Preset);
        Assert.Equal("", lamp.Slots["shade"].Image);
        Assert.Equal("/assets/pictures/p1.png", lamp.Slots["picture"].Image);
        var l = lamp.Light!;
        Assert.Equal(("#ffcc88", 2.0, 6.0, "candle", "night", 0.3, 1.1), (l.Color, l.Intensity, l.RangeM, l.Flicker, l.When, l.GlowM, l.HeightM));
        Pt(l.Offset, 0, 0.2);
        var sf = lamp.Surface!;
        Assert.Equal((0.5, 3, 2), (sf.Step, sf.Cols, sf.Rows));
        Pt(sf.Origin, -0.5, -0.5);
        Assert.Equal(new double?[] { 10, 20, null, 30, 40, 50 }, sf.Values);
        Assert.Equal((1.0, 1.0, 1.0), (sf.ExtentSnapped.X, sf.ExtentSnapped.Y, sf.ExtentSnapped.Z));
        Assert.Equal((-0.5, 0.0, -0.5), (sf.BoxMin.X, sf.BoxMin.Y, sf.BoxMin.Z));
        var w = Assert.Single(lamp.Water);
        Assert.Equal((0.8, 0.6, "#3b6b8a", 0.7, 1.2), (w.Y, w.BedY, w.Tint, w.Opacity, w.SwimFromM));
        Assert.Equal(3, w.Outline.Length);
        Assert.Empty(w.Holes);
        Assert.Equal((1.0, 1.0, 1.0), (lamp.LeafBox!.Value.Max.X, lamp.LeafBox.Value.Max.Y, lamp.LeafBox.Value.Max.Z));
        Assert.Null(lamp.WalkYWorld);

        var room = s.Models.Single(m => m.Role == "room");
        Assert.Equal(4, room.ClipOutline.Length);
        Pt(room.ClipOutline[3], -5, 0);
        Assert.Equal(0.05, room.WalkYWorld);

        var building = s.Models.Single(m => m.Role == "building");
        Assert.Equal(0, building.WalkYWorld);
        Assert.True(building.PlanHull);
        Assert.Single(building.Cutouts);
        Assert.Empty(building.ClipOutline);
        Assert.Null(building.Surface);
        Assert.Empty(building.Slots);
        Assert.Empty(building.Water);
    }

    [Fact]
    public void AbsentBlocksAreEmpty()
    {
        // The S1a house names levels, storey_m and figures, and leaves every list empty / every optional out.
        var s = Load("scene_loc-house.json");
        Assert.Equal("fixture-house", s.Signature);
        Assert.Equal(14, s.ExtentM);
        Assert.Equal(new[] { (0, 0.0) }, s.Levels.Select(l => (l.Level, l.FloorY)));
        Assert.Empty(s.Stairs);
        Assert.Empty(s.Markers);
        Assert.Empty(s.Doorways);
        Assert.Empty(s.Corridors);
        Assert.Empty(s.Problems);
        Assert.Empty(s.BoundaryOpenings);
        Assert.Empty(s.FloorPlan);
        Assert.Null(s.Boundary);
        Assert.Empty(s.Rooms);
        var crate = s.Models.Single(m => m.Id == "crate");
        Assert.Null(crate.Door);
        Assert.Null(crate.CutPlane);
        Assert.Null(crate.WalkYWorld);
        Assert.False(crate.Walkable);
    }

    [Fact]
    public void MalformedEntriesDoNotThrow()
    {
        using var doc = JsonDocument.Parse("""
            {"levels":[5,{"level":2}],"stairs":[null],"markers":["x",{"id":"m"}],"doorways":[{}],
             "rooms":[{"room_id":"r","overlay":7,"ambience":{"tint":3},"openings":[1,{}]}],
             "models":[{"role":"prop","id":"p","surface":{"values":[1,"a",null]},"door":{},"slots":{"a":3,"b":{}}}]}
            """);
        var s = ScenePayload.Parse(doc.RootElement);
        Assert.Equal(new[] { (2, 0.0) }, s.Levels.Select(l => (l.Level, l.FloorY)));
        Assert.Empty(s.Stairs);
        Assert.Equal("m", Assert.Single(s.Markers).Id);
        Assert.Equal("door", Assert.Single(s.Doorways).Type);   // an absent type reads as a door
        var r = Assert.Single(s.Rooms);
        Assert.Null(r.Overlay);
        Assert.Equal(1, r.Ambience!.Daylight);                   // ambienceTarget: daylight ?? 1
        Assert.Single(r.Openings);
        var p = Assert.Single(s.Models);
        Assert.Equal(new double?[] { 1, null, null }, p.Surface!.Values);
        Assert.Equal(1, p.Door!.Swing);
        Assert.Equal(new[] { "b" }, p.Slots.Keys);
    }
}
