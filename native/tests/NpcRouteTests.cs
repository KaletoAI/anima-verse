using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
using AnimaNative.Figures;
using AnimaNative.Overview;
using AnimaNative.Scatter;
using AnimaNative.Scene;
using AnimaNative.Water;
using AnimaNative.World;
using Xunit;

namespace AnimaNative.Tests;

/// <summary>
/// The door routing of a room change (main.ts <c>computeNpcPlacements</c>, <see cref="NpcRoute"/>) and the walking word of
/// the ground (ground.ts <c>typeAt</c>, <see cref="TerrainPayload.TypeAt"/>), by hand. Every lookup inside is
/// vector-checked (doors, lift stops: npc_ground.json / npc_walk.json; the stair chain: StairsTests); these cases pin
/// the ORDER of the stations and the frame they are turned into.
/// </summary>
public class NpcRouteTests
{
    private static SceneDoorway Door(int level, double x, double z, double baseY, bool outside, params string[] rooms)
        => SceneJson.Doorway(JsonDocument.Parse(JsonSerializer.Serialize(new
        {
            level, at_world = new[] { x, z }, along = new[] { 1.0, 0.0 }, width_m = 1.0, base_y = baseY, rooms, outside,
        })).RootElement);

    /// <summary>
    /// The tile: centre (100, 4, 200). r1 (Hall) and r2 share a wall at (2, 0); r1's outside door (−1, −2), r2's (3, −2),
    /// both at base 0.1; "up" on storey 1 has its door (0, 2) at base 2.3. The flight foot (98, 4.01, 201) → head
    /// (98, 7.01, 205); the lift stops on storeys 0 and 1 at (102, 4, 201) / (102, 7, 201).
    /// </summary>
    private static RouteTile Tile(double yaw = 0, bool stairs = true, bool lift = true)
    {
        var foot = new StairLanding { Level = 0, Pos = new Vec3(98, 4.01, 201) };
        var head = new StairLanding { Level = 1, Pos = new Vec3(98, 7.01, 205) };
        var levels = new Dictionary<string, int> { ["r1"] = 0, ["Hall"] = 0, ["r2"] = 0, ["up"] = 1 };
        return new RouteTile
        {
            Frame = new TileFrame(new Vec3(100, 4, 200), yaw),
            Doorways = new[]
            {
                Door(0, 2, 0, 0.1, false, "r1", "r2"), Door(0, -1, -2, 0.1, true, "r1"), Door(0, 3, -2, 0.1, true, "r2"),
                Door(1, 0, 2, 2.3, true, "up"),
            },
            RoomIdOf = raw => raw switch { "Hall" or "r1" => "r1", "r2" => "r2", "up" => "up", _ => null },
            RoomLevels = levels,
            Stairs = stairs
                ? new[] { new StairLink { Id = 1, Foot = foot, Head = head, At = new P2(98, 201.5), Dir = new P2(0, 1), RunM = 3, WidthM = 1, Footprint = Array.Empty<P2>() } }
                : Array.Empty<StairLink>(),
            LiftStops = lift ? new Dictionary<int, Vec3> { [0] = new(102, 4, 201), [1] = new(102, 7, 201) } : new Dictionary<int, Vec3>(),
        };
    }

    private static void Stops(NpcRoutePlan plan, params (double X, double Y, double Z)[] want)
    {
        Assert.Equal(want.Length, plan.Via.Count);
        for (int i = 0; i < want.Length; i++)
        {
            Assert.Equal(want[i].X, plan.Via[i].X, 9);
            Assert.Equal(want[i].Y, plan.Via[i].Y, 9);
            Assert.Equal(want[i].Z, plan.Via[i].Z, 9);
        }
    }

    [Fact]
    public void SharedWallIsTheWholeRoute()
    {
        // doorwayBetween(r1, r2) = (2, 0) at base 0.1 → world (102, 4.1, 200); the room NAME resolves to its id.
        var plan = NpcRoute.Plan(Tile(), "Hall", "r2");
        Stops(plan, (102, 4.1, 200));
        Assert.Empty(plan.Legs);
    }

    [Fact]
    public void LeavingForTheGroundTakesTheOutsideDoor()
    {
        Stops(NpcRoute.Plan(Tile(), "r1", null), (99, 4.1, 198));          // leave only; the ground has no door
        Stops(NpcRoute.Plan(Tile(), null, "r2"), (103, 4.1, 198));         // enter only
        Assert.Empty(NpcRoute.Plan(Tile(), null, null).Via);
    }

    [Fact]
    public void StoreyChangeClimbsStairsFirst()
    {
        // leave r1 (99, 4.1, 198), the flight's foot then head, enter "up" at (0, 2) base 2.3 → (100, 6.3, 202).
        var plan = NpcRoute.Plan(Tile(), "r1", "up");
        Stops(plan, (99, 4.1, 198), (98, 4.01, 201), (98, 7.01, 205), (100, 6.3, 202));
        Assert.Single(plan.Legs);
        Assert.Equal(0, plan.Legs[0].Start.Level);
        // …downwards the same flight from its head, and the lift is never asked while stairs connect.
        var down = NpcRoute.Plan(Tile(), "up", "r2");
        Stops(down, (100, 6.3, 202), (98, 7.01, 205), (98, 4.01, 201), (103, 4.1, 198));
        Assert.Equal(1, down.Legs[0].Start.Level);
    }

    [Fact]
    public void WithoutStairsTheLiftStops()
    {
        var plan = NpcRoute.Plan(Tile(stairs: false), "r1", "up");
        Stops(plan, (99, 4.1, 198), (102, 4, 201), (102, 7, 201), (100, 6.3, 202));
        Assert.Empty(plan.Legs);
        // Neither stairs nor a lift: out of one door and in at the other.
        Stops(NpcRoute.Plan(Tile(stairs: false, lift: false), "r1", "up"), (99, 4.1, 198), (100, 6.3, 202));
    }

    [Fact]
    public void DoorStopsAreTurnedWithTheTile()
    {
        // yaw π/2: x = cx + lz, z = cz − lx → the shared wall (2, 0) stands at (100, 198).
        var plan = NpcRoute.Plan(Tile(yaw: Math.PI / 2), "r1", "r2");
        Stops(plan, (100, 4.1, 198));
    }

    [Fact]
    public void TypeAtReadsTheTopmostAreaAndTheCatalog()
    {
        var t = TerrainPayload.Parse(JsonDocument.Parse("""
        {
          "default_kind": "grass",
          "types": [
            {"kind": "grass", "speed_factor": 1, "meta": {}},
            {"kind": "Lake", "speed_factor": 0.4, "meta": {"movement": "swim", "move_sink_m": "0.35", "idle_sink_m": 1.3, "swim_from_m": 0}},
            {"kind": "bog", "speed_factor": "x", "meta": {"movement": "walk", "move_sink_m": 0.2}},
            {"kind": "odd", "meta": {"movement": "fly", "move_sink_m": -1}}
          ],
          "areas": [
            {"id": "a", "kind": "lake", "polygon": [[0, 0], [10, 0], [10, 10], [0, 10]]},
            {"id": "b", "kind": "bog", "polygon": [[5, 5], [10, 5], [10, 10], [5, 10]]}
          ]
        }
        """).RootElement);
        // Outside every area: the default kind, plain walking.
        var plain = t.TypeAt(-5, -5);
        Assert.Equal(("grass", 1.0, "walk_run", 0.0, 0.0, 1.0), (plain.Kind, plain.SpeedFactor, plain.Movement, plain.MoveSinkM, plain.IdleSinkM, plain.SwimFromM));
        // The lake (kind matched case-insensitively): swim, the string sink read with Number(), threshold 0 kept.
        var lake = t.TypeAt(2, 2);
        Assert.Equal(("lake", 0.4, "swim", 0.35, 1.3, 0.0), (lake.Kind, lake.SpeedFactor, lake.Movement, lake.MoveSinkM, lake.IdleSinkM, lake.SwimFromM));
        Assert.Null(lake.WaterLevel);                                       // no water_profile: no mirror
        // The bog painted over it wins: walk, a non-number speed is 1, sinks only for swim → 0.
        var bog = t.TypeAt(7, 7);
        Assert.Equal(("bog", 1.0, "walk", 0.0, 0.0), (bog.Kind, bog.SpeedFactor, bog.Movement, bog.MoveSinkM, bog.IdleSinkM));
        // An unknown movement word walks and runs; a kind without catalog entry likewise.
        Assert.Equal("walk_run", t.TypeOf("odd")!.Movement);
    }

    [Fact]
    public void GroundWordCutsSinksOutsideSwimAndInsideBuiltPlaces()
    {
        var lake = new GroundMove("swim", new GroundSink(0.35, 1.3), 5, 1, 0.4, GroundScope.Wilderness, null);
        // Bed 3: 2 m of water ≥ 1 → swim with the sinks, the mirror 5.
        var w = WalkGround.WordOf(lake, 3).Word;
        Assert.Equal(("swim", 0.35, 1.3, (double?)5), (w.Movement, w.Sink.Move, w.Sink.Idle, w.Water));
        // Bed 4.6: 0.4 m < 1 → waded: walk_run, no sink, no mirror.
        Assert.Equal(("walk_run", (double?)null), (WalkGround.WordOf(lake, 4.6).Word.Movement, WalkGround.WordOf(lake, 4.6).Word.Water));
        // A built place hides the lake altogether.
        var hall = WalkGround.WordOf(lake with { Scope = GroundScope.Built }, 3).Word;
        Assert.Equal(("walk_run", 0.0, (double?)null), (hall.Movement, hall.Sink.Move, hall.Water));
        // A crawl ground keeps its word but never a sink; a prop water region turns any ground into swimming.
        var crawl = WalkGround.WordOf(lake with { Movement = "crawl", Water = null }, 3).Word;
        Assert.Equal(("crawl", 0.0), (crawl.Movement, crawl.Sink.Move));
        var region = WalkGround.WordOf(GroundMove.Plain with { PropWater = new WaterHit(2.5, 1, 0.5) }, 1.2).Word;
        Assert.Equal(("swim", 0.35, (double?)2.5), (region.Movement, region.Sink.Move, region.Water));
        Assert.Equal(GroundScope.Open, WalkGround.SinkScope(GroundMove.Plain with { Scope = GroundScope.Built, PropWater = new WaterHit(2.5, 1, 0.5) }));
    }
}
